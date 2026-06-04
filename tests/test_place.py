"""WP-D: placement tests (CP-SAT)."""

import pytest

from shapez2_tools import lift
from shapez2_tools.blueprint import Blueprint
from tests.conftest import REF


class TestPlaceFeasibility:
    """Basic placement feasibility: positions valid, no overlaps."""

    def test_place_single_rotator(self):
        """Place one source → one rotator → one sink on a 1×1 platform."""
        from shapez2_tools.place import place

        abstract = {
            "nodes": [
                {"id": "src0", "type": "BeltPortReceiverInternalVariant", "kind": "src"},
                {"id": "rot0", "type": "RotatorHalfInternalVariant", "kind": "machine"},
                {"id": "snk0", "type": "BeltPortSenderInternalVariant", "kind": "sink"},
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
                {"id": "src0", "type": "BeltPortReceiverInternalVariant", "kind": "src"},
                {"id": "rot0", "type": "RotatorHalfInternalVariant", "kind": "machine"},
                {"id": "rot1", "type": "RotatorHalfInternalVariant", "kind": "machine"},
                {"id": "snk0", "type": "BeltPortSenderInternalVariant", "kind": "sink"},
            ],
            "edges": [("src0", "rot0"), ("rot0", "rot1"), ("rot1", "snk0")],
        }
        result = place(abstract, "Foundation_1x1")

        positions = list(result.nodes.keys())
        assert len(positions) == len(set(positions))

        machine_positions = [
            pos for pos, n in result.nodes.items() if n.kind == "machine"
        ]
        assert len(machine_positions) == 2
        assert machine_positions[0] != machine_positions[1]


class TestPlaceThenRoute:
    """End-to-end: place → route → lift ≅ original netlist."""

    @pytest.mark.xfail(
        strict=False,
        reason="WP-D: placement + routing integration — first attempt",
    )
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
