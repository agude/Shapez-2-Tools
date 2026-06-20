"""WP-I: PathFinder negotiated-congestion router.

Replaces sequential A* (route.py) with negotiated-congestion routing
(McMurchie & Ebeling 1995 / VPR PathFinder). Every net is routed optimally
allowing overlaps, then iteratively re-priced until no cell is shared.

The emit table is the programmatic inverse of ``lift.routing_inout`` — one
shared calibration table, both directions.
"""

from __future__ import annotations

import heapq
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

from shapez2_tools import lift
from shapez2_tools.blueprint import Blueprint
from shapez2_tools.generator import Entity
from shapez2_tools.route import _all_entities, _rebuild_blueprint, strip_belts

N, S, E, W = lift.N, lift.S, lift.E, lift.W

Cell = tuple[int, int, int]

# Parameters — §7.2 WP-I spec.
BASE = 1.0
PRES_FAC_INIT = 0.5
PRES_FAC_MULT = 1.8
HIST_GAIN = 1.0
MAX_ITERS = 60
HOP_PENALTY = 1.5
LIFT_COST = 2.0
SYMMETRY_BREAK = 1e-4

LEGAL_LEG_PATTERNS: set[tuple[int, int]] = {
    (1, 1),
    (1, 2),
    (1, 3),
    (2, 1),
    (3, 1),
}


class RoutingError(Exception):
    """Routing failed — carries diagnostic data for WP-M placement feedback."""

    def __init__(self, message: str, overused: list[Cell] | None = None):
        super().__init__(message)
        self.overused = overused or []


@dataclass
class Net:
    net_id: int
    kind: Literal["fanout", "fanin"]
    root: Cell
    terminals: list[Cell]
    root_offset: bool = False
    root_approach: tuple[int, int] | None = None
    terminal_exit: dict[Cell, tuple[int, int]] = field(default_factory=dict)
    tree_cells: set[Cell] = field(default_factory=set)
    tree_edges: list[tuple[Cell, Cell]] = field(default_factory=list)
    hop_edges: set[tuple[Cell, Cell]] = field(default_factory=set)
    lift_edges: set[tuple[Cell, Cell]] = field(default_factory=set)
    group: int | None = None


@dataclass
class RoutingGraph:
    passable: set[Cell]
    hop_range: int = 0
    lift_enabled: bool = False
    base: dict[Cell, float] = field(default_factory=dict)
    hist: dict[Cell, float] = field(default_factory=dict)
    occ: dict[Cell, set[int]] = field(default_factory=lambda: defaultdict(set))
    # Pre-existing (already-placed) hop sender/receiver positions -> launch
    # direction, for route-only mode where new hops coexist with old ones
    # (§0b). Empty for the full-synthesis path (belts are stripped first,
    # so there are no pre-existing hops to conflict with).
    existing_senders: dict[Cell, tuple[int, int]] = field(default_factory=dict)
    existing_receivers: dict[Cell, tuple[int, int]] = field(default_factory=dict)
    hop_penalty: float = HOP_PENALTY
    reserved: dict[Cell, int] = field(default_factory=dict)
    sym_seed: int = 0

    def __post_init__(self):
        if self.hop_range > lift.MAX_HOP_RANGE:
            raise ValueError(
                f"hop_range={self.hop_range} exceeds the in-game launcher/catcher "
                f"limit of {lift.MAX_HOP_RANGE} (QUESTIONS.md Q7)"
            )
        for c in self.passable:
            self.base.setdefault(c, BASE)
            self.hist.setdefault(c, 0.0)


def _neighbors(cell: Cell) -> list[Cell]:
    x, y, ly = cell
    return [(x + 1, y, ly), (x - 1, y, ly), (x, y + 1, ly), (x, y - 1, ly)]


def _direction(src: Cell, dst: Cell) -> tuple[int, int]:
    return (dst[0] - src[0], dst[1] - src[1])


def _unit_direction(src: Cell, dst: Cell) -> tuple[int, int]:
    dx, dy = dst[0] - src[0], dst[1] - src[1]
    if dx:
        dx = 1 if dx > 0 else -1
    if dy:
        dy = 1 if dy > 0 else -1
    return (dx, dy)


_DIR_TO_ROT: dict[tuple[int, int], int] = {E: 0, N: 1, W: 2, S: 3}


