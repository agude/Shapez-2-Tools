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
Remaining calibration questions:
- How is the pair encoded — is it positional (sender throws along its facing
  direction to the first receiver in line), or is there a pairing field?
- What is the maximum flight distance? Is it fixed or variable?
- Can a launcher/catcher pair cross a machine cell, or only belt cells?
- How many flight lanes can stack over one ground cell (2? 3?)?

**Requested fixture:** a small *closed* blueprint (ports on every lane) with
one launcher→catcher hop flying over a perpendicular belt — ideally two
variants at different flight distances. That calibrates pairing + range and
gives the lift-side test (`test_hop_fixture_lifts_clean`, WP-K).

## 8. Lift calibration  *(blocks WP-J)*
Lift entities move items between floors; the router needs them as inter-layer
edges. Variants exist in `identifiers.json`:
`Lift1{Up,Down}{Forward,Backward,Left}InternalVariant` (+ `LeftMirrored`),
plus `Lift2*` two-layer versions. Unknowns:
- In/out sides per variant × R, and which cell(s) a lift occupies — hypothesis:
  a `Lift1UpForward` at `(x, y, L)` takes input from its back at layer L and
  outputs at layer L+1 in its facing direction, occupying the cell on both
  layers (Forward/Backward/Left name the exit direction relative to entry).
- Does `Lift2*` span L0→L2 directly through one cell on all three layers?

**Requested fixture:** a small *closed* blueprint where one belt lane goes up
one floor via a lift, runs a few cells, and comes back down — one copy using
Forward variants, one using Left/Backward if convenient. That calibrates the
in/out table and gives the lift-side test (`test_lift_fixture_lifts_clean`,
WP-J).

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
