# Route-Only Mode — Spec

**Status:** Draft, 2026-06-17. **Chunk 0a done** (2026-06-17): `_resolve_hops`
now scans `MAX_HOP_RANGE` down to 1 (furthest-first), matching the in-game
rule; identical 68/68 pairs on the Half Splitter, as predicted. **Chunk 0c
done** (2026-06-17): `lift.trace_upstream(bp, layer, start)` walks upstream
across hop boundaries (receiver -> paired sender via `_resolve_hops`) to the
originating machine cell. **Chunk 1 fixed** (2026-06-17): `route_only.py`'s
`find_and_classify_dangles` (already present, pre-dating this pass) was
crashing on hop-crossing dangles with a `KeyError`; it now calls
`lift.trace_upstream` instead of its own non-hop-aware walk. All 24 layer-0
dangles on the Half Splitter classify correctly. Chunk 0b (pathfinder hop
validity) deferred until Chunk 5 needs it. **Stale fixture counts fixed**:
`test_hop_pairing_half_splitter`, `test_hop_contraction_half_splitter`,
`test_strip_removes_interior_hops_half_splitter` hardcoded counts (145 pairs
/ 290 endpoints / 32 platform_out) mined from an earlier single-floor version
of the real blueprint; it's since been hand-edited into 3 symmetric layers,
so updated all three to the current per-layer counts (68 / 136 / 8 / 24
ports). **Chunk 2 done** (2026-06-17, reworked): `route_only.find_free_port_positions`
finds platform-edge port positions with no entity on the given layer — the
real routing targets (not the mirage of 46 "unconnected `platform_in`" from
the un-contracted netlist). On the Half Splitter layer 0: 24 free ports,
split 12 west / 12 east by platform-center x. **Chunk 3 done** (2026-06-17):
`route_only.match_dangles_to_ports` added (greedy nearest-neighbor by
Manhattan distance within a partition). On layer 0, all 12 west dangles and
all 12 east dangles match to a port. **Chunk 4
done** (2026-06-17): `route_only.build_passable_from_occupancy` added —
unlike `pathfinder._build_passable` (which only excludes machines, since
the full-synthesis path strips belts first), this excludes *every* occupied
cell except the supplied net endpoints, since route-only mode treats
existing belts as fixed obstacles too. **Chunk 0b done** (2026-06-17):
`pathfinder.RoutingGraph` gained `existing_senders`/`existing_receivers`
fields (`Cell -> launch direction`); `_grow_tree`'s hop-candidate evaluation
now rejects a candidate hop if a further pre-existing receiver (same
line/rotation) would steal the sender, or a further pre-existing sender
would steal the receiver, under the in-game furthest-first rule. A launch at
the full `hop_range` is always safe by construction (nothing can be
"further" within range). Empty dicts by default — zero behavior change on
the full-synthesis path, which has no pre-existing hops. 5 new unit tests in
`TestExistingHopValidity`.

