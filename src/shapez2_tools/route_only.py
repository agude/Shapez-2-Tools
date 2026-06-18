"""Route-only mode: route missing connections without disturbing existing placement.

Unlike ``place``, which re-places *and* re-routes a netlist from scratch, this
module takes a half-completed, hand-placed blueprint and routes only the
unconnected ends — existing machines and belts are immovable obstacles.  See
``docs/route-only-spec.md`` for the full design.
"""

from __future__ import annotations

from dataclasses import dataclass

from shapez2_tools import lift, pathfinder
from shapez2_tools.blueprint import Blueprint
from shapez2_tools.generator import Entity, all_entities


@dataclass(frozen=True)
class DanglingEnd:
    x: int
    y: int
    half: str  # "west" or "east"


def _dangle_positions(occ: dict[tuple[int, int], lift._Cell]) -> list[tuple[int, int]]:
    """Cells whose output points into empty space (no matching adjacent input).

    Same scan as the output-leg half of ``lift.unmatched_legs``, returning
    positions instead of a count.
    """
    positions = []
    for (x, y), c in occ.items():
        for d in c.outs:
            target = (x + d[0], y + d[1])
            n = occ.get(target)
            if not (n and lift._neg(d) in n.ins):
                positions.append((x, y))
    return positions


def _classify_dangle(
    pos: tuple[int, int],
    bp: Blueprint,
    layer: int,
    machines: dict[tuple[int, int], Entity],
) -> str:
    """Trace a dangle upstream, across hops, to its source cutter half.

    The cutter's anchor cell and second cell (see ``lift._machine_footprint``)
    always produce opposite halves, and which absolute half each one produces
    is rotation-invariant (mirrored swaps it). Mergers (cells with multiple
    ``ins``) collapse several cutters into one stream; the spec assumes they
    always combine outputs of the same half, so any upstream branch may be
    followed — true for all but a rare pre-existing wiring quirk in
    hand-placed blueprints, which this function does not attempt to detect.
    """
    cur, cell = lift.trace_upstream(bp, layer, pos)
    entity = machines[cell.anchor]
    mirrored = "Mirrored" in entity.type
    is_anchor_cell = cur == cell.anchor
    if is_anchor_cell:
        return "west" if mirrored else "east"
    return "east" if mirrored else "west"


def find_dangles(bp: Blueprint, layer: int) -> list[tuple[int, int]]:
    """Dangling belt/merger output positions on a layer."""
    return _dangle_positions(lift._occupancy(bp, layer))


def find_and_classify_dangles(bp: Blueprint, layer: int) -> list[DanglingEnd]:
    """Find dangling belt/merger outputs on a layer and label by source-cutter half."""
    occ = lift._occupancy(bp, layer)
    machines = {
        (e.x, e.y): e
        for e in all_entities(bp)
        if e.layer == layer and lift.kind(e.type) == "machine"
    }
    return [
        DanglingEnd(x, y, _classify_dangle((x, y), bp, layer, machines))
        for x, y in _dangle_positions(occ)
    ]


def find_free_port_positions(bp: Blueprint, layer: int) -> list[tuple[int, int]]:
    """Platform-edge port positions with no entity on *layer* — targets for new routes."""
    port_positions = lift._platform_port_positions(bp)
    occupied = {(e.x, e.y) for e in all_entities(bp) if e.layer == layer}
    return sorted(p for p in port_positions if p not in occupied)


