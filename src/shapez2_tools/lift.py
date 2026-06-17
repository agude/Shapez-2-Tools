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
footprint (see ``_machine_footprint``).  Footprint keys are 3-D offsets
``(dx, dy, dl)`` where ``dl`` is the layer offset (0 = same floor).
Calibrated machines: rotators and the half-destroyer (1×1), the cutter
(1-in/2-out) and the swapper (2-in/2-out) — each one entity + a second cell
to the side — and the stacker (2-in/1-out, three variants with distinct
output directions: ``StackerStraight`` forward, ``StackerDefault`` right of
flow, ``StackerDefaultMirrored`` left of flow).  The stacker's secondary
input is a cross-floor claim at ``(0, 0, +1)`` — the belt on the floor above
feeds into the anchor position.  ``trace_layer`` works per-floor;
``trace`` spans all floors via ``_occupancy_3d``.  Not yet handled: the
painter (needs a pipe routing layer).
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx

from shapez2_tools.blueprint import Blueprint
from shapez2_tools.generator import DECORATION_TYPES, all_entities

_DATA = Path(__file__).resolve().parent.parent.parent / "data"

# Direction vectors: R=0→+X(E), R=1→+Y(N), R=2→-X(W), R=3→-Y(S).
_DIR_VEC = {0: (1, 0), 1: (0, 1), 2: (-1, 0), 3: (0, -1)}

# Directions, +Y north. A +1 step in R rotates a cell 90 degrees CCW.
N, S, E, W = (0, 1), (0, -1), (1, 0), (-1, 0)

# In-game launcher/catcher hop limit (QUESTIONS.md Q7): 1-4 blank flight
# tiles between sender and receiver, i.e. sender-to-receiver cell distance
# hdist = blank_tiles + 1 in [2, 5]. Shared by pathfinder.py's RoutingGraph
# and _resolve_hops below.
MAX_HOP_RANGE = 5


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
    if "Lift" in type_:
        return None
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


def lift_inout(
    type_: str, r: int
) -> tuple[frozenset, frozenset, int] | None:
    """``(input sides, output sides, layer delta)`` for a lift, or ``None``.

    Calibrated empirically from 20+ blueprints across all 16 lift variants.
    Every lift takes input from its back at its own layer and outputs at
    L + delta in the named exit direction (Forward/Backward/Left/LeftMirrored).
    """
    if "Lift" not in type_:
        return None
    floors = 1 if "Lift1" in type_ else 2 if "Lift2" in type_ else 0
    if not floors:
        return None
    delta = floors if "Up" in type_ else -floors
    if "Forward" in type_:
        exit_dir = E
    elif "Backward" in type_:
        exit_dir = W
    elif "Mirrored" in type_:
        exit_dir = N
    elif "Left" in type_:
        exit_dir = S
    else:
        return None
    return _rot({W}, r), _rot({exit_dir}, r), delta


def _lift_footprint(
    type_: str, r: int
) -> dict[tuple[int, int, int], tuple[frozenset, frozenset]] | None:
    """Multi-floor cell expansion for a lift entity, or ``None``.

    Returns ``{(dx, dy, dl): (ins, outs)}`` keyed by offset from the entity
    anchor.  The input cell (dl=0) has only input legs; the output cell
    (dl=delta) has only output legs; intermediate cells (Lift2) are blockers.
    """
    info = lift_inout(type_, r)
    if info is None:
        return None
    ins, outs, delta = info
    cells: dict[tuple[int, int, int], tuple[frozenset, frozenset]] = {
        (0, 0, 0): (ins, frozenset()),
        (0, 0, delta): (frozenset(), outs),
    }
    sign = 1 if delta > 0 else -1
    for dl in range(sign, delta, sign):
        cells[(0, 0, dl)] = (frozenset(), frozenset())
    return cells


def kind(type_: str) -> str:
    """Classify a building: platform_in / platform_out / belt (routing) / machine."""
    if "PortReceiver" in type_:
        return "platform_in"
    if "PortSender" in type_:
        return "platform_out"
    if routing_inout(type_, 0) is not None:
        return "belt"
    if lift_inout(type_, 0) is not None:
        return "lift"
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


def _lift_inout_same_floor(type_: str, r: int):
    """Lift's legs visible on its own floor (input only, no same-floor output)."""
    info = lift_inout(type_, r)
    if info is None:
        return None
    ins, _outs, _delta = info
    return ins, frozenset()


