# Routing Research

Findings from investigating the 16-lane routing failure and the band-width
vs. crossing-range problem. Date: 2026-06-15.

---

## The core problem: belt band width vs. hop range

In-game hop range: 1–4 blank tiles between sender and receiver
(`MAX_HOP_RANGE = 5` in hdist). A contiguous belt band wider than 4 cells
**cannot be jumped by a single hop**. Lifts can cross any width (go up, walk
across, come back down) but cost 2 cells on each of the 3 available floors.

The stage-band placement model creates inter-stage channels that carry all
belts connecting those stages. For 16-lane × 4-cutter on Foundation_2x4:

| Channel                | Total belts | Per group (4 groups) | Hoppable? |
|------------------------|-------------|----------------------|-----------|
| Source → splitter      | 16          | 4                    | Yes (at limit) |
| Splitter → cutter      | 64          | 16                   | **No**    |
| Cutter → merger         | 128         | 32                   | **No**    |
| Merger → sink           | 32          | 8                    | **No**    |

Any net needing to cross one of the "No" channels laterally is stuck unless
it uses a lift — and lift capacity is bounded by 3 floors.

**The 16-lane failure (21 overused cells, 1868s) is not a router tuning
problem. It is a placement topology problem: the stage-band layout creates
physically uncrossable bands.**

---

## How dense human builds actually work

### The human Half Splitter: columnar layout

The human Half Splitter uses vertical lane columns, not horizontal stage
bands. Each lane is a column: source at bottom → splitter tree → 4 stacked
cutters → merger trees → output at top. Within a lane, the widest parallel
belt run is 4 (from the 1:4 split) — exactly at hop limit.

Cross-lane routing only appears at the output-gathering step (merged outputs
→ correct side ports). The 145 hops in the human build are all in this final
step, crossing individual lane columns (1–4 belts each), not wide stage bands.

### The Full Belt Stacker: hop relay chains are the dominant technique

`Stackers/Full Belt Stacker.spz2bp` — 192 stackers on Foundation_2x4, all
3 floors used, 5058 total entities:

| Category              | Count | % of total |
|-----------------------|-------|------------|
| Belts (fwd/turn)      | 3346  | 66%        |
| Hop senders+receivers | 990   | 20%        |
| Machines (stackers)   | 192   | 4%         |
| Lifts                 | 134   | 3%         |
| Junctions (split/merge)| 396  | 8%         |

**20% of the build is hop relay infrastructure.** 423 hop pairs across 3
floors, plus 134 lifts. Hop distances vary (29 at dist 2, 35 at dist 3, 55
at dist 4, 304 at dist 5) — not just max-range; shorter hops are used freely
where they fit.

Per floor: ~150 senders + ~166 receivers on L0 and L1; ~171 + ~187 on L2.
All 3 floors carry routing, not just machines.

### The Launchers template: multi-belt relay corridors

`TEMPLATES/Launchers.spz2bp` demonstrates the relay multiplexing pattern.
At row y=8, layer 0, 4 belts enter from the platform left edge (y=8..11).
Three of them are staggered into senders at x=8, x=10, x=12 and then relay
across the full platform width as 3 interleaved chains:

```
Chain 1: S@8 -> R@13 -> S@14 -> R@19 -> S@20 -> R@25 -> S@26 -> R@31
Chain 2: S@10-> R@15 -> S@16 -> R@21 -> S@22 -> R@27 -> S@28 -> R@33
Chain 3: S@12-> R@17 -> S@18 -> R@23 -> S@24 -> R@29 -> S@30 -> R@35
```

Each hop is distance 5 (4 blank tiles, maximum range). Receivers feed
directly into the adjacent sender (R→S coupling, no belt cell between).
The ground-cell pattern from x=13 onward is alternating `R S R S R S ...`
at every cell.

Layer 1 carries additional chains at the same y, and each floor is
independent. **Total capacity: 3 belts per row per floor, 9 per row
across 3 floors.**

Row y=15 shows 2 interleaved chains per floor. Row y=14: a single relay
chain spanning the full platform width in 5 hops.

### The relay chain capacity model

A **relay chain** carries one belt across an arbitrary distance using a
sequence of hops: sender → (flight over 4 blank tiles) → receiver → sender
→ .... The receiver-to-sender transition is direct adjacency (1 cell).

