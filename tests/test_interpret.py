"""Functional verification: interpret lifted netlists and check the transform."""

from pathlib import Path

from shapez2_tools import interpret, lift, shapes
from shapez2_tools.blueprint import Blueprint
from shapez2_tools.lift import Netlist, Node
from shapez2_tools.shapes import Shape

REF = Path(__file__).resolve().parent.parent / "data" / "reference"


def _src(xy):
    return Node(xy[0], xy[1], 0, "BeltPortReceiverInternalVariant", "platform_in")


def _sink(xy):
    return Node(xy[0], xy[1], 0, "BeltPortSenderInternalVariant", "platform_out")


def _check_every_lane(name, op, layer=0):
    """Lift the blueprint, feed one shape into every source, and assert every
    sink emits ``op`` applied to it."""
    nl = lift.trace_layer(Blueprint.from_file(REF / name), layer)
    shape = Shape.parse("RuCuSuWu")
    inputs = {p: shape for p, n in nl.nodes.items() if n.kind == "platform_in"}
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


class TestMultiPort:
    """Hand-built netlists exercise the multi-port machinery directly (a cutter's
    one input -> two distinct outputs, a swapper's two inputs -> two outputs)."""

    def test_cutter_splits_into_east_and_west(self):
        # src -> cutter(R0): anchor cell (10,10) = main/east out, second cell
        # (10,9) = secondary/west out, each to its own sink.
        nodes = {
            (9, 10): _src((9, 10)),
            (10, 10): Node(10, 10, 0, "CutterDefaultInternalVariant", "machine", 0),
            (11, 10): _sink((11, 10)),  # main (east)
            (11, 9): _sink((11, 9)),  # secondary (west)
        }
        port_edges = [
            ((9, 10), (10, 10)),  # src -> cutter input (anchor back)
            ((10, 10), (11, 10)),  # anchor out -> east sink
            ((10, 9), (11, 9)),  # second cell out -> west sink
        ]
        nl = Netlist(nodes, [], port_edges)
        shape = Shape.parse("RuCuSuWu")
        out = interpret.interpret(nl, {(9, 10): shape})
        east, west = shapes.cut(shape)
        assert out[(11, 10)] == east and out[(11, 9)] == west

    def _swapper_netlist(self):
        # two srcs -> swapper(R0) anchor (10,10) + second (10,9) -> two sinks.
        nodes = {
            (9, 10): _src((9, 10)),
            (9, 9): _src((9, 9)),
            (10, 10): Node(10, 10, 0, "HalvesSwapperDefaultInternalVariant", "machine", 0),
            (11, 10): _sink((11, 10)),
            (11, 9): _sink((11, 9)),
        }
        port_edges = [
            ((9, 10), (10, 10)),  # src A -> anchor input
            ((9, 9), (10, 9)),  # src B -> second-cell input
            ((10, 10), (11, 10)),  # anchor out -> sink A
            ((10, 9), (11, 9)),  # second out -> sink B
        ]
        return Netlist(nodes, [], port_edges)

    def test_swapper_swaps_west_halves(self):
        a, b = Shape.parse("RuRuRuRu"), Shape.parse("CuCuCuCu")
        out = interpret.interpret(self._swapper_netlist(), {(9, 10): a, (9, 9): b})
        exp_a, exp_b = shapes.swap_west(a, b)
        assert out[(11, 10)] == exp_a and out[(11, 9)] == exp_b

    def test_swapper_diagonal_trick(self):
        # The north-star trick: feed a north-only and a south-only shape; swapping
        # their west halves drops out the two diagonals.
        north = Shape.parse("Ru----Ru")  # NE, NW
        south = Shape.parse("--RuRu--")  # SE, SW
        out = interpret.interpret(self._swapper_netlist(), {(9, 10): north, (9, 9): south})
        assert out[(11, 10)] == Shape.parse("Ru--Ru--")  # NE + SW diagonal
        assert out[(11, 9)] == Shape.parse("--Ru--Ru")  # SE + NW diagonal
