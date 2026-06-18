"""Minimal Shapez 2 shape model and the absolute machine operations (Rung 2).

A shape is one or more layers, each with four quadrants in clockwise order from
top-right — (NE, SE, SW, NW) — each a 2-char part code (e.g. ``"Ru"``) or
``None`` for empty. Multi-layer codes separate layers with ``:``.  Colors,
crystals, and pins are not modelled yet.

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
Layer = tuple[Quad, Quad, Quad, Quad]

_EMPTY: Layer = (None, None, None, None)

# Orthogonal adjacency — diagonal pairs (NE↔SW, NW↔SE) are NOT connected.
_ADJ: dict[int, tuple[int, int]] = {
    NE: (SE, NW),
    SE: (NE, SW),
    SW: (SE, NW),
    NW: (SW, NE),
}


@dataclass(frozen=True)
class Shape:
    """One or more layers, each with four quadrants: (NE, SE, SW, NW)."""

    quads: Layer
    upper: tuple[Layer, ...] = ()

    @property
    def layers(self) -> tuple[Layer, ...]:
        return (self.quads,) + self.upper

    @property
    def num_layers(self) -> int:
        return 1 + len(self.upper)

    @classmethod
    def parse(cls, code: str) -> Shape:
        """Parse a shape code; layers separated by ``:``, ``--`` = empty quad."""
        layer_codes = code.split(":")
        parsed: list[Layer] = []
        for lc in layer_codes:
            parts = [lc[i : i + 2] for i in range(0, len(lc), 2)]
            if len(parts) != 4:
                raise ValueError(f"expected 4 quadrants per layer, got {len(parts)}")
            parsed.append(tuple(None if p == "--" else p for p in parts))
        return cls(parsed[0], upper=tuple(parsed[1:]))

    def __str__(self) -> str:
        return ":".join("".join(q if q else "--" for q in layer) for layer in self.layers)

    def _replace(self, **at: Quad) -> Shape:
        q = list(self.quads)
        for name, value in at.items():
            q[{"NE": NE, "SE": SE, "SW": SW, "NW": NW}[name]] = value
        return Shape(tuple(q), upper=self.upper)


# ── helpers ──────────────────────────────────────────────────────────────────


def _from_layers(layers: list[Layer]) -> Shape:
    """Construct a Shape, stripping empty top layers."""
    while len(layers) > 1 and all(q is None for q in layers[-1]):
        layers.pop()
    return Shape(layers[0], upper=tuple(layers[1:]))


def _map_layers(s: Shape, fn) -> Shape:
    return _from_layers([fn(ly) for ly in s.layers])


# ── single-layer ops (applied per layer for multi-layer shapes) ──────────────


def rotate_cw(s: Shape) -> Shape:
    """Rotate 90° clockwise (each part moves one quadrant clockwise)."""
    return _map_layers(s, lambda ly: (ly[NW], ly[NE], ly[SE], ly[SW]))


def rotate_ccw(s: Shape) -> Shape:
    """Rotate 90° counter-clockwise."""
    return _map_layers(s, lambda ly: (ly[SE], ly[SW], ly[NW], ly[NE]))


def rotate_180(s: Shape) -> Shape:
    return _map_layers(s, lambda ly: (ly[SW], ly[NW], ly[NE], ly[SE]))


def _keep(s: Shape, indices: tuple[int, ...]) -> Shape:
    return _map_layers(s, lambda ly: tuple(q if i in indices else None for i, q in enumerate(ly)))


def cut(s: Shape) -> tuple[Shape, Shape]:
    """Cut vertically: returns (east half = main, west half = secondary)."""
    return _keep(s, EAST), _keep(s, WEST)


def half_destroy(s: Shape) -> Shape:
    """Destroy the west half, keep the east half (the Half Destroyer)."""
    return _keep(s, EAST)


def swap_west(a: Shape, b: Shape) -> tuple[Shape, Shape]:
    """Swap the two shapes' west halves (the Swapper), empties included."""
    n = max(a.num_layers, b.num_layers)
    al = a.layers + (_EMPTY,) * (n - a.num_layers)
    bl = b.layers + (_EMPTY,) * (n - b.num_layers)
    oa: list[Layer] = []
    ob: list[Layer] = []
    for la, lb in zip(al, bl):
        oa.append((la[NE], la[SE], lb[SW], lb[NW]))
        ob.append((lb[NE], lb[SE], la[SW], la[NW]))
    return _from_layers(oa), _from_layers(ob)


# ── gravity & stacking ──────────────────────────────────────────────────────


def _find_groups(layer: Layer) -> list[frozenset[int]]:
    """Connected components of filled quadrants (orthogonal adjacency)."""
    filled = {i for i, q in enumerate(layer) if q is not None}
    visited: set[int] = set()
    groups: list[frozenset[int]] = []
    for start in sorted(filled):
        if start in visited:
            continue
        group: set[int] = set()
        stack_: list[int] = [start]
        while stack_:
            q = stack_.pop()
            if q in visited:
                continue
            visited.add(q)
            group.add(q)
            for adj in _ADJ[q]:
                if adj in filled and adj not in visited:
                    stack_.append(adj)
        groups.append(frozenset(group))
    return groups


MAX_LAYERS = 4


def _apply_gravity(grid: list[list[Quad]]) -> list[Layer]:
    """Drop unsupported groups layer-by-layer (bottom-to-top, in place)."""
    for li in range(1, len(grid)):
        for group in _find_groups(tuple(grid[li])):
            if any(grid[li - 1][q] is not None for q in group):
                continue
            target = li
            while target > 0 and not any(grid[target - 1][q] is not None for q in group):
                target -= 1
            if target != li:
                for q in group:
                    grid[target][q] = grid[li][q]
                    grid[li][q] = None
    while len(grid) > 1 and all(q is None for q in grid[-1]):
        grid.pop()
    return [tuple(row) for row in grid]


def stack(bottom: Shape, top: Shape) -> Shape:
    """Stack *top* onto *bottom* with Shapez 2 gravity rules.

    Places the top layers above the bottom layers with one empty gap layer,
    applies gravity (connected groups fall), then truncates to MAX_LAYERS.
    """
    grid: list[list[Quad]] = [list(ly) for ly in bottom.layers]
    grid.append(list(_EMPTY))
    grid.extend(list(ly) for ly in top.layers)
    settled = _apply_gravity(grid)[:MAX_LAYERS]
    while len(settled) > 1 and all(q is None for q in settled[-1]):
        settled.pop()
    return Shape(settled[0], upper=tuple(settled[1:]))
