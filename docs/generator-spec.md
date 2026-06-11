# Blueprint Synthesis — Plan

**Status:** Draft, updated 2026-06-10. **WP-M in progress — first north-star
gate passes** (`test_synth_diagonal_full_belt_2x4`: 8-pair diagonal on
Foundation_2x4, 32/32 edges, validates + interprets with hops). Row model +
feedback loop landed, hop direction constraints landed, A\* heuristic landed
(3.9× routing speedup), multi-face port support landed. WP-J done. WP-K done.
WP-L landed. WP-H landed. Scaling plan: §2a (architecture) + WP-I…WP-M (§7.2)
— negotiated-congestion routing for dense platforms.**

**North star:** synthesize *dense, compact, single-platform* blueprints from a
functional spec — e.g. "on a 2×8 full belt, extract both diagonals and pin the
upper-left diagonal to the 4 left outputs and the upper-right to the 4 right."
These are hard to route by hand and are what make factories compact. That is the
product.

**Easy platforms are the test harness, not the goal.** A "rotate 12 belts 180°"
is a 10-second hand build; here it exists only as an end-to-end test and a
regression floor. The hard target is intra-platform **place-and-route**.

---

## 0. Status & handoff (2026-06-10)

**Built and green** (247 tests pass, 0 xfail, `just test`, ruff clean):
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
  (`_machine_footprint`, 3-D offsets `(dx, dy, dl)`). `trace_layer`,
  `unmatched_legs`, `edge_kinds`. **Lifts the rotator family + half-destroyer
  + the cutter at 0 unmatched legs.** The **stacker** (2-in/1-out) has a
  cross-floor secondary input at `(0,0,+1)` — three output variants
  (Straight/Default/Mirrored). `trace(bp)` spans all floors via
  `_occupancy_3d`, resolving L+1 belt→stacker connections through the 3-D
  occupancy; verified on a synthetic closed fixture (2 inputs, 1 output per
  stacker) and both open stacker fixtures (4 straight, 8 bent).
  Includes `isomorphic(a, b)` for structural netlist comparison (WP-A done).
  **WP-J lift calibration:** `lift_inout(type, r)` returns `(ins, outs, delta)`
  for all 16 lift variants (Lift1/Lift2 × Up/Down × Forward/Backward/Left/
  LeftMirrored), calibrated empirically from 20+ existing blueprints.
  `_lift_footprint` expands lifts to multi-floor cells (input at entity layer,
  output at target layer, blockers in between). `_occupancy` and `_occupancy_3d`
  handle lift cells; `_Cell.out_layer_delta` enables `trace()` to follow
  cross-floor output. `kind()` returns `"lift"` for lift entities (excluded from
  nodes, contracted like belts). Verified: **12-to-12 Balancer** (pure routing +
  46 lifts, 3 floors) lifts at **0 unmatched legs** on all floors; 3-D trace
  recovers 32 port nodes (16 in, 16 out) + 148 edges, all platform_in→platform_out.
  **WP-K hop tracing:** `_resolve_hops` pairs interior launcher/catcher entities
  by scanning along the sender's facing direction (first receiver with same
  rotation wins); senders sorted by `(rotation, projected position)` so
  within each direction the sender whose items reach receivers first is
  processed first — fixes greedy pairing when multiple senders face the same
  way. `trace_layer(..., contract_hops=True)` threads belt contraction
  through hop pairs transparently. Verified: 145/145 Half Splitter pairs,
  18/18 swap_diagonal pairs.
- `shapes.py` — **multi-layer** shape model + absolute ops (rotate / cut /
  half-destroy / swap-west / **stack**). Convention: quadrants `(NE, SE, SW, NW)`,
  west = `SW+NW`, layers separated by `:`. **Gravity** (orthogonal adjacency,
  connected groups fall as units) implemented for the stacker; diagonal quadrant
  pairs (NE↔SW, NW↔SE) are not connected and fall independently.
- `interpret.py` — pushes shapes through a lifted netlist, **per cell** via the
  netlist's `port_edges`, so multi-port machines work. Verified: rotators +
  half-destroyer on every lane (quarter + full belt's 48), the **cutter** (1→2,
  east/west), and the **swapper** (2→2) including the **diagonal trick**
  (north-only + south-only in → the two diagonals out). **`collect` mode** for
  throughput blueprints: sinks fed by multiple distinct shapes return a
  `frozenset[Shape]` instead of raising. **`classify_sources(nl)`** partitions
  sources into feed groups via 2-coloring the swapper constraint graph.
  Full-blueprint functional drive on `swap_diagonal` (WP-H): 26 sinks, 17
  single-shape + 9 multi-shape (throughput mergers), all verified.
- `validate.py` — physical validator (WP-B done). Checks overlap, dangling legs,
  off-grid placement. Corpus sweep passes on all closed fixtures.
- `route.py` — **now a thin shell over `pathfinder.py`** (WP-I).
  `reroute_with_junctions` delegates to `pathfinder.strip_and_reroute`; the
  WP-C-era sequential-A\* fan machinery (`_route_split_chain` splitter comb,
  `_route_merge_chain` merger staircase, junction-placement heuristics,
  `_perp_reach` ordering) is **deleted** — PathFinder tree growth subsumes
  all of it. What remains: `strip_belts`, the A\* core (`route_astar`,
  `route_edge(s)`, `reroute_astar`), simple `route_fanout`/`route_fanin`,
  entity plumbing (`_all_entities`, `_rebuild_blueprint`,
  `entities_to_blueprint`), and the WP-C history in §7.2.
