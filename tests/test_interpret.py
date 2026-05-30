"""Functional verification: interpret lifted netlists and check the transform."""

from pathlib import Path

from shapez2_tools import interpret, lift, shapes
from shapez2_tools.blueprint import Blueprint
from shapez2_tools.shapes import Shape

REF = Path(__file__).resolve().parent.parent / "data" / "reference"


def _check_every_lane(name, op, layer=0):
    """Lift the blueprint, feed one shape into every source, and assert every
    sink emits ``op`` applied to it."""
    nl = lift.trace_layer(Blueprint.from_file(REF / name), layer)
    shape = Shape.parse("RuCuSuWu")
    inputs = {p: shape for p, n in nl.nodes.items() if n.kind == "src"}
    out = interpret.interpret(nl, inputs)
    assert out, "no sinks recovered"
    expected = op(shape)
    assert all(v == expected for v in out.values()), out


class TestInterpret:
    def test_quarter_180_rotates_every_lane(self):
        _check_every_lane("quarter_rotate_180.spz2bp", shapes.rotate_180)

    def test_quarter_cw(self):
        _check_every_lane("quarter_rotate_cw.spz2bp", shapes.rotate_cw)

    def test_quarter_ccw(self):
        _check_every_lane("quarter_rotate_ccw.spz2bp", shapes.rotate_ccw)

    def test_half_destroyer_keeps_east(self):
        _check_every_lane("quarter_destroy_west_half.spz2bp", shapes.half_destroy)

    def test_full_belt_180_all_48_lanes(self):
        _check_every_lane("full_belt_rotate_180.spz2bp", shapes.rotate_180)