def _platform_port_positions(bp: Blueprint) -> set[tuple[int, int]]:
    """Known platform-edge port positions from platforms.json."""
    platform_type = bp.entries[0]["T"] if bp.entries else None
    if not platform_type:
        return set()
    with open(_DATA / "platforms.json") as f:
        platforms = json.load(f)
    plat = platforms.get(platform_type)
    if not plat or "ports" not in plat:
        return set()
    return {(x, y) for x, y, _r in plat["ports"]}


def _is_interior_hop(
    type_: str, pos: tuple[int, int], port_positions: set[tuple[int, int]]
) -> bool:
    """True if an entity is an interior hop endpoint (not a platform-edge port)."""
    return ("PortSender" in type_ or "PortReceiver" in type_) and pos not in port_positions


def _resolve_hops(
    bp: Blueprint, layer: int, port_positions: set[tuple[int, int]]
) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """Pair interior hop senders with receivers and return directed edges.

    Pairing rule (in-game: a launcher connects to the *furthest* catcher in
    range — see https://shapez2.wiki.gg/wiki/Conveyor_Belt): scan along the
    sender's facing direction from ``MAX_HOP_RANGE`` down to 1; the first
    (furthest) receiver with the same rotation is its partner.  Returns
    ``(sender_pos, receiver_pos)`` pairs — each acts as a long straight belt
    in the netlist.
    """
    senders = []
    receivers_by_pos: dict[tuple[int, int], tuple[int, int]] = {}
    receiver_rotations: dict[tuple[int, int], int] = {}

    for e in all_entities(bp):
        if e.layer != layer:
            continue
        pos = (e.x, e.y)
        if _is_interior_hop(e.type, pos, port_positions):
            if "Sender" in e.type:
                senders.append(e)
            else:
                receivers_by_pos[pos] = pos
                receiver_rotations[pos] = e.rotation

    # Sort senders so that within each facing direction, the sender whose
    # items reach receivers first is processed first.  For west-facing hops
    # (dx=-1), the easternmost sender launches first; sort key = dx*x + dy*y
    # ascending naturally handles all four directions.
    senders.sort(
        key=lambda s: (s.rotation, _DIR_VEC[s.rotation][0] * s.x + _DIR_VEC[s.rotation][1] * s.y)
    )

    pairs: list[tuple[tuple[int, int], tuple[int, int]]] = []
    used_receivers: set[tuple[int, int]] = set()
    for s in senders:
        dx, dy = _DIR_VEC[s.rotation]
        for dist in range(MAX_HOP_RANGE, 0, -1):
            rx, ry = s.x + dx * dist, s.y + dy * dist
            rpos = (rx, ry)
            if rpos in receivers_by_pos and rpos not in used_receivers:
                if receiver_rotations[rpos] == s.rotation:
                    pairs.append(((s.x, s.y), rpos))
                    used_receivers.add(rpos)
                    break
    return pairs


def _machine_footprint(
    type_: str, r: int
) -> dict[tuple[int, int, int], tuple[frozenset, frozenset]]:
    """Occupied cells of a machine as 3-D offsets ``(dx, dy, dl)`` -> ``(ins, outs)``.

    Keys are ``(dx, dy, dl)`` relative to the anchor, where ``dl`` is the layer
    offset (0 = same floor, 1 = one floor up).  Most machines are single-cell
    ``(0, 0, 0)``; the cutter/swapper span a second cell on the same floor; the
    stacker claims a secondary-input cell one floor up.

    Stacker variants:
      - ``StackerStraight``: 1-in (back) / 1-out (front), + L+1 in (back).
      - ``StackerDefault``: 1-in (back) / 1-out (right of flow), + L+1 in (back).
      - ``StackerDefault…Mirrored``: 1-in (back) / 1-out (left of flow), + L+1 in.
    """
    back, fwd = _rotd(W, r), _rotd(E, r)
    through = (frozenset({back}), frozenset({fwd}))  # 1-in (back) / 1-out (front)
    if ("Cutter" in type_ and "Half" not in type_) or "Swapper" in type_:
        second = _rotd(N, r) if "Mirrored" in type_ else _rotd(S, r)
        output_only = (frozenset(), frozenset({fwd}))
        return {
            (0, 0, 0): through,
            (*second, 0): through if "Swapper" in type_ else output_only,
        }
    if "Stacker" in type_:
        if "Straight" in type_:
            out_dir = fwd
        elif "Mirrored" in type_:
            out_dir = _rotd(N, r)
        else:
            out_dir = _rotd(S, r)
        l0 = (frozenset({back}), frozenset({out_dir}))
        l1_in = (frozenset({back}), frozenset())
        return {(0, 0, 0): l0, (0, 0, 1): l1_in}
    return {(0, 0, 0): through}