- `pathfinder.py` — **WP-I done.** PathFinder negotiated-congestion router
  (McMurchie & Ebeling 1995). Routes multi-terminal nets as Steiner trees
  (farthest-first growth, per-cell leg-legality, junctions emerge from tree
  branching) under iterative congestion pricing with rip-up-and-reroute.
  Emit table is the programmatic inverse of `lift.routing_inout` (one shared
  calibration table, both directions). **Gate flipped:** `cutter_12_to_24`
  (66/66 edges) and `swap_diagonal` (162/162 edges) both round-trip through
  lift as isomorphic; single-cell corpus parity holds (all 7 fixtures).
  **WP-K hop routing:** `RoutingGraph(hop_range=N)` enables launcher/catcher
  hop edges (cost = `d·BASE + HOP_PENALTY`, strictly more expensive than
  walking — only congestion tips the balance). Hop endpoint cells emit
  `BeltPortSender/ReceiverInternalVariant`; flight cells are free.
  **Hop direction constraints:** sender approach (must be fed from opposite
  the hop), receiver exit (must continue in hop direction), terminal exit
  (hops landing on terminals must match the boundary edge direction toward
  the downstream machine/sink), no double-hop (receiver can't launch),
  root approach (seeds cell\_approach from port offset). `_resolve_hops`
  sorts senders by `(rotation, projected position)` for deterministic
  pairing. Single-floor topological crossings now route and round-trip.
  **A\* heuristic:** `_grow_tree` uses `manhattan(cell, terminal) × BASE`
  as an admissible heuristic, pruning exploration on large grids (3.9×
  speedup on the 2×4 diagonal). Platform bounds from `platforms.json`
  replace the fixed-margin bounding box for the passable set.
  **WP-J lift routing:** `RoutingGraph(lift_enabled=True)` enables vertical
  lift edges in Dijkstra (cost = `LIFT_COST = 3.0`, both cells occupied).
  `_lift_emit_table` inverts `lift.lift_inout` for all 16 variants × 4
  rotations. `_cell_to_entity` detects lift edges and emits the correct lift
  variant based on entry direction, exit direction, and layer delta.
  `Net.lift_edges` tracks cross-floor tree edges. Verified: two crossing nets
  on a 5×5×2 grid route successfully with lifts; fails without.
  **All failure paths raise `RoutingError`** (carrying overused cells for
  WP-M feedback): non-convergence at `MAX_ITERS`, unreachable terminals, leg patterns
  with no emit-table entry, and a root stuck on its port cell. Roots
  offset from a port are pre-seeded with the pending boundary in-leg so
  splitters/mergers can sit directly adjacent to ports (tight-fan regime).
  **Direct machine-to-machine couplings** (terminal still on a machine cell,
  e.g. rotator→adjacent swapper) are filtered out before routing — physical
  adjacency realizes those edges, lift re-derives them. N→M net components
  raise `NotImplementedError` loudly. 18 tests in `tests/test_pathfinder.py`.
- `place.py` — CP-SAT placement (WP-D done for rotator quarter + multi-cell
  machines). OR-Tools CP-SAT solver assigns `(x, y, rotation)` to machines given
  an abstract netlist (graph structure only, no coordinates) and a platform.
  Constraints: no overlap, interior bounds, rotation facing toward connected
  nodes, fan-out groups at adjacent x / ordered by source x, sink port
  ordering matched to source flow. **WP-M row model:** `_compute_stages()`
  assigns each machine a BFS depth from sources; all machines at the same
  stage share a single `row_y` variable. Routing channels between rows
  (and between ports and the nearest row) have minimum height 2 cells.
  The hand-tuned y-stagger, 2-cell port-row margin, and per-group same-y
  constraints are **deleted** — their effects emerge from the row model.
  **Multi-cell machines** (swapper, cutter): second-cell position via
  `add_element` on rotation-indexed offset tables; both cells in AllDifferent
  + bounds; second-cell wire length in objective; proximity-based port
  assignment in `_build_netlist` (`_assign_ports`); BFS-based sink ordering
  (`_trace_all_sinks`) handles multi-input machines correctly. Routes
  **16/16** rotator edges and **8/8** swapper edges.
  `abstract_netlist(nl)` strips coordinates from a lifted netlist for the
  solver. Accepts `forbidden` cells for WP-M feedback loop.
  **Density constraints:** per channel, per x-bucket of width 4, the number
  of nets whose horizontal interval covers the bucket is capped at the
  channel height (`_covers_bucket` reifies interval-covers-bucket for
  const/var endpoints). Row-balance objective term centers rows between the
  source and sink channels.
  **WP-M multi-face ports (Half Splitter gate, slice 1):** `platform_in`/
  `platform_out` nodes may carry an optional `"face"` key (0=west, 1=south,
  2=east, 3=north; default 3 for sources, 1 for sinks) to land on a
  non-default platform edge. `_port_rotation_for(face, kind)` derives the
  port entity's belt rotation — `face` for sources (the calibrated
  into-interior direction), `(face+2)%4` for sinks (continuing outward) —
  generalizing the old single global `port_rotation`. Extra-face ports are
  assigned sequentially from `_edge_ports(plat, face)`, independent of the
  row model; primary-face (3/1) ports keep the existing row-model + WP-L
  monotone sink ordering. Verified end-to-end: a rotator with a west-face
  (and separately east-face) sink places, routes, and lifts isomorphic.
  **CutterDefault composes with multi-face ports out of the box:** a single
  `CutterDefaultInternalVariant` (1-in/2-out, `_is_multi_cell` already true)
  feeding one south-face sink and one west-face sink places, routes, lifts
  isomorphic, and `interpret` recovers the correct `shapes.cut` east/west
  halves on the correctly-faced sinks — no placer changes needed
  (`tests/test_place.py::TestCutterDefault`). De-risks the Half Splitter's
  per-lane cutter fan; `CutterSpec` + region-constrained assignment remain.
  **The placer is scaffolding** — machine placement is often a human design
  decision; the product is the router.
- `synth.py` — spec-driven synthesis (WP-E + WP-L + WP-M). `Spec(op, platform,
  throughput)` where `op` is a single operation or a tuple of operations forming
  a **series chain**: each lane's source feeds `throughput` parallel paths, each
  path passing through every stage in order, then fan-in to the sink.
  `_lower(abstract, platform)` runs the generic pipeline (any abstract netlist →
  **monotone sort** → place → route → blueprint). **WP-M feedback loop:**
  `_lower` catches `RoutingError`, adds the overused cells to a `forbidden` set,
  and retries placement up to 3 times. **WP-L monotone assignment:**
  `_monotone_sort` reorders source/sink nodes by ascending x so the placer
  assigns leftmost sources to leftmost ports, eliminating route crossings for
  uniform specs. `abstract_netlist()` now carries `orig_x` on port nodes so
  lifted netlists sort correctly. **WP-L quotient fast path:**
  `synthesize_quotient(spec)` synthesizes one floor and stamps it across all
  three floors via `generator.stamp` — belt counts scale exactly 3×, each floor
  isomorphic. Verified: single-op rotate-180/cw/ccw on 1×1 quarter (isomorphic
  to oracles, 16/16 edges); half-destroy (validates + interprets at throughput=2
  **and throughput=3**); series chains (2×CW = 180°, 3×CCW = CW, both validate
  + interpret correctly); **series with throughput=2** (4×2×2 = 16 machines,
  validates + interprets correctly — the WP-D xfail now passes).
  Multi-cell: 2-swapper abstract netlists lower to valid blueprints that interpret
  correctly (placement + routing + port assignment verified end-to-end).
  **Diagonal trick synthesis:** `DiagonalSpec(pairs, platform)` generates the
  paired north/south → swapper → diagonal topology; `synthesize_diagonal()`
  lowers it through the full pipeline. Verified on 1×1 with 2 pairs (8/8 edges),
  **on 2×2 with 4 pairs** (16/16 edges), **and on 2×4 with 8 pairs** (32/32
  edges, validates, interprets to correct diagonals on all 16 lanes, with
  hop\_range=4 — the **first north-star gate**).
  CLI: `synth swap_diagonal [--pairs N] [--platform P]`.
  Reference: `data/reference/swap_diagonal_4pair_2x2.spz2bp`.
  **41 synth tests green, 0 xfail (247 total, 0 xfail).**
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

