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
class Port:
    """An input or output port on a building."""

    rel_x: int  # relative to building origin
    rel_y: int
    direction: Dir  # direction items flow (into for input, out of for output)
    layer: int = 0  # z-layer (0, 1, or 2)
    mirror_swap: int | None = None  # if set, swap with this port index when mirrored


@dataclass
class BuildingDef:
    """Definition of a building type's footprint and ports."""

    name: str
    cells: list[tuple[int, int]]  # cells occupied at R=0 (relative to origin)
    inputs: list[Port]
    outputs: list[Port]

    def rotated_cells(self, rotation: int) -> list[tuple[int, int]]:
        """Get cells after applying rotation."""
        result = []
        for x, y in self.cells:
            for _ in range(rotation):
                x, y = y, -x  # 90° CW rotation
            result.append((x, y))
        return result

    def rotated_dir(self, d: Dir, rotation: int) -> Dir:
        """Rotate a direction."""
        dirs = [Dir.E, Dir.S, Dir.W, Dir.N]
        idx = dirs.index(d)
        return dirs[(idx + rotation) % 4]

    def get_port_position(
        self, port: Port, bx: int, by: int, rotation: int, mirrored: bool
    ) -> tuple[int, int, Dir, int]:
        """Get absolute position and direction of a port.

        Returns (x, y, direction, layer).
        """
        rx, ry = port.rel_x, port.rel_y

        # Apply mirroring (flip relative to building center)
        if mirrored:
            # Find the extent of the building in Y (before rotation)
            max_y = max(c[1] for c in self.cells)
            # Flip Y relative to center: ry -> max_y - ry
            ry = max_y - ry

        # Apply rotation
        for _ in range(rotation):
            rx, ry = ry, -rx

        direction = self.rotated_dir(port.direction, rotation)

        return (bx + rx, by + ry, direction, port.layer)


# Building definitions at R=0 (output East, input West)
# Coordinates: origin at (0,0), +Y is North
BUILDING_DEFS: dict[str, BuildingDef] = {}


def _register(b: BuildingDef) -> BuildingDef:
    BUILDING_DEFS[b.name] = b
    return b


# === 1x1 Buildings ===

_register(
    BuildingDef(
        name="Rotator",
        cells=[(0, 0)],
        inputs=[Port(0, 0, Dir.W)],
        outputs=[Port(0, 0, Dir.E)],
    )
)

_register(
    BuildingDef(
        name="RotatorCCW",
        cells=[(0, 0)],
        inputs=[Port(0, 0, Dir.W)],
        outputs=[Port(0, 0, Dir.E)],
    )
)

_register(
    BuildingDef(
        name="RotatorHalf",
        cells=[(0, 0)],
        inputs=[Port(0, 0, Dir.W)],
        outputs=[Port(0, 0, Dir.E)],
    )
)

_register(
    BuildingDef(
        name="HalfDestroyer",
        cells=[(0, 0)],
        inputs=[Port(0, 0, Dir.W)],
        outputs=[Port(0, 0, Dir.E)],
    )
)

_register(
    BuildingDef(
        name="PinPusher",
        cells=[(0, 0)],
        inputs=[Port(0, 0, Dir.W)],
        outputs=[Port(0, 0, Dir.E)],
    )
)

_register(
    BuildingDef(
        name="Trash",
        cells=[(0, 0)],
        inputs=[Port(0, 0, Dir.W)],
        outputs=[],  # no output
    )
)

# === 1x2 Buildings ===

_register(
    BuildingDef(
        name="Cutter",
        cells=[(0, 0), (0, 1)],  # 1 wide, 2 tall
        inputs=[Port(0, 0, Dir.W)],  # input on cell (0,0); mirrored moves to (0,1)
        outputs=[
            Port(0, 0, Dir.E),  # one half
            Port(0, 1, Dir.E),  # other half
        ],
    )
)

_register(
    BuildingDef(
        name="Swapper",
        cells=[(0, 0), (0, 1)],
        inputs=[
            Port(0, 0, Dir.W),  # shape A input
            Port(0, 1, Dir.W),  # shape B input
        ],
        outputs=[
            Port(0, 0, Dir.E),  # shape A with B's half
            Port(0, 1, Dir.E),  # shape B with A's half
        ],
    )
)

# === Multi-layer Buildings (1x1 footprint, spans Z) ===

_register(
    BuildingDef(
        name="StackerStraight",
        cells=[(0, 0)],
        inputs=[
            Port(0, 0, Dir.S, layer=0),  # bottom layer input
            Port(0, 0, Dir.S, layer=1),  # top layer input
        ],
        outputs=[
            Port(0, 0, Dir.N, layer=0),  # stacked output, straight through
        ],
    )
)

_register(
    BuildingDef(
        name="StackerBent",
        cells=[(0, 0)],
        inputs=[
            Port(0, 0, Dir.S, layer=0),  # bottom layer input
            Port(0, 0, Dir.S, layer=1),  # top layer input
        ],
        outputs=[
            Port(0, 0, Dir.E, layer=0),  # stacked output, bent 90° (helicity)
        ],
    )
)