The repeating unit is 6 cells: `S _ _ _ _ R` (sender + 4 blank + receiver).
Within those 4 blank flight cells, 2 more sender-receiver pairs fit at
2-cell pitch: `S . S . S R . R . R` (3 senders staggered, 3 receivers
staggered, each pair at distance 5). This is the origin of the **3-chain
limit per row per floor**.

```
Capacity per row: 3 belts/floor × 3 floors = 9 belts total
Capacity per N-row corridor: 9N belts
```

A 4-row relay corridor carries 36 belts — sufficient for even the densest
inter-stage channels (the 32-belt merger→sink channel of the 16-lane Half
Splitter fits in 4 rows).

**This is how dense human builds solve the "band wider than 4" problem.**
They don't avoid wide bands or force spacing. They route through the density
using hop relay chains that multiplex 3 belts per row per floor.

### Hop pairing rule

The pairing rule is positional: each receiver catches from the **furthest**
sender within range along the sender's facing direction with the same
rotation. When multiple senders face the same direction, the furthest-first
rule ensures the 3-chain interleaving works: chain 1's sender at the back
pairs with the first receiver, chain 2's sender (2 cells closer) pairs with
the second receiver, etc. The exact ordering may be more nuanced — see
`TEMPLATES/Launchers.spz2bp` for all working patterns and QUESTIONS.md Q10
for the open verification task (current `_resolve_hops` uses nearest-first,
which may need to change to furthest-first).

Launcher range used to be fixed at 4 spaces (hdist=5). Variable-distance
launchers (hdist 2–5) were added later. The Full Belt Stacker (game version
1137) uses all four distances; older builds may assume fixed distance 5. The
current `MAX_HOP_RANGE = 5` cap is correct regardless.

---

## What FPGA CAD tells us (and doesn't)

### What we already have

PathFinder (McMurchie & Ebeling 1995) negotiated-congestion routing. We run
it at cell granularity — this is the "detailed routing" step in FPGA
terminology. At ~150 nets on ~8000 cells we are tiny by FPGA standards
(VPR handles 100k+ nets).

### What standard FPGA tools add: global routing

FPGA tools insert a **coarse global routing** pass before detailed routing:
abstract the grid as ~4×4-cell tiles with capacity = tile_width × floors,
run PathFinder on the coarse graph, then detail-route within the assigned
channels. This catches unjumpable bands as "channel over capacity" before
detailed routing wastes time.

**At our scale this would detect infeasibility faster (milliseconds vs.
1868s) but would not fix it.** The fix is upstream in placement. A global
routing phase is worth adding as a fast feasibility check and as a way to
produce channel assignments that guide detailed routing — but it is not the
primary solution.

### RUDY congestion estimation

RUDY (Rectangular Uniform wire Density) is a fast congestion estimator used
**during placement**: smear each net's demand uniformly over its bounding
box, sum per tile, compare to tile capacity. Used in routability-driven
placers (RippleFPGA, OpenPARF) to steer machines away from hotspots before
routing runs. Could be added to our CP-SAT objective as a soft penalty.

---

## What Factorio-SAT tells us

Factorio has the same constraint: underground belts have a fixed range (4/6/8
tiles by tier). Factorio-SAT (R-O-C-K-E-T) encodes the full grid as a SAT
problem with underground flow as a **second independent grid** coupled to the
surface only at entry/exit points. Works for small boxes (~16×16). CP-SAT
reimplementation (Venturini) scales to ~256 tiles with symmetry breaking.

**At our 76×36 scale, full SAT encoding is infeasible as the primary router.**
Confirmed viable as a **local repair tool** for stubborn congested windows of
~50 cells after PathFinder converges everywhere else (the pattern already
noted in generator-spec.md §6).

---

## VLSI channel routing: the density lower bound

Classic result: channel density `d_max` = max number of nets crossing any
column of a routing channel. This is a **hard lower bound** on required
tracks. If `d_max` exceeds channel height, the instance is **provably
unroutable** — no algorithm fixes it. Fix is upstream: widen the channel or
split across layers.

**Directly applicable.** Our inter-stage channels are VLSI channels. The
naive density check during placement would be:

    d_max(cross_section) ≤ (hop_range - 1) + lift_crossings_available

But relay chains (see above) raise the effective capacity to 3 belts per row
per floor (9 per row across 3 floors), so the real constraint is:

    d_max(cross_section) ≤ 9 × corridor_rows

The current density constraint (`place.py`) counts nets per x-bucket
globally, not per physical cross-section accounting for either limit. It
catches some infeasibility but misses both the hop-range ceiling and the
relay chain opportunity.

