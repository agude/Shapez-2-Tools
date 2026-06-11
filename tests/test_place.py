"""WP-D: placement tests (CP-SAT)."""

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
    """WP-M: a 2-output CutterDefault feeding sinks on different faces.

    Building block for the Half Splitter gate: confirms the multi-cell
    placement (``_is_multi_cell`` / ``_second_cell_tables``), BFS sink
    tracing, and multi-face port assignment compose for a cutter without
    any further changes to ``place.py``.
    """

    def _abstract(self):
        return {
            "nodes": [
                {"id": "src0", "type": "BeltPortReceiverInternalVariant", "kind": "platform_in"},
                {"id": "cut0", "type": "CutterDefaultInternalVariant", "kind": "machine"},
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
        south_ports = set(_edge_ports(plat, 1))
        west_ports = set(_edge_ports(plat, 0))

        cutter_pos = next(
            pos for pos, n in result.nodes.items() if n.kind == "machine"
        )
        cutter_node = result.nodes[cutter_pos]
        fp = lift._machine_footprint(cutter_node.type, cutter_node.rotation)
        cells = {(cutter_pos[0] + dx, cutter_pos[1] + dy) for dx, dy, dl in fp if dl == 0}
        assert len(cells) == 2  # anchor + second cell

        sink_positions = {pos for pos, n in result.nodes.items() if n.kind == "platform_out"}
        assert len(sink_positions & south_ports) == 1
        assert len(sink_positions & west_ports) == 1

        # No two nodes/cutter cells share a position.
        all_positions = list(result.nodes.keys()) + [c for c in cells if c != cutter_pos]
        assert len(all_positions) == len(set(all_positions))

    def test_routes_and_splits_shape_to_correct_faces(self):
        """Place → route → lift → interpret: east/west halves land on the
        correctly-faced sinks, matching ``shapes.cut``."""
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
        south_ports = set(_edge_ports(plat, 1))
        west_ports = set(_edge_ports(plat, 0))

        src_pos = next(p for p, n in routed_nl.nodes.items() if n.kind == "platform_in")
        shape = shapes.Shape.parse("RuCuSuWu")
        out = interpret(routed_nl, {src_pos: shape})
        east, west = shapes.cut(shape)

        for pos, n in routed_nl.nodes.items():
            if n.kind != "platform_out":
                continue
            if pos in south_ports:
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
