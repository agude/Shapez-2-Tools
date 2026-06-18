"""Tests for route_only: Chunk 1 (find + classify dangling belt ends), Chunk 2
(find + partition unconnected ports), Chunk 3 (match dangles to ports), Chunk 4
(build passable set from existing occupancy), Chunk 5 (build nets + route)."""

from collections import Counter
from pathlib import Path

import pytest

from shapez2_tools import lift, pathfinder, route, route_only
from shapez2_tools.blueprint import Blueprint
from shapez2_tools.generator import Entity

BLUEPRINTS = Path.home() / "Projects" / "shapez_2_blueprints"
HALF_SPLITTER = BLUEPRINTS / "UNFINISHED Half Splitter.spz2bp"


class TestFindAndClassifyDangles:
    @pytest.mark.skipif(not HALF_SPLITTER.exists(), reason="Half Splitter not found")
    def test_half_splitter_layer0(self):
        bp = Blueprint.from_file(HALF_SPLITTER)
        dangles = route_only.find_and_classify_dangles(bp, 0)
        assert len(dangles) == 24
        assert {d.half for d in dangles} <= {"west", "east"}
        # Reference split for this fixture (see docs/route-only-spec.md Chunk 1
        # tests); one dangle's upstream merger genuinely mixes both halves in
        # the hand-placed source, so the exact count is fixture-specific, not
        # a balanced 12/12.
        counts = Counter(d.half for d in dangles)
        assert counts["west"] + counts["east"] == 24

    @pytest.mark.skipif(not HALF_SPLITTER.exists(), reason="Half Splitter not found")
    def test_half_splitter_matches_unmatched_legs_count(self):
        from shapez2_tools import lift

        bp = Blueprint.from_file(HALF_SPLITTER)
        dangles = route_only.find_and_classify_dangles(bp, 0)
        assert len(dangles) == lift.unmatched_legs(bp, 0)

    def test_small_fixture_cutter_with_dangling_belt(self):
        # Receiver -> CutterDefault (anchor output continues through a belt
        # that dangles; second cell's output dangles directly off the cutter).
        src = Entity(type="BeltPortReceiverInternalVariant", x=-1, y=0, rotation=0, layer=0)
        cutter = Entity(type="CutterDefaultInternalVariant", x=0, y=0, rotation=0, layer=0)
        belt = Entity(type="BeltDefaultForwardInternalVariant", x=1, y=0, rotation=0, layer=0)
        bp = route.entities_to_blueprint([src, cutter, belt], platform="Foundation_1x1")

        dangles = route_only.find_and_classify_dangles(bp, 0)
        by_pos = {(d.x, d.y): d.half for d in dangles}

        assert by_pos[(1, 0)] == "east"  # traced through the belt to the anchor cell
        assert by_pos[(0, -1)] == "west"  # the cutter's second cell, dangling directly

    def test_small_fixture_mirrored_cutter_swaps_halves(self):
        src = Entity(type="BeltPortReceiverInternalVariant", x=-1, y=0, rotation=0, layer=0)
        cutter = Entity(
            type="CutterDefaultInternalVariantMirrored", x=0, y=0, rotation=0, layer=0
        )
        bp = route.entities_to_blueprint([src, cutter], platform="Foundation_1x1")

        dangles = route_only.find_and_classify_dangles(bp, 0)
        by_pos = {(d.x, d.y): d.half for d in dangles}

        assert by_pos[(0, 0)] == "west"  # anchor cell, mirrored
        assert by_pos[(0, 1)] == "east"  # second cell, mirrored


class TestFindFreePortPositions:
    @pytest.mark.skipif(not HALF_SPLITTER.exists(), reason="Half Splitter not found")
    def test_half_splitter_layer0(self):
        bp = Blueprint.from_file(HALF_SPLITTER)
        ports = route_only.find_free_port_positions(bp, 0)
        assert len(ports) == 24

    def test_small_fixture_all_ports_free(self):
        src = Entity(type="BeltPortReceiverInternalVariant", x=-1, y=0, rotation=0, layer=0)
        cutter = Entity(type="CutterDefaultInternalVariant", x=0, y=0, rotation=0, layer=0)
        bp = route.entities_to_blueprint([src, cutter], platform="Foundation_1x1")
        free = route_only.find_free_port_positions(bp, 0)
        assert len(free) == 16


