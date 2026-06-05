# Blueprint Synthesis — Plan

**Status:** Draft, updated 2026-06-05. **Diagonal swapper synthesis landed (2 pairs on 1×1).**

**North star:** synthesize *dense, compact, single-platform* blueprints from a
functional spec — e.g. "on a 2×8 full belt, extract both diagonals and pin the
upper-left diagonal to the 4 left outputs and the upper-right to the 4 right."
These are hard to route by hand and are what make factories compact. That is the
product.

**Easy platforms are the test harness, not the goal.** A "rotate 12 belts 180°"
is a 10-second hand build; here it exists only as an end-to-end test and a
regression floor. The hard target is intra-platform **place-and-route**.

---

## 0. Status & handoff (2026-06-05)

**Built and green** (150 tests pass, 3 xfail, `just test`, ruff clean):
- `blueprint.py` — faithful `.spz2bp` codec.
- `generator.py` — tile-replication generator: builds the rotator family
  (180/cw/ccw × 1×1/1×4) from one lifted tile. `Entity`, lift/stamp/build,
  functional `diff`, per-floor text `render`. 1×4 platforms get font-rendered
  silk-screen labels (direction text as trash-block pixel art, one character
  per gap between belt units, centered) plus a name-tag `Label` entity.
- `font.py` — pre-extracted 10×14 mono bitmap font (95 printable ASCII glyphs,
  stored as row bitmasks; no Pillow runtime dependency). `silkscreen()` renders
  text as `Trash` entities at a given origin and scale.
- `data/platforms.json` — seam-aware platform geometry + ground-truth port
  positions for all 13 Foundation types (calibrated from templates).
- `lift.py` — recovers a machine-level netlist from a placed blueprint. Belt
  direction is calibrated for **all** routing variants (belts + every
  splitter/merger); **machines expand to multi-cell footprints**
  (`_machine_footprint`). `trace_layer`, `unmatched_legs`, `edge_kinds`. **Lifts
  the rotator family + half-destroyer + the cutter at 0 unmatched legs.**
  Includes `isomorphic(a, b)` for structural netlist comparison (WP-A done).
- `shapes.py` — shape model + absolute ops (rotate / cut / half-destroy /
  swap-west). Convention: quadrants `(NE, SE, SW, NW)`, west = `SW+NW`.
- `interpret.py` — pushes shapes through a lifted netlist, **per cell** via the
  netlist's `port_edges`, so multi-port machines work. Verified: rotators +
  half-destroyer on every lane (quarter + full belt's 48), the **cutter** (1→2,
  east/west), and the **swapper** (2→2) including the **diagonal trick**
  (north-only + south-only in → the two diagonals out).
- `validate.py` — physical validator (WP-B done). Checks overlap, dangling legs,
  off-grid placement. Corpus sweep passes on all closed fixtures.
- `route.py` — junction-aware A* router (WP-C done for single-cell machines).
  `reroute_with_junctions` strips belts from a blueprint and re-routes via
  sequential A* with obstacle marking. Round-trips through lift for all
  single-cell fixtures (rotator family × 6, half-destroyer). Handles 1→2, 1→3,
  2→1, 3→1 fan patterns with correct junction placement near machine clusters.
  Now routes at **cell granularity** off `netlist.port_edges` (was anchor-level),
  so a multi-cell machine's several ports route as distinct ports — a cutter's
  two outputs are two 1→1 routes, not a bogus 1→2 splitter (`_node_cell_ports`).
  **≥4-way fans** chain (one junction cell holds ≤3 legs): fan-out uses a
  deterministic splitter comb (`_route_split_chain`, dsts spread along the flow
  axis); fan-in uses a collision-free merger staircase (`_route_merge_chain`,
  perpendicular-spread sources folded nearest-trunk-first). Both are covered by
  spacious synthetic tests (`TestMultiCellRouting`). **Multi-cell corpus
  round-trip (cutter, swapper) is the remaining gap** (2 xfail), and the blocker
  is now precisely understood: the corpus packs mergers in **2D in tight space**
  (a sink can sit ~2 cells from its four sources), where a linear staircase has
  no room and bails, and greedy sequential A* congests. Closing it needs
  **space-aware routing that co-decides merger placement** — i.e. WP-C routing
  blended with WP-D placement, not a deterministic comb. Cutter lifts back to
  ~38/66 edges; the missing ones are the tight 4-way fan-ins/outs. Adjacent-skip
  fix: when a splitter/merger is adjacent to its source/sink, the trunk/tail A*
  is skipped (the junction connects directly; the start cell would coincide with
  the already-placed obstacle). **Conditional outside-in fan-out ordering**
  (`_perp_reach`): when max source→destination Manhattan ≤ 5, fan-out groups are
  processed widest-perpendicular-reach first so inner fans' branch belts don't
  block outer fans' trunks; when machines are far (long trunks), the default
  dict order is kept because outer trunks would cross inner territory.
  **`route_astar` overlap fix**: the `start == end` shortcut now checks the
  obstacle set before placing a belt, preventing entity overlaps that previously
  corrupted the lift.
- `place.py` — CP-SAT placement (WP-D done for rotator quarter + multi-cell
  machines). OR-Tools CP-SAT solver assigns `(x, y, rotation)` to machines given
  an abstract netlist (graph structure only, no coordinates) and a platform.
  Constraints: no overlap, interior bounds, rotation facing toward connected
  nodes, fan-out groups at same y / adjacent x / ordered by source x, sink port
  ordering matched to source flow, **2-cell port-row margin**, **2-cell
  inter-group x-gap**, **y-stagger** (edge groups in x-order placed one row
  closer to sources than inner neighbours, ≤ 1 row apart). **Multi-cell
  machines** (swapper, cutter): second-cell position via `add_element` on
  rotation-indexed offset tables; both cells in AllDifferent + bounds; second-cell
  wire length in objective (keeps both cells near connected ports); proximity-based
  port assignment in `_build_netlist` (`_assign_ports`); BFS-based sink ordering
  (`_trace_all_sinks`) handles multi-input machines correctly. Routes **16/16**
  rotator edges and **8/8** swapper edges (4 srcs → 2 swappers → 4 sinks).
  `abstract_netlist(nl)` strips coordinates from a lifted netlist for the solver.
  **The placer is scaffolding** — machine placement is often a human design
  decision; the product is the router. The placer validates the full pipeline
  (abstract → place → route → verify) and will improve as the router matures.
