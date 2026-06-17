"""WP-D: placement tests (CP-SAT)."""

import pytest

from shapez2_tools import lift, shapes
from shapez2_tools.blueprint import Blueprint
from tests.conftest import REF


class TestPlaceFeasibility:
    """Basic placement feasibility: positions valid, no overlaps."""

    def test_place_single_rotator(self):
        """Place one source → one rotator → one sink on a 1×1 platform."""
        from shapez2_tools.place import place

        abstract = {
            "nodes": [
                {"id": "src0", "type": "BeltPortReceiverInternalVariant", "kind": "platform_in"},
                {"id": "rot0", "type": "RotatorHalfInternalVariant", "kind": "machine"},
                {"id": "snk0", "type": "BeltPortSenderInternalVariant", "kind": "platform_out"},
            ],
            "edges": [("src0", "rot0"), ("rot0", "snk0")],
        }
        result = place(abstract, "Foundation_1x1")

        # All nodes present
        assert len(result.nodes) == 3

        # No two nodes share a cell
        positions = list(result.nodes.keys())
        assert len(positions) == len(set(positions))

        # Machine is inside the platform interior (not on the port rows)
        for pos, node in result.nodes.items():
            if node.kind == "machine":
                assert 2 < pos[1] < 17, f"machine at {pos} outside interior"

    def test_place_two_rotators_no_overlap(self):
        """Two rotators on the same platform never overlap."""
        from shapez2_tools.place import place

        abstract = {
            "nodes": [
                {"id": "src0", "type": "BeltPortReceiverInternalVariant", "kind": "platform_in"},
                {"id": "rot0", "type": "RotatorHalfInternalVariant", "kind": "machine"},
                {"id": "rot1", "type": "RotatorHalfInternalVariant", "kind": "machine"},
                {"id": "snk0", "type": "BeltPortSenderInternalVariant", "kind": "platform_out"},
            ],
            "edges": [("src0", "rot0"), ("rot0", "rot1"), ("rot1", "snk0")],
        }
        result = place(abstract, "Foundation_1x1")

        positions = list(result.nodes.keys())
        assert len(positions) == len(set(positions))

        machine_positions = [pos for pos, n in result.nodes.items() if n.kind == "machine"]
        assert len(machine_positions) == 2
        assert machine_positions[0] != machine_positions[1]


class TestMultiFacePorts:
    """WP-M: platform_in/out nodes pinned to a non-default platform face."""

    def test_sink_on_west_face(self):
        """A sink with face=0 lands on a west-face port, rotated to exit west."""
        from shapez2_tools.place import _edge_ports, _load_platform, place

        abstract = {
            "nodes": [
                {"id": "src0", "type": "BeltPortReceiverInternalVariant", "kind": "platform_in"},
                {"id": "rot0", "type": "RotatorHalfInternalVariant", "kind": "machine"},
                {
                    "id": "snk0",
                    "type": "BeltPortSenderInternalVariant",
                    "kind": "platform_out",
                    "face": 0,
                },
            ],
            "edges": [("src0", "rot0"), ("rot0", "snk0")],
        }
        result = place(abstract, "Foundation_1x1")

        west_ports = set(_edge_ports(_load_platform("Foundation_1x1"), 0))
        sink_pos = next(
            pos for pos, n in result.nodes.items() if n.kind == "platform_out"
        )
        sink_node = result.nodes[sink_pos]

        assert sink_pos in west_ports
        assert sink_node.rotation == 2  # west-facing exit

        # No two nodes share a cell.
        positions = list(result.nodes.keys())
        assert len(positions) == len(set(positions))

    def test_west_face_sink_routes_and_lifts(self):
        """Place → route → lift round trip with a west-face sink."""
        from shapez2_tools.generator import Entity
        from shapez2_tools.place import place
        from shapez2_tools.route import entities_to_blueprint, reroute_with_junctions

        abstract = {
            "nodes": [
                {"id": "src0", "type": "BeltPortReceiverInternalVariant", "kind": "platform_in"},
                {"id": "rot0", "type": "RotatorHalfInternalVariant", "kind": "machine"},
                {
                    "id": "snk0",
                    "type": "BeltPortSenderInternalVariant",
                    "kind": "platform_out",
                    "face": 0,
                },
            ],
            "edges": [("src0", "rot0"), ("rot0", "snk0")],
        }
        placed = place(abstract, "Foundation_1x1")

        entities = [
            Entity(type=node.type, x=node.x, y=node.y, rotation=node.rotation, layer=0)
            for node in placed.nodes.values()
        ]
        stripped_bp = entities_to_blueprint(entities, platform="Foundation_1x1")
        routed_bp = reroute_with_junctions(
            stripped_bp, placed, layer=0, platform="Foundation_1x1"
        )
        routed_nl = lift.trace_layer(routed_bp, 0)

        assert lift.isomorphic(placed, routed_nl)
        assert lift.validate(routed_bp) == []


