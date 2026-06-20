"""Machine placement via OR-Tools CP-SAT (WP-D + WP-M + WP-N band model).

Given an abstract netlist (node types/kinds + edges, no coordinates) and a
platform, assigns (x, y, rotation) to each node using constraint programming.
Sources and sinks are fixed at platform-edge positions; machines are placed
in the interior with no-overlap and wire-length minimization.

Machines are assigned to **stage bands**: each stage (depth from sources) maps
to a y-interval (band_lo, band_hi) and each machine gets its own y within its
stage's band.  Routing channels between bands have a minimum height of 2 cells.
Fan-out groups (machines sharing a source) form **blocks** with a shared
x-interval; cross-block ordering by source x prevents lateral overlap.

Multi-cell machines (cutters, swappers) occupy a second cell whose position
depends on rotation. The solver tracks both cells for overlap avoidance and
bounds, and ``_build_netlist`` assigns port-level edges by proximity.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from ortools.sat.python import cp_model

from shapez2_tools import lift

_DATA = Path(__file__).resolve().parent.parent.parent / "data"

_BUCKET_WIDTH = 4

# Design convention (2026-06-11): items flow south → north. Sources default
# to the south face, sinks to the north face; west/east (and pins) are used
# when one face's port count is insufficient (e.g. the full-lane stacker:
# 8 inputs on south+west+east, 4 outputs on north).
SOURCE_FACE = 1  # south
SINK_FACE = 3  # north


def _load_platform(name: str) -> dict:
    with open(_DATA / "platforms.json") as f:
        platforms = json.load(f)
    return platforms[name]


def _is_multi_cell(type_: str) -> bool:
    return ("Cutter" in type_ and "Half" not in type_) or "Swapper" in type_


def _second_cell_tables(type_: str) -> tuple[list[int], list[int]]:
    """Offset (dx[R], dy[R]) for the second cell of a multi-cell machine."""
    if "Mirrored" in type_:
        return [0, -1, 0, 1], [1, 0, -1, 0]
    return [0, 1, 0, -1], [-1, 0, 1, 0]


def _compute_stages(abstract: dict) -> dict[str, int]:
    """Assign each machine a stage index by BFS depth from sources.

    Stage increments at each machine-to-machine hop.  Machines directly fed
    by sources are stage 0, machines fed by stage-0 machines are stage 1, etc.
    """
    node_by_id = {n["id"]: n for n in abstract["nodes"]}
    edge_out: dict[str, list[str]] = defaultdict(list)
    for sid, did in abstract["edges"]:
        edge_out[sid].append(did)

    stage: dict[str, int] = {}
    # BFS queue: (node_id, current_machine_depth).
    # Sources start at depth -1; the first machine hop bumps to 0.
    queue: list[tuple[str, int]] = [
        (n["id"], -1) for n in abstract["nodes"] if n["kind"] == "platform_in"
    ]
    visited: set[str] = set()
    while queue:
        nid, s = queue.pop(0)
        if nid in visited:
            continue
        visited.add(nid)
        node = node_by_id[nid]
        if node["kind"] == "machine":
            s += 1
            stage[nid] = s
        for child in edge_out.get(nid, []):
            queue.append((child, s))

    return stage


def _detect_fan_topology(
    abstract: dict,
    stages: dict[str, int],
) -> dict[str, list[str]] | None:
    """Detect whether the netlist has a fan topology suitable for columnar placement.

    Returns an anchor_id → [machine_ids] lane decomposition.  The anchor is
    the node whose port x determines column ordering — a source for single-input
    fans (cutters), a sink for multi-input fans (stackers).

    Columnar placement is used when all machines are stage 0 (no machine-to-
    machine edges), each machine belongs to exactly one lane, and the topology
    is dense enough to benefit from column constraints.
    """
    if not stages or max(stages.values()) != 0:
        return None

    node_by_id = {n["id"]: n for n in abstract["nodes"]}

    # --- Source-based detection (cutters: 1 source per machine) ---
    src_to_machines: dict[str, list[str]] = defaultdict(list)
    machine_owner_count: dict[str, int] = defaultdict(int)

    for sid, did in abstract["edges"]:
        if node_by_id[sid]["kind"] == "platform_in" and node_by_id[did]["kind"] == "machine":
            src_to_machines[sid].append(did)
            machine_owner_count[did] += 1

    if all(c == 1 for c in machine_owner_count.values()):
        lanes = {s: ms for s, ms in src_to_machines.items() if ms}
        if len(lanes) >= 2:
            has_multi_cell = any(
                _is_multi_cell(node_by_id[mid]["type"])
                for mids in lanes.values()
                for mid in mids
            )
            total_machines = sum(len(ms) for ms in lanes.values())
            if has_multi_cell and total_machines > 32:
                return lanes

    # --- Sink-based detection (stackers: 2+ sources per machine, 1 sink) ---
    # Only used when source-based detection failed due to multi-ownership
    # (each machine fed by >1 source, e.g. stacker primary + secondary).
    has_multi_owner = any(c > 1 for c in machine_owner_count.values())
    if has_multi_owner:
        sink_to_machines: dict[str, list[str]] = defaultdict(list)
        machine_sink_count: dict[str, int] = defaultdict(int)

        for sid, did in abstract["edges"]:
            if node_by_id[sid]["kind"] == "machine" and node_by_id[did]["kind"] == "platform_out":
                sink_to_machines[did].append(sid)
                machine_sink_count[sid] += 1

        if all(c == 1 for c in machine_sink_count.values()):
            lanes = {s: ms for s, ms in sink_to_machines.items() if ms}
            if len(lanes) >= 2:
                return lanes

    return None


def _covers_bucket(
    model: cp_model.CpModel,
    x_a,
    x_b,
    b_lo: int,
    b_hi: int,
    tag: str,
):
    """Whether the x-interval [min(x_a,x_b), max(x_a,x_b)] covers [b_lo, b_hi].

    Returns True, False, or a fully-reified BoolVar.
    """
    a_const = isinstance(x_a, int)
    b_const = isinstance(x_b, int)

    if a_const and b_const:
        return min(x_a, x_b) <= b_hi and max(x_a, x_b) >= b_lo

    if b_const:
        return _covers_bucket(model, x_b, x_a, b_lo, b_hi, tag)

    if a_const:
        if b_lo <= x_a <= b_hi:
            return True
        cov = model.new_bool_var(tag)
        if x_a < b_lo:
            model.add(x_b >= b_lo).only_enforce_if(cov)
            model.add(x_b <= b_lo - 1).only_enforce_if(cov.negated())
        else:
            model.add(x_b <= b_hi).only_enforce_if(cov)
            model.add(x_b >= b_hi + 1).only_enforce_if(cov.negated())
        return cov

    a_le = model.new_bool_var(f"{tag}_al")
    model.add(x_a <= b_hi).only_enforce_if(a_le)
    model.add(x_a >= b_hi + 1).only_enforce_if(a_le.negated())

    b_le = model.new_bool_var(f"{tag}_bl")
    model.add(x_b <= b_hi).only_enforce_if(b_le)
    model.add(x_b >= b_hi + 1).only_enforce_if(b_le.negated())

    a_ge = model.new_bool_var(f"{tag}_ag")
    model.add(x_a >= b_lo).only_enforce_if(a_ge)
    model.add(x_a <= b_lo - 1).only_enforce_if(a_ge.negated())

    b_ge = model.new_bool_var(f"{tag}_bg")
    model.add(x_b >= b_lo).only_enforce_if(b_ge)
    model.add(x_b <= b_lo - 1).only_enforce_if(b_ge.negated())

    c1 = model.new_bool_var(f"{tag}_c1")
    model.add_bool_or([a_le, b_le]).only_enforce_if(c1)
    model.add_bool_and([a_le.negated(), b_le.negated()]).only_enforce_if(c1.negated())

    c2 = model.new_bool_var(f"{tag}_c2")
    model.add_bool_or([a_ge, b_ge]).only_enforce_if(c2)
    model.add_bool_and([a_ge.negated(), b_ge.negated()]).only_enforce_if(c2.negated())

    cov = model.new_bool_var(tag)
    model.add_bool_and([c1, c2]).only_enforce_if(cov)
    model.add_bool_or([c1.negated(), c2.negated()]).only_enforce_if(cov.negated())

    return cov


def abstract_netlist(nl: lift.Netlist) -> dict:
    """Strip coordinates from a concrete netlist, keeping only the graph.

    Returns a dict with:
      - "nodes": list of {"id": str, "type": str, "kind": str}
      - "edges": list of (src_id, dst_id)

    Node IDs are arbitrary unique strings (derived from the original position
    and kind to aid debugging). The placer assigns new physical positions.
    """
    id_for_pos: dict[tuple[int, int], str] = {}
    nodes = []
    for i, (pos, node) in enumerate(nl.nodes.items()):
        nid = f"{node.kind}{i}"
        id_for_pos[tuple(pos)] = nid
        n: dict = {"id": nid, "type": node.type, "kind": node.kind}
        if node.kind in ("platform_in", "platform_out"):
            n["orig_x"] = pos[0]
        nodes.append(n)

    edges = []
    for src, dst in nl.edges:
        src_id = id_for_pos[tuple(src)]
        dst_id = id_for_pos[tuple(dst)]
        edges.append((src_id, dst_id))

    return {"nodes": nodes, "edges": edges}


def _edge_ports(plat: dict, rotation: int) -> list[tuple[int, int]]:
    """Port positions for a given facing direction, sorted by x then y."""
    return sorted((x, y) for x, y, r in plat["ports"] if r == rotation)


def _port_rotation_for(face: int, kind: str) -> int:
    """Belt rotation for a port entity on the given platform face.

    ``platforms.json``'s per-port rotation is the direction a *source* on
    that face points to feed the interior. A sink on the same face continues
    that flow outward, i.e. the opposite (180°) rotation.
    """
    return face if kind == "platform_in" else (face + 2) % 4


_GROUP_SIZE = 4


def _port_groups(plat: dict, face: int) -> list[list[tuple[int, int]]]:
    """Partition a face's ports into groups of 4, ordered by position.

    A group is the platform's natural cluster of co-located, same-face ports
    (one per platform unit-edge) — the addressable unit for ``Group``/
    ``Region`` pins (§5).
    """
    ports = _edge_ports(plat, face)
    return [ports[i : i + _GROUP_SIZE] for i in range(0, len(ports), _GROUP_SIZE)]


def side_regions(plat: dict) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """West/east-side region group lists for ``Region`` pins (§2a).

    The western region is every west-face (0) group plus the west-most half
    of the north-face (3) groups; the eastern region mirrors this on the
    east face (2) and the east-most half of face 3. This is the Half
    Splitter's ``western_faces``/``eastern_faces`` split, generalized to any
    platform.
    """
    west_groups = _port_groups(plat, 0)
    east_groups = _port_groups(plat, 2)
    north_groups = _port_groups(plat, 3)
    half = len(north_groups) // 2
    western = [(0, i) for i in range(len(west_groups))] + [(3, i) for i in range(half)]
    eastern = [(2, i) for i in range(len(east_groups))] + [
        (3, i) for i in range(len(north_groups) - half, len(north_groups))
    ]
    return western, eastern


def group_inversions(pairs: list[tuple[int, int]]) -> int:
    """Count inversions in a source-group → sink-group permutation (§2a).

    ``pairs`` are ``(source_group_index, sink_group_index)``. An inversion is
    a pair of edges whose sink-group order disagrees with their source-group
    order — the minimum number of route crossings the placement must
    accommodate.
    """
    ordered = [sink for _src, sink in sorted(pairs)]
    return sum(
        1
        for i in range(len(ordered))
        for j in range(i + 1, len(ordered))
        if ordered[i] > ordered[j]
    )


class CrossingBudgetExceeded(ValueError):
    """Raised when a netlist's group inversions exceed routing capacity (§2a)."""