def _grow_tree(
    net: Net,
    graph: RoutingGraph,
    pres_fac: float,
) -> None:
    """Grow a Steiner tree connecting root to all terminals.

    For fanin nets, we grow from sink to sources (reversed), then flip edges.
    Terminals are connected farthest-first (builds trunk first).

    Raises ``RoutingError`` when a terminal is unreachable. Overused cells
    are priced, never blocked, so unreachability is structural (walled off
    or seed leg limits) and will not resolve in later iterations.
    """
    root = net.root
    terminals = list(net.terminals)

    # Sort terminals farthest-first from root
    terminals.sort(key=lambda t: abs(t[0] - root[0]) + abs(t[1] - root[1]), reverse=True)

    tree_cells: set[Cell] = {root}
    tree_edges: list[tuple[Cell, Cell]] = []
    # Track legs per cell for legality checks
    cell_in: dict[Cell, int] = defaultdict(int)
    cell_out: dict[Cell, int] = defaultdict(int)
    hop_cells: set[Cell] = set()
    lift_cells: set[Cell] = set()
    cell_approach: dict[Cell, tuple[int, int]] = {}
    # Cells that will become hop receivers in item flow.  For fanout nets
    # that's the growth-direction hop destination (pc); for fanin nets it's
    # the growth-direction hop source (prev_cell, because the edge flip
    # turns the growth sender into the item-flow receiver).  Adjacent
    # receivers create unmatched legs (receiver entity has ins=∅).
    item_recv_cells: set[Cell] = set()

    # When the root was offset from its port cell, a boundary edge will be
    # appended after routing. Pre-seed the incoming count so the root can
    # legally become a splitter (1,2)/(1,3) or merger (2,1)/(3,1).
    if net.root_offset:
        cell_in[root] = 1
    if net.root_approach is not None:
        cell_approach[root] = net.root_approach

    for terminal in terminals:
        if terminal in tree_cells:
            continue

        # A* from all tree cells (cost 0) to this terminal.
        # Tree cells are seeds but not intermediate expansion targets.
        tx, ty, tl = terminal

        def _h(c: Cell) -> float:
            h = (abs(c[0] - tx) + abs(c[1] - ty)) * BASE
            if c[2] != tl:
                h += LIFT_COST
            return h

        def _search(allow_hops: bool) -> tuple[bool, dict[Cell, float], dict[Cell, Cell]]:
            dist: dict[Cell, float] = {}
            prev: dict[Cell, Cell] = {}
            expanded: set[Cell] = set()
            pq: list[tuple[float, int, int, int, float, Cell]] = []

            for seed in tree_cells:
                if seed in hop_cells or seed in lift_cells:
                    continue
                # Check if seed can still emit another edge
                outs = cell_out[seed]
                ins = cell_in[seed]
                total_legs = ins + outs
                if total_legs >= 4:
                    continue
                if outs + 1 > 3:
                    continue
                candidate = (ins, outs + 1)
                if candidate not in LEGAL_LEG_PATTERNS and total_legs > 0:
                    continue
                dist[seed] = 0.0
                heapq.heappush(pq, (_h(seed), seed[1], seed[0], seed[2], 0.0, seed))

            found = False
            while pq:
                _f, _y, _x, _l, cost, cell = heapq.heappop(pq)

                if cost > dist.get(cell, float("inf")):
                    continue

                if cell == terminal:
                    found = True
                    break

                expanded.add(cell)

                for nb in _neighbors(cell):
                    if nb not in graph.passable:
                        continue
                    if nb in tree_cells and nb != terminal:
                        continue
                    reserved_owner = graph.reserved.get(nb)
                    if reserved_owner is not None and reserved_owner != net.net_id:
                        continue
                    # Hop receiver exit constraint: a cell reached via a hop
                    # must exit in the hop direction (straight through).
                    if allow_hops and cell in prev:
                        p = prev[cell]
                        md = abs(cell[0] - p[0]) + abs(cell[1] - p[1])
                        if md > 1:
                            ux = (1 if cell[0] > p[0] else -1) if cell[0] != p[0] else 0
                            uy = (1 if cell[1] > p[1] else -1) if cell[1] != p[1] else 0
                            if (nb[0] - cell[0], nb[1] - cell[1]) != (ux, uy):
                                continue

                    if nb in expanded:
                        continue
                    occ_set = graph.occ.get(nb, set())
                    overuse = max(0, len(occ_set - {net.net_id}) + 1 - 1)
                    bias = (hash(nb) ^ net.net_id ^ graph.sym_seed) % 997 * SYMMETRY_BREAK
                    enter = (graph.base.get(nb, BASE) + graph.hist.get(nb, 0.0) + bias) * (
                        1 + pres_fac * overuse
                    )
                    new_cost = cost + enter

                    if new_cost < dist.get(nb, float("inf")):
                        dist[nb] = new_cost
                        prev[nb] = cell
                        heapq.heappush(pq, (new_cost + _h(nb), nb[1], nb[0], nb[2], new_cost, nb))

                if allow_hops and graph.hop_range > 0:
                    cx, cy, cl = cell
                    # No hops from cells reached via hops (can't overlay
                    # launcher + catcher on the same cell), and no hops from
                    # lift exits (lift entity already occupies the cell).
                    _skip_hops = False
                    if cell in prev:
                        p = prev[cell]
                        if abs(cx - p[0]) + abs(cy - p[1]) > 1:
                            _skip_hops = True
                        elif p[2] != cl:
                            _skip_hops = True
                    # For fanin nets, the hop *sender* becomes the
                    # item-flow *receiver* (edge flip).  A receiver
                    # entity has ins=∅ — it can't accept from adjacent
                    # cells.  Block hops from cells that already have
                    # outgoing step edges (which flip into incoming) or
                    # that are adjacent to an existing receiver (whose
                    # output would point at this new receiver).
                    if not _skip_hops and net.kind == "fanin":
                        if cell_out[cell] > 0:
                            _skip_hops = True
                        else:
                            for _dx2, _dy2 in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                                if (cx + _dx2, cy + _dy2, cl) in item_recv_cells:
                                    _skip_hops = True
                                    break
                    if _skip_hops:
                        pass
                    else:
                        # Sender approach constraint: the hop sender must be
                        # fed from the direction opposite to the hop, so
                        # approach_dir must equal the hop direction.
                        if cell in prev:
                            p = prev[cell]
                            _approach = (cx - p[0], cy - p[1])
                        elif cell in cell_approach:
                            _approach = cell_approach[cell]
                        else:
                            _approach = None
                        for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1)):
                            if _approach is not None and _approach != (dx, dy):
                                continue
                            for hdist in range(2, graph.hop_range + 1):
                                nb = (cx + dx * hdist, cy + dy * hdist, cl)
                                if nb not in graph.passable:
                                    continue
                                if nb in tree_cells and nb != terminal:
                                    continue
                                reserved_owner = graph.reserved.get(nb)
                                if reserved_owner is not None and reserved_owner != net.net_id:
                                    continue
                                te = net.terminal_exit.get(nb)
                                if te is not None and (dx, dy) != te:
                                    continue
                                # §0b: a further pre-existing receiver on the
                                # same line/rotation would steal this sender
                                # under furthest-first; a farther pre-existing
                                # sender would steal this receiver. Either
                                # makes the candidate hop unsafe.
                                _hop_conflict = False
                                for d2 in range(hdist + 1, graph.hop_range + 1):
                                    rpos = (cx + dx * d2, cy + dy * d2, cl)
                                    if graph.existing_receivers.get(rpos) == (dx, dy):
                                        _hop_conflict = True
                                        break
                                    spos = (nb[0] - dx * d2, nb[1] - dy * d2, cl)
                                    if graph.existing_senders.get(spos) == (dx, dy):
                                        _hop_conflict = True
                                        break
                                if _hop_conflict:
                                    continue
                                # No adjacent receivers (fanout): the hop
                                # destination becomes a receiver; skip if
                                # any neighbor is already a receiver.
                                if net.kind != "fanin":
                                    _adj_recv = False
                                    for _dx2, _dy2 in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                                        if (nb[0] + _dx2, nb[1] + _dy2, cl) in item_recv_cells:
                                            _adj_recv = True
                                            break
                                    if _adj_recv:
                                        continue
                                if nb in expanded:
                                    continue
                                occ_set = graph.occ.get(nb, set())
                                overuse = max(0, len(occ_set - {net.net_id}) + 1 - 1)
                                hop_base = hdist * BASE + graph.hop_penalty
                                bias = (
                                    (hash(nb) ^ net.net_id ^ graph.sym_seed) % 997 * SYMMETRY_BREAK
                                )
                                enter = (hop_base + graph.hist.get(nb, 0.0) + bias) * (
                                    1 + pres_fac * overuse
                                )
                                new_cost = cost + enter
                                if new_cost < dist.get(nb, float("inf")):
                                    dist[nb] = new_cost
                                    prev[nb] = cell
                                    heapq.heappush(
                                        pq, (new_cost + _h(nb), nb[1], nb[0], nb[2], new_cost, nb)
                                    )

                if allow_hops and graph.lift_enabled:
                    cx, cy, cl = cell
                    for dl in (1, -1):
                        nb = (cx, cy, cl + dl)
                        if nb not in graph.passable:
                            continue
                        if nb in tree_cells and nb != terminal:
                            continue
                        if nb in expanded:
                            continue
                        occ_set = graph.occ.get(nb, set())
                        overuse = max(0, len(occ_set - {net.net_id}) + 1 - 1)
                        bias = (hash(nb) ^ net.net_id ^ graph.sym_seed) % 997 * SYMMETRY_BREAK
                        enter = (LIFT_COST + graph.hist.get(nb, 0.0) + bias) * (
                            1 + pres_fac * overuse
                        )
                        new_cost = cost + enter
                        if new_cost < dist.get(nb, float("inf")):
                            dist[nb] = new_cost
                            prev[nb] = cell
                            heapq.heappush(
                                pq, (new_cost + _h(nb), nb[1], nb[0], nb[2], new_cost, nb)
                            )

            return found, dist, prev

        found, dist, prev = _search(allow_hops=True)
        if not found:
            # The hop-receiver exit constraint can lock every approach to a
            # terminal into a "straight through" hop landing that points
            # away from it (seen at 16-lane density under heavy congestion
            # pricing). The base 4-connected grid is always fully connected
            # (no cell is walled off on all four sides), so retry without
            # hops/lifts as a fallback before declaring true unreachability.
            found, dist, prev = _search(allow_hops=False)

        if not found:
            raise RoutingError(
                f"net {net.net_id} ({net.kind}): terminal {terminal} "
                f"unreachable from tree of {len(tree_cells)} cells"
            )

        # Trace back path and add to tree
        path: list[Cell] = []
        cur = terminal
        while cur in prev:
            path.append(cur)
            cur = prev[cur]
        # cur is now a tree cell (the seed we reached from)
        seed_cell = cur
        path.reverse()

        # Add edges along the path
        prev_cell = seed_cell
        for pc in path:
            tree_edges.append((prev_cell, pc))
            dx = pc[0] - prev_cell[0]
            dy = pc[1] - prev_cell[1]
            md = abs(dx) + abs(dy)
            if pc[2] != prev_cell[2]:
                lift_cells.add(prev_cell)
                lift_cells.add(pc)
            elif md > 1:
                hop_cells.add(prev_cell)
                hop_cells.add(pc)
                if net.kind == "fanin":
                    item_recv_cells.add(prev_cell)
                else:
                    item_recv_cells.add(pc)
            if md == 1:
                cell_approach[pc] = (dx, dy)
            elif md > 1 and pc[2] == prev_cell[2]:
                ux = (1 if dx > 0 else -1) if dx != 0 else 0
                uy = (1 if dy > 0 else -1) if dy != 0 else 0
                cell_approach[pc] = (ux, uy)
            cell_out[prev_cell] += 1
            cell_in[pc] += 1
            tree_cells.add(pc)
            prev_cell = pc

    # For fanin nets, flip edge directions
    if net.kind == "fanin":
        tree_edges = [(dst, src) for src, dst in tree_edges]

    net.tree_cells = tree_cells
    net.tree_edges = tree_edges
    net.hop_edges = {
        (s, d) for s, d in tree_edges if s[2] == d[2] and abs(d[0] - s[0]) + abs(d[1] - s[1]) > 1
    }
    net.lift_edges = {(s, d) for s, d in tree_edges if s[2] != d[2]}


