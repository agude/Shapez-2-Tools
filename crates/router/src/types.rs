use pyo3::prelude::*;
use rustc_hash::{FxHashMap, FxHashSet};
use std::collections::HashMap;

/// (x, y, layer)
pub type Cell = (i32, i32, i32);

/// Direction vector (dx, dy).
pub type Dir = (i32, i32);

pub const LEGAL_LEG_PATTERNS: [(i32, i32); 5] = [(1, 1), (1, 2), (1, 3), (2, 1), (3, 1)];

// ---------------------------------------------------------------------------
// Python-facing input types
// ---------------------------------------------------------------------------

/// One net to route — passed from Python as a dict.
#[derive(Clone, Debug, FromPyObject)]
#[pyo3(from_item_all)]
pub struct NetInput {
    pub net_id: i32,
    /// "fanout" or "fanin"
    pub kind: String,
    pub root: Cell,
    pub terminals: Vec<Cell>,
    pub root_offset: bool,
    /// (dx, dy) or None
    pub root_approach: Option<Dir>,
    /// terminal → (dx, dy)
    pub terminal_exit: HashMap<Cell, Dir>,
    /// Pre-existing routing state (non-empty when re-routing after a group pass).
    pub tree_cells: Vec<Cell>,
    pub tree_edges: Vec<(Cell, Cell)>,
    pub hop_edges: Vec<(Cell, Cell)>,
    pub lift_edges: Vec<(Cell, Cell)>,
}

/// Graph + algorithm parameters — shared across seeds.
#[derive(Clone, Debug, FromPyObject)]
#[pyo3(from_item_all)]
pub struct RoutingParams {
    pub passable: FxHashSet<Cell>,
    pub hop_range: i32,
    pub lift_enabled: bool,
    /// Pre-existing hop senders: cell → direction
    pub existing_senders: HashMap<Cell, Dir>,
    /// Pre-existing hop receivers: cell → direction
    pub existing_receivers: HashMap<Cell, Dir>,
    /// cell → net_id reservations
    pub reserved: HashMap<Cell, i32>,
    pub hop_penalty: f64,
    /// Pre-existing occupancy from previously-routed groups: cell → [net_ids].
    pub initial_occ: HashMap<Cell, Vec<i32>>,
    // Negotiation parameters
    pub max_iters: i32,
    pub pres_fac_init: f64,
    pub pres_fac_mult: f64,
    pub hist_gain: f64,
    pub stall_window: Option<i32>,
    pub keep_best: bool,
}

/// Per-seed input: the nets plus the symmetry-breaking seed.
#[derive(Clone, Debug, FromPyObject)]
#[pyo3(from_item_all)]
pub struct SeedInput {
    pub nets: Vec<NetInput>,
    pub sym_seed: u64,
}

// ---------------------------------------------------------------------------
// Python-facing output types
// ---------------------------------------------------------------------------

/// Routed net result — returned to Python as a dict.
#[derive(Clone, Debug, IntoPyObject)]
pub struct NetResult {
    pub net_id: i32,
    pub tree_cells: Vec<Cell>,
    pub tree_edges: Vec<(Cell, Cell)>,
    pub hop_edges: Vec<(Cell, Cell)>,
    pub lift_edges: Vec<(Cell, Cell)>,
}

// ---------------------------------------------------------------------------
// Internal working types (not PyO3)
// ---------------------------------------------------------------------------

#[derive(Clone, Debug)]
pub struct Net {
    pub net_id: i32,
    pub kind: NetKind,
    pub root: Cell,
    pub terminals: Vec<Cell>,
    pub root_offset: bool,
    pub root_approach: Option<Dir>,
    pub terminal_exit: FxHashMap<Cell, Dir>,
    pub tree_cells: FxHashSet<Cell>,
    pub tree_edges: Vec<(Cell, Cell)>,
    pub hop_edges: FxHashSet<(Cell, Cell)>,
    pub lift_edges: FxHashSet<(Cell, Cell)>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum NetKind {
    Fanout,
    Fanin,
}

impl Net {
    pub fn from_input(input: &NetInput) -> Self {
        let kind = if input.kind == "fanin" {
            NetKind::Fanin
        } else {
            NetKind::Fanout
        };
        Net {
            net_id: input.net_id,
            kind,
            root: input.root,
            terminals: input.terminals.clone(),
            root_offset: input.root_offset,
            root_approach: input.root_approach,
            terminal_exit: input.terminal_exit.iter().map(|(&k, &v)| (k, v)).collect(),
            tree_cells: input.tree_cells.iter().copied().collect(),
            tree_edges: input.tree_edges.clone(),
            hop_edges: input.hop_edges.iter().copied().collect(),
            lift_edges: input.lift_edges.iter().copied().collect(),
        }
    }

    pub fn to_result(&self) -> NetResult {
        NetResult {
            net_id: self.net_id,
            tree_cells: self.tree_cells.iter().copied().collect(),
            tree_edges: self.tree_edges.clone(),
            hop_edges: self.hop_edges.iter().copied().collect(),
            lift_edges: self.lift_edges.iter().copied().collect(),
        }
    }
}

pub struct RoutingGraph {
    pub passable: FxHashSet<Cell>,
    pub hop_range: i32,
    pub lift_enabled: bool,
    pub base: FxHashMap<Cell, f64>,
    pub hist: FxHashMap<Cell, f64>,
    pub occ: FxHashMap<Cell, FxHashSet<i32>>,
    pub existing_senders: FxHashMap<Cell, Dir>,
    pub existing_receivers: FxHashMap<Cell, Dir>,
    pub reserved: FxHashMap<Cell, i32>,
    pub hop_penalty: f64,
    pub sym_seed: u64,
}

pub const BASE: f64 = 1.0;
pub const LIFT_COST: f64 = 2.0;
pub const SYMMETRY_BREAK: f64 = 1e-4;

impl RoutingGraph {
    pub fn new(params: &RoutingParams, sym_seed: u64) -> Self {
        let mut base = FxHashMap::default();
        let hist = FxHashMap::default();
        for &c in &params.passable {
            base.insert(c, BASE);
        }
        let mut occ: FxHashMap<Cell, FxHashSet<i32>> = FxHashMap::default();
        for (cell, ids) in &params.initial_occ {
            let set = occ.entry(*cell).or_default();
            for &id in ids {
                set.insert(id);
            }
        }
        RoutingGraph {
            passable: params.passable.clone(),
            hop_range: params.hop_range,
            lift_enabled: params.lift_enabled,
            base,
            hist,
            occ,
            existing_senders: params.existing_senders.iter().map(|(&k, &v)| (k, v)).collect(),
            existing_receivers: params.existing_receivers.iter().map(|(&k, &v)| (k, v)).collect(),
            reserved: params.reserved.iter().map(|(&k, &v)| (k, v)).collect(),
            hop_penalty: params.hop_penalty,
            sym_seed,
        }
    }
}
