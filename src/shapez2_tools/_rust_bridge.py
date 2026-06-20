"""Bridge between the Python pathfinder types and the Rust `shapez2_router` extension.

Import ``rust_pathfinder_route`` or ``rust_route_multi_seed`` — they accept
the same Python-level ``Net`` / ``RoutingGraph`` objects and return results
in the same format. If the extension is not installed, ``RUST_AVAILABLE``
is False and the functions are None.
"""

from __future__ import annotations

from shapez2_tools.pathfinder import (
    HIST_GAIN,
    MAX_ITERS,
    PRES_FAC_INIT,
    PRES_FAC_MULT,
    Cell,
    Net,
    RoutingError,
    RoutingGraph,
)

try:
    from shapez2_router import py_pathfinder_route, py_route_multi_seed

    RUST_AVAILABLE = True
except ImportError:
    RUST_AVAILABLE = False
    py_pathfinder_route = None
    py_route_multi_seed = None


def _net_to_dict(net: Net) -> dict:
    d = {
        "net_id": net.net_id,
        "kind": net.kind,
        "root": net.root,
        "terminals": list(net.terminals),
        "root_offset": net.root_offset,
        "root_approach": net.root_approach,
        "terminal_exit": dict(net.terminal_exit),
        "tree_cells": list(net.tree_cells),
        "tree_edges": list(net.tree_edges),
        "hop_edges": list(net.hop_edges),
        "lift_edges": list(net.lift_edges),
    }
    return d


def _occ_to_dict(graph: RoutingGraph) -> dict[Cell, list[int]]:
    """Serialize graph.occ for Rust: cell → list of net_ids."""
    return {c: list(ids) for c, ids in graph.occ.items() if ids}


def _params_dict(
    graph: RoutingGraph,
    *,
    max_iters: int = MAX_ITERS,
    pres_fac_init: float = PRES_FAC_INIT,
    pres_fac_mult: float = PRES_FAC_MULT,
    hist_gain: float = HIST_GAIN,
    stall_window: int | None = None,
    keep_best: bool = False,
) -> dict:
    return {
        "passable": set(graph.passable),
        "hop_range": graph.hop_range,
        "lift_enabled": graph.lift_enabled,
        "existing_senders": dict(graph.existing_senders),
        "existing_receivers": dict(graph.existing_receivers),
        "reserved": dict(graph.reserved),
        "hop_penalty": graph.hop_penalty,
        "initial_occ": _occ_to_dict(graph),
        "max_iters": max_iters,
        "pres_fac_init": pres_fac_init,
        "pres_fac_mult": pres_fac_mult,
        "hist_gain": hist_gain,
        "stall_window": stall_window,
        "keep_best": keep_best,
    }


def _apply_results(nets: list[Net], results: list[dict]) -> None:
    """Write Rust routing results back into the Python Net objects."""
    by_id = {n.net_id: n for n in nets}
    for r in results:
        net = by_id[r["net_id"]]
        net.tree_cells = set(tuple(c) for c in r["tree_cells"])
        net.tree_edges = [(tuple(s), tuple(d)) for s, d in r["tree_edges"]]
        net.hop_edges = {(tuple(s), tuple(d)) for s, d in r["hop_edges"]}
        net.lift_edges = {(tuple(s), tuple(d)) for s, d in r["lift_edges"]}


def _sync_occ(nets: list[Net], graph: RoutingGraph) -> None:
    """Incrementally update graph.occ for the routed nets.

    Removes old occupancy for the given nets' IDs, then adds their new
    tree_cells.  Occupancy from other nets (e.g. previously-routed groups)
    is preserved.
    """
    net_ids = {n.net_id for n in nets}
    for s in graph.occ.values():
        s -= net_ids
    for net in nets:
        for c in net.tree_cells:
            graph.occ[c].add(net.net_id)


