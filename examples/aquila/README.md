# Aquila end-to-end example

A 128x128 PNG, a 190x190 mm page that fits the Aquila's drawable area, and the
commands that take it all the way to G-code. See `docs/AQUILA.md` for the
operator checklist before you plot.

From a clean checkout, with penpath installed (and `vpype` for the SVG export):

```sh
cd examples/aquila
make PENPATH="python -m penpath"
```

`make` writes `circle.svg`, `circle.gcode` and two preview PNGs. The equivalent
commands, if you prefer to run them one at a time:

```sh
penpath convert circle.png -o circle.svg --paper 190x190,10 -s seed=42 --quiet
penpath preview circle.svg -o circle.svg.png
penpath gcode circle.svg --profile aquila -o circle.gcode
penpath preview circle.gcode -o circle.gcode.png
```

The seed makes the SVG reproducible. `make clean` removes the generated files.
