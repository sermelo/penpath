# The Aquila plot workflow

This is the operator path from an image to a finished plot on sergio's Voxelab
Aquila (Marlin, pen holder on the toolhead, G-code from SD card). Penpath writes
the G-code itself with `penpath gcode --profile aquila`; the working scripts in
`reference/aquila_gcode/` on the read-only branch `origin/aquila-gcode-reference`
are provenance, not a second implementation and not part of this package.

## Before you start

- Install penpath (`pip install penpath`) and, for the SVG export used by
  `convert`, the optional vpype (`pip install "penpath[vpype]"`). From a source
  checkout, `uv sync --extra vpype` and use `python -m penpath`.
- A saved CR Touch mesh is required: the start block runs `M420 S1 Z0` (no fade).
- The paper must fit the pen's usable area: X 10..187.3 mm, Y 10..181.4 mm (bed
  220 × 220 mm, pen offset (-22.7, -28.6) mm, and a 10 mm safety margin inside
  the drawable edges). The largest page that fits is about 177 × 171 mm; a
  170 × 170 mm page is used below and in `examples/aquila/`. Its page origin is
  pen (17.3, 10.0), with the page's lower-right corner at (187.3, 10.0).

## The path, command by command

1. **Image → SVG.** Run `penpath convert` on the source image. The page size
   stays in the SVG and is what `gcode` uses, so pick one that fits the Aquila:

   ```sh
   penpath convert photo.jpg -o card.svg --paper 170x170,10 -s seed=42
   ```

   `--paper 170x170,10` means a 170 × 170 mm page with a 10 mm page margin. The
   `aquila` profile keeps a further 10 mm safety margin from the pen's reach, so
   the usable area is X 10..187.3 and Y 10..181.4 mm and the largest page that
   fits unchanged is about 177 × 171 mm. A larger page is fitted with a warning
   by default; `--no-fit` rejects it. The seed makes the drawing reproducible.
   With a palette (`--palette stabilo_88`) each used pen becomes one SVG layer.

2. **Review the SVG.** Look at it in Inkscape or render it with penpath:

   ```sh
   penpath preview card.svg -o card.svg.png
   ```

   Check that the ink is inside the page, that the layer order is the order you
   want to plot, and that the pens and colours are right. **Only plot the SVG you
   have reviewed**: `penpath gcode` reads this file as it stands and does not
   re-import or re-optimise it.

3. **SVG → G-code.** Use the built-in profile; there are no machine numbers to
   pass on the command line:

   ```sh
   penpath gcode card.svg --profile aquila -o card.gcode
   ```

    The stderr summary reports layers, drawing length, pen-up travel, pen lifts
    and an estimated time. A point outside the usable area is an error naming its
    coordinates and the usable limits; no partial G-code is written. With
    `--dry-run` the G-code goes to stdout and every message goes to stderr.

4. **Review the G-code as a plot.** This uses penpath's G-code interpreter, which
   reads `G0`/`G1`, applies the same page origin and pen offset as the emitter,
   and clips the ramped landing at touch height:

   ```sh
   penpath preview card.gcode -o card.gcode.png
   ```

   `card.gcode.png` should match `card.svg.png` (the 170 mm example differs in
   about 0.01% of pixels, at stroke ends). Check the start warning, one `M0` pause per
   pen layer, and the end block with `grep -nE 'M0|M117|M2|G28'` before copying
   the file to the SD card.

5. **Plot.** Put the `.gcode` on the SD card, insert it and start the print from
   the printer menu. Follow the checklist below at each pause. The file ends
   with no `M2`: the head parks at X0 Y220 Z80 and the steppers are disabled, so
   wait for the last beep and take the paper off once the head has parked.

## Operator checklist

Taken from `reference/aquila_gcode/README.md` and `aquila_plot.py`
(`Plot.start`, `Plot.pen`, `Plot.end`), proven on the machine in test 4 on
2026-11-18:

- [ ] The paper is held down, against the usable area's **right and front
      edges** (pen-space origin at the front-left corner of the bed).
- [ ] The pen is **OUT of the clamp** before `G28`. The start block beeps and
      waits 10 seconds (`M117 Pen OUT? Homing in 10s`, `G4 S10`) so you can abort.
      **Never home with a pen in** — the CR Touch triggers with the nozzle about
      0.85 mm above the bed.
