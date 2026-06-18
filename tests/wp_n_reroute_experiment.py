"""WP-N task 1: decisive experiment — re-route the human Half Splitter placement.

Not a pytest test (no ``test_`` prefix, not collected by ``just test``): this
is the §7.2 WP-N task-1 existence-proof experiment. It lifts the UNFINISHED
Half Splitter (16 lanes x 4 cutters/lane, 64 cutters total, single floor),
strips belts/hops, completes the ~32 cutter->sink edges the human never
routed, and re-routes everything via PathFinder at ``hop_range=MAX_HOP_RANGE``
on a single floor with the human's machine placement held fixed.

Outcome decides WP-N's direction:
  - Converges -> single-floor routing capacity is sufficient at true scale;
    placement (tasks 3-4) only needs to reproduce a columnar lane layout.
  - Doesn't converge -> single-floor capacity is insufficient; 3-D routing
    (lifts) is in scope for tasks 3-4.

Run: ``uv run python tests/wp_n_reroute_experiment.py``

CAVEAT (2026-06-11 review, see generator-spec.md §7.2 WP-N task 1
"Correction"): ``strip_belts`` keeps interior hop launchers/catchers
(``lift.kind`` misclassifies them as platform IO), so this script's
single-floor run fights 290 phantom obstacles from the human's hop
endpoints and fails with a misleading "structural" error. With them
stripped the true single-floor failure mode is congestion (124 overused
cells at MAX_ITERS=60). The conclusion (single floor doesn't converge;
lifts do) is unchanged. Re-run only after WP-N task 3e fixes the strip.
"""

from __future__ import annotations

import time
from pathlib import Path

from shapez2_tools import lift
from shapez2_tools.blueprint import Blueprint
from shapez2_tools.pathfinder import (
    Cell,
    Net,
    RoutingError,
    RoutingGraph,
    _platform_bounds,
    build_nets,
    pathfinder_route,
    strip_and_reroute,
)
from shapez2_tools.route import _all_entities, strip_belts

HALF_SPLITTER = Path.home() / "Projects" / "shapez_2_blueprints" / "UNFINISHED Half Splitter.spz2bp"

# The 8 partially-routed lanes (one source per `src`, 4 cutters each) each
# have one dangling output per cutter. The 8 currently-unfed sinks (face 1,
# the south-face groups at x in {-12..-9} and {8..11}) are the only ports
# left -- every other sink is already fed by the 8 fully-routed lanes. This
# pairing mirrors the already-routed group<->group pattern (face3 group0 <->
# face1 group2 reversed, face3 group1 <-> face1 group3): face3 group2 <->
# face1 group0 reversed, face3 group3 <-> face1 group1 reversed. Slot
# assignment within a Region is free per §5 -- this is one valid choice, not
# the only one.
NEW_SINK_FOR_SRC: dict[tuple[int, int], tuple[int, int]] = {
    (28, 37): (-9, 2),
    (29, 37): (-10, 2),
    (30, 37): (-11, 2),
    (31, 37): (-12, 2),
    (48, 37): (11, 2),
    (49, 37): (10, 2),
    (50, 37): (9, 2),
    (51, 37): (8, 2),
}


def _machine_out_cells(
    nl: lift.Netlist,
    anchor: tuple[int, int],
) -> dict[tuple[int, int], frozenset]:
    """Per-cell output directions (dl=0) for a machine node."""
    node = nl.nodes[anchor]
    fp = lift._machine_footprint(node.type, node.rotation)
    return {
        (anchor[0] + dx, anchor[1] + dy): outs
        for (dx, dy, dl), (_ins, outs) in fp.items()
        if dl == 0 and outs
    }