def _overused_cells(nets: list[Net], graph: RoutingGraph) -> list[Cell]:
    own_ids = {n.net_id for n in nets}
    return [c for c, s in graph.occ.items() if len(s) > 1 and (s & own_ids)]


def rust_pathfinder_route(
    nets: list[Net],
    graph: RoutingGraph,
    *,
    raise_on_failure: bool = True,
    max_iters: int = MAX_ITERS,
    pres_fac_init: float = PRES_FAC_INIT,
    pres_fac_mult: float = PRES_FAC_MULT,
    hist_gain: float = HIST_GAIN,
    stall_window: int | None = None,
    keep_best: bool = False,
) -> bool:
    """Drop-in replacement for ``pathfinder.pathfinder_route`` using Rust."""
    seed_input = {
        "nets": [_net_to_dict(n) for n in nets],
        "sym_seed": graph.sym_seed,
    }
    params = _params_dict(
        graph,
        max_iters=max_iters,
        pres_fac_init=pres_fac_init,
        pres_fac_mult=pres_fac_mult,
        hist_gain=hist_gain,
        stall_window=stall_window,
        keep_best=keep_best,
    )

    ok, results = py_pathfinder_route(seed_input, params)
    _apply_results(nets, results)
    _sync_occ(nets, graph)

    if not ok and raise_on_failure:
        overused = _overused_cells(nets, graph)
        raise RoutingError(
            f"PathFinder (Rust) failed after {max_iters} iterations; "
            f"{len(overused)} overused cells",
            overused=overused,
        )

    return ok


def rust_route_by_group(
    nets: list[Net],
    graph: RoutingGraph,
    *,
    raise_on_failure: bool = True,
) -> bool:
    """Drop-in replacement for ``pathfinder._route_by_group`` using Rust.

    Routes each lane group sequentially (occupancy carries over between
    groups via ``initial_occ``), then runs a joint pass on all nets if
    any overlaps remain.
    """
    groups: dict[int, list[Net]] = {}
    ungrouped: list[Net] = []
    for net in nets:
        if net.group is not None:
            groups.setdefault(net.group, []).append(net)
        else:
            ungrouped.append(net)

    _ITERS = 2000
    for g_idx in sorted(groups):
        graph.hist.clear()
        rust_pathfinder_route(
            groups[g_idx], graph, raise_on_failure=False, max_iters=_ITERS
        )

    if ungrouped:
        graph.hist.clear()
        rust_pathfinder_route(ungrouped, graph, raise_on_failure=False, max_iters=_ITERS)

    overused = [c for c, s in graph.occ.items() if len(s) > 1]
    if not overused:
        return True

    graph.hist.clear()
    return rust_pathfinder_route(
        nets, graph, raise_on_failure=raise_on_failure, max_iters=_ITERS
    )


def rust_route_multi_seed(
    base_nets: list[Net],
    graph_template: RoutingGraph,
    max_seeds: int,
    *,
    max_iters: int = MAX_ITERS,
    pres_fac_init: float = PRES_FAC_INIT,
    pres_fac_mult: float = PRES_FAC_MULT,
    hist_gain: float = HIST_GAIN,
    stall_window: int | None = None,
    keep_best: bool = False,
) -> tuple[bool, list[Net]]:
    """Run the multi-seed sweep in parallel via Rust.

    Returns ``(ok, nets)`` where ``nets`` have their tree populated from
    the best seed.
    """
    net_dicts = [_net_to_dict(n) for n in base_nets]
    seed_inputs = [{"nets": net_dicts, "sym_seed": seed} for seed in range(max_seeds)]
    params = _params_dict(
        graph_template,
        max_iters=max_iters,
        pres_fac_init=pres_fac_init,
        pres_fac_mult=pres_fac_mult,
        hist_gain=hist_gain,
        stall_window=stall_window,
        keep_best=keep_best,
    )

    ok, results = py_route_multi_seed(seed_inputs, params)
    _apply_results(base_nets, results)
    return ok, base_nets
