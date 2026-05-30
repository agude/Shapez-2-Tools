# Blueprint Synthesis — Plan

**Status:** Draft, updated 2026-05-29.

**North star:** synthesize *dense, compact, single-platform* blueprints from a
functional spec — e.g. "on a 2×8 full belt, extract both diagonals and pin the
upper-left diagonal to the 4 left outputs and the upper-right to the 4 right."
These are hard to route by hand and are what make factories compact. That is the
product.

**Easy platforms are the test harness, not the goal.** A "rotate 12 belts 180°"
is a 10-second hand build; here it exists only as an end-to-end test and a
regression floor. The hard target is intra-platform **place-and-route**.

---

## 1. What we know (verified against the corpus)

### Format & codec
- Envelope `SHAPEZ2-4-<base64(gzip(JSON))>$`; game `V=1137`.
- Two-level nesting: Island `BP.Entries` = platforms → each platform `.B.Entries`
  = buildings in platform-local coordinates.
- Building entry `{X, Y, R, L, T}` (R rotation 0–3, L layer 0–2, both omitted when 0).
- **Codec is faithful**: decode→encode reproduces the decompressed JSON
  byte-for-byte (only the gzip mtime differs). No codec work needed.

### Tile-replication family (lane-preserving 1×1→1×4 belt ops)
- Atom = **one floor of a quarter = 80 functional entities**.
- **Floors are exact duplicates** (only a cosmetic `Label` differs on L0); each
  floor is a self-contained 2-D circuit — **no lifts in this family**.
- **Full belt = 4× quarter, exactly**, at coordinate pitch 20. Verified for
  rotators *and* half-destroyers *and* speed-readers (all 4×).
- **CW/CCW = the 180 tile with only the rotator building type swapped**; the only
  per-direction wrapper difference is the island icon
  (`RotatorHalfVariant`/`RotatorOneQuadVariant`/`RotatorOneQuadCCWVariant`).

### Split/merge are belt junctions, not machines
- Shapez has no merger/splitter *building*: a "junction" is just a **belt cell
  with an extra leg** (a T/X). Whether it splits or merges is only the flow
  direction — legs sticking *out* = split (1 in / 2 out, `Splitter1To2L`), legs
  sticking *in* = merge (2 in / 1 out, `Merger2To1L`). Same geometry, reversed flow.
- A junction is general — any in/out split over ≤4 legs. Corpus routing variants:
  merges `2To1L`(+mir) / `3To1` / `TShape`, splits `1To2L`(+mir) / `1To3` / `TShape`,
  1/1 belts `Forward` / `Left`(+mir), plus `BeltFilter`(+mir) (routes by shape — a
  predicate) and `BeltReader`(+mir) (emits a wire signal). ~15 variants.
- They belong to the **routing layer** alongside straight and turn belts.
  Operation nodes in the netlist are only the actual machines (rotators, cutters…).
- **Lift's belt-direction calibration is this table**: each variant × R →
  (input sides, output sides). The tracer must handle arbitrary fan-in/fan-out.

### Belt-direction model (calibrated for the rotator family)
- Convention: **+1 in R = 90° CCW**. Each routing variant has fixed input/output
  sides at R=0, rotated by R (Forward: in=back / out=front; turns: out = one
  perpendicular; junctions: the multi-leg pattern).
- Validated on the rotator quarter: **0 unmatched legs**, and `lift.trace_layer`
  recovers its exact netlist (4 inputs each split to 2 rotators, 8 rotators each
  merge to 1 output) — and the full belt as 4× that. See `lift.py`.
- Calibrated (0 unmatched legs on the rotator quarter *and* the half-destroyer):
  all routing variants — Forward / Left(+mir) / Filter / Reader, `Splitter`
  `1To2L`(+mir)/`1To3`/`TShape`, `Merger` `2To1L`(+mir)/`3To1`/`TShape`, ports,
  rotator. Remaining gap: **multi-port machines** (cutters 1→2, swappers 2→2) —
  they read as vertical pass-through cells but still leave unmatched legs, so
  footprint/side-port handling is the next milestone.

### Shapes have absolute orientation
- A shape's orientation is fixed in **world** space — north is always north.
- Cut / swap / half-destroy act on the **absolute** west/east halves regardless of
  building rotation; rotating those buildings only re-routes belts, not function.
  **Only a Rotator re-orients a shape.**
- So to reach a non-west part you rotate the shape west, apply the op, rotate back
  — which is why extractors are dominated by rotators (they are *addressing*).
- This is a **simulator** fact (Rungs 2/4); it does not affect the belt-topology
  lift (ports still rotate with `R`). Detail in `docs/machines.md`.

### Decoration is per-blueprint signage
- `Trash` spells pixel-art names (e.g. "180"/"CW"/"CCW") on the rotators' L0 —
  ad-hoc, not systematic, and absent from most families.
- **`Trash` is functional in the Trash family.** So decoration detection must be
  **family/position-aware, never type-based** (a current latent bug in
  `DECORATION_TYPES`).

### Platform geometry (seam model) — see `data/platforms.json`
- Each unit is 20×20 bounding / 16×16 buildable (2-cell border). **Joining units
  fills the shared border: +4 cells per internal seam.**
- Interior = `20·units − 4` per axis. Verified: 1×1 = 16×16 (corpus), 1×4 = 76×16
  (M2). Generalizes to any size (2×4 = 76×36, 2×8, …).
- `platforms.json` rewritten with the unit model, correct interiors, provenance
  flags, and the four previously-missing platforms.
- Corpus extents are confounded by per-platform rotation and belt/port sprawl, so
  geometry is taken from the model, not raw measurement.