**WP-C (routing): SUPERSEDED BY WP-I.** WP-C's sequential A\* with junction
placement heuristics carried the project to cell-granularity multi-cell ports
(`_node_cell_ports`) and spacious wide fans, but its precisely-diagnosed
blocker — tight 2D fan packing, where greedy obstacle-marking A\* congests —
is exactly what WP-I's negotiated congestion solves. The WP-C fan machinery
(combs, staircases, placement heuristics) is deleted; `reroute_with_junctions`
delegates to `pathfinder.strip_and_reroute`. **All 9 corpus fixtures (7
single-cell + cutter_12_to_24 + swap_diagonal) round-trip isomorphic.** The
WP-C section in §7.2 is kept as the historical record.

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

**Rung 2 (interpret) — DONE, including full-blueprint drive.** The interpreter is
port-aware (`Node.rotation`, `Netlist.port_edges`, per-cell propagation); the
cutter/swapper ops + the diagonal trick are verified on hand-built netlists
(`tests/test_interpret.py::TestMultiPort`). **Full-blueprint drive (WP-H):** the
entire `swap_diagonal` blueprint (26 sources, 26 sinks, 32 swappers, 48 rotators)
runs end-to-end with `collect=True`. With uniform input S, single-feed sinks
produce `{S}` and throughput-merged sinks produce `{S, CW(S)}` — 17 + 9 = 26
sinks verified. `classify_sources(nl)` partitions the 26 sources into two swapper
feed groups (9 + 8) plus 9 pass-throughs via 2-coloring the constraint graph.

**Critical path — complete through WP-E + WP-I + WP-J + WP-L; WP-M in progress.**
~~WP-A~~ ✓ → ~~WP-B~~ ✓ → ~~WP-C~~ ✓ → ~~**WP-D placement**~~ ✓ →
~~**WP-E synthesize**~~ ✓ → ~~**WP-I PathFinder**~~ ✓ → ~~**WP-J lifts**~~ ✓ →
~~**WP-L assignment**~~ ✓ → **WP-M row placement** (row model + feedback loop
landed; hop direction constraints landed; A\* heuristic landed; **first
north-star gate passes** — `test_synth_diagonal_full_belt_2x4`; Half Splitter
gate remaining).
`synth.py` runs the full pipeline: spec → abstract netlist → monotone sort →
place → route → blueprint, with a feedback retry loop on routing failure.
Verified: rotate-180/cw/ccw on 1×1 quarter (**isomorphic to oracles**, 16/16
edges each), half-destroy on 1×1 (validates + interprets at throughput=2
**and throughput=3**), series chains with throughput=2 (**16 machines on 1×1,
the former xfail**), **8-pair diagonal on 2×4 with hops (32/32 edges,
validates + interprets)**. CLI: `just run synth rotate_180 -o out.spz2bp`.

**Remaining gaps:**
- ~~The tight 2D merger packing (cutter/swapper xfails)~~ — **resolved by WP-I**
  (PathFinder negotiated-congestion router). Both multi-cell corpus fixtures
  now round-trip at full edge count.
- ~~**The diagonal extractor**~~ (north-star demo): **first gate passes.**
  `test_synth_diagonal_full_belt_2x4` — 8 pairs on Foundation_2x4 with
  hop\_range=4, 32/32 edges, validates, interprets to correct diagonals on
  all 16 lanes (0.6s with A\* heuristic). Scales from 2 pairs on 1×1 through
  4 pairs on 2×2 to 8 pairs on 2×4.
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

## 2a. Scaling architecture — dense platforms (added 2026-06-09)

How place-and-route reaches the real targets: ~50–150 nets (48 input belts →
12–16 machines → 96 output belts) crossing each other across a 76×36×3-floor
interior. This section is the *why*; the implementable detail is WP-I…WP-M in
§7.2. Read this section before touching any of those WPs.

### Why the current router cannot get there

`route.py` is sequential A\* with hard obstacle marking. Two structural limits:

1. **Net ordering.** Each laid route permanently claims cells with no
   knowledge of later nets, so route #40 of 96 finds its corridor walled off.
   For congested instances **no ordering succeeds** — feasibility requires
   nets to mutually compromise, which a one-pass greedy scheme cannot express.
   The cutter/swapper corpus xfails are this failure at small scale; adding
   more ordering heuristics (we already have three) only moves the cliff.
2. **No crossing capacity.** One-occupant-per-cell on a single floor makes
   crossings impossible by construction — there is no 2-in/2-out belt cell
   (§1: junction variants are 1→2, 1→3, 2→1, 3→1, T). Yet the platform
   physically offers crossing capacity: 3 floors joined by lift entities
   (`Lift1Up*`/`Lift1Down*`), and launcher→catcher hops
   (`BeltPortSenderVariant`/`BeltPortReceiverVariant`) that fly over cells.
   Dense human builds spend that capacity freely; the router cannot express
   any of it.

### The fix (standard chip-CAD, sized for us)

This problem is FPGA detailed routing, which is solved at 1000× our scale by
**negotiated-congestion routing** (PathFinder, McMurchie & Ebeling 1995; the
VPR router): route every net optimally *allowing overlaps*, then iteratively
re-price shared cells and rip-up-and-reroute until no cell is shared. Nets
negotiate — a net with a cheap alternative vacates a contested cell; a net
without one pays the price and keeps it. VPR routes 100k+ nets this way; we
have ~150 on ~8k cells × 3 floors.

A giant co-formulated CP-SAT model (placement + routing together) stays
**rejected** (the chicken-egg decision): cell-level multi-commodity flow here
is ~3M booleans, and it discards the negotiation structure that makes
PathFinder converge. CP-SAT's jobs are assignment (WP-L) and
capacity-constrained placement (WP-M) — never the routing grid itself.

### Pipeline

```
abstract netlist
 → lane / instance assignment     WP-L  kill crossings before they exist; quotient symmetric lanes
 → placement w/ channel capacity  WP-M  rows + belt channels, CP-SAT, routability-aware
 → detailed routing               WP-I  PathFinder negotiated congestion …
     … on the unified 3-D graph   WP-J  floors + lifts      WP-K  launcher hops
 → emit                           existing  junction typing via the calibration table
 → verify                         existing  lift→isomorphic (I4) · interpret (I3/I5) · validate (I6)
```

