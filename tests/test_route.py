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


class TestRouteBasics:
    """Unit tests for individual routing operations."""

    def test_route_fanout(self):
        """One source → two destinations emits a splitter junction."""
        from shapez2_tools import route
        from shapez2_tools.generator import Entity

        # Source at (0, 0), two sinks at (3, 1) and (3, -1)
        # All facing East (R=0), so source outputs E, sinks accept from W
        src = Entity(type="BeltPortReceiverInternalVariant", x=0, y=0, rotation=0, layer=0)
        sink1 = Entity(type="BeltPortSenderInternalVariant", x=3, y=1, rotation=0, layer=0)
        sink2 = Entity(type="BeltPortSenderInternalVariant", x=3, y=-1, rotation=0, layer=0)

        # Route the fan-out: one source to two sinks
        # src_out_dir = E (1,0): source outputs to the east
        # dst_in_dirs = W (-1,0): sinks accept from the west
        entities = route.route_fanout(
            src_pos=(0, 0),
            dst_positions=[(3, 1), (3, -1)],
            src_out_dir=(1, 0),  # E
            dst_in_dirs=[(-1, 0), (-1, 0)],  # both sinks accept from W
            layer=0,
        )

        # Should include at least one splitter
        types = [e.type for e in entities]
        has_splitter = any("Splitter" in t for t in types)
        assert has_splitter, f"Expected a splitter, got types: {types}"

        # Build blueprint and lift to verify connectivity
        all_ents = [src, sink1, sink2] + entities
        bp = route.entities_to_blueprint(all_ents, platform="Foundation_1x1")
        nl = lift.trace_layer(bp, 0)

        # Should have 2 edges: src → sink1 and src → sink2
        assert len(nl.edges) == 2
        edge_set = {(tuple(e[0]), tuple(e[1])) for e in nl.edges}
        assert ((0, 0), (3, 1)) in edge_set
        assert ((0, 0), (3, -1)) in edge_set

    def test_route_fanin(self):
        """Two sources → one destination emits a merger junction."""
        from shapez2_tools import route
        from shapez2_tools.generator import Entity

        # Two sources at (0, 1) and (0, -1), one sink at (3, 0)
        # All facing East (R=0): sources output E, sink accepts from W
        src1 = Entity(type="BeltPortReceiverInternalVariant", x=0, y=1, rotation=0, layer=0)
        src2 = Entity(type="BeltPortReceiverInternalVariant", x=0, y=-1, rotation=0, layer=0)
        sink = Entity(type="BeltPortSenderInternalVariant", x=3, y=0, rotation=0, layer=0)

        # Route the fan-in: two sources to one sink
        # src_out_dirs = E (1,0): sources output to the east
        # dst_in_dir = W (-1,0): sink accepts from the west
        entities = route.route_fanin(
            src_positions=[(0, 1), (0, -1)],
            dst_pos=(3, 0),
            src_out_dirs=[(1, 0), (1, 0)],  # both sources output E
            dst_in_dir=(-1, 0),  # sink accepts from W
            layer=0,
        )

        # Should include at least one merger
        types = [e.type for e in entities]
        has_merger = any("Merger" in t for t in types)
        assert has_merger, f"Expected a merger, got types: {types}"

        # Build blueprint and lift to verify connectivity
        all_ents = [src1, src2, sink] + entities
        bp = route.entities_to_blueprint(all_ents, platform="Foundation_1x1")
        nl = lift.trace_layer(bp, 0)

        # Should have 2 edges: src1 → sink and src2 → sink
        assert len(nl.edges) == 2
        edge_set = {(tuple(e[0]), tuple(e[1])) for e in nl.edges}
        assert ((0, 1), (3, 0)) in edge_set
        assert ((0, -1), (3, 0)) in edge_set

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

    def test_route_avoids_obstacle(self):
        """A* routing detours around an obstacle."""
        from shapez2_tools import route
        from shapez2_tools.generator import Entity

        # Source at (0, 0), sink at (4, 0), obstacle at (2, 0)
        # Direct path would be (0,0) → (1,0) → (2,0) → (3,0) → (4,0)
        # With obstacle at (2, 0), must detour via (2, 1) or (2, -1)
        src = Entity(type="BeltPortReceiverInternalVariant", x=0, y=0, rotation=0, layer=0)
        sink = Entity(type="BeltPortSenderInternalVariant", x=4, y=0, rotation=0, layer=0)

        obstacles = {(2, 0)}
        entities = route.route_astar(
            src_pos=(0, 0),
            dst_pos=(4, 0),
            src_out_dir=(1, 0),  # E
            dst_in_dir=(-1, 0),  # W
            obstacles=obstacles,
            layer=0,
        )

        # Path should not include the obstacle
        routed_cells = {(e.x, e.y) for e in entities}
        assert (2, 0) not in routed_cells

        # Build blueprint and verify connectivity
        all_ents = [src, sink] + entities
        bp = route.entities_to_blueprint(all_ents, platform="Foundation_1x1")
        nl = lift.trace_layer(bp, 0)

        assert len(nl.edges) == 1
        assert nl.edges[0] == ((0, 0), (4, 0))


