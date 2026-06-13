# Open questions for review

Accumulated during autonomous work; each answer unblocks a specific next step.
Most-blocking first.

## 1. Swapper ports — RESOLVED (no export needed; see Resolved)
Solved by brute-forcing the footprint against the existing `Swap Diagonal`
blueprint instead of a belted template: 2-in/2-out, second cell right of flow,
both cells in-back/out-front. `Swap Diagonal` now lifts at 0 unmatched legs.
The remaining swapper-related *open* questions are the simulator's (Q3 shape
convention, and the swapper's exact swap semantics).

## 2. Pass-by mechanic  *(pins the connection rule)*
In tight routing a belt can run *past* a machine without connecting. When a
belt's output points at a machine's **solid (non-port) side**, does the game
always route it as a turn going elsewhere (so a belt never truly dead-ends into a
wall), or can a belt physically butt against a machine face? This sets how strict
the lifter's "a port must agree with the belt leg" rule should be.

## 3. Shape quadrant convention  *(simulator correctness)*
The shape model reads quadrants clockwise from top-right — `(NE, SE, SW, NW)` —
with the west half = `SW + NW`. The diagonal-swap test passes with this, but does
it match the game's shape-code order (e.g. `RuCuSuWu`)? A wrong labeling would
still pass the structural tests yet mislabel parts.

## 4. Stacker stacking semantics — RESOLVED
Primary = bottom, secondary = top, with one empty gap layer between, then gravity
applied. Gravity splits each layer into groups of orthogonally adjacent quadrants
(diagonal pairs NE↔SW, NW↔SE are **not** connected) and drops unsupported groups.
Truncate to 4 layers. Full rules in `docs/machines.md` § Stacking semantics.

## 4b. Painter pipe layer  *(blocks lifting painters)*
Painters consume paint on a separate **pipe** transport layer (`PipeForward`, …)
alongside shape belts, so the lifter needs a pipe routing model (calibrate
pipe Forward/turn/junction in/out sides, like belts) before painters lift. A
clean painter with belts **and** pipes on its I/O would calibrate it.

## 5. Non-1×1/1×4 platform ports — RESOLVED
User provided calibration templates (TEMPLATES/ in the blueprints repo) for all
13 Foundation types. Port slots are `BeltPortReceiverInternalVariant` and are
**bidirectional** — the same physical slot becomes a source (Receiver) or sink
(Sender) depending on the entity placed. Ground-truth port positions added to
`platforms.json` as `[x, y, rotation]` lists. Foundation_1x2 geometry corrected
(was modeled as portrait, actually landscape). Eight new Foundation types added:
1x3, 2x3, 3x3, C5 (cross), L3 (short L), L4 (long L), S4, T4.

## 6. Rotation direction sanity check
The interpreter maps `RotatorOneQuad` → clockwise, `RotatorOneQuadCCW` →
counter-clockwise. Tests pass, but confirm that matches in-game (the building
icons should settle it).

## 7. Launcher/catcher routing model  *(blocks WP-K)*
Belt launchers and catchers act as same-layer vias: a launcher sends items over
other belts to a catcher, allowing routes to cross without conflicting. Multiple
launched belts can even share a lane (2–3 flights over the same ground cell).
**Entity types identified** (2026-06-09, from `identifiers.json`):
`BeltPortSenderVariant` (launcher) and `BeltPortReceiverVariant` (catcher) —
the placeable siblings of the platform-edge port slots (`*InternalVariant`).
**Empirical answers mined from `UNFINISHED Half Splitter.spz2bp`
(2026-06-09, 145 interior hop pairs analyzed):**
- Pairing is **positional**: each sender pairs with the first receiver along
  its facing ray **with the same rotation** — no pairing field. All 145 pairs
  resolve under direction convention R=0→+X, R=1→+Y, R=2→−X, R=3→−Y.
- Interior hop endpoints use the **same entity types as platform-edge port
  slots** (`BeltPortSenderInternalVariant`/`BeltPortReceiverInternalVariant`);
  position (border ring vs interior) is the only distinguisher. The lifter
  must learn this — it currently classifies all 338 as platform IO.
- Flight distances observed: 1–5 cells.
- Flights pass over belts and over other hop endpoints; **never over machine
  cells** (0 of 280 flight cells in the sample).
- Up to **3 flights** stack over one ground cell.