@dataclass(frozen=True)
class _Cell:
    """One occupied tile in a placed blueprint, owned by an entity ``anchor``."""

    ins: frozenset
    outs: frozenset
    anchor: tuple[int, int]
    is_belt: bool
    out_layer_delta: int = 0
    is_lift_exit: bool = False


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


def _occupancy(
    bp: Blueprint,
    layer: int,
    skip_positions: set[tuple[int, int]] | None = None,
) -> dict[tuple[int, int], _Cell]:
    """Map every occupied tile on a floor to its ports and owning entity.

    Routing cells and ports occupy their own tile; a machine is expanded into
    its footprint (``_machine_footprint``), so multi-cell machines (cutters)
    contribute one tile per cell, all owned by the entity's anchor. Decoration
    is excluded -- the rotator-family assumption (trash = signage); in the Trash
    family it is functional, so this filter must become family-aware.

    ``skip_positions`` (optional): cells to exclude from the occupancy map —
    used for interior hop endpoints which are paired separately.
    """
    occ: dict[tuple[int, int], _Cell] = {}
    for e in all_entities(bp):
        if e.type in DECORATION_TYPES:
            continue
        anchor = (e.x, e.y)
        if skip_positions and anchor in skip_positions:
            continue
        k = kind(e.type)
        if k == "lift":
            info = lift_inout(e.type, e.rotation)
            if info is None:
                continue
            ins, outs, delta = info
            sign = 1 if delta > 0 else -1
            if e.layer == layer:
                occ[anchor] = _Cell(ins, frozenset(), anchor, True)
            elif e.layer + delta == layer:
                occ[anchor] = _Cell(frozenset(), outs, anchor, True,
                                    is_lift_exit=True)
            else:
                for dl in range(sign, delta, sign):
                    if e.layer + dl == layer:
                        occ[anchor] = _Cell(frozenset(), frozenset(), anchor, True)
        elif k == "machine":
            if e.layer != layer:
                continue
            for (dx, dy, dl), (ins, outs) in _machine_footprint(e.type, e.rotation).items():
                if dl != 0:
                    continue
                occ[(e.x + dx, e.y + dy)] = _Cell(ins, outs, anchor, False)
        else:
            if e.layer != layer:
                continue
            ins, outs = _inout(e.type, e.rotation)
            occ[anchor] = _Cell(ins, outs, anchor, k == "belt")
    return occ


def unmatched_legs(bp: Blueprint, layer: int) -> int:
    """Count routing legs with no matching partner (0 means well-formed).

    Lift exit cells (the destination floor of a lift entity) are excluded from
    counting: they have no physical entity on this floor — the lift entity on
    the source floor realizes both the entry and exit connections.  Adjacent
    cells whose output points toward a lift exit are also excluded, since the
    lift entity occupies that position.
    """
    occ = _occupancy(bp, layer)
    lift_exit_pos = {(x, y) for (x, y), c in occ.items() if c.is_lift_exit}
    bad = 0
    for (x, y), c in occ.items():
        if c.is_lift_exit:
            continue
        for d in c.outs:
            target = (x + d[0], y + d[1])
            if target in lift_exit_pos:
                continue
            n = occ.get(target)
            if not (n and _neg(d) in n.ins):
                bad += 1
        for d in c.ins:
            source = (x + d[0], y + d[1])
            if source in lift_exit_pos:
                continue
            n = occ.get(source)
            if not (n and _neg(d) in n.outs):
                bad += 1
    return bad


