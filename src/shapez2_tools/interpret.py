"""Interpret a lifted netlist: push shapes through it and read the outputs.

Forward-propagates a shape from each source port, through each machine's shape
operation, to the sink ports, in topological order. This turns a lift into a
*functional* check — does the recovered netlist compute the intended transform?

Only 1-in/1-out machines are handled (rotators, half-destroyer). Multi-port
machines (cutters, swappers, stackers) need the machine-port lift work first.
"""

from __future__ import annotations

from collections import defaultdict, deque

from shapez2_tools import shapes
from shapez2_tools.lift import Netlist
from shapez2_tools.shapes import Shape

# Machine building type -> the shape operation it performs.
MACHINE_OPS = {
    "RotatorHalfInternalVariant": shapes.rotate_180,
    "RotatorOneQuadInternalVariant": shapes.rotate_cw,
    "RotatorOneQuadCCWInternalVariant": shapes.rotate_ccw,
    "CutterHalfInternalVariant": shapes.half_destroy,
}


def interpret(nl: Netlist, inputs: dict[tuple[int, int], Shape]) -> dict[tuple[int, int], Shape]:
    """Return the shape at each sink, given a shape at each source.

    Raises on a machine with no known op, or a machine fed by more than one
    distinct shape (a real multi-input combine, which this minimal pass cannot
    do yet).
    """
    incoming: dict = defaultdict(list)
    outgoing: dict = defaultdict(list)
    indeg = dict.fromkeys(nl.nodes, 0)
    for a, b in nl.edges:
        incoming[b].append(a)
        outgoing[a].append(b)
        indeg[b] += 1

    out: dict[tuple[int, int], Shape] = {}
    queue = deque(p for p in nl.nodes if indeg[p] == 0)
    while queue:
        p = queue.popleft()
        node = nl.nodes[p]
        if node.kind == "src":
            out[p] = inputs[p]
        else:
            feeds = {out[a] for a in incoming[p]}  # equal-shape merges collapse
            if node.kind == "machine":
                if node.type not in MACHINE_OPS:
                    raise ValueError(f"no shape op for machine {node.type!r}")
                if len(feeds) != 1:
                    raise ValueError(f"machine at {p} has {len(feeds)} distinct inputs")
                out[p] = MACHINE_OPS[node.type](next(iter(feeds)))
            else:  # sink: pass through
                out[p] = next(iter(feeds))
        for nb in outgoing[p]:
            indeg[nb] -= 1
            if indeg[nb] == 0:
                queue.append(nb)

    return {p: out[p] for p, n in nl.nodes.items() if n.kind == "sink"}
