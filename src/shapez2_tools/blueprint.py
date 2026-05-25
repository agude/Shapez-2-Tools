"""Shapez 2 blueprint codec - decode, modify, encode .spz2bp files."""

from __future__ import annotations

import base64
import gzip
import json
import re
from pathlib import Path
from typing import Any


class Blueprint:
    """Represents a Shapez 2 blueprint."""

    PATTERN = re.compile(r"^SHAPEZ2-(\d+)-(.+)\$$")

    def __init__(self, data: dict, format_version: int = 1):
        self.data = data
        self.format_version = format_version

    @classmethod
    def from_file(cls, path: Path | str) -> Blueprint:
        """Load a blueprint from a .spz2bp file."""
        path = Path(path)
        content = path.read_text().strip()
        return cls.from_string(content)

    @classmethod
    def from_string(cls, content: str) -> Blueprint:
        """Parse a blueprint string."""
        match = cls.PATTERN.match(content.strip())
        if not match:
            raise ValueError("Invalid blueprint format")

        format_version = int(match.group(1))
        encoded = match.group(2)

        compressed = base64.b64decode(encoded)
        json_bytes = gzip.decompress(compressed)
        data = json.loads(json_bytes)

        return cls(data, format_version)

    def to_string(self) -> str:
        """Encode blueprint to string format."""
        json_bytes = json.dumps(self.data, separators=(",", ":")).encode()
        compressed = gzip.compress(json_bytes, mtime=0)
        encoded = base64.b64encode(compressed).decode()
        return f"SHAPEZ2-{self.format_version}-{encoded}$"

    def to_file(self, path: Path | str) -> None:
        """Write blueprint to a .spz2bp file."""
        path = Path(path)
        path.write_text(self.to_string())

    @property
    def version(self) -> int:
        """Game version this blueprint was created with."""
        return self.data.get("V", 0)

    @property
    def bp_type(self) -> str:
        """Blueprint type: 'Island' or 'Building'."""
        return self.data.get("BP", {}).get("$type", "Unknown")

    @property
    def icon(self) -> list:
        """Icon data array (4 slots)."""
        return self.data.get("BP", {}).get("Icon", {}).get("Data", [None] * 4)

    @icon.setter
    def icon(self, value: list) -> None:
        """Set icon data array."""
        if len(value) != 4:
            raise ValueError("Icon must have exactly 4 slots")
        if "BP" not in self.data:
            self.data["BP"] = {}
        if "Icon" not in self.data["BP"]:
            self.data["BP"]["Icon"] = {}
        self.data["BP"]["Icon"]["Data"] = value

    @property
    def entries(self) -> list:
        """Building/island entries."""
        return self.data.get("BP", {}).get("Entries", [])

    def summary(self) -> dict[str, Any]:
        """Return a summary of the blueprint."""
        return {
            "format_version": self.format_version,
            "game_version": self.version,
            "type": self.bp_type,
            "icon": self.icon,
            "entry_count": len(self.entries),
        }

    def to_json(self, indent: int = 2) -> str:
        """Return pretty-printed JSON."""
        return json.dumps(self.data, indent=indent)
