"""Machine placement via OR-Tools CP-SAT (WP-D).

Given an abstract netlist (node types/kinds + edges, no coordinates) and a
platform, assigns (x, y, rotation) to each node using constraint programming.
Sources and sinks are fixed at platform-edge positions; machines are placed
in the interior with no-overlap and wire-length minimization.

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
        nodes.append({"id": nid, "type": node.type, "kind": node.kind})

    edges = []
    for src, dst in nl.edges:
        src_id = id_for_pos[tuple(src)]
        dst_id = id_for_pos[tuple(dst)]
        edges.append((src_id, dst_id))

    return {"nodes": nodes, "edges": edges}


def place(abstract: dict, platform: str) -> lift.Netlist:
    """Place an abstract netlist on a platform via CP-SAT.

    Args:
        abstract: dict with "nodes" and "edges" (see ``abstract_netlist``).
        platform: platform name from platforms.json (e.g. "Foundation_1x1").

    Returns:
        A concrete ``Netlist`` with solver-chosen positions and rotations.
    """
    plat = _load_platform(platform)
    grid_w, grid_h = plat["grid_size"]
    border = 2

    # Interior bounds: buildable area inside the platform border.
    x_min, x_max = border, grid_w - border - 1
    y_min, y_max = border, grid_h - border - 1

    input_y = plat["input_y"]
    output_y = plat["output_y"]
    port_x_range = plat.get("port_x_range")

    # Index nodes by id.
    node_by_id: dict[str, dict] = {n["id"]: n for n in abstract["nodes"]}

    # Separate sources, sinks, and machines.
    sources = [n for n in abstract["nodes"] if n["kind"] == "src"]
    sinks = [n for n in abstract["nodes"] if n["kind"] == "sink"]
    machines = [n for n in abstract["nodes"] if n["kind"] == "machine"]

    # Assign port positions: sources at input_y, sinks at output_y.
    # Port x positions come from port_x_range; assign left to right.
    #
    # To avoid route crossings, order sinks to match the source ordering:
    # trace each source → machines → sink chain, then assign the sink that
    # a leftmost source feeds to the leftmost sink port, etc.
    port_rotation = _port_rotation(input_y, output_y)

    src_positions: dict[str, tuple[int, int]] = {}
    if port_x_range:
        for i, src in enumerate(sources):
            x = port_x_range[0] + i
            src_positions[src["id"]] = (x, input_y)
    else:
        for i, src in enumerate(sources):
            src_positions[src["id"]] = (x_min + i, input_y)

    # Build the src → sink mapping by tracing through machine edges.
    edge_out: dict[str, list[str]] = {}
    for sid, did in abstract["edges"]:
        edge_out.setdefault(sid, []).append(did)

    def _trace_all_sinks(src_id: str) -> list[str]:
        """BFS from src through machines, return all reachable sink ids."""
        visited: set[str] = set()
        frontier = [src_id]
        found: list[str] = []
        while frontier:
            nid = frontier.pop(0)
            if nid in visited:
                continue
            visited.add(nid)
            n = node_by_id[nid]
            if n["kind"] == "sink":
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
    src_by_x = sorted(sources, key=lambda s: src_positions[s["id"]][0])
    seen_sinks: set[str] = set()
    for src in src_by_x:
        for sink_id in _trace_all_sinks(src["id"]):
            if sink_id not in seen_sinks:
                ordered_sinks.append(sink_id)
                seen_sinks.add(sink_id)
    for sink in sinks:
        if sink["id"] not in seen_sinks:
            ordered_sinks.append(sink["id"])

    sink_positions: dict[str, tuple[int, int]] = {}
    if port_x_range:
        for i, sink_id in enumerate(ordered_sinks):
            x = port_x_range[0] + i
            sink_positions[sink_id] = (x, output_y)
    else:
        for i, sink_id in enumerate(ordered_sinks):
            sink_positions[sink_id] = (x_min + i, output_y)

    if not machines:
        return _build_netlist(
            abstract, src_positions, sink_positions, {}, port_rotation
        )

    # --- CP-SAT model ---
    model = cp_model.CpModel()

    # Machine variables: (x, y, r) per machine.
    m_x: dict[str, cp_model.IntVar] = {}
    m_y: dict[str, cp_model.IntVar] = {}
    m_r: dict[str, cp_model.IntVar] = {}

    # Keep machines away from port rows so fan-out splitters and belt
    # trunks have room.  A margin of 1 lets the solver place machines
    # adjacent to the source row; the router then puts a splitter ON
    # the source row, whose trunk end cell collides with a source port.
    machine_y_min = min(input_y, output_y) + 2
    machine_y_max = max(input_y, output_y) - 2
    # Clamp to interior.
    machine_y_min = max(machine_y_min, y_min)
    machine_y_max = min(machine_y_max, y_max)

    for m in machines:
        mid = m["id"]
        m_x[mid] = model.new_int_var(x_min, x_max, f"x_{mid}")
        m_y[mid] = model.new_int_var(machine_y_min, machine_y_max, f"y_{mid}")
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
    for pos in list(src_positions.values()) + list(sink_positions.values()):
        fixed_flat = pos[0] * h + pos[1]
        for fp in flat_positions:
            model.add(fp != fixed_flat)

    if len(flat_positions) >= 2:
        model.add_all_different(flat_positions)

    # Rotation constraints: a machine's output must face *toward* its
    # downstream neighbour (positive dot product between output direction and
    # the vector from machine to neighbour). Input must face toward upstream.
    #
    # Output direction at R=0,1,2,3 is E(1,0), N(0,1), W(-1,0), S(0,-1).
    # Dot product = out_dx*(vx-ux) + out_dy*(vy-uy) >= 1.
    # Encode via element constraints on R → direction components.
    out_dx_table = [1, 0, -1, 0]  # R=0→E, R=1→N, R=2→W, R=3→S
    out_dy_table = [0, 1, 0, -1]
    in_dx_table = [-1, 0, 1, 0]   # input is opposite: W, S, E, N
    in_dy_table = [0, -1, 0, 1]

    for ei, (src_id, dst_id) in enumerate(abstract["edges"]):
        src_node = node_by_id[src_id]
        dst_node = node_by_id[dst_id]

        # Source output must face toward dst.
        if src_node["kind"] == "machine":
            sx = m_x[src_id]
            sy = m_y[src_id]
            dx = _node_x(dst_id, dst_node, src_positions, sink_positions, m_x, model)
            dy = _node_y(dst_id, dst_node, src_positions, sink_positions, m_y, model)
            _add_output_faces_toward(
                model, m_r[src_id], sx, sy, dx, dy,
                out_dx_table, out_dy_table, grid_w, grid_h, f"eout_{ei}",
            )

        # Dst input must face toward src.
        if dst_node["kind"] == "machine":
            dx2 = m_x[dst_id]
            dy2 = m_y[dst_id]
            sx2 = _node_x(src_id, src_node, src_positions, sink_positions, m_x, model)
            sy2 = _node_y(src_id, src_node, src_positions, sink_positions, m_y, model)
            _add_output_faces_toward(
                model, m_r[dst_id], dx2, dy2, sx2, sy2,
                in_dx_table, in_dy_table, grid_w, grid_h, f"ein_{ei}",
            )

    # Fan-group structure: machines sharing a source (fan-out) or sink
    # (fan-in) form a group. Within a group, machines must be at adjacent
    # x-coordinates and the same y — the pattern the router's splitter/merger
    # heuristics expect. Between groups, x-ranges must not overlap so routes
    # don't cross through other groups' machines.
    fan_out_groups: defaultdict[str, list[str]] = defaultdict(list)
    fan_in_groups: defaultdict[str, list[str]] = defaultdict(list)
    for sid, did in abstract["edges"]:
        fan_out_groups[sid].append(did)
        fan_in_groups[did].append(sid)

    fanout_groups: list[list[str]] = []
    for group_id, members in fan_out_groups.items():
        machine_members = [m for m in members if node_by_id[m]["kind"] == "machine"]
        if len(machine_members) >= 2:
            fanout_groups.append(machine_members)

    for group_id, members in fan_in_groups.items():
        machine_members = [m for m in members if node_by_id[m]["kind"] == "machine"]
        if len(machine_members) >= 2:
            # Same y within fan-in group too.
            for i in range(1, len(machine_members)):
                model.add(m_y[machine_members[0]] == m_y[machine_members[i]])

    for machine_members in fanout_groups:
        # Same y for all machines in the fan-out group.
        for i in range(1, len(machine_members)):
            model.add(m_y[machine_members[0]] == m_y[machine_members[i]])
        # Adjacent x: pair must differ by exactly 1.
        if len(machine_members) == 2:
            a, b = machine_members
            abs_dx = model.new_int_var(0, grid_w, f"grp_dx_{a}_{b}")
            model.add_abs_equality(abs_dx, m_x[a] - m_x[b])
            model.add(abs_dx == 1)

    # Per-group same-y already keeps each fan-in / fan-out group on one
    # row; wire-length minimization keeps different groups nearby.  A
    # hard global y-band forces all groups to the same row, preventing
    # the staggered two-row layouts that route cleanly.

    # Cross-group ordering: fan-out groups ordered by their source's
    # x-position so routes don't cross. A source at lower x should feed
    # machines at lower x than a source at higher x.
    fanout_src_ids = [
        sid for sid in fan_out_groups
        if sum(1 for m in fan_out_groups[sid] if node_by_id[m]["kind"] == "machine") >= 2
    ]
    # Sort source IDs by their assigned x-position.
    fanout_by_src: dict[str, list[str]] = {}
    src_x_for_id: dict[str, int] = {}
    for sid in fanout_src_ids:
        fanout_by_src[sid] = [
            m for m in fan_out_groups[sid] if node_by_id[m]["kind"] == "machine"
        ]
        src_x_for_id[sid] = src_positions[sid][0]
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

        sx = _node_x(src_id, src_node, src_positions, sink_positions, m_x, model)
        sy = _node_y(src_id, src_node, src_positions, sink_positions, m_y, model)
        dx = _node_x(dst_id, dst_node, src_positions, sink_positions, m_x, model)
        dy = _node_y(dst_id, dst_node, src_positions, sink_positions, m_y, model)

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

        sx = _node_x(src_id, src_node, src_positions, sink_positions, m_x, model)
        sy = _node_y(src_id, src_node, src_positions, sink_positions, m_y, model)
        dx = _node_x(dst_id, dst_node, src_positions, sink_positions, m_x, model)
        dy = _node_y(dst_id, dst_node, src_positions, sink_positions, m_y, model)

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

    # Y-stagger: the y-component of wire length is invariant
    # (|src_y - y| + |y - sink_y| = const), so the solver is indifferent
    # among y-assignments.  Edge groups (first/last in x-order) have
    # trunks that extend horizontally across inner groups' territory at
    # y = source_y - 1.  Placing edge groups one row CLOSER to the
    # source than their inner neighbours gives the inner trunks a
    # clear vertical lane at a different y-level.
    if len(sorted_src_ids) >= 2:
        group_ys = [m_y[fanout_by_src[sid][0]] for sid in sorted_src_ids]
        for i in range(len(group_ys) - 1):
            abs_dy = model.new_int_var(0, grid_h, f"ydiv_{i}")
            model.add_abs_equality(abs_dy, group_ys[i] - group_ys[i + 1])
            model.add(abs_dy <= 1)
        model.add(group_ys[0] > group_ys[1])
        if len(group_ys) >= 3:
            model.add(group_ys[-1] > group_ys[-2])

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

    return _build_netlist(
        abstract, src_positions, sink_positions, machine_positions, port_rotation
    )


def _add_output_faces_toward(
    model: cp_model.CpModel,
    r_var: cp_model.IntVar,
    ux, uy, vx, vy,
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


def _port_rotation(input_y: int, output_y: int) -> int:
    """Determine port rotation from the platform's port Y positions.

    Sources at a higher y feed downward (south); the convention in the rotator
    corpus is R=3 for both sources and sinks on platforms where input_y > output_y.
    """
    if input_y > output_y:
        return 3
    return 1


def _node_x(nid, node, src_pos, sink_pos, m_x, model):
    if node["kind"] == "src":
        return src_pos[nid][0]
    if node["kind"] == "sink":
        return sink_pos[nid][0]
    return m_x[nid]


def _node_y(nid, node, src_pos, sink_pos, m_y, model):
    if node["kind"] == "src":
        return src_pos[nid][1]
    if node["kind"] == "sink":
        return sink_pos[nid][1]
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
    src_positions: dict[str, tuple[int, int]],
    sink_positions: dict[str, tuple[int, int]],
    machine_positions: dict[str, tuple[int, int, int]],
    port_rotation: int,
) -> lift.Netlist:
    """Assemble a concrete Netlist from solver results."""
    node_by_id = {n["id"]: n for n in abstract["nodes"]}

    pos_for_id: dict[str, tuple[int, int]] = {}
    nodes: dict[tuple[int, int], lift.Node] = {}

    for nid, pos in src_positions.items():
        pos_for_id[nid] = pos
        n = node_by_id[nid]
        nodes[pos] = lift.Node(
            x=pos[0], y=pos[1], layer=0, type=n["type"],
            kind="src", rotation=port_rotation,
        )

    for nid, pos in sink_positions.items():
        pos_for_id[nid] = pos
        n = node_by_id[nid]
        nodes[pos] = lift.Node(
            x=pos[0], y=pos[1], layer=0, type=n["type"],
            kind="sink", rotation=port_rotation,
        )

    for nid, (x, y, r) in machine_positions.items():
        pos = (x, y)
        pos_for_id[nid] = pos
        n = node_by_id[nid]
        nodes[pos] = lift.Node(
            x=x, y=y, layer=0, type=n["type"],
            kind="machine", rotation=r,
        )

    # Build port cells for multi-cell machines.
    machine_in_cells: dict[str, list[tuple[int, int]]] = {}
    machine_out_cells: dict[str, list[tuple[int, int]]] = {}
    for nid, (x, y, r) in machine_positions.items():
        n = node_by_id[nid]
        fp = lift._machine_footprint(n["type"], r)
        ins = [(x + dx, y + dy) for (dx, dy), (i, _o) in fp.items() if i]
        outs = [(x + dx, y + dy) for (dx, dy), (_i, o) in fp.items() if o]
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

    return lift.Netlist(
        nodes=nodes, edges=edges, port_edges=port_edges
    )