The verification loop is untouched and is what makes the rebuild safe: routed
output is never eyeballed — it is lifted back and graph-compared (I4). Emit
must keep producing exactly the types+rotations `lift.routing_inout` decodes
(single shared calibration table, both directions).

### The unified routing graph (the key data structure)

One graph encodes all the physics, so the router needs no special-case
crossing logic — going over (lift), flying over (hop), and detouring around
become the same decision under one cost model:

- **Nodes:** cells `(x, y, layer)`, layer ∈ {0, 1, 2}. Capacity = 1 net per
  cell. Machine-occupied cells are not nodes.
- **Step edges:** 4-adjacent same-layer cells, cost 1.0.
- **Lift edges (WP-J):** between adjacent layers via lift entities, cost
  ≈ 3.0; claiming one claims a cell on **both** layers. Geometry must be
  calibrated from a fixture first (QUESTIONS.md Q8).
- **Hop edges (WP-K):** launcher → catcher, straight line, same layer, cost
  ≈ 2.0 + 0.05·distance; **flight cells are not occupied** (or lane-limited —
  per Q7 calibration). Endpoints each occupy one cell.
- **Legal leg patterns per cell:** (1 in, 1 out), (1, 2), (1, 3), (2, 1),
  (3, 1) — exactly the junction variant table. Max 4 legs. Never 2-in/2-out.

### Concrete north-star instance: the Half Splitter (added 2026-06-09)

The user's hand build exists, unfinished, at
`~/Projects/shapez_2_blueprints/UNFINISHED Half Splitter.spz2bp` — it is both
the demand signal and the partial oracle. Functional spec, as stated:

- **Input:** 48 full-shape belts entering across the **four south port faces**
  (4 faces × 4 slots × 3 floors = 48 lanes).
- **Operation:** cut every shape into its west half and east half (the
  absolute-halves cutter — `CutterDefault`, 1-in/2-out).
- **Output routing (the hard part):** 48 west-half belts must exit on the
  **western faces** (the 2 W-edge faces + the two west-most north faces) and
  48 east-half belts on the **eastern faces** (the 2 E-edge faces + the two
  east-most north faces). That side semantics is part of the spec. What is
  relaxed — see "Spec relaxation" below — is the slot-level assignment
  *within* each side, which the optimizer owns.
- **Port arithmetic — CONFIRMED (2026-06-09, mined from the blueprint):**
  platform is `Foundation_2x4` (8 non-south faces = 4 north + 2 west + 2
  east). The build is **entirely on layer 0** (all 1562 entities): 16 input
  lanes (S faces) → 32 output lanes per floor; the hand plan was the
  tile-replication convention — duplicate the floor ×3 for 48→96 (a **floor
  quotient**, the same instance-shrinking move as WP-L's lane quotient).
  Per the spec relaxation below, that is a baseline strategy, not the target.
- **Machine arithmetic (complete in the build):** per input lane: 1→4
  splitter tree (3 × `Splitter1To2L`) → **4 cutters** (cutter rate = ¼ belt)
  → two 4→1 merger trees (6 × `Merger2To1L`, 3 per half). 16 lanes ⇒ 48
  splitters + 64 cutters + 96 mergers, all present and all locally routed
  (every cutter has its input and reaches an output).
- **The human's crossing mechanism — hops, not floors:** zero lifts; **145
  launcher→catcher pairs on one floor** (`BeltPortSenderInternalVariant` →
  `BeltPortReceiverInternalVariant`, the same types as edge port slots —
  interior position is what distinguishes a hop endpoint from platform IO).
  Mined hop physics (feeds Q7): pairing is **first receiver along the
  sender's facing ray with the same rotation** (all 145 pairs resolve);
  flight distances observed 1–5 cells; flights pass over belts and over other
  hop endpoints but **never over machine cells** (0 of 280 flight cells);
  up to **3 flights stack** over one ground cell. Hops are clearly cheap —
  the synthesizer's `HOP_COST` should not penalize them much.
- **What is unfinished (the demand signal):** 17 of 32 outputs are fed. All
  eastern-lane **west halves** — which must traverse ~60 cells across the
  whole platform over everything else — are unrouted, plus parts of the
  north-face fan-in. The human completed every local route and stopped at
  exactly the maximal-crossing hauls. That is the regime WP-I + WP-K must
  win at.
- **Spec relaxation (2026-06-09, user decision).** Two properties of the hand
  build are *artifacts of hand design*, not requirements — do not imitate
  them:
  1. **Output ports are Region-constrained, not slot-pinned** (corrected
     2026-06-09 — an earlier draft of this item said `Free`, which
     over-relaxed: the side semantics *is* the spec). West-half sinks carry
     `Region(western_faces)`, east-half sinks `Region(eastern_faces)` — each
     region a named set of port-`Group`s (§5 pinning levels); face purity
     follows from the regions being disjoint. What the hand build
     over-specified — and what the optimizer now owns — is the **slot-level
     assignment within each region**: which lane lands on which
     face/slot/floor of its side. Hard `Locked` pins remain available for
     factory-integration cases.
  2. **Single-floor + copy-paste layers is a hand convenience.** Humans build
     one floor and duplicate it because hand-routing in 3-D is miserable; the
     optimizer has no such excuse. Full 3-D routing — lifts, non-identical
     floors, cross-floor paths — is sanctioned and expected (**WP-J is on
     this instance's critical path after all**). The floor quotient (route
     one floor at 16→32, stamp ×3) is demoted to an optional baseline: cheap
     to compute, useful as an I7 reference point and as a fallback when full
     3-D search struggles, but not the target strategy.
- **Role in the plan:** this is the acceptance instance for the full scaling
  arc — WP-M's north-star gate (`test_synth_half_splitter_2x4`, alongside the
  diagonal extractor). Lifting the unfinished build (even partially routed) is
  also a corpus stress test for WP-I: its completed regions are tight-packed
  fan trees.

### Crossing budget (cheap infeasibility check)

With `Locked`- or `Group`-pinned inputs and outputs, the minimum number of
route crossings is fixed by the **group-level permutation**'s inversion count
(slot assignment within a group is free and contributes no additional
crossings). Floors, lifts, hops, and channel heights give a computable
crossing capacity. Compare the two **before** solving anything: an impossible
spec is rejected with a counting argument and a clear message instead of a
solver timeout. (Built as part of WP-M.)