---

## Shapez 2 community

No automated routing or synthesis tools exist. The community has codec/
viewing/sharing tools only (shapez-vortex, community-vortex.shapez2.com).
We are the only project attempting place-and-route.

---

## Candidate approaches

### A. Hop relay corridor routing (from the human builds)

Teach the router to build **relay chains**: sender → flight → receiver →
belt → sender → ..., where multiple chains share a corridor via interleaving
and flight stacking. This is how the Full Belt Stacker achieves 20%
hop-infrastructure density and how the Half Splitter crosses lane columns.

The current router uses hops for point-to-point crossing (one belt per hop
pair). It has no concept of relay chains or interleaved sender/receiver
placement. Extending it requires:
- Relay chain planning: decide where corridors go and how many chains each
  carries (max 3 per row per floor)
- Interleaved sender/receiver placement within corridors (the `S.S.SRSR...`
  pattern)
- Modified routing graph: a relay corridor row has capacity 3 (not 1)
- Modified cost model: relay chains amortize the hop overhead across the
  corridor length

**Trade-offs:** Matches what dense human builds actually do. Requires
significant router extension — the routing graph model changes from
"1 net per cell" to "1 ground occupant per cell but N flights overhead."
Most complex option but solves the fundamental bandwidth problem.

### B. Columnar placement for fan topologies

Mirror the human Half Splitter layout: assign each lane to an x-column,
stack machines vertically within a lane. Cross-lane routing only at output
gathering. Maximum intra-lane band width = fan-out degree (4 for the cutter
fan) = hoppable.

**Trade-offs:** Directly solves the band-width problem for the Half Splitter.
Requires topology detection (fan stages get columns, serial stages get
bands). Natural for 1→N / N→1 fan structures; less clear for arbitrary
topologies. Does not address the stacker's routing pattern (which is not
columnar — it's fully interleaved).

### C. Template-based placement

Extract compact machine+routing tiles from human builds and use them as
placement templates. E.g., the Full Belt Stacker has a repeating unit: one
stacker pair (Default + Mirrored) with their input feeds and output routing.
The Stacker 2 (1x1, 48 machines) is a tighter version of the same pattern.

**Approach:** lift the human build, identify the repeating tile, encode it as
a placement template with parameterized port positions. The placer tiles
templates instead of placing individual machines. Routing within a template
is solved (copied from the human build); only inter-template routing needs
PathFinder.

**Trade-offs:** Leverages human expertise directly. Limited to topologies
with known templates. Template extraction could be automated (find the
repeating unit in a lifted netlist) or manual (the user provides a tile).
Doesn't generalize to novel specs without a template. But for the stacker
and half splitter families, templates exist.

### D. Crossing-feasibility constraint in the placer

Add an explicit constraint to CP-SAT: for each vertical cross-section of
each inter-stage channel, `d_max ≤ crossing_capacity`. The crossing capacity
accounts for relay chain bandwidth:

    capacity(corridor) = 3 chains/row/floor × corridor_rows × 3 floors
                       = 9 × corridor_rows

