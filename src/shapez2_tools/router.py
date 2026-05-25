"""Simple belt router for single-layer blueprint design."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import Enum


class Dir(Enum):
    """Cardinal directions."""

    N = (0, 1)
    E = (1, 0)
    S = (0, -1)
    W = (-1, 0)

    @property
    def opposite(self) -> Dir:
        return {Dir.N: Dir.S, Dir.S: Dir.N, Dir.E: Dir.W, Dir.W: Dir.E}[self]

    @property
    def dx(self) -> int:
        return self.value[0]

    @property
    def dy(self) -> int:
        return self.value[1]


@dataclass
class Building:
    """A building on the grid."""

    type: str
    x: int
    y: int
    rotation: int = 0  # 0=E, 1=S, 2=W, 3=N (output direction for belts)

    def output_dir(self) -> Dir:
        """Direction this building outputs to."""
        dirs = [Dir.E, Dir.S, Dir.W, Dir.N]
        return dirs[self.rotation]

    def input_dir(self) -> Dir:
        """Direction this building receives from."""
        return self.output_dir().opposite


@dataclass
class Grid:
    """2D grid for placing buildings."""

    width: int
    height: int
    cells: dict[tuple[int, int], Building] = field(default_factory=dict)

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def is_empty(self, x: int, y: int) -> bool:
        return (x, y) not in self.cells and self.in_bounds(x, y)

    def place(self, building: Building) -> bool:
        """Place a building if cell is empty."""
        if self.is_empty(building.x, building.y):
            self.cells[(building.x, building.y)] = building
            return True
        return False

    def get(self, x: int, y: int) -> Building | None:
        return self.cells.get((x, y))

    def neighbors(self, x: int, y: int) -> Iterator[tuple[int, int, Dir]]:
        """Yield (nx, ny, direction_to_neighbor) for valid neighbors."""
        for d in Dir:
            nx, ny = x + d.dx, y + d.dy
            if self.in_bounds(nx, ny):
                yield nx, ny, d

    def render(self) -> str:
        """Render grid as ASCII."""
        lines = []
        # Header
        header = "   " + "".join(f"{x % 10}" for x in range(self.width))
        lines.append(header)

        for y in range(self.height - 1, -1, -1):
            row = f"{y:2} "
            for x in range(self.width):
                b = self.get(x, y)
                if b is None:
                    row += "."
                elif b.type == "belt":
                    arrows = {0: "→", 1: "↓", 2: "←", 3: "↑"}
                    row += arrows.get(b.rotation, "-")
                elif b.type == "input":
                    row += "I"
                elif b.type == "output":
                    row += "O"
                elif b.type == "cutter":
                    row += "C"
                elif b.type == "splitter":
                    row += "<"
                elif b.type == "merger":
                    row += ">"
                else:
                    row += "?"
            lines.append(row)
        return "\n".join(lines)


def find_path(
    grid: Grid,
    start: tuple[int, int],
    end: tuple[int, int],
    start_dir: Dir | None = None,
) -> list[tuple[int, int, int]] | None:
    """
    Find a belt path from start to end using BFS.
    Returns list of (x, y, rotation) for belt placements, or None if no path.
    """
    from collections import deque

    # State: (x, y, incoming_direction)
    # We track incoming direction to ensure belt continuity
    queue: deque[tuple[int, int, Dir | None, list[tuple[int, int, Dir]]]] = deque()
    visited: set[tuple[int, int]] = set()

    queue.append((start[0], start[1], start_dir, []))
    visited.add(start)

    while queue:
        x, y, incoming, path = queue.popleft()

        # Check if we reached the end
        if (x, y) == end:
            # Convert path to belt placements
            result = []
            for px, py, out_dir in path:
                # Rotation: 0=E, 1=S, 2=W, 3=N
                rot = {Dir.E: 0, Dir.S: 1, Dir.W: 2, Dir.N: 3}[out_dir]
                result.append((px, py, rot))
            return result

        # Try each neighbor
        for nx, ny, direction in grid.neighbors(x, y):
            if (nx, ny) in visited:
                continue
            if not grid.is_empty(nx, ny) and (nx, ny) != end:
                continue

            visited.add((nx, ny))
            new_path = path + [(x, y, direction)]
            queue.append((nx, ny, direction, new_path))

    return None


def route_simple(
    grid: Grid,
    inputs: list[tuple[int, int]],
    outputs: list[tuple[int, int]],
    operations: list[tuple[str, int, int]],  # (type, x, y)
) -> bool:
    """
    Route belts from inputs through operations to outputs.
    Very simple: 1 input → 1 operation → 1 output for now.
    """
    if len(inputs) != 1 or len(outputs) != 1 or len(operations) != 1:
        raise ValueError("Simple router only handles 1→1→1 for now")

    inp = inputs[0]
    out = outputs[0]
    op_type, op_x, op_y = operations[0]

    # Place the operation
    op = Building(op_type, op_x, op_y, rotation=0)
    if not grid.place(op):
        return False

    # Route input to operation
    # Cutter takes input from West (rotation 0 = outputs East)
    op_input = (op_x - 1, op_y)
    path1 = find_path(grid, inp, op_input)
    if path1 is None:
        return False

    for x, y, rot in path1:
        grid.place(Building("belt", x, y, rot))

    # Route operation output to output
    op_output = (op_x + 1, op_y)  # Cutter outputs East
    path2 = find_path(grid, op_output, out)
    if path2 is None:
        return False

    for x, y, rot in path2:
        grid.place(Building("belt", x, y, rot))

    return True


def load_platform_data() -> dict:
    """Load platform definitions from data file."""
    import json
    from pathlib import Path

    data_file = Path(__file__).parent.parent.parent / "data" / "platforms.json"
    if data_file.exists():
        return json.loads(data_file.read_text())
    return {}


def create_platform(
    layout: str = "Foundation_1x1",
) -> tuple[Grid, list[tuple[int, int]], list[tuple[int, int]]]:
    """
    Create a grid for a given platform layout.
    Returns (grid, input_positions, output_positions).
    """
    platforms = load_platform_data()

    if layout not in platforms:
        raise ValueError(f"Unknown layout: {layout}. Available: {list(platforms.keys())}")

    p = platforms[layout]
    grid = Grid(p["grid_size"][0], p["grid_size"][1])

    # Generate port positions
    inputs = []
    outputs = []

    if "port_x_range" in p and "input_y" in p and "output_y" in p:
        x_min, x_max = p["port_x_range"]
        for x in range(x_min, x_max + 1):
            inputs.append((x, p["input_y"]))
            outputs.append((x, p["output_y"]))

    for x, y in inputs:
        grid.place(Building("input", x, y, rotation=1))

    for x, y in outputs:
        grid.place(Building("output", x, y, rotation=1))

    return grid, inputs, outputs


def create_quarter_platform() -> tuple[Grid, list[tuple[int, int]], list[tuple[int, int]]]:
    """Create a Foundation_1x1 (quarter) platform."""
    return create_platform("Foundation_1x1")


def route_parallel_ops(
    grid: Grid,
    inputs: list[tuple[int, int]],
    outputs: list[tuple[int, int]],
    op_type: str,
    op_y: int,
) -> bool:
    """
    Route N parallel operations: each input → one op → corresponding output.
    Places operations at given Y level.
    """
    if len(inputs) != len(outputs):
        raise ValueError("Input/output count mismatch")

    n = len(inputs)
    success = True

    for i in range(n):
        inp_x, inp_y = inputs[i]
        out_x, out_y = outputs[i]

        # Place operation aligned with input X
        op_x = inp_x
        op = Building(op_type, op_x, op_y, rotation=1)  # Output facing South
        if not grid.place(op):
            success = False
            continue

        # Route: input → op (going South)
        path1 = find_path(grid, (inp_x, inp_y - 1), (op_x, op_y + 1))
        if path1:
            for x, y, rot in path1:
                grid.place(Building("belt", x, y, rot))

        # Route: op → output (going South)
        path2 = find_path(grid, (op_x, op_y - 1), (out_x, out_y + 1))
        if path2:
            for x, y, rot in path2:
                grid.place(Building("belt", x, y, rot))

    return success


def demo():
    """Demo: 4 parallel cutters on a quarter platform."""
    grid, inputs, outputs = create_quarter_platform()

    # Place 4 cutters at Y=10 (middle of platform)
    route_parallel_ops(grid, inputs, outputs, "cutter", op_y=10)

    print("Quarter platform with 4 parallel cutters:")
    print(grid.render())
    return grid


def demo_with_split():
    """Demo: 1 input → split to 3 cutters → merge to 1 output."""
    grid = Grid(12, 16)

    # Single input at top center, single output at bottom center
    inp = (6, 15)
    out = (6, 0)
    grid.place(Building("input", *inp, rotation=1))
    grid.place(Building("output", *out, rotation=1))

    # Splitter below input
    grid.place(Building("splitter", 6, 13, rotation=1))

    # 3 cutters
    for i, x in enumerate([4, 6, 8]):
        grid.place(Building("cutter", x, 8, rotation=1))

    # Merger above output
    grid.place(Building("merger", 6, 2, rotation=1))

    # Route: input → splitter
    path = find_path(grid, (6, 14), (6, 14))
    if path:
        for x, y, rot in path:
            grid.place(Building("belt", x, y, rot))

    # Route: splitter outputs → cutters
    for i, cx in enumerate([4, 6, 8]):
        # Splitter has 3 outputs, we'll manually route
        pass  # Complex - need smarter routing

    print("Split/merge demo (partial):")
    print(grid.render())
    return grid


if __name__ == "__main__":
    demo()
