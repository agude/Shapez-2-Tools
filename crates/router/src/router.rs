use std::collections::BinaryHeap;

use rayon::prelude::*;
use rustc_hash::{FxHashMap, FxHashSet};

use crate::types::*;

const DIRS: [Dir; 4] = [(1, 0), (-1, 0), (0, 1), (0, -1)];

#[inline]
fn neighbors(cell: Cell) -> [Cell; 4] {
    let (x, y, l) = cell;
    [(x + 1, y, l), (x - 1, y, l), (x, y + 1, l), (x, y - 1, l)]
}

#[inline]
fn unit_dir(dx: i32, dy: i32) -> Dir {
    (dx.signum(), dy.signum())
}

#[inline]
fn manhattan(a: Cell, b: Cell) -> i32 {
    (a.0 - b.0).abs() + (a.1 - b.1).abs()
}

fn cell_hash(cell: Cell, net_id: i32, sym_seed: u64) -> u64 {
    let mut h = cell.0 as u64;
    h = h.wrapping_mul(2654435761).wrapping_add(cell.1 as u64);
    h = h.wrapping_mul(2654435761).wrapping_add(cell.2 as u64);
    h ^= net_id as u64;
    h ^= sym_seed;
    h % 997
}

/// Priority-queue entry. Ordered by (f, y, x, layer) for tie-breaking
/// consistent with the Python implementation.
#[derive(PartialEq)]
struct PqEntry {
    f: f64,
    y: i32,
    x: i32,
    layer: i32,
    cost: f64,
    cell: Cell,
}

impl Eq for PqEntry {}

impl PartialOrd for PqEntry {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for PqEntry {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        // Reverse ordering for min-heap via BinaryHeap (which is max-heap)
        other
            .f
            .partial_cmp(&self.f)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then(other.y.cmp(&self.y))
            .then(other.x.cmp(&self.x))
            .then(other.layer.cmp(&self.layer))
    }
}

