use pyo3::prelude::*;

mod router;
mod types;

use router::{pathfinder_route, route_multi_seed};
use types::{NetResult, RoutingParams, SeedInput};

/// Native pathfinder router for shapez2-tools.
#[pymodule]
fn shapez2_router(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(py_pathfinder_route, m)?)?;
    m.add_function(wrap_pyfunction!(py_route_multi_seed, m)?)?;
    Ok(())
}

/// Run the PathFinder negotiated-congestion loop on a single seed.
///
/// Returns `(ok, nets)` where `ok` is True if all nets converged without
/// overlap, and `nets` is a list of `NetResult` dicts carrying the routed
/// tree for each net.
#[pyfunction]
#[pyo3(signature = (seed_input, params))]
fn py_pathfinder_route(seed_input: SeedInput, params: RoutingParams) -> PyResult<(bool, Vec<NetResult>)> {
    let (ok, results) = pathfinder_route(&seed_input, &params);
    Ok((ok, results))
}

/// Run the multi-seed sweep in parallel (rayon).
///
/// Returns `(ok, nets)` for the best seed. Early-exits on the first
/// clean (zero-overuse) solution.
#[pyfunction]
#[pyo3(signature = (seed_inputs, params))]
fn py_route_multi_seed(seed_inputs: Vec<SeedInput>, params: RoutingParams) -> PyResult<(bool, Vec<NetResult>)> {
    let (ok, results) = route_multi_seed(seed_inputs, &params);
    Ok((ok, results))
}
