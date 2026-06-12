"""Belt routing for blueprint synthesis (WP-C).

Routes edges between machine/port positions, emitting belt entities that
round-trip through lift. The belt type+rotation table is inverted from
lift.routing_inout, so both directions share the same calibration.

The main routing approach is sequential A* with obstacle marking:
1. Build a grid graph for the routing area
2. Route each edge using networkx.astar_path()
3. After routing, mark those cells as obstacles for subsequent edges
4. Convert path cells to belt entities with correct type/rotation
"""

from __future__ import annotations

import networkx as nx

from shapez2_tools import lift
from shapez2_tools.blueprint import Blueprint
from shapez2_tools.generator import Entity

N, S, E, W = lift.N, lift.S, lift.E, lift.W


def _dir_name(d: tuple[int, int]) -> str:
    """Human-readable direction name."""
    return {N: "N", S: "S", E: "E", W: "W"}[d]


def _belt_for_inout(in_dir: tuple[int, int], out_dir: tuple[int, int]) -> tuple[str, int]:
    """Return (type, rotation) for a belt cell with given input/output directions.

    The table is the inverse of lift.routing_inout: given the directions items
    flow from/to, what belt variant and rotation produces that?
    """
    # Straight: in from back, out to front. At R=0, in=W out=E.
    # So if in and out are opposite, we need a Forward belt rotated so that
    # the output direction matches.
    if in_dir == _neg(out_dir):
        # Straight belt. Rotation maps out_dir: E→R0, N→R1, W→R2, S→R3.
        r = {E: 0, N: 1, W: 2, S: 3}[out_dir]
        return "BeltDefaultForwardInternalVariant", r

    # Turn: in from back (W at R=0), out to side (S for Left, N for LeftMirrored).
    # We need to find the rotation that makes in_dir map to back and out_dir to side.
    # At R=0: back=W, front=E, right=S (Left turn), left=N (LeftMirrored).
    # Each +1 in R rotates CCW: back→S, front→N, right→W, left→E.
    for r in range(4):
        back = lift._rotd(W, r)
        if in_dir == back:
            # Check Left (out = S rotated by r) or LeftMirrored (out = N rotated by r)
            left_out = lift._rotd(S, r)
            right_out = lift._rotd(N, r)
            if out_dir == left_out:
                return "BeltDefaultLeftInternalVariant", r
            if out_dir == right_out:
                return "BeltDefaultLeftInternalVariantMirrored", r

    raise ValueError(f"No belt for in={_dir_name(in_dir)} out={_dir_name(out_dir)}")


def _neg(d: tuple[int, int]) -> tuple[int, int]:
    return (-d[0], -d[1])