- [ ] The saved mesh is loaded with no fade (`M420 S1 Z0`).
- [ ] At each `M0` pause the head is at the touch spot **(190, 12)** mm in pen
      space, at Z 10.0: put the pen in, slide it down onto the paper (a scrap of
      plastic under the tip avoids a dot; pull it out once the pen has lifted
      and started moving), tighten the clamp, and press the knob. Sometimes two
      presses are needed. The first pen is set here too, not just colour changes.
      **The spot sits inside the 10 mm safety margin on purpose**: paper and
      magnets must not cover it. It is not a drawing point and is not checked
      against the usable area.
- [ ] **Never use `M25` on this firmware**; the pen-change pauses are `M0`.
- [ ] The end sequence has **no `M2`**: Z 80 → X0 Y220 → two beeps → `M84 S120`,
      `M84` → `M117 Plot done`. The head parks at **X0 Y220 Z80**, left of the
      paper with the bed forward, so the sheet is free to take out.

## Small end-to-end example

[`examples/aquila/`](../examples/aquila/) contains a 128 × 128 PNG and a
Makefile that runs all four commands above:

```sh
cd examples/aquila
make PENPATH="python -m penpath"
```

It writes `circle.svg`, `circle.gcode` and both preview PNGs; `make clean`
removes them. The whole example takes about 7 s on this runner.

## Equivalence with the reference script