def _net_hpwl(net: Net) -> int:
    """Half-perimeter wire length (bounding box) of a net's terminals + root."""
    all_cells = [net.root] + net.terminals
    xs = [c[0] for c in all_cells]
    ys = [c[1] for c in all_cells]
    return (max(xs) - min(xs)) + (max(ys) - min(ys))


_NetSnap = dict[
    int,
    tuple[set[Cell], list[tuple[Cell, Cell]], set[tuple[Cell, Cell]], set[tuple[Cell, Cell]]],
]
_BestState = tuple[_NetSnap, dict[Cell, float]]


def _snapshot(nets: list[Net], graph: RoutingGraph) -> _BestState:
    net_snap = {
        n.net_id: (set(n.tree_cells), list(n.tree_edges), set(n.hop_edges), set(n.lift_edges))
        for n in nets
    }
    return net_snap, dict(graph.hist)


def _restore(nets: list[Net], graph: RoutingGraph, state: _BestState) -> None:
    net_snap, hist_snap = state
    for n in nets:
        for c in n.tree_cells:
            graph.occ[c].discard(n.net_id)
        cells, edges, hops, lifts = net_snap[n.net_id]
        n.tree_cells = cells
        n.tree_edges = edges
        n.hop_edges = hops
        n.lift_edges = lifts
        for c in n.tree_cells:
            graph.occ[c].add(n.net_id)
    graph.hist = {c: v for c, v in hist_snap.items()}


