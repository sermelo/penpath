#!/usr/bin/env bash
# Regenerate every PNG used by the README Examples gallery.
# Run from anywhere: bash examples/gallery/generate.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
if [ -x .venv/bin/penpath ]; then PATH="$PWD/.venv/bin:$PATH"; export PATH; fi
mkdir -p build/gallery docs/images/luc-88

# One example per PFM: original -> SVG plot -> simulated G-code.
penpath convert tests/fixtures/images/reference/santa.jpg -o build/gallery/sketch_lines.svg --paper a4 --max-resolution 800 -s seed=42 -q --pfm sketch_lines
penpath preview build/gallery/sketch_lines.svg -o docs/images/luc-88/sketch_lines_plot.png --dpi 2.86
penpath gcode build/gallery/sketch_lines.svg --profile generic -o build/gallery/sketch_lines.gcode
penpath preview build/gallery/sketch_lines.gcode -o docs/images/luc-88/sketch_lines_gcode.png --dpi 2.86

penpath convert tests/fixtures/images/reference/santa.jpg -o build/gallery/sketch_squares.svg --paper a4 --max-resolution 800 -s seed=42 -q --pfm sketch_squares:fine
penpath preview build/gallery/sketch_squares.svg -o docs/images/luc-88/sketch_squares_plot.png --dpi 2.86
penpath gcode build/gallery/sketch_squares.svg --profile generic -o build/gallery/sketch_squares.gcode
penpath preview build/gallery/sketch_squares.gcode -o docs/images/luc-88/sketch_squares_gcode.png --dpi 2.86

penpath convert tests/fixtures/images/reference/santa.jpg -o build/gallery/contour.svg --paper a4 --max-resolution 800 -s seed=42 -q --pfm contour_portrait
penpath preview build/gallery/contour.svg -o docs/images/luc-88/contour_plot.png --dpi 2.86
penpath gcode build/gallery/contour.svg --profile generic -o build/gallery/contour.gcode
penpath preview build/gallery/contour.gcode -o docs/images/luc-88/contour_gcode.png --dpi 2.86

penpath convert tests/fixtures/images/reference/santa.jpg -o build/gallery/stipple.svg --paper a4 --max-resolution 800 -s seed=42 -q --pfm stipple_default
penpath preview build/gallery/stipple.svg -o docs/images/luc-88/stipple_plot.png --dpi 2.86
penpath gcode build/gallery/stipple.svg --profile generic -o build/gallery/stipple.gcode
penpath preview build/gallery/stipple.gcode -o docs/images/luc-88/stipple_gcode.png --dpi 2.86

penpath convert tests/fixtures/images/reference/santa.jpg -o build/gallery/spiral_sawtooth.svg --paper a4 --max-resolution 800 -s seed=42 -q --pfm spiral_sawtooth:fine
penpath preview build/gallery/spiral_sawtooth.svg -o docs/images/luc-88/spiral_sawtooth_plot.png --dpi 2.86
penpath gcode build/gallery/spiral_sawtooth.svg --profile generic -o build/gallery/spiral_sawtooth.gcode
penpath preview build/gallery/spiral_sawtooth.gcode -o docs/images/luc-88/spiral_sawtooth_gcode.png --dpi 2.86

# Pen width: identical settings, only the stroke width changes.
penpath convert tests/fixtures/images/reference/photo.jpg -o build/gallery/pen_fine.svg --paper a4 --max-resolution 800 -s seed=42 -q --pen fine
penpath preview build/gallery/pen_fine.svg -o docs/images/luc-88/pen_fine_plot.png --dpi 3.2
penpath convert tests/fixtures/images/reference/photo.jpg -o build/gallery/pen_medium.svg --paper a4 --max-resolution 800 -s seed=42 -q --pen medium
penpath preview build/gallery/pen_medium.svg -o docs/images/luc-88/pen_medium_plot.png --dpi 3.2
penpath convert tests/fixtures/images/reference/photo.jpg -o build/gallery/pen_bold.svg --paper a4 --max-resolution 800 -s seed=42 -q --pen bold
penpath preview build/gallery/pen_bold.svg -o docs/images/luc-88/pen_bold_plot.png --dpi 3.2
penpath gcode build/gallery/pen_bold.svg --profile generic -o build/gallery/pen_bold.gcode
penpath preview build/gallery/pen_bold.gcode -o docs/images/luc-88/pen_bold_gcode.png --dpi 2.86

# Colour: one inline pen, then the multi-pen Stabilo 88 palette.
penpath convert tests/fixtures/images/reference/photo.jpg -o build/gallery/pen_colour.svg --paper a4 --max-resolution 800 -s seed=42 -q --pen "0.4,#E4002B"
penpath preview build/gallery/pen_colour.svg -o docs/images/luc-88/pen_colour_plot.png --dpi 2.86
penpath convert tests/fixtures/images/colour/christmas_tree.jpg -o build/gallery/palette.svg --paper a4 --max-resolution 800 -s seed=42 -q --palette stabilo_88
penpath preview build/gallery/palette.svg -o docs/images/luc-88/palette_plot.png --dpi 2.86
penpath gcode build/gallery/palette.svg --profile generic -o build/gallery/palette.gcode
penpath preview build/gallery/palette.gcode -o docs/images/luc-88/palette_gcode.png --dpi 2.86

# Saved looks (styles).
penpath convert tests/fixtures/images/reference/photo.jpg -o build/gallery/style_sketch.svg --paper a4 --max-resolution 800 -s seed=42 -q --style sketch
penpath preview build/gallery/style_sketch.svg -o docs/images/luc-88/style_sketch_plot.png --dpi 2.86
penpath convert tests/fixtures/images/reference/photo.jpg -o build/gallery/style_hatch.svg --paper a4 --max-resolution 800 -s seed=42 -q --style hatch
penpath preview build/gallery/style_hatch.svg -o docs/images/luc-88/style_hatch_plot.png --dpi 2.86
penpath convert tests/fixtures/images/reference/photo.jpg -o build/gallery/style_outline.svg --paper a4 --max-resolution 800 -s seed=42 -q --style outline
penpath preview build/gallery/style_outline.svg -o docs/images/luc-88/style_outline_plot.png --dpi 2.86