class TestCutterDefault:
    """WP-M: a 2-output Mirrored cutter feeding sinks on different faces.

    Building block for the Half Splitter gate: confirms the multi-cell
    placement (``_is_multi_cell`` / ``_second_cell_tables``), BFS sink
    tracing, and multi-face port assignment compose for a cutter without
    any further changes to ``place.py``. South source, north + west sinks —
    the synthesized cutter fan's convention (§7.2 WP-M2).
    """

    def _abstract(self):
        return {
            "nodes": [
                {"id": "src0", "type": "BeltPortReceiverInternalVariant", "kind": "platform_in"},
                {"id": "cut0", "type": "CutterDefaultInternalVariantMirrored", "kind": "machine"},
                {"id": "snk0", "type": "BeltPortSenderInternalVariant", "kind": "platform_out"},
                {
                    "id": "snk1",
                    "type": "BeltPortSenderInternalVariant",
                    "kind": "platform_out",
                    "face": 0,
                },
            ],
            "edges": [("src0", "cut0"), ("cut0", "snk0"), ("cut0", "snk1")],
        }

    def test_places_with_two_output_cells(self):
        """The cutter's anchor + second cell occupy distinct, non-port cells."""
        from shapez2_tools.place import _edge_ports, _load_platform, place

        result = place(self._abstract(), "Foundation_1x1")

        plat = _load_platform("Foundation_1x1")
        north_ports = set(_edge_ports(plat, 3))
        west_ports = set(_edge_ports(plat, 0))

        cutter_pos = next(
            pos for pos, n in result.nodes.items() if n.kind == "machine"
        )
        cutter_node = result.nodes[cutter_pos]
        fp = lift._machine_footprint(cutter_node.type, cutter_node.rotation)
        cells = {(cutter_pos[0] + dx, cutter_pos[1] + dy) for dx, dy, dl in fp if dl == 0}
        assert len(cells) == 2  # anchor + second cell

        sink_positions = {pos for pos, n in result.nodes.items() if n.kind == "platform_out"}
        assert len(sink_positions & north_ports) == 1
        assert len(sink_positions & west_ports) == 1

        # No two nodes/cutter cells share a position.
        all_positions = list(result.nodes.keys()) + [c for c in cells if c != cutter_pos]
        assert len(all_positions) == len(set(all_positions))

    def test_routes_and_splits_shape_to_correct_faces(self):
        """Place → route → lift → interpret: east/west halves land on the
        correctly-faced sinks, matching ``shapes.cut``.

        Per the absolute half->cell mapping (machines.md, §7.2 WP-M2 problem
        3): the anchor's front emits the east half, the second cell's front
        emits the west half. With ``Mirrored`` at R=1 (south source -> north
        sinks) the second cell sits west of the anchor, so the west half
        reaches the west-face sink and the east half the north-face sink.
        """
        from shapez2_tools.generator import Entity
        from shapez2_tools.interpret import interpret
        from shapez2_tools.place import _edge_ports, _load_platform, place
        from shapez2_tools.route import entities_to_blueprint, reroute_with_junctions

        placed = place(self._abstract(), "Foundation_1x1")

        entities = [
            Entity(type=node.type, x=node.x, y=node.y, rotation=node.rotation, layer=0)
            for node in placed.nodes.values()
        ]
        stripped_bp = entities_to_blueprint(entities, platform="Foundation_1x1")
        routed_bp = reroute_with_junctions(
            stripped_bp, placed, layer=0, platform="Foundation_1x1"
        )
        routed_nl = lift.trace_layer(routed_bp, 0)

        assert lift.isomorphic(placed, routed_nl)
        assert lift.validate(routed_bp) == []

        plat = _load_platform("Foundation_1x1")
        north_ports = set(_edge_ports(plat, 3))
        west_ports = set(_edge_ports(plat, 0))

        src_pos = next(p for p, n in routed_nl.nodes.items() if n.kind == "platform_in")
        shape = shapes.Shape.parse("RuCuSuWu")
        out = interpret(routed_nl, {src_pos: shape})
        east, west = shapes.cut(shape)

        for pos, n in routed_nl.nodes.items():
            if n.kind != "platform_out":
                continue
            if pos in north_ports:
                assert out[pos] == east
            elif pos in west_ports:
                assert out[pos] == west