def trace_upstream(
    bp: Blueprint, layer: int, start: tuple[int, int]
) -> tuple[tuple[int, int], _Cell]:
    """Walk upstream from a belt/port cell, across hops, to the originating machine.

    ``BeltPortReceiver`` and ``BeltPortSender`` both have ``is_belt = False``
    but neither is a terminal: a receiver's upstream is its paired sender
    (looked up via ``_resolve_hops``), and a sender's upstream is whatever
    feeds its own input leg, same as a belt. The walk stops at the first
    machine cell.
    """
    occ = _occupancy(bp, layer)
    port_positions = _platform_port_positions(bp)
    sender_by_receiver = {r: s for s, r in _resolve_hops(bp, layer, port_positions)}
    entity_type = {(e.x, e.y): e.type for e in all_entities(bp) if e.layer == layer}

    cur = start
    visited = {cur}
    while True:
        cell = occ[cur]
        if kind(entity_type[cell.anchor]) == "machine":
            return cur, cell
        if kind(entity_type[cell.anchor]) == "platform_in":
            cur = sender_by_receiver[cur]
        else:
            d = next(iter(cell.ins))
            cur = (cur[0] + d[0], cur[1] + d[1])
        if cur in visited:
            raise ValueError(f"cycle detected tracing upstream from {start}")
        visited.add(cur)


def trace_layer(bp: Blueprint, layer: int, *, contract_hops: bool = False) -> Netlist:
    """Recover the machine/port-level netlist for one floor.

    When ``contract_hops`` is True, interior hop endpoints (launcher/catcher
    pairs at non-port positions) are resolved and contracted: each hop acts as
    a transparent belt connecting the sender's upstream to the receiver's
    downstream.  When False (default), hop endpoints are treated as regular
    platform_in/platform_out nodes — backward-compatible with existing corpus
    tests that were calibrated before hop support.
    """
    hop_send_to_recv: dict[tuple[int, int], tuple[int, int]] = {}
    hop_senders: set[tuple[int, int]] = set()
    hop_receivers: set[tuple[int, int]] = set()

    if contract_hops:
        port_positions = _platform_port_positions(bp)
        hop_pairs = _resolve_hops(bp, layer, port_positions)
        hop_send_to_recv = dict(hop_pairs)
        hop_senders = set(hop_send_to_recv)
        hop_receivers = set(hop_send_to_recv.values())

    occ = _occupancy(bp, layer)

    if contract_hops:
        for pos in hop_senders | hop_receivers:
            if pos in occ:
                c = occ[pos]
                occ[pos] = _Cell(c.ins, c.outs, c.anchor, is_belt=True)

    anchor_cells: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    for cell, c in occ.items():
        anchor_cells[c.anchor].append(cell)

    def down(cell):
        result = []
        if cell in hop_senders:
            recv = hop_send_to_recv[cell]
            if recv in occ:
                result.append(recv)
            return result
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
        pos = (e.x, e.y)
        if pos in hop_senders or pos in hop_receivers:
            continue
        if kind(e.type) not in ("belt", "lift"):
            nodes[pos] = Node(e.x, e.y, layer, e.type, kind(e.type), e.rotation)

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


Cell3D = tuple[int, int, int]


def _occupancy_3d(bp: Blueprint) -> dict[Cell3D, _Cell]:
    """Map every occupied tile across all floors to its ports and owning entity.

    Like ``_occupancy`` but keyed by ``(x, y, layer)``.  Machine footprints
    with ``dl != 0`` (stackers' cross-floor input) are included at their
    absolute layer.
    """
    occ: dict[Cell3D, _Cell] = {}
    for e in all_entities(bp):
        if e.type in DECORATION_TYPES:
            continue
        anchor: Cell3D = (e.x, e.y, e.layer)
        k = kind(e.type)
        if k == "lift":
            info = lift_inout(e.type, e.rotation)
            if info is not None:
                ins, outs, delta = info
                occ[anchor] = _Cell(
                    ins, outs, anchor, True, out_layer_delta=delta
                )
                sign = 1 if delta > 0 else -1
                for dl in range(sign, delta + sign, sign):
                    blocker: Cell3D = (e.x, e.y, e.layer + dl)
                    if blocker not in occ:
                        occ[blocker] = _Cell(
                            frozenset(), frozenset(), anchor, True
                        )
        elif k == "machine":
            for (dx, dy, dl), (ins, outs) in _machine_footprint(e.type, e.rotation).items():
                occ[(e.x + dx, e.y + dy, e.layer + dl)] = _Cell(ins, outs, anchor, False)
        else:
            ins, outs = _inout(e.type, e.rotation)
            occ[anchor] = _Cell(ins, outs, anchor, k == "belt")
    return occ