def _check_crossing_budget(abstract: dict) -> None:
    """Reject early if group-pinned ports create more inversions than routable.

    Extracts group-level source→sink pairs by tracing edges through machines,
    counts inversions, and compares to the empirically derived capacity
    (WP-N task 3d: all inversion counts up to C(n,2) converge on
    Foundation_2x4 with 4 groups at hop_range=5, single floor).
    """
    node_by_id = {n["id"]: n for n in abstract["nodes"]}
    edge_out: dict[str, list[str]] = defaultdict(list)
    for src_id, dst_id in abstract["edges"]:
        edge_out[src_id].append(dst_id)

    group_pinned_sources = [
        n for n in abstract["nodes"] if n["kind"] == "platform_in" and n.get("pin") == "group"
    ]
    if not group_pinned_sources:
        return

    def _reachable_sink_groups(start_id: str) -> set[int]:
        visited: set[str] = set()
        frontier = [start_id]
        groups: set[int] = set()
        while frontier:
            nid = frontier.pop(0)
            if nid in visited:
                continue
            visited.add(nid)
            n = node_by_id[nid]
            if n["kind"] == "platform_out" and n.get("pin") == "group":
                groups.add(n["target"][1])
                continue
            for child in edge_out.get(nid, []):
                frontier.append(child)
        return groups

    pairs: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for src in group_pinned_sources:
        src_g = src["target"][1]
        for sink_g in _reachable_sink_groups(src["id"]):
            pair = (src_g, sink_g)
            if pair not in seen:
                pairs.append(pair)
                seen.add(pair)

    if not pairs:
        return

    inversions = group_inversions(pairs)
    n_groups = max(max(s, k) for s, k in pairs) + 1
    capacity = n_groups * (n_groups - 1) // 2
    if inversions > capacity:
        raise CrossingBudgetExceeded(
            f"group permutation has {inversions} inversions but routing "
            f"capacity for {n_groups} groups is {capacity} "
            f"(empirical: WP-N task 3d)"
        )