class TestPlaceThenRoute:
    """End-to-end: place → route → lift ≅ original netlist."""

    def test_place_then_route_rotator_quarter(self):
        """Lift the rotator quarter, strip coords, place, route, re-lift."""
        from shapez2_tools.place import abstract_netlist, place
        from shapez2_tools.route import entities_to_blueprint, reroute_with_junctions

        bp = Blueprint.from_file(REF / "quarter_rotate_180.spz2bp")
        original = lift.trace_layer(bp, 0)

        abstract = abstract_netlist(original)
        placed = place(abstract, "Foundation_1x1")

        # Build a blueprint from the placed machines + ports, then route
        from shapez2_tools.generator import Entity

        entities = [
            Entity(
                type=node.type,
                x=node.x,
                y=node.y,
                rotation=node.rotation,
                layer=0,
            )
            for node in placed.nodes.values()
        ]
        stripped_bp = entities_to_blueprint(entities, platform="Foundation_1x1")
        routed_bp = reroute_with_junctions(stripped_bp, placed, layer=0)
        routed_nl = lift.trace_layer(routed_bp, 0)

        assert lift.isomorphic(original, routed_nl)
        assert lift.validate(routed_bp) == []


class TestPortGroups:
    """§5: ports are partitioned into groups of 4 — the addressable unit for
    ``Group``/``Region`` pins (one group per platform unit-edge)."""

    def test_groups_of_four_ordered_by_position(self):
        from shapez2_tools.place import _load_platform, _port_groups

        plat = _load_platform("Foundation_2x4")
        groups = _port_groups(plat, 1)  # south face: 16 ports = 4 groups

        assert len(groups) == 4
        assert all(len(g) == 4 for g in groups)
        assert groups[0][-1][0] < groups[1][0][0]
        assert groups[1][-1][0] < groups[2][0][0]
        assert groups[2][-1][0] < groups[3][0][0]

    def test_single_unit_platform_has_one_group_per_face(self):
        from shapez2_tools.place import _load_platform, _port_groups

        plat = _load_platform("Foundation_1x1")
        for face in range(4):
            groups = _port_groups(plat, face)
            assert len(groups) == 1
            assert len(groups[0]) == 4


class TestGroupInversions:
    """§2a: group-level permutation inversions = minimum route crossings."""

    def test_identity_has_no_inversions(self):
        from shapez2_tools.place import group_inversions

        assert group_inversions([(0, 0), (1, 1), (2, 2), (3, 3)]) == 0

    def test_full_reversal_of_four_groups(self):
        """The §2a worked example: a full reversal of 4 groups = 6 inversions."""
        from shapez2_tools.place import group_inversions

        assert group_inversions([(0, 3), (1, 2), (2, 1), (3, 0)]) == 6


