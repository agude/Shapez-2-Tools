# Shapez 2 Machine Reference

Footprints and ports for the buildings the lifter must model.
Sources: the [Shapez 2 Wiki](https://shapez2.wiki.gg) (Cutting, Rotator pages)
plus direct measurement of the blueprint corpus.

**Convention:** top-down view, **North up**, shapes flow **south → north** unless
rotated. `I` = input, `O` = output. A building's `R` field rotates the whole
thing (**+1 = 90° CCW**).

**Absolute shape orientation.** Shapes carry a fixed *world* orientation — north
is always north. Cut / swap / half-destroy always act on the **absolute** west/
east halves no matter how the building is rotated; rotating one only changes its
belt I/O for routing, not its function. **Only a Rotator re-orients a shape.** So
to operate on a non-west part you rotate the shape to bring it west, apply the
(absolute) op, then rotate back — which is why extractors are full of rotators
(they are *addressing*, not incidental). The building still rotates physically
(footprint + ports turn with `R`); only the operation is rotation-invariant.

**Throughput:** every machine runs well below full-belt speed, so a **full lane
needs many machines in parallel.** That's why a lane fans `1 → N` into a bank of
machines and gathers `N → 1` afterward (e.g. the half-destroyer's `1 → 3 → 1`).

---

## Rotators — 1×1, 1 in / 1 out
`RotatorOneQuad` (90° CW), `RotatorOneQuadCCW` (90° CCW), `RotatorHalf` (180°).
Straight through; only the shape is rotated.

```
  O
 [R]
  I
```

## Half Destroyer (`CutterHalf`) — 1×1, 1 in / 1 out
Destroys the **west** half, outputs the **east** half. No waste output.

```
  O
 [H]
  I
```

## Cutter (`CutterDefault`) — 1×2, 1 in / 2 out (one entity)
Cuts vertically: **east half → main output, west half → secondary output.**
A cutter is a **single entity** spanning two cells: the **anchor** takes the one
input on its back and emits the main (east-half) output on its front; an
**output-only second cell** emits the secondary (west-half) output on its front
and has **no input**. The second cell sits to the **right** of the flow
direction for `Default` and to the **left** for `Mirrored` (the only difference
between the two variants — both are single entities).

```
  O   O       front: main output (anchor) + secondary output (2nd cell)
 [A][2]       A = anchor (also takes the input); 2 = output-only second cell
  I           single input, on the anchor's back
```

Verified on `data/reference/cutters_8_pinwheel.spz2bp` (all 4 rotations × both
variants: anchor = IN-back + OUT-front, second cell = OUT-front only) and on the
dense `cutter_12_to_24.spz2bp` (16 independent cutters per floor, footprints tile
with zero overlap, the whole floor lifts at **0 unmatched legs**, every cutter
in-degree 1 / out-degree 2). Modeled in `lift._machine_footprint`.

## Swapper (`HalvesSwapper`) — 1×2, 2 in / 2 out
Swaps the **west halves** of two shapes. Halves stay side by side (not stacked),
so crystals survive. Two tiles, two inputs, two outputs.

**Works on empty parts too.** Feed one shape with only its north quadrants and
another with only its south quadrants, swap the (absolute) west halves, and the
two **diagonals** fall out. This is the core trick of the diagonal extractors.

```
  O    O      two outputs
 [ |  | ]     1×2 footprint
  I    I      two inputs
```

**Calibration: confirmed.** A swapper is **one entity** spanning two cells:
anchor + a second cell to the **right** of flow (`rot(S, R)`); a hypothetical
`Mirrored` would put it left. **Both cells are `in-back / out-front`** — 2-in/
2-out — the two west halves are swapped internally. Determined without a belted
template by brute-forcing footprint hypotheses against the existing
`Swappers/Swap Diagonal.spz2bp`: this model lifts that blueprint at **0 unmatched
legs** (32 swappers, each in-degree 2 / out-degree 2); every other hypothesis
(second cell output-only, or left) leaves many unmatched. Saved as
`data/reference/swap_diagonal.spz2bp`; modeled in `lift._machine_footprint`.

## Stacker (`StackerDefault` / `StackerStraight`) — 1×1, 2 in / 1 out, one input vertical
Stacks a secondary shape on top of a primary. A stacker is a **single 1×1 cell**
on its floor with **two inputs** and **one output**:
- **primary input** — the anchor's back, same floor (`rot(W, R)`).
- **secondary input** — from the **floor above**: the feeding belt sits on `L+1`
  and its output lands on the anchor's `(x, y)`, dropping the shape into the
  stacker. This is a genuine **cross-floor** connection.
- **output** — same floor:
  - `StackerStraight` → anchor **front** (`rot(E, R)`), straight through.
  - bent `StackerDefault` → anchor **right** (`rot(S, R)`); `…Mirrored` → **left**
    (`rot(N, R)`). The 90° turn is the only Default/Mirrored difference.

Verified across all 12 stackers in `stackers_straight_4.spz2bp` (4 straight) and
`stackers_bent_8.spz2bp` (4 + 4 mirrored), every rotation: each has a same-floor
back input, an L+1 vertical input over the anchor, and the output above.

**Lifter implication:** the rotator family had independent floors ("no lifts"),
so the lifter is per-floor today. The stacker is the **first machine that
connects floors**, so lifting it needs vertical-port support in the occupancy
model (read a cell at `L±1`). Until then the stacker's structure is known but not
lifted. The stacking *semantics* (how two shapes combine into layers) are still
needed for the simulator.

## Painter (`Painter` / `PainterMirrored`) — needs a pipe layer
Painters consume a **fluid** (paint) delivered on a separate **pipe** transport
layer (`PipeForward`, …) alongside the shape belts. The lifter has no pipe
routing model yet, so painters can't be lifted until pipes are calibrated as a
second routing layer. `Painter` is a single entity; footprint spans a larger
region (≈2×4). Deferred until the pipe layer exists.

---

## Routing primitives (calibrated — see `lift.py`)
Belts + junctions. `R` rotates +90° CCW; a junction is just a belt with extra
legs, flow direction decides split vs merge.

| Variant | legs |
|---|---|
| `BeltDefaultForward` | in back → out front |
| `BeltDefaultLeft` / `…Mirrored` | in back → out one side (left / right) |
| `Splitter1To2L` / `1To3` / `TShape` | 1 in → 2–3 out |
| `Merger2To1L` / `3To1` / `TShape` | 2–3 in → 1 out |
| `BeltPortReceiver` / `BeltPortSender` | platform-edge in / out |

---

## Resolved: cutter is ONE entity + an output-only second cell (1-in/2-out)
The clean export `data/reference/cutters_8_pinwheel.spz2bp` settled the encoding:
**each cutter is a single `CutterDefault…` entity** (8 cutters = 8 entities,
4 `Default` + 4 `…Mirrored`, in two pinwheels). It occupies a 1×2 footprint =
anchor + an **output-only** second cell to the side (right of flow for `Default`,
left for `Mirrored`). Ports: one input on the anchor's back; two outputs (anchor
front = east half, second-cell front = west half).

This **overturns the earlier "`Default`+`Mirrored` tile pair = one cutter"
conclusion**, which was an artifact of the dense `12→24` blueprint: there the
cutters pack as vertically-adjacent `Default`/`Mirrored` *pairs*, so two
independent interlocking cutters looked like one 1×2 machine. The previously
*rejected* "one entity + implied cell" theory is in fact correct — the implied
cell is not empty and not an input, it is an **output-only** tile, which is why
belts L-turning past it were miscounted as inputs.

With the second cell modeled as output-only (no input side), a belt merely
pointing at it does not connect, and the dense floor lifts at **0 unmatched
legs** with 16 cutters × (in-degree 1, out-degree 2). See
`lift._machine_footprint` and `tests/test_lift.py::TestCutter`.
