"""WP-B: corpus sweep — closed fixtures lift clean on every floor."""

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


@pytest.mark.parametrize("name", CLOSED_FIXTURES)
def test_closed_fixtures_lift_clean(name):
    """Every closed fixture has 0 unmatched legs on all floors."""
    bp = Blueprint.from_file(REF / name)
    for layer in range(3):
        assert lift.unmatched_legs(bp, layer) == 0, f"{name} layer {layer}"