class TestCrossingBudget:
    """§2a crossing budget: reject early when inversions exceed capacity."""

    def test_full_reversal_within_budget(self):
        """4 groups, full reversal (6 inversions) is within capacity C(4,2)=6."""
        from shapez2_tools.place import _check_crossing_budget

        nodes = []
        edges = []
        for g in range(4):
            src = f"src{g}"
            sink = f"sink{g}"
            mid = f"m{g}"
            nodes.append({
                "id": src, "type": "BeltPortReceiverInternalVariant",
                "kind": "platform_in", "pin": "group", "target": (1, g),
            })
            nodes.append({
                "id": sink, "type": "BeltPortSenderInternalVariant",
                "kind": "platform_out", "pin": "group", "target": (3, 3 - g),
            })
            nodes.append({
                "id": mid, "type": "RotatorHalfInternalVariant",
                "kind": "machine",
            })
            edges.append((src, mid))
            edges.append((mid, sink))
        _check_crossing_budget({"nodes": nodes, "edges": edges})

    def test_no_group_pins_skips_check(self):
        """Netlists without group pins pass the gate unconditionally."""
        from shapez2_tools.place import _check_crossing_budget

        abstract = {
            "nodes": [
                {"id": "src0", "type": "BeltPortReceiverInternalVariant",
                 "kind": "platform_in"},
                {"id": "snk0", "type": "BeltPortSenderInternalVariant",
                 "kind": "platform_out"},
            ],
            "edges": [("src0", "snk0")],
        }
        _check_crossing_budget(abstract)

    def test_identity_permutation_zero_inversions(self):
        """Identity permutation has 0 inversions, always within budget."""
        from shapez2_tools.place import _check_crossing_budget

        nodes = []
        edges = []
        for g in range(4):
            src, sink, mid = f"src{g}", f"sink{g}", f"m{g}"
            nodes.append({
                "id": src, "type": "BeltPortReceiverInternalVariant",
                "kind": "platform_in", "pin": "group", "target": (1, g),
            })
            nodes.append({
                "id": sink, "type": "BeltPortSenderInternalVariant",
                "kind": "platform_out", "pin": "group", "target": (3, g),
            })
            nodes.append({
                "id": mid, "type": "RotatorHalfInternalVariant",
                "kind": "machine",
            })
            edges.append((src, mid))
            edges.append((mid, sink))
        _check_crossing_budget({"nodes": nodes, "edges": edges})


