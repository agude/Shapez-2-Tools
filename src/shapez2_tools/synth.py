"""Synthesize blueprints from a functional spec (WP-E).

Spec → abstract netlist → place (CP-SAT) → route (A*) → blueprint.

The ``Spec.op`` field accepts either a single operation name (the common case)
or a tuple of operations forming a **series chain**: each lane's source feeds
``throughput`` parallel paths, each path passing through every stage in order,
and the last stage fans in to the lane's sink.

Examples::

    Spec("rotate_180", "Foundation_1x1", throughput=2)
        # 4 lanes × 2 parallel rotate-180 machines (matches the oracle).

    Spec(("rotate_cw", "rotate_cw"), "Foundation_1x1", throughput=1)
        # 4 lanes × 1 path × 2 series machines = rotate-180 via two CW.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from shapez2_tools.blueprint import Blueprint
from shapez2_tools.generator import Entity
from shapez2_tools.place import place
from shapez2_tools.route import entities_to_blueprint, reroute_with_junctions

_DATA = Path(__file__).resolve().parent.parent.parent / "data"

OP_TYPES: dict[str, str] = {
    "rotate_180": "RotatorHalfInternalVariant",
    "rotate_cw": "RotatorOneQuadInternalVariant",
    "rotate_ccw": "RotatorOneQuadCCWInternalVariant",
    "half_destroy": "CutterHalfInternalVariant",
}

SRC_TYPE = "BeltPortReceiverInternalVariant"
SINK_TYPE = "BeltPortSenderInternalVariant"


@dataclass(frozen=True)
class Spec:
    """A platform spec: one or more operations per lane, with parallel throughput.

    op: operation name or tuple of names forming a series chain.
    platform: platform name from platforms.json.
    throughput: parallel paths per lane (fan-out at source, fan-in at sink).
    """

    op: str | tuple[str, ...]
    platform: str
    throughput: int = 2

    @property
    def stages(self) -> tuple[str, ...]:
        return (self.op,) if isinstance(self.op, str) else self.op

    @property
    def lanes(self) -> int:
        with open(_DATA / "platforms.json") as f:
            platforms = json.load(f)
        return platforms[self.platform]["ports_per_layer"]


def netlist_from_spec(spec: Spec) -> dict:
    """Build an abstract netlist from a spec.

    Returns the same dict format as ``place.abstract_netlist``:
      - "nodes": list of {"id": str, "type": str, "kind": str}
      - "edges": list of (src_id, dst_id)

    Topology: L lanes × T parallel paths × S serial stages.
    Each path: src → stage[0] → stage[1] → … → stage[-1] → sink.
    Fan-out from src to T path-heads; fan-in from T path-tails to sink.
    """
    stages = spec.stages
    nodes: list[dict] = []
    edges: list[tuple[str, str]] = []

    for lane in range(spec.lanes):
        src_id = f"src{lane}"
        sink_id = f"sink{lane}"
        nodes.append({"id": src_id, "type": SRC_TYPE, "kind": "src"})
        nodes.append({"id": sink_id, "type": SINK_TYPE, "kind": "sink"})

        for path in range(spec.throughput):
            prev_id = src_id
            for si, stage_op in enumerate(stages):
                mid = f"m{lane}_{path}_s{si}"
                nodes.append({"id": mid, "type": OP_TYPES[stage_op], "kind": "machine"})
                edges.append((prev_id, mid))
                prev_id = mid
            edges.append((prev_id, sink_id))

    return {"nodes": nodes, "edges": edges}


def _lower(abstract: dict, platform: str, layer: int = 0) -> Blueprint:
    """Lower an abstract netlist to a blueprint: place → route → blueprint."""
    placed = place(abstract, platform)
    entities = [
        Entity(
            type=node.type,
            x=node.x,
            y=node.y,
            rotation=node.rotation,
            layer=layer,
        )
        for node in placed.nodes.values()
    ]
    stripped = entities_to_blueprint(entities, platform=platform)
    return reroute_with_junctions(stripped, placed, layer=layer)


def synthesize(spec: Spec, layer: int = 0) -> Blueprint:
    """Synthesize a blueprint from a spec."""
    return _lower(netlist_from_spec(spec), spec.platform, layer)