@dataclass
class Building:
    """A placed building on the grid."""

    type: str
    x: int
    y: int
    rotation: int = 0  # 0=E, 1=S, 2=W, 3=N (output direction for belts)
    mirrored: bool = False
    layer: int = 0  # z-layer this building is on

    def output_dir(self) -> Dir:
        """Direction this building outputs to (for simple 1x1 buildings)."""
        dirs = [Dir.E, Dir.S, Dir.W, Dir.N]
        return dirs[self.rotation]

    def input_dir(self) -> Dir:
        """Direction this building receives from (for simple 1x1 buildings)."""
        return self.output_dir().opposite

    def get_definition(self) -> BuildingDef | None:
        """Get the building definition for this type."""
        # Map blueprint type names to our definitions
        type_map = {
            "belt": None,  # belts don't have a BuildingDef
            "input": None,
            "output": None,
            "cutter": "Cutter",
            "rotator": "Rotator",
            "rotatorccw": "RotatorCCW",
            "rotatorhalf": "RotatorHalf",
            "stacker": "StackerBent",
            "stackerstraight": "StackerStraight",
            "swapper": "Swapper",
            "trash": "Trash",
            "pinpusher": "PinPusher",
            "halfdestroyer": "HalfDestroyer",
        }
        def_name = type_map.get(self.type.lower())
        if def_name:
            return BUILDING_DEFS.get(def_name)
        return None

    def get_cells(self) -> list[tuple[int, int]]:
        """Get all cells this building occupies.

        Mirroring does NOT affect the footprint - only which cell has ports.
        """
        defn = self.get_definition()
        if defn is None:
            return [(self.x, self.y)]
        cells = defn.rotated_cells(self.rotation)
        return [(self.x + dx, self.y + dy) for dx, dy in cells]

    def get_input_ports(self) -> list[tuple[int, int, Dir, int]]:
        """Get input port positions as (x, y, from_direction, layer)."""
        defn = self.get_definition()
        if defn is None:
            # Default for simple buildings
            return [(self.x, self.y, self.input_dir(), self.layer)]
        result = []
        for port in defn.inputs:
            pos = defn.get_port_position(port, self.x, self.y, self.rotation, self.mirrored)
            result.append(pos)
        return result

    def get_output_ports(self) -> list[tuple[int, int, Dir, int]]:
        """Get output port positions as (x, y, to_direction, layer)."""
        defn = self.get_definition()
        if defn is None:
            return [(self.x, self.y, self.output_dir(), self.layer)]
        result = []
        for port in defn.outputs:
            pos = defn.get_port_position(port, self.x, self.y, self.rotation, self.mirrored)
            result.append(pos)
        return result


@dataclass
class Grid:
    """2D grid for placing buildings."""

    width: int
    height: int
    cells: dict[tuple[int, int], Building] = field(default_factory=dict)
    valid_cells: set[tuple[int, int]] | None = None  # None = all cells valid

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def is_valid(self, x: int, y: int) -> bool:
        """Check if cell is within bounds and valid for placement."""
        if not self.in_bounds(x, y):
            return False
        if self.valid_cells is None:
            return True
        return (x, y) in self.valid_cells

    def is_empty(self, x: int, y: int) -> bool:
        return (x, y) not in self.cells and self.is_valid(x, y)

    def place(self, building: Building) -> bool:
        """Place a building if cell is empty and valid."""
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
            if self.is_valid(nx, ny):
                yield nx, ny, d

    def set_valid_from_shape(self, shape: list[str], origin_x: int = 0, origin_y: int = 0) -> None:
        """
        Set valid cells from an ASCII shape mask.
        '#' = valid, '.' = invalid
        Shape is top-to-bottom (first row = highest Y).
        """
        self.valid_cells = set()
        for row_idx, row in enumerate(shape):
            y = origin_y + (len(shape) - 1 - row_idx)  # Flip Y so first row is top
            for col_idx, char in enumerate(row):
                x = origin_x + col_idx
                if char == "#":
                    self.valid_cells.add((x, y))

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

    # Handle irregular shapes (L, T, Cross, etc.)
    if "shape_units" in p:
        unit_size = p.get("unit_size", 20)
        origin_x, origin_y = p.get("shape_origin", [0, 0])
        shape_units = p["shape_units"]

        # Build valid_cells from unit grid
        grid.valid_cells = set()
        for row_idx, row in enumerate(shape_units):
            # First row in shape_units is top (highest Y)
            unit_y = len(shape_units) - 1 - row_idx
            for col_idx, char in enumerate(row):
                if char == "#":
                    unit_x = col_idx
                    # Expand unit to tiles
                    tile_x_start = origin_x + unit_x * unit_size
                    tile_y_start = origin_y + unit_y * unit_size
                    for tx in range(tile_x_start, tile_x_start + unit_size):
                        for ty in range(tile_y_start, tile_y_start + unit_size):
                            grid.valid_cells.add((tx, ty))

    # Generate port positions (simple case: top/bottom edges)
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
