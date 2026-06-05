"""Interpret a lifted netlist: push shapes through it and read the outputs.

Forward-propagates a shape from each source port, through each machine's shape
operation, to the sink ports, in topological order. This turns a lift into a
*functional* check — does the recovered netlist compute the intended transform?

Works at **cell** granularity using the netlist's ``port_edges`` (output cell ->
input cell), so multi-port machines work: a cutter takes one input and emits two
distinct outputs, a swapper takes two inputs and emits two. Equal-shape merges
collapse; a single input cell fed by genuinely different shapes is an error.
"""

from __future__ import annotations

from collections import defaultdict, deque

from shapez2_tools import shapes
from shapez2_tools.lift import Cell, Netlist, _machine_footprint
from shapez2_tools.shapes import Shape


def _machine_op(type_: str):
    """(input arity, fn[list[Shape] -> list[Shape]]) for a machine type.

    Output order matches the footprint's output-cell order (anchor first): the
    cutter emits (east=main=anchor, west=secondary=second cell); the swapper
    emits (anchor lane, second lane) after swapping their west halves.
    """
    if "RotatorHalf" in type_:
        return 1, lambda s: [shapes.rotate_180(s[0])]
    if "RotatorOneQuadCCW" in type_:  # must precede RotatorOneQuad
        return 1, lambda s: [shapes.rotate_ccw(s[0])]
    if "RotatorOneQuad" in type_:
        return 1, lambda s: [shapes.rotate_cw(s[0])]
    if "CutterHalf" in type_:  # must precede Cutter
        return 1, lambda s: [shapes.half_destroy(s[0])]
    if "Cutter" in type_:
        return 1, lambda s: list(shapes.cut(s[0]))
    if "Swapper" in type_:
        return 2, lambda s: list(shapes.swap_west(s[0], s[1]))
    raise ValueError(f"no shape op for machine {type_!r}")


def _node_cells(node) -> tuple[list[Cell], list[Cell]]:
    """(input cells, output cells) of a node, anchor-first."""
    a = (node.x, node.y)
    if node.kind == "platform_in":
        return [], [a]
    if node.kind == "platform_out":
        return [a], []
    fp = _machine_footprint(node.type, node.rotation)
    ins = [(a[0] + dx, a[1] + dy) for (dx, dy), (i, _o) in fp.items() if i]
    outs = [(a[0] + dx, a[1] + dy) for (dx, dy), (_i, o) in fp.items() if o]
    return ins, outs


def interpret(nl: Netlist, inputs: dict[Cell, Shape]) -> dict[Cell, Shape]:
    """Return the shape at each sink, given a shape at each source."""
    cell_node: dict[Cell, Cell] = {}
    in_cells: dict[Cell, list[Cell]] = {}
    out_cells: dict[Cell, list[Cell]] = {}
    for p, node in nl.nodes.items():
        ins, outs = _node_cells(node)
        in_cells[p], out_cells[p] = ins, outs
        for c in ins + outs:
            cell_node[c] = p

    feeders: dict[Cell, list[Cell]] = defaultdict(list)  # dst cell -> [src cell]
    succ: dict[Cell, set[Cell]] = defaultdict(set)
    indeg = dict.fromkeys(nl.nodes, 0)
    node_edges: set[tuple[Cell, Cell]] = set()
    for s, d in nl.port_edges:
        feeders[d].append(s)
        a, b = cell_node[s], cell_node[d]
        if a != b and (a, b) not in node_edges:
            node_edges.add((a, b))
            succ[a].add(b)
            indeg[b] += 1

    cell_shape: dict[Cell, Shape] = {}
    out: dict[Cell, Shape] = {}
    queue = deque(p for p, d in indeg.items() if d == 0)
    while queue:
        p = queue.popleft()
        node = nl.nodes[p]
        if node.kind == "platform_in":
            cell_shape[out_cells[p][0]] = inputs[p]
        else:
            feeds = []
            for c in in_cells[p]:
                distinct = {cell_shape[s] for s in feeders[c]}
                if len(distinct) != 1:
                    raise ValueError(f"input cell {c} of {p} has {len(distinct)} shapes")
                feeds.append(next(iter(distinct)))
            if node.kind == "platform_out":
                out[p] = feeds[0]
            else:
                arity, op = _machine_op(node.type)
                if len(feeds) != arity:
                    raise ValueError(f"machine at {p} has {len(feeds)} inputs, want {arity}")
                for cell, shape in zip(out_cells[p], op(feeds)):
                    cell_shape[cell] = shape
        for q in succ[p]:
            indeg[q] -= 1
            if indeg[q] == 0:
                queue.append(q)

    return out
