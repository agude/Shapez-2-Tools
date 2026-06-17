"""Route-only mode: route missing connections without disturbing existing placement.

Unlike ``place``, which re-places *and* re-routes a netlist from scratch, this
module takes a half-completed, hand-placed blueprint and routes only the
unconnected ends — existing machines and belts are immovable obstacles.  See
``docs/route-only-spec.md`` for the full design.
"""

from __future__ import annotations

from dataclasses import dataclass

from shapez2_tools import lift
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