**Confirmed (2026-06-11, user) — BLOCKING, see generator-spec.md §2a "Gate-2
blockers":** the in-game launcher/catcher range is **1–4 blank (flight) tiles
between** sender and receiver. In `pathfinder.py` terms (`hdist` = sender-cell
to receiver-cell distance, `range(2, hop_range + 1)`), `blank_tiles =
hdist - 1`, so the legal range is `hdist ∈ [2, 5]` ⇒ **`hop_range` must be ≤
5**. Gate 2 (`test_synth_half_splitter_2x4`) uses `hop_range=8`, which
violates this — resolves the "is 5 the hard max" question below (yes, modulo
reconciling the gap-vs-span off-by-one against the "1–5 cells" empirical
figure above).

**Still open (in-game checks, no fixture needed for the rest):**
- Is flying over a machine cell actually illegal, or merely unused here?
- Is 3 the flight-lane cap, or just the observed max?
- Must the catcher's rotation equal the sender's (all 145 match here), or is
  that a builder habit?

## 9. Density constraint scaling for 16-lane Half Splitter
The `place.py` density constraint counts **all** source→machine edges crossing
each x-bucket globally, then requires the channel height (band_lo - input_y - 1)
to exceed the max count. With source group-pinning, each port group contributes
at most `lanes_per_group × cutters_per_lane` edges to the buckets near that
group's x-region. For 4 lanes × 4 groups = 1 source/group, max density = 4 and
machines land at y=8 (near sinks). For 16 lanes × 4 groups = 4 sources/group,
max density = 16 and machines get pushed to y=19 again.

**Design question:** should the density constraint be:
- **(a) Per-group:** only count edges from sources whose x-interval actually
  overlaps the bucket (already partially done by `_covers_bucket`, but the
  channel height is a single global variable — the bottleneck);
- **(b) Softened:** convert from hard constraint to penalty in the objective,
  letting the solver trade density overflows against wire length; or
- **(c) Multi-channel:** model per-group channel heights (each source-group's
  fan-out uses a different vertical slice of the routing area)?

Not blocking 4-lane work. Blocks the 16-lane Half Splitter gate.

## 8. Lift calibration — RESOLVED (no fixture needed; see Resolved)
Calibrated empirically from the 12-to-12 Balancer (46 lifts, 3 floors) — same
approach that bypassed Q7 for WP-K. All 16 variants verified at 0 unmatched
legs.

---

## Resolved (for the record)
- Shapes have absolute world orientation; cut/swap/half-destroy act on absolute
  west/east halves; only rotators re-orient.
- Cutter 1-in/2-out, swapper 2-in/2-out, half-destroyer 1-in/1-out; in ports on
  the left (W), out on the right (E).
- The cutter's apparent "2 inputs" was belts routing *past* output-only tiles.
- Swappers swap west halves including empty parts (the diagonal trick).
- **Cutter encoding (Q1, was the blocker):** a cutter is **one entity + an
  output-only second cell**, *not* a `Default`+`Mirrored` tile pair. The second
  cell is right of flow (`Default`) / left (`Mirrored`); one input on the anchor
  back, two outputs on the fronts. The dense `12→24` blueprint lifts at 0
  unmatched legs (16 cutters × in-1/out-2). Modeled in `lift._machine_footprint`;
  the disproven "tile pair" note in `machines.md` is corrected.
- **Stacker structure:** 1×1, 2-in/1-out. Primary input on the anchor's back
  (same floor); **secondary input from the floor above** (the L+1 belt's output
  lands on the anchor). Output: front (`StackerStraight`) / right (bent
  `StackerDefault`) / left (`…Mirrored`). The first machine with a **cross-floor**
  connection — lifting it needs vertical-port support (not yet built).
- **Swapper ports (Q1):** 2-in/2-out, one entity + a second cell to the right of
  flow (Default) / left (Mirrored), both cells in-back/out-front. Found **without
  a belted template** — brute-forced footprint hypotheses against the existing
  `Swap Diagonal` blueprint; the winning model lifts it at 0 unmatched legs (32
  swappers × in-2/out-2), so the diagonal extractor's topology is lifted. Modeled
  in `lift._machine_footprint`; fixture `data/reference/swap_diagonal.spz2bp`.
- **Lift calibration (Q8):** all 16 lift variants (`Lift{1,2}{Up,Down}
  {Forward,Backward,Left}[Mirrored]InternalVariant`) calibrated empirically from
  the 12-to-12 Balancer (`data/reference/balancer_12_to_12.spz2bp`, 46 lifts, 3
  floors). Input always from back at entity's own layer; output at L±delta in the
  named exit direction (delta = 1 for Lift1, 2 for Lift2; positive for Up,
  negative for Down). Exit directions at R=0: Forward→E, Backward→W, Left→S,
  LeftMirrored→N. `Lift2*` spans 3 layers (input + blocker + output). All floors
  at 0 unmatched legs. No user fixture export was needed.
