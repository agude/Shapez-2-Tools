"""Tile-replication generator for single-operation platform blueprints.

See ``docs/generator-spec.md``. v1 builds the rotator family by lifting one
floor of a quarter platform (the 80-entity "tile") from a known-good blueprint
and stamping it across the three floors and across N platform units. The
platform/island wrapper is lifted from an oracle and reused verbatim; only the
building ``Entries`` are generated.

No belt geometry or rotation reasoning is involved: tiles are copied verbatim
and translated, and translation preserves ``R`` and ``T``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from shapez2_tools.blueprint import Blueprint

# Building types that are decoration, not function (spec section 2.2):
# the blueprint name tag and the trash pixel-art signage.
DECORATION_TYPES = frozenset({"LabelDefaultInternalVariant", "TrashDefaultInternalVariant"})

# A blueprint platform unit is 20x20 tiles; the three floors are L0/L1/L2.
UNIT_PITCH = 20
FLOORS = (0, 1, 2)

# X-offsets of each platform unit relative to the canonical quarter tile
# (spec section 2.2): the 1x4 holds four units at pitch 20, with the canonical
# tile aligning to the second unit.
PLATFORM_X_OFFSETS: dict[str, tuple[int, ...]] = {
    "1x1": (0,),
    "1x4": (-20, 0, 20, 40),
}


@dataclass(frozen=True)
class Entity:
    """A single building inside a platform, in platform-local coordinates."""

    x: int
    y: int
    type: str
    rotation: int = 0
    layer: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> Entity:
        """Build from a raw blueprint entry (missing R/L default to 0)."""
        return cls(
            x=d.get("X", 0),
            y=d.get("Y", 0),
            type=d["T"],
            rotation=d.get("R", 0),
            layer=d.get("L", 0),
        )

    def to_dict(self) -> dict:
        """Serialize to a raw blueprint entry, omitting zero R/L like the game."""
        d: dict = {"X": self.x, "Y": self.y}
        if self.rotation:
            d["R"] = self.rotation
        if self.layer:
            d["L"] = self.layer
        d["T"] = self.type
        return d

    def translated(self, dx: int = 0, dy: int = 0, layer: int | None = None) -> Entity:
        """Copy shifted in X/Y and optionally moved to another floor."""
        return Entity(
            x=self.x + dx,
            y=self.y + dy,
            type=self.type,
            rotation=self.rotation,
            layer=self.layer if layer is None else layer,
        )


def _platform_entries(bp: Blueprint) -> list[dict]:
    """Yield every building entry across all platforms of a blueprint."""
    entries: list[dict] = []
    for platform in bp.entries:
        body = platform.get("B")
        if body:
            entries.extend(body.get("Entries", []))
    return entries


def functional_entities(bp: Blueprint) -> list[Entity]:
    """All non-decoration building entities in a blueprint."""
    return [
        e for d in _platform_entries(bp) if (e := Entity.from_dict(d)).type not in DECORATION_TYPES
    ]


def lift_tile(path: Path | str, layer: int = 1) -> list[Entity]:
    """Extract one floor's functional tile from an oracle, normalized to L0.

    Floors are exact duplicates, so any floor yields the same tile; L1 is used
    by default because it carries no decoration.
    """
    bp = Blueprint.from_file(path)
    return [
        Entity(x=e.x, y=e.y, type=e.type, rotation=e.rotation, layer=0)
        for e in functional_entities(bp)
        if e.layer == layer
    ]


def stamp(
    tile: list[Entity],
    x_offsets: tuple[int, ...],
    layers: tuple[int, ...] = FLOORS,
) -> list[Entity]:
    """Replicate a tile across floors and across platform units in X."""
    return [e.translated(dx=dx, layer=layer) for layer in layers for dx in x_offsets for e in tile]


def stamp_platform(tile: list[Entity], platform: str) -> list[Entity]:
    """Stamp a tile for a named platform layout (e.g. ``"1x1"``, ``"1x4"``)."""
    return stamp(tile, PLATFORM_X_OFFSETS[platform])


def build_from_skeleton(
    skeleton: Path | str, entities: list[Entity], platform_index: int = 0
) -> Blueprint:
    """Lift the wrapper from an oracle and replace its building entries."""
    bp = Blueprint.from_file(skeleton)
    bp.entries[platform_index]["B"]["Entries"] = [e.to_dict() for e in entities]
    return bp


def diff_functional(a: Blueprint, b: Blueprint) -> dict[str, Counter]:
    """Compare two blueprints by functional-entity multiset (spec section 8).

    Returns the entities present in exactly one side; both empty means the
    functional layouts are identical.
    """
    ca = Counter(astuple(e) for e in functional_entities(a))
    cb = Counter(astuple(e) for e in functional_entities(b))
    return {"only_in_first": ca - cb, "only_in_second": cb - ca}


def astuple(e: Entity) -> tuple[int, int, int, int, str]:
    """Canonical comparison key for an entity."""
    return (e.x, e.y, e.rotation, e.layer, e.type)


# === Parametric rotator family (scaffolding / regression floor) =============
# CW/CCW tiles are the 180 tile with only the rotator building type swapped
# (verified). The wrapper is identical across directions except the island icon.

REFERENCE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "reference"

# direction -> (rotator building type, island icon for BP.Icon slot 4)
ROTATORS: dict[str, tuple[str, str]] = {
    "180": ("RotatorHalfInternalVariant", "icon:building.RotatorHalfVariant"),
    "cw": ("RotatorOneQuadInternalVariant", "icon:building.RotatorOneQuadVariant"),
    "ccw": ("RotatorOneQuadCCWInternalVariant", "icon:building.RotatorOneQuadCCWVariant"),
}

# platform -> reference blueprint whose wrapper (island/platform/icons) is reused
PLATFORM_SKELETON: dict[str, str] = {
    "1x1": "quarter_rotate_180.spz2bp",
    "1x4": "full_belt_rotate_180.spz2bp",
}

_BASE_TILE = "quarter_rotate_180.spz2bp"


def reference(name: str) -> Path:
    """Path to a committed reference blueprint under data/reference/."""
    return REFERENCE_DIR / name


def substitute(tile: list[Entity], mapping: dict[str, str]) -> list[Entity]:
    """Return a copy of the tile with building types remapped."""
    return [Entity(e.x, e.y, mapping.get(e.type, e.type), e.rotation, e.layer) for e in tile]


_DIRECTION_LABELS: dict[str, str] = {"180": "180", "cw": "CW", "ccw": "CCW"}
_LABEL_TYPE = "LabelDefaultInternalVariant"
_LABEL_POS = (54, 3)


def _find_gaps(entities: list[Entity]) -> list[tuple[int, int]]:
    """Find contiguous free-X runs on layer 0 between the outermost occupied columns."""
    occupied = sorted(set(e.x for e in entities if e.layer == 0))
    if not occupied:
        return []
    free = sorted(set(range(occupied[0], occupied[-1] + 1)) - set(occupied))
    gaps: list[tuple[int, int]] = []
    for x in free:
        if gaps and x == gaps[-1][1] + 1:
            gaps[-1] = (gaps[-1][0], x)
        else:
            gaps.append((x, x))
    return gaps


def _add_silkscreen(entities: list[Entity], direction: str, platform: str) -> list[Entity]:
    """Add font-rendered trash-block text and a name-tag label to a 1x4 rotator."""
    if platform != "1x4":
        return entities

    from shapez2_tools.font import CELL_HEIGHT, CELL_WIDTH, silkscreen

    label = _DIRECTION_LABELS[direction]
    gaps = _find_gaps(entities)

    text: list[Entity] = []
    chars = list(label)
    # Distribute characters across gaps, centering each in its gap.
    # More gaps than chars: use the rightmost gaps (leftmost gap stays empty).
    assigned = gaps[-len(chars):]
    y_span = 16 - 2  # usable rows y=2..17
    origin_y = 2 + (y_span + CELL_HEIGHT) // 2 - 1  # center vertically

    for ch, (gx_lo, gx_hi) in zip(chars, assigned):
        gap_w = gx_hi - gx_lo + 1
        origin_x = gx_lo + (gap_w - CELL_WIDTH) // 2
        text.extend(silkscreen(ch, origin_x=origin_x, origin_y=origin_y, layer=0, scale=1))

    return entities + text + [Entity(*_LABEL_POS, _LABEL_TYPE)]


def generate_rotator(direction: str, platform: str = "1x1") -> Blueprint:
    """Generate a rotator blueprint (180/cw/ccw) on a platform (1x1/1x4).

    Lifts the 180 quarter tile, swaps in the requested rotator variant, stamps
    it across the three floors and the platform's units, reuses a wrapper, and
    sets the island icon.
    """
    if direction not in ROTATORS:
        raise ValueError(f"Unknown direction {direction!r}; choose from {sorted(ROTATORS)}")
    if platform not in PLATFORM_SKELETON:
        raise ValueError(f"Unknown platform {platform!r}; choose from {sorted(PLATFORM_SKELETON)}")

    rotator_type, icon = ROTATORS[direction]
    tile = substitute(
        lift_tile(reference(_BASE_TILE)), {"RotatorHalfInternalVariant": rotator_type}
    )
    entities = _add_silkscreen(stamp_platform(tile, platform), direction, platform)
    bp = build_from_skeleton(reference(PLATFORM_SKELETON[platform]), entities)
    data_icon = list(bp.icon)
    data_icon[3] = icon
    bp.icon = data_icon
    return bp


# === Rendering (debug view) =================================================

# Belts are drawn structurally, not as flow arrows: a belt's `R` is its facing
# (input side), true flow is the opposite, and turn directions are not yet
# calibrated. So straight belts show their axis and turns/junctions show topology.
_STRAIGHT = {0: "─", 1: "│", 2: "─", 3: "│"}
_SYMBOLS = {  # substring -> glyph (machines and ports)
    "BeltPortReceiver": "I",
    "BeltPortSender": "O",
    "Rotator": "R",
    "Trash": "#",
    "Label": "L",
}


def all_entities(bp: Blueprint) -> list[Entity]:
    """Every building entity across the blueprint's platforms (incl. decoration)."""
    return [Entity.from_dict(d) for d in _platform_entries(bp)]


def _symbol(e: Entity) -> str:
    t = e.type
    if "Splitter" in t or "Merger" in t:
        return "Y"  # belt junction (split/merge) — made of belts, not a machine
    if t.startswith("Belt") and "Port" not in t:
        return "+" if "Left" in t else _STRAIGHT.get(e.rotation, "·")  # turn vs straight
    for key, glyph in _SYMBOLS.items():
        if key in t:
            return glyph
    return "?"


def render_text(bp: Blueprint, layer: int = 0) -> str:
    """Render one floor as an ASCII map (belts shown as flow arrows)."""
    cells = {(e.x, e.y): e for e in all_entities(bp) if e.layer == layer}
    if not cells:
        return f"(no entities on layer {layer})"
    xs = [x for x, _ in cells]
    ys = [y for _, y in cells]
    lines = []
    for y in range(max(ys), min(ys) - 1, -1):
        row = "".join(
            _symbol(cells[(x, y)]) if (x, y) in cells else "·" for x in range(min(xs), max(xs) + 1)
        )
        lines.append(f"{y:3} {row}")
    lines.append("    " + "".join(str(x % 10) for x in range(min(xs), max(xs) + 1)))
    return "\n".join(lines)