### Per-family parametrics (reference)
- Lane-preserving belt ops: **12 in / 12 out** (quarter), **48 / 48** (full belt).
- Lane-changing (cut 12→24), multi-input (stack/swap → 2×4/2×2), and fluid ops
  (painter/crystallizer/miner) have operation-specific port counts and platforms.
- Diagonal extractors are routing-dominated: e.g. `Full Belt Shape to Upper Left
  Diagonal` on a 2×4 is in=48, out=96, with **3456 belts** — ~95% routing.

### Composition
- A composite ("destroy west half **then** rotate 180") is a pipeline of named ops.
- Valid when lane signatures line up (12→12 | 12→12).
- Two lowerings of the same spec: **chain of platforms** (space-belt connected —
  easy) vs **co-placed on one platform** (place-and-route — the goal).

---

## 2. Architecture (the real target)

- **Netlist IR** — a directed dataflow graph. Nodes = operations with typed ports,
  lane signatures, throughput; edges = nets; output ports may be *pinned* to
  specific physical positions. Placement-free.
- **Lowering** — netlist → placement (cell, layer, rotation per building) →
  routing (3-D belts with Forward/Left/Left-Mirrored turn-typing, lifts as vias,
  throughput-aware) → entities → file.
- **Simulator** — push shapes through the netlist (does it compute the spec?) plus
  a physical validator (no overlaps, ports connect, on legal cells).
- Tile-replication is the **degenerate case**: one fixed placement, straight-lane
  routing, lane-preserving. It exercises the whole I/O + verification loop.

---

## 3. The ladder

Your hand-built library is the **oracle at every rung** — it supplies both the
spec library and the measuring stick.

- **Foundation — DONE.** Codec, `Entity` model, functional `diff`, seam-accurate
  geometry, corpus oracle. Tile-replication **M1** (quarter reproduced) and **M2**
  (full belt = 4× quarter, built from the quarter tile) verified.
- **Scaffolding — DESIGNED, not landed.** Single-op `generate_rotator` (180/cw/ccw
  × 1×1/1×4) + `gen`/`diff` CLI verbs; extend the tile family to half-destroyers
  and speed-readers. This is the regression floor, not the product.
- **Rung 1 — Lift (underway).** Decompile a placed blueprint into a netlist by
  tracing the oriented belt graph. All routing variants are calibrated; `lift.py`
  lifts the rotator family and the half-destroyer at 0 unmatched legs (see §1).
  Next: a **machine-definition table** (footprint + ports per type). The generic
  1-in/1-out "straight through" machine model holds only when belts sit on both
  ends; in dense packing it breaks — e.g. a rotator fed by a belt on its east and
  a cutter on its south has no west input at all. Cutters (1×2, 1 in / 2 out) and
  swappers (1×2, 2 in / 2 out) compound this: their belt-facing ports match, but
  the second output and machine-to-machine couplings don't, so downstream
  machines get dangling inputs. Derive footprints + ports per type from the pure
  blueprints by examining *all* neighbours (belts and machines), then the
  extractor lifts.
- **Rung 2 — Simulate.** Shape model + op transforms + physical validator. Makes
  "correct" mean *computes the function*, not *belts connect*. Needed in full only
  at Rung 4 — Rung 3 can defer it via structural validation (see below).
- **Rung 3 — Re-route a known netlist.** Strip the placement off a lifted example;
  have the router reproduce a **valid** (then **compact**) layout; measure against
  the human-optimal original. The first real place-and-route. Validity can be
  checked **structurally** — lift the routed output and assert graph-isomorphism
  back to the input netlist — so the shape simulator is not required here.
- **Rung 4 — Synthesize from spec.** "Extract both diagonals, pin to L/R outputs"
  → netlist → place-and-route. The product.

---

## 4. Acceptance

- Tile cases: functional-entity `diff` against the corpus oracle.
- Netlist cases: simulation equivalence to the spec.
- Routing: physical validity + functional equivalence; **compactness measured
  against the human oracle**.
- Final gate (manual): loads and runs in-game.

---

## 5. Open questions

- Decoration detection: family/position-aware, not type-based.
- Output-port pinning: how the netlist encodes "this result → that physical port".
- Routing objective: fit-first, then compactness; how to measure vs human.
- Icon convention mismatch (`icon:Platforms` used for both quarter and full belt);
  `BinaryVersion` meaning.

---

## 6. Dependencies / build-vs-buy

Guiding principle: **buy the generic search, build the domain.** You cannot buy
Shapez-2 shape/format/belt knowledge; you should not hand-roll a constraint solver.

- **Codec** (gzip/base64/json): stdlib. Built.
- **Netlist graph**: likely `networkx` (traversal, topo-sort, connectivity).
- **Shape model + simulator**: in-house (domain-specific to Shapez 2). Survey
  existing community tooling first for a reference implementation (web search was
  rate-limited; revisit).
- **Blueprint lowering / belt turn-typing**: in-house (format-specific).
- **Placement search**: a constraint solver (`OR-Tools` CP-SAT, or SAT/SMT) —
  do not hand-roll. Needed only at Rung 3.
- **Routing (multi-net, 3-D)**: mostly in-house; no clean Python package. A* core
  can lean on `networkx`; CP-SAT may absorb small instances.
- **CLI**: `argparse` (stdlib) now; `typer`/`click` optional later.

**Phasing:** Rungs 1–2 need at most `networkx`; `OR-Tools` arrives only at Rung 3.
The dependency footprint stays near-zero until the solver phase.

**Structural validation** (Rung 3 graph-isomorphism) defers the shape simulator
to Rung 4.

**The corpus de-risks every buy:** validate CP-SAT placement and the router
against human-optimal layouts before trusting them on novel specs.