**Blocked on `Group`-level sink pinning (§5):** today every sink is
effectively `Free`, and `place()`'s sink ordering (`_trace_all_sinks` +
left-to-right `ordered_sinks`) always reassigns sink *positions* to match
source x-order — normalizing the placed netlist to 0 inversions regardless of
the abstract netlist's edges. A worked test case once `Group` lands: 4 input
groups and 4 output groups (west→east) on `Foundation_2x4`'s north/south
faces, with input group *i* `Group`-pinned to output group `5-i` — a full
reversal, maximal group-level crossing (6 inversions for 4 groups).

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
- Output-port pinning — **DECIDED (2026-06-09), refined (2026-06-10):**
  pinning is per-sink and optional, a four-level hierarchy where each level
  is a relaxation of the one before it:
  - **Locked** (was `Pinned`): exactly this port. No optimizer freedom.
  - **Group** *(new)*: any port within this **group** — a group being the
    platform's natural cluster of co-located, same-face ports (e.g. on
    `Foundation_2x4` each face's ports split into 4-port groups by x/y
    contiguity; derivable from `platforms.json`'s flat `ports` list, not yet
    a stored field). The optimizer picks the slot within the group.
  - **Region**: any port in any group within a *named set of groups* (e.g.
    `western_faces` = the 2 west-face groups + the 2 west-most north-face
    groups). The optimizer picks both group and slot.
  - **Free**: any port on the platform, subject to **face purity** (one
    result kind per face). `Free` ≡ `Region(all groups)`.

  The level is part of each spec's semantics — e.g. the Half Splitter uses
  `Region` (west halves → `western_faces`, east → `eastern_faces`; the side
  matters), not `Free`. **`Group` is the new addressable unit**: it is what
  makes a "force this group of inputs to cross to that group of outputs"
  spec — and the crossing-budget check below — expressible at all.
  `Free`/`Region` sinks are reordered by `place()`'s monotone sink
  assignment, which always drives inversions to 0 and so cannot represent a
  forced crossing.

  The assignment stage (WP-L/WP-M) chooses slots (and groups, for `Region`)
  within whatever freedom the level leaves. Remaining sub-question: the
  concrete encoding on netlist sink nodes (likely
  `{"pin": "locked"|"group"|"region"|"free", "target": <port|group-id|
  region-name|None>}`).
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

### Library survey for the scaling arc (2026-06-09)

Searched for an embeddable negotiated-congestion / grid router. Conclusion:
**build the PathFinder loop in-house** (~400 lines on `heapq` + the existing
grid model). Every existing implementation is format-locked or unembeddable,
and our cell semantics (junction variant set, directional belts, lifts, hops)
are the domain anyway:

- **VPR / VTR** (C++): the canonical PathFinder implementation. Not
  embeddable from Python; **read it for the cost schedule** if WP-I's
  parameters need retuning.
- **OrthoRoute** (Python + CUDA, KiCad plugin): PathFinder on a Manhattan
  lattice — the closest existing code to WP-I. KiCad-locked, GPU-dependent.
  Reading material, not a dependency.
- **Freerouting** (Java, Specctra DSN) / **KiCadRoutingTools** (Rust+Python,
  KiCad): PCB-format-locked rip-up-and-reroute routers. Not usable.
- **Factorio-SAT** (R-O-C-K-E-T/Factorio-SAT): SAT-encodes belt semantics to
  synthesize balancers inside small fixed boxes. Corroborates the chicken-egg
  decision (exact global models only work at window scale). Borrowable
  *pattern*, held in reserve: exact CP-SAT **local repair** of one stubborn
  congested window after PathFinder converges everywhere else. Not a WP.
- **networkx `steiner_tree`** (kou/mehlhorn): optional better initial tree
  topology for wide nets. Farthest-first growth should suffice; do not add
  until measured.
- **scipy `linear_sum_assignment`** or CP-SAT: only for WP-L's deferred
  general case; the monotone fast path needs no solver.

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
- **Status: SUPERSEDED BY WP-I** (this section is the historical record; the
  fan machinery described below is deleted). At hand-off: round-trip verified
  on 7 single-cell fixtures; the 2 multi-cell fixtures xfailed on tight 2D
  fan packing — resolved by WP-I's negotiated congestion.
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
  12. ✓ `test_reroute_roundtrip_multi_cell` — parametrized over 2 multi-cell
      fixtures (cutter_12_to_24, swap_diagonal). **Was xfail (tight 2D
      packing); flipped by WP-I.**
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
- **Status: cross-floor lift DONE.** `_machine_footprint` returns 3-D offsets
  `(dx, dy, dl)` for all machines; the stacker claims `(0, 0, 1)` as a
  secondary input (in from back, no output). Three output variants:
  `StackerStraight` (forward), `StackerDefault` (right of flow),
  `StackerDefaultMirrored` (left of flow). `_occupancy_3d` + `trace(bp)` span
  all floors; `trace_layer` unchanged for single-floor families. All 10 callers
  of `_machine_footprint` updated to filter `dl == 0` where needed. All prior
  tests still pass (161 + 3 xfail).
- **Tests:**
  - ✓ `test_footprint_vertical_input` — all 3 stacker variants at R=0.
  - ✓ `test_footprint_rotated` — cross-floor input direction rotates with R.
  - ✓ `test_stacker_nodes_in_single_layer_trace` — 4 stackers found by
    `trace_layer` (open fixture, no edges — no ports).
  - ✓ `test_stacker_cross_floor_trace_synthetic` — programmatic closed fixture
    with ports on L0+L1: stacker is 2-in (L0 primary + L1 secondary) / 1-out.
  - ✓ `test_stacker_cross_floor_trace_finds_all_nodes` — both open fixtures
    (4 straight, 8 bent) produce the right node counts.
- **Shape op DONE.** `Shape` extended to multi-layer (`upper` field, `:` syntax).
  `shapes.stack(bottom, top)` implements full gravity (gap layer, orthogonal
  adjacency grouping, group falling, MAX_LAYERS truncation). `_machine_op` wired
  for `Stacker → stack`. 16 new tests (multi-layer parse/rotate, stacking with
  overlap/no-overlap/diagonal-gravity/truncation, gravity group adjacency).
  Remaining: the **interpreter** can't exercise stackers on real blueprints until
  it supports 3-D node keys (cross-floor `port_edges`).

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

#### WP-H — Full-blueprint functional drive *(breadth track; confidence, not capability)* — **DONE**
- **Goal:** I3 on a whole dense blueprint, not just hand-built netlists.
- **Solution:** `interpret(nl, inputs, collect=True)` allows throughput-merged
  sinks to return `frozenset[Shape]` instead of raising. `classify_sources(nl)`
  partitions sources into swapper feed groups via 2-coloring.
- **Verified on `swap_diagonal`:** 26 sources, 26 sinks, 32 swappers, 48
  rotators. With uniform input S: 17 single-feed sinks → `{S}`, 9 multi-feed
  sinks → `{S, CW(S)}`. Source partition: 9 group A + 8 group B + 9 pass-through.