class TestAStarReroute:
    """A*-based sequential routing tests."""

    def test_reroute_simple_two_edges(self):
        """Route two non-crossing edges sequentially."""
        from shapez2_tools import route
        from shapez2_tools.generator import Entity

        # Two parallel edges that shouldn't cross:
        # src1 at (0, 1) → sink1 at (4, 1)
        # src2 at (0, 0) → sink2 at (4, 0)
        src1 = Entity(type="BeltPortReceiverInternalVariant", x=0, y=1, rotation=0, layer=0)
        sink1 = Entity(type="BeltPortSenderInternalVariant", x=4, y=1, rotation=0, layer=0)
        src2 = Entity(type="BeltPortReceiverInternalVariant", x=0, y=0, rotation=0, layer=0)
        sink2 = Entity(type="BeltPortSenderInternalVariant", x=4, y=0, rotation=0, layer=0)

        # Route both edges using sequential A*
        edges = [
            ((0, 1), (4, 1), (1, 0), (-1, 0)),  # src1 → sink1
            ((0, 0), (4, 0), (1, 0), (-1, 0)),  # src2 → sink2
        ]
        entities = route.route_edges_sequential(edges, layer=0)

        # Build blueprint and verify both edges exist
        all_ents = [src1, sink1, src2, sink2] + entities
        bp = route.entities_to_blueprint(all_ents, platform="Foundation_1x1")
        nl = lift.trace_layer(bp, 0)

        assert len(nl.edges) == 2
        edge_set = {tuple(e) for e in nl.edges}
        assert ((0, 1), (4, 1)) in edge_set
        assert ((0, 0), (4, 0)) in edge_set

    def test_reroute_crossing_edges(self):
        """Route two crossing edges — second must detour around first."""
        from shapez2_tools import route
        from shapez2_tools.generator import Entity

        # Two edges that would cross if routed naively:
        # src1 at (0, 0) → sink1 at (4, 0) (horizontal)
        # src2 at (2, -2) → sink2 at (2, 2) (vertical, crosses at (2, 0))
        # R=0: source outputs E(1,0), sink accepts from W(-1,0)
        # R=1: source outputs N(0,1), sink accepts from S(0,-1)
        src1 = Entity(type="BeltPortReceiverInternalVariant", x=0, y=0, rotation=0, layer=0)
        sink1 = Entity(type="BeltPortSenderInternalVariant", x=4, y=0, rotation=0, layer=0)
        src2 = Entity(
            type="BeltPortReceiverInternalVariant", x=2, y=-2, rotation=1, layer=0
        )  # R=1: outputs N
        sink2 = Entity(
            type="BeltPortSenderInternalVariant", x=2, y=2, rotation=1, layer=0
        )  # R=1: accepts from S

        # Route horizontal first, then vertical must detour
        # src_out_dir=N(0,1), dst_in_dir=S(0,-1) means belt approaches sink from below (y=1)
        edges = [
            ((0, 0), (4, 0), (1, 0), (-1, 0)),  # horizontal
            ((2, -2), (2, 2), (0, 1), (0, -1)),  # vertical (out=N, in=S: approach from south)
        ]
        entities = route.route_edges_sequential(edges, layer=0)

        # Build blueprint and verify both edges exist
        all_ents = [src1, sink1, src2, sink2] + entities
        bp = route.entities_to_blueprint(all_ents, platform="Foundation_1x1")
        nl = lift.trace_layer(bp, 0)

        assert len(nl.edges) == 2
        edge_set = {tuple(e) for e in nl.edges}
        assert ((0, 0), (4, 0)) in edge_set
        assert ((2, -2), (2, 2)) in edge_set

    def test_fanin_same_direction_merger_near_sources(self):
        """Two adjacent sources outputting the same direction must merge near sources.

        Geometry:
            src_A (0, 10)  outputs S
            src_B (1, 10)  outputs S
            sink  (0,  0)  accepts from N

        Both sources output south. A merger near the sink (0,1) would need both
        inputs from the north — impossible for a T-merger. The merger must be
        placed near the sources where one source can turn sideways into it.

        Valid solution: merger at (1,9) accepting from W (src_A turns east)
        and from N (src_B goes straight), then single trunk south to sink.
        """
        from shapez2_tools import route
        from shapez2_tools.generator import Entity

        src_a = Entity(type="BeltPortReceiverInternalVariant", x=0, y=10, rotation=3, layer=0)
        src_b = Entity(type="BeltPortReceiverInternalVariant", x=1, y=10, rotation=3, layer=0)
        sink = Entity(type="BeltPortSenderInternalVariant", x=0, y=0, rotation=3, layer=0)

        # Build the netlist we want to route: src_a→sink, src_b→sink
        nl = lift.Netlist(
            nodes={
                (0, 10): lift.Node(
                    x=0, y=10, layer=0, type=src_a.type, kind="platform_in", rotation=3
                ),
                (1, 10): lift.Node(
                    x=1, y=10, layer=0, type=src_b.type, kind="platform_in", rotation=3
                ),
                (0, 0): lift.Node(
                    x=0, y=0, layer=0, type=sink.type, kind="platform_out", rotation=3
                ),
            },
            edges=[((0, 10), (0, 0)), ((1, 10), (0, 0))],
        )

        stripped = route.entities_to_blueprint([src_a, src_b, sink], platform="Foundation_1x1")
        rerouted_bp = route.reroute_with_junctions(stripped, nl, layer=0)
        rerouted_nl = lift.trace_layer(rerouted_bp, 0)

        # Must produce both edges
        edge_set = {tuple(e) for e in rerouted_nl.edges}
        assert ((0, 10), (0, 0)) in edge_set
        assert ((1, 10), (0, 0)) in edge_set

    def test_fanout_same_direction_splitter_near_sinks(self):
        """One source to two adjacent sinks accepting from the same direction.

        Geometry:
            source (0, 10)  outputs S
            sink_A (0,  0)  accepts from N
            sink_B (1,  0)  accepts from N

        The splitter must be placed near the sinks where one branch can
        approach from the side, not near the source where both branches
        would need to go south in parallel (wasting belts).
        """
        from shapez2_tools import route
        from shapez2_tools.generator import Entity

        src = Entity(type="BeltPortReceiverInternalVariant", x=0, y=10, rotation=3, layer=0)
        sink_a = Entity(type="BeltPortSenderInternalVariant", x=0, y=0, rotation=3, layer=0)
        sink_b = Entity(type="BeltPortSenderInternalVariant", x=1, y=0, rotation=3, layer=0)

        nl = lift.Netlist(
            nodes={
                (0, 10): lift.Node(
                    x=0, y=10, layer=0, type=src.type, kind="platform_in", rotation=3
                ),
                (0, 0): lift.Node(
                    x=0, y=0, layer=0, type=sink_a.type, kind="platform_out", rotation=3
                ),
                (1, 0): lift.Node(
                    x=1, y=0, layer=0, type=sink_b.type, kind="platform_out", rotation=3
                ),
            },
            edges=[((0, 10), (0, 0)), ((0, 10), (1, 0))],
        )

        stripped = route.entities_to_blueprint([src, sink_a, sink_b], platform="Foundation_1x1")
        rerouted_bp = route.reroute_with_junctions(stripped, nl, layer=0)
        rerouted_nl = lift.trace_layer(rerouted_bp, 0)

        # Must produce both edges
        edge_set = {tuple(e) for e in rerouted_nl.edges}
        assert ((0, 10), (0, 0)) in edge_set
        assert ((0, 10), (1, 0)) in edge_set

    def test_fanin_merger_placement_allows_distinct_directions(self):
        """The merger cell must have inputs from distinct directions.

        After routing, find the merger entity and verify its input directions
        are not identical — the whole point of placing near sources.
        """
        from shapez2_tools import route
        from shapez2_tools.generator import Entity

        # Same geometry as test_fanin_same_direction_merger_near_sources
        src_a = Entity(type="BeltPortReceiverInternalVariant", x=0, y=10, rotation=3, layer=0)
        src_b = Entity(type="BeltPortReceiverInternalVariant", x=1, y=10, rotation=3, layer=0)
        sink = Entity(type="BeltPortSenderInternalVariant", x=0, y=0, rotation=3, layer=0)

        nl = lift.Netlist(
            nodes={
                (0, 10): lift.Node(
                    x=0, y=10, layer=0, type=src_a.type, kind="platform_in", rotation=3
                ),
                (1, 10): lift.Node(
                    x=1, y=10, layer=0, type=src_b.type, kind="platform_in", rotation=3
                ),
                (0, 0): lift.Node(
                    x=0, y=0, layer=0, type=sink.type, kind="platform_out", rotation=3
                ),
            },
            edges=[((0, 10), (0, 0)), ((1, 10), (0, 0))],
        )

        stripped = route.entities_to_blueprint([src_a, src_b, sink], platform="Foundation_1x1")
        rerouted_bp = route.reroute_with_junctions(stripped, nl, layer=0)

        # Find the merger entity
        entities = route._all_entities(rerouted_bp)
        mergers = [e for e in entities if "Merger" in e.type]
        assert len(mergers) >= 1, "No merger placed"

        # The merger must be closer to sources (y=10) than to sink (y=0)
        for m in mergers:
            dist_to_sources = min(abs(m.y - 10), abs(m.y - 10))
            dist_to_sink = abs(m.y - 0)
            assert dist_to_sources < dist_to_sink, (
                f"Merger at ({m.x},{m.y}) is closer to sink than sources"
            )

    def test_reroute_with_junctions_rotator_quarter(self):
        """Use junction-aware reroute on the rotator quarter.

        The rotator quarter has 4 sources each fanning out to 2 machines,
        and 4 sinks each receiving from 2 machines. This tests the full
        fan-in/fan-out handling.

        Currently fails because the simplistic "place merger adjacent to sink"
        approach doesn't account for geometric constraints. The sources may not
        be aligned to approach the merger from different directions, requiring
        a more sophisticated placement strategy.
        """
        from shapez2_tools import route

        bp = Blueprint.from_file(REF / "quarter_rotate_180.spz2bp")
        original = lift.trace_layer(bp, 0)

        # Strip belts, keep machines and ports
        stripped = route.strip_belts(bp, layer=0)

        # Re-route using junction-aware routing
        rerouted_bp = route.reroute_with_junctions(stripped, original, layer=0)

        # Lift the result and compare
        rerouted = lift.trace_layer(rerouted_bp, 0)

        # Check structural equivalence
        assert lift.isomorphic(original, rerouted)

    # Fixtures with only single-cell machines (rotators, cutters-as-half-destroyers)
    SINGLE_CELL_FIXTURES = [
        "quarter_rotate_180.spz2bp",
        "quarter_rotate_cw.spz2bp",
        "quarter_rotate_ccw.spz2bp",
        "full_belt_rotate_180.spz2bp",
        "full_belt_rotate_cw.spz2bp",
        "full_belt_rotate_ccw.spz2bp",
        "quarter_destroy_west_half.spz2bp",
    ]

    # Fixtures with multi-cell machines (cutter 2-cell, swapper 2-cell)
    MULTI_CELL_FIXTURES = [
        "cutter_12_to_24.spz2bp",
        "swap_diagonal.spz2bp",
    ]

    @pytest.mark.parametrize("name", SINGLE_CELL_FIXTURES)
    def test_reroute_roundtrip(self, name):
        """Strip and re-route single-cell fixture → isomorphic lift."""
        from shapez2_tools import route

        bp = Blueprint.from_file(REF / name)
        original = lift.trace_layer(bp, 0)
        stripped = route.strip_belts(bp, layer=0)
        rerouted_bp = route.reroute_with_junctions(stripped, original, layer=0)
        rerouted = lift.trace_layer(rerouted_bp, 0)
        assert lift.isomorphic(original, rerouted)

    @pytest.mark.parametrize("name", MULTI_CELL_FIXTURES)
    def test_reroute_roundtrip_multi_cell(self, name):
        """Strip and re-route multi-cell fixture → isomorphic lift (WP-I PathFinder)."""
        from shapez2_tools import route
        from shapez2_tools.pathfinder import strip_and_reroute

        bp = Blueprint.from_file(REF / name)
        original = lift.trace_layer(bp, 0)
        stripped = route.strip_belts(bp, layer=0)
        rerouted_bp = strip_and_reroute(stripped, original, layer=0)
        rerouted = lift.trace_layer(rerouted_bp, 0)
        assert lift.isomorphic(original, rerouted)