class TestPinnedPorts:
    """§5: ``Group``/``Locked`` pins place ports independent of the Free
    monotone ordering."""

    def test_locked_pin_uses_exact_port(self):
        from shapez2_tools.place import _assign_pinned_ports, _edge_ports, _load_platform

        plat = _load_platform("Foundation_1x1")
        target = _edge_ports(plat, 0)[2]  # an arbitrary west-face port
        nodes = [
            {
                "id": "snk0",
                "type": "BeltPortSenderInternalVariant",
                "kind": "platform_out",
                "pin": "locked",
                "target": target,
            },
        ]

        port_pos, port_rot = _assign_pinned_ports(plat, nodes)

        assert port_pos["snk0"] == target
        assert port_rot["snk0"] == 2  # west-face (0) sink exits west: (0+2)%4

    def test_group_pinned_full_reversal(self):
        """§2a worked example: 4 source groups → 4 sink groups, reversed.

        Each group's 4 slots are assigned in node order; sources land in
        their target north-face group and sinks in their target south-face
        group, with the group order reversed end to end.
        """
        from shapez2_tools.place import (
            _assign_pinned_ports,
            _load_platform,
            _port_groups,
            group_inversions,
        )

        plat = _load_platform("Foundation_2x4")
        src_groups = _port_groups(plat, 3)
        sink_groups = _port_groups(plat, 1)

        nodes = []
        for g in range(4):
            for slot in range(4):
                nodes.append({
                    "id": f"src{g}_{slot}",
                    "type": "BeltPortReceiverInternalVariant",
                    "kind": "platform_in",
                    "pin": "group",
                    "target": (3, g),
                })
                nodes.append({
                    "id": f"sink{g}_{slot}",
                    "type": "BeltPortSenderInternalVariant",
                    "kind": "platform_out",
                    "pin": "group",
                    "target": (1, 3 - g),
                })
        # One pair per group (not per slot): the group-level permutation.
        pairs = [(g, 3 - g) for g in range(4)]

        port_pos, port_rot = _assign_pinned_ports(plat, nodes)

        for g in range(4):
            for slot in range(4):
                assert port_pos[f"src{g}_{slot}"] in src_groups[g]
                assert port_pos[f"sink{g}_{slot}"] in sink_groups[3 - g]
                assert port_rot[f"src{g}_{slot}"] == 3
                assert port_rot[f"sink{g}_{slot}"] == 3

        # Every slot in every group is filled exactly once.
        assert len(set(port_pos.values())) == len(port_pos)

        # Full reversal of 4 groups: 6 inversions (§2a).
        assert group_inversions(pairs) == 6

    def test_region_pin_spans_multiple_groups(self):
        """A ``region`` pin fills the flattened slot pool of every listed
        group, in node order, before any group repeats."""
        from shapez2_tools.place import _assign_pinned_ports, _load_platform, _port_groups

        plat = _load_platform("Foundation_2x4")
        region = [(0, 0), (0, 1)]  # both west-face groups: 8 slots total
        nodes = [
            {
                "id": f"sink{i}",
                "type": "BeltPortSenderInternalVariant",
                "kind": "platform_out",
                "pin": "region",
                "target": region,
            }
            for i in range(8)
        ]

        port_pos, port_rot = _assign_pinned_ports(plat, nodes)

        expected_slots = [
            pos for face, gidx in region for pos in _port_groups(plat, face)[gidx]
        ]
        assert [port_pos[f"sink{i}"] for i in range(8)] == expected_slots
        assert len(set(port_pos.values())) == 8
        # West face (0): a sink continues outward, rotation (0+2)%4 = 2.
        assert all(r == 2 for r in port_rot.values())

    def test_half_splitter_regions_on_2x4(self):
        """§2a: the western/eastern regions for the Half Splitter — west
        (resp. east) face plus the two west-most (resp. east-most) north-face
        groups, 16 slots each, disjoint."""
        from shapez2_tools.place import (
            _assign_pinned_ports,
            _load_platform,
            _port_groups,
            side_regions,
        )

        plat = _load_platform("Foundation_2x4")
        western = [(0, 0), (0, 1), (3, 0), (3, 1)]
        eastern = [(2, 0), (2, 1), (3, 2), (3, 3)]
        assert side_regions(plat) == (western, eastern)

        nodes = []
        for i in range(16):
            nodes.append({
                "id": f"west{i}",
                "type": "BeltPortSenderInternalVariant",
                "kind": "platform_out",
                "pin": "region",
                "target": western,
            })
            nodes.append({
                "id": f"east{i}",
                "type": "BeltPortSenderInternalVariant",
                "kind": "platform_out",
                "pin": "region",
                "target": eastern,
            })

        port_pos, port_rot = _assign_pinned_ports(plat, nodes)

        west_slots = {
            pos for face, gidx in western for pos in _port_groups(plat, face)[gidx]
        }
        east_slots = {
            pos for face, gidx in eastern for pos in _port_groups(plat, face)[gidx]
        }

        assert {port_pos[f"west{i}"] for i in range(16)} == west_slots
        assert {port_pos[f"east{i}"] for i in range(16)} == east_slots
        assert west_slots.isdisjoint(east_slots)

    def test_place_with_group_pinned_reversal(self):
        """End-to-end: ``place()`` honors a group-reversed, pass-through netlist.

        No machines, so this exercises only the pinned-port assignment path
        (the ``if not machines`` early return).
        """
        from shapez2_tools.place import _load_platform, _port_groups, place

        plat = _load_platform("Foundation_2x4")
        src_groups = _port_groups(plat, 3)
        sink_groups = _port_groups(plat, 1)
        all_src_ports = {p for g in src_groups for p in g}
        all_sink_ports = {p for g in sink_groups for p in g}

        nodes = []
        edges = []
        for g in range(4):
            for slot in range(4):
                src_id = f"src{g}_{slot}"
                sink_id = f"sink{g}_{slot}"
                nodes.append({
                    "id": src_id,
                    "type": "BeltPortReceiverInternalVariant",
                    "kind": "platform_in",
                    "pin": "group",
                    "target": (3, g),
                })
                nodes.append({
                    "id": sink_id,
                    "type": "BeltPortSenderInternalVariant",
                    "kind": "platform_out",
                    "pin": "group",
                    "target": (1, 3 - g),
                })
                edges.append((src_id, sink_id))

        result = place({"nodes": nodes, "edges": edges}, "Foundation_2x4")

        positions = list(result.nodes.keys())
        assert len(positions) == len(set(positions))

        src_positions = {p for p, n in result.nodes.items() if n.kind == "platform_in"}
        sink_positions = {p for p, n in result.nodes.items() if n.kind == "platform_out"}
        assert src_positions == all_src_ports
        assert sink_positions == all_sink_ports


# ---------------------------------------------------------------------------
# WP-O: columnar placement for fan topologies
# ---------------------------------------------------------------------------