def pathfinder_route(
    nets: list[Net],
    graph: RoutingGraph,
    *,
    raise_on_failure: bool = True,
    max_iters: int = MAX_ITERS,
    pres_fac_init: float = PRES_FAC_INIT,
    pres_fac_mult: float = PRES_FAC_MULT,
    hist_gain: float = HIST_GAIN,
    stall_window: int | None = None,
    keep_best: bool = False,
) -> bool:
    """Run the PathFinder negotiated-congestion loop.

    Returns True if all nets routed without overlap. When *raise_on_failure*
    is True (the default for production callers), raises ``RoutingError``
    carrying the overused cells so WP-M can use them as placement feedback.

    When *keep_best* is True, the best net routes found during negotiation
    are restored before returning (instead of the final, possibly worse,
    iteration).
    """
    own_ids = {n.net_id for n in nets}
    nets_sorted = sorted(nets, key=lambda n: (-_net_hpwl(n), n.net_id))
    pres_fac = pres_fac_init
    _STALL_WINDOW = stall_window if stall_window is not None else max(15, len(nets))
    prev_overuse_counts: list[int] = []
    best_overuse = float("inf")
    best_snap: _BestState | None = None

    for _iteration in range(max_iters):
        for net in nets_sorted:
            for c in net.tree_cells:
                graph.occ[c].discard(net.net_id)

            _grow_tree(net, graph, pres_fac)

            for c in net.tree_cells:
                graph.occ[c].add(net.net_id)

        overused = [c for c, s in graph.occ.items() if len(s) > 1 and (s & own_ids)]
        if not overused:
            return True

        if keep_best and len(overused) < best_overuse:
            best_overuse = len(overused)
            best_snap = _snapshot(nets, graph)

        prev_overuse_counts.append(len(overused))
        if len(prev_overuse_counts) > _STALL_WINDOW:
            recent = prev_overuse_counts[-_STALL_WINDOW:]
            if min(recent) >= recent[0]:
                break

        overused_set = set(overused)
        nets_sorted = sorted(
            nets,
            key=lambda n: (
                0 if n.tree_cells & overused_set else 1,
                -_net_hpwl(n),
                n.net_id,
            ),
        )

        for c in overused:
            graph.hist[c] = graph.hist.get(c, 0.0) + hist_gain * (len(graph.occ[c]) - 1)
        pres_fac *= pres_fac_mult

    if keep_best and best_snap is not None:
        _restore(nets, graph, best_snap)

    overused = [c for c, s in graph.occ.items() if len(s) > 1 and (s & own_ids)]
    if raise_on_failure:
        raise RoutingError(
            f"PathFinder failed after {max_iters} iterations; {len(overused)} overused cells",
            overused=overused,
        )
    return False


# ---------------------------------------------------------------------------
# Lane-group decomposition (§7.3 step 7)
# ---------------------------------------------------------------------------


def _assign_net_groups(
    nets: list[Net],
    netlist: lift.Netlist,
    platform: str,
) -> None:
    """Assign each net to a source port group for lane-group decomposition.

    Traces netlist edges forward from sources to propagate group membership
    to machines and sinks.  Each net inherits the group of whichever netlist
    node its root or terminals correspond to.
    """
    from shapez2_tools.place import SOURCE_FACE, _load_platform, _port_groups

    plat = _load_platform(platform)
    src_groups = _port_groups(plat, SOURCE_FACE)
    if len(src_groups) <= 1:
        return

    group_centers = [sum(p[0] for p in g) / len(g) for g in src_groups]

    node_group: dict[tuple, int] = {}
    for pos, node in netlist.nodes.items():
        if node.kind == "platform_in":
            node_group[pos] = min(
                range(len(group_centers)),
                key=lambda g: abs(group_centers[g] - pos[0]),
            )

    changed = True
    while changed:
        changed = False
        for src, dst in netlist.edges:
            if src in node_group and dst not in node_group:
                node_group[dst] = node_group[src]
                changed = True

    for net in nets:
        root_2d = (net.root[0], net.root[1])
        if root_2d in node_group:
            net.group = node_group[root_2d]
            continue
        for t in net.terminals:
            t_2d = (t[0], t[1])
            if t_2d in node_group:
                net.group = node_group[t_2d]
                break


