"""WP-C: re-routing — route a netlist at fixed placement, round-trip via lift.

This test file supersedes tests/test_router.py (the deprecated A* prototype).
The old tests cover the prototype's data structures and A*; these cover the
new router that round-trips through lift.
"""

from pathlib import Path

import pytest

from shapez2_tools import lift
from shapez2_tools.blueprint import Blueprint

REF = Path(__file__).resolve().parent.parent / "data" / "reference"

CLOSED_FIXTURES = [
    "quarter_rotate_180.spz2bp",
    "quarter_rotate_cw.spz2bp",
    "quarter_rotate_ccw.spz2bp",
    "full_belt_rotate_180.spz2bp",
    "full_belt_rotate_cw.spz2bp",
    "full_belt_rotate_ccw.spz2bp",
    "quarter_destroy_west_half.spz2bp",
    "cutter_12_to_24.spz2bp",
    "swap_diagonal.spz2bp",
]


@pytest.mark.xfail(strict=True, reason="WP-C: route module not implemented yet")
class TestRouteBasics:
    """Unit tests for individual routing operations."""

    def test_route_straight(self):
        """One source → one destination in a line emits Forward belts."""
        from shapez2_tools import route

        # Route from (0, 0) → (3, 0), all in a horizontal line
        entities = route.route_edge((0, 0), (3, 0), layer=0)
        # Should be 2 belt entities: at (1, 0) and (2, 0), both Forward, R=0
        assert len(entities) == 2
        for e in entities:
            assert "Forward" in e.type
            assert e.rotation == 0  # Pointing East

    def test_route_one_turn(self):
        """Source and destination offset on both axes → Forward + turn."""
        from shapez2_tools import route

        # Route from (0, 0) → (2, 2)
        entities = route.route_edge((0, 0), (2, 2), layer=0)
        assert len(entities) > 0
        # Should include at least one turn (Left or LeftMirrored)
        types = [e.type for e in entities]
        has_turn = any("Left" in t for t in types)
        assert has_turn

    def test_route_single_edge_lifts_back(self):
        """A routed edge lifts back to the same edge."""
        from shapez2_tools import route
        from shapez2_tools.generator import Entity

        # Build a minimal blueprint with a source port, routed belts, and sink
        # Route (0, 0) → (3, 0) on layer 0
        entities = route.route_edge((0, 0), (3, 0), layer=0)
        # Add source at (0, 0) and sink at (3, 0)
        src = Entity(type="BeltPortReceiverInternalVariant", x=0, y=0, rotation=0, layer=0)
        sink = Entity(type="BeltPortSenderInternalVariant", x=3, y=0, rotation=0, layer=0)
        all_ents = [src] + entities + [sink]

        # Build a minimal blueprint and lift
        # (This requires the route module to produce Entity objects compatible
        # with lift.trace_layer — the implementation detail)
        bp = route.entities_to_blueprint(all_ents, platform="Foundation_1x1")
        nl = lift.trace_layer(bp, 0)

        # Should have 1 edge: src → sink
        assert len(nl.edges) == 1
        assert nl.edges[0] == ((0, 0), (3, 0))


@pytest.mark.xfail(strict=True, reason="WP-C: route module not implemented yet")
class TestReroute:
    """Round-trip tests: strip belts, re-route, lift must be isomorphic."""

    def test_reroute_rotator_quarter(self):
        """Strip belts from quarter, re-route, isomorphic to original."""
        from shapez2_tools import route

        bp = Blueprint.from_file(REF / "quarter_rotate_180.spz2bp")
        original = lift.trace_layer(bp, 0)

        # Strip belts, keep machines and ports at their positions
        stripped = route.strip_belts(bp, layer=0)

        # Re-route the netlist at the same placement
        rerouted_bp = route.reroute(stripped, original)

        # Lift the result and compare
        rerouted = lift.trace_layer(rerouted_bp, 0)
        assert lift.isomorphic(original, rerouted)

    @pytest.mark.parametrize("name", CLOSED_FIXTURES)
    def test_reroute_roundtrip(self, name):
        """Strip and re-route any closed fixture → isomorphic lift."""
        from shapez2_tools import route

        bp = Blueprint.from_file(REF / name)
        original = lift.trace_layer(bp, 0)
        stripped = route.strip_belts(bp, layer=0)
        rerouted_bp = route.reroute(stripped, original)
        rerouted = lift.trace_layer(rerouted_bp, 0)
        assert lift.isomorphic(original, rerouted)