def complete_netlist(nl: lift.Netlist) -> lift.Netlist:
    """Add the ~32 missing cutter->sink edges (§7.2 WP-N task 1)."""
    src_to_cutters: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for s, d in nl.port_edges:
        sn, dn = nl.nodes.get(s), nl.nodes.get(d)
        if sn and dn and sn.kind == "platform_in" and dn.kind == "machine":
            src_to_cutters.setdefault(s, []).append(d)

    fed_cells = {s for s, d in nl.port_edges if nl.nodes[d].kind == "platform_out"}

    new_port_edges: list[tuple[tuple[int, int], tuple[int, int]]] = []
    new_edges: list[tuple[tuple[int, int], tuple[int, int]]] = []
    for src, sink in NEW_SINK_FOR_SRC.items():
        for cutter in src_to_cutters[src]:
            for cell in _machine_out_cells(nl, cutter):
                if cell not in fed_cells:
                    new_port_edges.append((cell, sink))
                    new_edges.append((cutter, sink))

    nl.port_edges = nl.port_edges + new_port_edges
    nl.edges = sorted(set(nl.edges) | set(new_edges))
    return nl


def _build_passable_2floor(
    bp: Blueprint,
    layer: int,
    platform: str,
) -> set[Cell]:
    """Floor ``layer``: platform interior minus machine cells. Floor
    ``layer + 1``: fully open (the human placement uses only floor 0)."""
    stripped = strip_belts(bp, layer=layer)
    kept = [e for e in _all_entities(stripped) if e.layer == layer]

    machine_cells: set[tuple[int, int]] = set()
    for e in kept:
        machine_cells.add((e.x, e.y))
        if lift.kind(e.type) == "machine":
            fp = lift._machine_footprint(e.type, e.rotation)
            for dx, dy, dl in fp:
                if dl == 0:
                    machine_cells.add((e.x + dx, e.y + dy))

    min_x, max_x, min_y, max_y = _platform_bounds(platform)
    passable: set[Cell] = set()
    for x in range(min_x, max_x + 1):
        for y in range(min_y, max_y + 1):
            if (x, y) not in machine_cells:
                passable.add((x, y, layer))
            passable.add((x, y, layer + 1))
    return passable


def _translate_nets(
    nets: list[Net],
    cell_out_dir: dict[tuple[int, int], tuple[int, int]],
    cell_in_dir: dict[tuple[int, int], tuple[int, int]],
    passable: set[Cell],
) -> list[Net]:
    """Port -> routing-cell translation, copied from
    ``pathfinder.strip_and_reroute`` (layer-agnostic; depends only on
    ``passable``)."""
    for net in nets:
        rx, ry, rl = net.root

        if net.kind == "fanout":
            d = cell_out_dir.get((rx, ry))
            if d:
                new_root = (rx + d[0], ry + d[1], rl)
                if new_root in passable:
                    net.root = new_root
                    net.root_offset = True
                    net.root_approach = d
            new_terms = []
            for tx, ty, tl in net.terminals:
                orig = (tx, ty, tl)
                d = cell_in_dir.get((tx, ty))
                if d:
                    new_t = (tx + d[0], ty + d[1], tl)
                    if new_t in passable:
                        new_terms.append(new_t)
                        net.terminal_exit[new_t] = (-d[0], -d[1])
                    else:
                        new_terms.append(orig)
                else:
                    new_terms.append(orig)
            net.terminals = new_terms
        else:  # fanin: root is the sink
            d = cell_in_dir.get((rx, ry))
            if d:
                new_root = (rx + d[0], ry + d[1], rl)
                if new_root in passable:
                    net.root = new_root
                    net.root_offset = True
                    net.root_approach = d
            new_terms = []
            for tx, ty, tl in net.terminals:
                orig = (tx, ty, tl)
                d = cell_out_dir.get((tx, ty))
                if d:
                    new_t = (tx + d[0], ty + d[1], tl)
                    if new_t in passable:
                        new_terms.append(new_t)
                        net.terminal_exit[new_t] = (-d[0], -d[1])
                    else:
                        new_terms.append(orig)
                else:
                    new_terms.append(orig)
            net.terminals = new_terms

    routable: list[Net] = []
    for net in nets:
        net.terminals = [t for t in net.terminals if t in passable]
        if not net.terminals:
            continue
        if net.root not in passable:
            raise RoutingError(f"root could not leave port cell ({net.root[0]}, {net.root[1]})")
        routable.append(net)
    return routable


