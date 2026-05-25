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


def render_svg(
    grid: Grid,
    cell_size: int = 20,
    show_ports: bool = True,
    path: list[tuple[int, int, int]] | None = None,
) -> str:
    """Render grid as SVG.

    Args:
        grid: The grid to render
        cell_size: Size of each cell in pixels
        show_ports: Whether to show input/output port indicators
        path: Optional path to highlight [(x, y, rotation), ...]

    Returns:
        SVG string
    """
    width = grid.width * cell_size
    height = grid.height * cell_size

    # Colors for different building types
    colors = {
        "belt": "#4a9eff",
        "input": "#4ade80",
        "output": "#f87171",
        "cutter": "#fbbf24",
        "rotator": "#a78bfa",
        "rotatorccw": "#a78bfa",
        "rotatorhalf": "#a78bfa",
        "stacker": "#fb923c",
        "stackerstraight": "#fb923c",
        "swapper": "#f472b6",
        "trash": "#6b7280",
        "splitter": "#22d3d8",
        "merger": "#22d3d8",
    }

    # Direction arrows (as SVG path data, pointing in direction)
    arrow_paths = {
        Dir.N: "M 0,-4 L 3,2 L -3,2 Z",
        Dir.E: "M 4,0 L -2,3 L -2,-3 Z",
        Dir.S: "M 0,4 L 3,-2 L -3,-2 Z",
        Dir.W: "M -4,0 L 2,3 L 2,-3 Z",
    }

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">',
        '<style>',
        '  .cell { stroke: #333; stroke-width: 0.5; }',
        '  .valid { fill: #1a1a2e; }',
        '  .invalid { fill: #0a0a0a; }',
        '  .building { stroke: #000; stroke-width: 1; }',
        '  .arrow { fill: #fff; }',
        '  .path { fill: #4a9eff; opacity: 0.8; }',
        '  .port-in { fill: #4ade80; }',
        '  .port-out { fill: #f87171; }',
        '</style>',
    ]

    # Draw grid cells
    for y in range(grid.height):
        for x in range(grid.width):
            # SVG Y is inverted (0 at top)
            svg_y = (grid.height - 1 - y) * cell_size
            svg_x = x * cell_size
            valid = grid.is_valid(x, y)
            css_class = "valid" if valid else "invalid"
            lines.append(
                f'<rect x="{svg_x}" y="{svg_y}" width="{cell_size}" '
                f'height="{cell_size}" class="cell {css_class}"/>'
            )

    # Draw path if provided
    if path:
        for x, y, rot in path:
            svg_y = (grid.height - 1 - y) * cell_size
            svg_x = x * cell_size
            lines.append(
                f'<rect x="{svg_x}" y="{svg_y}" width="{cell_size}" '
                f'height="{cell_size}" class="path"/>'
            )

    # Draw buildings
    for (x, y), building in grid.cells.items():
        svg_y = (grid.height - 1 - y) * cell_size
        svg_x = x * cell_size
        color = colors.get(building.type.lower(), "#888")
        cx = svg_x + cell_size // 2
        cy = svg_y + cell_size // 2

        # Building rectangle
        lines.append(
            f'<rect x="{svg_x + 1}" y="{svg_y + 1}" '
            f'width="{cell_size - 2}" height="{cell_size - 2}" '
            f'fill="{color}" class="building"/>'
        )

        # Direction arrow
        out_dir = building.output_dir()
        arrow = arrow_paths.get(out_dir, "")
        if arrow:
            lines.append(
                f'<path d="{arrow}" transform="translate({cx},{cy})" class="arrow"/>'
            )

        # Port indicators
        if show_ports and building.get_definition():
            for px, py, d, _layer in building.get_input_ports():
                psvg_y = (grid.height - 1 - py) * cell_size + cell_size // 2
                psvg_x = px * cell_size + cell_size // 2
                # Offset toward the edge
                psvg_x += d.dx * (cell_size // 3)
                psvg_y -= d.dy * (cell_size // 3)  # SVG Y inverted
                lines.append(
                    f'<circle cx="{psvg_x}" cy="{psvg_y}" r="3" class="port-in"/>'
                )
            for px, py, d, _layer in building.get_output_ports():
                psvg_y = (grid.height - 1 - py) * cell_size + cell_size // 2
                psvg_x = px * cell_size + cell_size // 2
                psvg_x += d.dx * (cell_size // 3)
                psvg_y -= d.dy * (cell_size // 3)
                lines.append(
                    f'<circle cx="{psvg_x}" cy="{psvg_y}" r="3" class="port-out"/>'
                )

    lines.append("</svg>")
    return "\n".join(lines)


def find_path(
    grid: Grid,
    start: tuple[int, int],
    end: tuple[int, int],
    start_dir: Dir | None = None,
    end_dir: Dir | None = None,
    turn_cost: float = 0.5,
) -> list[tuple[int, int, int]] | None:
    """
    Find a belt path from start to end using A*.

    Args:
        grid: The grid to route on
        start: Starting cell (x, y)
        end: Ending cell (x, y)
        start_dir: If set, the first belt must point this direction
        end_dir: If set, the final belt must point this direction
        turn_cost: Extra cost for each turn (default 0.5)

    Returns:
        List of (x, y, rotation) for belt placements, or None if no path.
    """
    import heapq
    from itertools import count

    dir_to_rot = {Dir.E: 0, Dir.S: 1, Dir.W: 2, Dir.N: 3}
    counter = count()  # Tiebreaker for heap

    def heuristic(x: int, y: int) -> float:
        return abs(x - end[0]) + abs(y - end[1])

    # State: (x, y, last_direction)
    # last_direction is the direction we moved TO reach this cell
    # Priority queue: (cost + heuristic, counter, cost, x, y, last_dir, path)
    # Counter breaks ties to avoid comparing Dir enums

    start_states = []

    if start_dir is not None:
        # Must start in this direction
        entry = (heuristic(*start), next(counter), 0.0, start[0], start[1], start_dir, [])
        start_states.append(entry)
    else:
        # Can start in any direction - will be determined by first move
        entry = (heuristic(*start), next(counter), 0.0, start[0], start[1], None, [])
        start_states.append(entry)

    heap = start_states
    heapq.heapify(heap)

    # visited: (x, y, direction) -> best cost seen
    visited: dict[tuple[int, int, Dir | None], float] = {}

    while heap:
        _, _, cost, x, y, last_dir, path = heapq.heappop(heap)

        # Check if we reached the end with correct direction
        if (x, y) == end:
            if end_dir is None or (path and path[-1][2] == end_dir):
                # Convert path to belt placements
                result = []
                for px, py, out_dir in path:
                    rot = dir_to_rot[out_dir]
                    result.append((px, py, rot))
                return result
            elif end_dir is not None and not path:
                # We started at the end, no path needed
                # but we can't satisfy end_dir constraint
                continue

        state = (x, y, last_dir)
        if state in visited and visited[state] <= cost:
            continue
        visited[state] = cost

        # Try each neighbor
        for nx, ny, direction in grid.neighbors(x, y):
            if not grid.is_empty(nx, ny) and (nx, ny) != end:
                continue

            # Calculate move cost
            move_cost = 1.0
            if last_dir is not None and direction != last_dir:
                move_cost += turn_cost  # Turn penalty

            new_cost = cost + move_cost
            new_path = path + [(x, y, direction)]

            # Check if this direction satisfies end constraint
            if (nx, ny) == end and end_dir is not None and direction != end_dir:
                continue  # Can't reach end with wrong direction

            new_state = (nx, ny, direction)
            if new_state in visited and visited[new_state] <= new_cost:
                continue

            priority = new_cost + heuristic(nx, ny)
            heapq.heappush(heap, (priority, next(counter), new_cost, nx, ny, direction, new_path))

    return None


def route_to_port(
    grid: Grid,
    start: tuple[int, int],
    port: tuple[int, int, Dir, int],
    start_dir: Dir | None = None,
) -> list[tuple[int, int, int]] | None:
    """
    Route from start to a building's input port.

    The path includes belts up to and including the cell that feeds the port.

    Args:
        grid: The grid to route on
        start: Starting cell (x, y)
        port: Input port (x, y, from_direction, layer)
        start_dir: If set, the first belt must point this direction

    Returns:
        List of (x, y, rotation) for belt placements, or None if no path.
    """
    port_x, port_y, from_dir, _layer = port

    # Route TO the port cell itself (which is occupied by the building)
    # The path will include belts up to the cell before the port
    # The end_dir ensures the last belt points toward the port
    end_dir = from_dir.opposite  # Belt points toward port

    return find_path(grid, start, (port_x, port_y), start_dir=start_dir, end_dir=end_dir)


def route_from_port(
    grid: Grid,
    port: tuple[int, int, Dir, int],
    end: tuple[int, int],
    end_dir: Dir | None = None,
) -> list[tuple[int, int, int]] | None:
    """
    Route from a building's output port to end.

    The path starts at the cell AFTER the port, receiving from it.

    Args:
        grid: The grid to route on
        port: Output port (x, y, to_direction, layer)
        end: Ending cell (x, y)
        end_dir: If set, the final belt must point this direction

    Returns:
        List of (x, y, rotation) for belt placements, or None if no path.
    """
    port_x, port_y, to_dir, _layer = port

    # The belt receives from the port, so starts adjacent in the output direction
    start_x = port_x + to_dir.dx
    start_y = port_y + to_dir.dy
    start_dir = to_dir  # Belt continues in same direction as output

    return find_path(grid, (start_x, start_y), end, start_dir=start_dir, end_dir=end_dir)


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


def demo_svg():
    """Demo: render a grid with buildings and port-based routing to SVG."""
    from pathlib import Path

    grid = Grid(15, 12)

    # Place buildings
    rotator = Building("rotator", 5, 6, rotation=0)  # R=0: input W, output E
    grid.place(rotator)

    cutter = Building("cutter", 10, 6, rotation=0)
    # Cutter is 1x2, mark both cells
    for cell in cutter.get_cells():
        grid.cells[cell] = cutter

    # Route from (0, 6) to rotator's input port
    input_port = rotator.get_input_ports()[0]
    path1 = route_to_port(grid, (0, 6), input_port)

    # Route from rotator's output to cutter's input
    output_port = rotator.get_output_ports()[0]
    cutter_input = cutter.get_input_ports()[0]
    path2 = route_from_port(grid, output_port, (cutter_input[0], cutter_input[1]))

    # Place belts
    all_paths = []
    if path1:
        for x, y, rot in path1:
            grid.place(Building("belt", x, y, rot))
        all_paths.extend(path1)
    if path2:
        for x, y, rot in path2:
            grid.place(Building("belt", x, y, rot))
        all_paths.extend(path2)

    svg = render_svg(grid, cell_size=30, show_ports=True, path=all_paths)
    out_path = Path("/tmp/router_demo.svg")
    out_path.write_text(svg)
    print(f"SVG written to {out_path}")
    print(f"Rotator input port: {input_port}")
    print(f"Rotator output port: {output_port}")
    print(f"Cutter input port: {cutter_input}")
    return grid


if __name__ == "__main__":
    demo_svg()