def route_fanout(
    src_pos: tuple[int, int],
    dst_positions: list[tuple[int, int]],
    src_out_dir: tuple[int, int],
    dst_in_dirs: list[tuple[int, int]],
    layer: int = 0,
) -> list[Entity]:
    """Route one source to multiple destinations using splitter junctions.

    Places a T-splitter at the point where paths diverge, with straight belts
    from source to splitter and from splitter branches to each destination.
    """
    if len(dst_positions) != len(dst_in_dirs):
        raise ValueError("dst_positions and dst_in_dirs must have same length")
    if len(dst_positions) < 2:
        raise ValueError("Fanout requires at least 2 destinations")

    entities: list[Entity] = []

    # Compute where each destination's approach belt is (one cell before dst)
    approach_cells = []
    for dst_pos, dst_in_dir in zip(dst_positions, dst_in_dirs):
        approach = (dst_pos[0] + dst_in_dir[0], dst_pos[1] + dst_in_dir[1])
        approach_cells.append(approach)

    # Find the split point: where the trunk from src meets the divergence point.
    # For horizontal src_out_dir (E/W), split at the x of the closest approach cell,
    # at y = src_pos[1] (trunk continues straight until split).
    # For vertical src_out_dir (N/S), split at the y of the closest approach cell.
    if src_out_dir in (E, W):
        # Trunk is horizontal. Split at x where we need to branch vertically.
        # Use the x coordinate that's closest to src but still reachable.
        if src_out_dir == E:
            # Going east: split at min x of approach cells (furthest we can go on trunk)
            split_x = min(a[0] for a in approach_cells)
            # Ensure split is at least one step from src
            split_x = max(split_x, src_pos[0] + 1)
        else:  # W
            split_x = max(a[0] for a in approach_cells)
            split_x = min(split_x, src_pos[0] - 1)
        split_y = src_pos[1]
    else:
        # Trunk is vertical. Split at y where we need to branch horizontally.
        if src_out_dir == N:
            split_y = min(a[1] for a in approach_cells)
            split_y = max(split_y, src_pos[1] + 1)
        else:  # S
            split_y = max(a[1] for a in approach_cells)
            split_y = min(split_y, src_pos[1] - 1)
        split_x = src_pos[0]

    split_pos = (split_x, split_y)

    # Route trunk from src to split (if more than adjacent)
    trunk_start = (src_pos[0] + src_out_dir[0], src_pos[1] + src_out_dir[1])
    if trunk_start != split_pos:
        # Straight belts along the trunk
        if src_out_dir in (E, W):
            step = 1 if src_out_dir == E else -1
            for x in range(trunk_start[0], split_x, step):
                belt_type, r = _belt_for_inout(_neg(src_out_dir), src_out_dir)
                entities.append(Entity(x=x, y=split_y, type=belt_type, rotation=r, layer=layer))
        else:
            step = 1 if src_out_dir == N else -1
            for y in range(trunk_start[1], split_y, step):
                belt_type, r = _belt_for_inout(_neg(src_out_dir), src_out_dir)
                entities.append(Entity(x=split_x, y=y, type=belt_type, rotation=r, layer=layer))

    # Determine output directions from split to each branch
    split_outs: set[tuple[int, int]] = set()
    branch_info: list[tuple[tuple[int, int], tuple[int, int], tuple[int, int]]] = []

    for approach, (dst_pos, dst_in_dir) in zip(approach_cells, zip(dst_positions, dst_in_dirs)):
        # Direction from split to approach cell
        dx = approach[0] - split_x
        dy = approach[1] - split_y

        # Perpendicular direction (branches go perpendicular to trunk)
        if src_out_dir in (E, W):
            # Trunk is horizontal, branches go N or S
            out_dir = N if dy > 0 else S if dy < 0 else src_out_dir
        else:
            # Trunk is vertical, branches go E or W
            out_dir = E if dx > 0 else W if dx < 0 else src_out_dir

        split_outs.add(out_dir)
        branch_info.append((approach, dst_pos, dst_in_dir, out_dir))

    # Place the splitter at split point
    split_in = _neg(src_out_dir)
    splitter_type, splitter_r = _belt_for_cell(frozenset({split_in}), frozenset(split_outs))
    entities.append(
        Entity(x=split_x, y=split_y, type=splitter_type, rotation=splitter_r, layer=layer)
    )

    # Route from splitter to each destination via its approach cell
    for approach, dst_pos, dst_in_dir, out_dir in branch_info:
        # First cell after split in branch direction
        branch_start = (split_x + out_dir[0], split_y + out_dir[1])

        # If approach is further, route the branch
        if branch_start == approach:
            # Just one turn belt from branch to approach
            in_d = _neg(out_dir)
            out_d = _neg(dst_in_dir)
            belt_type, r = _belt_for_inout(in_d, out_d)
            entities.append(
                Entity(x=approach[0], y=approach[1], type=belt_type, rotation=r, layer=layer)
            )
        else:
            # Multiple cells: straight belts + final turn
            # Go perpendicular from split until we reach approach's perpendicular coord
            if out_dir in (N, S):
                # Going N/S, need to reach approach[1]
                step = 1 if out_dir == N else -1
                y = branch_start[1]
                # Use range to avoid infinite loop
                y_range = (
                    range(branch_start[1], approach[1], step)
                    if step > 0
                    else range(branch_start[1], approach[1], step)
                )
                for y in y_range:
                    belt_type, r = _belt_for_inout(_neg(out_dir), out_dir)
                    entities.append(Entity(x=split_x, y=y, type=belt_type, rotation=r, layer=layer))
                # Final turn at approach
                in_d = _neg(out_dir)
                out_d = _neg(dst_in_dir)
                belt_type, r = _belt_for_inout(in_d, out_d)
                entities.append(
                    Entity(x=approach[0], y=approach[1], type=belt_type, rotation=r, layer=layer)
                )
            else:
                # Going E/W, need to reach approach[0]
                step = 1 if out_dir == E else -1
                x_range = (
                    range(branch_start[0], approach[0], step)
                    if step > 0
                    else range(branch_start[0], approach[0], step)
                )
                for x in x_range:
                    belt_type, r = _belt_for_inout(_neg(out_dir), out_dir)
                    entities.append(Entity(x=x, y=split_y, type=belt_type, rotation=r, layer=layer))
                # Final turn at approach
                in_d = _neg(out_dir)
                out_d = _neg(dst_in_dir)
                belt_type, r = _belt_for_inout(in_d, out_d)
                entities.append(
                    Entity(x=approach[0], y=approach[1], type=belt_type, rotation=r, layer=layer)
                )

    return entities


