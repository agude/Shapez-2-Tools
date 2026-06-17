"""Tests for route_only: Chunk 1 (find + classify dangling belt ends)."""

from collections import Counter
from pathlib import Path

import pytest

from shapez2_tools import route, route_only
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
