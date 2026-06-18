"""Interpret a lifted netlist: push shapes through it and read the outputs.

Forward-propagates a shape from each source port, through each machine's shape
operation, to the sink ports, in topological order. This turns a lift into a
*functional* check — does the recovered netlist compute the intended transform?

Works at **cell** granularity using the netlist's ``port_edges`` (output cell ->
input cell), so multi-port machines work: a cutter takes one input and emits two
distinct outputs, a swapper takes two inputs and emits two. Equal-shape merges
collapse; a single input cell fed by genuinely different shapes is an error
(unless *collect* mode is used for throughput sinks).
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
    if "Stacker" in type_:
        return 2, lambda s: [shapes.stack(s[0], s[1])]
    raise ValueError(f"no shape op for machine {type_!r}")


def _node_cells(node) -> tuple[list[Cell], list[Cell]]:
    """(input cells, output cells) of a node, anchor-first."""
    a = (node.x, node.y)
    if node.kind == "platform_in":
        return [], [a]
    if node.kind == "platform_out":
        return [a], []
    fp = _machine_footprint(node.type, node.rotation)
    ins = [(a[0] + dx, a[1] + dy) for (dx, dy, dl), (i, _o) in fp.items() if i and dl == 0]
    outs = [(a[0] + dx, a[1] + dy) for (dx, dy, dl), (_i, o) in fp.items() if o and dl == 0]
    return ins, outs


def interpret(
    nl: Netlist,
    inputs: dict[Cell, Shape],
    *,
    collect: bool = False,
) -> dict[Cell, Shape | frozenset[Shape]]:
    """Return the shape at each sink, given a shape at each source.

    When *collect* is True, sinks fed by multiple distinct shapes (throughput
    mergers) return a ``frozenset[Shape]`` instead of raising.
    """
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
    out: dict[Cell, Shape | frozenset[Shape]] = {}
    queue = deque(p for p, d in indeg.items() if d == 0)
    while queue:
        p = queue.popleft()
        node = nl.nodes[p]
        if node.kind == "platform_in":
            cell_shape[out_cells[p][0]] = inputs[p]
        else:
            feeds: list[Shape] = []
            collected = False
            for c in in_cells[p]:
                distinct = {cell_shape[s] for s in feeders[c]}
                if len(distinct) != 1:
                    if collect and node.kind == "platform_out" and distinct:
                        out[p] = frozenset(distinct)
                        collected = True
                        break
                    raise ValueError(f"input cell {c} of {p} has {len(distinct)} shapes")
                feeds.append(next(iter(distinct)))
            if collected:
                pass
            elif node.kind == "platform_out":
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


def classify_sources(nl: Netlist) -> dict[Cell, str]:
    """Partition sources into feed groups via the swapper topology.

    Returns ``"A"`` / ``"B"`` for sources that feed different swapper inputs,
    ``"pass"`` for sources that bypass all swappers.
    """
    cell_owner: dict[Cell, Cell] = {}
    node_ins: dict[Cell, list[Cell]] = {}
    for p, node in nl.nodes.items():
        ins, outs = _node_cells(node)
        node_ins[p] = ins
        for c in ins + outs:
            cell_owner[c] = p

    rev: dict[Cell, list[Cell]] = defaultdict(list)
    for s, d in nl.port_edges:
        rev[d].append(s)

    def _trace_sources(start_cell: Cell) -> set[Cell]:
        visited: set[Cell] = set()
        queue = deque([start_cell])
        sources: set[Cell] = set()
        while queue:
            c = queue.popleft()
            if c in visited:
                continue
            visited.add(c)
            for src_cell in rev.get(c, []):
                owner = cell_owner.get(src_cell)
                if owner is None:
                    continue
                node = nl.nodes[owner]
                if node.kind == "platform_in":
                    sources.add(owner)
                else:
                    for ic in node_ins.get(owner, []):
                        queue.append(ic)
        return sources

    adj: dict[Cell, set[Cell]] = defaultdict(set)
    swapper_sources: set[Cell] = set()
    for p, node in nl.nodes.items():
        if "Swapper" not in node.type:
            continue
        ins = node_ins[p]
        if len(ins) != 2:
            continue
        g0 = _trace_sources(ins[0])
        g1 = _trace_sources(ins[1])
        swapper_sources |= g0 | g1
        for a in g0:
            for b in g1:
                adj[a].add(b)
                adj[b].add(a)

    color: dict[Cell, int] = {}
    for start in swapper_sources:
        if start in color:
            continue
        color[start] = 0
        bfs: deque[Cell] = deque([start])
        while bfs:
            s = bfs.popleft()
            for nb in adj[s]:
                if nb not in color:
                    color[nb] = 1 - color[s]
                    bfs.append(nb)

    all_sources = {p for p, n in nl.nodes.items() if n.kind == "platform_in"}
    return {p: ("A" if color[p] == 0 else "B") if p in color else "pass" for p in all_sources}