def _assign_pinned_ports(
    plat: dict,
    nodes: list[dict],
) -> tuple[dict[str, tuple[int, int]], dict[str, int]]:
    """Assign port positions for ``Locked``/``Group``/``Region``-pinned nodes (§5).

    A ``"group"`` pin (``target = (face, group_index)``) takes the next free
    slot within that group, in node order. A ``"region"`` pin
    (``target = [(face, group_index), ...]``, a named set of groups) takes
    the next free slot across the *flattened* slot pool of every listed
    group, in node order — a thin wrapper over the same mechanism. A
    ``"locked"`` pin (``target = (x, y)``) takes that exact port position.
    Nodes without a ``"pin"`` key (``Free``, the default) are not assigned
    here.

    Returns ``(port_pos, port_rot)`` covering only the pinned node ids.
    """
    port_pos: dict[str, tuple[int, int]] = {}
    port_rot: dict[str, int] = {}
    face_for_port = {(x, y): r for x, y, r in plat["ports"]}
    group_next: dict[tuple[int, int], int] = defaultdict(int)
    region_next: dict[tuple[tuple[int, int], ...], int] = defaultdict(int)

    for n in nodes:
        pin = n.get("pin")
        if pin == "group":
            face, gidx = n["target"]
            slot = group_next[(face, gidx)]
            port_pos[n["id"]] = _port_groups(plat, face)[gidx][slot]
            group_next[(face, gidx)] += 1
            port_rot[n["id"]] = _port_rotation_for(face, n["kind"])
        elif pin == "region":
            groups = tuple((face, gidx) for face, gidx in n["target"])
            slots = [pos for face, gidx in groups for pos in _port_groups(plat, face)[gidx]]
            pos = slots[region_next[groups]]
            port_pos[n["id"]] = pos
            region_next[groups] += 1
            port_rot[n["id"]] = _port_rotation_for(face_for_port[pos], n["kind"])
        elif pin == "locked":
            pos = tuple(n["target"])
            port_pos[n["id"]] = pos
            port_rot[n["id"]] = _port_rotation_for(face_for_port[pos], n["kind"])

    return port_pos, port_rot