def route_fanin(
    src_positions: list[tuple[int, int]],
    dst_pos: tuple[int, int],
    src_out_dirs: list[tuple[int, int]],
    dst_in_dir: tuple[int, int],
    layer: int = 0,
) -> list[Entity]:
    """Route multiple sources to one destination using merger junctions.

    Places a T-merger where branches converge, with straight belts from each
    source to the merge point, and from merge point to destination.
    """
    if len(src_positions) != len(src_out_dirs):
        raise ValueError("src_positions and src_out_dirs must have same length")
    if len(src_positions) < 2:
        raise ValueError("Fanin requires at least 2 sources")

    entities: list[Entity] = []

    # Compute where each source's departure cell is (one cell after src)
    departure_cells = []
    for src_pos, src_out_dir in zip(src_positions, src_out_dirs):
        departure = (src_pos[0] + src_out_dir[0], src_pos[1] + src_out_dir[1])
        departure_cells.append(departure)

    # Find the merge point: where branches converge before heading to dst.
    # The trunk goes from merge to dst; branches come in perpendicular.
    # Output direction from merge = opposite of dst_in_dir
    merge_out = _neg(dst_in_dir)

    if merge_out in (E, W):
        # Trunk is horizontal (merge → dst). Merge at x of the closest departure cell.
        if merge_out == E:
            # Going east to dst: merge at max x of departures (closest to dst)
            merge_x = max(d[0] for d in departure_cells)
            # Ensure merge is at least one step before dst's approach cell
            approach_x = dst_pos[0] + dst_in_dir[0]
            merge_x = min(merge_x, approach_x - 1) if approach_x > merge_x else merge_x
        else:  # W
            merge_x = min(d[0] for d in departure_cells)
            approach_x = dst_pos[0] + dst_in_dir[0]
            merge_x = max(merge_x, approach_x + 1) if approach_x < merge_x else merge_x
        merge_y = dst_pos[1]  # Same y as dst for horizontal trunk
    else:
        # Trunk is vertical (merge → dst). Merge at y of the closest departure cell.
        if merge_out == N:
            merge_y = max(d[1] for d in departure_cells)
            approach_y = dst_pos[1] + dst_in_dir[1]
            merge_y = min(merge_y, approach_y - 1) if approach_y > merge_y else merge_y
        else:  # S
            merge_y = min(d[1] for d in departure_cells)
            approach_y = dst_pos[1] + dst_in_dir[1]
            merge_y = max(merge_y, approach_y + 1) if approach_y < merge_y else merge_y
        merge_x = dst_pos[0]  # Same x as dst for vertical trunk

    # Determine input directions to merge from each branch
    merge_ins: set[tuple[int, int]] = set()
    branch_info: list[tuple[tuple[int, int], tuple[int, int], tuple[int, int]]] = []

    for departure, (src_pos, src_out_dir) in zip(departure_cells, zip(src_positions, src_out_dirs)):
        # Direction from departure toward merge
        dx = merge_x - departure[0]
        dy = merge_y - departure[1]

        # Perpendicular direction (branches approach perpendicular to trunk)
        if merge_out in (E, W):
            # Trunk is horizontal, branches come from N or S
            in_dir = S if dy < 0 else N if dy > 0 else _neg(merge_out)
        else:
            # Trunk is vertical, branches come from E or W
            in_dir = W if dx < 0 else E if dx > 0 else _neg(merge_out)

        merge_ins.add(in_dir)
        branch_info.append((departure, src_pos, src_out_dir, in_dir))

    # Place the merger at merge point
    merger_type, merger_r = _belt_for_cell(frozenset(merge_ins), frozenset({merge_out}))
    entities.append(Entity(x=merge_x, y=merge_y, type=merger_type, rotation=merger_r, layer=layer))

    # Route trunk from merge to dst
    approach_cell = (dst_pos[0] + dst_in_dir[0], dst_pos[1] + dst_in_dir[1])
    trunk_start = (merge_x + merge_out[0], merge_y + merge_out[1])
    if trunk_start != dst_pos:
        # Straight belts along the trunk (inclusive of approach_cell)
        if merge_out in (E, W):
            step = 1 if merge_out == E else -1
            for x in range(trunk_start[0], approach_cell[0] + step, step):
                belt_type, r = _belt_for_inout(_neg(merge_out), merge_out)
                entities.append(Entity(x=x, y=merge_y, type=belt_type, rotation=r, layer=layer))
        else:
            step = 1 if merge_out == N else -1
            for y in range(trunk_start[1], approach_cell[1] + step, step):
                belt_type, r = _belt_for_inout(_neg(merge_out), merge_out)
                entities.append(Entity(x=merge_x, y=y, type=belt_type, rotation=r, layer=layer))

    # Route from each source to merge point via its departure cell
    for departure, src_pos, src_out_dir, in_dir in branch_info:
        # Last cell before merge in branch direction (where belt turns into merge)
        branch_end = (merge_x - in_dir[0], merge_y - in_dir[1])

        if departure == branch_end:
            # Just one turn belt from departure to merge
            in_d = _neg(src_out_dir)
            out_d = in_dir  # Output in the direction merge accepts from (toward merge)
            belt_type, r = _belt_for_inout(in_d, out_d)
            entities.append(
                Entity(x=departure[0], y=departure[1], type=belt_type, rotation=r, layer=layer)
            )
        else:
            # Multiple cells: initial turn + straight belts to merge
            # First belt turns from src direction to branch direction
            if in_dir in (N, S):
                # Branch goes N/S toward merge
                # First belt at departure: turn from src_out_dir toward merge
                in_d = _neg(src_out_dir)
                out_d = in_dir  # Output in the direction merge accepts from
                belt_type, r = _belt_for_inout(in_d, out_d)
                entities.append(
                    Entity(x=departure[0], y=departure[1], type=belt_type, rotation=r, layer=layer)
                )

                # Straight belts from departure toward branch_end
                step = -1 if in_dir == S else 1  # S means we go south (y decreases)
                start_y = departure[1] + step
                end_y = branch_end[1] + step
                y_range = (
                    range(start_y, end_y, step)
                    if (step > 0 and start_y < end_y) or (step < 0 and start_y > end_y)
                    else []
                )
                for y in y_range:
                    belt_type, r = _belt_for_inout(_neg(in_dir), in_dir)
                    entities.append(Entity(x=merge_x, y=y, type=belt_type, rotation=r, layer=layer))
            else:
                # Branch goes E/W toward merge
                in_d = _neg(src_out_dir)
                out_d = in_dir  # Output in the direction merge accepts from
                belt_type, r = _belt_for_inout(in_d, out_d)
                entities.append(
                    Entity(x=departure[0], y=departure[1], type=belt_type, rotation=r, layer=layer)
                )

                step = 1 if in_dir == W else -1
                start_x = departure[0] + step
                end_x = branch_end[0] + step
                x_range = (
                    range(start_x, end_x, step)
                    if (step > 0 and start_x < end_x) or (step < 0 and start_x > end_x)
                    else []
                )
                for x in x_range:
                    belt_type, r = _belt_for_inout(_neg(in_dir), in_dir)
                    entities.append(Entity(x=x, y=merge_y, type=belt_type, rotation=r, layer=layer))

    return entities


