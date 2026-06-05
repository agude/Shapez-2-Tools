"""Synthesize blueprints from a functional spec (WP-E).

Spec → abstract netlist → place (CP-SAT) → route (A*) → blueprint.
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
    """A single-op platform spec.

    op: operation name (key into OP_TYPES).
    platform: platform name from platforms.json.
    throughput: machines per lane, placed in parallel (fan-out then fan-in).
    """

    op: str
    platform: str
    throughput: int = 2

    @property
    def machine_type(self) -> str:
        return OP_TYPES[self.op]

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

    Topology for a single-op spec with throughput T and L lanes:
      L sources, each fan-out to T machines, those T machines fan-in to 1 sink.
      Total: L sources + L*T machines + L sinks.
    """
    nodes: list[dict] = []
    edges: list[tuple[str, str]] = []

    for lane in range(spec.lanes):
        src_id = f"src{lane}"
        sink_id = f"sink{lane}"
        nodes.append({"id": src_id, "type": SRC_TYPE, "kind": "src"})
        nodes.append({"id": sink_id, "type": SINK_TYPE, "kind": "sink"})

        for m in range(spec.throughput):
            mid = f"machine{lane}_{m}"
            nodes.append({"id": mid, "type": spec.machine_type, "kind": "machine"})
            edges.append((src_id, mid))
            edges.append((mid, sink_id))

    return {"nodes": nodes, "edges": edges}


def synthesize(spec: Spec, layer: int = 0) -> Blueprint:
    """Synthesize a blueprint from a spec.

    Runs the full pipeline: spec → abstract netlist → place → route → blueprint.
    """
    abstract = netlist_from_spec(spec)
    placed = place(abstract, spec.platform)

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
    stripped = entities_to_blueprint(entities, platform=spec.platform)
    return reroute_with_junctions(stripped, placed, layer=layer)
