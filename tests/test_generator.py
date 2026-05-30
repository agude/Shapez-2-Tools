"""Tests for the tile-replication generator (spec foundation + scaffolding)."""

from collections import Counter
from pathlib import Path

import pytest

from shapez2_tools import generator as g
from shapez2_tools.blueprint import Blueprint

REF = Path(__file__).resolve().parent.parent / "data" / "reference"
QUARTER = REF / "quarter_rotate_180.spz2bp"
FULL = REF / "full_belt_rotate_180.spz2bp"


class TestEntity:
    def test_round_trips_through_dict(self):
        d = {"X": 6, "Y": 15, "R": 3, "T": "RotatorHalfInternalVariant"}
        assert g.Entity.from_dict(d).to_dict() == d

    def test_omits_zero_rotation_and_layer(self):
        e = g.Entity(x=1, y=2, type="T")
        assert e.to_dict() == {"X": 1, "Y": 2, "T": "T"}

    def test_translated_shifts_and_relayers(self):
        e = g.Entity(x=6, y=15, type="T", rotation=3, layer=1)
        moved = e.translated(dx=-20, layer=0)
        assert (moved.x, moved.y, moved.rotation, moved.layer) == (-14, 15, 3, 0)


class TestLiftTile:
    def test_tile_is_80_normalized_functional_entities(self):
        tile = g.lift_tile(QUARTER)
        assert len(tile) == 80
        assert all(e.layer == 0 for e in tile)
        assert all(e.type not in g.DECORATION_TYPES for e in tile)

    def test_tile_composition_matches_spec(self):
        counts = Counter(e.type for e in g.lift_tile(QUARTER))
        assert counts["RotatorHalfInternalVariant"] == 8
        assert counts["BeltPortReceiverInternalVariant"] == 4
        assert counts["BeltPortSenderInternalVariant"] == 4
        assert counts["Splitter1To2LInternalVariant"] == 2
        assert counts["Merger2To1LInternalVariant"] == 2
        assert counts["BeltDefaultForwardInternalVariant"] == 42


class TestM1QuarterRoundTrip:
    def test_stamped_quarter_matches_oracle_functionally(self):
        tile = g.lift_tile(QUARTER)
        built = g.build_from_skeleton(QUARTER, g.stamp_platform(tile, "1x1"))
        diff = g.diff_functional(built, Blueprint.from_file(QUARTER))
        assert not diff["only_in_first"]
        assert not diff["only_in_second"]

    def test_quarter_has_240_functional_entities(self):
        tile = g.lift_tile(QUARTER)
        built = g.build_from_skeleton(QUARTER, g.stamp_platform(tile, "1x1"))
        assert len(g.functional_entities(built)) == 240


class TestM2FullBeltIsFourQuarters:
    def test_full_belt_built_from_quarter_tile_matches_oracle(self):
        tile = g.lift_tile(QUARTER)
        built = g.build_from_skeleton(FULL, g.stamp_platform(tile, "1x4"))
        diff = g.diff_functional(built, Blueprint.from_file(FULL))
        assert not diff["only_in_first"], list(diff["only_in_first"])[:5]
        assert not diff["only_in_second"], list(diff["only_in_second"])[:5]

    def test_full_belt_has_960_functional_entities(self):
        tile = g.lift_tile(QUARTER)
        built = g.build_from_skeleton(FULL, g.stamp_platform(tile, "1x4"))
        assert len(g.functional_entities(built)) == 960


class TestGenerateRotatorFamily:
    CASES = [
        ("180", "1x1", "quarter_rotate_180"),
        ("cw", "1x1", "quarter_rotate_cw"),
        ("ccw", "1x1", "quarter_rotate_ccw"),
        ("180", "1x4", "full_belt_rotate_180"),
        ("cw", "1x4", "full_belt_rotate_cw"),
        ("ccw", "1x4", "full_belt_rotate_ccw"),
    ]

    @pytest.mark.parametrize("direction,platform,oracle", CASES)
    def test_matches_oracle_functionally(self, direction, platform, oracle):
        bp = g.generate_rotator(direction, platform=platform)
        ref = Blueprint.from_file(REF / f"{oracle}.spz2bp")
        diff = g.diff_functional(bp, ref)
        assert not diff["only_in_first"], list(diff["only_in_first"])[:3]
        assert not diff["only_in_second"], list(diff["only_in_second"])[:3]

    @pytest.mark.parametrize("direction,platform,oracle", CASES)
    def test_sets_island_icon(self, direction, platform, oracle):
        bp = g.generate_rotator(direction, platform=platform)
        assert bp.icon[3] == g.ROTATORS[direction][1]

    def test_unknown_direction_raises(self):
        with pytest.raises(ValueError):
            g.generate_rotator("90", platform="1x1")


class TestRender:
    def test_render_shows_machines_ports_and_junctions(self):
        out = g.render_text(g.generate_rotator("cw", platform="1x1"), layer=0)
        assert "R" in out  # rotators
        assert "I" in out and "O" in out  # ports
        assert "Y" in out  # split/merge belt junctions
        assert len(out.splitlines()) > 10