class TestMultiCellRouting:
    """WP-C multi-cell: cell-level ports and high-arity (≥4) fan chaining.

    The two failures behind the multi-cell xfail are independent:
    1. A multi-cell machine's ports live on distinct cells, so its several
       outputs must route as separate ports — not as a fan-out junction.
    2. The multi-cell corpus fixtures have 4-way fans; one junction cell holds
       at most 3 legs (3-in/1-out), so 4-way fans need chained junctions.
    """

    def test_cutter_outputs_route_as_distinct_ports(self):
        """A cutter's two outputs are separate ports, not a 1→2 fan-out.

        A CutterDefault at R=0 occupies its anchor (in W / out E) plus a second
        cell one north (out E). Both outputs head east from *different* cells, so
        routing them must emit plain belts and NO splitter — the anchor-level
        router used to mistake them for a fan-out.
        """
        from shapez2_tools import route
        from shapez2_tools.generator import Entity

        cutter = Entity(type="CutterDefaultInternalVariant", x=5, y=5, rotation=0, layer=0)
        # Footprint output cells: anchor (5,5)→E and second (5,4)→E.
        sink_a = Entity(type="BeltPortSenderInternalVariant", x=8, y=5, rotation=0, layer=0)
        sink_b = Entity(type="BeltPortSenderInternalVariant", x=8, y=4, rotation=0, layer=0)

        nl = lift.Netlist(
            nodes={
                (5, 5): lift.Node(x=5, y=5, layer=0, type=cutter.type, kind="machine", rotation=0),
                (8, 5): lift.Node(
                    x=8, y=5, layer=0, type=sink_a.type, kind="platform_out", rotation=0
                ),
                (8, 4): lift.Node(
                    x=8, y=4, layer=0, type=sink_b.type, kind="platform_out", rotation=0
                ),
            },
            edges=[((5, 5), (8, 5)), ((5, 5), (8, 4))],
            port_edges=[((5, 5), (8, 5)), ((5, 4), (8, 4))],
        )

        stripped = route.entities_to_blueprint([cutter, sink_a, sink_b], platform="Foundation_1x4")
        rerouted_bp = route.reroute_with_junctions(stripped, nl, layer=0)

        # No splitter: the two outputs are distinct ports, not a fan-out.
        splitters = [e for e in route._all_entities(rerouted_bp) if "Splitter" in e.type]
        assert splitters == [], f"Unexpected splitter(s): {[e.type for e in splitters]}"

        # Both port-edges realized: anchor → both sinks.
        rerouted = lift.trace_layer(rerouted_bp, 0)
        edge_set = {(tuple(a), tuple(b)) for a, b in rerouted.edges}
        assert ((5, 5), (8, 5)) in edge_set
        assert ((5, 5), (8, 4)) in edge_set