GROUP_FREEZE_HIST = 5.0


def _route_by_group(
    nets: list[Net],
    graph: RoutingGraph,
    *,
    raise_on_failure: bool = True,
) -> bool:
    """Route nets group-by-group with retained inter-group occupancy.

    Each group is routed via ``pathfinder_route`` while previous groups'
    cells remain occupied in the graph.  History is cleared between
    groups so prior intra-group iteration history doesn't pollute
    subsequent groups.

    Per-group failures are tolerated: long east-west routes from one
    group may cross another group's routing channels, creating
    cross-group interference that no single group can resolve.  After
    all groups run, a joint ``pathfinder_route`` on all nets handles
    residual overlaps.
    """
    groups: dict[int, list[Net]] = {}
    ungrouped: list[Net] = []
    for net in nets:
        if net.group is not None:
            groups.setdefault(net.group, []).append(net)
        else:
            ungrouped.append(net)

    for g_idx in sorted(groups):
        graph.hist.clear()
        pathfinder_route(groups[g_idx], graph, raise_on_failure=False)

    if ungrouped:
        graph.hist.clear()
        pathfinder_route(ungrouped, graph, raise_on_failure=False)

    overused = [c for c, s in graph.occ.items() if len(s) > 1]
    if not overused:
        return True

    graph.hist.clear()
    return pathfinder_route(nets, graph, raise_on_failure=raise_on_failure)


# ---------------------------------------------------------------------------
# Emit table — programmatic inverse of lift.routing_inout
# ---------------------------------------------------------------------------


def emit_table() -> dict[tuple[frozenset, frozenset], tuple[str, int]]:
    """Build (ins, outs) → (type, rotation) from lift.routing_inout.

    This is the single shared calibration table inverted. Never hand-write
    a second table — the I4 round-trip depends on both directions sharing
    one source of truth. The variant names are probes into routing_inout's
    substring matcher; each is validated (must return non-None at R=0).
    """
    variants = [
        "BeltDefaultForwardInternalVariant",
        "BeltDefaultLeftInternalVariant",
        "BeltDefaultLeftInternalVariantMirrored",
        "Splitter1To2LInternalVariant",
        "Splitter1To2LInternalVariantMirrored",
        "Splitter1To3InternalVariant",
        "SplitterTShapeInternalVariant",
        "Merger2To1LInternalVariant",
        "Merger2To1LInternalVariantMirrored",
        "Merger3To1InternalVariant",
        "MergerTShapeInternalVariant",
    ]
    table: dict[tuple[frozenset, frozenset], tuple[str, int]] = {}
    for variant in variants:
        assert lift.routing_inout(variant, 0) is not None, (
            f"emit_table probe {variant!r} not recognised by routing_inout"
        )
        for r in range(4):
            ins, outs = lift.routing_inout(variant, r)
            key = (ins, outs)
            if key not in table:
                table[key] = (variant, r)
    return table


_EMIT_TABLE: dict[tuple[frozenset, frozenset], tuple[str, int]] | None = None


def _get_emit_table() -> dict[tuple[frozenset, frozenset], tuple[str, int]]:
    global _EMIT_TABLE
    if _EMIT_TABLE is None:
        _EMIT_TABLE = emit_table()
    return _EMIT_TABLE


def _lift_emit_table() -> dict[tuple[frozenset, frozenset, int], tuple[str, int]]:
    """Build (ins, outs, delta) → (type, rotation) from lift.lift_inout."""
    bases = ["Forward", "Backward", "Left"]
    table: dict[tuple[frozenset, frozenset, int], tuple[str, int]] = {}
    for prefix in ["Lift1", "Lift2"]:
        for direction in ["Up", "Down"]:
            for exit_dir in bases:
                for suffix in ["InternalVariant", "InternalVariantMirrored"]:
                    if exit_dir != "Left" and suffix == "InternalVariantMirrored":
                        continue
                    variant = f"{prefix}{direction}{exit_dir}{suffix}"
                    info = lift.lift_inout(variant, 0)
                    if info is None:
                        continue
                    for r in range(4):
                        ins, outs, delta = lift.lift_inout(variant, r)
                        key = (ins, outs, delta)
                        if key not in table:
                            table[key] = (variant, r)
    return table


_LIFT_EMIT: dict[tuple[frozenset, frozenset, int], tuple[str, int]] | None = None


def _get_lift_emit_table() -> dict[tuple[frozenset, frozenset, int], tuple[str, int]]:
    global _LIFT_EMIT
    if _LIFT_EMIT is None:
        _LIFT_EMIT = _lift_emit_table()
    return _LIFT_EMIT


