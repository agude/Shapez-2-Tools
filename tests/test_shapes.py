"""Tests for the shape model and absolute operations (Rung 2)."""

from shapez2_tools import shapes
from shapez2_tools.shapes import MAX_LAYERS, Shape


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


class TestMultiLayer:
    def test_parse_single_layer_unchanged(self):
        s = Shape.parse("RuCuSuWu")
        assert s.num_layers == 1
        assert s.quads == ("Ru", "Cu", "Su", "Wu")
        assert s.upper == ()

    def test_parse_multi_layer(self):
        s = Shape.parse("RuCuSuWu:AuBuCuDu")
        assert s.num_layers == 2
        assert s.quads == ("Ru", "Cu", "Su", "Wu")
        assert s.upper == (("Au", "Bu", "Cu", "Du"),)

    def test_str_round_trip(self):
        code = "RuCuSuWu:AuBuCuDu"
        assert str(Shape.parse(code)) == code

    def test_single_layer_equality_unchanged(self):
        assert Shape.parse("RuCuSuWu") == Shape(("Ru", "Cu", "Su", "Wu"))

    def test_rotate_multi_layer(self):
        s = Shape.parse("RuCuSuWu:Au------")
        r = shapes.rotate_cw(s)
        assert r.num_layers == 2
        assert str(r) == "WuRuCuSu:--Au----"


class TestStacking:
    def test_no_overlap_merges_to_one_layer(self):
        east = Shape.parse("RuRu----")
        west = Shape.parse("----SuSu")
        result = shapes.stack(east, west)
        assert str(result) == "RuRuSuSu"
        assert result.num_layers == 1

    def test_full_overlap_stacks_to_two_layers(self):
        full = Shape.parse("RuRuRuRu")
        result = shapes.stack(full, full)
        assert result.num_layers == 2
        assert str(result) == "RuRuRuRu:RuRuRuRu"

    def test_half_overlap_keeps_two_layers(self):
        bottom = Shape.parse("RuRu----")  # east half
        top = Shape.parse("RuRu----")  # same east half
        result = shapes.stack(bottom, top)
        assert result.num_layers == 2
        assert str(result) == "RuRu----:RuRu----"

    def test_diagonal_falls_independently(self):
        # NE+SW are NOT adjacent → separate groups.
        # Bottom supports only NE; SW falls to layer 0.
        bottom = Shape.parse("Ru------")  # NE only
        top = Shape.parse("Au--Bu--")  # NE + SW (diagonal, two groups)
        result = shapes.stack(bottom, top)
        assert result.num_layers == 2
        assert result.quads == ("Ru", None, "Bu", None)  # L0: NE + SW(fell)
        assert result.upper[0] == ("Au", None, None, None)  # L1: NE(supported)

    def test_connected_group_stays_together(self):
        # NE+SE are adjacent → one group. If NE is supported, SE stays too.
        bottom = Shape.parse("Ru------")  # NE only
        top = Shape.parse("AuBu----")  # NE + SE (adjacent, one group)
        result = shapes.stack(bottom, top)
        assert result.num_layers == 2
        assert result.quads == ("Ru", None, None, None)  # L0 unchanged
        assert result.upper[0] == ("Au", "Bu", None, None)  # whole group on L1

    def test_truncation(self):
        s = Shape.parse("RuRuRuRu")
        result = s
        for _ in range(MAX_LAYERS):
            result = shapes.stack(result, s)
        assert result.num_layers == MAX_LAYERS

    def test_west_on_east(self):
        east = Shape.parse("RuRu----")
        west = Shape.parse("----SuSu")
        assert str(shapes.stack(east, west)) == "RuRuSuSu"
        assert str(shapes.stack(west, east)) == "RuRuSuSu"


class TestGravityGroups:
    def test_all_four_is_one_group(self):
        groups = shapes._find_groups(("Ru", "Ru", "Ru", "Ru"))
        assert len(groups) == 1

    def test_diagonal_is_two_groups(self):
        groups = shapes._find_groups(("Ru", None, "Ru", None))
        assert len(groups) == 2

    def test_three_adjacent_is_one_group(self):
        groups = shapes._find_groups(("Ru", "Ru", "Ru", None))
        assert len(groups) == 1

    def test_empty_layer_is_no_groups(self):
        assert shapes._find_groups((None, None, None, None)) == []