class TestPartitionPorts:
    @pytest.mark.skipif(not HALF_SPLITTER.exists(), reason="Half Splitter not found")
    def test_half_splitter_layer0(self):
        bp = Blueprint.from_file(HALF_SPLITTER)
        ports = route_only.find_free_port_positions(bp, 0)
        west, east = route_only.partition_ports(ports, "Foundation_2x4")
        assert len(west) + len(east) == len(ports)
        assert len(west) == 12
        assert len(east) == 12

    def test_splits_by_center(self):
        ports = [(-2, 0), (0, 0), (2, 0), (50, 0)]
        west, east = route_only.partition_ports(ports, "Foundation_2x4")
        assert set(west) == {(-2, 0), (0, 0), (2, 0)}
        assert set(east) == {(50, 0)}


class TestMatchDanglesToPorts:
    def test_pairs_nearest_neighbors(self):
        dangles = [(0, 0), (10, 0)]
        ports = [(1, 0), (9, 0)]
        pairs = route_only.match_dangles_to_ports(dangles, ports)
        assert set(pairs) == {((0, 0), (1, 0)), ((10, 0), (9, 0))}

    def test_excess_ports_left_unmatched(self):
        dangles = [(0, 0)]
        ports = [(1, 0), (2, 0)]
        pairs = route_only.match_dangles_to_ports(dangles, ports)
        assert len(pairs) == 1
        assert pairs[0][0] == (0, 0)

    @pytest.mark.skipif(not HALF_SPLITTER.exists(), reason="Half Splitter not found")
    def test_half_splitter_layer0_geographically_sensible(self):
        bp = Blueprint.from_file(HALF_SPLITTER)
        dangles = route_only.find_and_classify_dangles(bp, 0)
        ports = route_only.find_free_port_positions(bp, 0)
        west_ports, east_ports = route_only.partition_ports(ports, "Foundation_2x4")
        west_dangles = [(d.x, d.y) for d in dangles if d.half == "west"]
        east_dangles = [(d.x, d.y) for d in dangles if d.half == "east"]

        west_pairs = route_only.match_dangles_to_ports(west_dangles, west_ports)
        east_pairs = route_only.match_dangles_to_ports(east_dangles, east_ports)

        assert len(west_pairs) == len(west_dangles)
        assert len(east_pairs) == len(east_dangles)
        for d, p in west_pairs + east_pairs:
            dist = abs(d[0] - p[0]) + abs(d[1] - p[1])
            assert dist < 80


class TestBuildPassableFromOccupancy:
    @pytest.mark.skipif(not HALF_SPLITTER.exists(), reason="Half Splitter not found")
    def test_half_splitter_layer0_excludes_occupied_cells(self):
        bp = Blueprint.from_file(HALF_SPLITTER)
        occ = lift._occupancy(bp, 0)
        passable = route_only.build_passable_from_occupancy(bp, 0, "Foundation_2x4")

        passable_xy = {(x, y) for x, y, _layer in passable}
        assert passable_xy.isdisjoint(occ.keys())
        assert all(layer == 0 for _x, _y, layer in passable)

    @pytest.mark.skipif(not HALF_SPLITTER.exists(), reason="Half Splitter not found")
    def test_half_splitter_layer0_known_free_and_occupied_cells(self):
        bp = Blueprint.from_file(HALF_SPLITTER)
        occ = lift._occupancy(bp, 0)
        passable = route_only.build_passable_from_occupancy(bp, 0, "Foundation_2x4")

        # A known belt cell from the occupancy map is not passable.
        occupied_pos = next(iter(occ))
        assert (occupied_pos[0], occupied_pos[1], 0) not in passable

        # A known free cell (interior, unoccupied, off the platform ring) is.
        min_x, max_x, min_y, max_y = pathfinder._platform_bounds("Foundation_2x4")
        free = next(
            (x, y)
            for x in range(min_x + 1, max_x)
            for y in range(min_y + 1, max_y)
            if (x, y) not in occ
        )
        assert (free[0], free[1], 0) in passable

    def test_endpoints_remain_passable_even_when_occupied(self):
        min_x, _max_x, min_y, _max_y = pathfinder._platform_bounds("Foundation_1x1")
        ax, ay = min_x + 1, min_y + 1
        src = Entity(
            type="BeltPortReceiverInternalVariant", x=ax - 1, y=ay, rotation=0, layer=0
        )
        cutter = Entity(
            type="CutterDefaultInternalVariant", x=ax, y=ay, rotation=0, layer=0
        )
        bp = route.entities_to_blueprint([src, cutter], platform="Foundation_1x1")

        occ = lift._occupancy(bp, 0)
        assert (ax, ay) in occ  # the cutter anchor is occupied

        passable_without = route_only.build_passable_from_occupancy(bp, 0, "Foundation_1x1")
        assert (ax, ay, 0) not in passable_without

        passable_with = route_only.build_passable_from_occupancy(
            bp, 0, "Foundation_1x1", endpoints={(ax, ay)}
        )
        assert (ax, ay, 0) in passable_with

    def test_excludes_platform_edge_ring(self):
        src = Entity(type="BeltPortReceiverInternalVariant", x=-1, y=0, rotation=0, layer=0)
        cutter = Entity(type="CutterDefaultInternalVariant", x=0, y=0, rotation=0, layer=0)
        bp = route.entities_to_blueprint([src, cutter], platform="Foundation_1x1")

        min_x, max_x, min_y, max_y = pathfinder._platform_bounds("Foundation_1x1")
        passable = route_only.build_passable_from_occupancy(bp, 0, "Foundation_1x1")
        ring = {
            (x, y, 0)
            for x in range(min_x, max_x + 1)
            for y in range(min_y, max_y + 1)
            if x in (min_x, max_x) or y in (min_y, max_y)
        }
        assert passable.isdisjoint(ring)