def _cell_to_entity(
    cell: Cell,
    tree_edges: list[tuple[Cell, Cell]],
    hop_edges: set[tuple[Cell, Cell]] | None = None,
    lift_edges: set[tuple[Cell, Cell]] | None = None,
) -> Entity | None:
    """Convert a tree cell to a belt Entity using the emit table.

    Returns None only for cells with no incident tree edges (port/machine
    cells that appear in boundary edges but aren't routing cells).
    Raises ``RoutingError`` if a routing cell has a leg pattern with no
    matching belt variant — that indicates a bug in tree growth.
    """
    if lift_edges:
        for src, dst in lift_edges:
            if src == cell:
                # This cell is the entry side of a lift.
                # Find horizontal in-direction and out-direction.
                in_dir = None
                out_dir = None
                for s2, d2 in tree_edges:
                    if d2 == cell and s2[2] == cell[2]:
                        in_dir = _unit_direction(cell, s2)
                    if s2 == dst:
                        if d2[2] == dst[2]:
                            out_dir = _unit_direction(dst, d2)
                if hop_edges:
                    if in_dir is None:
                        for s2, d2 in hop_edges:
                            if d2 == cell:
                                in_dir = _unit_direction(cell, s2)
                    if out_dir is None:
                        for s2, d2 in hop_edges:
                            if s2 == dst:
                                out_dir = _unit_direction(dst, d2)
                delta = dst[2] - src[2]
                if in_dir is None or out_dir is None:
                    return None
                key = (frozenset({in_dir}), frozenset({out_dir}), delta)
                table = _get_lift_emit_table()
                entry = table.get(key)
                if entry is None:
                    raise RoutingError(
                        f"No lift variant for in={in_dir} out={out_dir} "
                        f"delta={delta} at cell {cell}"
                    )
                variant, r = entry
                return Entity(
                    x=cell[0],
                    y=cell[1],
                    type=variant,
                    rotation=r,
                    layer=cell[2],
                )
            if dst == cell:
                return None

    if hop_edges:
        for src, dst in hop_edges:
            dx, dy = dst[0] - src[0], dst[1] - src[1]
            ux = (1 if dx > 0 else -1) if dx else 0
            uy = (1 if dy > 0 else -1) if dy else 0
            r = _DIR_TO_ROT[(ux, uy)]
            if src == cell:
                return Entity(
                    x=cell[0],
                    y=cell[1],
                    type="BeltPortSenderInternalVariant",
                    rotation=r,
                    layer=cell[2],
                )
            if dst == cell:
                return Entity(
                    x=cell[0],
                    y=cell[1],
                    type="BeltPortReceiverInternalVariant",
                    rotation=r,
                    layer=cell[2],
                )

    in_dirs: set[tuple[int, int]] = set()
    out_dirs: set[tuple[int, int]] = set()

    for src, dst in tree_edges:
        if src[2] != dst[2]:
            continue
        if dst == cell:
            in_dirs.add(_direction(cell, src))
        if src == cell:
            out_dirs.add(_direction(cell, dst))

    if not in_dirs and not out_dirs:
        return None

    key = (frozenset(in_dirs), frozenset(out_dirs))
    table = _get_emit_table()
    entry = table.get(key)
    if entry is None:
        raise RoutingError(
            f"No belt variant for leg pattern ins={in_dirs} outs={out_dirs} at cell {cell}"
        )

    variant, r = entry
    return Entity(x=cell[0], y=cell[1], type=variant, rotation=r, layer=cell[2])


def emit_entities(nets: list[Net]) -> list[Entity]:
    """Convert routed nets to belt entities."""
    entities: list[Entity] = []
    for net in nets:
        for cell in net.tree_cells:
            ent = _cell_to_entity(
                cell,
                net.tree_edges,
                hop_edges=net.hop_edges,
                lift_edges=net.lift_edges,
            )
            if ent is not None:
                entities.append(ent)
    return entities


# ---------------------------------------------------------------------------
# Net extraction from a lifted netlist
# ---------------------------------------------------------------------------


def _node_cell_ports(
    node: lift.Node,
) -> dict[tuple[int, int], tuple[frozenset, frozenset]]:
    """Per-cell (ins, outs) for a node, in absolute coordinates."""
    if node.kind == "machine":
        fp = lift._machine_footprint(node.type, node.rotation)
        return {
            (node.x + dx, node.y + dy): (ins, outs)
            for (dx, dy, dl), (ins, outs) in fp.items()
            if dl == 0
        }
    ins, outs = lift._inout(node.type, node.rotation)
    return {(node.x, node.y): (ins, outs)}


