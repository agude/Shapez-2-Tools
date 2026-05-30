"""Minimal Shapez 2 shape model and the absolute machine operations (Rung 2).

A shape is four quadrants in clockwise order from top-right — (NE, SE, SW, NW) —
each a 2-char part code (e.g. ``"Ru"``) or ``None`` for empty. Single layer only
for now; colors, layers, crystals, and pins are not modelled yet.

Operations are **absolute** (world-fixed): cut / half-destroy / swap act on the
fixed west/east halves regardless of any building rotation, and only rotation
re-orients a shape (see ``docs/machines.md``). The quadrant order is the standard
Shapez reading order; the *behaviour* is pinned by the tests, including the
diagonal-extractor trick, so the labels can be re-checked without changing logic.
"""

from __future__ import annotations

from dataclasses import dataclass

# Quadrant indices, clockwise from top-right.
NE, SE, SW, NW = 0, 1, 2, 3
WEST = (SW, NW)
EAST = (NE, SE)
NORTH = (NE, NW)
SOUTH = (SE, SW)

Quad = str | None  # 2-char part code, or None for empty


@dataclass(frozen=True)
class Shape:
    """Four quadrants: (NE, SE, SW, NW)."""

    quads: tuple[Quad, Quad, Quad, Quad]

    @classmethod
    def parse(cls, code: str) -> Shape:
        """Parse a 8-char single-layer code; ``--`` is an empty quadrant."""
        parts = [code[i : i + 2] for i in range(0, len(code), 2)]
        if len(parts) != 4:
            raise ValueError(f"expected 4 quadrants, got {len(parts)} from {code!r}")
        return cls(tuple(None if p == "--" else p for p in parts))

    def __str__(self) -> str:
        return "".join(q if q else "--" for q in self.quads)

    def _replace(self, **at: Quad) -> Shape:
        q = list(self.quads)
        for name, value in at.items():
            q[{"NE": NE, "SE": SE, "SW": SW, "NW": NW}[name]] = value
        return Shape(tuple(q))


def rotate_cw(s: Shape) -> Shape:
    """Rotate 90° clockwise (each part moves one quadrant clockwise)."""
    a, b, c, d = s.quads  # NE, SE, SW, NW
    return Shape((d, a, b, c))


def rotate_ccw(s: Shape) -> Shape:
    """Rotate 90° counter-clockwise."""
    a, b, c, d = s.quads
    return Shape((b, c, d, a))


def rotate_180(s: Shape) -> Shape:
    a, b, c, d = s.quads
    return Shape((c, d, a, b))


def _keep(s: Shape, indices: tuple[int, ...]) -> Shape:
    return Shape(tuple(q if i in indices else None for i, q in enumerate(s.quads)))


def cut(s: Shape) -> tuple[Shape, Shape]:
    """Cut vertically: returns (east half = main, west half = secondary)."""
    return _keep(s, EAST), _keep(s, WEST)


def half_destroy(s: Shape) -> Shape:
    """Destroy the west half, keep the east half (the Half Destroyer)."""
    return _keep(s, EAST)


def swap_west(a: Shape, b: Shape) -> tuple[Shape, Shape]:
    """Swap the two shapes' west halves (the Swapper), empties included."""
    out_a = Shape((a.quads[NE], a.quads[SE], b.quads[SW], b.quads[NW]))
    out_b = Shape((b.quads[NE], b.quads[SE], a.quads[SW], a.quads[NW]))
    return out_a, out_b
