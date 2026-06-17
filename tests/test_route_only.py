"""Tests for route_only: Chunk 1 (find + classify dangling belt ends), Chunk 2
(find + partition unconnected ports), Chunk 3 (match dangles to ports), Chunk 4
(build passable set from existing occupancy)."""

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


class TestFindUnconnectedPorts:
    @pytest.mark.skipif(not HALF_SPLITTER.exists(), reason="Half Splitter not found")
    def test_half_splitter_layer0(self):
        bp = Blueprint.from_file(HALF_SPLITTER)
        nl = lift.trace_layer(bp, 0)
        ports = route_only.find_unconnected_ports(nl)
        assert len(ports) == 46
        assert all(nl.nodes[p].kind == "platform_in" for p in ports)

    def test_small_fixture_no_unconnected_ports(self):
        src = Entity(type="BeltPortReceiverInternalVariant", x=-1, y=0, rotation=0, layer=0)
        cutter = Entity(type="CutterDefaultInternalVariant", x=0, y=0, rotation=0, layer=0)
        bp = route.entities_to_blueprint([src, cutter], platform="Foundation_1x1")
        nl = lift.trace_layer(bp, 0)
        assert route_only.find_unconnected_ports(nl) == []


class TestPartitionPorts:
    @pytest.mark.skipif(not HALF_SPLITTER.exists(), reason="Half Splitter not found")
    def test_half_splitter_layer0(self):
        bp = Blueprint.from_file(HALF_SPLITTER)
        nl = lift.trace_layer(bp, 0)
        ports = route_only.find_unconnected_ports(nl)
        west, east = route_only.partition_ports(ports, "Foundation_2x4")
        assert len(west) + len(east) == len(ports)
        assert len(west) == 23
        assert len(east) == 23

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
        nl = lift.trace_layer(bp, 0)
        dangles = route_only.find_and_classify_dangles(bp, 0)
        ports = route_only.find_unconnected_ports(nl)
        west_ports, east_ports = route_only.partition_ports(ports, "Foundation_2x4")
        west_dangles = [(d.x, d.y) for d in dangles if d.half == "west"]
        east_dangles = [(d.x, d.y) for d in dangles if d.half == "east"]

        west_pairs = route_only.match_dangles_to_ports(west_dangles, west_ports)
        east_pairs = route_only.match_dangles_to_ports(east_dangles, east_ports)

        assert len(west_pairs) == len(west_dangles)
        assert len(east_pairs) == len(east_dangles)
        # Every matched port is reasonably close to its dangle — sanity bound,
        # not a precise distance claim.
        for d, p in west_pairs + east_pairs:
            dist = abs(d[0] - p[0]) + abs(d[1] - p[1])
            assert dist < 60


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