def partition_ports(
    ports: list[tuple[int, int]], platform: str
) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Split ports into west/east groups by position relative to platform center.

    Matches the hand-routed convention already present in the source
    blueprint: west-half shapes go to ports west of the platform's
    horizontal center, east-half shapes to ports east of it.
    """
    min_x, max_x, _min_y, _max_y = pathfinder._platform_bounds(platform)
    center_x = (min_x + max_x) / 2
    west = [p for p in ports if p[0] < center_x]
    east = [p for p in ports if p[0] >= center_x]
    return west, east


def build_passable_from_occupancy(
    bp: Blueprint,
    layer: int,
    platform: str,
    endpoints: set[tuple[int, int]] | None = None,
) -> set[pathfinder.Cell]:
    """Passable cells for routing into an already-placed layer.

    Unlike ``pathfinder._build_passable`` (which only excludes machine
    cells, since the existing belts are about to be stripped), every
    occupied tile here is a fixed obstacle — belts, machines, ports,
    mergers, splitters all stay put. ``endpoints`` are net endpoints
    (dangles and unconnected ports): they already have an entity in
    ``bp`` but the router must still treat them as passable, since it
    needs to terminate a path there.

    The platform-edge ring (ports-only in-game, see ``_build_passable``)
    is excluded from ``passable`` for the same reason, with the same
    endpoint exception.
    """
    occ = lift._occupancy(bp, layer)
    min_x, max_x, min_y, max_y = pathfinder._platform_bounds(platform)
    endpoints = endpoints or set()

    passable: set[pathfinder.Cell] = set()
    for x in range(min_x, max_x + 1):
        for y in range(min_y, max_y + 1):
            pos = (x, y)
            if pos in endpoints:
                passable.add((x, y, layer))
                continue
            if pos in occ:
                continue
            on_ring = x in (min_x, max_x) or y in (min_y, max_y)
            if on_ring:
                continue
            passable.add((x, y, layer))
    return passable


def match_dangles_to_ports(
    dangles: list[tuple[int, int]], ports: list[tuple[int, int]]
) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """Greedily pair each dangle with its nearest unmatched port (Manhattan distance).

    Assumes both lists are already partitioned into the same west/east group
    by the caller. If counts differ, the shorter side is exhausted first and
    the rest of the longer side is left unmatched.
    """
    candidates = sorted(
        (
            (abs(dx - px) + abs(dy - py), (dx, dy), (px, py))
            for dx, dy in dangles
            for px, py in ports
        ),
        key=lambda t: t[0],
    )
    matched_dangles: set[tuple[int, int]] = set()
    matched_ports: set[tuple[int, int]] = set()
    pairs = []
    for _dist, d, p in candidates:
        if d in matched_dangles or p in matched_ports:
            continue
        matched_dangles.add(d)
        matched_ports.add(p)
        pairs.append((d, p))
    return pairs


def _dangle_direction(
    pos: tuple[int, int], occ: dict[tuple[int, int], lift._Cell]
) -> tuple[int, int]:
    """The output direction of *pos* that points into empty space."""
    c = occ[pos]
    for d in c.outs:
        target = (pos[0] + d[0], pos[1] + d[1])
        n = occ.get(target)
        if not (n and lift._neg(d) in n.ins):
            return d
    raise ValueError(f"{pos} has no dangling output direction")


def _port_face(pos: tuple[int, int], platform: str) -> tuple[tuple[int, int], int]:
    """Interior-facing direction and sender rotation for a free port at *pos*.

    Calibrated against placed ``BeltPortSenderInternalVariant`` entities in
    the reference blueprint corpus: a port on the east edge faces outward
    at R=0 (fed from the west, interior, side); rotating +90 deg CCW per
    edge gives north=R1 (fed from south), west=R2 (fed from east), south=R3
    (fed from north).
    """
    min_x, max_x, min_y, max_y = pathfinder._platform_bounds(platform)
    x, y = pos
    if x == max_x:
        return lift.W, 0
    if y == max_y:
        return lift.S, 1
    if x == min_x:
        return lift.E, 2
    if y == min_y:
        return lift.N, 3
    raise ValueError(f"{pos} is not on a platform edge of {platform!r}")


def build_routing_nets(
    matched_pairs: list[tuple[tuple[int, int], tuple[int, int]]],
    bp: Blueprint,
    layer: int,
    platform: str,
) -> list[pathfinder.Net]:
    """Build one 1->1 fanout net per matched (dangle, port) pair.

    The dangle and port cells already exist (dangle) or will be placed
    during merge (port) — neither is a routing cell. Each net's root and
    terminal are the first free cell stepping off the dangle (in its
    dangling-output direction) and off the port (in its interior-facing
    direction), matching the boundary-edge convention in
    ``pathfinder.strip_and_reroute``.
    """
    occ = lift._occupancy(bp, layer)
    nets = []
    for net_id, (dangle, port) in enumerate(matched_pairs):
        ddir = _dangle_direction(dangle, occ)
        root: pathfinder.Cell = (dangle[0] + ddir[0], dangle[1] + ddir[1], layer)
        pdir, _rotation = _port_face(port, platform)
        term: pathfinder.Cell = (port[0] + pdir[0], port[1] + pdir[1], layer)
        nets.append(
            pathfinder.Net(
                net_id=net_id,
                kind="fanout",
                root=root,
                terminals=[term],
                root_offset=True,
                root_approach=ddir,
                terminal_exit={term: (-pdir[0], -pdir[1])},
            )
        )
    return nets


def _attach_boundary_edges(nets: list[pathfinder.Net]) -> None:
    """Insert dangle->root and terminal->port edges for correct emit at the
    routing tree's boundary cells.

    The dangle and port cells are not added to ``tree_cells`` — the dangle
    already has a real entity in the blueprint, and the port's sender
    entity is placed separately during merge (Chunk 6) — but
    ``pathfinder._cell_to_entity`` needs these edges to compute the correct
    in/out directions for the root and terminal routing cells.
    """
    for net in nets:
        rx, ry, rl = net.root
        ax, ay = net.root_approach
        dangle: pathfinder.Cell = (rx - ax, ry - ay, rl)
        net.tree_edges.insert(0, (dangle, net.root))

        term = net.terminals[0]
        pdx, pdy = net.terminal_exit[term]
        port: pathfinder.Cell = (term[0] + pdx, term[1] + pdy, term[2])
        net.tree_edges.append((term, port))


def _existing_hop_endpoints(
    bp: Blueprint, layer: int
) -> tuple[dict[pathfinder.Cell, tuple[int, int]], dict[pathfinder.Cell, tuple[int, int]]]:
    """Pre-existing interior-hop sender/receiver positions -> launch direction.

    Feeds ``pathfinder.RoutingGraph.existing_senders/receivers`` (§0b) so
    new hops placed by the router don't conflict with hops already in the
    hand-placed blueprint under the furthest-first pairing rule.
    """
    port_positions = lift._platform_port_positions(bp)
    senders: dict[pathfinder.Cell, tuple[int, int]] = {}
    receivers: dict[pathfinder.Cell, tuple[int, int]] = {}
    for e in all_entities(bp):
        if e.layer != layer:
            continue
        pos = (e.x, e.y)
        if not lift._is_interior_hop(e.type, pos, port_positions):
            continue
        cell: pathfinder.Cell = (e.x, e.y, layer)
        d = lift._DIR_VEC[e.rotation]
        if "Sender" in e.type:
            senders[cell] = d
        else:
            receivers[cell] = d
    return senders, receivers


def route_layer_nets(
    bp: Blueprint, layer: int, hop_range: int = lift.MAX_HOP_RANGE
) -> list[pathfinder.Net]:
    """Run Chunks 1-5 for one layer: find, classify, match, build, and route.

    Returns routed ``Net`` objects (boundary edges attached) ready for
    ``pathfinder.emit_entities`` — merging the resulting belts plus a new
    ``BeltPortSenderInternalVariant`` at each matched port back into the
    blueprint is Chunk 6.
    """
    platform = bp.entries[0]["T"]
    dangles = find_and_classify_dangles(bp, layer)
    ports = find_free_port_positions(bp, layer)
    west_ports, east_ports = partition_ports(ports, platform)
    west_dangles = [(d.x, d.y) for d in dangles if d.half == "west"]
    east_dangles = [(d.x, d.y) for d in dangles if d.half == "east"]
    pairs = match_dangles_to_ports(west_dangles, west_ports) + match_dangles_to_ports(
        east_dangles, east_ports
    )

    nets = build_routing_nets(pairs, bp, layer, platform)
    endpoints = {(c[0], c[1]) for n in nets for c in (n.root, n.terminals[0])}
    passable = build_passable_from_occupancy(bp, layer, platform, endpoints=endpoints)
    senders, receivers = _existing_hop_endpoints(bp, layer)
    graph = pathfinder.RoutingGraph(
        passable=passable,
        hop_range=hop_range,
        existing_senders=senders,
        existing_receivers=receivers,
    )
    pathfinder.pathfinder_route(nets, graph)
    _attach_boundary_edges(nets)
    return nets

