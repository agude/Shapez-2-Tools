"""Lift: recover a machine-level netlist from a placed blueprint.

The routing layer (belts + split/merge junctions) is calibrated as a set of
input sides and output sides per variant at R=0, rotated +90 deg CCW per R step.
Orienting the belt graph by these legs and contracting belt paths yields the
machine-to-machine netlist.

Validated on the rotator quarter: 0 unmatched legs, and the recovered netlist
matches its known structure (4 inputs each split to 2 rotators, 8 rotators each
merge to an output).

Calibrated: Forward / Left (+Mirrored) / Filter / Reader (1-in/1-out),
Splitter1To2L (+Mirrored), Merger2To1L (+Mirrored), ports, and the rotator.
Machines may span more than one cell: a machine entity is expanded into its
footprint (see ``_machine_footprint``). Calibrated machines: rotators and the
half-destroyer (1×1), the cutter (1-in/2-out) and the swapper (2-in/2-out) — each
one entity + a second cell to the side. Not yet handled: the stacker (its second
input is on the floor above — needs cross-floor support) and the painter (needs a
pipe routing layer).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

import networkx as nx

from shapez2_tools.blueprint import Blueprint
from shapez2_tools.generator import DECORATION_TYPES, all_entities

# Directions, +Y north. A +1 step in R rotates a cell 90 degrees CCW.
N, S, E, W = (0, 1), (0, -1), (1, 0), (-1, 0)


def _ccw(d: tuple[int, int]) -> tuple[int, int]:
    return (-d[1], d[0])


def _neg(d: tuple[int, int]) -> tuple[int, int]:
    return (-d[0], -d[1])


def _rot(sides: set[tuple[int, int]], r: int) -> frozenset[tuple[int, int]]:
    for _ in range(r):
        sides = {_ccw(d) for d in sides}
    return frozenset(sides)


def _rotd(d: tuple[int, int], r: int) -> tuple[int, int]:
    """Rotate a single direction +90 deg CCW, r times."""
    for _ in range(r):
        d = _ccw(d)
    return d


def routing_inout(type_: str, r: int):
    """(input sides, output sides) for a routing cell, or None if not routing."""
    if "Splitter1To2L" in type_:
        outs = {E, N} if "Mirrored" in type_ else {E, S}
        return _rot({W}, r), _rot(outs, r)
    if "Splitter1To3" in type_:  # 1 in (back), 3 out
        return _rot({W}, r), _rot({E, N, S}, r)
    if "SplitterTShape" in type_:  # 1 in (back), 2 out (both sides)
        return _rot({W}, r), _rot({N, S}, r)
    if "Merger2To1L" in type_:
        ins = {N, W} if "Mirrored" in type_ else {S, W}
        return _rot(ins, r), _rot({E}, r)
    if "Merger3To1" in type_:  # 3 in, 1 out (front)
        return _rot({N, S, W}, r), _rot({E}, r)
    if "MergerTShape" in type_:  # 2 in (both sides), 1 out (front)
        return _rot({N, S}, r), _rot({E}, r)
    if "Left" in type_:  # Left turn; Mirrored = right turn
        out = N if "Mirrored" in type_ else S
        return _rot({W}, r), _rot({out}, r)
    if type_.startswith("Belt") and "Port" not in type_:  # Forward / Filter / Reader
        return _rot({W}, r), _rot({E}, r)
    return None


def kind(type_: str) -> str:
    """Classify a building: src / sink / belt (routing) / machine."""
    if "PortReceiver" in type_:
        return "src"
    if "PortSender" in type_:
        return "sink"
    if routing_inout(type_, 0) is not None:
        return "belt"
    return "machine"


def _inout(type_: str, r: int):
    routing = routing_inout(type_, r)
    if routing is not None:
        return routing
    if "PortReceiver" in type_:
        return frozenset(), _rot({E}, r)
    if "PortSender" in type_:
        return _rot({W}, r), frozenset()
    # Machine: 1-in/1-out facing (correct for rotators; multi-port machines TODO).
    return _rot({W}, r), _rot({E}, r)


def _machine_footprint(type_: str, r: int) -> dict[tuple[int, int], tuple[frozenset, frozenset]]:
    """Occupied cells of a machine as offsets from its anchor -> (ins, outs).

    Default machine: a single 1-in/1-out cell (rotators, half-destroyer). The
    cutter and swapper each span a second cell **to the right of flow** for the
    Default variant (``Mirrored`` puts it left); both take input(s) on the back
    and emit on the front:
      - cutter (1-in/2-out): the second cell is **output-only** (its half comes
        from the internal cut), so belts merely routing past it never connect.
      - swapper (2-in/2-out): the second cell mirrors the anchor (in-back,
        out-front); the two west halves are swapped internally.
    Verified at 0 unmatched legs against data/reference/cutter_12_to_24.spz2bp
    and swap_diagonal.spz2bp (plus the pinwheel exports), every rotation/variant.
    """
    back, fwd = _rotd(W, r), _rotd(E, r)
    through = (frozenset({back}), frozenset({fwd}))  # 1-in (back) / 1-out (front)
    if ("Cutter" in type_ and "Half" not in type_) or "Swapper" in type_:
        second = _rotd(N, r) if "Mirrored" in type_ else _rotd(S, r)
        output_only = (frozenset(), frozenset({fwd}))
        return {(0, 0): through, second: through if "Swapper" in type_ else output_only}
    return {(0, 0): through}


@dataclass(frozen=True)
class _Cell:
    """One occupied tile in a placed blueprint, owned by an entity ``anchor``."""

    ins: frozenset
    outs: frozenset
    anchor: tuple[int, int]
    is_belt: bool


@dataclass(frozen=True)
class Node:
    x: int
    y: int
    layer: int
    type: str
    kind: str
    rotation: int = 0


# A cell is an (x, y) tile; an edge is a pair of cells or a pair of node anchors.
Cell = tuple[int, int]


@dataclass
class Netlist:
    nodes: dict[Cell, Node]
    edges: list[tuple[Cell, Cell]]  # node-anchor to node-anchor (machine/port level)
    # Port-level edges (output cell -> input cell), so multi-port machines keep
    # which output/input each connection uses. ``edges`` is these collapsed to
    # node anchors. Used by the interpreter to route shapes per port.
    port_edges: list[tuple[Cell, Cell]] = field(default_factory=list)


def _occupancy(bp: Blueprint, layer: int) -> dict[tuple[int, int], _Cell]:
    """Map every occupied tile on a floor to its ports and owning entity.

    Routing cells and ports occupy their own tile; a machine is expanded into
    its footprint (``_machine_footprint``), so multi-cell machines (cutters)
    contribute one tile per cell, all owned by the entity's anchor. Decoration
    is excluded -- the rotator-family assumption (trash = signage); in the Trash
    family it is functional, so this filter must become family-aware.
    """
    occ: dict[tuple[int, int], _Cell] = {}
    for e in all_entities(bp):
        if e.layer != layer or e.type in DECORATION_TYPES:
            continue
        anchor = (e.x, e.y)
        if kind(e.type) == "machine":
            for (dx, dy), (ins, outs) in _machine_footprint(e.type, e.rotation).items():
                occ[(e.x + dx, e.y + dy)] = _Cell(ins, outs, anchor, False)
        else:
            ins, outs = _inout(e.type, e.rotation)
            occ[anchor] = _Cell(ins, outs, anchor, kind(e.type) == "belt")
    return occ


def unmatched_legs(bp: Blueprint, layer: int) -> int:
    """Count routing legs with no matching partner (0 means well-formed)."""
    occ = _occupancy(bp, layer)
    bad = 0
    for (x, y), c in occ.items():
        for d in c.outs:
            n = occ.get((x + d[0], y + d[1]))
            if not (n and _neg(d) in n.ins):
                bad += 1
        for d in c.ins:
            n = occ.get((x + d[0], y + d[1]))
            if not (n and _neg(d) in n.outs):
                bad += 1
    return bad


def trace_layer(bp: Blueprint, layer: int) -> Netlist:
    """Recover the machine/port-level netlist for one floor."""
    occ = _occupancy(bp, layer)
    anchor_cells: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    for cell, c in occ.items():
        anchor_cells[c.anchor].append(cell)

    def down(cell):
        result = []
        for d in occ[cell].outs:
            n = (cell[0] + d[0], cell[1] + d[1])
            nc = occ.get(n)
            if nc and _neg(d) in nc.ins:
                result.append(n)
        return result

    def reach_cells(start):
        """Non-belt cells reachable downstream of one output cell (contract belts)."""
        out, seen, stack = set(), set(), list(down(start))
        while stack:
            cell = stack.pop()
            if cell in seen:
                continue
            seen.add(cell)
            if occ[cell].is_belt:
                stack.extend(down(cell))
            else:
                out.add(cell)
        return out

    nodes = {}
    for e in all_entities(bp):
        if e.layer != layer or e.type in DECORATION_TYPES:
            continue
        if kind(e.type) != "belt":
            nodes[(e.x, e.y)] = Node(e.x, e.y, layer, e.type, kind(e.type), e.rotation)

    # Port edges: a specific output cell -> the input cell it lands on downstream.
    port_edges = [
        (out_cell, dst_cell)
        for anchor in nodes
        for out_cell in anchor_cells[anchor]
        for dst_cell in reach_cells(out_cell)
    ]
    # Collapse to node-anchor granularity for the kind-level view (back-compat).
    edges = sorted({(occ[s].anchor, occ[d].anchor) for s, d in port_edges})
    return Netlist(nodes, edges, port_edges)


def edge_kinds(nl: Netlist) -> Counter:
    """Count netlist edges by (source kind, destination kind)."""
    return Counter((nl.nodes[a].kind, nl.nodes[b].kind) for a, b in nl.edges)


def to_graph(nl: Netlist) -> nx.MultiDiGraph:
    """Convert a Netlist to a networkx MultiDiGraph for isomorphism tests.

    Node attributes: (kind, type) — kind distinguishes src/sink/machine; type
    distinguishes machine variants (rotator cw vs ccw). Edges are unlabelled.
    Using a MultiDiGraph because parallel edges (multiple lanes) are possible.
    """
    g = nx.MultiDiGraph()
    for anchor, node in nl.nodes.items():
        g.add_node(anchor, kind=node.kind, type=node.type)
    for src, dst in nl.edges:
        g.add_edge(src, dst)
    return g


def isomorphic(a: Netlist, b: Netlist) -> bool:
    """Placement-independent equality: same graph structure and node types."""
    ga, gb = to_graph(a), to_graph(b)

    def node_match(n1, n2):
        return n1["kind"] == n2["kind"] and n1["type"] == n2["type"]

    return nx.is_isomorphic(ga, gb, node_match=node_match)