- **Tests:** `TestFullBlueprintDrive` — `test_swap_diagonal_computes_diagonals`,
  `test_swap_diagonal_sink_counts`, `test_classify_sources_partitions`.

#### WP-I — PathFinder detailed router *(critical path; replaces sequential A\*)* — **DONE**

Read §2a first. This WP needs **no new calibration** and **no new fixtures** —
start here.

- **Goal:** replace hard-obstacle sequential A\* with negotiated-congestion
  routing. Acceptance gate: the two corpus xfails
  (`test_reroute_roundtrip_multi_cell` over `cutter_12_to_24` and
  `swap_diagonal`) go green **on the oracle's own placement** — strip belts,
  re-route, lift back, isomorphic (I4).
- **New module** `src/shapez2_tools/pathfinder.py`. Keep `route.py` working
  until parity, then make `reroute_with_junctions` delegate to it (callers and
  tests keep the same entry point).
- **Data model** (single floor for now; the `layer` slot exists so WP-J does
  not change signatures):

  ```python
  Cell = tuple[int, int, int]              # (x, y, layer); layer == 0 until WP-J

  @dataclass
  class Net:
      net_id: int
      kind: Literal["fanout", "fanin"]     # 1→N or N→1; a 1→1 net is fanout, N=1
      root: Cell                           # the single-port end
      terminals: list[Cell]                # the N-port end
      tree_cells: set[Cell]                # result of growth
      tree_edges: list[tuple[Cell, Cell]]  # directed src→dst, derived after growth

  class RoutingGraph:
      passable: set[Cell]                  # interior minus machine cells
      base: dict[Cell, float]              # 1.0 everywhere initially
      hist: dict[Cell, float]              # accumulated overuse history, starts 0.0
      occ: dict[Cell, set[int]]            # net ids currently claiming the cell
  ```

- **Net extraction:** from `netlist.port_edges` at **cell granularity** (reuse
  `_node_cell_ports` from `route.py`). Group edges into connected components by
  shared endpoint cells. Each component must be 1→N (one source cell) or N→1
  (one sink cell); `raise NotImplementedError` on N→M components (none exist
  in current specs; do not silently mishandle one). Copy the endpoint
  conventions from `reroute_with_junctions` verbatim — including the
  adjacent-skip fix (when an endpoint is adjacent to the junction, there is no
  trunk to route).
- **Signal router (route one net):** grow a tree from `root`. Connect
  terminals **farthest-first** (builds the trunk first, the way the oracle's
  combs do). Each connection is one Dijkstra run seeded with *every current
  tree cell at cost 0*, expanding only through `passable` cells, terminating
  at the terminal. Rules:
  - Tree cells are seeds, never intermediate path cells (prevents within-net
    cycles): once seeded, do not re-expand into a tree cell.
  - Expansion *out of* a tree cell `t` is allowed only while `legs(t) < 4` and
    the resulting leg pattern stays in the legal set (§2a). Track per-cell leg
    counts on the growing tree.
  - For `fanin` nets, grow the identical tree with root = the sink cell and
    terminals = the sources, then flip every edge direction when deriving
    `tree_edges`.
- **Cost function** (the negotiation — this is the entire trick):

  ```
  overuse(n)    = max(0, len(occ[n] − {this_net}) + 1 − 1)     # capacity = 1
  enter_cost(n) = (base[n] + hist[n]) * (1 + pres_fac * overuse(n))
  ```

- **Global loop:**

  ```
  pres_fac = PRES_FAC_INIT
  for iteration in range(MAX_ITERS):
      for net in nets sorted by net_id:          # rip up and reroute EVERY net
          release net's cells from occ
          regrow net's tree under current costs
          claim the new cells in occ
      if no cell has len(occ) > 1:  SUCCESS
      for every overused cell n:    hist[n] += HIST_GAIN * (len(occ[n]) − 1)
      pres_fac *= PRES_FAC_MULT
  FAIL → return the overused cells               # placement feedback for WP-M
  ```

  Early iterations: `pres_fac` is small, every net takes its best path,
  overlaps allowed. Later: shared cells get expensive; nets with alternatives
  move off; nets without alternatives stay and pay. The history term breaks
  oscillation (two nets endlessly swapping the same two corridors).
- **Parameters** (record any retuning here; do not scatter magic numbers):
  `BASE = 1.0`, `PRES_FAC_INIT = 0.5`, `PRES_FAC_MULT = 1.8`,
  `HIST_GAIN = 1.0`, `MAX_ITERS = 60`.
- **Emit:** per tree cell, legs = incident `tree_edges` with directions ⇒
  `(in_sides, out_sides)` ⇒ entity type + R via the **inverse of
  `lift.routing_inout`**. Build the inverse table once, programmatically, in a
  helper (`emit_table()`); **never hand-write a second table** — the I4
  round-trip depends on the two directions sharing one source of truth.
- **Determinism:** sort nets by `net_id`; Dijkstra tie-break by
  `(cost, y, x, layer)`. Tests assert run-twice-identical output.
- **Tests first** (`tests/test_pathfinder.py`, flavours 4 + 5):
  1. `test_blocked_pocket_negotiates` — net B's sink sits in a pocket with a
     single entrance cell; net A's shortest path runs through that entrance
     but A has a detour. Route A first. Sequential hard-obstacle routing
     strands B; assert PathFinder routes both, disjoint cells.
  2. `test_oscillation_breaks_via_history` — two nets, two equal-cost shared
     corridors (symmetric — the classic oscillation case); assert convergence
     in < `MAX_ITERS` and both routed.
  3. `test_tight_fanin_two_cells_from_sink` — 4 sources, sink ~2 cells away
     (the corpus disease the merger staircase bails on, synthesized small);
     assert all 4 edges route and lift back.
  4. `test_fanout_tree_legs_legal` / `test_fanin_tree_legs_legal` — 1→4 and
     4→1 in open space; every tree cell's leg pattern is in the legal set;
     emitted junctions decode via `routing_inout`.
  5. `test_emit_roundtrip_small` — tiny netlist → route → emit → lift →
     `isomorphic`.
  6. `test_single_cell_corpus_parity` — parametrize the 7 single-cell fixtures
     through the new router (strip → pathfinder → lift ≅ original).
  7. `test_deterministic` — route the same instance twice; identical entity
     lists.
  8. **The gate:** remove xfail from `test_reroute_roundtrip_multi_cell`
     (cutter_12_to_24: 66/66 edges; swap_diagonal: all edges).
- **Done when:** the gate is green, single-cell parity holds, the corpus sweep
  is green, and `_route_split_chain` / `_route_merge_chain` are deleted (the
  tree growth subsumes both).