**Chunk 5 UNBLOCKED** (2026-06-17): the blocker was a misunderstanding.
Chunks 2/3/5 used `trace_layer(bp, layer)` without `contract_hops=True`,
which treats interior hop endpoints as separate `platform_in`/`platform_out`
nodes — so all 46 interior hop receivers appeared "unconnected." With
`contract_hops=True`, the real netlist emerges: **0 unconnected
`platform_in`**, 16 real south-face input ports (all connected via 1→4
fan-out to 64 cutters), 8 real output ports on the west face at y=28–31
(already routed by the user), and **32 machine outputs with no outgoing
edge** (the cutter halves that haven't reached output ports yet). The 24
dangles are the downstream ends of those 32 unrouted outputs (some merge
before dangling). The routing targets are the **24 free platform-edge
output ports**: 4 on the west face (x=-18, y=8–11), 4 on the east face
(x=57, y=8–11), and 16 on the south face (y=2, 4 groups of 4). West-half
dangles route to western port groups, east-half to eastern.
**Chunks 0a/0b/0c/1/2/3/4 are solid and tested.** **Chunk 5 done**
(2026-06-17): `route_only.build_routing_nets` builds a 1→1 fanout `Net`
per matched (dangle, port) pair — root offset one cell off the dangle in
its dangling-output direction, terminal offset one cell off the port in
its interior-facing direction (`route_only._port_face`, calibrated
against placed `BeltPortSenderInternalVariant` rotations in the reference
corpus: east edge R0/fed-from-west, north R1/fed-from-south, west
R2/fed-from-east, south R3/fed-from-north). `route_only.route_layer_nets`
chains chunks 1-5: find/classify dangles, find/partition free ports,
match, build nets, build the passable set (endpoints = all net
roots/terminals), build pre-existing hop sender/receiver positions
(`route_only._existing_hop_endpoints`, feeds `RoutingGraph.existing_*`
from §0b) and run `pathfinder.pathfinder_route`. On the real fixture
(UNFINISHED Half Splitter, layer 0): all 24 nets route successfully in
~1.3s, `pathfinder.emit_entities` converts them to 720 valid belt
entities with no errors. `route_only._attach_boundary_edges` inserts the
dangle->root and terminal->port edges after routing so the emit table
sees correct in/out directions at the tree's boundary cells — neither
the dangle cell (already a real entity) nor the port cell (placed during
merge) is added to `tree_cells` itself. **Chunk 6 done** (2026-06-17):
`route_only._port_sender_entities` builds a `BeltPortSenderInternalVariant`
for each net's matched port — position and rotation recovered from
`net.terminals[0] + net.terminal_exit[term]` (the port cell) and
`route_only._port_face` (the calibrated outward rotation), since the port
cell itself is never a routing cell. `route_only.merge_entities` appends
new entities (routing belts + port senders) to the blueprint's existing
entity list via `route._rebuild_blueprint`, raising `ValueError` on any
position collision (would indicate a passable-set bug, not an expected
outcome). `route_only.route_and_merge(bp, layer, hop_range=...)` chains
Chunks 1-6 end-to-end. On the real fixture (UNFINISHED Half Splitter,
layer 0): `lift.unmatched_legs` drops from 24 to 0, no entity-position
collisions, and `lift.trace_layer(..., contract_hops=True)` shows new
`platform_out` edges at all 24 previously-free ports. Chunk 7 (CLI
integration: `shapez2 route`) is next.

**Motivation:** The user has a hand-placed Half Splitter blueprint
(`UNFINISHED Half Splitter.spz2bp`) with 192 cutters across 3 symmetric
layers, all machine outputs routed, but 24 dangling belt ends per layer
(72 total) that need routing to platform input ports. Hand-routing these
is tedious; the existing `place` command re-places *and* re-routes from
scratch, which destroys the hand-tuned layout. A route-only mode keeps
existing placement and belts fixed and routes only the missing
connections.

**North star:** `shapez2 route input.spz2bp -o output.spz2bp` — take a
half-completed blueprint, identify unrouted connections, route them, emit
a complete blueprint.

---

## §0. Definitions

- **Dangling end**: a belt or merger cell whose output points into empty
  space (no matching input on the adjacent cell). Found by
  `lift.unmatched_legs`'s scan — each unmatched output-side leg is a
  dangling end.
- **Free port position**: a platform-edge port slot with no entity on the
  layer. These are the routing targets — each needs a
  `BeltPortSenderInternalVariant` placed at it and a belt path feeding it.
- **Occupied cell**: any (x, y) position on a given layer that already
  contains a belt, machine, port, or other entity. These are obstacles
  for the router.
- **West/east half**: a cutter produces two outputs — the west half
  (left output) and east half (right output) of the input shape.
  Absolute orientation; rotation doesn't change which half is which.

---

## §1. Pipeline overview

Per layer (0, 1, 2), independently, `lift_enabled=False`:

1. **Lift** — `trace_layer(bp, layer)` to get the current netlist.
2. **Find dangles** — scan occupancy for unmatched output legs pointing
   into empty space.
3. **Classify dangles** — trace each dangle upstream through the belt
   graph to the cutter output that produced it. Label it west-half or
   east-half based on which cutter port it traces back to.
4. **Find free output ports** — identify platform-edge port positions
   not already used by the netlist (requires `contract_hops=True` to
   avoid counting interior hop receivers as unconnected ports).
5. **Partition ports** — determine which port groups are west-targets
   and which are east-targets. The user's existing routed connections
   (the SE/SW port groups) establish the convention; the remaining
   port groups follow the same east/west split by position.
6. **Match** — within each partition (west dangles → west port groups,
   east dangles → east port groups), assign dangles to ports by
   nearest-neighbor or minimum-cost matching.
7. **Build passable set** — `platform_bounds − all_occupied_cells` on
   this layer only.
8. **Route** — `pathfinder.pathfinder_route` on the matched nets,
   `hop_range` from platform geometry, `lift_enabled=False`.
9. **Emit** — convert routed nets to belt entities, merge with
   existing blueprint entities (no stripping).

Repeat for each layer, then write the combined result.

---

## §2. Chunk breakdown

### Chunk 0: Fix hop pairing + hop-aware upstream trace in `lift.py`

Two pieces: a bug fix in `_resolve_hops` and a new `trace_upstream`
function.

#### 0a: Fix `_resolve_hops` — furthest-first pairing

**Bug:** `_resolve_hops` scans `range(1, MAX_HOP_RANGE + 1)` and
takes the first (nearest) matching receiver. The in-game rule
([Shapez 2 Wiki — Conveyor Belt](https://shapez2.wiki.gg/wiki/Conveyor_Belt))
is:

> "A launcher will try to connect to the **furthest** catcher in
> range."
> "If there are multiple launchers trying to connect to a single
> catcher, the launcher **furthest** from the catcher will be chosen."

**Fix:** Reverse the scan to `range(MAX_HOP_RANGE, 0, -1)`.

This produces identical results on all existing test blueprints
(UNFINISHED Half Splitter: 68/68 same; Launchers template: 30/30
same) because their layouts have no ambiguous pairings. But the
nearest-first rule is wrong in the general case — relay chains where
multiple receivers are in range of one sender will mispair.

**Sender processing order also matters** when multiple launchers
compete for the same catcher. The wiki says the furthest launcher
wins. The current sort key
(`dx*x + dy*y` ascending within each rotation) processes the
sender whose items arrive first at receivers. This needs review:
the game likely resolves ties by giving priority to the
furthest launcher, not the one whose items arrive first. For now,
reversing the distance scan is the critical fix; sender ordering
can be revisited if a test case surfaces.

**Tests:**
- All existing hop-dependent tests must still pass (regression).
- New test with a relay chain fixture: 3 senders and 3 receivers
  in a line, spacing such that nearest-first would mispair but
  furthest-first pairs correctly.

#### 0b: Pathfinder hop validity under furthest-first

**Problem:** The pathfinder places physical sender/receiver entities.
When the game loads the blueprint, it applies furthest-first pairing
to ALL launchers and catchers — including ones the pathfinder just
placed. If the pathfinder places a short hop but another catcher
exists further along the same lane, the game pairs the sender with
that further catcher, breaking the intended routing.

This is critical for route-only mode: new hops are placed into a
blueprint with existing launchers and catchers. Cross-interference
between old and new hops is a real risk.

**Constraints the pathfinder must enforce:**

1. **Sender validity:** when placing a sender at `(sx, sy)` facing
   direction `(dx, dy)`, verify that no catcher exists at any
   position `(sx + dx*d, sy + dy*d)` for `d` in
   `(hop_dist+1 .. MAX_HOP_RANGE)` with the same rotation. If one
   does, the game would pair the sender with that further catcher
   instead of the intended one. Either skip this hop candidate or
   ensure the intended receiver is the furthest in range.
2. **Receiver validity:** when placing a receiver at `(rx, ry)`,
   verify that no sender exists further away (in the opposite
   direction) within `MAX_HOP_RANGE` that would claim this receiver
   under the furthest-first rule. If a further sender exists and
   hasn't already paired with a closer receiver, it would steal
   this one.

**Where it lives:** `pathfinder.py`, in the hop candidate evaluation
inside `_grow_tree` (~line 272). Add a validity check before
accepting a hop candidate. The check needs access to existing
sender/receiver positions — pass them into `RoutingGraph` or build
them from the blueprint's occupancy.

**Scope for the MVP:** For route-only mode, the existing blueprint's
sender/receiver positions are known. New hops placed by the
pathfinder must not conflict with them. The simplest approach: after
building the passable set, also build a set of existing
sender/receiver positions and their rotations. The hop candidate
check in `_grow_tree` queries this set.

For the existing synthesis path (full re-route from scratch with no
pre-existing hops), this constraint is automatically satisfied if
the pathfinder doesn't place conflicting hops with itself — which
the current tree-growth already prevents (a cell used by one net
is occupied, so another net can't place a catcher there). The new
constraint only triggers when pre-existing hops are present.

**Tests:**
- Place a new hop near an existing catcher that's further along the
  same lane. Verify the pathfinder rejects the short hop or adjusts
  to avoid the conflict.
- Route-only integration test on a blueprint with dense existing
  hops: verify all hop pairs in the output resolve correctly under
  furthest-first.

#### 0c: Hop-aware upstream trace

**Problem:** There is no function that walks upstream through the belt
graph across hop boundaries. `_occupancy` gives per-cell data and
`_resolve_hops` gives sender→receiver pairs, but nothing composes them
into a connected upstream walk. `BeltPortReceiver` and
`BeltPortSender` both have `is_belt = False`, so a naive "stop at
first non-belt" trace terminates at the first hop catcher instead of
reaching the machine that produced the shape.

**Input:** Blueprint, layer index, starting position `(x, y)`.

**Output:** The terminal non-belt, non-port cell `(x, y)` and its
`_Cell` — typically a machine (cutter) output cell.

**Algorithm:**

1. Build occupancy via `_occupancy(bp, layer)`.
2. Build hop pair lookup via `_resolve_hops(bp, layer,
   _platform_port_positions(bp))` — produces a `dict[receiver_pos,
   sender_pos]` for reverse lookups (given a receiver, find its
   sender).
3. Starting from `(x, y)`, walk upstream:
   a. If current cell `is_belt`: follow `ins` to the upstream cell.
   b. If current cell is a `BeltPortReceiver`: look up its paired
      sender in the hop table. Jump to the sender position.
   c. If current cell is a `BeltPortSender`: it has `is_belt = False`
      but is NOT a terminal. Follow its `ins` to continue upstream
      (the sender receives items from a belt feeding into it).
   d. If current cell is a machine (not a belt, not a port): stop.
      This is the terminal.
4. Return the terminal position and cell.

**Where it lives:** `lift.py` as `trace_upstream(bp, layer, start) →
(pos, _Cell)`. This is general-purpose infrastructure, not
route-only-specific. The hop pair table can be cached per
`(bp, layer)` call.

**Existing code to reuse:**
- `lift._occupancy` for the cell map.
- `lift._resolve_hops` (fixed in 0a) for hop pair resolution.
- `lift._platform_port_positions` for port position filtering.
- `lift.kind()` to distinguish machine cells from port cells (but
  note: `kind()` currently misclassifies interior hop endpoints as
  platform IO — see generator-spec.md §7.2 WP-N task 1. Use the
  entity type string directly: `"BeltPortReceiver"` / `"BeltPortSender"`
  substrings, not `kind()`).

**New code:**
- `lift.trace_upstream(bp, layer, start) → tuple[tuple[int, int], _Cell]`

**Tests:**
- On the UNFINISHED Half Splitter, layer 0: trace from each of the
  24 dangle positions. All 24 should terminate at a cutter cell
  (anchor entity contains `"Cutter"`). Zero should terminate at a
  `BeltPortReceiver`.
- On a small fixture with one cutter, one hop, one belt: verify the
  trace crosses the hop and reaches the cutter.

---

### Chunk 1: Find dangles and classify west/east

**Input:** Blueprint, layer index.

**Output:** List of `(x, y, half)` where `half` is `"west"` or
`"east"`.

**Algorithm:**

1. Build occupancy via `lift._occupancy(bp, layer)`.
2. For each cell in occupancy, check each output direction. If the
   target cell has no matching input (same logic as
   `lift.unmatched_legs`), record `(x, y)` as a dangling end.
3. For each dangle, call `lift.trace_upstream(bp, layer, pos)` (from
   chunk 0) to walk upstream across hops to the originating cutter
   cell.
4. The terminal machine cell belongs to a cutter. Check whether this
   cell is the cutter's west output or east output:
   - Get the cutter's anchor and rotation from the occupancy.
   - Use `lift._machine_footprint(type, rotation)` to find the
     footprint. The cutter has two output cells; the one at the
     "left" offset (relative to flow direction) is the west half, the
     "right" is the east half.
   - For `CutterDefaultInternalVariant`: at R=0, the west output is
     at `(0, 1)` (left of flow) and east at `(1, 1)` (right of flow).
     For `CutterDefaultInternalVariantMirrored`: swapped.
   - Determine which output cell the traced path arrived at. Label
     accordingly.

**Edge cases:**
- A dangle may trace through multiple mergers (4→1 fan-in from 4
  cutters). All 4 cutters produce the *same* half (west or east), so
  any cutter reached gives the correct label.
- A dangle may trace to a splitter (1→2 fan-out). Follow upstream
  through the splitter's input side.
- Hop traversal edge cases are handled by chunk 0's
  `trace_upstream`.

**Existing code to reuse:**
- `lift._occupancy` for the cell map.
- `lift._machine_footprint` for cutter port identification.
- `lift.unmatched_legs` logic for dangle detection (refactor to return
  positions instead of just a count).

**New code:**
- `route_only.find_dangles(bp, layer) → list[tuple[int, int]]`
- `route_only.classify_dangle(pos, occupancy) → str` ("west"/"east")
- Or combined:
  `route_only.find_and_classify_dangles(bp, layer) → list[DanglingEnd]`
  where `DanglingEnd` is a dataclass with `x, y, half`.

**Tests:**
- Unit test on the UNFINISHED Half Splitter: find 24 dangles on layer
  0, all classified as west or east, counts match (12 west, 12 east
  — or whatever the actual split is).
- Unit test on a small hand-built fixture with 1 cutter + 1 dangling
  belt: traces back correctly, classifies correctly.

---

### Chunk 2: Find free platform-edge output ports and partition west/east

**Critical:** use `trace_layer(bp, layer, contract_hops=True)` to get
the real netlist. Without `contract_hops`, interior hop receivers
appear as 46 unconnected `platform_in` nodes — a mirage. With it, the
real picture: 16 south-face inputs (all connected), 8 output ports
(user-routed), and 32 machine outputs with no path to output ports.

**Input:** Blueprint, layer index, platform name.

**Output:** Two lists: `west_ports` and `east_ports`, each a list of
`(x, y)` positions of free platform-edge output ports.

**Algorithm:**

1. Load platform port positions from `platforms.json`.
2. Lift with `contract_hops=True` to get the real netlist.
3. Find occupied port positions: any platform-edge port that already
   has an entity on this layer.
4. Free ports = all platform-edge positions minus occupied.
5. Partition free ports into west-target and east-target:
   - The platform has a center x-coordinate.
   - Port groups west of center are west-targets (receive west-half
     shapes).
   - Port groups east of center are east-targets (receive east-half
     shapes).
   - This matches the user's convention: east halves go to eastward
     ports, west halves to westward ports.

On the UNFINISHED Half Splitter: 24 free ports (4 west face y=8–11,
4 east face y=8–11, 16 south face y=2 in 4 groups of 4). Exactly
matching the 24 dangles.

**Edge cases:**
- Ports on multiple faces (south, west, east). All partition by
  east/west of center.

**Existing code to reuse:**
- `lift.trace_layer` (with `contract_hops=True`) for the netlist.
- `pathfinder._platform_bounds` for platform center.
- `lift._platform_port_positions` for all port positions.

**New code:**
- `route_only.find_free_output_ports(bp, layer, platform) → list[tuple[int, int]]`
- `route_only.partition_ports(ports, platform) → (west, east)`

**Tests:**
- Unit test on UNFINISHED Half Splitter: 24 free ports found (not 46),
  partitioned 12 west / 12 east.

---

### Chunk 3: Match dangles to ports

**Input:** `west_dangles`, `west_ports`, `east_dangles`, `east_ports`.

**Output:** List of `(dangle_pos, port_pos)` pairs — the nets to route.

**Algorithm:**

1. Within each partition, compute pairwise Manhattan distances.
2. Use greedy nearest-neighbor matching: sort all (dangle, port)
   pairs by distance, greedily assign the closest unmatched pair.
   (Hungarian algorithm is better but overkill for 12×N matching.)
3. If `len(dangles) != len(available_ports)` within a partition,
   that's a warning — some ports will be unmatched. Route what we
   can.

**New code:**
- `route_only.match_dangles_to_ports(dangles, ports) → list[tuple]`

**Tests:**
- Unit test: given known dangle and port positions from the
  UNFINISHED Half Splitter, verify each dangle is matched to a
  geographically sensible port.

---

### Chunk 4: Build passable set from existing occupancy

**Input:** Blueprint, layer index, platform name.

**Output:** `set[Cell]` of passable (x, y, layer) cells.

**Algorithm:**

1. Get platform bounds via `pathfinder._platform_bounds(platform)`.
2. Build occupancy via `lift._occupancy(bp, layer)`.
3. Passable = all cells within platform bounds that are NOT in the
   occupancy map (i.e. not occupied by any entity — belt, machine,
   port, anything).
4. Exclude the platform-edge ring (same logic as
   `pathfinder._build_passable`) except for the specific port cells
   that are net endpoints.
5. The dangling end cells and free port cells must be in the passable
   set (they are net endpoints — the router needs to reach them).
   Dangles already have entities; free ports do not (yet).

**Key difference from existing `_build_passable`:** the existing
function excludes only machines; this one excludes *everything* that's
already placed (machines + belts + ports + mergers + splitters). The
only entities in passable are the net endpoints themselves.

**Existing code to reuse:**
- `pathfinder._platform_bounds`.
- `lift._occupancy` for the full cell map.

**New code:**
- `route_only.build_passable_from_occupancy(bp, layer, platform, endpoints) → set[Cell]`

**Tests:**
- Unit test: passable set on UNFINISHED Half Splitter layer 0 has no
  overlap with occupied cells (except endpoints). Verify a known free
  cell is passable and a known belt cell is not.

---

### Chunk 5: Build nets and route

**Input:** Matched pairs from chunk 3 (each pair is
`(dangle_pos, free_port_pos)`), passable set from chunk 4, platform
geometry.

**Output:** Routed `Net` objects with `tree_cells` and `tree_edges`.

**Corrected model (2026-06-17):** The routing targets are free
platform-edge output ports, NOT interior hop receivers. The dangles
are cutter-output belt ends pointing south; they need belt paths
running south/west/east to reach platform-edge ports where items
leave the platform. No new hops to interior receivers — those are
already connected (visible only with `contract_hops=True`).

**Algorithm:**

1. For each `(dangle, port)` pair, create a `pathfinder.Net`:
   - The dangle outputs south into empty space. Items flow from the
     cutter through the existing belt network to the dangle, then
     need to continue south/laterally to the platform-edge port.
   - `kind="fanout"`, `root` = dangle endpoint, `terminal` = port.
   - The root is the first free cell south of the dangle:
     `(dangle_x, dangle_y - 1, layer)`. The dangle's existing belt
     outputs south into this cell, so the router starts there. The
     dangle cell itself already has an entity and must not be
     overwritten.
   - The terminal is the platform-edge port position. Platform-edge
     ports are on the ring (y=2 for south, x=-18 for west, x=57 for
     east). The port cell must be in the passable set.
2. Set approach/exit directions:
   - Root approach: `(0, -1)` (south — continuing the dangle's output
     direction).
   - Terminal exit: depends on port face. South-face ports (y=2) need
     items arriving from the north `(0, 1)`. West-face ports (x=-18)
     need items arriving from the east `(1, 0)`. East-face ports
     (x=57) need items from the west `(-1, 0)`. Derive from port
     rotation in `platforms.json`.
3. Build `pathfinder.RoutingGraph` with the passable set,
   `hop_range=MAX_HOP_RANGE` (or from platform), `lift_enabled=False`.
   Pass existing sender/receiver positions for hop validity (chunk
   0b).
4. Run `pathfinder.pathfinder_route` (or `_route_by_group` if >24
   nets).
5. If routing fails, report which nets failed and their positions.

**Existing code to reuse:**
- `pathfinder.Net`, `RoutingGraph`, `pathfinder_route`,
  `_route_by_group`.
- `pathfinder._cell_to_entity`, `emit_entities` for emit.

**New code:**
- `route_only.build_nets_for_routing(matched_pairs, bp, layer) → list[Net]`
- Most of the routing call is existing; the new part is net
  construction and the passable set.

**Tests:**
- Integration test: route 1 matched pair on a small fixture, verify
  the routed net's tree connects port to dangle with valid belt
  entities.

---

### Chunk 6: Emit and merge

**Input:** Routed nets, original blueprint.

**Output:** New blueprint with routed belt entities added (not
replacing — merging).

**Algorithm:**

1. Convert routed nets to belt entities via
   `pathfinder._cell_to_entity` / `emit_entities`.
2. Collect existing entities from the original blueprint (all layers).
3. Concatenate new belt entities with existing entities.
4. Rebuild the blueprint via `route._rebuild_blueprint`.

**Key difference from existing `strip_and_reroute`:** no stripping
step. The existing entities are kept verbatim; new belt entities are
added in previously-empty cells.

**Collision check:** before emitting, verify no new entity overlaps
an existing entity. If overlap detected, that's a routing bug (the
passable set should have prevented it).

**Existing code to reuse:**
- `pathfinder.emit_entities` or `_cell_to_entity`.
- `route._rebuild_blueprint`.
- `route._all_entities` to extract existing entities.

**New code:**
- `route_only.merge_entities(bp, new_entities) → Blueprint`

**Tests:**
- After merge, `lift.unmatched_legs(result, layer)` should be
  reduced (ideally 0 on the routed layer, but may not be 0 if some
  ports were intentionally left unmatched).
- After merge, `lift.trace_layer(result, layer)` should show new
  edges connecting the previously-free ports.
- No entity at the same (x, y, layer) appears twice.

---

### Chunk 7: CLI integration

**New command:** `shapez2 route`

```
shapez2 route input.spz2bp -o output.spz2bp [--platform NAME] [--layer N] [--hop-range N] [--viz]
```

**Arguments:**
- `input.spz2bp` — the half-completed blueprint.
- `-o output.spz2bp` — output path (required).
- `--platform NAME` — override platform type (default: read from
  blueprint).
- `--layer N` — route only this layer (default: all layers 0–2).
- `--hop-range N` — override hop range (default: `MAX_HOP_RANGE`).
- `--viz` — generate HTML visualization after routing.

**Behavior:**
1. Load blueprint.
2. For each layer (or the specified layer):
   a. Run chunks 1–6.
   b. Report: dangles found, classified (N west, N east), ports
      matched, routing result (success/failure, time).
3. Write output blueprint.
4. Run `lift.unmatched_legs` on the result and report.
5. If `--viz`, generate visualization.

**New code:**
- `cli.cmd_route(args)` — thin wrapper calling `route_only` module
  functions.
- Add `route` subparser to `cli.main()`.

**Tests:**
- End-to-end test: `cmd_route` on UNFINISHED Half Splitter produces
  a blueprint with fewer unmatched legs.

---

## §3. File layout

All new code goes in `src/shapez2_tools/route_only.py`. This module
imports from `lift`, `pathfinder`, `route`, and `blueprint`.

Functions (public API):

```python
def find_and_classify_dangles(bp: Blueprint, layer: int) -> list[DanglingEnd]
def find_free_port_positions(bp: Blueprint, layer: int) -> list[tuple[int, int]]
def partition_ports(ports, platform: str) -> tuple[list, list]
def match_dangles_to_ports(dangles, ports) -> list[tuple]
def build_passable_from_occupancy(bp, layer, platform, endpoints) -> set[Cell]
def build_routing_nets(matched_pairs, bp, layer) -> list[Net]
def route_and_merge(bp: Blueprint, layer: int, platform: str, ...) -> Blueprint
```

`route_and_merge` is the top-level function that chains chunks 1–6.
`cmd_route` in `cli.py` calls `route_and_merge` per layer.

---

## §4. What this does NOT do

- **No re-placement.** Machines stay where they are.
- **No re-routing of existing belts.** Existing belt entities are
  immovable obstacles.
- **No lift/elevator routing.** `lift_enabled=False` for the MVP.
  Each layer routes independently.
- **No chained launcher trick.** The pathfinder uses standard hops
  (launch over empty space) but not the dense sender/receiver
  chaining pattern from `TEMPLATES/Launchers.spz2bp`. If routing
  fails due to congestion, this is the upgrade path.
- **No lane-to-port-group assignment.** The MVP uses nearest-neighbor
  matching within the west/east partition. Future: user specifies
  "lane N's outputs go to port group Y."
- **No fan-in/fan-out net construction.** Each net is 1→1
  (port→dangle). The fan-in mergers are already built by the user;
  the router just connects the remaining straight runs.

---

## §5. Sequencing

Build and test in order:

0. **Chunk 0a** (fix `_resolve_hops` furthest-first) — pure bug fix
   in `lift.py`. Regression-safe (identical results on current
   blueprints). No dependencies.
   **Chunk 0b** (pathfinder hop validity) — depends on understanding
   from 0a. Adds pre-existing hop awareness to `_grow_tree` in
   `pathfinder.py`. Required for route-only mode where new hops
   coexist with existing ones. Can be deferred for the full-synth
   path (no pre-existing hops).
   **Chunk 0c** (hop-aware upstream trace) — depends on 0a.
   General-purpose infrastructure in `lift.py`. Test against
   UNFINISHED Half Splitter: all 24 dangles trace to cutters.
1. **Chunk 1** (find + classify dangles) — depends on chunk 0c. Test
   standalone against the UNFINISHED Half Splitter fixture.
2. **Chunk 2** (find + partition ports) — depends on lift, testable
   standalone.
3. **Chunk 3** (match) — depends on chunks 1–2, pure logic, easy to
   test.
4. **Chunk 4** (passable set) — depends on lift occupancy, testable
   standalone.
5. **Chunk 5** (build nets + route) — depends on chunks 0b, 3–4.
   Uses existing pathfinder with hop validity checks. Integration
   test.
6. **Chunk 6** (emit + merge) — depends on chunk 5, uses existing
   emit code. Integration test.
7. **Chunk 7** (CLI) — thin wrapper, depends on all chunks. End-to-end
   test.

Each chunk is a standalone PR-able unit with its own tests.

---

## §6. Test plan

### Fixture
Copy `UNFINISHED Half Splitter.spz2bp` to `data/reference/` for test
use. It's the primary integration fixture.

### Unit tests (per chunk)
- Chunk 1: `test_find_dangles_half_splitter` — 24 dangles on L0,
  classified west/east.
- Chunk 2: `test_free_port_positions_half_splitter` — 24 free ports,
  partitioned 12 west / 12 east.
- Chunk 3: `test_match_dangles_to_ports` — matched pairs are
  geographically sensible.
- Chunk 4: `test_passable_excludes_existing_belts` — no occupied cell
  in passable set.
- Chunk 5: `test_route_single_pair` — one net routes successfully on
  a small fixture.

### Integration tests
- `test_route_layer_0_half_splitter` — full pipeline on layer 0:
  dangles found, classified, matched, routed, merged. Result has
  `unmatched_legs(result, 0) < 24`. Ideally 0.
- `test_route_all_layers_half_splitter` — all 3 layers routed.
  Result has `unmatched_legs == 0` on all layers.
- `test_no_entity_overlap` — after merge, no two entities share the
  same `(x, y, layer)`.
- `test_lift_trace_new_edges` — the routed blueprint's netlist
  contains new `machine → platform_out` edges that didn't exist
  before.

### Acceptance
The routed UNFINISHED Half Splitter loads in-game, all belts connect,
items flow from south inputs through cutters to correct output ports
(west halves to west ports, east halves to east ports).