def retry_with_lifts(bp: Blueprint, nl: lift.Netlist, hop_range: int) -> None:
    """§7.2 WP-N task 1 fallback: same nets, floor 1 opened up as a fully
    passable second layer with ``lift_enabled=True``."""
    nets, cell_out_dir, cell_in_dir = build_nets(nl, layer=0)
    passable = _build_passable_2floor(bp, layer=0, platform="Foundation_2x4")
    routable = _translate_nets(nets, cell_out_dir, cell_in_dir, passable)
    graph = RoutingGraph(passable=passable, hop_range=hop_range, lift_enabled=True)

    print("\nretrying with lifts: floor 1 opened, lift_enabled=True ...")
    t0 = time.monotonic()
    try:
        pathfinder_route(routable, graph)
    except RoutingError as e:
        dt = time.monotonic() - t0
        print(f"\nLIFT RETRY FAILED to converge after {dt:.1f}s: {e}")
        overused = e.overused
        print(f"{len(overused)} overused cells:")
        for c in sorted(overused):
            print("  ", c)
        return

    dt = time.monotonic() - t0
    print(f"\nLIFT RETRY CONVERGED in {dt:.1f}s")
    lift_nets = [n for n in routable if n.lift_edges]
    print(f"{len(lift_nets)}/{len(routable)} nets used at least one lift edge")
    for n in lift_nets:
        print(f"  net {n.net_id} ({n.kind}): {sorted(n.lift_edges)}")


def main() -> None:
    bp = Blueprint.from_file(HALF_SPLITTER)
    nl = lift.trace_layer(bp, 0, contract_hops=True)

    by_kind = {}
    for n in nl.nodes.values():
        by_kind[n.kind] = by_kind.get(n.kind, 0) + 1
    print(f"lifted (hop-contracted): nodes={by_kind}, port_edges={len(nl.port_edges)}")

    nl = complete_netlist(nl)
    print(f"completed: port_edges={len(nl.port_edges)}")

    nets, _out, _in = build_nets(nl, layer=0)
    fanout = sum(1 for n in nets if n.kind == "fanout")
    fanin = sum(1 for n in nets if n.kind == "fanin")
    print(f"nets: {len(nets)} ({fanout} fanout, {fanin} fanin)")
    for n in nets:
        if len(n.terminals) != 4:
            print(f"  WARNING: net {n.net_id} ({n.kind}) has {len(n.terminals)} terminals")

    print(f"\nrouting at hop_range={lift.MAX_HOP_RANGE}, single floor, Foundation_2x4 ...")
    t0 = time.monotonic()
    try:
        routed = strip_and_reroute(
            bp,
            nl,
            layer=0,
            hop_range=lift.MAX_HOP_RANGE,
            platform="Foundation_2x4",
        )
    except RoutingError as e:
        dt = time.monotonic() - t0
        print(f"\nFAILED to converge after {dt:.1f}s: {e}")
        overused = e.overused
        print(f"{len(overused)} overused cells:")
        for c in sorted(overused):
            print("  ", c)
        retry_with_lifts(bp, nl, lift.MAX_HOP_RANGE)
        return

    dt = time.monotonic() - t0
    print(f"\nCONVERGED in {dt:.1f}s")

    problems = lift.validate(routed)
    print(f"validate(): {problems if problems else 'OK (0 problems)'}")

    routed_nl = lift.trace_layer(routed, 0, contract_hops=True)
    routed_by_kind = {}
    for n in routed_nl.nodes.values():
        routed_by_kind[n.kind] = routed_by_kind.get(n.kind, 0) + 1
    print(f"re-lifted: nodes={routed_by_kind}, port_edges={len(routed_nl.port_edges)}")
    print(f"unmatched_legs: {lift.unmatched_legs(routed, 0)}")

    out_path = (
        Path(__file__).resolve().parent.parent / "data" / "reference" / "wp_n_task1_routed.spz2bp"
    )
    routed.to_file(out_path)
    print(f"\nwrote routed blueprint to {out_path}")


if __name__ == "__main__":
    main()
