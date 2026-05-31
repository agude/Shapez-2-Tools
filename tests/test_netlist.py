"""WP-A: placement-independent isomorphism of lifted netlists (test-first).

Scaffolded ahead of the implementation (docs/generator-spec.md §7.2 WP-A). These
are xfail until ``lift.isomorphic`` lands; ``strict=True`` flips them to failures
the moment it does, which is the signal to delete this marker. This is the red
bar of the TDD loop for the isomorphism backbone that Rungs 3-4 validate against.
"""

from pathlib import Path

from shapez2_tools import lift
from shapez2_tools.blueprint import Blueprint

REF = Path(__file__).resolve().parent.parent / "data" / "reference"


def _lift(name, layer=0):
    return lift.trace_layer(Blueprint.from_file(REF / name), layer)


class TestIsomorphism:
    def test_self_isomorphic(self):
        q = _lift("quarter_rotate_180.spz2bp")
        assert lift.isomorphic(q, q)

    def test_floors_are_isomorphic(self):
        # Floors are exact duplicates: identical structure, different layer/coords.
        # Proves isomorphism is coordinate-independent on a real example.
        bp = Blueprint.from_file(REF / "quarter_rotate_180.spz2bp")
        assert lift.isomorphic(lift.trace_layer(bp, 0), lift.trace_layer(bp, 1))

    def test_cw_ccw_180_quarters_not_isomorphic(self):
        # Identical 4->8->4 topology, different rotator type -> type-sensitive.
        cw = _lift("quarter_rotate_cw.spz2bp")
        ccw = _lift("quarter_rotate_ccw.spz2bp")
        half = _lift("quarter_rotate_180.spz2bp")
        assert not lift.isomorphic(cw, ccw)
        assert not lift.isomorphic(cw, half)
        assert not lift.isomorphic(ccw, half)

    def test_cutter_not_isomorphic_to_rotator(self):
        cutter = _lift("cutter_12_to_24.spz2bp")
        rotator = _lift("quarter_rotate_cw.spz2bp")
        assert not lift.isomorphic(cutter, rotator)

    def test_full_belt_not_isomorphic_to_quarter(self):
        full = _lift("full_belt_rotate_180.spz2bp")
        quarter = _lift("quarter_rotate_180.spz2bp")
        assert not lift.isomorphic(full, quarter)