# =============================================================================
# A* routing with obstacle avoidance
# =============================================================================


def _build_grid_graph(
    bounds: tuple[int, int, int, int],
    obstacles: set[tuple[int, int]] | None = None,
) -> nx.Graph:
    """Build a 2D grid graph for A* routing.

    Args:
        bounds: (min_x, min_y, max_x, max_y) inclusive
        obstacles: set of (x, y) cells to exclude from the graph

    Returns:
        An undirected grid graph with nodes at each non-obstacle cell.
    """
    min_x, min_y, max_x, max_y = bounds
    width = max_x - min_x + 1
    height = max_y - min_y + 1

    # Create grid graph with offset coordinates
    G = nx.grid_2d_graph(width, height)

    # Relabel nodes to actual coordinates
    mapping = {(i, j): (min_x + i, min_y + j) for i in range(width) for j in range(height)}
    G = nx.relabel_nodes(G, mapping)

    # Remove obstacle nodes
    if obstacles:
        for obs in obstacles:
            if obs in G:
                G.remove_node(obs)

    return G


def _manhattan_distance(a: tuple[int, int], b: tuple[int, int]) -> int:
    """Manhattan distance heuristic for A*."""
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def route_astar(
    src_pos: tuple[int, int],
    dst_pos: tuple[int, int],
    src_out_dir: tuple[int, int],
    dst_in_dir: tuple[int, int],
    obstacles: set[tuple[int, int]] | None = None,
    layer: int = 0,
    bounds: tuple[int, int, int, int] | None = None,
) -> list[Entity]:
    """Route a single edge using A* pathfinding with obstacle avoidance.

    Args:
        src_pos: Source position (machine/port cell)
        dst_pos: Destination position (machine/port cell)
        src_out_dir: Direction source outputs to
        dst_in_dir: Direction destination accepts from
        obstacles: Cells that cannot be routed through
        layer: Layer for generated entities
        bounds: (min_x, min_y, max_x, max_y) for the routing area.
                If None, computed from src/dst with margin.

    Returns:
        List of belt entities connecting src to dst.
    """
    obstacles = obstacles or set()

    # Start cell is one step from src in output direction
    start = (src_pos[0] + src_out_dir[0], src_pos[1] + src_out_dir[1])
    # End cell is one step from dst in input direction (belt approaches from there)
    end = (dst_pos[0] + dst_in_dir[0], dst_pos[1] + dst_in_dir[1])

    if start == end:
        if start in obstacles:
            return []
        in_d = _neg(src_out_dir)
        out_d = _neg(dst_in_dir)
        belt_type, r = _belt_for_inout(in_d, out_d)
        return [Entity(x=start[0], y=start[1], type=belt_type, rotation=r, layer=layer)]

    # Compute bounds if not provided
    if bounds is None:
        all_x = [src_pos[0], dst_pos[0], start[0], end[0]]
        all_y = [src_pos[1], dst_pos[1], start[1], end[1]]
        margin = max(abs(dst_pos[0] - src_pos[0]), abs(dst_pos[1] - src_pos[1])) + 2
        bounds = (
            min(all_x) - margin,
            min(all_y) - margin,
            max(all_x) + margin,
            max(all_y) + margin,
        )

    # Build grid graph excluding obstacles and src/dst positions
    full_obstacles = obstacles | {src_pos, dst_pos}
    G = _build_grid_graph(bounds, full_obstacles)

    # Ensure start and end are in the graph
    if start not in G:
        return []  # Can't route
    if end not in G:
        return []  # Can't route

    # Find path using A*
    try:
        path = nx.astar_path(G, start, end, heuristic=_manhattan_distance)
    except nx.NetworkXNoPath:
        return []  # No path exists

    # Convert path to belt entities
    entities: list[Entity] = []
    for i, (x, y) in enumerate(path):
        # Determine input direction
        if i == 0:
            in_d = _neg(src_out_dir)  # First cell receives from source
        else:
            px, py = path[i - 1]
            in_d = (px - x, py - y)  # Receives from previous cell

        # Determine output direction
        if i == len(path) - 1:
            out_d = _neg(dst_in_dir)  # Last cell outputs to destination
        else:
            nx_, ny = path[i + 1]
            out_d = (nx_ - x, ny - y)  # Outputs to next cell

        belt_type, r = _belt_for_inout(in_d, out_d)
        entities.append(Entity(x=x, y=y, type=belt_type, rotation=r, layer=layer))

    return entities


