# Open questions for review

Accumulated during autonomous work; each answer unblocks a specific next step.
Most-blocking first.

## 1. Cutter input tile  *(blocks finishing the lift)*
A cutter is `CutterDefault` + `CutterDefaultMirrored` — two tiles (1×2). One is
the **input tile** (in + out), the other **output-only**. Which entity is which,
and how are the two arranged relative to the building's rotation `R`? That lets
me model the cutter's ports and lift the diagonal extractor.
*(Shortcut: for a `Default` cutter at its default rotation, which side is the
single input on?)*

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
