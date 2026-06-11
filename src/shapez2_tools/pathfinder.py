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
HOP_PENALTY = 2.0
LIFT_COST = 3.0

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
    tree_cells: set[Cell] = field(default_factory=set)
    tree_edges: list[tuple[Cell, Cell]] = field(default_factory=list)
    hop_edges: set[tuple[Cell, Cell]] = field(default_factory=set)
    lift_edges: set[tuple[Cell, Cell]] = field(default_factory=set)


@dataclass
class RoutingGraph:
    passable: set[Cell]
    hop_range: int = 0
    lift_enabled: bool = False
    base: dict[Cell, float] = field(default_factory=dict)
    hist: dict[Cell, float] = field(default_factory=dict)
    occ: dict[Cell, set[int]] = field(default_factory=lambda: defaultdict(set))

    def __post_init__(self):
        for c in self.passable:
            self.base.setdefault(c, BASE)
            self.hist.setdefault(c, 0.0)


def _neighbors(cell: Cell) -> list[Cell]:
    x, y, ly = cell
    return [(x + 1, y, ly), (x - 1, y, ly), (x, y + 1, ly), (x, y - 1, ly)]


def _direction(src: Cell, dst: Cell) -> tuple[int, int]:
    return (dst[0] - src[0], dst[1] - src[1])


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

    # When the root was offset from its port cell, a boundary edge will be
    # appended after routing. Pre-seed the incoming count so the root can
    # legally become a splitter (1,2)/(1,3) or merger (2,1)/(3,1).
    if net.root_offset:
        cell_in[root] = 1

    for terminal in terminals:
        if terminal in tree_cells:
            continue

        # Dijkstra from all tree cells (cost 0) to this terminal.
        # Tree cells are seeds but not intermediate expansion targets.
        dist: dict[Cell, float] = {}
        prev: dict[Cell, Cell] = {}
        pq: list[tuple[float, int, int, int, Cell]] = []

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
            heapq.heappush(pq, (0.0, seed[1], seed[0], seed[2], seed))

        found = False
        while pq:
            cost, _y, _x, _l, cell = heapq.heappop(pq)

            if cost > dist.get(cell, float("inf")):
                continue

            if cell == terminal:
                found = True
                break

            for nb in _neighbors(cell):
                if nb not in graph.passable:
                    continue
                if nb in tree_cells and nb != terminal:
                    continue

                occ_set = graph.occ.get(nb, set())
                overuse = max(0, len(occ_set - {net.net_id}) + 1 - 1)
                enter = (graph.base.get(nb, BASE) + graph.hist.get(nb, 0.0)) * (
                    1 + pres_fac * overuse
                )
                new_cost = cost + enter

                if new_cost < dist.get(nb, float("inf")):
                    dist[nb] = new_cost
                    prev[nb] = cell
                    heapq.heappush(pq, (new_cost, nb[1], nb[0], nb[2], nb))

            if graph.hop_range > 0:
                cx, cy, cl = cell
                for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1)):
                    for hdist in range(2, graph.hop_range + 1):
                        nb = (cx + dx * hdist, cy + dy * hdist, cl)
                        if nb not in graph.passable:
                            continue
                        if nb in tree_cells and nb != terminal:
                            continue
                        occ_set = graph.occ.get(nb, set())
                        overuse = max(0, len(occ_set - {net.net_id}) + 1 - 1)
                        hop_base = hdist * BASE + HOP_PENALTY
                        enter = (hop_base + graph.hist.get(nb, 0.0)) * (
                            1 + pres_fac * overuse
                        )
                        new_cost = cost + enter
                        if new_cost < dist.get(nb, float("inf")):
                            dist[nb] = new_cost
                            prev[nb] = cell
                            heapq.heappush(
                                pq, (new_cost, nb[1], nb[0], nb[2], nb)
                            )

            if graph.lift_enabled:
                cx, cy, cl = cell
                for dl in (1, -1):
                    nb = (cx, cy, cl + dl)
                    if nb not in graph.passable:
                        continue
                    if nb in tree_cells and nb != terminal:
                        continue
                    occ_set = graph.occ.get(nb, set())
                    overuse = max(0, len(occ_set - {net.net_id}) + 1 - 1)
                    enter = (LIFT_COST + graph.hist.get(nb, 0.0)) * (
                        1 + pres_fac * overuse
                    )
                    new_cost = cost + enter
                    if new_cost < dist.get(nb, float("inf")):
                        dist[nb] = new_cost
                        prev[nb] = cell
                        heapq.heappush(
                            pq, (new_cost, nb[1], nb[0], nb[2], nb)
                        )

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
            if pc[2] != prev_cell[2]:
                lift_cells.add(prev_cell)
                lift_cells.add(pc)
            elif abs(pc[0] - prev_cell[0]) + abs(pc[1] - prev_cell[1]) > 1:
                hop_cells.add(prev_cell)
                hop_cells.add(pc)
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
        (s, d)
        for s, d in tree_edges
        if s[2] == d[2] and abs(d[0] - s[0]) + abs(d[1] - s[1]) > 1
    }
    net.lift_edges = {
        (s, d) for s, d in tree_edges if s[2] != d[2]
    }