fn grow_tree(
    net: &mut Net,
    graph: &RoutingGraph,
    pres_fac: f64,
) -> Result<(), String> {
    let root = net.root;
    let mut terminals = net.terminals.clone();
    terminals.sort_by(|a, b| {
        manhattan(*b, root).cmp(&manhattan(*a, root))
    });

    let mut tree_cells: FxHashSet<Cell> = FxHashSet::default();
    tree_cells.insert(root);
    let mut tree_edges: Vec<(Cell, Cell)> = Vec::new();
    let mut cell_in: FxHashMap<Cell, i32> = FxHashMap::default();
    let mut cell_out: FxHashMap<Cell, i32> = FxHashMap::default();
    let mut hop_cells: FxHashSet<Cell> = FxHashSet::default();
    let mut lift_cells: FxHashSet<Cell> = FxHashSet::default();
    let mut cell_approach: FxHashMap<Cell, Dir> = FxHashMap::default();
    let mut item_recv_cells: FxHashSet<Cell> = FxHashSet::default();

    if net.root_offset {
        *cell_in.entry(root).or_insert(0) = 1;
    }
    if let Some(d) = net.root_approach {
        cell_approach.insert(root, d);
    }

    for &terminal in &terminals {
        if tree_cells.contains(&terminal) {
            continue;
        }

        let (tx, ty, tl) = terminal;

        let heuristic = |c: Cell| -> f64 {
            let mut h = ((c.0 - tx).abs() + (c.1 - ty).abs()) as f64 * BASE;
            if c.2 != tl {
                h += LIFT_COST;
            }
            h
        };

        let search = |allow_hops: bool| -> (bool, FxHashMap<Cell, f64>, FxHashMap<Cell, Cell>) {
            let mut dist: FxHashMap<Cell, f64> = FxHashMap::default();
            let mut prev: FxHashMap<Cell, Cell> = FxHashMap::default();
            let mut expanded: FxHashSet<Cell> = FxHashSet::default();
            let mut pq: BinaryHeap<PqEntry> = BinaryHeap::new();

            for &seed in &tree_cells {
                if hop_cells.contains(&seed) || lift_cells.contains(&seed) {
                    continue;
                }
                let outs = *cell_out.get(&seed).unwrap_or(&0);
                let ins = *cell_in.get(&seed).unwrap_or(&0);
                let total_legs = ins + outs;
                if total_legs >= 4 {
                    continue;
                }
                if outs + 1 > 3 {
                    continue;
                }
                let candidate = (ins, outs + 1);
                if !LEGAL_LEG_PATTERNS.contains(&candidate) && total_legs > 0 {
                    continue;
                }
                dist.insert(seed, 0.0);
                pq.push(PqEntry {
                    f: heuristic(seed),
                    y: seed.1,
                    x: seed.0,
                    layer: seed.2,
                    cost: 0.0,
                    cell: seed,
                });
            }

            let mut found = false;
            while let Some(entry) = pq.pop() {
                let cell = entry.cell;
                let cost = entry.cost;

                if cost > *dist.get(&cell).unwrap_or(&f64::INFINITY) {
                    continue;
                }

                if cell == terminal {
                    found = true;
                    break;
                }

                expanded.insert(cell);

                // Step neighbors (4-connected grid)
                for nb in neighbors(cell) {
                    if !graph.passable.contains(&nb) {
                        continue;
                    }
                    if tree_cells.contains(&nb) && nb != terminal {
                        continue;
                    }
                    if let Some(&owner) = graph.reserved.get(&nb) {
                        if owner != net.net_id {
                            continue;
                        }
                    }
                    // Hop receiver exit constraint
                    if allow_hops {
                        if let Some(&p) = prev.get(&cell) {
                            let md = (cell.0 - p.0).abs() + (cell.1 - p.1).abs();
                            if md > 1 {
                                let (ux, uy) = unit_dir(cell.0 - p.0, cell.1 - p.1);
                                if (nb.0 - cell.0, nb.1 - cell.1) != (ux, uy) {
                                    continue;
                                }
                            }
                        }
                    }
                    if expanded.contains(&nb) {
                        continue;
                    }
                    let occ_set = graph.occ.get(&nb);
                    let overuse = match occ_set {
                        Some(s) => {
                            let others = s.iter().filter(|&&id| id != net.net_id).count();
                            others as f64
                        }
                        None => 0.0,
                    };
                    let bias = cell_hash(nb, net.net_id, graph.sym_seed) as f64 * SYMMETRY_BREAK;
                    let base_cost = graph.base.get(&nb).copied().unwrap_or(BASE);
                    let hist_cost = graph.hist.get(&nb).copied().unwrap_or(0.0);
                    let enter = (base_cost + hist_cost + bias) * (1.0 + pres_fac * overuse);
                    let new_cost = cost + enter;

                    if new_cost < *dist.get(&nb).unwrap_or(&f64::INFINITY) {
                        dist.insert(nb, new_cost);
                        prev.insert(nb, cell);
                        pq.push(PqEntry {
                            f: new_cost + heuristic(nb),
                            y: nb.1,
                            x: nb.0,
                            layer: nb.2,
                            cost: new_cost,
                            cell: nb,
                        });
                    }
                }

                // Hop neighbors
                if allow_hops && graph.hop_range > 0 {
                    let (cx, cy, cl) = cell;
                    let mut skip_hops = false;

                    if let Some(&p) = prev.get(&cell) {
                        if (cx - p.0).abs() + (cy - p.1).abs() > 1 {
                            skip_hops = true;
                        } else if p.2 != cl {
                            skip_hops = true;
                        }
                    }

                    if !skip_hops && net.kind == NetKind::Fanin {
                        if *cell_out.get(&cell).unwrap_or(&0) > 0 {
                            skip_hops = true;
                        } else {
                            for &(dx2, dy2) in &DIRS {
                                if item_recv_cells.contains(&(cx + dx2, cy + dy2, cl)) {
                                    skip_hops = true;
                                    break;
                                }
                            }
                        }
                    }

                    if !skip_hops {
                        let approach = if let Some(&p) = prev.get(&cell) {
                            Some((cx - p.0, cy - p.1))
                        } else {
                            cell_approach.get(&cell).copied()
                        };

                        for &(dx, dy) in &DIRS {
                            if let Some(app) = approach {
                                if app != (dx, dy) {
                                    continue;
                                }
                            }
                            for hdist in 2..=graph.hop_range {
                                let nb = (cx + dx * hdist, cy + dy * hdist, cl);
                                if !graph.passable.contains(&nb) {
                                    continue;
                                }
                                if tree_cells.contains(&nb) && nb != terminal {
                                    continue;
                                }
                                if let Some(&owner) = graph.reserved.get(&nb) {
                                    if owner != net.net_id {
                                        continue;
                                    }
                                }
                                if let Some(&te) = net.terminal_exit.get(&nb) {
                                    if (dx, dy) != te {
                                        continue;
                                    }
                                }
                                // §0b: existing hop conflict check
                                let mut hop_conflict = false;
                                for d2 in (hdist + 1)..=graph.hop_range {
                                    let rpos = (cx + dx * d2, cy + dy * d2, cl);
                                    if graph.existing_receivers.get(&rpos) == Some(&(dx, dy)) {
                                        hop_conflict = true;
                                        break;
                                    }
                                    let spos = (nb.0 - dx * d2, nb.1 - dy * d2, cl);
                                    if graph.existing_senders.get(&spos) == Some(&(dx, dy)) {
                                        hop_conflict = true;
                                        break;
                                    }
                                }
                                if hop_conflict {
                                    continue;
                                }
                                // Adjacent receiver check
                                if net.kind != NetKind::Fanin {
                                    let mut adj_recv = false;
                                    for &(dx2, dy2) in &DIRS {
                                        if item_recv_cells.contains(&(nb.0 + dx2, nb.1 + dy2, cl))
                                        {
                                            adj_recv = true;
                                            break;
                                        }
                                    }
                                    if adj_recv {
                                        continue;
                                    }
                                }
                                if expanded.contains(&nb) {
                                    continue;
                                }
                                let occ_set = graph.occ.get(&nb);
                                let overuse = match occ_set {
                                    Some(s) => {
                                        s.iter().filter(|&&id| id != net.net_id).count() as f64
                                    }
                                    None => 0.0,
                                };
                                let hop_base = hdist as f64 * BASE + graph.hop_penalty;
                                let bias = cell_hash(nb, net.net_id, graph.sym_seed) as f64
                                    * SYMMETRY_BREAK;
                                let hist_cost = graph.hist.get(&nb).copied().unwrap_or(0.0);
                                let enter =
                                    (hop_base + hist_cost + bias) * (1.0 + pres_fac * overuse);
                                let new_cost = cost + enter;
                                if new_cost < *dist.get(&nb).unwrap_or(&f64::INFINITY) {
                                    dist.insert(nb, new_cost);
                                    prev.insert(nb, cell);
                                    pq.push(PqEntry {
                                        f: new_cost + heuristic(nb),
                                        y: nb.1,
                                        x: nb.0,
                                        layer: nb.2,
                                        cost: new_cost,
                                        cell: nb,
                                    });
                                }
                            }
                        }
                    }
                }

                // Lift neighbors
                if allow_hops && graph.lift_enabled {
                    let (cx, cy, cl) = cell;
                    for dl in [-1i32, 1] {
                        let nb = (cx, cy, cl + dl);
                        if !graph.passable.contains(&nb) {
                            continue;
                        }
                        if tree_cells.contains(&nb) && nb != terminal {
                            continue;
                        }
                        if expanded.contains(&nb) {
                            continue;
                        }
                        let occ_set = graph.occ.get(&nb);
                        let overuse = match occ_set {
                            Some(s) => s.iter().filter(|&&id| id != net.net_id).count() as f64,
                            None => 0.0,
                        };
                        let bias =
                            cell_hash(nb, net.net_id, graph.sym_seed) as f64 * SYMMETRY_BREAK;
                        let hist_cost = graph.hist.get(&nb).copied().unwrap_or(0.0);
                        let enter =
                            (LIFT_COST + hist_cost + bias) * (1.0 + pres_fac * overuse);
                        let new_cost = cost + enter;
                        if new_cost < *dist.get(&nb).unwrap_or(&f64::INFINITY) {
                            dist.insert(nb, new_cost);
                            prev.insert(nb, cell);
                            pq.push(PqEntry {
                                f: new_cost + heuristic(nb),
                                y: nb.1,
                                x: nb.0,
                                layer: nb.2,
                                cost: new_cost,
                                cell: nb,
                            });
                        }
                    }
                }
            }

            (found, dist, prev)
        };

        let (found, _dist, prev) = search(true);
        let (found, prev) = if !found {
            let (f2, _d2, p2) = search(false);
            (f2, p2)
        } else {
            (found, prev)
        };

        if !found {
            return Err(format!(
                "net {} ({}): terminal {:?} unreachable from tree of {} cells",
                net.net_id,
                if net.kind == NetKind::Fanin {
                    "fanin"
                } else {
                    "fanout"
                },
                terminal,
                tree_cells.len()
            ));
        }

        // Trace back
        let mut path: Vec<Cell> = Vec::new();
        let mut cur = terminal;
        while let Some(&p) = prev.get(&cur) {
            path.push(cur);
            cur = p;
        }
        let seed_cell = cur;
        path.reverse();

        let mut prev_cell = seed_cell;
        for &pc in &path {
            tree_edges.push((prev_cell, pc));
            let dx = pc.0 - prev_cell.0;
            let dy = pc.1 - prev_cell.1;
            let md = dx.abs() + dy.abs();
            if pc.2 != prev_cell.2 {
                lift_cells.insert(prev_cell);
                lift_cells.insert(pc);
            } else if md > 1 {
                hop_cells.insert(prev_cell);
                hop_cells.insert(pc);
                if net.kind == NetKind::Fanin {
                    item_recv_cells.insert(prev_cell);
                } else {
                    item_recv_cells.insert(pc);
                }
            }
            if md == 1 {
                cell_approach.insert(pc, (dx, dy));
            } else if md > 1 && pc.2 == prev_cell.2 {
                cell_approach.insert(pc, unit_dir(dx, dy));
            }
            *cell_out.entry(prev_cell).or_insert(0) += 1;
            *cell_in.entry(pc).or_insert(0) += 1;
            tree_cells.insert(pc);
            prev_cell = pc;
        }
    }

    // Fanin: flip edges
    if net.kind == NetKind::Fanin {
        tree_edges = tree_edges.into_iter().map(|(s, d)| (d, s)).collect();
    }

    net.tree_cells = tree_cells;
    net.tree_edges = tree_edges.clone();
    net.hop_edges = tree_edges
        .iter()
        .filter(|(s, d)| s.2 == d.2 && (d.0 - s.0).abs() + (d.1 - s.1).abs() > 1)
        .copied()
        .collect();
    net.lift_edges = tree_edges
        .iter()
        .filter(|(s, d)| s.2 != d.2)
        .copied()
        .collect();

    Ok(())
}