def route_edges_sequential(
    edges: list[tuple[tuple[int, int], tuple[int, int], tuple[int, int], tuple[int, int]]],
    layer: int = 0,
    initial_obstacles: set[tuple[int, int]] | None = None,
) -> list[Entity]:
    """Route multiple edges sequentially, each becoming an obstacle for the next.

    Args:
        edges: List of (src_pos, dst_pos, src_out_dir, dst_in_dir) tuples
        layer: Layer for generated entities
        initial_obstacles: Pre-existing obstacles (e.g., machine positions)

    Returns:
        List of all belt entities for all edges.
    """
    obstacles = set(initial_obstacles) if initial_obstacles else set()
    all_entities: list[Entity] = []

    # Compute bounds from all edges
    all_x = []
    all_y = []
    for src_pos, dst_pos, _, _ in edges:
        all_x.extend([src_pos[0], dst_pos[0]])
        all_y.extend([src_pos[1], dst_pos[1]])

    margin = 5
    bounds = (
        min(all_x) - margin,
        min(all_y) - margin,
        max(all_x) + margin,
        max(all_y) + margin,
    )

    # Add ALL src/dst positions to obstacles upfront (machines can't be routed through)
    for src_pos, dst_pos, _, _ in edges:
        obstacles.add(src_pos)
        obstacles.add(dst_pos)

    for src_pos, dst_pos, src_out_dir, dst_in_dir in edges:
        entities = route_astar(
            src_pos,
            dst_pos,
            src_out_dir,
            dst_in_dir,
            obstacles=obstacles,
            layer=layer,
            bounds=bounds,
        )

        # Add routed cells to obstacles for next edge
        for e in entities:
            obstacles.add((e.x, e.y))

        all_entities.extend(entities)

    return all_entities


