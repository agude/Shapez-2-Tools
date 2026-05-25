"""Tests for router module."""

import pytest

from shapez2_tools.router import (
    BUILDING_DEFS,
    Building,
    Dir,
    Grid,
    create_platform,
    find_path,
    load_platform_data,
)


class TestDir:
    def test_opposite(self):
        assert Dir.N.opposite == Dir.S
        assert Dir.S.opposite == Dir.N
        assert Dir.E.opposite == Dir.W
        assert Dir.W.opposite == Dir.E

    def test_dx_dy(self):
        assert Dir.N.dx == 0 and Dir.N.dy == 1
        assert Dir.E.dx == 1 and Dir.E.dy == 0
        assert Dir.S.dx == 0 and Dir.S.dy == -1
        assert Dir.W.dx == -1 and Dir.W.dy == 0


class TestBuilding:
    def test_output_dir(self):
        b = Building("belt", 0, 0, rotation=0)
        assert b.output_dir() == Dir.E

        b = Building("belt", 0, 0, rotation=1)
        assert b.output_dir() == Dir.S

    def test_input_dir(self):
        b = Building("belt", 0, 0, rotation=0)
        assert b.input_dir() == Dir.W

    def test_rotator_ports(self):
        # Rotator at origin, R=0 (output East)
        b = Building("rotator", 5, 5, rotation=0)
        inputs = b.get_input_ports()
        outputs = b.get_output_ports()

        assert len(inputs) == 1
        assert inputs[0] == (5, 5, Dir.W, 0)  # input from West
        assert len(outputs) == 1
        assert outputs[0] == (5, 5, Dir.E, 0)  # output to East

    def test_rotator_rotated(self):
        # Rotator at origin, R=1 (output South)
        b = Building("rotator", 5, 5, rotation=1)
        inputs = b.get_input_ports()
        outputs = b.get_output_ports()

        assert inputs[0][2] == Dir.N  # input from North
        assert outputs[0][2] == Dir.S  # output to South

    def test_cutter_cells(self):
        # Cutter is 1x2
        b = Building("cutter", 5, 5, rotation=0)
        cells = b.get_cells()
        assert len(cells) == 2
        assert (5, 5) in cells
        assert (5, 6) in cells

    def test_cutter_ports(self):
        # Cutter R=0: input from West, outputs to East
        b = Building("cutter", 5, 5, rotation=0)
        inputs = b.get_input_ports()
        outputs = b.get_output_ports()

        assert len(inputs) == 1
        assert inputs[0][2] == Dir.W  # input from West
        assert len(outputs) == 2  # two output halves
        assert all(o[2] == Dir.E for o in outputs)  # both output East

    def test_cutter_rotated(self):
        # Cutter R=1 (output South): becomes 2x1
        b = Building("cutter", 5, 5, rotation=1)
        cells = b.get_cells()
        assert len(cells) == 2
        # After 90° rotation, (0,0)->(0,0), (0,1)->(1,0)
        assert (5, 5) in cells
        assert (6, 5) in cells

    def test_stacker_ports(self):
        # Stacker has inputs on two layers
        b = Building("stacker", 5, 5, rotation=0)
        inputs = b.get_input_ports()
        outputs = b.get_output_ports()

        assert len(inputs) == 2
        # Both inputs from same direction, different layers
        assert inputs[0][2] == inputs[1][2]  # same direction
        assert inputs[0][3] != inputs[1][3]  # different layers

        assert len(outputs) == 1


class TestBuildingDefs:
    def test_all_defs_registered(self):
        expected = [
            "Rotator", "RotatorCCW", "RotatorHalf",
            "HalfDestroyer", "PinPusher", "Trash",
            "Cutter", "Swapper",
            "StackerStraight", "StackerBent",
        ]
        for name in expected:
            assert name in BUILDING_DEFS

    def test_cutter_def(self):
        cutter = BUILDING_DEFS["Cutter"]
        assert len(cutter.cells) == 2
        assert len(cutter.inputs) == 1
        assert len(cutter.outputs) == 2

    def test_swapper_def(self):
        swapper = BUILDING_DEFS["Swapper"]
        assert len(swapper.cells) == 2
        assert len(swapper.inputs) == 2
        assert len(swapper.outputs) == 2

    def test_stacker_def(self):
        stacker = BUILDING_DEFS["StackerBent"]
        assert len(stacker.cells) == 1  # 1x1 footprint
        assert len(stacker.inputs) == 2  # two layer inputs
        assert stacker.inputs[0].layer == 0
        assert stacker.inputs[1].layer == 1

    def test_cutter_mirrored(self):
        # Mirrored cutter should have input on other cell
        b_normal = Building("cutter", 5, 5, rotation=0, mirrored=False)
        b_mirror = Building("cutter", 5, 5, rotation=0, mirrored=True)

        # Both occupy same cells
        assert set(b_normal.get_cells()) == set(b_mirror.get_cells())

        # Input positions differ (Y flipped)
        inp_normal = b_normal.get_input_ports()[0]
        inp_mirror = b_mirror.get_input_ports()[0]
        assert inp_normal[1] != inp_mirror[1]  # different Y position