fn net_hpwl(net: &Net) -> i32 {
    let mut xs = vec![net.root.0];
    let mut ys = vec![net.root.1];
    for t in &net.terminals {
        xs.push(t.0);
        ys.push(t.1);
    }
    (xs.iter().max().unwrap() - xs.iter().min().unwrap())
        + (ys.iter().max().unwrap() - ys.iter().min().unwrap())
}

struct Snapshot {
    nets: Vec<(
        i32,
        FxHashSet<Cell>,
        Vec<(Cell, Cell)>,
        FxHashSet<(Cell, Cell)>,
        FxHashSet<(Cell, Cell)>,
    )>,
    hist: FxHashMap<Cell, f64>,
}

fn snapshot(nets: &[Net], graph: &RoutingGraph) -> Snapshot {
    Snapshot {
        nets: nets
            .iter()
            .map(|n| {
                (
                    n.net_id,
                    n.tree_cells.clone(),
                    n.tree_edges.clone(),
                    n.hop_edges.clone(),
                    n.lift_edges.clone(),
                )
            })
            .collect(),
        hist: graph.hist.clone(),
    }
}

fn restore(nets: &mut [Net], graph: &mut RoutingGraph, snap: &Snapshot) {
    for (i, n) in nets.iter_mut().enumerate() {
        for c in &n.tree_cells {
            if let Some(s) = graph.occ.get_mut(c) {
                s.remove(&n.net_id);
            }
        }
        let (_, ref cells, ref edges, ref hops, ref lifts) = snap.nets[i];
        n.tree_cells = cells.clone();
        n.tree_edges = edges.clone();
        n.hop_edges = hops.clone();
        n.lift_edges = lifts.clone();
        for c in &n.tree_cells {
            graph.occ.entry(*c).or_default().insert(n.net_id);
        }
    }
    graph.hist = snap.hist.clone();
}

