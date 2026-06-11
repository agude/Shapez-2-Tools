"""Machine placement via OR-Tools CP-SAT (WP-D + WP-M row model).

Given an abstract netlist (node types/kinds + edges, no coordinates) and a
platform, assigns (x, y, rotation) to each node using constraint programming.
Sources and sinks are fixed at platform-edge positions; machines are placed
in the interior with no-overlap and wire-length minimization.

Machines are assigned to **stage rows**: each stage (depth from sources) maps
to a single y-coordinate shared by all machines at that depth. Routing channels
between rows have a minimum height of 2 cells, replacing the hand-tuned
y-stagger and port-row margin constraints from WP-D.

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


def _assign_pinned_ports(
    plat: dict, nodes: list[dict],
) -> tuple[dict[str, tuple[int, int]], dict[str, int]]:
    """Assign port positions for ``Locked``/``Group``-pinned nodes (§5).

    A ``"group"`` pin (``target = (face, group_index)``) takes the next free
    slot within that group, in node order. A ``"locked"`` pin
    (``target = (x, y)``) takes that exact port position. Nodes without a
    ``"pin"`` key (``Free``, the default) are not assigned here.

    Returns ``(port_pos, port_rot)`` covering only the pinned node ids.
    """
    port_pos: dict[str, tuple[int, int]] = {}
    port_rot: dict[str, int] = {}
    face_for_port = {(x, y): r for x, y, r in plat["ports"]}
    group_next: dict[tuple[int, int], int] = defaultdict(int)

    for n in nodes:
        pin = n.get("pin")
        if pin == "group":
            face, gidx = n["target"]
            slot = group_next[(face, gidx)]
            port_pos[n["id"]] = _port_groups(plat, face)[gidx][slot]
            group_next[(face, gidx)] += 1
            port_rot[n["id"]] = _port_rotation_for(face, n["kind"])
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
    # Convention: sources default to the north wall (face 3, items flow south
    # into the platform), sinks default to the south wall (face 1, items exit
    # south). Abstract nodes may set a "face" key (0=west, 1=south, 2=east,
    # 3=north) to land on a different platform edge (WP-M multi-face ports).
    all_source_ports = _edge_ports(plat, 3)
    all_sink_ports = _edge_ports(plat, 1)
    input_y = all_source_ports[0][1]
    output_y = all_sink_ports[0][1]

    # Index nodes by id.
    node_by_id: dict[str, dict] = {n["id"]: n for n in abstract["nodes"]}

    all_sources = [n for n in abstract["nodes"] if n["kind"] == "platform_in"]
    all_sinks = [n for n in abstract["nodes"] if n["kind"] == "platform_out"]
    machines = [n for n in abstract["nodes"] if n["kind"] == "machine"]

    # Locked/Group-pinned ports (§5) are assigned first, independent of the
    # Free ordering below.
    port_pos, port_rot = _assign_pinned_ports(plat, all_sources + all_sinks)
    pinned_positions = set(port_pos.values())
    source_ports = [p for p in all_source_ports if p not in pinned_positions]
    sink_ports = [p for p in all_sink_ports if p not in pinned_positions]

    # Separate the remaining (Free) sources, sinks, and machines. Sources/
    # sinks on the primary faces (3 / 1) drive the row model and WP-L
    # monotone sink ordering; sources/sinks pinned to other faces are
    # assigned ports independently, in node order.
    free_sources = [n for n in all_sources if n["id"] not in port_pos]
    free_sinks = [n for n in all_sinks if n["id"] not in port_pos]

    sources = [n for n in free_sources if n.get("face", 3) == 3]
    sinks = [n for n in free_sinks if n.get("face", 1) == 1]
    extra_sources = [n for n in free_sources if n.get("face", 3) != 3]
    extra_sinks = [n for n in free_sinks if n.get("face", 1) != 1]

    # Extra-face ports: assign sequentially from that face's port list.
    extra_face_next: dict[int, int] = defaultdict(int)
    for n in extra_sources + extra_sinks:
        face = n["face"]
        ports = _edge_ports(plat, face)
        port_pos[n["id"]] = ports[extra_face_next[face]]
        extra_face_next[face] += 1
        port_rot[n["id"]] = _port_rotation_for(face, n["kind"])

    # Assign primary-face port positions from the actual port list, left to
    # right. To avoid route crossings, order sinks to match the source
    # ordering: trace each source → machines → sink chain, then assign the
    # sink that a leftmost source feeds to the leftmost sink port, etc.
    primary_src_rot = _port_rotation_for(3, "platform_in")
    primary_sink_rot = _port_rotation_for(1, "platform_out")

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
                if n.get("face", 1) == 1 and nid not in port_pos:
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

    for i, sink_id in enumerate(ordered_sinks):
        port_pos[sink_id] = sink_ports[i]
        port_rot[sink_id] = primary_sink_rot

    if not machines:
        return _build_netlist(abstract, port_pos, port_rot, {})

    # --- Stage computation (WP-M row model) ---
    stages = _compute_stages(abstract)
    n_stages = max(stages.values()) + 1

    # --- CP-SAT model ---
    model = cp_model.CpModel()

    # Row y-positions: one variable per stage.  All machines at the same
    # stage share a single y.  Routing channels between rows (and between
    # ports and the nearest row) must be at least 2 cells tall.
    row_y: list[cp_model.IntVar] = [
        model.new_int_var(y_min, y_max, f"row_y_{r}") for r in range(n_stages)
    ]

    if input_y > output_y:
        # South flow (common case): row 0 nearest sources, last row nearest sinks.
        model.add(row_y[0] <= input_y - 3)
        model.add(row_y[-1] >= output_y + 3)
        for r in range(n_stages - 1):
            model.add(row_y[r] >= row_y[r + 1] + 3)
    else:
        model.add(row_y[0] >= input_y + 3)
        model.add(row_y[-1] <= output_y - 3)
        for r in range(n_stages - 1):
            model.add(row_y[r + 1] >= row_y[r] + 3)

    # Machine variables: x is free within interior, y is the stage row,
    # r is rotation 0–3.
    m_x: dict[str, cp_model.IntVar] = {}
    m_y: dict[str, cp_model.IntVar] = {}
    m_r: dict[str, cp_model.IntVar] = {}

    for m in machines:
        mid = m["id"]
        m_x[mid] = model.new_int_var(x_min, x_max, f"x_{mid}")
        m_y[mid] = row_y[stages[mid]]
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
    # Per routing channel, per x-bucket of width _BUCKET_WIDTH: the number of
    # nets whose horizontal interval covers the bucket must not exceed the
    # channel height (classic channel-routing density).
    if input_y > output_y:
        all_px = [x for x, _ in port_pos.values()]
        bkt_lo = min(x_min, *all_px)
        bkt_hi = max(x_max, *all_px)
        n_bkt = (bkt_hi - bkt_lo + _BUCKET_WIDTH) // _BUCKET_WIDTH + 1

        ch_h = [input_y - row_y[0] - 1]
        for r in range(n_stages - 1):
            ch_h.append(row_y[r] - row_y[r + 1] - 1)
        ch_h.append(row_y[-1] - output_y - 1)

        ch_edges: dict[int, list[tuple]] = defaultdict(list)
        for sid, did in abstract["edges"]:
            sn, dn = node_by_id[sid], node_by_id[did]
            xs = _node_x(sid, sn, port_pos, m_x, model)
            xd = _node_x(did, dn, port_pos, m_x, model)
            if sn["kind"] == "platform_in":
                ci = 0
            elif sn["kind"] == "machine":
                ci = stages[sid] + 1
            else:
                continue
            ch_edges[ci].append((xs, xd))

        for ci in range(n_stages + 1):
            edges_ci = ch_edges.get(ci, [])
            if not edges_ci:
                continue
            for b in range(n_bkt):
                bl = bkt_lo + b * _BUCKET_WIDTH
                bh = min(bl + _BUCKET_WIDTH - 1, bkt_hi)
                terms: list = []
                fixed = 0
                for ei, (xs, xd) in enumerate(edges_ci):
                    c = _covers_bucket(model, xs, xd, bl, bh, f"d{ci}b{b}e{ei}")
                    if isinstance(c, bool):
                        if c:
                            fixed += 1
                    else:
                        terms.append(c)
                if terms or fixed > 0:
                    model.add(sum(terms) + fixed <= ch_h[ci])

    # Rotation constraints: a machine's output must face *toward* its
    # downstream neighbour (positive dot product between output direction and
    # the vector from machine to neighbour). Input must face toward upstream.
    #
    # Output direction at R=0,1,2,3 is E(1,0), N(0,1), W(-1,0), S(0,-1).
    # Dot product = out_dx*(vx-ux) + out_dy*(vy-uy) >= 1.
    # Encode via element constraints on R → direction components.
    out_dx_table = [1, 0, -1, 0]  # R=0→E, R=1→N, R=2→W, R=3→S
    out_dy_table = [0, 1, 0, -1]
    in_dx_table = [-1, 0, 1, 0]  # input is opposite: W, S, E, N
    in_dy_table = [0, -1, 0, 1]

    for ei, (src_id, dst_id) in enumerate(abstract["edges"]):
        src_node = node_by_id[src_id]
        dst_node = node_by_id[dst_id]

        # Source output must face toward dst.
        if src_node["kind"] == "machine":
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

        # Dst input must face toward src.
        if dst_node["kind"] == "machine":
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

    # Fan-group structure: machines sharing a source (fan-out) form a group.
    # Within a group, machines must be at adjacent x-coordinates.  Same-y
    # is now enforced by the row model (all machines at the same stage share
    # a row variable).  Between groups, x-ranges must not overlap so routes
    # don't cross through other groups' machines.
    fan_out_groups: defaultdict[str, list[str]] = defaultdict(list)
    for sid, did in abstract["edges"]:
        fan_out_groups[sid].append(did)

    fanout_groups: list[list[str]] = []
    for group_id, members in fan_out_groups.items():
        machine_members = [m for m in members if node_by_id[m]["kind"] == "machine"]
        if len(machine_members) >= 2:
            fanout_groups.append(machine_members)

    for machine_members in fanout_groups:
        if len(machine_members) == 2:
            a, b = machine_members
            abs_dx = model.new_int_var(0, grid_w, f"grp_dx_{a}_{b}")
            model.add_abs_equality(abs_dx, m_x[a] - m_x[b])
            model.add(abs_dx == 1)

    # Cross-group ordering: fan-out groups ordered by their source's
    # x-position so routes don't cross. A source at lower x should feed
    # machines at lower x than a source at higher x.
    fanout_src_ids = [
        sid
        for sid in fan_out_groups
        if sum(1 for m in fan_out_groups[sid] if node_by_id[m]["kind"] == "machine") >= 2
    ]
    # Sort source IDs by their assigned x-position.
    fanout_by_src: dict[str, list[str]] = {}
    src_x_for_id: dict[str, int] = {}
    for sid in fanout_src_ids:
        fanout_by_src[sid] = [m for m in fan_out_groups[sid] if node_by_id[m]["kind"] == "machine"]
        src_x_for_id[sid] = port_pos[sid][0]
    sorted_src_ids = sorted(fanout_src_ids, key=lambda s: src_x_for_id[s])

    for i in range(len(sorted_src_ids) - 1):
        left_group = fanout_by_src[sorted_src_ids[i]]
        right_group = fanout_by_src[sorted_src_ids[i + 1]]
        # Ordered non-overlapping: left group's machines left of right group.
        for a in left_group:
            for b in right_group:
                if a in m_x and b in m_x:
                    model.add(m_x[a] + 1 <= m_x[b])

    # Minimum spacing between connected nodes: at least 2 Manhattan distance
    # (room for one belt cell between machine and its source/sink).
    for ei, (src_id, dst_id) in enumerate(abstract["edges"]):
        src_node = node_by_id[src_id]
        dst_node = node_by_id[dst_id]

        sx = _node_x(src_id, src_node, port_pos, m_x, model)
        sy = _node_y(src_id, src_node, port_pos, m_y, model)
        dx = _node_x(dst_id, dst_node, port_pos, m_x, model)
        dy = _node_y(dst_id, dst_node, port_pos, m_y, model)

        abs_dx = model.new_int_var(0, grid_w, f"spc_adx_{ei}")
        abs_dy = model.new_int_var(0, grid_h, f"spc_ady_{ei}")
        model.add_abs_equality(abs_dx, sx - dx)
        model.add_abs_equality(abs_dy, sy - dy)
        model.add(abs_dx + abs_dy >= 2)

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

    # Row balance: prefer rows near the vertical center so routing channels
    # on both sides of the machine rows have roughly equal height.
    mid_y = (input_y + output_y) // 2
    for r in range(n_stages):
        bal = model.new_int_var(0, grid_h, f"bal_{r}")
        model.add_abs_equality(bal, row_y[r] - mid_y)
        total_wire.append(bal)

    model.minimize(sum(total_wire))

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
    """Assign neighbors to port cells by nearest-neighbor (greedy).

    Returns result[i] = index of the port cell assigned to neighbor i.
    """
    assigned: list[int | None] = [None] * len(neighbor_positions)
    used: set[int] = set()
    pairs = []
    for i, np in enumerate(neighbor_positions):
        for j, pc in enumerate(port_cells):
            d = abs(np[0] - pc[0]) + abs(np[1] - pc[1])
            pairs.append((d, i, j))
    pairs.sort()
    for _, i, j in pairs:
        if assigned[i] is None and j not in used:
            assigned[i] = j
            used.add(j)
    return assigned  # type: ignore[return-value]


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

    # Build port cells for multi-cell machines.
    machine_in_cells: dict[str, list[tuple[int, int]]] = {}
    machine_out_cells: dict[str, list[tuple[int, int]]] = {}
    for nid, (x, y, r) in machine_positions.items():
        n = node_by_id[nid]
        fp = lift._machine_footprint(n["type"], r)
        ins = [(x + dx, y + dy) for (dx, dy, dl), (i, _o) in fp.items() if i and dl == 0]
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