- **Pitfalls:**
  - There is no 2-in/2-out cell. If two nets *topologically must* cross on one
    floor, PathFinder will iterate to `MAX_ITERS` and fail — that is correct
    behaviour; crossing capacity arrives in WP-J/WP-K. Do not "fix" it here.
  - A junction cell belongs to exactly one net. Cell capacity is always 1.
  - Machine cells are not passable; platform border cells are not passable;
    port cells are endpoints with fixed directions.
  - Throughput-aware parallel lanes stay deferred (one belt per edge).

#### WP-J — third dimension: floors + lifts *(crossing capacity, part 1)* — DONE

- **Goal:** routes change floors through lift entities; the router decides
  when going up-and-over beats detouring.
- **Calibration (Q8) bypassed** — same approach as WP-K: mined empirical
  data from the 12-to-12 Balancer (`data/reference/balancer_12_to_12.spz2bp`,
  46 lifts, 3 floors). No user fixture needed.
- **lift.py:** `lift_inout(type, r)` → `(ins, outs, delta)` for all 16 lift
  variants. `_lift_footprint(type, r)` → multi-floor cell expansion. Input
  always from back at entity's own layer; output at L±delta in the named exit
  direction. `_Cell.out_layer_delta` enables cross-floor output in 3-D trace.
  `_occupancy` and `_occupancy_3d` handle lift multi-floor cells (input cell
  at entity floor, output cell at target floor, blockers between).
- **pathfinder.py:** `RoutingGraph(lift_enabled=True)` enables vertical
  neighbor expansion in `_grow_tree`. `LIFT_COST = 3.0`. `_lift_emit_table()`
  inverts `lift_inout` to map `(ins, outs, delta)` → `(variant, r)`.
  `_cell_to_entity` emits lift entities at cross-floor edge sources.
- **Tests (30 new in `tests/test_lift_3d.py`):** `TestLiftInout` (12
  parametrized R=0 variants + rotation + non-lift → None + all-16 sweep),
  `TestLiftFootprint` (Lift1 2-cell, Lift2 3-cell, input/output split),
  `TestBalancer` (0 unmatched legs all floors, 3-D trace ports, edges,
  all 3 floors used), `TestLiftEmitTable` (all 16 in table, roundtrip),
  `TestCrossingNets` (fails without lift, succeeds with, uses lift edges,
  emits valid lift entities).

#### WP-K — launcher/catcher hops *(crossing capacity, part 2)*

- **Goal:** same-floor crossings via flight. Entities identified:
  `BeltPortSenderVariant` (launcher) / `BeltPortReceiverVariant` (catcher) —
  the placeable siblings of the platform-edge port slots (`*InternalVariant`).
- **Tracer side: DONE.** `_platform_port_positions(bp)` loads known edge-port
  positions from `platforms.json`. `_is_interior_hop(type, pos, ports)` tests
  whether a port entity is at a non-edge position. `_resolve_hops(bp, layer,
  ports)` pairs interior senders with receivers: scan along the sender's
  facing direction, first receiver with the same rotation wins. Verified on
  the Half Splitter (145/145 pairs, 0 unresolved) and the swap_diagonal
  corpus fixture (18 pairs). `trace_layer(..., contract_hops=True)` marks hop
  endpoints as belt cells and jumps from sender to receiver in `down()`, so
  the belt contraction threads through hops transparently. Default is
  `contract_hops=False` (backward-compatible — existing corpus tests
  unaffected). 5 new tests in `tests/test_lift.py` (209 total, 1 xfail).
- **Router side: DONE.** `RoutingGraph(hop_range=N)` enables hop expansion in
  Dijkstra: from every cell × 4 directions × distances 2..N. Hop cost =
  `distance * BASE + HOP_PENALTY` (strictly more expensive than walking; only
  congestion tips the balance). Hop endpoint cells occupy normally; flight
  cells are free. `_cell_to_entity` emits `BeltPortSenderInternalVariant` /
  `BeltPortReceiverInternalVariant` at hop endpoints with rotation matching
  the flight direction. `strip_and_reroute(..., hop_range=N)` passes the
  parameter through. `Net.hop_edges` tracks non-adjacent tree edges for
  emission. Hop cells are excluded from further seed growth (no splitter/hop
  hybrid entities). 3 new tests in `tests/test_pathfinder.py`.
- **Lift side first, router second** (I4 requires the tracer to understand
  hops before the router may emit them):
  1. ~~Q7 fixture~~ — **bypassed**: mined pairing rules empirically from the
     Half Splitter (145 interior hop pairs). Remaining sub-questions (hard
     limits) are edge cases for the router, not the tracer.
  2. ✓ Tracer: resolve sender→receiver pairing by scanning along the sender's
     facing direction; the pair becomes a transparent belt connection.
  3. ✓ Router: hop edges in Dijkstra with congestion-gated cost. Endpoint
     cells occupy normally; flight cells free. Sender/receiver entities
     emitted with correct rotation. Round-trip verified via
     `contract_hops=True` re-lift.
- **Tests:**
  - ✓ `test_hop_pairing_half_splitter` — 145/145 pairs on the Half Splitter.
  - ✓ `test_hop_contraction_half_splitter` — 16 src, 64 cutters, 32 sinks.
  - ✓ `test_hop_contraction_swap_diagonal` — 8 src, 80 machines, 8 sinks.
  - ✓ `test_hop_contraction_no_hops_unchanged` — no-hop corpus = same result.
  - ✓ `test_swap_diagonal_hop_pairs` — 18 pairs resolved.
  - ✓ `test_hop_resolves_crossing` — two crossing 1→1 nets routed via hop.
  - ✓ `test_hop_emit_roundtrip` — route → emit → re-lift ≅ original.
  - ✓ `test_no_hop_when_unnecessary` — hops not used without congestion.
- **Done:** single-floor topological crossing routes via hop and round-trips.

#### WP-L — lane assignment + symmetry quotient *(shrink the instance first)* — **DONE**

Pure software, no fixtures, independent of I/J/K. Every crossing removed here
is one the router never negotiates.

- **Status: DONE.** `_monotone_sort` in `synth.py` sorts source/sink nodes
  by ascending x before placement (by `orig_x` from lifted netlists, or
  numeric ID suffix from synthesized ones). `abstract_netlist()` in `place.py`
  now carries `orig_x` on port nodes. `synthesize_quotient(spec)` synthesizes
  one floor and stamps across three floors via `generator.stamp`. 3 new tests
  (201 total, 1 xfail).