def place(
    abstract: dict,
    platform: str,
    *,
    forbidden: set[tuple[int, int]] | None = None,
) -> lift.Netlist:
    """Place an abstract netlist on a platform via CP-SAT.

    Args:
        abstract: dict with "nodes" and "edges" (see ``abstract_netlist``).
        platform: platform name from platforms.json (e.g. "Foundation_1x1").
        forbidden: cells where machines must not be placed (WP-M feedback).

    Returns:
        A concrete ``Netlist`` with solver-chosen positions and rotations.
    """
    plat = _load_platform(platform)
    grid_w, grid_h = plat["grid_size"]
    border = 2

    # Interior bounds: buildable area inside the platform border.
    x_min, x_max = border, grid_w - border - 1
    y_min, y_max = border, grid_h - border - 1

    # Port positions from the calibrated ports list.
    # Convention: sources default to the south wall (SOURCE_FACE, items flow
    # north into the platform), sinks default to the north wall (SINK_FACE,
    # items exit north). Abstract nodes may set a "face" key (0=west, 1=south,
    # 2=east, 3=north) to land on a different platform edge (WP-M multi-face
    # ports).
    all_source_ports = _edge_ports(plat, SOURCE_FACE)
    all_sink_ports = _edge_ports(plat, SINK_FACE)
    input_y = all_source_ports[0][1]
    output_y = all_sink_ports[0][1]

    # Index nodes by id.
    node_by_id: dict[str, dict] = {n["id"]: n for n in abstract["nodes"]}

    all_sources = [n for n in abstract["nodes"] if n["kind"] == "platform_in"]
    all_sinks = [n for n in abstract["nodes"] if n["kind"] == "platform_out"]
    machines = [n for n in abstract["nodes"] if n["kind"] == "machine"]

    # Crossing budget gate (§2a): reject early if group-pinned ports create
    # more inversions than the router can handle.
    _check_crossing_budget(abstract)

    # Locked/Group-pinned ports (§5) are assigned first, independent of the
    # Free ordering below.
    port_pos, port_rot = _assign_pinned_ports(plat, all_sources + all_sinks)
    pinned_positions = set(port_pos.values())
    source_ports = [p for p in all_source_ports if p not in pinned_positions]
    sink_ports = [p for p in all_sink_ports if p not in pinned_positions]

    # Separate the remaining (Free) sources, sinks, and machines. Sources/
    # sinks on the primary faces (SOURCE_FACE / SINK_FACE) drive the row
    # model and WP-L monotone sink ordering; sources/sinks pinned to other
    # faces are assigned ports independently, in node order.
    free_sources = [n for n in all_sources if n["id"] not in port_pos]
    free_sinks = [n for n in all_sinks if n["id"] not in port_pos]

    sources = [n for n in free_sources if n.get("face", SOURCE_FACE) == SOURCE_FACE]
    sinks = [n for n in free_sinks if n.get("face", SINK_FACE) == SINK_FACE]
    extra_sources = [n for n in free_sources if n.get("face", SOURCE_FACE) != SOURCE_FACE]
    extra_sinks = [n for n in free_sinks if n.get("face", SINK_FACE) != SINK_FACE]

    # Extra-face ports: assign sequentially from that face's free port list.
    extra_face_next: dict[int, int] = defaultdict(int)
    for n in extra_sources + extra_sinks:
        face = n["face"]
        ports = [p for p in _edge_ports(plat, face) if p not in pinned_positions]
        if extra_face_next[face] >= len(ports):
            raise ValueError(
                f"node {n['id']!r} needs a port on face {face} but all "
                f"{len(ports)} free ports there are taken"
            )
        port_pos[n["id"]] = ports[extra_face_next[face]]
        extra_face_next[face] += 1
        port_rot[n["id"]] = _port_rotation_for(face, n["kind"])

    # Assign primary-face port positions from the actual port list, left to
    # right. To avoid route crossings, order sinks to match the source
    # ordering: trace each source → machines → sink chain, then assign the
    # sink that a leftmost source feeds to the leftmost sink port, etc.
    primary_src_rot = _port_rotation_for(SOURCE_FACE, "platform_in")
    primary_sink_rot = _port_rotation_for(SINK_FACE, "platform_out")

    if len(sources) > len(source_ports):
        raise ValueError(
            f"{len(sources)} sources need free ports on face {SOURCE_FACE} "
            f"but only {len(source_ports)} remain after pinning"
        )
    for i, src in enumerate(sources):
        port_pos[src["id"]] = source_ports[i]
        port_rot[src["id"]] = primary_src_rot

    # Build the src → sink mapping by tracing through machine edges.
    edge_out: dict[str, list[str]] = {}
    for sid, did in abstract["edges"]:
        edge_out.setdefault(sid, []).append(did)

    def _trace_all_sinks(src_id: str) -> list[str]:
        """BFS from src through machines, return reachable primary-face sinks."""
        visited: set[str] = set()
        frontier = [src_id]
        found: list[str] = []
        while frontier:
            nid = frontier.pop(0)
            if nid in visited:
                continue
            visited.add(nid)
            n = node_by_id[nid]
            if n["kind"] == "platform_out":
                if n.get("face", SINK_FACE) == SINK_FACE and nid not in port_pos:
                    found.append(nid)
                continue
            for child in edge_out.get(nid, []):
                frontier.append(child)
        return found

    # Order sinks to match source x-ordering. For 1-in/1-out machines each
    # source traces to exactly one sink. For multi-input machines (swapper)
    # one source may reach multiple sinks; BFS visits them in edge order so
    # the leftmost source's reachable sinks fill leftmost port slots first.
    ordered_sinks: list[str] = []
    src_by_x = sorted(sources, key=lambda s: port_pos[s["id"]][0])
    seen_sinks: set[str] = set()
    for src in src_by_x:
        for sink_id in _trace_all_sinks(src["id"]):
            if sink_id not in seen_sinks:
                ordered_sinks.append(sink_id)
                seen_sinks.add(sink_id)
    for sink in sinks:
        if sink["id"] not in seen_sinks:
            ordered_sinks.append(sink["id"])

    if len(ordered_sinks) > len(sink_ports):
        raise ValueError(
            f"{len(ordered_sinks)} sinks need free ports on face {SINK_FACE} "
            f"but only {len(sink_ports)} remain after pinning"
        )
    for i, sink_id in enumerate(ordered_sinks):
        port_pos[sink_id] = sink_ports[i]
        port_rot[sink_id] = primary_sink_rot

    if not machines:
        return _build_netlist(abstract, port_pos, port_rot, {})

    # Detect off-primary-face sinks early (used by both band constraints
    # and the balance objective).
    primary_sink_positions = set(_edge_ports(plat, SINK_FACE))
    off_face_sink_ys = [
        port_pos[n["id"]][1]
        for n in abstract["nodes"]
        if n["kind"] == "platform_out"
        and n["id"] in port_pos
        and port_pos[n["id"]] not in primary_sink_positions
    ]

    # --- Stage computation (WP-M row model → WP-N band model) ---
    stages = _compute_stages(abstract)
    n_stages = max(stages.values()) + 1

    # --- WP-O: detect fan topology for columnar placement ---
    fan_lanes = _detect_fan_topology(abstract, stages)

    # --- CP-SAT model ---
    model = cp_model.CpModel()

    # Machine variables: x is free within interior, y depends on layout model,
    # r is rotation 0–3.
    m_x: dict[str, cp_model.IntVar] = {}
    m_y: dict[str, cp_model.IntVar] = {}
    m_r: dict[str, cp_model.IntVar] = {}

    band_lo: list[cp_model.IntVar] = []
    band_hi: list[cp_model.IntVar] = []

    if fan_lanes is not None:
        # --- COLUMN MODEL (WP-O): fan topologies ---
        # Each lane's machines get a vertical column (shared x-band) instead
        # of a horizontal stage band.  Machines stack vertically within the
        # column; the output clearance constraint (y-spacing >= 3) enforces
        # separation.  No band variables needed.
        assert input_y < output_y, "south-to-north flow convention violated"
        flow_r = 1

        for m in machines:
            mid = m["id"]
            m_x[mid] = model.new_int_var(x_min, x_max, f"x_{mid}")
            m_y[mid] = model.new_int_var(input_y + 3, output_y - 3, f"y_{mid}")
            m_r[mid] = model.new_int_var(flow_r, flow_r, f"r_{mid}")

        # Column variables: per-lane x-extent.
        col_lo_x: dict[str, cp_model.IntVar] = {}
        col_hi_x: dict[str, cp_model.IntVar] = {}
        src_x_for_col: dict[str, int] = {}

        for sid, mids in fan_lanes.items():
            col_lo_x[sid] = model.new_int_var(x_min, x_max, f"clo_{sid}")
            col_hi_x[sid] = model.new_int_var(x_min, x_max, f"chi_{sid}")
            model.add(col_hi_x[sid] - col_lo_x[sid] <= 1)
            model.add(col_hi_x[sid] >= col_lo_x[sid])
            src_x_for_col[sid] = port_pos[sid][0]

            for mid in mids:
                if mid not in m_x:
                    continue
                model.add(m_x[mid] >= col_lo_x[sid])
                model.add(m_x[mid] <= col_hi_x[sid])

        # Cross-column ordering by source port x.  Gap of 2 between column
        # bounds ensures at least 1 empty routing cell between adjacent columns.
        sorted_col_sids = sorted(fan_lanes, key=lambda s: src_x_for_col[s])
        for i in range(len(sorted_col_sids) - 1):
            left = sorted_col_sids[i]
            right = sorted_col_sids[i + 1]
            model.add(col_hi_x[left] + 2 <= col_lo_x[right])

        # In-column vertical spacing: machines in the same lane need y-spacing
        # >= 3 so each machine's input/output approach cells don't conflict.
        for sid, mids in fan_lanes.items():
            placed_mids = [mid for mid in mids if mid in m_y]
            for i in range(len(placed_mids)):
                for j in range(i + 1, len(placed_mids)):
                    ai, aj = placed_mids[i], placed_mids[j]
                    abs_dy = model.new_int_var(0, grid_h, f"cldy_{ai}_{aj}")
                    model.add_abs_equality(abs_dy, m_y[ai] - m_y[aj])
                    model.add(abs_dy >= 3)

    else:
        # --- BAND MODEL (serial topologies) ---
        # Stage bands: each stage gets a y-interval [band_lo, band_hi].
        band_lo = [model.new_int_var(y_min, y_max, f"band_lo_{s}") for s in range(n_stages)]
        band_hi = [model.new_int_var(y_min, y_max, f"band_hi_{s}") for s in range(n_stages)]
        stage_counts = [0] * n_stages
        for m in machines:
            stage_counts[stages[m["id"]]] += 1
        for s in range(n_stages):
            model.add(band_hi[s] >= band_lo[s])
            mc = stage_counts[s]
            interior_h = plat.get("interior", plat.get("grid_size", [0, 0]))[1]
            if mc > 16 and interior_h >= 30:
                est_rows = max(2, (mc + 15) // 16)
                min_height = 4 * est_rows - 3
                model.add(band_hi[s] - band_lo[s] >= min_height)

        if input_y > output_y:
            model.add(band_hi[0] <= input_y - 3)
            model.add(band_lo[-1] >= output_y + 3)
            for s in range(n_stages - 1):
                model.add(band_lo[s] >= band_hi[s + 1] + 3)
        else:
            model.add(band_lo[0] >= input_y + 3)
            if off_face_sink_ys:
                max_sink_y = max(off_face_sink_ys)
                band_ceil = max(max_sink_y + 8, input_y + 3 + 3 * n_stages)
                model.add(band_hi[-1] <= min(band_ceil, output_y - 3))
            else:
                model.add(band_hi[-1] <= output_y - 3)
            for s in range(n_stages - 1):
                model.add(band_lo[s + 1] >= band_hi[s] + 3)

        for m in machines:
            mid = m["id"]
            s = stages[mid]
            m_x[mid] = model.new_int_var(x_min, x_max, f"x_{mid}")
            m_y[mid] = model.new_int_var(y_min, y_max, f"y_{mid}")
            model.add(m_y[mid] >= band_lo[s])
            model.add(m_y[mid] <= band_hi[s])
            m_r[mid] = model.new_int_var(0, 3, f"r_{mid}")

    # No overlap: all occupied cells must be distinct.
    # Encode as AllDifferent(x_i * H + y_i) where H > max y range.
    h = grid_h + 1
    flat_positions = []
    for mid in m_x:
        flat = model.new_int_var(0, grid_w * h + grid_h, f"flat_{mid}")
        model.add(flat == m_x[mid] * h + m_y[mid])
        flat_positions.append(flat)

    # Multi-cell machines: add second-cell position variables.
    second_x: dict[str, cp_model.IntVar] = {}
    second_y: dict[str, cp_model.IntVar] = {}
    for m in machines:
        mid = m["id"]
        if not _is_multi_cell(m["type"]):
            continue
        dx_tab, dy_tab = _second_cell_tables(m["type"])

        sdx = model.new_int_var(-1, 1, f"sdx_{mid}")
        sdy = model.new_int_var(-1, 1, f"sdy_{mid}")
        model.add_element(m_r[mid], dx_tab, sdx)
        model.add_element(m_r[mid], dy_tab, sdy)

        sx = model.new_int_var(x_min, x_max, f"sx_{mid}")
        sy = model.new_int_var(y_min, y_max, f"sy_{mid}")
        model.add(sx == m_x[mid] + sdx)
        model.add(sy == m_y[mid] + sdy)
        second_x[mid] = sx
        second_y[mid] = sy

        flat2 = model.new_int_var(0, grid_w * h + grid_h, f"flat2_{mid}")
        model.add(flat2 == sx * h + sy)
        flat_positions.append(flat2)

    # WP-O: constrain second cells within their lane's column.
    if fan_lanes is not None:
        mid_to_lane = {mid: sid for sid, mids in fan_lanes.items() for mid in mids}
        for mid, sx in second_x.items():
            sid = mid_to_lane.get(mid)
            if sid is not None and sid in col_lo_x:
                model.add(sx >= col_lo_x[sid])
                model.add(sx <= col_hi_x[sid])

    # Output clearance for multi-cell fan-out groups: within each group of
    # multi-cell machines sharing a source, machine pairs at the same x-column
    # (anchor or second cell) must have y-spacing >= 3.  At spacing 2, the
    # single cell between machines is both the output approach of one and the
    # input approach of the next — two nets share a terminal cell that can't
    # host both flows.  Spacing 3 leaves 2 routing cells between machines.
    fanout_groups: dict[str, list[str]] = defaultdict(list)
    for src_id, dst_id in abstract["edges"]:
        if node_by_id[dst_id]["kind"] == "machine":
            fanout_groups[src_id].append(dst_id)
    for _src, members in fanout_groups.items():
        mc_members = [
            mid for mid in members if _is_multi_cell(node_by_id[mid]["type"]) and mid in m_x
        ]
        if len(mc_members) < 2:
            continue
        for i in range(len(mc_members)):
            for j in range(i + 1, len(mc_members)):
                ai, aj = mc_members[i], mc_members[j]
                abs_dy = model.new_int_var(0, grid_h, f"mcdy_{ai}_{aj}")
                model.add_abs_equality(abs_dy, m_y[ai] - m_y[aj])
                same_x = model.new_bool_var(f"samex_{ai}_{aj}")
                model.add(m_x[ai] == m_x[aj]).only_enforce_if(same_x)
                model.add(m_x[ai] != m_x[aj]).only_enforce_if(same_x.negated())
                model.add(abs_dy >= 3).only_enforce_if(same_x)
                if ai in second_x:
                    same_sx = model.new_bool_var(f"samesx_{ai}_{aj}")
                    model.add(second_x[ai] == m_x[aj]).only_enforce_if(same_sx)
                    model.add(second_x[ai] != m_x[aj]).only_enforce_if(same_sx.negated())
                    model.add(abs_dy >= 3).only_enforce_if(same_sx)
                if aj in second_x:
                    same_xs = model.new_bool_var(f"samexs_{ai}_{aj}")
                    model.add(m_x[ai] == second_x[aj]).only_enforce_if(same_xs)
                    model.add(m_x[ai] != second_x[aj]).only_enforce_if(same_xs.negated())
                    model.add(abs_dy >= 3).only_enforce_if(same_xs)

    # Also exclude port positions from ALL occupied cells.
    for pos in port_pos.values():
        fixed_flat = pos[0] * h + pos[1]
        for fp in flat_positions:
            model.add(fp != fixed_flat)

    if len(flat_positions) >= 2:
        model.add_all_different(flat_positions)

    # Forbidden cells (WP-M feedback): machines must not occupy these positions.
    if forbidden:
        for fx, fy in forbidden:
            ff = fx * h + fy
            for fp in flat_positions:
                model.add(fp != ff)

    # --- Density constraints (WP-M channel capacity) ---
    # Skipped for fan topologies (WP-O): column width ≤ 2 is within hop range,
    # so intra-lane routing doesn't create wide channels.
    if fan_lanes is None:
        primary_port_ids = {n["id"] for n in sources} | set(ordered_sinks)
        all_px = [x for x, _ in port_pos.values()]
        bkt_lo = min(x_min, *all_px)
        bkt_hi = max(x_max, *all_px)
        n_bkt = (bkt_hi - bkt_lo + _BUCKET_WIDTH) // _BUCKET_WIDTH + 1

        if input_y > output_y:
            ch_h = [input_y - band_hi[0] - 1]
            for s in range(n_stages - 1):
                ch_h.append(band_lo[s] - band_hi[s + 1] - 1)
            ch_h.append(band_lo[-1] - output_y - 1)
        else:
            ch_h = [band_lo[0] - input_y - 1]
            for s in range(n_stages - 1):
                ch_h.append(band_lo[s + 1] - band_hi[s] - 1)
            ch_h.append(output_y - band_hi[-1] - 1)

        ch_edges: dict[tuple[int, int | None], list[tuple]] = defaultdict(list)
        for sid, did in abstract["edges"]:
            sn, dn = node_by_id[sid], node_by_id[did]
            if sn["kind"] == "platform_in" and sid not in primary_port_ids:
                continue
            if dn["kind"] == "platform_out" and did not in primary_port_ids:
                continue
            xs = _node_x(sid, sn, port_pos, m_x, model)
            xd = _node_x(did, dn, port_pos, m_x, model)
            if sn["kind"] == "platform_in":
                ci = 0
                grp = sn.get("target", (None, None))[1] if sn.get("pin") == "group" else None
            elif sn["kind"] == "machine":
                ci = stages[sid] + 1
                grp = None
            else:
                continue
            ch_edges[(ci, grp)].append((xs, xd))

        for ci in range(n_stages + 1):
            group_keys = sorted(
                {g for c, g in ch_edges if c == ci},
                key=lambda g: (g is not None, g),
            )
            for grp in group_keys:
                edges_cg = ch_edges.get((ci, grp), [])
                if not edges_cg:
                    continue
                for b in range(n_bkt):
                    bl = bkt_lo + b * _BUCKET_WIDTH
                    bh = min(bl + _BUCKET_WIDTH - 1, bkt_hi)
                    terms: list = []
                    fixed = 0
                    for ei, (xs, xd) in enumerate(edges_cg):
                        c = _covers_bucket(model, xs, xd, bl, bh, f"d{ci}g{grp}b{b}e{ei}")
                        if isinstance(c, bool):
                            if c:
                                fixed += 1
                        else:
                            terms.append(c)
                    if terms or fixed > 0:
                        model.add(sum(terms) + fixed <= ch_h[ci])

    # Port position sets used by both rotation and minimum-spacing constraints.
    primary_src_pos = set(_edge_ports(plat, SOURCE_FACE))
    primary_sink_pos = set(_edge_ports(plat, SINK_FACE))

    # Rotation constraints: for fan topologies (WP-O), rotation is fixed to
    # flow_r in the variable domain — no element constraints needed.  For band
    # topologies, constrain each machine's output to face toward its downstream
    # neighbour.
    if fan_lanes is None:
        out_dx_table = [1, 0, -1, 0]  # R=0→E, R=1→N, R=2→W, R=3→S
        out_dy_table = [0, 1, 0, -1]
        in_dx_table = [-1, 0, 1, 0]  # input is opposite: W, S, E, N
        in_dy_table = [0, -1, 0, 1]

        assert input_y < output_y, "south-to-north flow convention violated"
        flow_r = 1

        for ei, (src_id, dst_id) in enumerate(abstract["edges"]):
            src_node = node_by_id[src_id]
            dst_node = node_by_id[dst_id]

            if src_node["kind"] == "machine":
                if dst_node["kind"] == "platform_out" and port_pos[dst_id] not in primary_sink_pos:
                    model.add(m_r[src_id] == flow_r)
                else:
                    sx = m_x[src_id]
                    sy = m_y[src_id]
                    dx = _node_x(dst_id, dst_node, port_pos, m_x, model)
                    dy = _node_y(dst_id, dst_node, port_pos, m_y, model)
                    _add_output_faces_toward(
                        model,
                        m_r[src_id],
                        sx,
                        sy,
                        dx,
                        dy,
                        out_dx_table,
                        out_dy_table,
                        grid_w,
                        grid_h,
                        f"eout_{ei}",
                    )

            if dst_node["kind"] == "machine":
                if src_node["kind"] == "platform_in" and port_pos[src_id] not in primary_src_pos:
                    model.add(m_r[dst_id] == flow_r)
                else:
                    dx2 = m_x[dst_id]
                    dy2 = m_y[dst_id]
                    sx2 = _node_x(src_id, src_node, port_pos, m_x, model)
                    sy2 = _node_y(src_id, src_node, port_pos, m_y, model)
                    _add_output_faces_toward(
                        model,
                        m_r[dst_id],
                        dx2,
                        dy2,
                        sx2,
                        sy2,
                        in_dx_table,
                        in_dy_table,
                        grid_w,
                        grid_h,
                        f"ein_{ei}",
                    )

    # Fan-out blocks (band model only): the column model's cross-column
    # ordering (WP-O) subsumes this for fan topologies.
    if fan_lanes is None:
        fan_out_groups: defaultdict[str, list[str]] = defaultdict(list)
        for sid, did in abstract["edges"]:
            fan_out_groups[sid].append(did)

        candidate_src_ids = [
            sid
            for sid in fan_out_groups
            if node_by_id[sid]["kind"] == "platform_in"
            and sum(1 for m in fan_out_groups[sid] if node_by_id[m]["kind"] == "machine") >= 1
        ]
        fanout_by_src: dict[str, list[str]] = {}
        src_x_for_id: dict[str, int] = {}
        for sid in candidate_src_ids:
            fanout_by_src[sid] = [
                m for m in fan_out_groups[sid] if node_by_id[m]["kind"] == "machine"
            ]
            src_x_for_id[sid] = port_pos[sid][0]
        machine_owner_count: dict[str, int] = defaultdict(int)
        for sid in candidate_src_ids:
            for mid in fanout_by_src[sid]:
                machine_owner_count[mid] += 1
        fanout_src_ids = [
            sid
            for sid in candidate_src_ids
            if all(machine_owner_count[mid] == 1 for mid in fanout_by_src[sid])
        ]
        sorted_src_ids = sorted(fanout_src_ids, key=lambda s: src_x_for_id[s])

        block_lo_x: dict[str, cp_model.IntVar] = {}
        block_hi_x: dict[str, cp_model.IntVar] = {}
        for sid in sorted_src_ids:
            members = fanout_by_src[sid]
            all_x_vars = []
            for mid in members:
                if mid in m_x:
                    all_x_vars.append(m_x[mid])
                if mid in second_x:
                    all_x_vars.append(second_x[mid])
            if all_x_vars:
                lo = model.new_int_var(x_min, x_max, f"blo_{sid}")
                hi = model.new_int_var(x_min, x_max, f"bhi_{sid}")
                model.add_min_equality(lo, all_x_vars)
                model.add_max_equality(hi, all_x_vars)
                block_lo_x[sid] = lo
                block_hi_x[sid] = hi

        for i in range(len(sorted_src_ids) - 1):
            left_sid = sorted_src_ids[i]
            right_sid = sorted_src_ids[i + 1]
            if left_sid in block_hi_x and right_sid in block_lo_x:
                model.add(block_hi_x[left_sid] + 1 <= block_lo_x[right_sid])

    # Minimum spacing between connected nodes: at least 2 Manhattan distance
    # (room for one belt cell between machine and its source/sink).  Edges to
    # off-primary-face ports need 3 so the machine's input/output routes don't
    # collide at the sink's approach cell (the flow-direction facing constraint
    # no longer implicitly separates them by forcing y toward the sink).
    for ei, (src_id, dst_id) in enumerate(abstract["edges"]):
        src_node = node_by_id[src_id]
        dst_node = node_by_id[dst_id]

        sx = _node_x(src_id, src_node, port_pos, m_x, model)
        sy = _node_y(src_id, src_node, port_pos, m_y, model)
        dx = _node_x(dst_id, dst_node, port_pos, m_x, model)
        dy = _node_y(dst_id, dst_node, port_pos, m_y, model)

        min_spacing = 2
        if dst_node["kind"] == "platform_out" and port_pos[dst_id] not in primary_sink_pos:
            min_spacing = 3
        elif src_node["kind"] == "platform_in" and port_pos[src_id] not in primary_src_pos:
            min_spacing = 3

        abs_dx = model.new_int_var(0, grid_w, f"spc_adx_{ei}")
        abs_dy = model.new_int_var(0, grid_h, f"spc_ady_{ei}")
        model.add_abs_equality(abs_dx, sx - dx)
        model.add_abs_equality(abs_dy, sy - dy)
        model.add(abs_dx + abs_dy >= min_spacing)

    # Objective: minimize total wire length.
    # For multi-cell machines, also add second-cell distances so the solver
    # prefers placements where both cells are near connected nodes.
    total_wire = []
    for src_id, dst_id in abstract["edges"]:
        src_node = node_by_id[src_id]
        dst_node = node_by_id[dst_id]

        sx = _node_x(src_id, src_node, port_pos, m_x, model)
        sy = _node_y(src_id, src_node, port_pos, m_y, model)
        dx = _node_x(dst_id, dst_node, port_pos, m_x, model)
        dy = _node_y(dst_id, dst_node, port_pos, m_y, model)

        abs_dx = model.new_int_var(0, grid_w, f"adx_{src_id}_{dst_id}")
        abs_dy = model.new_int_var(0, grid_h, f"ady_{src_id}_{dst_id}")
        model.add_abs_equality(abs_dx, sx - dx)
        model.add_abs_equality(abs_dy, sy - dy)
        total_wire.append(abs_dx)
        total_wire.append(abs_dy)

        if dst_id in second_x:
            a2dx = model.new_int_var(0, grid_w, f"a2dx_in_{src_id}_{dst_id}")
            a2dy = model.new_int_var(0, grid_h, f"a2dy_in_{src_id}_{dst_id}")
            model.add_abs_equality(a2dx, sx - second_x[dst_id])
            model.add_abs_equality(a2dy, sy - second_y[dst_id])
            total_wire.append(a2dx)
            total_wire.append(a2dy)

        if src_id in second_x:
            a2dx = model.new_int_var(0, grid_w, f"a2dx_out_{src_id}_{dst_id}")
            a2dy = model.new_int_var(0, grid_h, f"a2dy_out_{src_id}_{dst_id}")
            model.add_abs_equality(a2dx, second_x[src_id] - dx)
            model.add_abs_equality(a2dy, second_y[src_id] - dy)
            total_wire.append(a2dx)
            total_wire.append(a2dy)

    if fan_lanes is not None:
        # Column span compactness: prefer tight packing of all columns.
        if len(sorted_col_sids) >= 2:
            span = model.new_int_var(0, x_max - x_min, "col_span")
            model.add(span == col_hi_x[sorted_col_sids[-1]] - col_lo_x[sorted_col_sids[0]])
            total_wire.append(span)
    else:
        # Band balance: prefer bands near the vertical center.
        if off_face_sink_ys:
            avg_sink_y = sum(off_face_sink_ys) // len(off_face_sink_ys)
            mid_y = (input_y + avg_sink_y) // 2
        else:
            mid_y = (input_y + output_y) // 2
        bal_weight = len(off_face_sink_ys) if off_face_sink_ys else 1
        for s in range(n_stages):
            bal = model.new_int_var(0, 2 * grid_h, f"bal_{s}")
            model.add_abs_equality(bal, band_lo[s] + band_hi[s] - 2 * mid_y)
            wbal = model.new_int_var(0, bal_weight * 2 * grid_h, f"wbal_{s}")
            model.add(wbal == bal * bal_weight)
            total_wire.append(wbal)

        # Band compactness.
        stage_mcnt = [0] * n_stages
        for m in machines:
            stage_mcnt[stages[m["id"]]] += 1
        for s in range(n_stages):
            bw = model.new_int_var(0, y_max - y_min, f"bw_{s}")
            model.add(bw == band_hi[s] - band_lo[s])
            w = 2 * stage_mcnt[s]
            if w > 0:
                sbw = model.new_int_var(0, w * (y_max - y_min), f"sbw_{s}")
                model.add(sbw == w * bw)
                total_wire.append(sbw)

    # Ring avoidance: small penalty for machines on the port-ring x-columns.
    # The _build_passable ring exclusion blocks non-port cells on these
    # columns, so a machine there can't have routable I/O cells.  The
    # penalty is soft (doesn't restrict the domain) to keep tight layouts
    # feasible when every column is needed.
    port_xs = [p[0] for p in plat["ports"]]
    ring_xs = {min(port_xs), max(port_xs)}
    for mid in m_x:
        for rx in ring_xs:
            on_ring = model.new_bool_var(f"ring_{mid}_{rx}")
            model.add(m_x[mid] == rx).only_enforce_if(on_ring)
            model.add(m_x[mid] != rx).only_enforce_if(on_ring.negated())
            total_wire.append(on_ring * 4)

    model.minimize(sum(total_wire))

    # Search strategy: when off-face sinks pull the balance target low, tell
    # the solver to branch on y-variables with low values first.  Without
    # this, CP-SAT's default search finds a feasible solution in the high-y
    # region and can't escape within the time limit.
    if off_face_sink_ys:
        if fan_lanes is not None:
            y_vars = [m_y[mid] for mid in m_y]
        else:
            y_vars = list(band_lo) + list(band_hi) + [m_y[mid] for mid in m_y]
        model.add_decision_strategy(
            y_vars,
            cp_model.CHOOSE_FIRST,
            cp_model.SELECT_MIN_VALUE,
        )

    # Solve.
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10.0
    status = solver.solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(f"CP-SAT placement failed: status={status}")

    # Extract machine positions.
    machine_positions: dict[str, tuple[int, int, int]] = {}
    for m in machines:
        mid = m["id"]
        machine_positions[mid] = (
            solver.value(m_x[mid]),
            solver.value(m_y[mid]),
            solver.value(m_r[mid]),
        )

    return _build_netlist(abstract, port_pos, port_rot, machine_positions)


def _add_output_faces_toward(
    model: cp_model.CpModel,
    r_var: cp_model.IntVar,
    ux,
    uy,
    vx,
    vy,
    dx_table: list[int],
    dy_table: list[int],
    grid_w: int,
    grid_h: int,
    tag: str,
) -> None:
    """Constrain rotation so the direction (from dx/dy_table) faces toward (vx, vy).

    Encodes: dx_table[r]*(vx - ux) + dy_table[r]*(vy - uy) >= 1.
    Uses element constraints to look up direction components by r_var.
    """
    dir_dx = model.new_int_var(-1, 1, f"ddx_{tag}")
    dir_dy = model.new_int_var(-1, 1, f"ddy_{tag}")
    model.add_element(r_var, dx_table, dir_dx)
    model.add_element(r_var, dy_table, dir_dy)

    # dot = dir_dx * (vx - ux) + dir_dy * (vy - uy)
    # Since dir_dx/dy are {-1,0,1} and deltas can be up to grid size,
    # use intermediate products.
    delta_x = model.new_int_var(-grid_w, grid_w, f"deltax_{tag}")
    delta_y = model.new_int_var(-grid_h, grid_h, f"deltay_{tag}")
    model.add(delta_x == vx - ux)
    model.add(delta_y == vy - uy)

    prod_x = model.new_int_var(-grid_w, grid_w, f"prodx_{tag}")
    prod_y = model.new_int_var(-grid_h, grid_h, f"prody_{tag}")
    model.add_multiplication_equality(prod_x, [dir_dx, delta_x])
    model.add_multiplication_equality(prod_y, [dir_dy, delta_y])

    model.add(prod_x + prod_y >= 1)


def _node_x(nid, node, port_pos, m_x, model):
    if node["kind"] in ("platform_in", "platform_out"):
        return port_pos[nid][0]
    return m_x[nid]


def _node_y(nid, node, port_pos, m_y, model):
    if node["kind"] in ("platform_in", "platform_out"):
        return port_pos[nid][1]
    return m_y[nid]


def _assign_ports(
    neighbor_positions: list[tuple[int, int]],
    port_cells: list[tuple[int, int]],
) -> list[int]:
    """Assign neighbors to port cells by monotone (non-crossing) matching.

    A multi-cell machine's port cells are adjacent and differ along one
    axis (e.g. a cutter's anchor/second-cell output ports). Sorting both the
    port cells and the neighbors along that axis (breaking ties on the other
    axis) and pairing them positionally avoids the crossed assignments a
    pure nearest-neighbor match can produce when the neighbors fall on the
    same side of the machine — e.g. a cutter's west/east-half outputs both
    routed to Region sinks on the platform's north face (§7.2 WP-M2).

    Returns result[i] = index of the port cell assigned to neighbor i.
    """
    n = len(port_cells)
    if n <= 1:
        return [0] * len(neighbor_positions)

    xs = [p[0] for p in port_cells]
    ys = [p[1] for p in port_cells]
    axis = 0 if max(xs) - min(xs) >= max(ys) - min(ys) else 1
    other = 1 - axis

    port_order = sorted(range(n), key=lambda j: (port_cells[j][axis], port_cells[j][other]))
    nbr_order = sorted(
        range(len(neighbor_positions)),
        key=lambda i: (neighbor_positions[i][axis], neighbor_positions[i][other]),
    )

    assigned = [0] * len(neighbor_positions)
    for nbr_idx, port_idx in zip(nbr_order, port_order):
        assigned[nbr_idx] = port_idx
    return assigned


def _build_netlist(
    abstract: dict,
    port_pos: dict[str, tuple[int, int]],
    port_rot: dict[str, int],
    machine_positions: dict[str, tuple[int, int, int]],
) -> lift.Netlist:
    """Assemble a concrete Netlist from solver results."""
    node_by_id = {n["id"]: n for n in abstract["nodes"]}

    pos_for_id: dict[str, tuple[int, int]] = {}
    nodes: dict[tuple[int, int], lift.Node] = {}

    for nid, pos in port_pos.items():
        pos_for_id[nid] = pos
        n = node_by_id[nid]
        nodes[pos] = lift.Node(
            x=pos[0],
            y=pos[1],
            layer=0,
            type=n["type"],
            kind=n["kind"],
            rotation=port_rot[nid],
        )

    for nid, (x, y, r) in machine_positions.items():
        pos = (x, y)
        pos_for_id[nid] = pos
        n = node_by_id[nid]
        nodes[pos] = lift.Node(
            x=x,
            y=y,
            layer=0,
            type=n["type"],
            kind="machine",
            rotation=r,
        )

    # Build port cells for multi-cell machines.  Include cross-floor input
    # cells (e.g. stacker L+1 claim) so that multi-input port assignment can
    # split primary (L0) and secondary (L+1) edges.
    machine_in_cells: dict[str, list[tuple]] = {}
    machine_out_cells: dict[str, list[tuple[int, int]]] = {}
    for nid, (x, y, r) in machine_positions.items():
        n = node_by_id[nid]
        fp = lift._machine_footprint(n["type"], r)
        ins: list[tuple] = []
        for (dx, dy, dl), (i, _o) in fp.items():
            if i:
                ins.append((x + dx, y + dy) if dl == 0 else (x + dx, y + dy, dl))
        outs = [(x + dx, y + dy) for (dx, dy, dl), (_i, o) in fp.items() if o and dl == 0]
        machine_in_cells[nid] = ins
        machine_out_cells[nid] = outs

    # Group abstract edges by machine for port assignment.
    edges_into: defaultdict[str, list[str]] = defaultdict(list)
    edges_from: defaultdict[str, list[str]] = defaultdict(list)
    for sid, did in abstract["edges"]:
        if node_by_id[did]["kind"] == "machine":
            edges_into[did].append(sid)
        if node_by_id[sid]["kind"] == "machine":
            edges_from[sid].append(did)

    # Pre-compute port assignments for multi-cell machines.
    in_port_map: dict[str, dict[str, int]] = {}
    out_port_map: dict[str, dict[str, int]] = {}
    for nid in machine_positions:
        in_cells = machine_in_cells[nid]
        if len(in_cells) > 1:
            srcs = edges_into[nid]
            src_pos = [pos_for_id[s] for s in srcs]
            assignment = _assign_ports(src_pos, in_cells)
            in_port_map[nid] = dict(zip(srcs, assignment))

        out_cells = machine_out_cells[nid]
        if len(out_cells) > 1:
            dsts = edges_from[nid]
            dst_pos = [pos_for_id[d] for d in dsts]
            assignment = _assign_ports(dst_pos, out_cells)
            out_port_map[nid] = dict(zip(dsts, assignment))

    # Build edges (anchor-level) and port_edges (cell-level).
    edges: list[tuple[tuple[int, int], tuple[int, int]]] = []
    port_edges: list[tuple[tuple[int, int], tuple[int, int]]] = []

    for src_id, dst_id in abstract["edges"]:
        src_anchor = pos_for_id[src_id]
        dst_anchor = pos_for_id[dst_id]
        edges.append((src_anchor, dst_anchor))

        # Source cell: anchor by default, or assigned output port.
        src_cell = src_anchor
        if src_id in out_port_map:
            idx = out_port_map[src_id][dst_id]
            src_cell = machine_out_cells[src_id][idx]

        # Dest cell: anchor by default, or assigned input port.
        dst_cell = dst_anchor
        if dst_id in in_port_map:
            idx = in_port_map[dst_id][src_id]
            dst_cell = machine_in_cells[dst_id][idx]

        port_edges.append((src_cell, dst_cell))

    return lift.Netlist(nodes=nodes, edges=edges, port_edges=port_edges)
