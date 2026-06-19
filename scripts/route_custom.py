#!/usr/bin/env python3
"""Route the Half Splitter with custom dangle→port assignments.

Usage:
    python scripts/route_custom.py [--max-seeds N] [--save PATH] [--clone]
"""
from __future__ import annotations

import argparse
import copy
import sys
import time

from shapez2_tools import blueprint, pathfinder, route_only
from shapez2_tools.route_only import _optimal_match

BP_PATH = "UNFINISHED Half Splitter.spz2bp"
BP_DIR = "/home/agude/Projects/shapez_2_blueprints"


# fmt: off
ASSIGNMENTS: dict[str, tuple[list[tuple[int, int]], list[tuple[int, int]]]] = {
    "1E -> E": (
        [(-12, 17), (-11, 17), (-2, 17), (0, 17)],
        [(28, 2), (29, 2), (30, 2), (31, 2)],
    ),
    "2W -> B": (
        [(5, 22), (6, 21), (15, 22), (17, 21)],
        [(-18, 8), (-18, 9), (-18, 10), (-18, 11)],
    ),
    "2E -> F": (
        [(2, 21), (4, 22), (13, 22), (14, 22)],
        [(48, 2), (49, 2), (50, 2), (51, 2)],
    ),
    "3W -> C": (
        [(25, 22), (26, 22), (35, 22), (37, 21)],
        [(-12, 2), (-11, 2), (-10, 2), (-9, 2)],
    ),
    "3E -> G": (
        [(22, 21), (24, 22), (33, 21), (34, 22)],
        [(57, 8), (57, 9), (57, 10), (57, 11)],
    ),
    "4W -> D": (
        [(39, 17), (41, 17), (50, 17), (51, 17)],
        [(8, 2), (9, 2), (10, 2), (11, 2)],
    ),
}
# fmt: on


def build_custom_pairs() -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """Build (dangle, port) pairs using within-group optimal matching."""
    pairs: list[tuple[tuple[int, int], tuple[int, int]]] = []
    for name, (dangles, ports) in ASSIGNMENTS.items():
        group_pairs = _optimal_match(dangles, ports)
        print(f"  {name}: {len(group_pairs)} pairs")
        pairs.extend(group_pairs)
    return pairs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-seeds", type=int, default=50)
    parser.add_argument("--save", type=str, default=None)
    parser.add_argument("--clone", action="store_true")
    args = parser.parse_args()

    bp_path = f"{BP_DIR}/{BP_PATH}"
    print(f"Loading {bp_path}")
    bp = blueprint.Blueprint.from_file(bp_path)

    print("Building custom pairs...")
    pairs = build_custom_pairs()
    print(f"Total: {len(pairs)} nets to route")

    platform = bp.entries[0]["T"]
    base_nets = route_only.build_routing_nets(pairs, bp, 0, platform)
    endpoints = {(c[0], c[1]) for n in base_nets for c in (n.root, n.terminals[0])}
    passable = route_only.build_passable_from_occupancy(bp, 0, platform, endpoints=endpoints)
    senders, receivers = route_only._existing_hop_endpoints(bp, 0)

    best_nets = None
    best_overuse = float("inf")
    t0 = time.time()

    for seed in range(args.max_seeds):
        ts = time.time()
        nets = copy.deepcopy(base_nets)
        graph = pathfinder.RoutingGraph(
            passable=passable,
            hop_range=5,
            existing_senders=senders,
            existing_receivers=receivers,
            hop_penalty=-1.5,
            sym_seed=seed,
        )
        _ITERS = 2000
        ok = pathfinder.pathfinder_route(
            nets,
            graph,
            raise_on_failure=False,
            max_iters=_ITERS,
            pres_fac_init=0.01,
            pres_fac_mult=1.05,
            hist_gain=0.1,
            stall_window=_ITERS,
            keep_best=True,
        )
        elapsed = time.time() - ts
        own_ids = {n.net_id for n in nets}
        overused = [c for c, s in graph.occ.items() if len(s) > 1 and (s & own_ids)]
        n_ov = len(overused)
        tag = "CONVERGED" if ok else f"best={n_ov:3d}"
        print(f"  seed {seed:3d}: {tag}  {elapsed:6.1f}s", flush=True)

        if ok:
            route_only._attach_boundary_edges(nets)
            best_nets = nets
            best_overuse = 0
            break
        if n_ov < best_overuse:
            best_overuse = n_ov
            best_nets = nets

    total = time.time() - t0
    print(f"\nTotal: {total:.1f}s, best overuse: {best_overuse}")

    if best_nets is None:
        print("No solution found.")
        sys.exit(1)

    if best_overuse > 0:
        route_only._attach_boundary_edges(best_nets)
        print(f"WARNING: best solution has {best_overuse} overused cells")

    clone_to = [1, 2] if args.clone else None
    new_entities = pathfinder.emit_entities(best_nets) + route_only._port_sender_entities(
        best_nets, platform, 0
    )
    source = list(new_entities)
    for target in clone_to or []:
        new_entities += route_only._clone_entities_to_layer(source, target)
    result = route_only.merge_entities(bp, new_entities)

    if args.save:
        result.to_file(args.save)
        print(f"Saved to {args.save}")


if __name__ == "__main__":
    main()