def build_nets(
    netlist: lift.Netlist,
    layer: int = 0,
) -> tuple[
    list[Net], dict[tuple[int, int], tuple[int, int]], dict[tuple[int, int], tuple[int, int]]
]:
    """Extract nets from a netlist's port_edges at cell granularity.

    Returns (nets, cell_out_dir, cell_in_dir).
    """
    cell_out_dir: dict[tuple[int, int], tuple[int, int]] = {}
    cell_in_dir: dict[tuple[int, int], tuple[int, int]] = {}
    for node in netlist.nodes.values():
        for cell, (ins, outs) in _node_cell_ports(node).items():
            if outs:
                cell_out_dir[cell] = next(iter(outs))
            if ins:
                cell_in_dir[cell] = next(iter(ins))

    cell_edges = sorted(netlist.port_edges if netlist.port_edges else netlist.edges)

    # Group edges into connected components by shared endpoint cells.
    outgoing: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    incoming: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    for src, dst in cell_edges:
        outgoing[src].append(dst)
        incoming[dst].append(src)

    # Guard: reject N→M components (a cell that is both a fan-out source and
    # a fan-in destination from unrelated edges). None exist in current specs;
    # silently mishandling one would corrupt the routing.
    for cell in set(outgoing) & set(incoming):
        out_dsts = set(outgoing[cell])
        in_srcs = set(incoming[cell])
        if len(out_dsts) >= 2 and len(in_srcs) >= 2:
            raise NotImplementedError(
                f"N→M component at cell {cell}: "
                f"{len(in_srcs)} sources, {len(out_dsts)} destinations"
            )

    # Build nets: group edges into fan-out (1→N) and fan-in (N→1) nets.
    # Process fan-out first (1→N where N≥2), then fan-in (N→1 where N≥2),
    # then remaining 1→1 edges.
    visited_edges: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    nets: list[Net] = []
    net_id = 0

    # Fan-out: one source to many (N≥2)
    for src, dsts in outgoing.items():
        if len(dsts) < 2:
            continue
        edges_from_src = [(src, d) for d in dsts]
        for e in edges_from_src:
            visited_edges.add(e)

        root_3d: Cell = (src[0], src[1], layer)
        term_3d: list[Cell] = [(d[0], d[1], layer) for d in dsts]
        nets.append(Net(net_id=net_id, kind="fanout", root=root_3d, terminals=term_3d))
        net_id += 1

    # Fan-in: many sources to one (N≥2), only for edges not already in a fan-out
    for dst, srcs in incoming.items():
        remaining = [s for s in srcs if (s, dst) not in visited_edges]
        if len(remaining) < 2:
            continue
        for s in remaining:
            visited_edges.add((s, dst))

        root_3d = (dst[0], dst[1], layer)
        term_3d: list[Cell] = [(s[0], s[1], layer) for s in remaining]
        nets.append(Net(net_id=net_id, kind="fanin", root=root_3d, terminals=term_3d))
        net_id += 1

    # Remaining 1→1 edges
    for src, dsts in outgoing.items():
        for dst in dsts:
            if (src, dst) in visited_edges:
                continue
            visited_edges.add((src, dst))
            root_3d = (src[0], src[1], layer)
            term_3d = [(dst[0], dst[1], layer)]
            nets.append(Net(net_id=net_id, kind="fanout", root=root_3d, terminals=term_3d))
            net_id += 1

    return nets, cell_out_dir, cell_in_dir


# ---------------------------------------------------------------------------
# Top-level entry point (same interface as reroute_with_junctions)
# ---------------------------------------------------------------------------


def _platform_bounds(platform: str) -> tuple[int, int, int, int]:
    """Return (min_x, max_x, min_y, max_y) for the platform's buildable interior."""
    import json
    from pathlib import Path

    data = Path(__file__).resolve().parent.parent.parent / "data"
    with open(data / "platforms.json") as f:
        platforms = json.load(f)
    plat = platforms[platform]
    ports = plat["ports"]
    xs = [p[0] for p in ports]
    ys = [p[1] for p in ports]
    return min(xs), max(xs), min(ys), max(ys)


def _build_passable(
    netlist: lift.Netlist,
    machine_cells: set[tuple[int, int]],
    layer: int,
    *,
    platform: str | None = None,
    extra_layers: tuple[int, ...] = (),
) -> set[Cell]:
    """Build the routing graph's passable cell set.

    For platform-bounded routing, ``_platform_bounds`` returns the full
    bounding box of the port positions, but the outermost ring of that box
    (e.g. x in {-18, 57} / y in {2, 37} on ``Foundation_2x4``) is ports-only
    in-game: the buildable interior starts one cell inside
    (``viz._platform_geometry``'s inset=3). The ring is excluded from
    ``passable``, except for the specific port cells that are net endpoints
    in ``netlist`` (``platform_in``/``platform_out`` nodes) — those remain
    passable so the router can reach them.

    Without a ``platform``, bounds come from the netlist's own node
    positions plus a margin (synthetic test fixtures); there is no port
    ring to exclude.

    ``extra_layers`` (WP-N 3e, lift-aware routing) opens additional floors
    over the same (x, y) bounding box, fully passable — no ``machine_cells``
    or ring exclusion. ``netlist`` is single-floor, so an extra floor has no
    machines or ports of its own; this matches the WP-N task-1 finding that
    floor+1 is a fully open second layer for the human's single-floor build.
    """
    if platform is not None:
        min_x, max_x, min_y, max_y = _platform_bounds(platform)
        port_cells = {
            pos
            for pos, node in netlist.nodes.items()
            if node.kind in ("platform_in", "platform_out")
        }
    else:
        all_x = [pos[0] for pos in netlist.nodes]
        all_y = [pos[1] for pos in netlist.nodes]
        margin = 5
        min_x, max_x = min(all_x) - margin, max(all_x) + margin
        min_y, max_y = min(all_y) - margin, max(all_y) + margin
        port_cells = set()

    passable: set[Cell] = set()
    for x in range(min_x, max_x + 1):
        for y in range(min_y, max_y + 1):
            if (x, y) not in machine_cells:
                on_ring = platform is not None and (x in (min_x, max_x) or y in (min_y, max_y))
                if not on_ring or (x, y) in port_cells:
                    passable.add((x, y, layer))
            for extra in extra_layers:
                passable.add((x, y, extra))
    return passable


