"""Belt routing for blueprint synthesis (WP-C).

Routes edges between machine/port positions, emitting belt entities that
round-trip through lift. The belt type+rotation table is inverted from
lift.routing_inout, so both directions share the same calibration.
"""

from __future__ import annotations

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
        # Straight belt. Rotation maps E→S→W→N for out_dir.
        r = {E: 0, S: 1, W: 2, N: 3}[out_dir]
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


def strip_belts(bp: Blueprint, layer: int) -> Blueprint:
    """Remove belt entities from a blueprint, keeping machines and ports."""
    kept = []
    for e in _all_entities(bp):
        if e.layer == layer and lift.kind(e.type) == "belt":
            continue  # skip belt
        kept.append(e)
    return _rebuild_blueprint(bp, kept)


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


def reroute(stripped: Blueprint, netlist: lift.Netlist, layer: int = 0) -> Blueprint:
    """Re-route a netlist using the machine positions from stripped blueprint.

    Generates belt entities to realize every edge in the netlist, then
    combines them with the non-belt entities from stripped.
    """
    # Get kept entities (machines + ports)
    kept = [e for e in _all_entities(stripped) if e.layer == layer]

    # Route each edge using port directions from the netlist
    routed_belts: list[Entity] = []
    for src_anchor, dst_anchor in netlist.edges:
        src_node = netlist.nodes[src_anchor]
        dst_node = netlist.nodes[dst_anchor]

        # Get port directions from _inout
        _, src_outs = lift._inout(src_node.type, src_node.rotation)
        dst_ins, _ = lift._inout(dst_node.type, dst_node.rotation)

        # For 1-out/1-in nodes, use the single direction
        # For multi-port, we'd need to match specific ports (TODO for cutters/swappers)
        src_out_dir = next(iter(src_outs)) if len(src_outs) == 1 else None
        dst_in_dir = next(iter(dst_ins)) if len(dst_ins) == 1 else None

        # Route with port awareness
        belts = route_edge(src_anchor, dst_anchor, layer, src_out_dir, dst_in_dir)
        routed_belts.extend(belts)

    # Deduplicate routed belts by position (overlapping paths merge)
    seen_positions: set[tuple[int, int]] = set()
    deduped_belts: list[Entity] = []
    for belt in routed_belts:
        pos = (belt.x, belt.y)
        if pos not in seen_positions:
            seen_positions.add(pos)
            deduped_belts.append(belt)

    # Combine kept + deduped
    all_entities = kept + deduped_belts
    return _rebuild_blueprint(stripped, all_entities)


def _anchor_of(cell: tuple[int, int], netlist: lift.Netlist) -> tuple[int, int] | None:
    """Find the node anchor that owns a cell (for port_edges lookup)."""
    for anchor in netlist.nodes:
        if anchor == cell:
            return anchor
    return None


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
