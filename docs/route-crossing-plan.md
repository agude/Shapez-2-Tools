# Route-only crossing-route plan

## Problem

The `_classify_dangle` fix (anchor = east half, always, regardless of
mirroring) is semantically correct but creates 12 routes that must cross the
full 76-cell platform width (Manhattan distances 54--78). All 24 routes
compete for the narrow free corridor at y=3--16 (~1000 passable cells). The
pathfinder fails with 28 overused cells after 60 iterations.

The router already supports **hops** (launcher/receiver pairs that teleport
2--5 cells, skipping intermediates). Hops are the in-game mechanism for
multiplexing: two belts can share the same row if one of them hops over the
other. The fix is making the route-only pipeline use hops more effectively for
crossing routes.

## Geometry budget

Free corridor: rows y=3--13 fully free (11 rows x 74 cols = 814 cells), rows
y=14--16 partially free (~180 cells). ~1000 total.

12 crossing routes at ~60 cells each = 720 cells of demand. Each hop saves
~3 cells (5-cell jump costs only sender + receiver). Heavy hop usage should
bring demand well under budget.

## Chunks (simplest first)

### Chunk 1: Optimal matching (replace greedy with min-cost) — DONE

**What:** Replace `match_dangles_to_ports` with a min-cost bipartite matching
that minimizes total Manhattan distance across all pairs simultaneously.

**Why:** The greedy matcher pairs closest first, giving nearby dangles the
nearby ports and forcing far dangles onto the worst remaining ports. An optimal
matching distributes wire-length more evenly and can reduce maximum route
length significantly.

**Result:** `_optimal_match` added using `scipy.optimize.linear_sum_assignment`.
Falls back to greedy if scipy unavailable. `route_layer_nets` now calls
`_optimal_match`. On the Half Splitter fixture, total Manhattan distance
dropped from 1244 to 1220 (1.9% improvement) — the greedy matcher was already
fairly good on this layout, but optimal avoids worst-case long routes.

**Commit scope:** `route_only.py`, `pyproject.toml`, `tests/test_route_only.py`.

---

### Chunk 2: Lower hop penalty for route-only mode

**What:** Add a `hop_penalty` parameter to `RoutingGraph` (default =
`HOP_PENALTY = 1.5`) and let `route_layer_nets` pass a lower value (e.g.
`0.5`) so the router prefers hops over long detours.

**Why:** The current `HOP_PENALTY = 1.5` was tuned for synthesis (where hops
are a last resort). In route-only mode with dense crossing traffic, hops are
the *intended* mechanism -- a lower penalty encourages the router to use them
freely, compressing each crossing route from ~60 cells to ~20 cells of actual
passable-cell demand.

**Implementation:**
- Add `hop_penalty: float = HOP_PENALTY` field to `RoutingGraph`.
- In `_grow_tree`, replace the constant `HOP_PENALTY` reference on the
  hop-cost line with `graph.hop_penalty`.
- In `route_layer_nets`, pass `hop_penalty=0.5` (or a parameter) when
  constructing the `RoutingGraph`.

**Test:**
- Unit test: build a small 2-net crossing scenario on Foundation_1x1, verify
  both route when hop_penalty is low but one fails when it's high.
- Re-run `route` on UNFINISHED Half Splitter layer 0 -- check improvement.

**Commit scope:** `pathfinder.py`, `route_only.py`,
`tests/test_route_only.py`.

---

### Chunk 3: Two-phase routing (local first, crossing second)

**What:** Split nets into "local" (dangle and port on same side) and
"crossing" (opposite sides) groups. Route local nets first, then crossing
nets, so crossing nets see the local nets' cells as obstacles and are forced
to use the remaining free corridor + hops.

**Why:** Local nets are short and easy. If routed first, they claim cells near
the ports and leave the wide central corridor for crossing traffic. Without
this, the pathfinder tries to negotiate all 24 nets simultaneously, and the
short nets steal corridor cells from the long ones.

**Implementation:**
- In `route_layer_nets`, after building nets, partition them: a net is
  "crossing" if its root and terminal are on opposite sides of the platform
  center-x.
- Route local nets first via `pathfinder_route(local_nets, graph)`.
- Freeze their cells in the occupancy map.
- Route crossing nets via `pathfinder_route(crossing_nets, graph)`.

**Test:**
- Unit test: build a 4-net scenario (2 local, 2 crossing) on Foundation_1x1,
  verify all route.
- Integration: UNFINISHED Half Splitter layer 0 routes to 0 overused cells.

**Commit scope:** `route_only.py`, `tests/test_route_only.py`.

---

### Chunk 4: Dedicated hop lanes (last resort)

**What:** If negotiated routing still fails, pre-allocate "hop lanes" -- full
platform-width rows in the free corridor reserved for crossing traffic. Each
lane is a row where only hop senders/receivers are placed, at regular
intervals, forming a highway that crossing routes share.

**Why:** The pathfinder's negotiation can fail when too many crossing routes
compete for the same narrow corridor. Pre-allocated lanes guarantee capacity.
Each row can carry multiple independent hops simultaneously (a hop occupies
only sender + receiver cells; the cells in between are free for other hops
that don't conflict).

**Implementation:**
- Before routing, identify free rows in the corridor.
- For each crossing net, assign it a hop-lane row.
- Build the net's path to enter the lane, hop across, and exit to the port.
- This bypasses the pathfinder for the crossing portion, using it only for
  the entry/exit segments.

**Test:**
- Integration: UNFINISHED Half Splitter layer 0 routes with 0 unmatched legs.
- Verify interpret produces correct east/west halves at all output ports.

**Commit scope:** `route_only.py`, possibly `pathfinder.py`,
`tests/test_route_only.py`.

## Execution order

Try each chunk, test, and commit. Stop when UNFINISHED Half Splitter routes
to 0 unmatched legs on all 3 layers and interpret confirms correct halves.