class TestColumnPlacement:
    """WP-O: columnar placement for fan topologies."""

    def test_fan_topology_detected(self):
        from shapez2_tools.place import _compute_stages, _detect_fan_topology
        from shapez2_tools.synth import CutterSpec, netlist_from_cutter_spec

        spec = CutterSpec(lanes=16, platform="Foundation_2x4", cutters_per_lane=4)
        abstract = netlist_from_cutter_spec(spec)
        stages = _compute_stages(abstract)
        fan_lanes = _detect_fan_topology(abstract, stages)
        assert fan_lanes is not None
        assert len(fan_lanes) == 16
        assert all(len(ms) == 4 for ms in fan_lanes.values())

    def test_serial_topology_not_detected(self):
        from shapez2_tools.place import _compute_stages, _detect_fan_topology
        from shapez2_tools.synth import Spec, netlist_from_spec

        spec = Spec(op=("rotate_cw", "rotate_cw"), platform="Foundation_1x1")
        abstract = netlist_from_spec(spec)
        stages = _compute_stages(abstract)
        assert _detect_fan_topology(abstract, stages) is None

    def test_small_fan_not_detected(self):
        """Fan topologies with ≤ 32 machines stay on the band model."""
        from shapez2_tools.place import _compute_stages, _detect_fan_topology
        from shapez2_tools.synth import CutterSpec, netlist_from_cutter_spec

        spec = CutterSpec(lanes=4, platform="Foundation_2x4", cutters_per_lane=4)
        abstract = netlist_from_cutter_spec(spec)
        stages = _compute_stages(abstract)
        assert _detect_fan_topology(abstract, stages) is None

    @pytest.mark.slow
    def test_columns_ordered_by_source_x(self):
        """Placed machines' mean x is monotone with source port x."""
        from collections import defaultdict

        from shapez2_tools.place import place
        from shapez2_tools.synth import (
            CutterSpec,
            _monotone_sort,
            netlist_from_cutter_spec,
        )

        spec = CutterSpec(lanes=16, platform="Foundation_2x4", cutters_per_lane=4)
        abstract = _monotone_sort(netlist_from_cutter_spec(spec), spec.platform)
        nl = place(abstract, spec.platform)

        node_by_id = {n["id"]: n for n in abstract["nodes"]}
        edge_out: dict[str, list[str]] = defaultdict(list)
        for sid, did in abstract["edges"]:
            edge_out[sid].append(did)

        src_xs: list[tuple[int, float]] = []
        for n in abstract["nodes"]:
            if n["kind"] != "platform_in":
                continue
            src_pos = next(
                p for p, nd in nl.nodes.items()
                if nd.kind == "platform_in"
                and nd.x == p[0] and nd.y == p[1]
            )
            machine_ids = [
                d for d in edge_out.get(n["id"], [])
                if node_by_id[d]["kind"] == "machine"
            ]
            if not machine_ids:
                continue
            machine_xs = []
            for mid in machine_ids:
                for p, nd in nl.nodes.items():
                    if nd.kind == "machine" and nd.type == node_by_id[mid]["type"]:
                        machine_xs.append(p[0])
                        break
            if machine_xs:
                src_xs.append((src_pos[0], sum(machine_xs) / len(machine_xs)))

        src_xs.sort(key=lambda t: t[0])
        mean_xs = [mx for _, mx in src_xs]
        assert mean_xs == sorted(mean_xs), f"columns not monotone: {mean_xs}"

    @pytest.mark.slow
    def test_sixteen_lane_placement_columnar(self):
        """16-lane placement produces 16 distinct x-columns of width ≤ 2."""
        from collections import defaultdict

        from shapez2_tools.place import place
        from shapez2_tools.synth import (
            CutterSpec,
            _monotone_sort,
            netlist_from_cutter_spec,
        )

        spec = CutterSpec(lanes=16, platform="Foundation_2x4", cutters_per_lane=4)
        abstract = _monotone_sort(netlist_from_cutter_spec(spec), spec.platform)
        nl = place(abstract, spec.platform)

        by_col: dict[int, list[int]] = defaultdict(list)
        for pos, node in nl.nodes.items():
            if node.kind == "machine":
                by_col[pos[0]].append(pos[1])

        assert len(by_col) == 16
        for x, ys in by_col.items():
            assert len(ys) == 4, f"column x={x} has {len(ys)} machines, expected 4"