- **Monotone assignment (build first, covers all current specs):** when a
  spec's machine instances are interchangeable (synth *created* them, so it
  knows), assign the k-th leftmost input lane group to the k-th leftmost
  machine slot, and the k-th machine to the k-th output port group. Monotone
  assignment minimizes pairwise inversions for uniform specs — most "insane"
  crossings never come into existence. Implementation: a deterministic sort in
  `synth._lower` before placement; no solver.
- **Output-port assignment (scope added 2026-06-09, refined 2026-06-10):**
  for `Region` and `Free` sinks (§5 pinning decision) the assignment stage
  also chooses **which physical port each sink uses**, not just the ordering
  within pinned groups. Monotone rule extends naturally: sort each result
  kind's sinks and its candidate ports in flow order, assign k-th to k-th.
  For `Region` sinks (the Half Splitter case) the candidate set is the
  union of the region's `Group`s — nothing else to decide. Only `Free` sinks
  need the extra kind→face step: assign whole faces to one kind (face
  purity) minimizing total Manhattan distance from the kind's machine
  outputs to the face (a tiny assignment problem; brute force is fine).
  `Group`/`Locked` sinks (§5) bypass this stage entirely — their group/port
  is fixed by the spec, not chosen here; `place()` must stop reordering them
  via `_trace_all_sinks`.
- **General case (defer until a real need):** interchangeable-instance groups
  on *lifted* netlists + pairwise-crossing minimization via CP-SAT (bool
  `x[i][s]` = instance i in slot s; crossing bools reified from order
  inversions; minimize the sum). Do not build speculatively.
- **Symmetry quotient:** for lane-uniform specs, route **one** lane group on a
  one-unit-wide strip and stamp at pitch 20 — `generator.py` already stamps
  exactly this way for the rotator family; promote stamping into
  `synth._lower` as a fast path. A 48-lane spec with 4-fold uniformity is a
  12-lane routing problem.
- **Tests:**
  - ✓ `test_monotone_assignment_no_inversions` — uniform spec, 0 inversions.
  - ✓ `test_reversed_pins_minimized` — reversed source list order, monotone
    sort reorders to natural order, 0 inversions after placement.
  - ✓ `test_quotient_isomorphic_to_direct` — quotient+stamp lift ≅ direct
    route lift per floor, belt counts exactly 3×.
- **Done when:** synth uses monotone ordering and the quotient fast path, and
  the existing synth suite stays green. ✓

#### WP-M — channel-capacity placement *(replaces hand constraints; consumes router feedback)*

Build **after** WP-I (it consumes PathFinder's overuse output as feedback).

- ✅ **Row template:** `_compute_stages(abstract)` assigns each machine a BFS
  depth from sources. All machines at the same stage share a single `row_y`
  CP-SAT variable. Routing channels between rows (and between ports and the
  nearest row) have height ≥ 2 cells, enforced as `row_y[r] - row_y[r+1] >= 3`
  (1 row + 2 channel). This replaces the individual per-machine y-variables.
- **Density constraint (the heart):** per channel, per x-bucket of width 4:
  `(number of nets whose horizontal interval covers the bucket) ≤ h[c] ×
  floors_available`. A net's interval ends are reified from its endpoints'
  placement vars. Buckets stay coarse to bound model size. This is classic
  channel-routing density, and it is what "the placer reserves routing room"
  concretely means. **(Not yet implemented.)**
- ✅ **Delete the hand constraints** (y-stagger, 2-cell inter-group gap, port-row
  margin) — their effects emerge from the row model. Tests assert outcomes
  (round-trip, validation), never constraint presence.
- ✅ **Feedback loop:** `_lower()` catches `RoutingError`, adds overused cells
  to a `forbidden` set, and retries `place()` up to 3 times. `place()` accepts
  `forbidden: set[tuple[int, int]]` and excludes those cells from all machine
  flat positions.
  **(Future: map overused cells to channel/bucket for density feedback.)**
- ✅ **Hop direction constraints:** sender approach (fed from opposite the
  hop), receiver exit (continue in hop direction), terminal exit (hops to
  terminals must match boundary edge direction), no double-hop, root approach.
  `_resolve_hops` sender sort for deterministic pairing.
- ✅ **A\* heuristic:** `manhattan(cell, terminal) × BASE` as admissible
  heuristic in `_grow_tree`. Platform bounds from `platforms.json` replace
  the fixed-margin bounding box. 2×4 diagonal: 2.44s → 0.62s (3.9×).
- ✅ **North-star gate 1:** `test_synth_diagonal_full_belt_2x4` — 8-pair
  diagonal on Foundation_2x4 with hop\_range=4, 32/32 edges, validates +
  interprets to correct diagonals on all 16 lanes. **PASSES.**
- **Crossing budget check (§2a):** before solving, compare the pinned
  permutation's inversion count against total crossing capacity
  (floors + hops + channel slack); reject infeasible specs with a counting
  message.
- **North-star gate 2:** `test_synth_half_splitter_2x4` — the Half Splitter
  (§2a: 48 in south, cut, west halves out on `Region(western_faces)`, east
  halves on `Region(eastern_faces)`; full 3-D allowed) validates + interprets
  correctly, asserting per-kind belt counts and **region membership** of
  every output port — but **not** any specific slot assignment within a
  region. ✅ Multi-face port support landed (`_port_rotation_for`, optional
  `"face"` key on `platform_in`/`platform_out`). Still needs: `CutterSpec`,
  region-constrained output assignment. Record belts vs the human oracle
  where one exists (I7, tracked metric, soft target ≤ 2×).
- **Done when:** both north-star gates pass end-to-end (spec → assign → place
  → route → emit → lift → interpret).

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
- **Scaling arc (2026-06-10): ~~I~~ ✓ → {~~J~~ ✓, ~~K~~ ✓, ~~L~~ ✓} → M → north star**
  (the Half Splitter + the 48→96 full-belt diagonal extractor). WP-I done
  (negotiated congestion); WP-J done (lift calibration + 3-D tracing + lift
  edges in PathFinder); WP-K done (hop tracer + router); WP-L done (monotone
  sort + quotient stamping). **WP-M in progress:** row model + feedback loop
  landed; hop direction constraints landed; A\* heuristic landed (3.9×
  routing speedup); **first north-star gate passes**
  (`test_synth_diagonal_full_belt_2x4`); multi-face port support landed.
  Remaining: crossing budget check, Half Splitter gate (CutterSpec + region
  assignment).

### 7.4 Test infrastructure to build first
- `tests/conftest.py`: fixture loaders + the `CLOSED_FIXTURES` / `OPEN_FIXTURES`
  registry, and a `tiny_netlist(...)` builder (promote the helper from
  `tests/test_interpret.py::TestMultiPort`) for hand-built I4/I5 cases.
- Treat the deprecated `router.py` + `tests/test_router.py` as **out of the
  regression contract**; WP-C replaces them.