pub fn pathfinder_route(
    seed_input: &SeedInput,
    params: &RoutingParams,
) -> (bool, Vec<NetResult>) {
    let mut graph = RoutingGraph::new(params, seed_input.sym_seed);
    let mut nets: Vec<Net> = seed_input.nets.iter().map(Net::from_input).collect();

    let own_ids: FxHashSet<i32> = nets.iter().map(|n| n.net_id).collect();

    // Sort: longest nets first
    let mut order: Vec<usize> = (0..nets.len()).collect();
    order.sort_by(|&a, &b| {
        let ha = net_hpwl(&nets[a]);
        let hb = net_hpwl(&nets[b]);
        hb.cmp(&ha).then(nets[a].net_id.cmp(&nets[b].net_id))
    });

    let max_iters = params.max_iters;
    let mut pres_fac = params.pres_fac_init;
    let stall_window = params
        .stall_window
        .unwrap_or_else(|| 15i32.max(nets.len() as i32));
    let mut prev_overuse_counts: Vec<usize> = Vec::new();
    let mut best_overuse = usize::MAX;
    let mut best_snap: Option<Snapshot> = None;

    for _iteration in 0..max_iters {
        for &idx in &order {
            let net = &mut nets[idx];
            // Rip up
            for c in &net.tree_cells {
                if let Some(s) = graph.occ.get_mut(c) {
                    s.remove(&net.net_id);
                }
            }

            // Re-route
            let _ = grow_tree(net, &graph, pres_fac);

            // Mark occupancy
            for c in &net.tree_cells {
                graph.occ.entry(*c).or_default().insert(net.net_id);
            }
        }

        let overused: Vec<Cell> = graph
            .occ
            .iter()
            .filter(|(_, s)| s.len() > 1 && s.iter().any(|id| own_ids.contains(id)))
            .map(|(&c, _)| c)
            .collect();

        if overused.is_empty() {
            let results = nets.iter().map(|n| n.to_result()).collect();
            return (true, results);
        }

        if params.keep_best && overused.len() < best_overuse {
            best_overuse = overused.len();
            best_snap = Some(snapshot(&nets, &graph));
        }

        prev_overuse_counts.push(overused.len());
        if prev_overuse_counts.len() > stall_window as usize {
            let start = prev_overuse_counts.len() - stall_window as usize;
            let recent = &prev_overuse_counts[start..];
            if *recent.iter().min().unwrap() >= recent[0] {
                break;
            }
        }

        // Re-sort: overused nets first
        let overused_set: FxHashSet<Cell> = overused.into_iter().collect();
        order.sort_by(|&a, &b| {
            let oa = nets[a].tree_cells.iter().any(|c| overused_set.contains(c));
            let ob = nets[b].tree_cells.iter().any(|c| overused_set.contains(c));
            let pa = if oa { 0 } else { 1 };
            let pb = if ob { 0 } else { 1 };
            pa.cmp(&pb)
                .then(net_hpwl(&nets[b]).cmp(&net_hpwl(&nets[a])))
                .then(nets[a].net_id.cmp(&nets[b].net_id))
        });

        // Update history
        for c in &overused_set {
            let occ_len = graph.occ.get(c).map_or(0, |s| s.len());
            if occ_len > 1 {
                *graph.hist.entry(*c).or_insert(0.0) +=
                    params.hist_gain * (occ_len as f64 - 1.0);
            }
        }
        pres_fac *= params.pres_fac_mult;
    }

    if params.keep_best {
        if let Some(ref snap) = best_snap {
            restore(&mut nets, &mut graph, snap);
        }
    }

    let results = nets.iter().map(|n| n.to_result()).collect();
    (false, results)
}

