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
    return {
        "net_id": net.net_id,
        "kind": net.kind,
        "root": net.root,
        "terminals": list(net.terminals),
        "root_offset": net.root_offset,
        "root_approach": net.root_approach,
        "terminal_exit": dict(net.terminal_exit),
    }


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
    """Sync net occupancy back into the Python graph."""
    graph.occ.clear()
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