def route_edge(
    src: tuple[int, int],
    dst: tuple[int, int],
    layer: int = 0,
    src_out_dir: tuple[int, int] | None = None,
    dst_in_dir: tuple[int, int] | None = None,
) -> list[Entity]:
    """Route a single edge from src to dst, emitting belt entities.

    If src_out_dir is given, the first belt starts at (src + src_out_dir) and
    receives from src_out_dir. If dst_in_dir is given, the last belt feeds into
    dst from that direction.

    The src and dst cells are NOT included in the output — they're assumed to be
    the machine/port positions. Only the intermediate belt cells are returned.
    """
    entities: list[Entity] = []

    # Determine start and end points for the belt path
    if src_out_dir:
        # Start at the cell adjacent to src in the output direction
        start = (src[0] + src_out_dir[0], src[1] + src_out_dir[1])
        first_in_dir = _neg(src_out_dir)  # belt receives from src
    else:
        # No port direction — start one cell toward dst (exclude src)
        # Use primary axis (horizontal if |dx| >= |dy|)
        dx = dst[0] - src[0]
        dy = dst[1] - src[1]
        if abs(dx) >= abs(dy) and dx != 0:
            step = E if dx > 0 else W
        elif dy != 0:
            step = N if dy > 0 else S
        else:
            step = E  # shouldn't happen (src == dst)
        start = (src[0] + step[0], src[1] + step[1])
        first_in_dir = _neg(step)

    if dst_in_dir:
        # End at the cell adjacent to dst that feeds into it
        end = (dst[0] + dst_in_dir[0], dst[1] + dst_in_dir[1])
        last_out_dir = _neg(dst_in_dir)  # belt outputs toward dst
    else:
        # No port direction — end one cell before dst (exclude dst)
        # Use the axis we'll be traveling on last (vertical if we went horizontal first)
        dx = dst[0] - src[0]
        dy = dst[1] - src[1]
        if abs(dx) >= abs(dy) and dy != 0:
            # Horizontal first, so approach dst vertically
            step = N if dy > 0 else S
        elif dx != 0:
            step = E if dx > 0 else W
        elif dy != 0:
            step = N if dy > 0 else S
        else:
            step = E  # shouldn't happen
        end = (dst[0] - step[0], dst[1] - step[1])
        last_out_dir = step

    # Handle adjacent cells (1 step apart) — no intermediate belts needed
    if start == end:
        if first_in_dir and last_out_dir:
            belt_type, r = _belt_for_inout(first_in_dir, last_out_dir)
            entities.append(Entity(x=start[0], y=start[1], type=belt_type, rotation=r, layer=layer))
        return entities

    # Handle src == dst or dst one step from src
    sx, sy = start
    ex, ey = end
    if sx == ex and sy == ey:
        return entities  # Nothing to route

    # Route from start to end
    path = _find_path(start, end, first_in_dir, last_out_dir)
    for x, y, in_d, out_d in path:
        belt_type, r = _belt_for_inout(in_d, out_d)
        entities.append(Entity(x=x, y=y, type=belt_type, rotation=r, layer=layer))

    return entities


