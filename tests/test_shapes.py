"""Tests for the shape model and absolute operations (Rung 2)."""

from shapez2_tools import shapes
from shapez2_tools.shapes import Shape


class TestParse:
    def test_round_trip(self):
        assert str(Shape.parse("RuCuSuWu")) == "RuCuSuWu"

    def test_empty_quadrants(self):
        s = Shape.parse("Ru----Wu")
        assert s.quads == ("Ru", None, None, "Wu")
        assert str(s) == "Ru----Wu"


class TestRotation:
    def test_four_cw_is_identity(self):
        s = Shape.parse("RuCuSuWu")
        r = s
        for _ in range(4):
            r = shapes.rotate_cw(r)
        assert r == s

    def test_cw_then_ccw_is_identity(self):
        s = Shape.parse("RuCuSuWu")
        assert shapes.rotate_ccw(shapes.rotate_cw(s)) == s

    def test_180_is_two_cw(self):
        s = Shape.parse("RuCuSuWu")
        assert shapes.rotate_180(s) == shapes.rotate_cw(shapes.rotate_cw(s))

    def test_cw_moves_parts_clockwise(self):
        # NE part should land in SE after one CW step.
        s = Shape.parse("Ru------")  # NE only
        assert str(shapes.rotate_cw(s)) == "--Ru----"  # now SE only


class TestCutting:
    def test_cut_splits_east_west(self):
        east, west = shapes.cut(Shape.parse("RuCuSuWu"))
        assert str(east) == "RuCu----"  # NE, SE
        assert str(west) == "----SuWu"  # SW, NW

    def test_half_destroy_keeps_east(self):
        assert str(shapes.half_destroy(Shape.parse("RuCuSuWu"))) == "RuCu----"


class TestSwapper:
    def test_swaps_west_halves(self):
        a, b = shapes.swap_west(Shape.parse("RuCuSuWu"), Shape.parse("AABBCCDD"))
        assert str(a) == "RuCuCCDD"  # a east + b west
        assert str(b) == "AABBSuWu"  # b east + a west

    def test_diagonal_extractor_trick(self):
        # Feed a north-only shape and a south-only shape; swapping west halves
        # yields the two diagonals (the diagonal-extractor mechanism).
        north = Shape.parse("Ru----Ru")  # NE + NW present
        south = Shape.parse("--RuRu--")  # SE + SW present
        a, b = shapes.swap_west(north, south)
        assert str(a) == "Ru--Ru--"  # NE + SW = one diagonal
        assert str(b) == "--Ru--Ru"  # SE + NW = the other diagonal