- `synth.py` — spec-driven synthesis (WP-E). `Spec(op, platform, throughput)`
  where `op` is a single operation or a tuple of operations forming a **series
  chain**: each lane's source feeds `throughput` parallel paths, each path passing
  through every stage in order, then fan-in to the sink. `_lower(abstract,
  platform)` runs the generic pipeline (any abstract netlist → place → route →
  blueprint). Verified: single-op rotate-180/cw/ccw on 1×1 quarter (isomorphic
  to oracles, 16/16 edges); half-destroy (validates + interprets at throughput=2);
  series chains (2×CW = 180°, 3×CCW = CW, both validate + interpret correctly).
  Multi-cell: 2-swapper abstract netlists lower to valid blueprints that interpret
  correctly (placement + routing + port assignment verified end-to-end).
  **Diagonal trick synthesis:** `DiagonalSpec(pairs, platform)` generates the
  paired north/south → swapper → diagonal topology; `synthesize_diagonal()`
  lowers it through the full pipeline. Verified on 1×1 with 2 pairs: 8/8 edges,
  validates, and interprets to the correct diagonals (`Ru--Ru--` / `--Ru--Ru`).
  CLI: `synth swap_diagonal [--pairs N]`. Scaling to 4 pairs needs a platform
  with 8 ports (Foundation_2x2, port calibration done — Q5 resolved).
  **26 synth tests green, 1 xfail (150 total, 3 xfail).**
- CLI: `gen`, `diff`, `show`, `lift`, `viz`, `place`, `synth`. `synth` synthesizes
  a blueprint from a spec (e.g. `synth rotate_180` or `synth rotate_cw,rotate_cw`).
  `viz` renders a blueprint as HTML/SVG (belts as directional lines,
  machines/ports as filled rectangles, failed edges as dashed red overlays;
  `--open` launches a browser). `place` runs the full abstract→place→route
  pipeline on a blueprint and writes the result. `data/reference/` holds oracle
  fixtures and `*_font.spz2bp` copies with font-based silk screening for
  comparison.

**WP-A and WP-B: DONE.** Netlist isomorphism via networkx graph comparison; physical
validator with corpus sweep. Both green.

**WP-C (routing): DONE for single-cell machines + isolated wide fans; corpus
multi-cell round-trip still xfail.** The router now works at **cell granularity**
off `netlist.port_edges`, so a multi-cell machine's ports route independently
(`_node_cell_ports`). Junction placement rules (≤3-way fans, single junction
cell):
- **Fan-in (N→1):** merger one cell from the "straight" source; turned sources
  approach from perpendicular via A*.
- **Fan-out (1→N):** splitter one cell from the "straight" destination; trunk
  routes from source via A*.
- **2-way fans:** pick the endpoint closest to the far side on the perpendicular
  axis (keeps trunk along the flow axis, avoids trunk/branch conflicts).
- **3-way fans:** pick the median endpoint so branches spread to both sides
  (`Splitter1To3` / `Merger3To1`).
- **≥4-way fans** chain (a junction cell holds ≤3 legs): fan-out = a splitter
  comb (`_route_split_chain`, dsts spread along the flow axis); fan-in = a
  collision-free merger staircase (`_route_merge_chain`, perpendicular-spread
  sources folded nearest-trunk-first). Covered by `TestMultiCellRouting`.

Verified: parametrized round-trip over 7 single-cell fixtures (strip → reroute →
lift ≅ original) + the wide-fan unit tests. **The 2 multi-cell fixtures
(cutter_12_to_24, swap_diagonal) remain xfail.** The blocker, now precise: the
multi-cell *port* problem is solved (cutter outputs route as distinct ports), but
the corpus packs mergers in **2D in tight space** — a sink can sit ~2 cells from
its four sources, where a linear staircase has no room (it bails) and greedy
sequential A* congests. The chains handle *spacious* wide fans (the synthetic
tests); the *tight* corpus fans need **space-aware routing that co-decides merger
placement** (WP-C routing blended with WP-D placement). Cutter currently lifts
back to ~38/66 edges.

**Cutter + swapper: SOLVED (the cutter was the blocker).** Machines now expand to
footprints (`_machine_footprint`); each is one entity + a second cell to the
right of flow (Default) / left (Mirrored):
- **Cutter** (1-in/2-out): second cell output-only — pass-by belts don't connect.
  Dense `12→24` lifts at **0 unmatched legs** (16 cutters × in-1/out-2).
- **Swapper** (2-in/2-out): second cell mirrors the anchor. Determined **without a
  belted template** — brute-forced against `Swap Diagonal`, which lifts at **0
  unmatched legs** (32 swappers × in-2/out-2). So the **diagonal extractor's
  topology is lifted** (the north-star demo, structurally).

`tests/test_lift.py::TestCutter`/`TestSwapper`. See `docs/machines.md`,
`QUESTIONS.md` Q1.

**Rung 2 (interpret) — multi-port done; full-blueprint drive remaining.** The
interpreter is now port-aware (`Node.rotation`, `Netlist.port_edges`, per-cell
propagation) and the cutter/swapper ops + the diagonal trick are verified on
hand-built netlists (`tests/test_interpret.py::TestMultiPort`). What's *not* yet
done: driving the **whole** `swap_diagonal` blueprint end-to-end. Its sinks gather
several machines through throughput mergers, so it only computes the diagonals
under its **intended input pattern** (specific north-feed / south-feed sources) —
feeding all sources one shape makes the gather points see different shapes (the
interpreter correctly refuses). Next: identify which source ports are which feed
(port labelling / structural analysis), then assert the diagonals fall out of the
real blueprint.

