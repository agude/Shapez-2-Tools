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

## Cutter (`CutterDefault`) — 1×2, 1 in / 2 out
Cuts vertically: **east half → main output, west half → secondary output.**
Two tiles side by side; one input. The **Mirrored** variant flips which tile
holds the input.

```
  O    O      east-half (main) + west-half (secondary)
 [E]  [W]     1×2 footprint, two tiles
  I           single input, south of the main tile
```

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

## Resolved: cutter is 1-in/2-out; the "2-in" was belts routing past
A cutter is a `Default`+`Mirrored` tile pair (1×2). One tile is the **input tile**
(in on the back, out on the front); the other is **output-only** (out on the
front; its half comes from the cut internally). Building images confirm the
canonical layout: **in ports on the left (W), out ports on the right (E).** The
swapper is the symmetric version — both tiles in W / out E, swap internal.

The corpus *looked* like 2-in/2-out only because the leg model counted belts
**routing past** the output-only tile as inputs. A count over the pure cutter: 16
cutter cells, **16 belt-outs (correct: 8 cutters × 2)** but **16 belt-ins, 8 of
them spurious** — exactly the 8 output-only tiles. So the lifter must (a) model the
cutter's two tiles distinctly (one output-only) and (b) require a machine *port*
to agree with the belt leg — a belt merely pointing at a machine's non-port side
is routing past, not connecting.

(Rejected theory: "cutter = one entity + one *implied* empty footprint cell" —
tested and false; no empty cells next to cutters receive any inflow.)
