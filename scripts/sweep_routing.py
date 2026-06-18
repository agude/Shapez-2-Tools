#!/usr/bin/env python3
"""Sweep routing parameters for the UNFINISHED Half Splitter.

Usage:
    python scripts/sweep_routing.py                       # default sweep
    python scripts/sweep_routing.py --seeds 0-99          # seed range
    python scripts/sweep_routing.py --hp -1.5 -1.8        # try two hop penalties
    python scripts/sweep_routing.py --iters 1000           # more iterations
    python scripts/sweep_routing.py --save                 # save first convergence as blueprint
    python scripts/sweep_routing.py --seeds 0-99 --hp -1.5 --hg 0.1 --verbose

Known good config: --seeds 4-4 --hp -1.5 --hg 0.1 --iters 1000
"""
from __future__ import annotations

import argparse
import copy
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shapez2_tools import blueprint, pathfinder, route_only


def load_problem(bp_path: Path | None = None, layer: int = 0):
    if bp_path is None:
        bp_path = Path.home() / "Projects/shapez_2_blueprints/UNFINISHED Half Splitter.spz2bp"
    bp = blueprint.Blueprint.from_file(bp_path)
    platform = bp.entries[0]["T"]
    dangles = route_only.find_and_classify_dangles(bp, layer)
    ports = route_only.find_free_port_positions(bp, layer)
    west_ports, east_ports = route_only.partition_ports(ports, platform)
    west_dangles = [(d.x, d.y) for d in dangles if d.half == "west"]
    east_dangles = [(d.x, d.y) for d in dangles if d.half == "east"]
    pairs = route_only._optimal_match(west_dangles, west_ports) + route_only._optimal_match(
        east_dangles, east_ports
    )
    nets = route_only.build_routing_nets(pairs, bp, layer, platform)
    endpoints = {(c[0], c[1]) for n in nets for c in (n.root, n.terminals[0])}
    passable = route_only.build_passable_from_occupancy(bp, layer, platform, endpoints=endpoints)
    senders, receivers = route_only._existing_hop_endpoints(bp, layer)
    return bp, platform, layer, nets, passable, senders, receivers


def run_one(
    base_nets,
    passable,
    senders,
    receivers,
    *,
    hp: float = -1.5,
    hg: float = 0.1,
    pm: float = 1.05,
    pi: float = 0.01,
    seed: int = 0,
    max_iters: int = 1000,
    verbose: bool = False,
):
    nets = copy.deepcopy(base_nets)
    graph = pathfinder.RoutingGraph(
        passable=passable,
        hop_range=5,
        existing_senders=senders,
        existing_receivers=receivers,
        hop_penalty=hp,
        sym_seed=seed,
    )
    own_ids = {n.net_id for n in nets}
    nets_sorted = sorted(nets, key=lambda n: (-pathfinder._net_hpwl(n), n.net_id))
    pres_fac = pi
    best = 999
    best_iter = 0
    t0 = time.time()

    for i in range(max_iters):
        for net in nets_sorted:
            for c in net.tree_cells:
                graph.occ[c].discard(net.net_id)
            pathfinder._grow_tree(net, graph, pres_fac)
            for c in net.tree_cells:
                graph.occ[c].add(net.net_id)

        overused = [c for c, s in graph.occ.items() if len(s) > 1 and (s & own_ids)]
        n_ov = len(overused)
        if n_ov < best:
            best = n_ov
            best_iter = i
            if verbose:
                print(f"  iter {i}: new best {n_ov} overused, pf={pres_fac:.4f}")
        if not overused:
            return 0, i, time.time() - t0, nets

        overused_set = set(overused)
        nets_sorted = sorted(
            nets,
            key=lambda n: (
                0 if n.tree_cells & overused_set else 1,
                -pathfinder._net_hpwl(n),
                n.net_id,
            ),
        )
        for c in overused:
            graph.hist[c] = graph.hist.get(c, 0.0) + hg * (len(graph.occ[c]) - 1)
        pres_fac *= pm

    return best, best_iter, time.time() - t0, None


def parse_range(s: str) -> range:
    if "-" in s:
        lo, hi = s.split("-", 1)
        return range(int(lo), int(hi) + 1)
    return range(int(s), int(s) + 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seeds", default="0-19", help="Seed range, e.g. 0-99 (default: 0-19)")
    parser.add_argument("--hp", type=float, nargs="+", default=[-1.5], help="Hop penalties (default: -1.5)")
    parser.add_argument("--hg", type=float, nargs="+", default=[0.1], help="Hist gains (default: 0.1)")
    parser.add_argument("--pm", type=float, nargs="+", default=[1.05], help="Pressure multipliers (default: 1.05)")
    parser.add_argument("--pi", type=float, nargs="+", default=[0.01], help="Pressure init (default: 0.01)")
    parser.add_argument("--iters", type=int, default=1000, help="Max iterations (default: 1000)")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--show-all", action="store_true", help="Show all results, not just best<=2")
    parser.add_argument("--save", action="store_true", help="Save first converged result as blueprint")
    parser.add_argument("--save-path", type=Path, help="Output path for --save")
    parser.add_argument("--bp", type=Path, help="Blueprint to route (default: UNFINISHED Half Splitter)")
    parser.add_argument("--layer", type=int, default=0, help="Layer to route (default: 0)")
    args = parser.parse_args()

    seeds = parse_range(args.seeds)
    print("Loading problem...", flush=True)
    bp, platform, layer, base_nets, passable, senders, receivers = load_problem(args.bp, args.layer)
    n_configs = len(seeds) * len(args.hp) * len(args.hg) * len(args.pm) * len(args.pi)
    print(f"{len(base_nets)} nets, {n_configs} configs, max {args.iters} iters each")
    print()

    converged = 0
    for hp in args.hp:
        for hg in args.hg:
            for pm in args.pm:
                for pi in args.pi:
                    for seed in seeds:
                        best, best_iter, elapsed, nets = run_one(
                            base_nets, passable, senders, receivers,
                            hp=hp, hg=hg, pm=pm, pi=pi, seed=seed,
                            max_iters=args.iters, verbose=args.verbose,
                        )
                        tag = f"hp={hp:+.1f} hg={hg} pm={pm} pi={pi} seed={seed:3d}"
                        if best == 0:
                            converged += 1
                            print(f"CONVERGED  {tag} iter={best_iter:4d} t={elapsed:.1f}s")
                            if args.save and nets is not None:
                                route_only._attach_boundary_edges(nets)
                                new_ents = pathfinder.emit_entities(nets) + route_only._port_sender_entities(nets, platform, layer)
                                result_bp = route_only.merge_entities(bp, new_ents)
                                out = args.save_path or Path.home() / f"Projects/shapez_2_blueprints/TESTING Routed L{layer}.spz2bp"
                                result_bp.to_file(out)
                                print(f"  -> saved {out}")
                                args.save = False
                        elif args.show_all or best <= 2:
                            print(f"best={best:2d}     {tag} iter={best_iter:4d} t={elapsed:.1f}s")

    print(f"\n{converged}/{n_configs} converged")


if __name__ == "__main__":
    main()