**Critical path — complete through WP-E.** ~~WP-A~~ ✓ → ~~WP-B~~ ✓ →
~~WP-C~~ ✓ (single-cell + cell-level multi-cell ports + spacious wide fans) →
~~**WP-D placement**~~ ✓ (rotator quarter 16/16) → ~~**WP-E synthesize**~~ ✓
(single-op platforms). `synth.py` runs the full pipeline from a `Spec(op,
platform, throughput)`: spec → abstract netlist → place → route → blueprint.
Verified: rotate-180/cw/ccw on 1×1 quarter (**isomorphic to oracles**, 16/16
edges each), half-destroy on 1×1 (validates + interprets correctly at
throughput=2). Limitation: the router can't handle 1→3 fan-out in tight space
(the half-destroyer oracle uses throughput=3; the synthesizer works at
throughput=2). CLI: `just run synth rotate_180 -o out.spz2bp`.

**Remaining gaps:**
- The tight 2D merger packing from WP-C (cutter/swapper xfails) — the placer
  must reserve routing channels for dense fans. The 1→3 fan-out limitation for
  the half-destroyer is the same underlying issue.
- **The diagonal extractor** (north-star demo): `DiagonalSpec` +
  `synthesize_diagonal()` landed for 2 pairs on 1×1 (8/8 edges, validates,
  interprets to correct diagonals). Scaling to 4 pairs (the full-belt target)
  needs a platform with 8 ports — Foundation_2x2 is the candidate and is now
  calibrated (Q5 resolved).
- **Platform calibration done (2026-06-05).** User provided 13 empty
  templates (TEMPLATES/ in the blueprints repo) with `BeltPortReceiverInternalVariant`
  on every IO port slot. Port slots are **bidirectional** (Receiver = source,
  Sender = sink). Ground-truth port positions added to `platforms.json` for all
  13 Foundation types; `place.py` reads positions from the `ports` list.
  Foundation_1x2 geometry corrected (was [1,2], now [2,1]). New types:
  Foundation_1x3, 2x3, 3x3, C5 (cross), L3 (short L), L4 (long L), S4, T4.
- **Machine placement is often a human design decision; the product is the
  router.** The placer validates the pipeline and will improve as the router
  matures.
- Machine-type breadth work (stacker WP-F, painter WP-G, full-blueprint sim
  WP-H) blocks nothing on the diagonal extractor — its machines (rotators,
  swappers, belts) are already lifted and simulated.

---

## 1. What we know (verified against the corpus)

### Format & codec
- Envelope `SHAPEZ2-4-<base64(gzip(JSON))>$`; game `V=1137`.
- Two-level nesting: Island `BP.Entries` = platforms → each platform `.B.Entries`
  = buildings in platform-local coordinates.
- Building entry `{X, Y, R, L, T}` (R rotation 0–3, L layer 0–2, both omitted when 0).
- **Codec is faithful**: decode→encode reproduces the decompressed JSON
  byte-for-byte (only the gzip mtime differs). No codec work needed.

### Tile-replication family (lane-preserving 1×1→1×4 belt ops)
- Atom = **one floor of a quarter = 80 functional entities**.
- **Floors are exact duplicates** (only a cosmetic `Label` differs on L0); each
  floor is a self-contained 2-D circuit — **no lifts in this family**.
- **Full belt = 4× quarter, exactly**, at coordinate pitch 20. Verified for
  rotators *and* half-destroyers *and* speed-readers (all 4×).
- **CW/CCW = the 180 tile with only the rotator building type swapped**; the only
  per-direction wrapper difference is the island icon
  (`RotatorHalfVariant`/`RotatorOneQuadVariant`/`RotatorOneQuadCCWVariant`).

### Split/merge are belt junctions, not machines
- Shapez has no merger/splitter *building*: a "junction" is just a **belt cell
  with an extra leg** (a T/X). Whether it splits or merges is only the flow
  direction — legs sticking *out* = split (1 in / 2 out, `Splitter1To2L`), legs
  sticking *in* = merge (2 in / 1 out, `Merger2To1L`). Same geometry, reversed flow.
- A junction is general — any in/out split over ≤4 legs. Corpus routing variants:
  merges `2To1L`(+mir) / `3To1` / `TShape`, splits `1To2L`(+mir) / `1To3` / `TShape`,
  1/1 belts `Forward` / `Left`(+mir), plus `BeltFilter`(+mir) (routes by shape — a
  predicate) and `BeltReader`(+mir) (emits a wire signal). ~15 variants.
- They belong to the **routing layer** alongside straight and turn belts.
  Operation nodes in the netlist are only the actual machines (rotators, cutters…).
- **Lift's belt-direction calibration is this table**: each variant × R →
  (input sides, output sides). The tracer must handle arbitrary fan-in/fan-out.

### Belt-direction model (calibrated for the rotator family)
- Convention: **+1 in R = 90° CCW**. Each routing variant has fixed input/output
  sides at R=0, rotated by R (Forward: in=back / out=front; turns: out = one
  perpendicular; junctions: the multi-leg pattern).
- Validated on the rotator quarter: **0 unmatched legs**, and `lift.trace_layer`
  recovers its exact netlist (4 inputs each split to 2 rotators, 8 rotators each
  merge to 1 output) — and the full belt as 4× that. See `lift.py`.
- Calibrated (0 unmatched legs on the rotator quarter *and* the half-destroyer):
  all routing variants — Forward / Left(+mir) / Filter / Reader, `Splitter`
  `1To2L`(+mir)/`1To3`/`TShape`, `Merger` `2To1L`(+mir)/`3To1`/`TShape`, ports,
  rotator, and the **cutter** (one entity + an output-only second cell, 1→2 — the
  dense `12→24` blueprint lifts at 0 unmatched legs). Remaining gap: the swapper
  (2→2), stacker (2→1), and painter (needs a pipe routing layer).

