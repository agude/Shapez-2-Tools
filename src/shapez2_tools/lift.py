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
Not yet calibrated: other junctions (3To1, 1To3, TShape) and multi-port machines
(cutters, stackers, ...), which need their own entries.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

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


def routing_inout(type_: str, r: int):
    """(input sides, output sides) for a routing cell, or None if not routing."""
    if "Splitter1To2L" in type_:
        outs = {E, N} if "Mirrored" in type_ else {E, S}
        return _rot({W}, r), _rot(outs, r)
    if "Merger2To1L" in type_:
        ins = {N, W} if "Mirrored" in type_ else {S, W}
        return _rot(ins, r), _rot({E}, r)
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


@dataclass(frozen=True)
class Node:
    x: int
    y: int
    layer: int
    type: str
    kind: str


@dataclass
class Netlist:
    nodes: dict[tuple[int, int], Node]
    edges: list[tuple[tuple[int, int], tuple[int, int]]]


def _cells(bp: Blueprint, layer: int) -> dict[tuple[int, int], object]:
    # Exclude decoration. This is the rotator-family assumption (trash = signage);
    # in the Trash family it is functional, so this filter must become family-aware.
    return {
        (e.x, e.y): e
        for e in all_entities(bp)
        if e.layer == layer and e.type not in DECORATION_TYPES
    }


def unmatched_legs(bp: Blueprint, layer: int) -> int:
    """Count routing legs with no matching partner (0 means well-formed)."""
    cells = _cells(bp, layer)
    bad = 0
    for (x, y), e in cells.items():
        ins, outs = _inout(e.type, e.rotation)
        for d in outs:
            n = cells.get((x + d[0], y + d[1]))
            if not (n and _neg(d) in _inout(n.type, n.rotation)[0]):
                bad += 1
        for d in ins:
            n = cells.get((x + d[0], y + d[1]))
            if not (n and _neg(d) in _inout(n.type, n.rotation)[1]):
                bad += 1
    return bad


def trace_layer(bp: Blueprint, layer: int) -> Netlist:
    """Recover the machine/port-level netlist for one floor."""
    cells = _cells(bp, layer)

    def down(p):
        _, outs = _inout(cells[p].type, cells[p].rotation)
        result = []
        for d in outs:
            n = (p[0] + d[0], p[1] + d[1])
            if n in cells and _neg(d) in _inout(cells[n].type, cells[n].rotation)[0]:
                result.append(n)
        return result

    def reach(p):
        out, seen, stack = set(), set(), list(down(p))
        while stack:
            c = stack.pop()
            if c in seen:
                continue
            seen.add(c)
            if kind(cells[c].type) == "belt":
                stack.extend(down(c))
            else:
                out.add(c)
        return out

    nodes = {
        p: Node(p[0], p[1], layer, e.type, kind(e.type))
        for p, e in cells.items()
        if kind(e.type) != "belt"
    }
    edges = [(p, d) for p in nodes for d in reach(p)]
    return Netlist(nodes, edges)


def edge_kinds(nl: Netlist) -> Counter:
    """Count netlist edges by (source kind, destination kind)."""
    return Counter((nl.nodes[a].kind, nl.nodes[b].kind) for a, b in nl.edges)
