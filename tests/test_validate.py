"""WP-B: physical validator — corpus is valid, broken inputs detected."""

from pathlib import Path

import pytest

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
    "balancer_12_to_12.spz2bp",
]


class TestValidate:
    @pytest.mark.parametrize("name", CLOSED_FIXTURES)
    def test_corpus_is_valid(self, name):
        from shapez2_tools import lift

        bp = Blueprint.from_file(REF / name)
        problems = lift.validate(bp)
        assert problems == []

    def test_overlap_detected(self):
        from shapez2_tools import lift

        # Hand-build a blueprint with two entities at the same position.
        bp = Blueprint.from_file(REF / "quarter_rotate_180.spz2bp")
        # Duplicate an entity at the same coords (creates overlap).
        ent = bp.data["BP"]["Entries"][0]["B"]["Entries"][0]
        bp.data["BP"]["Entries"][0]["B"]["Entries"].append(dict(ent))
        problems = lift.validate(bp)
        assert any("overlap" in str(p).lower() for p in problems)

    def test_dangling_leg_detected(self):
        from shapez2_tools import lift

        # Open fixtures have dangling edges by design.
        bp = Blueprint.from_file(REF / "cutters_8_pinwheel.spz2bp")
        problems = lift.validate(bp)
        assert any("unmatched" in str(p).lower() or "dangling" in str(p).lower() for p in problems)