### Shapes have absolute orientation
- A shape's orientation is fixed in **world** space — north is always north.
- Cut / swap / half-destroy act on the **absolute** west/east halves regardless of
  building rotation; rotating those buildings only re-routes belts, not function.
  **Only a Rotator re-orients a shape.**
- So to reach a non-west part you rotate the shape west, apply the op, rotate back
  — which is why extractors are dominated by rotators (they are *addressing*).
- This is a **simulator** fact (Rungs 2/4); it does not affect the belt-topology
  lift (ports still rotate with `R`). Detail in `docs/machines.md`.

### Decoration is per-blueprint signage
- `Trash` spells pixel-art names (e.g. "180"/"CW"/"CCW") on the rotators' L0 —
  ad-hoc, not systematic, and absent from most families.
- **`Trash` is functional in the Trash family.** So decoration detection must be
  **family/position-aware, never type-based** (a current latent bug in
  `DECORATION_TYPES`).

### Platform geometry (seam model) — see `data/platforms.json`
- Each unit is 20×20 bounding / 16×16 buildable (2-cell border). **Joining units
  fills the shared border: +4 cells per internal seam.**
- Interior = `20·units − 4` per axis. Verified: 1×1 = 16×16 (corpus), 1×4 = 76×16
  (M2). Generalizes to any size (2×4 = 76×36, 2×8, …).
- `platforms.json` carries ground-truth `ports` lists (all 13 Foundation types
  calibrated from templates, 2026-06-05). Port slots are bidirectional
  `BeltPortReceiverInternalVariant`; direction is determined by entity type
  (Receiver = source, Sender = sink). 4 ports per exposed unit-edge face.
  Foundation_1x2 geometry corrected (was [1,2], now [2,1]).

### Per-family parametrics (reference)
- Lane-preserving belt ops: **12 in / 12 out** (quarter), **48 / 48** (full belt).
- Lane-changing (cut 12→24), multi-input (stack/swap → 2×4/2×2), and fluid ops
  (painter/crystallizer/miner) have operation-specific port counts and platforms.
- Diagonal extractors are routing-dominated: e.g. `Full Belt Shape to Upper Left
  Diagonal` on a 2×4 is in=48, out=96, with **3456 belts** — ~95% routing.

### Composition
- A composite ("destroy west half **then** rotate 180") is a pipeline of named ops.
- Valid when lane signatures line up (12→12 | 12→12).
- Two lowerings of the same spec: **chain of platforms** (space-belt connected —
  easy) vs **co-placed on one platform** (place-and-route — the goal).

---

## 2. Architecture (the real target)

- **Netlist IR** — a directed dataflow graph. Nodes = operations with typed ports,
  lane signatures, throughput; edges = nets; output ports may be *pinned* to
  specific physical positions. Placement-free.
- **Lowering** — netlist → placement (cell, layer, rotation per building) →
  routing (3-D belts with Forward/Left/Left-Mirrored turn-typing, lifts as vias,
  throughput-aware) → entities → file.
- **Simulator** — push shapes through the netlist (does it compute the spec?) plus
  a physical validator (no overlaps, ports connect, on legal cells).
- Tile-replication is the **degenerate case**: one fixed placement, straight-lane
  routing, lane-preserving. It exercises the whole I/O + verification loop.

---

## 3. The ladder

Your hand-built library is the **oracle at every rung** — it supplies both the
spec library and the measuring stick.

- **Foundation — DONE.** Codec, `Entity` model, functional `diff`, seam-accurate
  geometry, corpus oracle. Tile-replication **M1** (quarter reproduced) and **M2**
  (full belt = 4× quarter, built from the quarter tile) verified.
- **Scaffolding — DESIGNED, not landed.** Single-op `generate_rotator` (180/cw/ccw
  × 1×1/1×4) + `gen`/`diff` CLI verbs; extend the tile family to half-destroyers
  and speed-readers. This is the regression floor, not the product.
- **Rung 1 — Lift (underway).** Decompile a placed blueprint into a netlist by
  tracing the oriented belt graph. All routing variants are calibrated; `lift.py`
  lifts the rotator family and the half-destroyer at 0 unmatched legs (see §1).
  Next: a **machine-definition table** (footprint + ports per type). The generic
  1-in/1-out "straight through" machine model holds only when belts sit on both
  ends; in dense packing it breaks — e.g. a rotator fed by a belt on its east and
  a cutter on its south has no west input at all. Cutters (1×2, 1 in / 2 out) and
  swappers (1×2, 2 in / 2 out) compound this: their belt-facing ports match, but
  the second output and machine-to-machine couplings don't, so downstream
  machines get dangling inputs. Derive footprints + ports per type from the pure
  blueprints by examining *all* neighbours (belts and machines), then the
  extractor lifts.
- **Rung 2 — Simulate.** Shape model + op transforms + physical validator. Makes
  "correct" mean *computes the function*, not *belts connect*. Needed in full only
  at Rung 4 — Rung 3 can defer it via structural validation (see below).
- **Rung 3 — Re-route a known netlist.** Strip the placement off a lifted example;
  have the router reproduce a **valid** (then **compact**) layout; measure against
  the human-optimal original. The first real place-and-route. Validity can be
  checked **structurally** — lift the routed output and assert graph-isomorphism
  back to the input netlist — so the shape simulator is not required here.
- **Rung 4 — Synthesize from spec.** "Extract both diagonals, pin to L/R outputs"
  → netlist → place-and-route. The product.

---

## 4. Acceptance

- Tile cases: functional-entity `diff` against the corpus oracle.
- Netlist cases: simulation equivalence to the spec.
- Routing: physical validity + functional equivalence; **compactness measured
  against the human oracle**.