Run on 2026-11-26 with vpype 1.15 and the read-only scripts from
`origin/aquila-gcode-reference` (extracted to a temporary directory, never into
penpath's source tree). The input was
`tests/fixtures/svg/gcode/aquila_two_layers.svg`: a 190 × 190 mm SVG with two
pen layers in document order. Sergio's script ran without a safety margin, so
the regression test generates penpath's side with
`with_margin_mm(load_profile("aquila"), 0.0)`; the shipped profile keeps its
10 mm margin and would fit or reject that 190 mm page. The same check was run on
the larger, generated `examples/aquila/circle.svg` to cover a many-stroke
drawing.

The circle counts below are from that historical run on the earlier 190 × 190 mm
example page; the current example uses 170 × 170 mm. They assume that SVG was
produced by the `convert` in `examples/aquila/Makefile` with vpype on `PATH`:
vpype optimises the strokes and
yields 843 XY points and Z 9.0 ×793. If vpype is not on `PATH`, `convert` warns
`vpype not found, falling back to direct SVG export` and writes two extra
points; the same comparison on that SVG gives 845 XY points and Z 9.0 ×795 in
both outputs. Reference and penpath agree in either case — only the input SVG
differs — so check which path `convert` took before comparing these numbers.

```sh
python /tmp/aquila-ref/svg_plot.py tests/fixtures/svg/gcode/aquila_two_layers.svg /tmp/reference.gcode
```

`sergio`'s output is kept verbatim in
`tests/fixtures/golden/gcode/aquila_reference_two_layers.gcode`; the regression
test `tests/integration/test_aquila_equivalence.py` compares it on every run
with penpath's output from the same SVG and the margin-0 profile copy.

| Check | Reference `svg_plot.py` | `penpath gcode --profile aquila` |
|---|---|---|
| Start block (`G21` … `G1 Z12.5 F600`) | identical | identical after the 3-decimal formatting below |
| Pen change (first and second pen) | `; ---- pen N: name ----`, lift, travel to (190, 12), touch, beeps, `M0`, messages, lift | same lines in the same order, plus `; pen change` and `; layer N/2 pen=…` comments |
| End block (Z80 → X0 Y220 → beeps → `M84 S120`, `M84` → done) | identical, no `M2` | identical after formatting, no `M2` |
| Page placement | page at pen (7.3, 0.0); right/front edges of the drawable area | same origin from `reachable_corner` with the margin-0 override |
| Coordinates | 16 XY points (two-layer SVG); 843 on the generated circle SVG | same 16 / 843 points; largest difference 0.001 mm |
| Z sequence | per stroke: 12.5 → 10.5 → 10.0 → 9.0 ×n → 10.0 → 10.5 → 12.5; end 80 | same sequence, with one extra 12.5 lift before the first stroke |
| Feeds | F600 (Z), F6000 (travel), F1500 (draw) | same three values; fewer repeated clauses (see below) |

On the two-layer SVG the Z counts are 9.0 ×5, 10.0 ×6, 10.5 ×4, 12.5 ×7 and
80.0 ×1 for the reference; penpath has the same counts with 12.5 ×8. On the
generated circle SVG: 9.0 ×793, 10.0 ×25, 10.5 ×24, 12.5 ×15, 80.0 ×1 versus
12.5 ×16. The extra lift is the emitter's explicit pen-up before the first
stroke; it is a state change, not a different landing.

### Intentional differences

1. **Header comment.** The reference writes
   `; <input path>: N layer(s), page W x H mm at (X, Y) (pen_holder_aquila/scripts/…)`.
   Penpath writes `; penpath gcode profile=aquila page=170.000x170.000
   page_origin=17.300,10.000 usable_x=10.000..187.300 usable_y=10.000..181.400
   z_up=12.500 z_touch=10.000 z_down=9.000`: no source path (a file can move),
   and the page placement, usable area and Z heights that `penpath preview` needs
   to invert the mapping.
2. **Layer comments.** Penpath adds `; pen change` before every used layer and
   `; layer N/M pen=<name>` after it. The reference only has the
   `; ---- pen N: name ----` line. Comments do not affect the machine.
3. **Structural pen-up moves.** The reference assumes the pen is already up
   after each pen change and uses `G1 … F6000` for travel, `G1 Z… F600` for Z;
   penpath's state machine emits `G0 Z12.500` before the first stroke and uses
   `G0` for travel and Z moves, with `F6000`/`F600` on those `G0` moves and the
   drawing `F1500` on the first `G1` of each stroke only. So the reference
   repeats F1500 on every drawing move (829 times on the circle SVG) while
   penpath sets it 12 times, once per stroke. Travel and Z feedrates are
   otherwise identical (F6000 appears 5 times in both outputs on the two-layer
   SVG); the remaining spelling difference is `G0` where the reference writes
   `G1`, which Marlin treats the same. The XY path and Z heights are the same.
4. **Page placement.** With the margin-0 override used for this check, both put
   a 190 mm page at pen (7.3, 0.0). The reference derives this from vpype's pixel
   sizes (96 px/in) and its default `at`; penpath reads millimetres from the
   reviewed SVG's `width`/`height` and places the page's bottom-right corner at
   the usable area's front-right corner (`reachable_corner`). With the shipped
   10 mm margin a 170 mm page goes at pen (17.3, 10.0). An SVG without a
   millimetre page size is an error in penpath instead of being guessed from
   pixels.
5. **Number formatting.** The reference mixes Python's short float spelling
   (`Z12.5`, `Z80.0`, `X0.0`) with three decimals on interpolated points;
   penpath always uses three decimals (`Z12.500`, `Z80.000`, `X0.000`). Values
   are equal, not rounded differently.
6. **Stroke order.** The reference greedily orders strokes from the touch spot
   and may reverse each stroke; penpath uses its shared nearest-neighbour
   travel sort with a fixed tie-break. The set of coordinates is identical; the
   order and direction of some strokes differ. Drawing order between pen layers
   is document order in both.
7. **Reach checks.** The reference checks every point against the page rectangle
   (and its optional `--margin`) before applying the pen offset; penpath checks
   pen-space drawing points, including the ramped lead-in and lead-out, against
   the usable area (drawable area minus `bed.margin_mm`, 10 mm in the shipped
   profile). The pen-change touch spot is not a drawing point and is not checked.
   A page that does not fit fails in both, with different messages.

None of these differences changes the machine values: bed, offset, Z heights,
ramp, feeds, touch spot, start, pen-change and end blocks all come from the
built-in `aquila` profile, whose numbers were copied from the reference script
(LUC-65). The 10 mm safety margin is penpath's own addition; the equivalence
check removes it so the historical comparison stays meaningful.

## First real plot with a penpath-generated `.gcode`

**Not confirmed yet (2026-11-26).** This is operator evidence, not a CI result,
and must be filled in by someone who plots it. The reference's test 4 on
2026-11-18 used sergio's `svg_plot.py`, not penpath's G-code, so it does not
count. To record it, fill in: date, source image and SVG, exact penpath commands
(including `--profile aquila`), paper and pen, and what was observed at each
`M0` and at the end. The request for this evidence is on LUC-95.