A 4-row relay corridor carries 36 belts. The density model is much more
permissive than the naive `hop_range - 1` limit, but the placer needs to
reserve the corridor rows (they can't contain machines or plain belts).

**Trade-offs:** Prevents the placer from creating provably unroutable
geometries. Requires modeling relay chain bandwidth, which is the hard
part — how many interleaved chains fit in a given corridor? The Full Belt
Stacker data gives empirical calibration.

### E. Forced spacing between groups

Leave gaps in belt bands so hops can cross them. E.g., every 4 belts, leave
a 1-cell gap.

**Trade-offs:** Simple to implement. But the Full Belt Stacker (62% cell
utilization, 5058 entities on a 2x4) and the Half Splitter (1562 entities,
single floor) show that dense human builds do NOT use spacing — they fill
every cell and cross via hops/lifts. Forced spacing wastes area that could
carry more routing. Likely only viable for low-density specs where area is
not a constraint.

### F. Coarse global routing as feasibility check

Build a ~475-tile coarse grid (4×4-cell tiles × 3 floors), run PathFinder on
it, check for channel overflow. Fast rejection of infeasible placements
(milliseconds vs. 1868s of futile detailed routing).

**Trade-offs:** Detects infeasibility fast but doesn't fix it. Value is in
fast feedback to the placement retry loop. Less important if the placer
already has good crossing-feasibility constraints (D).

### G. RUDY congestion proxy in CP-SAT objective

Estimate per-tile congestion during placement, add as a soft penalty.
RUDY (Rectangular Uniform wire Density): smear each net's demand over its
bounding box, penalize tiles where demand exceeds capacity.

**Trade-offs:** Heuristic — doesn't guarantee routability. Useful as a
steering signal combined with hard constraints. Well-studied in FPGA CAD
(RippleFPGA, OpenPARF).

### H. CP-SAT local repair for residual hotspots

After PathFinder converges everywhere except a small congested window (~50
cells), encode that window as a CP-SAT model with exact belt/hop/lift
constraints. Proven viable at this scale by Factorio-SAT (works up to
~16×16 = 256 tiles). Already noted in generator-spec.md §6.

**Trade-offs:** A cleanup tool, not a primary strategy. Complements any
of the above.

---

## Analysis

The options split into two categories:

**Placement strategies (B, C, E)** change how machines are arranged to avoid
creating unroutable geometries. Columnar (B) and template (C) are the
strongest — they directly encode human expertise. Spacing (E) is weak:
the evidence from dense builds is that humans don't use it.

**Routing strategies (A, D, F, G, H)** extend what the router can handle.
Relay corridor routing (A) is the big one — it's the technique that makes
the Full Belt Stacker possible and represents the largest gap between what
human builds do and what our router can express. The feasibility constraint
(D), global routing (F), and RUDY (G) are supporting infrastructure. Local
repair (H) is a known-viable cleanup tool.

The key question: **should we teach the router to build relay chains (A), or
should we arrange machines so relay chains aren't needed (B/C)?**

Arguments for A (relay chains):
- It's what all dense human builds use (Full Belt Stacker: 20% hop relay)
- It solves the bandwidth problem at the routing level, independent of
  placement strategy
- Without it, the router is fundamentally limited to specs where every
  crossing fits in a single hop — a small subset of real designs

Arguments for B/C (placement):
- Simpler to implement than relay chain routing
- Columnar layout (B) directly solves the Half Splitter
- Templates (C) leverage human expertise for known topologies
- The Half Splitter (the current north star) is columnar, not relay-heavy

**They aren't mutually exclusive.** The likely end state is both: columnar
or template-based placement to keep most routing local, plus relay chain
capability in the router for the inter-column gathering step. The question
is sequencing.

---

## Recommendation

**Near term (unblock 16-lane Half Splitter):** columnar placement (B). It's
the smallest change that directly addresses the blocker, it's validated by
the human build, and it keeps the router changes minimal (point-to-point
hops suffice for crossing lane columns of width ≤ 4).

**Medium term (Full Belt Stacker class):** relay corridor routing (A) plus
crossing-feasibility constraints (D). The stacker's topology is not columnar
— it's fully interleaved with massive hop relay infrastructure. Reaching this
class of design requires the router to understand relay chains.

**Template-based placement (C)** is worth exploring in parallel — if the user
provides (or we can extract) compact tiles for common topologies, it
short-circuits both placement and intra-tile routing. The question is whether
template extraction can be automated or requires manual curation.

**Skip forced spacing (E)** — the evidence is clear that dense builds don't
use it.

---

## External references

### FPGA CAD
- PathFinder: McMurchie & Ebeling 1995, doi:10.1145/201310.201328
- VPR/VTR: docs.verilogtorouting.org
- OpenPARF: arxiv.org/html/2306.16665v1
- RUDY: Spindler & Johannes, "Fast and Accurate Routing Demand Estimation"
- RippleFPGA: doi:10.1145/2966986.2980084

### Factorio
- Factorio-SAT: github.com/R-O-C-K-E-T/Factorio-SAT
- Venturini reimplementation: gianlucaventurini.com/posts/2024/factorio-sat

### Shapez 2 community
No automated routing or synthesis tools exist. Codec/viewing/sharing only
(shapez-vortex, community-vortex.shapez2.com). We are the only project
attempting place-and-route.

### Corpus evidence (measured 2026-06-15)

| Blueprint | Platform | Machines | Hop pairs | Lifts | Total entities |
|-----------|----------|----------|-----------|-------|----------------|
| UNFINISHED Half Splitter | 2x4 | 208 | 145 | 0 | 1562 |
| Full Belt Stacker | 2x4 | 192 | 423 | 134 | 5058 |
| Stacker 2 | 1x1 | 48 | ~48 | 24 | 464 |
| Launchers (template) | 1x1 | 2 | 35 | 6 | 352 |
