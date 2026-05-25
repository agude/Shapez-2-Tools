"""Tests for blueprint codec."""

import json

import pytest

from shapez2_tools.blueprint import Blueprint

MINIMAL_BP = {
    "V": 1000,
    "BP": {
        "$type": "Building",
        "Icon": {"Data": ["icon:Test", None, None, None]},
        "Entries": [],
    },
}


class TestBlueprint:
    def test_roundtrip(self):
        """Encode then decode produces identical data."""
        bp = Blueprint(MINIMAL_BP.copy(), format_version=1)
        encoded = bp.to_string()
        decoded = Blueprint.from_string(encoded)

        assert decoded.data == bp.data
        assert decoded.format_version == bp.format_version

    def test_string_format(self):
        """Encoded string has correct format."""
        bp = Blueprint(MINIMAL_BP.copy(), format_version=1)
        encoded = bp.to_string()

        assert encoded.startswith("SHAPEZ2-1-")
        assert encoded.endswith("$")

    def test_version_property(self):
        """Version property returns game version."""
        bp = Blueprint(MINIMAL_BP.copy())
        assert bp.version == 1000

    def test_bp_type_property(self):
        """bp_type property returns blueprint type."""
        bp = Blueprint(MINIMAL_BP.copy())
        assert bp.bp_type == "Building"

    def test_icon_getter(self):
        """Icon property returns icon data."""
        bp = Blueprint(MINIMAL_BP.copy())
        assert bp.icon == ["icon:Test", None, None, None]

    def test_icon_setter(self):
        """Icon setter updates icon data."""
        bp = Blueprint(MINIMAL_BP.copy())
        bp.icon = ["icon:A", "icon:B", None, "shape:RuRuRuRu"]
        assert bp.icon == ["icon:A", "icon:B", None, "shape:RuRuRuRu"]

    def test_icon_setter_validates_length(self):
        """Icon setter rejects wrong-length arrays."""
        bp = Blueprint(MINIMAL_BP.copy())
        with pytest.raises(ValueError, match="exactly 4 slots"):
            bp.icon = ["icon:A", "icon:B"]

    def test_entries_property(self):
        """Entries property returns building entries."""
        bp = Blueprint(MINIMAL_BP.copy())
        assert bp.entries == []

    def test_summary(self):
        """Summary returns expected keys."""
        bp = Blueprint(MINIMAL_BP.copy(), format_version=1)
        summary = bp.summary()

        assert summary["format_version"] == 1
        assert summary["game_version"] == 1000
        assert summary["type"] == "Building"
        assert summary["entry_count"] == 0

    def test_invalid_string_raises(self):
        """Invalid blueprint string raises ValueError."""
        with pytest.raises(ValueError, match="Invalid blueprint format"):
            Blueprint.from_string("not a blueprint")

    def test_to_json(self):
        """to_json returns valid JSON."""
        bp = Blueprint(MINIMAL_BP.copy())
        output = bp.to_json()
        parsed = json.loads(output)
        assert parsed == MINIMAL_BP