- Final gate (manual): loads and runs in-game.

---

## 5. Open questions

- Decoration detection: family/position-aware, not type-based.
- Output-port pinning: how the netlist encodes "this result → that physical port".
- Routing objective: fit-first, then compactness; how to measure vs human.
- Icon convention mismatch (`icon:Platforms` used for both quarter and full belt);
  `BinaryVersion` meaning.

---

## 6. Dependencies / build-vs-buy

Guiding principle: **buy the generic search, build the domain.** You cannot buy
Shapez-2 shape/format/belt knowledge; you should not hand-roll a constraint solver.

- **Codec** (gzip/base64/json): stdlib. Built.
- **Netlist graph + isomorphism**: `networkx` (traversal, topo-sort, and
  `is_isomorphic` with a node-type matcher for the round-trip invariants I4/I5).
  Needed from **WP-A**.
- **Shape model + simulator**: in-house (domain-specific to Shapez 2). Survey
  existing community tooling first for a reference implementation (web search was
  rate-limited; revisit).
- **Blueprint lowering / belt turn-typing**: in-house (format-specific).
- **Placement search**: a constraint solver (`OR-Tools` CP-SAT, or SAT/SMT) —
  do not hand-roll. Needed only at Rung 3.
- **Routing (multi-net, 3-D)**: mostly in-house; no clean Python package. A* core
  can lean on `networkx`; CP-SAT may absorb small instances.
- **CLI**: `argparse` (stdlib) now; `typer`/`click` optional later.

**Phasing:** Rungs 1–2 need at most `networkx`; `OR-Tools` arrives only at Rung 3.
The dependency footprint stays near-zero until the solver phase.

**Structural validation** (Rung 3 graph-isomorphism) defers the shape simulator
to Rung 4.

**The corpus de-risks every buy:** validate CP-SAT placement and the router
against human-optimal layouts before trusting them on novel specs.

---

## 7. Execution plan (test-first)

The concrete, TDD-ordered work plan. It supersedes §0's prose "next steps" and
details §3's ladder. **Methodology: write the test first, watch it fail, make it
pass, refactor.** A red bar that cannot pass yet is captured as
`@pytest.mark.xfail(strict=True, reason=...)` (the cutter precedent) so `just
test` stays green, the gap is visible in the run output, and the marker removes
itself the moment the feature lands (strict ⇒ an unexpected pass fails the suite).

### 7.0 Test taxonomy

Six flavours; each work package below says which it adds.

1. **Calibration (unit).** Pure functions — `_machine_footprint`,
   `routing_inout`, pipe directions, shape ops. Exact, fast, no fixtures.
2. **Structural lift.** On a *closed* oracle fixture (a port on every lane):
   `unmatched_legs == 0` plus node/edge counts and per-type degree. "Topology is
   right."
3. **Functional sim.** `interpret(...)` yields the expected shapes — lane-wise on
   a corpus fixture, or exact on a hand-built minimal netlist.
4. **Round-trip / isomorphism.** The inverse-pair invariants (§7.1): routing and
   synthesis are checked by lifting their output back and comparing graphs.
5. **Physical validity.** `validate(bp)` passes for the corpus and fails — with a
   specific reason — on hand-built broken inputs (overlap, dangling, off-grid).
6. **Corpus sweep (regression).** One parametrized test over every closed
   fixture, asserting flavours 2 and 5. The blanket safety net.

### 7.1 Master invariants

Everything reduces to these; each WP moves one closer to green.

- **I1 — well-formed lift:** a closed corpus blueprint ⇒ `unmatched_legs == 0`.
- **I2 — correct lift:** recovered nodes / edges / degrees == the known structure.
- **I3 — correct sim:** `interpret(lift(bp), inputs) == expected_outputs`.
- **I4 — route is lift's inverse (Rung 3):** `isomorphic(lift(route(N, P)), N)`
  for a netlist `N` placed at fixed positions `P`.
- **I5 — synthesis is correct (Rung 4):** `isomorphic(lift(synth(spec)),
  netlist(spec))` **and** `interpret(lift(synth(spec)), in) == spec(in)`.
- **I6 — physical validity:** `validate(bp)` ⇔ `bp` is placeable and legal.
- **I7 — compactness (soft):** `belts(synth(spec)) ≤ k · belts(oracle)` — measured
  and tracked against the human oracle, not a hard gate.

Lifting is the trusted core (I1–I3, green for rotators/half-destroyer/cutter/
swapper). I4 and I5 *bootstrap off it*: we never hand-verify routed/synthesized
geometry — we lift it back and compare to the intended netlist. Route and synth
must therefore emit exactly the belt/junction types+rotations that
`lift.routing_inout` decodes; the calibration table is the single source of truth
shared by both directions, which is what makes the round-trip exact.

### 7.2 Work packages

Ordered along the **critical path to the north star**. The diagonal extractor (the
headline demo) uses only rotators, swappers, and belts — all already lifted and
simulated — so the path is IR → router → placement → synth, needing **no**
stacker/painter work. Machine-table breadth (WP-F/G/H) is a parallel track that
widens the spec space but blocks nothing on the diagonal extractor.

#### WP-A — Netlist isomorphism *(validation backbone; critical path)*
- **Goal:** a placement-independent equality on lifted netlists — the substrate
  for I4/I5. Lets us assert "this routed/synthesized blueprint realizes that
  netlist" without comparing coordinates.
- **Tests first** (`tests/test_netlist.py`, flavour 4 — scaffolded as xfail now):
  - `test_self_isomorphic` — `isomorphic(trace_layer(Q,0), trace_layer(Q,0))`.
  - `test_floors_are_isomorphic` — `isomorphic(trace_layer(Q,0),
    trace_layer(Q,1))` True: identical structure, different layer/coords ⇒ proves
    coordinate-independence on a *real* example.
  - `test_cw_ccw_180_quarters_not_isomorphic` — pairwise False: identical topology
    (4→8→4) but different rotator **type** ⇒ proves type-sensitivity.
  - `test_cutter_not_isomorphic_to_rotator`, `test_full_belt_not_isomorphic_to_
    quarter` — False (different op/degree; different size).
