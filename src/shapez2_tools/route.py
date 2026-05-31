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
) -> list[Entity]:
    """Route a single edge from src to dst, emitting belt entities.

    Uses a simple Manhattan path: horizontal first, then vertical (or vice versa
    if that would work better). No obstacle avoidance yet.

    The src and dst cells are NOT included in the output — they're assumed to be
    the machine/port positions. Only the intermediate belt cells are returned.
    """
    x, y = src
    dx, dy = dst[0] - src[0], dst[1] - src[1]
    entities: list[Entity] = []

    # Decide primary direction based on which axis has more distance
    # (arbitrary choice — could be optimized later)
    if abs(dx) >= abs(dy):
        # Horizontal first
        h_dir = E if dx > 0 else W
        v_dir = N if dy > 0 else S
        h_steps = abs(dx)
        v_steps = abs(dy)
    else:
        # Vertical first
        h_dir = E if dx > 0 else W
        v_dir = N if dy > 0 else S
        h_steps = abs(dx)
        v_steps = abs(dy)
        # Swap order
        h_dir, v_dir = v_dir, h_dir
        h_steps, v_steps = v_steps, h_steps

    prev_dir = None
    cx, cy = x, y

    def emit(in_d, out_d, ex, ey):
        """Emit a belt at (ex, ey) with the given in/out directions."""
        belt_type, r = _belt_for_inout(in_d, out_d)
        entities.append(Entity(x=ex, y=ey, type=belt_type, rotation=r, layer=layer))

    # Move in primary direction
    for _ in range(h_steps):
        # Step forward
        ncx, ncy = cx + h_dir[0], cy + h_dir[1]
        # The cell we're leaving becomes a belt (unless it's src)
        if (cx, cy) != src:
            in_d = _neg(prev_dir) if prev_dir else _neg(h_dir)  # from where we came
            out_d = h_dir  # to where we're going
            emit(in_d, out_d, cx, cy)
        prev_dir = h_dir
        cx, cy = ncx, ncy

    # Turn if needed
    if v_steps > 0 and (cx, cy) != dst:
        # Emit a turn at the corner
        in_d = _neg(prev_dir)
        out_d = v_dir
        emit(in_d, out_d, cx, cy)
        prev_dir = v_dir
        cx, cy = cx + v_dir[0], cy + v_dir[1]

    # Move in secondary direction
    for _ in range(v_steps - 1):  # -1 because we already took one step at the turn
        ncx, ncy = cx + v_dir[0], cy + v_dir[1]
        if (cx, cy) != src and (cx, cy) != dst:
            in_d = _neg(prev_dir)
            out_d = v_dir
            emit(in_d, out_d, cx, cy)
        prev_dir = v_dir
        cx, cy = ncx, ncy

    return entities


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

    # Route each edge in the netlist
    routed_belts: list[Entity] = []
    for src_anchor, dst_anchor in netlist.edges:
        # Get the actual cells from port_edges if available
        port_edge_cells = [
            (s, d)
            for s, d in netlist.port_edges
            if _anchor_of(s, netlist) == src_anchor and _anchor_of(d, netlist) == dst_anchor
        ]

        if port_edge_cells:
            for src_cell, dst_cell in port_edge_cells:
                belts = route_edge(src_cell, dst_cell, layer)
                routed_belts.extend(belts)
        else:
            # Fallback: route from src anchor to dst anchor
            belts = route_edge(src_anchor, dst_anchor, layer)
            routed_belts.extend(belts)

    # Combine kept + routed
    all_entities = kept + routed_belts
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