pub fn route_multi_seed(
    seed_inputs: Vec<SeedInput>,
    params: &RoutingParams,
) -> (bool, Vec<NetResult>) {
    use std::sync::atomic::{AtomicBool, Ordering};

    let found = AtomicBool::new(false);

    let results: Vec<(bool, Vec<NetResult>, usize)> = seed_inputs
        .par_iter()
        .enumerate()
        .map(|(idx, seed_input)| {
            if found.load(Ordering::Relaxed) {
                // Another seed already found a clean solution; skip.
                return (false, Vec::new(), usize::MAX);
            }
            let (ok, nets) = pathfinder_route(seed_input, params);
            if ok {
                found.store(true, Ordering::Relaxed);
            }
            let overuse = if ok {
                0
            } else {
                // Count overused cells from the results (approximate — we
                // don't have the graph, but we can count cells appearing in
                // multiple nets' tree_cells).
                let mut cell_count: FxHashMap<Cell, usize> = FxHashMap::default();
                for net in &nets {
                    for &c in &net.tree_cells {
                        *cell_count.entry(c).or_insert(0) += 1;
                    }
                }
                cell_count.values().filter(|&&v| v > 1).count()
            };
            let _ = idx; // suppress unused warning
            (ok, nets, overuse)
        })
        .collect();

    // Find the best result
    if let Some((ok, nets, _)) = results
        .into_iter()
        .filter(|(_, nets, _)| !nets.is_empty())
        .min_by_key(|(ok, _, overuse)| (if *ok { 0 } else { 1 }, *overuse))
    {
        (ok, nets)
    } else {
        (false, Vec::new())
    }
}
