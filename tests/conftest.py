"""Pytest fixtures and shared test infrastructure."""

from pathlib import Path

import pytest

from shapez2_tools.blueprint import Blueprint

REF = Path(__file__).resolve().parent.parent / "data" / "reference"

# Closed fixtures: fully ported, unmatched_legs == 0 on every floor.
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

# Open fixtures: dangling edges by design (pinwheel exports, machine demos).
OPEN_FIXTURES = [
    "cutters_8_pinwheel.spz2bp",
    "swappers_4_pinwheel.spz2bp",
    "painters_4_normal.spz2bp",
    "painters_4_mirror.spz2bp",
    "stackers_straight_4.spz2bp",
    "stackers_bent_8.spz2bp",
]


@pytest.fixture
def ref_path():
    return REF


def load_blueprint(name: str) -> Blueprint:
    return Blueprint.from_file(REF / name)
