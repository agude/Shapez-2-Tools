"""Synthesize blueprints from a functional spec (WP-E + WP-L).

Spec → abstract netlist → monotone sort → place (CP-SAT) → route → blueprint.

The ``Spec.op`` field accepts either a single operation name (the common case)
or a tuple of operations forming a **series chain**: each lane's source feeds
``throughput`` parallel paths, each path passing through every stage in order,
and the last stage fans in to the lane's sink.

``DiagonalSpec`` synthesizes the **diagonal trick** topology: paired
north/south sources feed swappers that extract shape diagonals.

``synthesize_quotient`` is the lane-uniform fast path: synthesize one floor on
one platform unit, stamp across floors (and units for multi-unit platforms).

Examples::

    Spec("rotate_180", "Foundation_1x1", throughput=2)
        # 4 lanes × 2 parallel rotate-180 machines (matches the oracle).

    Spec(("rotate_cw", "rotate_cw"), "Foundation_1x1", throughput=1)
        # 4 lanes × 1 path × 2 series machines = rotate-180 via two CW.

    DiagonalSpec(pairs=2, platform="Foundation_1x1")
        # 2 swapper pairs: 4 sources, 2 swappers, 4 sinks.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from shapez2_tools.blueprint import Blueprint
from shapez2_tools.generator import FLOORS, Entity, functional_entities, stamp
from shapez2_tools.place import SOURCE_FACE, _port_groups, place, side_regions
from shapez2_tools.route import entities_to_blueprint, reroute_with_junctions

_DATA = Path(__file__).resolve().parent.parent.parent / "data"

OP_TYPES: dict[str, str] = {
    "rotate_180": "RotatorHalfInternalVariant",
    "rotate_cw": "RotatorOneQuadInternalVariant",
    "rotate_ccw": "RotatorOneQuadCCWInternalVariant",
    "half_destroy": "CutterHalfInternalVariant",
}

SWAPPER_TYPE = "HalvesSwapperDefaultInternalVariant"
# Mirrored: second cell sits west of the anchor at R=1 (south source ->
# north sinks), putting the west-half output on the platform's west side
# where it can reach a west-face Region sink (§7.2 WP-M2 problem 3).
CUTTER_FAN_TYPE = "CutterDefaultInternalVariantMirrored"

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
        plat = platforms[self.platform]
        if "ports" in plat:
            return sum(1 for _, _, r in plat["ports"] if r == 3)
        return plat["ports_per_layer"]


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
        nodes.append({"id": src_id, "type": SRC_TYPE, "kind": "platform_in"})
        nodes.append({"id": sink_id, "type": SINK_TYPE, "kind": "platform_out"})

        for path in range(spec.throughput):
            prev_id = src_id
            for si, stage_op in enumerate(stages):
                mid = f"m{lane}_{path}_s{si}"
                nodes.append({"id": mid, "type": OP_TYPES[stage_op], "kind": "machine"})
                edges.append((prev_id, mid))
                prev_id = mid
            edges.append((prev_id, sink_id))

    return {"nodes": nodes, "edges": edges}


@dataclass(frozen=True)
class DiagonalSpec:
    """Diagonal trick: paired north/south sources → swappers → diagonal outputs.

    Each swapper pair has two sources (north-feed and south-feed) and two
    sinks (upper-left diagonal and upper-right diagonal).  ``pairs`` must
    not exceed half the platform's port count.
    """

    pairs: int
    platform: str

    @property
    def ports_needed(self) -> int:
        return self.pairs * 2

    def validate(self) -> None:
        with open(_DATA / "platforms.json") as f:
            platforms = json.load(f)
        plat = platforms[self.platform]
        if "ports" in plat:
            ports = sum(1 for _, _, r in plat["ports"] if r == 3)
        else:
            ports = plat["ports_per_layer"]
        if self.ports_needed > ports:
            raise ValueError(
                f"{self.pairs} pairs need {self.ports_needed} ports, "
                f"but {self.platform} has {ports}"
            )


def netlist_from_diagonal_spec(spec: DiagonalSpec) -> dict:
    """Build an abstract netlist for the diagonal trick.

    Topology per pair i:
      src_{i}_n, src_{i}_s → swap_{i} → sink_{i}_a, sink_{i}_b

    Sources are interleaved (n, s, n, s, …) so adjacent port slots
    feed the same swapper — the placer groups them by proximity.
    Sinks follow the same interleaving.
    """
    spec.validate()
    nodes: list[dict] = []
    edges: list[tuple[str, str]] = []

    for i in range(spec.pairs):
        src_n = f"src{i}_n"
        src_s = f"src{i}_s"
        swap = f"swap{i}"
        sink_a = f"sink{i}_a"
        sink_b = f"sink{i}_b"

        nodes.append({"id": src_n, "type": SRC_TYPE, "kind": "platform_in"})
        nodes.append({"id": src_s, "type": SRC_TYPE, "kind": "platform_in"})
        nodes.append({"id": swap, "type": SWAPPER_TYPE, "kind": "machine"})
        nodes.append({"id": sink_a, "type": SINK_TYPE, "kind": "platform_out"})
        nodes.append({"id": sink_b, "type": SINK_TYPE, "kind": "platform_out"})

        edges.append((src_n, swap))
        edges.append((src_s, swap))
        edges.append((swap, sink_a))
        edges.append((swap, sink_b))

    return {"nodes": nodes, "edges": edges}


def synthesize_diagonal(
    spec: DiagonalSpec, layer: int = 0, *, hop_range: int = 0,
) -> Blueprint:
    """Synthesize a diagonal-trick blueprint from a spec."""
    return _lower(
        netlist_from_diagonal_spec(spec), spec.platform, layer,
        hop_range=hop_range,
    )


@dataclass(frozen=True)
class CutterSpec:
    """Cutter fan: south-face sources, each split into west/east halves.

    Each lane: one south-face source (``SOURCE_FACE``) feeds
    ``cutters_per_lane`` parallel ``CutterDefault`` machines (1-in/2-out,
    each fed the same source — a 1->N split tree, real Half Splitter
    arithmetic uses 4: cutter throughput = 1/4 belt). Every cutter's
    west-half output is ``Region``-pinned to the platform's western faces
    and its east-half output to the eastern faces (§2a `side_regions`),
    merging into one sink per side per lane (an N->1 merge tree) — the Half
    Splitter's side semantics. ``lanes=16, cutters_per_lane=4`` on
    ``Foundation_2x4`` is the Half Splitter (north-star gate 2).
    """

    lanes: int
    platform: str
    cutters_per_lane: int = 1

    def validate(self) -> None:
        with open(_DATA / "platforms.json") as f:
            platforms = json.load(f)
        plat = platforms[self.platform]
        if "ports" in plat:
            ports = sum(1 for _, _, r in plat["ports"] if r == SOURCE_FACE)
        else:
            ports = plat["ports_per_layer"]
        if self.lanes > ports:
            raise ValueError(
                f"{self.lanes} lanes need {self.lanes} source ports on face "
                f"{SOURCE_FACE}, but {self.platform} has {ports}"
            )

        western, eastern = side_regions(plat)
        for name, groups in (("western", western), ("eastern", eastern)):
            slots = sum(len(_port_groups(plat, face)[gidx]) for face, gidx in groups)
            if self.lanes > slots:
                raise ValueError(
                    f"{self.lanes} lanes need {self.lanes} {name}-region "
                    f"output slots, but {self.platform} has {slots}"
                )


def netlist_from_cutter_spec(spec: CutterSpec) -> dict:
    """Build an abstract netlist for the cutter fan (§2a Half Splitter).

    Topology per lane i, with j ranging over ``cutters_per_lane``:
      src_i -> cut_i_j -> sink_i_w (Region: western faces)
                        -> sink_i_e (Region: eastern faces)

    Each cutter independently splits the lane's input and feeds both side
    sinks — a 1->N split (src fan-out) and two N->1 merges (sink fan-in per
    side), all expressed as plain edges sharing a node (§2a: split/merge are
    routing-layer junctions, not netlist nodes).
    """
    spec.validate()
    with open(_DATA / "platforms.json") as f:
        platforms = json.load(f)
    western, eastern = side_regions(platforms[spec.platform])

    nodes: list[dict] = []
    edges: list[tuple[str, str]] = []

    for i in range(spec.lanes):
        src = f"src{i}"
        sink_w = f"sink{i}_w"
        sink_e = f"sink{i}_e"

        nodes.append({"id": src, "type": SRC_TYPE, "kind": "platform_in"})
        nodes.append({
            "id": sink_w, "type": SINK_TYPE, "kind": "platform_out",
            "pin": "region", "target": western,
        })
        nodes.append({
            "id": sink_e, "type": SINK_TYPE, "kind": "platform_out",
            "pin": "region", "target": eastern,
        })

        for j in range(spec.cutters_per_lane):
            cut = f"cut{i}_{j}"
            nodes.append({"id": cut, "type": CUTTER_FAN_TYPE, "kind": "machine"})
            edges.append((src, cut))
            edges.append((cut, sink_w))
            edges.append((cut, sink_e))

    return {"nodes": nodes, "edges": edges}


def synthesize_cutter(
    spec: CutterSpec, layer: int = 0, *, hop_range: int = 0,
) -> Blueprint:
    """Synthesize a cutter-fan blueprint from a spec (§2a, north-star gate 2)."""
    return _lower(
        netlist_from_cutter_spec(spec), spec.platform, layer,
        hop_range=hop_range,
    )


def _sort_key(n: dict) -> tuple:
    """Sort key for monotone ordering: orig_x if available, else numeric ID suffix."""
    if "orig_x" in n:
        return (n["orig_x"], n["id"])
    m = re.search(r"\d+", n["id"])
    return (int(m.group()), n["id"]) if m else (0, n["id"])


def _monotone_sort(abstract: dict, platform: str) -> dict:
    """Sort source and sink nodes for monotone port assignment (WP-L).

    The placer assigns the i-th source in the node list to the i-th source
    port (sorted by x).  Sorting sources by ascending x (orig_x from a
    lifted netlist, or lane index from a synthesized one) ensures leftmost
    sources feed leftmost machines and sinks.
    """
    sources = sorted(
        [n for n in abstract["nodes"] if n["kind"] == "platform_in"],
        key=_sort_key,
    )
    sinks = sorted(
        [n for n in abstract["nodes"] if n["kind"] == "platform_out"],
        key=_sort_key,
    )
    machines = [n for n in abstract["nodes"] if n["kind"] == "machine"]
    return {"nodes": sources + machines + sinks, "edges": abstract["edges"]}


_MAX_RETRIES = 3


def _lower(
    abstract: dict, platform: str, layer: int = 0, *, hop_range: int = 0,
) -> Blueprint:
    """Lower an abstract netlist to a blueprint: sort → place → route → blueprint.

    On routing failure, feeds overused cells back to the placer as forbidden
    positions and retries (WP-M feedback loop, capped at 3 iterations).
    """
    from shapez2_tools.pathfinder import RoutingError

    abstract = _monotone_sort(abstract, platform)

    forbidden: set[tuple[int, int]] = set()
    for attempt in range(_MAX_RETRIES + 1):
        placed = place(abstract, platform, forbidden=forbidden)
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
        try:
            return reroute_with_junctions(
                stripped, placed, layer=layer, hop_range=hop_range,
                platform=platform,
            )
        except RoutingError as err:
            if attempt == _MAX_RETRIES:
                raise
            for x, y, _l in err.overused:
                forbidden.add((x, y))


def synthesize(spec: Spec, layer: int = 0, *, hop_range: int = 0) -> Blueprint:
    """Synthesize a blueprint from a spec."""
    return _lower(netlist_from_spec(spec), spec.platform, layer, hop_range=hop_range)


def synthesize_quotient(spec: Spec) -> Blueprint:
    """Synthesize via quotient: route one floor, stamp across three floors.

    For lane-uniform specs every floor is identical, so we synthesize a
    single floor and replicate it.  Belt counts scale exactly 3×.
    """
    one_floor = synthesize(spec, layer=0)
    tile = [e for e in functional_entities(one_floor) if e.layer == 0]
    all_entities = stamp(tile, (0,), FLOORS)
    return entities_to_blueprint(all_entities, platform=spec.platform)