def _find_path(
    start: tuple[int, int],
    end: tuple[int, int],
    first_in_dir: tuple[int, int] | None,
    last_out_dir: tuple[int, int] | None,
) -> list[tuple[int, int, tuple[int, int], tuple[int, int]]]:
    """Find a Manhattan path, returning [(x, y, in_dir, out_dir), ...].

    Simple L-shaped routing: go horizontal first, then vertical.
    Respects entry (first_in_dir) and exit (last_out_dir) constraints.
    """
    sx, sy = start
    ex, ey = end
    dx, dy = ex - sx, ey - sy

    if dx == 0 and dy == 0:
        return []

    path: list[tuple[int, int, tuple[int, int], tuple[int, int]]] = []

    # Build the sequence of cells and directions
    cells = [(sx, sy)]
    cx, cy = sx, sy

    # Horizontal movement first
    h_dir = E if dx > 0 else W if dx < 0 else None
    while h_dir and cx != ex:
        cx = cx + h_dir[0]
        cells.append((cx, cy))

    # Then vertical movement
    v_dir = N if dy > 0 else S if dy < 0 else None
    while v_dir and cy != ey:
        cy = cy + v_dir[1]
        cells.append((cx, cy))

    # Now assign in/out directions to each cell
    for i, (x, y) in enumerate(cells):
        if i == 0:
            # First cell: use first_in_dir if given, else derive from next cell
            if first_in_dir:
                in_d = first_in_dir
            elif len(cells) > 1:
                nx, ny = cells[1]
                in_d = _neg((nx - x, ny - y))
            else:
                in_d = W  # default
        else:
            # Input is opposite of how we got here
            px, py = cells[i - 1]
            in_d = (px - x, py - y)

        if i == len(cells) - 1:
            # Last cell: use last_out_dir if given
            if last_out_dir:
                out_d = last_out_dir
            else:
                out_d = _neg(in_d)  # continue straight
        else:
            # Output is toward next cell
            nx, ny = cells[i + 1]
            out_d = (nx - x, ny - y)

        path.append((x, y, in_d, out_d))

    return path


def strip_belts(bp: Blueprint, layer: int, netlist: lift.Netlist | None = None) -> Blueprint:
    """Remove belt entities from a blueprint, keeping machines and ports.

    If ``netlist`` is given, also strip platform_in/platform_out-typed
    entities whose cell is not a node of ``netlist`` — interior hop
    launcher/catcher endpoints contracted out by
    ``lift.trace_layer(..., contract_hops=True)`` are routing primitives,
    not platform IO, and PathFinder re-derives them as needed. Without a
    netlist, ``lift.kind()`` can't distinguish the two, so all
    platform_in/platform_out entities are kept (old behavior).
    """
    kept = []
    for e in _all_entities(bp):
        if e.layer == layer:
            k = lift.kind(e.type)
            if k == "belt":
                continue  # skip belt
            if (
                netlist is not None
                and k in ("platform_in", "platform_out")
                and (e.x, e.y) not in netlist.nodes
            ):
                continue  # skip interior hop endpoint
        kept.append(e)
    return _rebuild_blueprint(bp, kept)


def reroute_astar(stripped: Blueprint, netlist: lift.Netlist, layer: int = 0) -> Blueprint:
    """Re-route a netlist using A*-based sequential routing.

    Routes each edge one at a time using A* pathfinding. After routing each edge,
    the routed cells become obstacles for subsequent edges, preventing crossings.

    Note: This basic version routes edges independently and doesn't handle
    fan-in (N→1) or fan-out (1→N) patterns that require merger/splitter junctions.
    Use reroute_with_junctions() for netlists with fan patterns.

    Args:
        stripped: Blueprint with belts removed (machines and ports only)
        netlist: The netlist to realize
        layer: Layer to route on

    Returns:
        Blueprint with new belt routing.
    """
    # Get kept entities (machines + ports)
    kept = [e for e in _all_entities(stripped) if e.layer == layer]

    # Collect machine/port positions as initial obstacles
    initial_obstacles: set[tuple[int, int]] = set()
    for e in kept:
        initial_obstacles.add((e.x, e.y))
        # Add footprint cells for multi-cell machines
        footprint = lift._machine_footprint(e.type, e.rotation)
        for dx, dy, dl in footprint:
            if dl == 0:
                initial_obstacles.add((e.x + dx, e.y + dy))

    # Build edge list with port directions
    edges: list[tuple[tuple[int, int], tuple[int, int], tuple[int, int], tuple[int, int]]] = []
    for src_anchor, dst_anchor in netlist.edges:
        src_node = netlist.nodes[src_anchor]
        dst_node = netlist.nodes[dst_anchor]

        _, src_outs = lift._inout(src_node.type, src_node.rotation)
        dst_ins, _ = lift._inout(dst_node.type, dst_node.rotation)

        # Use first output/input direction (single-port assumption for now)
        src_out_dir = next(iter(src_outs)) if src_outs else E
        dst_in_dir = next(iter(dst_ins)) if dst_ins else W

        edges.append((src_anchor, dst_anchor, src_out_dir, dst_in_dir))

    # Sort edges: longer edges first (more routing freedom)
    def edge_length(e):
        src, dst, _, _ = e
        return abs(dst[0] - src[0]) + abs(dst[1] - src[1])

    edges.sort(key=edge_length, reverse=True)

    # Route all edges sequentially
    routed_belts = route_edges_sequential(edges, layer=layer, initial_obstacles=initial_obstacles)

    # Combine kept + routed
    all_entities = kept + routed_belts
    return _rebuild_blueprint(stripped, all_entities)