def strip_and_reroute(
    bp: Blueprint,
    netlist: lift.Netlist,
    layer: int = 0,
    *,
    hop_range: int = 0,
    platform: str | None = None,
    lift_enabled: bool = False,
) -> Blueprint:
    """Strip belts and re-route via PathFinder.

    Drop-in replacement for ``route.reroute_with_junctions``. When
    ``lift_enabled`` is True (WP-N task 3e), floor ``layer + 1`` is opened as
    a fully passable second layer and ``RoutingGraph`` may route nets through
    it via lift edges — the 2-floor approach validated by the WP-N task-1
    experiment (single floor doesn't converge at Half-Splitter scale; 2
    floors with lifts does).
    """
    extra_layers = (layer + 1,) if lift_enabled else ()

    stripped = strip_belts(bp, layer=layer, netlist=netlist)
    for extra in extra_layers:
        stripped = strip_belts(stripped, layer=extra)
    kept = [e for e in _all_entities(stripped) if e.layer in (layer, *extra_layers)]

    # Machine/port positions on the primary floor → obstacles (not passable).
    machine_cells: set[tuple[int, int]] = set()
    for e in kept:
        if e.layer != layer:
            continue
        machine_cells.add((e.x, e.y))
        if lift.kind(e.type) == "machine":
            fp = lift._machine_footprint(e.type, e.rotation)
            for dx, dy, dl in fp:
                if dl == 0:
                    machine_cells.add((e.x + dx, e.y + dy))

    # Build passable set from platform bounds (preferred) or node bounding box.
    passable = _build_passable(
        netlist,
        machine_cells,
        layer,
        platform=platform,
        extra_layers=extra_layers,
    )

    # Build nets
    nets, cell_out_dir, cell_in_dir = build_nets(netlist, layer=layer)

    # Assign lane groups before translating roots/terminals (positions still
    # match netlist node positions at this point).
    if platform is not None:
        _assign_net_groups(nets, netlist, platform)

    # Translate root/terminal to routing cells (one step from the port in
    # its output/input direction), matching the A* router's convention.
    # Store original port positions for boundary edges after routing.
    port_of_root: dict[int, Cell] = {}  # net_id → original port cell
    # net_id → list of (routing_cell, port_cell) pairs
    port_of_term: dict[int, list[tuple[Cell, Cell]]] = {}

    for net in nets:
        rx, ry, rl = net.root
        port_of_root[net.net_id] = net.root
        port_of_term[net.net_id] = []

        if net.kind == "fanout":
            d = cell_out_dir.get((rx, ry))
            if d:
                new_root = (rx + d[0], ry + d[1], rl)
                if new_root in passable:
                    net.root = new_root
                    net.root_offset = True
                    net.root_approach = d
            new_terms = []
            for tx, ty, tl in net.terminals:
                orig = (tx, ty, tl)
                d = cell_in_dir.get((tx, ty))
                if d:
                    new_t = (tx + d[0], ty + d[1], tl)
                    if new_t in passable:
                        port_of_term[net.net_id].append((new_t, orig))
                        new_terms.append(new_t)
                        net.terminal_exit[new_t] = (-d[0], -d[1])
                    else:
                        new_terms.append(orig)
                else:
                    new_terms.append(orig)
            net.terminals = new_terms
        else:  # fanin: root is the sink
            d = cell_in_dir.get((rx, ry))
            if d:
                new_root = (rx + d[0], ry + d[1], rl)
                if new_root in passable:
                    net.root = new_root
                    net.root_offset = True
                    net.root_approach = d
            new_terms = []
            for tx, ty, tl in net.terminals:
                orig = (tx, ty, tl)
                d = cell_out_dir.get((tx, ty))
                if d:
                    new_t = (tx + d[0], ty + d[1], tl)
                    if new_t in passable:
                        port_of_term[net.net_id].append((new_t, orig))
                        new_terms.append(new_t)
                        net.terminal_exit[new_t] = (-d[0], -d[1])
                    else:
                        new_terms.append(orig)
                else:
                    new_terms.append(orig)
            net.terminals = new_terms

    # A terminal still on a machine/port cell is a direct machine-to-machine
    # coupling (e.g. a rotator feeding an adjacent swapper): the physical
    # adjacency realizes that edge with no belt, and lift re-derives it.
    # Route only the passable terminals; a net with none left needs no belts.
    routable: list[Net] = []
    for net in nets:
        net.terminals = [t for t in net.terminals if t in passable]
        if not net.terminals:
            continue
        if net.root not in passable:
            # A root stuck on its port cell with routable terminals would
            # emit a belt entity overlapping the port entity.
            raise RoutingError(f"root could not leave port cell ({net.root[0]}, {net.root[1]})")
        routable.append(net)

    graph = RoutingGraph(passable=passable, hop_range=hop_range, lift_enabled=lift_enabled)

    grouped = [n for n in routable if n.group is not None]
    if len(grouped) > 24:
        _route_by_group(routable, graph)
    else:
        from shapez2_tools._rust_bridge import RUST_AVAILABLE

        if RUST_AVAILABLE:
            from shapez2_tools._rust_bridge import rust_pathfinder_route

            rust_pathfinder_route(routable, graph)
        else:
            pathfinder_route(routable, graph)

    # Add boundary edges connecting port cells to the tree's root/terminal
    # routing cells so the emit table can resolve correct belt types.
    for net in routable:
        port_root = port_of_root[net.net_id]
        if port_root != net.root:
            if net.kind == "fanout":
                net.tree_edges.insert(0, (port_root, net.root))
            else:
                net.tree_edges.append((net.root, port_root))

        for routing_cell, port_cell in port_of_term[net.net_id]:
            if port_cell != routing_cell:
                if net.kind == "fanout":
                    net.tree_edges.append((routing_cell, port_cell))
                else:
                    net.tree_edges.insert(0, (port_cell, routing_cell))

    # Emit: tree cells → belt entities with correct type/rotation.
    belt_entities: list[Entity] = []
    for net in routable:
        for cell in sorted(net.tree_cells, key=lambda c: (c[1], c[0], c[2])):
            ent = _cell_to_entity(
                cell,
                net.tree_edges,
                hop_edges=net.hop_edges,
                lift_edges=net.lift_edges,
            )
            if ent is not None:
                belt_entities.append(ent)

    all_ents = kept + belt_entities
    return _rebuild_blueprint(bp, all_ents)
