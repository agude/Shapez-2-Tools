# Open questions for review

Accumulated during autonomous work; each answer unblocks a specific next step.
Most-blocking first.

## 1. Export a clean cutter blueprint  *(do this first — blocks the lift)*
The cutter's structure is confirmed (1×2, 1-in/2-out), but its **file encoding**
is not: is a 1×2 cutter two entities (`Default` + `Mirrored`) = one cutter, one
entity with an implied 2nd cell, or two separate single-tile cutters? Each
predicts different ports, and the dense `12 to 24 Cutter` plus the screenshots
can't disambiguate. **Please export a single cutter (or the four fed-from-south
ones) to a `.spz2bp` and paste it.** Decoding a clean example settles the encoding
in one pass and unblocks the whole machine-port model.

## 2. Pass-by mechanic  *(pins the connection rule)*
In tight routing a belt can run *past* a machine without connecting. When a
belt's output points at a machine's **solid (non-port) side**, does the game
always route it as a turn going elsewhere (so a belt never truly dead-ends into a
wall), or can a belt physically butt against a machine face? This sets how strict
the lifter's "a port must agree with the belt leg" rule should be.

## 3. Shape quadrant convention  *(simulator correctness)*
The shape model reads quadrants clockwise from top-right — `(NE, SE, SW, NW)` —
with the west half = `SW + NW`. The diagonal-swap test passes with this, but does
it match the game's shape-code order (e.g. `RuCuSuWu`)? A wrong labeling would
still pass the structural tests yet mislabel parts.

## 4. Stacker  *(to extend simulator + lifter)*
Footprint, port layout, and semantics — how does a stacker combine two input
shapes (stack layers)? Needed before the simulator/lifter can handle stacking.

## 5. Non-1×1/1×4 platform ports  *(calibration)*
The swapper (2×2) and painter (2×4) blueprints leave unmatched legs at their
ports. Are belt ports on 2×2 / 2×4 platforms placed or oriented differently from
the 1×1 / 1×4 convention I calibrated?

## 6. Rotation direction sanity check
The interpreter maps `RotatorOneQuad` → clockwise, `RotatorOneQuadCCW` →
counter-clockwise. Tests pass, but confirm that matches in-game (the building
icons should settle it).

---

## Resolved (for the record)
- Shapes have absolute world orientation; cut/swap/half-destroy act on absolute
  west/east halves; only rotators re-orient.
- Cutter 1-in/2-out, swapper 2-in/2-out, half-destroyer 1-in/1-out; in ports on
  the left (W), out on the right (E).
- The cutter's apparent "2 inputs" was belts routing *past* output-only tiles.
- Swappers swap west halves including empty parts (the diagonal trick).