def reroute_with_junctions(
    stripped: Blueprint,
    netlist: lift.Netlist,
    layer: int = 0,
    *,
    hop_range: int = 0,
    platform: str | None = None,
) -> Blueprint:
    """Re-route a netlist handling fan-in and fan-out with junctions.

    Delegates to the PathFinder negotiated-congestion router (WP-I).
    """
    from shapez2_tools.pathfinder import strip_and_reroute

    return strip_and_reroute(
        stripped, netlist, layer=layer, hop_range=hop_range, platform=platform,
    )


def _all_entities(bp: Blueprint) -> list[Entity]:
    """Extract all entities from a blueprint."""
    entities = []
    for platform in bp.entries:
        body = platform.get("B")
        if body:
            for d in body.get("Entries", []):
                entities.append(Entity.from_dict(d))
    return entities


def _rebuild_blueprint(bp: Blueprint, entities: list[Entity]) -> Blueprint:
    """Rebuild a blueprint with a new entity list, preserving structure."""
    import copy

    data = copy.deepcopy(bp.data)
    # Assume single platform for now
    if data["BP"]["Entries"]:
        data["BP"]["Entries"][0]["B"]["Entries"] = [e.to_dict() for e in entities]
    return Blueprint(data, bp.format_version)


def _belt_for_cell(ins: frozenset, outs: frozenset) -> tuple[str, int]:
    """Return (type, rotation) for a belt cell with given input/output direction sets.

    Handles simple belts (1-in/1-out), turns, splitters (1-in/2-out), and
    mergers (2-in/1-out).
    """
    # Try each belt variant at each rotation
    variants = [
        "BeltDefaultForwardInternalVariant",
        "BeltDefaultLeftInternalVariant",
        "BeltDefaultLeftInternalVariantMirrored",
        "Splitter1To2LInternalVariant",
        "Splitter1To2LInternalVariantMirrored",
        "Splitter1To3InternalVariant",
        "SplitterTShapeInternalVariant",
        "Merger2To1LInternalVariant",
        "Merger2To1LInternalVariantMirrored",
        "Merger3To1InternalVariant",
        "MergerTShapeInternalVariant",
    ]

    for variant in variants:
        for r in range(4):
            result = lift.routing_inout(variant, r)
            if result:
                v_ins, v_outs = result
                if v_ins == ins and v_outs == outs:
                    return variant, r

    # Fallback: if no exact match, try to find a superset match
    # (a belt that has at least the required I/O)
    for variant in variants:
        for r in range(4):
            result = lift.routing_inout(variant, r)
            if result:
                v_ins, v_outs = result
                if ins.issubset(v_ins) and outs.issubset(v_outs):
                    return variant, r

    # No belt type can handle this I/O configuration (e.g., 2-in/2-out crossing)
    # Return a placeholder that will cause unmatched legs — better than crashing
    return "BeltDefaultForwardInternalVariant", 0


def entities_to_blueprint(
    entities: list[Entity],
    platform: str = "Foundation_1x1",
    game_version: int = 1137,
) -> Blueprint:
    """Wrap entities in a minimal Blueprint for testing.

    Creates a single-platform Island blueprint containing the given entities.
    Used for round-trip testing: route → blueprint → lift.
    """
    building_entries = [e.to_dict() for e in entities]
    data = {
        "V": game_version,
        "BP": {
            "$type": "Island",
            "Icon": {"Data": [None, None, None, None]},
            "Entries": [
                {
                    "R": 0,
                    "T": platform,
                    "B": {
                        "$type": "Building",
                        "Icon": {"Data": [None, None, None, None]},
                        "Entries": building_entries,
                    },
                }
            ],
        },
    }
    return Blueprint(data)
