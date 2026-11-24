# Aquila pen-plotter G-code scripts (reference, not part of the package)

Working scripts from sergio's `pen_holder_aquila` project (Voxelab Aquila with a
pen holder, Marlin, G-code from SD card). Read-only reference for a future
`penpath gcode --profile`; the machine-specific values are the constants at the
top of `aquila_plot.py`.

- `aquila_plot.py`: G-code writer (`Plot`: start / pen / stroke / end). Pen
  coordinates in mm, pen-to-nozzle offset applied, reach checked, pen lands and
  lifts while moving (no ink dots), `M0` pause for every pen change. Proven on
  the real machine (test 4, 2026-11-18). Never use `M25` to pause on this firmware.
- `svg_plot.py IN.svg OUT.gcode [PREVIEW.png] [--at X,Y] [--layers 1,2] [--margin N]`:
  layered SVG -> G-code, one pen per top-level layer group (file order). Needs vpype
  and matplotlib. It parses top-level groups itself because
  `vpype.read_multilayer_svg` takes the layer id from the digits in the label.
- `image_plot.py`: one-colour image -> outline + hatch fill -> G-code.
- `test_plot.py`, `colour_test.py`, `moon_craters.py`, `make_test_svgs.py`: test and demo plots / inputs.