def trace(bp: Blueprint) -> Netlist:
    """Recover the machine/port-level netlist spanning all floors.

    Cross-floor connections (e.g. a stacker's L+1 secondary input) are
    resolved through the 3-D occupancy: a belt on floor *L+1* can feed
    into a machine claim cell on that floor, whose anchor is the machine
    entity on floor *L*.  Belt paths are contracted exactly as in
    ``trace_layer``.

    Node keys are 3-D ``(x, y, layer)`` tuples (stored in a ``Netlist``
    whose ``Cell`` alias is nominally 2-D — the runtime types are 3-tuples).
    """
    occ = _occupancy_3d(bp)
    anchor_cells: dict[Cell3D, list[Cell3D]] = defaultdict(list)
    for cell, c in occ.items():
        anchor_cells[c.anchor].append(cell)

    def down(cell: Cell3D) -> list[Cell3D]:
        result: list[Cell3D] = []
        c = occ[cell]
        target_layer = cell[2] + c.out_layer_delta
        for d in c.outs:
            n: Cell3D = (cell[0] + d[0], cell[1] + d[1], target_layer)
            nc = occ.get(n)
            if nc and _neg(d) in nc.ins:
                result.append(n)
        return result

    def reach_cells(start: Cell3D) -> set[Cell3D]:
        out: set[Cell3D] = set()
        seen: set[Cell3D] = set()
        stack = list(down(start))
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
    node_anchors: set[Cell3D] = set()
    for e in all_entities(bp):
        if e.type in DECORATION_TYPES:
            continue
        if kind(e.type) not in ("belt", "lift"):
            key: Cell3D = (e.x, e.y, e.layer)
            nodes[key] = Node(e.x, e.y, e.layer, e.type, kind(e.type), e.rotation)
            node_anchors.add(key)

    port_edges_3d: list[tuple[Cell3D, Cell3D]] = [
        (out_cell, dst_cell)
        for anchor_3d in node_anchors
        for out_cell in anchor_cells.get(anchor_3d, [])
        for dst_cell in reach_cells(out_cell)
    ]
    edges_3d = sorted({(occ[s].anchor, occ[d].anchor) for s, d in port_edges_3d})
    return Netlist(nodes, edges_3d, port_edges_3d)


def edge_kinds(nl: Netlist) -> Counter:
    """Count netlist edges by (source kind, destination kind)."""
    return Counter((nl.nodes[a].kind, nl.nodes[b].kind) for a, b in nl.edges)


def to_graph(nl: Netlist) -> nx.MultiDiGraph:
    """Convert a Netlist to a networkx MultiDiGraph for isomorphism tests.

    Node attributes: (kind, type) — kind distinguishes platform_in/platform_out/
    machine; type distinguishes machine variants (rotator cw vs ccw). Edges are
    unlabelled.
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


@dataclass
class Problem:
    """A physical validity problem in a blueprint."""

    kind: str
    message: str

    def __str__(self):
        return f"{self.kind}: {self.message}"


def validate(bp: Blueprint) -> list[Problem]:
    """Check physical validity: overlaps, dangling legs, off-grid.

    Returns an empty list if the blueprint is valid.
    """
    problems: list[Problem] = []

    # Collect all entities across all platforms.
    occupied: dict[tuple[int, int, int], list[str]] = defaultdict(list)
    for e in all_entities(bp):
        key = (e.x, e.y, e.layer)
        occupied[key].append(e.type)
        # Multi-cell machines: also check their footprint cells.
        if kind(e.type) == "machine":
            for dx, dy, dl in _machine_footprint(e.type, e.rotation):
                if (dx, dy, dl) != (0, 0, 0):
                    key2 = (e.x + dx, e.y + dy, e.layer + dl)
                    occupied[key2].append(f"{e.type}[+{dx},{dy},{dl}]")

    # Check for overlaps.
    for (x, y, layer), types in occupied.items():
        if len(types) > 1:
            problems.append(
                Problem("overlap", f"({x}, {y}, L{layer}) occupied by: {', '.join(types)}")
            )

    # Check for dangling legs on each floor.
    for layer in range(3):
        legs = unmatched_legs(bp, layer)
        if legs > 0:
            problems.append(Problem("dangling", f"layer {layer} has {legs} unmatched legs"))

    return problems