- **Implementation:** `lift.to_graph(nl) -> nx.MultiDiGraph` (node attr =
  `(kind, type)`, edges from `nl.edges`); `lift.isomorphic(a, b)` via
  `nx.is_isomorphic(..., node_match=by (kind, type))`. Add the `networkx` dep.
  *Port-aware* isomorphism (distinguishing a swapper's two inputs) is **deferred** —
  Rung-3 structural validity does not need it (§3).
- **Done when:** the five tests are green; `networkx` added; xfail removed.

#### WP-B — Physical validator + corpus sweep *(safety net; critical path)*
- **Goal:** I6, plus a blanket regression that makes every later change cheap to
  trust.
- **Tests first:**
  - `tests/test_validate.py` (flavour 5): `test_corpus_is_valid` parametrized over
    closed fixtures ⇒ `validate(bp) == []`; `test_overlap_detected`,
    `test_dangling_leg_detected`, `test_offgrid_detected` on hand-built broken
    blueprints ⇒ a non-empty problem list naming the cause.
  - `tests/test_corpus.py` (flavour 6): `test_closed_fixtures_lift_clean`
    parametrized over the closed registry ⇒ `unmatched_legs == 0` on every floor.
- **Implementation:** `validate(bp) -> list[Problem]` (empty ⇒ valid): (a) no two
  entities share `(x, y, L)`; (b) `unmatched_legs == 0` across floors (reuse
  lift); (c) every cell inside the platform interior (use `platforms.json` + the
  seam model). A `CLOSED_FIXTURES` / `OPEN_FIXTURES` registry in `conftest.py`
  (closed = ported, assert 0 unmatched; open = the pinwheel exports, dangling by
  design).
- **Done when:** the sweep is green over closed fixtures; broken inputs rejected
  with the right reason.

#### WP-C — Rung 3: re-route at fixed placement *(the router core; critical path)*
- **Goal:** I4. Given a netlist + the machines' existing cells, regenerate belts
  realizing every edge; lifting the result reproduces the netlist.
- **Status: DONE for single-cell machines, cell-level multi-cell ports, and
  *spacious* wide fans. Corpus multi-cell round-trip still xfail (tight 2D fan
  packing).** Round-trip verified on 7 single-cell fixtures (rotator family × 6,
  half-destroyer). 2 multi-cell fixtures xfail (cutter, swapper).
- **Tests** (`tests/test_route.py`; flavours 4 + 5):
  1. ✓ `test_route_straight` — one src → one dst in a line ⇒ Forward belts.
  2. ✓ `test_route_one_turn` — offset on both axes ⇒ Forward + Left turn.
  3. ✓ `test_route_fanout` / `test_route_fanin` — 1→2 / 2→1 with junctions.
  4. ✓ `test_route_avoids_obstacle` — A* detours around blocked cell.
  5. ✓ `test_fanin_same_direction_merger_near_sources` — merger placed near
     machine cluster, not near sink.
  6. ✓ `test_fanout_same_direction_splitter_near_sinks` — splitter placed near
     machine cluster, not near source.
  7. ✓ `test_fanin_merger_placement_allows_distinct_directions` — merger has
     inputs from distinct directions (position assertion).
  8. ✓ `test_reroute_with_junctions_rotator_quarter` — full strip→reroute→lift
     round-trip on the rotator quarter.
  9. ✓ `test_reroute_roundtrip` — parametrized over 7 single-cell fixtures.
  10. ✓ `TestMultiCellRouting::test_cutter_outputs_route_as_distinct_ports` — a
      cutter's two outputs route as distinct ports (no bogus splitter).
  11. ✓ `TestMultiCellRouting::test_reroute_fanin_four_way` /
      `test_reroute_fanout_four_way` — ≥4-way fans on *spacious* synthetic
      layouts ⇒ all edges recovered (chained junctions).
  12. ✗ `test_reroute_roundtrip_multi_cell` — parametrized over 2 multi-cell
      fixtures (cutter_12_to_24, swap_diagonal). **xfail (tight 2D packing).**
- **Implementation:**
  - `reroute_with_junctions(stripped, netlist)` — the main entry point. Strips
    belts, analyzes fan patterns at **cell granularity** off `netlist.port_edges`
    (each multi-cell port routed independently via `_node_cell_ports`), routes
    via sequential A* with obstacle marking.
  - **Junction placement near machine clusters (≤3-way):** when all sources
    (fan-in) or destinations (fan-out) face the same direction, the junction is
    placed next to the cluster — one endpoint feeds straight in, others turn
    perpendicular. 2-way picks the endpoint closest to the far side on the
    perpendicular axis; 3-way the median (so branches spread for `Splitter1To3` /
    `Merger3To1`).
  - **≥4-way chains:** a junction cell holds ≤3 legs, so wide fans chain.
    `_route_split_chain` is a deterministic splitter comb (dsts spread along the
    flow axis, one trunk cell each); `_route_merge_chain` is a collision-free
    merger staircase (perpendicular-spread sources folded nearest-trunk-first so
    a farther source's drop only crosses already-vacated rows). Both build
    explicit bounded paths (`_explicit_path` / `_path_belts`) — no A* wandering,
    no unbounded loops.
  - Sequential A* with obstacle marking prevents crossings by construction.
  - Emits exactly the types+rotations `lift.routing_inout` decodes — shared table,
    round-trip exact by construction.
- **Remaining gap (tight 2D fan packing):** the multi-cell *port* problem is
  solved, but the corpus packs mergers in 2D where a linear chain has no room —
  a sink can sit ~2 cells from its four sources. The merge staircase bails when
  it won't fit (unmatched legs, no crash); greedy A* congests. Closing this is
  not a standalone router fix — it needs the **placer to reserve routing room**,
  so it folds into WP-D (space-aware place-and-route). Cutter lifts back to
  ~38/66 edges; the misses are the tight 4-way fans.
- **Defer:** throughput-aware **parallel-lane** routing — one belt per edge for now.

#### WP-D — Placement (CP-SAT) *(Rung 3→4; critical path)*
- **Goal:** choose machine cells + rotations for a netlist on a platform, instead
  of reusing the oracle's placement. **Now also absorbs the last WP-C gap**: the
  router can't realize the corpus's *tight* fan-ins on the oracle's own packing
  (no room for a merger chain), so the placer must reserve routing room — port
  adjacency feasibility must account for the junction cells a fan needs, not just
  the machines. **Note:** machine placement is often a human design decision — the
  user places machines; the tool routes belts. The placer validates the full
  pipeline and will become smarter as the router matures.
- **Status: DONE (rotator quarter 16/16, swapper 8/8).** CP-SAT placer in
  `place.py`. `abstract_netlist` strips coordinates; `place()` assigns
  `(x, y, r)` via OR-Tools. Constraints: no overlap, interior bounds, rotation
  facing toward connected nodes (element constraint on direction dot-product),
  fan-out groups at same y / adjacent x / ordered by source x, sink ports
  ordered to match source flow, **2-cell port-row margin**, **2-cell inter-group
  x-gap**, **y-stagger** (edge groups placed one row closer to sources than inner
  neighbours). **Multi-cell machines** (swapper, cutter): second-cell position
  via `add_element` on rotation-indexed offset tables; both cells in
  AllDifferent + bounds; second-cell wire length in objective (keeps both cells
  near connected ports); proximity-based port assignment in `_build_netlist`
  (`_assign_ports`); BFS-based sink ordering (`_trace_all_sinks`) handles
  multi-input machines. Routes **16/16** rotator and **8/8** swapper edges.
  **Key insight:** the y-component of wire length is invariant: for every edge,
  `|src_y - machine_y| + |machine_y - sink_y| = const` regardless of machine y.
  The solver was indifferent among y-assignments and happened to find the flat
  layout first. Edge groups' horizontal trunks (from off-column sources) collide
  with inner groups' vertical trunks at the shared y-level. The oracle staggers
  groups across two y-levels so trunks use different y-levels and don't cross.
  The y-stagger constraint (`group_ys[0] > group_ys[1]`, `group_ys[-1] >
  group_ys[-2]`) deterministically produces this pattern.
  Router-side fixes also landed: `route_astar` `start == end` obstacle check,
  conditional outside-in fan-out ordering via `_perp_reach`, fan-in retry logic
  (`_route_fanin_pass` tries default and distance-sorted orderings).
- **Tests:**
  - ✓ `test_place_single_rotator` — feasible placement, no overlap, interior.
  - ✓ `test_place_two_rotators_no_overlap` — AllDifferent stress.
  - ✓ `test_place_then_route_rotator_quarter` — 16/16 edges, isomorphic.
  - ✓ `test_swapper_placement_solves` — CP-SAT places 2 swappers.
  - ✓ `test_swapper_second_cells_no_overlap` — all footprint cells distinct.
  - ✓ `test_swapper_lowered_validates` — lowered blueprint passes validation.
  - ✓ `test_swapper_lowered_interprets` — diagonal shapes verified.
  - TODO: `test_placement_compact` (bounding box / belt count within `k×` oracle).
- **Implementation:** OR-Tools CP-SAT — vars = `(cell, rotation)` per machine
  + `(second_x, second_y)` per multi-cell machine (element constraints on R);
  constraints = AllDifferent over all cells (anchor + second), on-grid, rotation
  facing, fan-group structure, source/sink ordering, port-row margin 2,
  inter-group gap 2, y-stagger; objective = minimize total Manhattan wire length
  including second-cell distances.
- **Done when:** place+route reproduces the quarter and full belt structurally;
  compactness tracked.

#### WP-E — Rung 4: synthesize from spec *(the product; critical path)*
- **Goal:** I5. Spec → netlist → place (D) → route (C) → entities → file.
- **Status: DONE for single-op, series-chain, and diagonal-trick platforms.**
  `Spec(op, platform, throughput)` for uniform lane pipelines; `DiagonalSpec(pairs,
  platform)` for the diagonal trick. `_lower(abstract, platform)` runs the generic
  pipeline on any abstract netlist. 26 tests green, 1 xfail (series+throughput=2
  on 1×1 — 16 machines too dense). CLI: `synth rotate_cw,rotate_cw --throughput 1`
  or `synth swap_diagonal [--pairs N]`.
- **Tests:**
  - ✓ `test_rotate_180_quarter_topology` — 4 src + 8 machines + 4 sinks, 16 edges.
  - ✓ `test_machine_type_matches_op` — CW spec → RotatorOneQuad machines.
  - ✓ `test_edge_structure_fan_out_fan_in` — each src fans to T, each sink gathers T.
  - ✓ `test_series_chain_topology` — 4×1×2 stages = 8 machines, 12 edges.
  - ✓ `test_series_chain_edge_structure` — every machine 1-in/1-out.
  - ✓ `test_series_with_throughput_topology` — 4×2×2 = 16 machines, 24 edges.
  - ✓ `test_synth_rotate_180_quarter` — isomorphic to oracle.
  - ✓ `test_synth_rotate_180_quarter_validate` — physical validation clean.
  - ✓ `test_synth_rotate_180_quarter_interpret` — RuCuSuWu → SuWuRuCu on all lanes.
  - ✓ `test_synth_rotate_cw_quarter` — isomorphic to oracle.
  - ✓ `test_synth_rotate_ccw_quarter` — isomorphic to oracle.
  - ✓ `test_synth_half_destroy_quarter` — validates + interprets → RuCu---- on all.
  - ✓ `test_series_cw_cw_equals_180` — 2×CW in series = 180° (validate + interpret).
  - ✓ `test_series_ccw_ccw_ccw_equals_cw` — 3×CCW = CW (validate + interpret).
  - ✗ `test_series_with_throughput` — xfail (16 machines on 1×1 too dense).
  - ✓ `test_swapper_placement_solves` — 2 swappers placed by CP-SAT.
  - ✓ `test_swapper_second_cells_no_overlap` — all footprint cells distinct.
  - ✓ `test_swapper_lowered_validates` — lowered swapper blueprint clean.
  - ✓ `test_swapper_lowered_interprets` — diagonal shapes from north/south inputs.
  - ✓ `TestDiagonalNetlist::test_two_pair_topology` — 4 src, 2 swap, 4 sink, 8 edges.
  - ✓ `TestDiagonalNetlist::test_machine_type_is_swapper` — correct entity type.
  - ✓ `TestDiagonalNetlist::test_each_swapper_has_two_in_two_out` — 2-in/2-out.
  - ✓ `TestDiagonalNetlist::test_sources_interleaved_north_south` — port ordering.
  - ✓ `TestDiagonalNetlist::test_too_many_pairs_raises` — validation.
  - ✓ `TestDiagonalSynthesize::test_diagonal_validates` — physical validation clean.
  - ✓ `TestDiagonalSynthesize::test_diagonal_edge_count` — 8/8 edges realized.
  - ✓ `TestDiagonalSynthesize::test_diagonal_interprets` — diagonals from N/S inputs.
- **Remaining:** scaling to 4 pairs (the full-belt target) — Foundation_2x2
  port calibration done (Q5 resolved); placer needs multi-edge port support.

#### WP-F — Stacker cross-floor lift *(breadth track)*
- **Goal:** lift inter-floor machines; complete the table for stacking specs.
- **Tests first:** `test_stacker_footprint_vertical_input` (unit: the 3-D
  `_machine_footprint` puts the secondary input one floor up at the anchor,
  offset `(0,0,+1)`, accepting from the back; output front=straight /
  right=`StackerDefault` / left=`…Mirrored`); `test_stacker_blueprint_lifts_clean`
  (save `Full Belt Stacker` → `data/reference/stacker_full_belt.spz2bp`; whole-
  blueprint `unmatched_legs == 0`; stackers = 2-in (one cross-floor) / 1-out);
  `test_independent_floors_unchanged` (rotator quarter/full belt still lift
  per-floor at 0 — the 3-D change must not break independent-floor families).
- **Implementation:** occupancy keyed by `(x, y, layer)`; `_machine_footprint`
  returns 3-tuple offsets; add `trace(bp)` spanning floors (keep `trace_layer` for
  single-floor families). The stacker claims the cell **directly above** its
  anchor as an input port (the L+1 feed belt's output lands there). `down`/`reach`
  / `unmatched_legs` operate in 3-D.
- **Then (separate sub-task):** the stacker shape op needs a **layered** shape
  model — `Shape` is single-layer today; extend to N layers before `interpret`
  can stack.

#### WP-G — Painter pipe layer *(breadth track)*
- **Goal:** lift fluid machines (painter, later crystallizer/miner).
- **Tests first:** `test_pipe_directions` (unit: pipe Forward/turn/junction in/out
  sides per R, calibrated like belts); `test_painter_lifts_clean` (a clean
  belted+piped painter lifts at 0 unmatched across **both** layers; the painter
  node has shape-in + paint-in + shape-out).
- **Implementation:** a `pipe_inout` table mirroring `routing_inout`; a two-graph
  occupancy (belts carry shapes, pipes carry fluid); the painter consumes from
  both. Likely needs a fresh export with belts **and** pipes on its I/O —
  `QUESTIONS.md` Q4b. Sim needs a color model (defer).

#### WP-H — Full-blueprint functional drive *(breadth track; confidence, not capability)*
- **Goal:** I3 on a whole dense blueprint, not just hand-built netlists.
- **Problem:** a closed extractor's sinks gather several machines through
  throughput mergers, so it resolves to single shapes only under its **intended
  input pattern**; uniform input makes a gather see different shapes (the
  interpreter rightly refuses — observed on `swap_diagonal`).
- **Tests first:** `test_swap_diagonal_computes_diagonals` — feed the intended
  per-source pattern (north-feed / south-feed lanes) ⇒ the two diagonals at the
  labelled sinks.
- **Implementation:** derive each source's input role and each sink's output role
  structurally (trace reachable machines / feeders), or take the I/O contract from
  the blueprint name / user. Lower priority: the ops are already proven on minimal
  netlists, so this is confidence, not new capability.

### 7.3 Sequencing & dependencies
- **Critical path:** A → B → C → D → E, each gated by the prior's invariant.
- A and B are cheap and unblock everything — done.
- C (the router) is the hard, high-value core. Single-cell round-trip, cell-level
  multi-cell ports, and spacious wide-fan chaining are green; the **last C gap
  (tight 2D fan packing) is now coupled to D** — the placer must leave routing
  room, so finish it inside WP-D rather than as a standalone router pass.
- F / G / H run in parallel whenever a stacker / painter / confidence need
  arises; none block the diagonal-extractor north star.
- New deps (§6): A/H add `networkx`; D adds `OR-Tools`. Nothing else.

### 7.4 Test infrastructure to build first
- `tests/conftest.py`: fixture loaders + the `CLOSED_FIXTURES` / `OPEN_FIXTURES`
  registry, and a `tiny_netlist(...)` builder (promote the helper from
  `tests/test_interpret.py::TestMultiPort`) for hand-built I4/I5 cases.
- Treat the deprecated `router.py` + `tests/test_router.py` as **out of the
  regression contract**; WP-C replaces them.