def pathfinder_route(
    nets: list[Net], graph: RoutingGraph, *, raise_on_failure: bool = True
) -> bool:
    """Run the PathFinder negotiated-congestion loop.

    Returns True if all nets routed without overlap. When *raise_on_failure*
    is True (the default for production callers), raises ``RoutingError``
    carrying the overused cells so WP-M can use them as placement feedback.
    """
    nets_sorted = sorted(nets, key=lambda n: n.net_id)
    pres_fac = PRES_FAC_INIT

    for _iteration in range(MAX_ITERS):
        for net in nets_sorted:
            # Rip up: release this net's cells
            for c in net.tree_cells:
                graph.occ[c].discard(net.net_id)

            # Reroute
            _grow_tree(net, graph, pres_fac)

            # Claim new cells
            for c in net.tree_cells:
                graph.occ[c].add(net.net_id)

        # Check convergence
        overused = [c for c, s in graph.occ.items() if len(s) > 1]
        if not overused:
            return True

        # Update history
        for c in overused:
            graph.hist[c] = graph.hist.get(c, 0.0) + HIST_GAIN * (len(graph.occ[c]) - 1)
        pres_fac *= PRES_FAC_MULT

    overused = [c for c, s in graph.occ.items() if len(s) > 1]
    if raise_on_failure:
        raise RoutingError(
            f"PathFinder failed after {MAX_ITERS} iterations; "
            f"{len(overused)} overused cells",
            overused=overused,
        )
    return False


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


def _lift_emit_table() -> dict[
    tuple[frozenset, frozenset, int], tuple[str, int]
]:
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


def _get_lift_emit_table() -> dict[
    tuple[frozenset, frozenset, int], tuple[str, int]
]:
    global _LIFT_EMIT
    if _LIFT_EMIT is None:
        _LIFT_EMIT = _lift_emit_table()
    return _LIFT_EMIT


def _cell_to_entity(
    cell: Cell,
    tree_edges: list[tuple[Cell, Cell]],
    layer: int,
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
                        in_dir = _direction(cell, s2)
                    if s2 == dst:
                        if d2[2] == dst[2]:
                            out_dir = _direction(dst, d2)
                delta = dst[2] - src[2]
                if in_dir is not None and out_dir is not None:
                    key = (frozenset({in_dir}), frozenset({out_dir}), delta)
                    table = _get_lift_emit_table()
                    entry = table.get(key)
                    if entry is not None:
                        variant, r = entry
                        return Entity(
                            x=cell[0], y=cell[1], type=variant,
                            rotation=r, layer=cell[2],
                        )
                return None
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
                    x=cell[0], y=cell[1],
                    type="BeltPortSenderInternalVariant",
                    rotation=r, layer=layer,
                )
            if dst == cell:
                return Entity(
                    x=cell[0], y=cell[1],
                    type="BeltPortReceiverInternalVariant",
                    rotation=r, layer=layer,
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
            f"No belt variant for leg pattern ins={in_dirs} outs={out_dirs} "
            f"at cell {cell}"
        )

    variant, r = entry
    return Entity(x=cell[0], y=cell[1], type=variant, rotation=r, layer=layer)


def emit_entities(
    nets: list[Net],
    layer: int = 0,
) -> list[Entity]:
    """Convert routed nets to belt entities."""
    entities: list[Entity] = []
    for net in nets:
        for cell in net.tree_cells:
            ent = _cell_to_entity(
                cell, net.tree_edges, layer,
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


def strip_and_reroute(
    bp: Blueprint,
    netlist: lift.Netlist,
    layer: int = 0,
    *,
    hop_range: int = 0,
) -> Blueprint:
    """Strip belts and re-route via PathFinder.

    Drop-in replacement for ``route.reroute_with_junctions``.
    """
    stripped = strip_belts(bp, layer=layer)
    kept = [e for e in _all_entities(stripped) if e.layer == layer]

    # Machine/port positions → obstacles (not passable)
    machine_cells: set[tuple[int, int]] = set()
    for e in kept:
        machine_cells.add((e.x, e.y))
        if lift.kind(e.type) == "machine":
            fp = lift._machine_footprint(e.type, e.rotation)
            for dx, dy, dl in fp:
                if dl == 0:
                    machine_cells.add((e.x + dx, e.y + dy))

    # Build passable set: bounding box minus machine cells.
    all_x = [pos[0] for pos in netlist.nodes]
    all_y = [pos[1] for pos in netlist.nodes]
    margin = 5
    min_x, max_x = min(all_x) - margin, max(all_x) + margin
    min_y, max_y = min(all_y) - margin, max(all_y) + margin

    passable: set[Cell] = set()
    for x in range(min_x, max_x + 1):
        for y in range(min_y, max_y + 1):
            if (x, y) not in machine_cells:
                passable.add((x, y, layer))

    # Build nets
    nets, cell_out_dir, cell_in_dir = build_nets(netlist, layer=layer)

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
            new_terms = []
            for tx, ty, tl in net.terminals:
                orig = (tx, ty, tl)
                d = cell_in_dir.get((tx, ty))
                if d:
                    new_t = (tx + d[0], ty + d[1], tl)
                    if new_t in passable:
                        port_of_term[net.net_id].append((new_t, orig))
                        new_terms.append(new_t)
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
            new_terms = []
            for tx, ty, tl in net.terminals:
                orig = (tx, ty, tl)
                d = cell_out_dir.get((tx, ty))
                if d:
                    new_t = (tx + d[0], ty + d[1], tl)
                    if new_t in passable:
                        port_of_term[net.net_id].append((new_t, orig))
                        new_terms.append(new_t)
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
            raise RoutingError(
                f"root could not leave port cell ({net.root[0]}, {net.root[1]})"
            )
        routable.append(net)

    graph = RoutingGraph(passable=passable, hop_range=hop_range)
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
                cell, net.tree_edges, layer,
                hop_edges=net.hop_edges,
                lift_edges=net.lift_edges,
            )
            if ent is not None:
                belt_entities.append(ent)

    all_ents = kept + belt_entities
    return _rebuild_blueprint(bp, all_ents)
