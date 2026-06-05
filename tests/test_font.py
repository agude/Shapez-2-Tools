"""Tests for the bitmap font silk-screening module."""

from shapez2_tools.font import CELL_HEIGHT, GLYPHS, TRASH_TYPE, silkscreen


class TestGlyphs:
    def test_all_printable_ascii_present(self):
        for code in range(32, 127):
            assert chr(code) in GLYPHS

    def test_each_glyph_has_correct_height(self):
        for ch, rows in GLYPHS.items():
            assert len(rows) == CELL_HEIGHT, f"{ch!r} has {len(rows)} rows"

    def test_space_is_blank(self):
        assert all(row == 0 for row in GLYPHS[" "])

    def test_nonblank_chars_have_lit_pixels(self):
        for ch, rows in GLYPHS.items():
            if ch != " ":
                assert any(row != 0 for row in rows), f"{ch!r} is blank"


class TestSilkscreen:
    def test_empty_string_returns_no_entities(self):
        assert silkscreen("", 0, 0) == []

    def test_space_returns_no_entities(self):
        assert silkscreen(" ", 0, 0) == []

    def test_all_entities_are_trash(self):
        for e in silkscreen("A", 0, 14):
            assert e.type == TRASH_TYPE

    def test_scale_doubles_entity_count_per_pixel(self):
        s1 = len(silkscreen("A", 0, 14, scale=1))
        s2 = len(silkscreen("A", 0, 14, scale=2))
        assert s2 == s1 * 2

    def test_origin_offsets_all_entities(self):
        base = silkscreen("A", 0, 100, scale=1)
        shifted = silkscreen("A", 50, 100, scale=1)
        base_xs = {e.x for e in base}
        shifted_xs = {e.x for e in shifted}
        assert shifted_xs == {x + 50 for x in base_xs}

    def test_y_decreases_from_origin(self):
        entities = silkscreen("A", 0, 100, scale=1)
        assert all(e.y <= 100 for e in entities)

    def test_layer_propagates(self):
        for e in silkscreen("A", 0, 14, layer=2):
            assert e.layer == 2

    def test_unknown_char_produces_filled_rect(self):
        entities = silkscreen("\x80", 0, 14, scale=1)
        assert len(entities) > 0
