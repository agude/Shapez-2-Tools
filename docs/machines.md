# Shapez 2 Machine Reference

Footprints and ports for the buildings the lifter must model.
Sources: the [Shapez 2 Wiki](https://shapez2.wiki.gg) (Cutting, Rotator pages)
plus direct measurement of the blueprint corpus.

**Convention:** top-down view, **North up**, shapes flow **south → north** unless
rotated. `I` = input, `O` = output. A building's `R` field rotates the whole
thing (**+1 = 90° CCW**). All cut/swap ops act on **east–west halves** regardless
of rotation.

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

## Open: exact tile↔port mapping for the 1×2 machines
Footprints and port counts (above) are confirmed, but the corpus packs cutters
and swappers densely — the two tiles sit **N–S adjacent, perpendicular to flow**,
and both tiles carry the main E↔W flow. Which entity (`Default` vs `…Mirrored`)
is the *input* tile vs the *secondary-output* tile, per `R`, still needs pinning
before the lifter can place their ports. That is the last piece to lift the
diagonal extractor.