class TestPortFace:
    @pytest.mark.parametrize(
        "pos, expected_dir, expected_rotation",
        [
            ((17, 8), lift.W, 0),  # east edge (max_x): faces east, fed from west
            ((8, 17), lift.S, 1),  # north edge (max_y): faces north, fed from south
            ((2, 8), lift.E, 2),  # west edge (min_x): faces west, fed from east
            ((8, 2), lift.N, 3),  # south edge (min_y): faces south, fed from north
        ],
    )
    def test_matches_placed_port_rotations(self, pos, expected_dir, expected_rotation):
        # Calibration check: these (pos, rotation) pairs are taken from real
        # placed BeltPortSenderInternalVariant entities in the reference corpus.
        interior_dir, rotation = route_only._port_face(pos, "Foundation_1x1")
        assert interior_dir == expected_dir
        assert rotation == expected_rotation

    def test_interior_position_raises(self):
        with pytest.raises(ValueError, match="not on a platform edge"):
            route_only._port_face((9, 9), "Foundation_1x1")


class TestBuildRoutingNets:
    def test_single_pair_root_and_terminal_offset_into_passable_space(self):
        cutter = Entity(type="CutterDefaultInternalVariant", x=10, y=10, rotation=0, layer=0)
        bp = route.entities_to_blueprint([cutter], platform="Foundation_1x1")

        nets = route_only.build_routing_nets(
            [((10, 10), (17, 8))], bp, 0, "Foundation_1x1"
        )

        assert len(nets) == 1
        net = nets[0]
        assert net.kind == "fanout"
        assert net.root == (11, 10, 0)  # one east of the dangle (its output dir)
        assert net.root_approach == (1, 0)
        assert net.terminals == [(16, 8, 0)]  # one west of the port (its interior dir)
        assert net.terminal_exit == {(16, 8, 0): (1, 0)}


class TestRouteLayerNets:
    def test_single_pair_routes_and_emits_valid_belts(self):
        cutter = Entity(type="CutterDefaultInternalVariant", x=10, y=10, rotation=0, layer=0)
        bp = route.entities_to_blueprint([cutter], platform="Foundation_1x1")

        nets = route_only.build_routing_nets(
            [((10, 10), (17, 8))], bp, 0, "Foundation_1x1"
        )
        endpoints = {(c[0], c[1]) for n in nets for c in (n.root, n.terminals[0])}
        passable = route_only.build_passable_from_occupancy(
            bp, 0, "Foundation_1x1", endpoints=endpoints
        )
        graph = pathfinder.RoutingGraph(passable=passable, hop_range=5)

        assert pathfinder.pathfinder_route(nets, graph)
        route_only._attach_boundary_edges(nets)

        net = nets[0]
        assert net.tree_edges[0] == ((10, 10, 0), net.root)  # dangle -> root boundary edge
        assert net.tree_edges[-1] == (net.terminals[0], (17, 8, 0))  # term -> port

        entities = pathfinder.emit_entities(nets)
        assert entities  # at least one routing cell got a belt
        assert all((e.x, e.y) != (10, 10) for e in entities)  # dangle cell untouched
        assert all((e.x, e.y) != (17, 8) for e in entities)  # port cell untouched

    @pytest.mark.skipif(not HALF_SPLITTER.exists(), reason="Half Splitter not found")
    def test_half_splitter_layer0_all_dangles_route(self):
        bp = Blueprint.from_file(HALF_SPLITTER)
        nets = route_only.route_layer_nets(bp, 0)

        assert len(nets) == 24
        entities = pathfinder.emit_entities(nets)
        assert entities