class TestGrid:
    def test_in_bounds(self):
        grid = Grid(10, 10)
        assert grid.in_bounds(0, 0)
        assert grid.in_bounds(9, 9)
        assert not grid.in_bounds(-1, 0)
        assert not grid.in_bounds(10, 0)

    def test_is_valid_no_mask(self):
        grid = Grid(10, 10)
        assert grid.is_valid(5, 5)
        assert not grid.is_valid(10, 10)

    def test_is_valid_with_mask(self):
        grid = Grid(10, 10)
        grid.valid_cells = {(0, 0), (1, 1), (2, 2)}
        assert grid.is_valid(0, 0)
        assert grid.is_valid(1, 1)
        assert not grid.is_valid(5, 5)

    def test_place_and_get(self):
        grid = Grid(10, 10)
        b = Building("belt", 5, 5)
        assert grid.place(b)
        assert grid.get(5, 5) == b
        assert grid.get(0, 0) is None

    def test_place_collision(self):
        grid = Grid(10, 10)
        b1 = Building("belt", 5, 5)
        b2 = Building("cutter", 5, 5)
        assert grid.place(b1)
        assert not grid.place(b2)

    def test_is_empty(self):
        grid = Grid(10, 10)
        assert grid.is_empty(5, 5)
        grid.place(Building("belt", 5, 5))
        assert not grid.is_empty(5, 5)

    def test_neighbors(self):
        grid = Grid(10, 10)
        neighbors = list(grid.neighbors(5, 5))
        assert len(neighbors) == 4
        positions = [(n[0], n[1]) for n in neighbors]
        assert (5, 6) in positions  # N
        assert (6, 5) in positions  # E
        assert (5, 4) in positions  # S
        assert (4, 5) in positions  # W

    def test_neighbors_corner(self):
        grid = Grid(10, 10)
        neighbors = list(grid.neighbors(0, 0))
        assert len(neighbors) == 2  # Only N and E

    def test_set_valid_from_shape(self):
        grid = Grid(6, 6)
        grid.set_valid_from_shape(["##", ".#"], origin_x=0, origin_y=0)
        # Shape (top to bottom):
        # ##  -> y=1
        # .#  -> y=0
        assert grid.is_valid(0, 1)  # top-left #
        assert grid.is_valid(1, 1)  # top-right #
        assert not grid.is_valid(0, 0)  # bottom-left .
        assert grid.is_valid(1, 0)  # bottom-right #


class TestFindPath:
    def test_simple_path(self):
        grid = Grid(10, 10)
        path = find_path(grid, (0, 0), (3, 0))
        assert path is not None
        assert len(path) == 3  # 3 belts to go 3 cells

    def test_path_around_obstacle(self):
        grid = Grid(10, 10)
        grid.place(Building("cutter", 2, 0))
        path = find_path(grid, (0, 0), (4, 0))
        assert path is not None
        assert len(path) > 4  # Must go around

    def test_no_path(self):
        grid = Grid(5, 5)
        # Block all paths
        for x in range(5):
            grid.place(Building("cutter", x, 2))
        path = find_path(grid, (0, 0), (0, 4))
        assert path is None


class TestPlatforms:
    def test_load_platform_data(self):
        data = load_platform_data()
        assert "Foundation_1x1" in data
        assert "Layout_Normal_5_Cross" in data

    def test_create_quarter_platform(self):
        grid, inputs, outputs = create_platform("Foundation_1x1")
        assert grid.width == 20
        assert grid.height == 20
        assert len(inputs) == 4
        assert len(outputs) == 4

    def test_create_irregular_platform(self):
        grid, inputs, outputs = create_platform("Layout_Normal_3_L")
        assert grid.valid_cells is not None
        # L-shape has 3 units * 20*20 = 1200 valid cells
        assert len(grid.valid_cells) == 1200

    def test_create_cross_platform(self):
        grid, _, _ = create_platform("Layout_Normal_5_Cross")
        # Cross has 5 units * 400 = 2000 valid cells
        assert len(grid.valid_cells) == 2000

    def test_unknown_platform_raises(self):
        with pytest.raises(ValueError, match="Unknown layout"):
            create_platform("NotARealPlatform")
