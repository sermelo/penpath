# penpath

Free software that takes you from an image to a finished pen plot: simple by default, customizable when needed. Use it as a Python library, from the command line, or through AI agents.

[![Python versions](https://img.shields.io/pypi/pyversions/penpath.svg)](https://pypi.org/project/penpath/)
[![License](https://img.shields.io/pypi/l/penpath.svg)](LICENSE)
[![Build status](https://github.com/sermelo/penpath/workflows/CI/badge.svg)](https://github.com/sermelo/penpath/actions)

---

## Quickstart

```bash
# Install
pip install penpath

# Convert a photo to SVG (uses default settings)
penpath convert photo.jpg
# → photo_plot.svg

# View the result in a browser or send to your plotter
```

That's it! You now have a plottable SVG optimized for pen plotting.

---

## Installation

### From PyPI (recommended)

```bash
pip install "penpath[vpype]"
```

The `vpype` extra is optional: `pip install penpath` installs the core with no
vpype dependency.

### From source (development)

```bash
git clone https://github.com/sermelo/penpath.git
cd penpath
uv sync --extra dev  # or: pip install -e ".[dev]"
```

Run the whole nightly workload locally — dependency sync, a timed reference
photo conversion and the full unit + integration suite — with:

```bash
bash scripts/nightly.sh
```

See [docs/TESTING.md](docs/TESTING.md#run-the-nightly-workload-locally) for the
prerequisites and the exact steps it runs.

### Optional: `vpype`

For best results (line merging, sorting, optimization), install the `vpype`
extra, which pulls in [vpype](https://vpype.readthedocs.io/):

```bash
pip install "penpath[vpype]"
```

Installing vpype directly with `pip install vpype` works too; the `test` extra
also pulls it in. Without vpype, penpath prints
`vpype not found, falling back to direct SVG export (install it with: pip install "penpath[vpype]")`.
Penpath's own simplify → merge → sort still runs, but vpype's extra
`linemerge → linesimplify → reloop → linesort` pass does not, so the output is
less optimized. Use `--no-vpype` to skip vpype on purpose. Either way penpath
writes the final SVG: vpype contributes geometry only.

---

## Core Concepts

| Concept | Description |
|---------|-------------|
| **PFM** (Pen Follower Module) | Algorithm that converts pixels to lines. Built in: `sketch_lines` (hatching), `sketch_squares` (grid hatching), both ported from DrawingBotV3, and `contour` (scikit-image + Shapely outlines). |
| **Palette** | An ordered set of pens. Each pixel is drawn by its nearest palette colour; each used pen becomes one SVG layer. |
| **Filters** | Image preprocessing: grayscale, threshold, blur, contrast, etc. Applied in order before PFM. |
| **Geometry optimization** | Simplify (RDP), merge (collinear join), sort (greedy NN + 2-opt) — runs automatically. |
| **vpype** | External CLI for final SVG optimization (linemerge, linesimplify, reloop, linesort). |
| **Project file** | YAML file capturing all settings for reproducible, iterative workflows. |

---

## Commands Overview

| Command | Purpose |
|---------|---------|
| `penpath convert` | Photo → SVG (main command) |
| `penpath preview` | Simulate an SVG or G-code file and save a preview image |
| `penpath evaluate` | Score an SVG's likeness to the original image and its machine cost |
| `penpath gcode` | Turn a reviewed SVG into machine G-code with a machine profile |
| `penpath info` | List presets and machine profiles, show image details, inspect config |
| `penpath config` | Manage user configuration (~/.config/penpath/config.toml) |

See [docs/CLI.md](docs/CLI.md) for complete reference.

---

## Basic Usage

```bash
# Simple conversion with defaults
penpath convert input.jpg

# Custom output path (positional argument or -o/--output; give only one)
penpath convert input.jpg output.svg
penpath convert input.jpg -o output.svg

# Apply image filters before drawing
penpath convert photo.jpg -f grayscale -f "posterize:levels=4,dither=floyd_steinberg"

# Tonal range is normalized automatically; images already spanning at least
# 7/8 of 0-255 are left alone. Keep the original tones with:
penpath convert photo.jpg --no-auto-equalize

# Palette mode masks pale paper as no ink by default; tune or override it:
penpath convert photo.jpg --palette stabilo_88 --background-threshold 6
penpath convert photo.jpg --palette stabilo_88 --no-background
penpath convert photo.jpg --pen fine --background

# The default local paper field follows lighting gradients and shadows; the
# global method uses one detected colour (with a lower cut-off it leaves a pale
# gradient as ink, which is the regression the local field fixes):
penpath convert photo.jpg --palette stabilo_88 --background-method local
penpath convert photo.jpg --palette stabilo_88 --background-method global --background-threshold 5

# Muted colour photos can be boosted before the palette split (1.0 is off):
penpath convert photo.jpg --palette stabilo_88 --palette-adapt
penpath convert photo.jpg --palette stabilo_88 --saturation 2.0

# Saved looks: sketch (the default), directional hatch, or clean outlines
penpath convert photo.jpg --style sketch -o sketch.svg
penpath convert photo.jpg --style hatch -o hatch.svg
penpath convert photo.jpg --style outline -o outline.svg

# Adjust PFM (Sketch Lines) settings; -s wins over a look's value
penpath convert photo.jpg -s line_density=0.5 -s max_fill=90 -s seed=42

# Draw with the grid-hatched Sketch Squares PFM, or one of its presets
penpath convert photo.jpg --pfm sketch_squares -s seed=42
penpath convert photo.jpg --pfm sketch_squares:crosshatch-grid -s seed=42

# Opt into the full tonal range (solid black areas included)
penpath convert photo.jpg -s max_fill=100 -o full-range.svg

# Choose pen and paper
penpath convert photo.jpg --pen fine --paper a4

# Skip vpype (faster, less optimized)
penpath convert photo.jpg --no-vpype

# Preview the simulated plot as an image
penpath preview plot.svg -o preview.png --dpi 10
# Also show pen-up travel as thin light lines (default stays ink-only)
penpath preview plot.svg -o travel_preview.png --travel

# Evaluate likeness, machine cost and ink coverage (JSON for scripts)
penpath evaluate photo.jpg plot.svg
penpath evaluate photo.jpg plot.svg --json | jq '.likeness'

# Turn the reviewed SVG into G-code for a machine profile (stdout stays empty)
penpath gcode plot.svg --profile generic -o plot.gcode
penpath gcode plot.svg --profile generic --dry-run > plot.gcode
# A multi-pen SVG becomes one G-code layer per used pen, in layer order, with
# one pen-change block before each layer that follows the first
penpath convert photo.jpg -o palette_plot.svg --palette stabilo_88 -s seed=42
penpath gcode palette_plot.svg --profile generic -o palette_plot.gcode
# The built-in aquila profile drives sergio's Voxelab Aquila: it parks the page
# against the usable corner, ramps each landing and pauses to set every pen.
# Its 10 mm safety margin leaves about 177 x 171 mm of usable area, so lay the
# card out on a 170x170 mm page:
penpath convert photo.jpg -o card.svg --paper 170x170 -s seed=42
penpath gcode card.svg --profile aquila -o card.gcode
# A page slightly past the usable area is fitted by default, with a warning on
# stderr; add --no-fit to keep the strict error instead
penpath gcode card.svg --profile aquila
# Place the page at a named spot or an exact pen-space lower-left corner; with
# neither, the profile decides (Aquila: front-right, generic/ramped: origin)
penpath gcode card.svg --profile aquila --place center -o centred.gcode
penpath gcode card.svg --profile aquila --at 20,20 -o corner.gcode

# Check the G-code without a machine: the PNG shows the bed, the page and the
# same ink as the SVG preview
penpath preview plot.gcode -o gcode_preview.png
```

### Working resolution

Large photos are downscaled before drawing, so they take tens of seconds rather
than hours: a 12 MP photo on 190x190 mm paper with a 0.4 mm pen converted in
11.49 s on our VPS, and the reference `photo.jpg` with the default A4/0.3 mm
settings took 56 s. These are measured times; see `docs/TESTING.md` for the
commands and machine. Penpath uses one pixel per pen width on the longest
side of the paper (`paper_longest_side_mm / pen_width_mm`, clamped to
256–1024 px) and never enlarges the source. Pixel-valued Sketch Lines settings
(`min_length`, `max_length`, `sample_step`) are interpreted in working-image
pixels and are
not scaled. The chosen size is printed on stderr and recorded in the SVG
metadata; the image rectangle on the page is unchanged. Override it with
`--max-resolution` or keep all source pixels with `--no-downscale`:

```bash
penpath convert photo.jpg --paper 190x190 --pen 0.4
# Working resolution: 475x358 px (source 4080x3072 px, scale 0.116)

penpath convert photo.jpg --max-resolution 800
penpath convert photo.jpg --no-downscale
penpath info image photo.jpg  # shows the resolution penpath would plan
```

### Progress and quiet mode

`convert` keeps stdout empty and reports progress on stderr. On a terminal it
shows a live bar; redirected to a log it writes one flushed line per stage, so
the log fills in while the command runs:

```bash
penpath convert photo.jpg 2>convert.log
# [1/6] Loading image... done in 0.1 s
# [2/6] Downscaling image... done in 1.4 s
# ...
# [6/6] Exporting SVG... done in 0.1 s
# Done in 20.9 s
# ✓ SVG saved to: photo_plot.svg

penpath convert photo.jpg --quiet  # no stderr output; errors still shown
```

---

## Project Files: Reproducible Workflows

Save your entire pipeline in a YAML file for version control and iteration.

```bash
# Create a project file manually (see minimal example below)
# Edit my_project.yaml to taste
penpath convert photo.jpg --project my_project.yaml
```

**Example `project.yaml`:**

```yaml
# penpath project file v1
version: 1

input:
  path: "photo.jpg"
  auto_orient: true

filters:
  - grayscale:
      method: luminance
  - posterize:
      levels: 4
      dither: floyd_steinberg
  - gaussian_blur:
      radius: 1.0

pfm:
  name: sketch_lines
  settings:
    line_density: 0.3
    max_fill: 80.0
    min_length: 2.0
    max_length: 40.0
    angle_range: [0.0, 360.0]
    shading_enabled: true
    squiggle_enabled: false
    erase_enabled: false
    seed: null

pen:
  name: fine
  # or inline:
  # width_mm: 0.3
  # color: "#000000"
  # pen_type: fineliner

paper:
  name: a4
  # or inline:
  # size_mm: [210, 297]
  # margins_mm: [10, 10, 10, 10]
  # background: "#FFFFFF"

output:
  path: "plot.svg"
  vpype: true
  layer_per_pen: true
```

**Minimal example:**

```yaml
version: 1
input:
  path: "photo.jpg"
output:
  path: "plot.svg"
```

---

## Common Workflows

### Quick Art Print

```bash
penpath convert photo.jpg -o art.svg \
  -f grayscale -f "posterize:levels=6,dither=floyd_steinberg" \
  -s line_density=0.4 -s shading_enabled=true -s seed=12345 \
  --pen "0.4,#000000,fineliner" --paper a4
```

### Project-Based Iteration

```bash
# Create project file manually from the minimal example
# Edit portrait.yaml: tweak filters, PFM settings, pen, paper
penpath convert photo.jpg --project portrait.yaml
# Re-run after edits — same results every time
```

### Batch Processing (Shell)

```bash
for img in photos/*.jpg; do
  penpath convert "$img" -o "output/$(basename "$img" .jpg).svg" --project batch.yaml
done
```

### Debug Pipeline Stages

```bash
# Inspect image properties
penpath info image photo.jpg

# See filter effects without vpype optimization
penpath convert photo.jpg -f grayscale -f threshold --no-vpype -o debug.svg
# Open debug.svg in browser/Inkscape to inspect lines
```

### Check the Plot Before Printing

```bash
penpath convert photo.jpg -o plot.svg
# Render a preview at 10 px/mm on cream paper
penpath preview plot.svg -o preview.png --dpi 10 --paper-color "#FFFDD0"
# Check likeness against the original (SSIM + machine cost)
penpath evaluate photo.jpg plot.svg
# Machine-readable output for scripts and agents
penpath evaluate photo.jpg plot.svg --json | jq '{likeness, total: .machine_cost.total}'
```

The machine-cost table includes a `Pen` column with the Inkscape layer name
(falling back to the stroke hex) and a `Coverage (%)` column; the JSON output
includes `pen` and `ink_coverage_pct` per layer, and `ink_coverage_pct` in
`total`. A layer covering more than 50% of the page warns on stderr (naming
the layer and suggesting
`--background-threshold` / `--saturation`); `--coverage-warn 0` silences it.
Warnings never change the exit code or the JSON on stdout.

### Worked Example: Photo → SVG → Preview

The shipped defaults are calibrated against five reference images. Here is the
whole path on one of them, from a repository checkout:

```bash
# Convert with the shipped defaults; the seed makes the result reproducible
penpath convert tests/fixtures/images/reference/photo.jpg -o photo_plot.svg -s seed=42

# Render the simulated plot as an image
penpath preview photo_plot.svg -o photo_preview.png --dpi 10

# Score likeness (SSIM 0.5099 with these defaults) and machine cost
penpath evaluate tests/fixtures/images/reference/photo.jpg photo_plot.svg
```

This is what the simulated plot looks like; the 600 px greyscale preview is
committed at [docs/images/luc-47/photo_after.png](docs/images/luc-47/photo_after.png):

![Simulated plot of the reference photo](docs/images/luc-47/photo_after.png)

Before the LUC-53 algorithm fix the same photo produced a much smaller, sparser
plot (SSIM 0.4917, only 41% of the placement width covered). Compare the
[before preview](docs/images/luc-47/photo_before.png) and the full
[before/after measurements](docs/TESTING.md#final-shipped-defaults-measurement-luc-54-2026-11-25).

### Reproducible Results

Use `-s seed=N` for deterministic output:

```bash
penpath convert photo.jpg -s seed=42 -o plot1.svg
penpath convert photo.jpg -s seed=42 -o plot2.svg
# plot1.svg and plot2.svg are byte-for-byte identical
```

---

## Built-in Presets

### Pens

| Name | Width (mm) | Colour |
|------|------------|--------|
| `fine` (default) | 0.3 | black |
| `medium` | 0.5 | black |
| `bold` | 0.8 | black |
| `extra_fine` | 0.2 | black |
| `brush` | 1.0 | black |
| `red_fine` | 0.3 | red |
| `blue_fine` | 0.3 | blue |
| `green_fine` | 0.3 | green |

**Inline format:** `WIDTH[,COLOR[,TYPE]]` — width in millimetres, colour as
`#RRGGBB` or a named CSS colour, type one of `ballpoint`, `fineliner`,
`fountain`, `brush`, `marker`, `rollerball`, `gel` (default `rollerball`):

```bash
penpath convert photo.jpg --pen 0.4
penpath convert photo.jpg --pen "0.4,#FF6600"
penpath convert photo.jpg --pen "0.4,#000000,fineliner"
```

### PFMs and Contour presets

`--pfm` selects `sketch_lines` (the default hatching algorithm) or `contour`,
which traces clean outlines with scikit-image and Shapely. Each PFM accepts its
own `-s KEY=VALUE` settings; `penpath info pfms` lists every PFM, its defaults
and its presets.

| Preset | PFM | Character |
|--------|-----|-----------|
| `contour_portrait` | `contour` | Four threshold levels for internal detail; tuned on a face. |
| `contour_silhouette` | `contour` | One threshold and a larger minimum speck size for a few bold outlines. |

Simulated plot previews on the free Santa portrait:
[contour_portrait](docs/images/luc-139/contour_portrait.png) ·
[contour_silhouette](docs/images/luc-139/contour_silhouette.png). The
[Contour gate](docs/TESTING.md#contour-readability-and-plot-cost-gate-luc-146-2026-11-27)
records the measured readability and plot cost; acceptance is by looking at the
previews, not by SSIM alone.

```bash
penpath convert photo.jpg --pfm contour -o outlines.svg
penpath convert photo.jpg --pfm contour_portrait -o portrait_contour.svg
```

### Palettes: one SVG layer per pen

Each pixel is assigned to the palette pen whose colour is nearest in CIE Lab,
and that pen receives a full-size greyscale image holding the luminance of its
own pixels and white elsewhere. Paper-coloured pixels are masked to white
before separation, so the lightest pen cannot scribble over the page; use
`--no-background` if you want the old behaviour. Filters, the selected PFM and geometry
optimization then run once per pen, so lines from different pens are never
sorted together. Every pen that draws becomes one Inkscape layer, named after
the pen, in palette order:

```bash
# Photo -> SVG with one layer per used pen (the Christmas-card workflow)
penpath convert photo.jpg -o card.svg --palette stabilo_88 -s seed=42

# See the pens, colours and drawing order
penpath info palettes
penpath info palettes --format json

# See which pens the colour separation picks and each pen's pixel share
penpath info palette-match photo.jpg
penpath info palette-match photo.jpg --palette stabilo_88 --format json
penpath info palette-match photo.jpg --palette "red=0.4,#FF0000;blue=0.4,#0000FF"

# Check the result before plotting
penpath preview card.svg -o card.png --dpi 10
penpath evaluate photo.jpg card.svg
```

`penpath info palette-match` reports one row per palette pen (including unused
pens) and an unassigned share. It measures the raw separation on the loaded
image: no filters, background masking or saturation boost, and pixels in regions
smaller than 8 px count as unassigned. Percentages are of all image pixels, not
of the finished drawing.

A project file can use `palette: stabilo_88` or an explicit ordered `pens:` list
instead of `pen:`. Palette order is drawing order and the layer order. An
unused pen gets no layer, so a twelve-pen palette may yield fewer than twelve
layers. Without `--palette`, the single default pen draws the whole image and
produces one layer, exactly as before. `--pen` and `--palette` are mutually
exclusive.

The built-in `stabilo_88` palette, in drawing order (all 0.4 mm):

| # | Layer label | Colour |
|--:|-------------|--------|
| 1 | `stabilo_88_yellow` | `#F7E300` |
| 2 | `stabilo_88_cyan` | `#00B5B0` |
| 3 | `stabilo_88_light_blue` | `#8CCFE8` |
| 4 | `stabilo_88_blue` | `#1B4C9E` |
| 5 | `stabilo_88_light_green` | `#A9D18E` |
| 6 | `stabilo_88_purple` | `#6C3B9E` |
| 7 | `stabilo_88_pink` | `#F2A0BE` |
| 8 | `stabilo_88_brown` | `#7A4B23` |
| 9 | `stabilo_88_orange` | `#F4741F` |
| 10 | `stabilo_88_black` | `#000000` |
| 11 | `stabilo_88_red` | `#E4002B` |
| 12 | `stabilo_88_green` | `#00963E` |

### SVG layout and `vpype read`

Every SVG penpath writes uses millimetres: for A4 the root is
`width="210mm" height="297mm" viewBox="0 0 210 297"`, and each used pen gets one
Inkscape layer with `id="layerN"` (N in pen order) and the pen name as
`inkscape:label`. Strokes have `fill="none"`, a hex `stroke` and a millimetre
`stroke-width`; the background is a plain `<rect>`, not a layer.

Do not feed a penpath SVG back to `vpype read`. vpype takes the layer number
from the digits in `inkscape:label`, so `stabilo_88_red` and
`stabilo_88_green` both read as layer 88 and merge. Read the file with an XML
parser and use the `<g>` groups with their numeric `layerN` ids instead; the
G-code step does this.

### Papers

| Name | Size (mm) | Margins (mm) |
|------|-----------|--------------|
| `a4` | 210 × 297 | 10 all sides |
| `a4_landscape` | 297 × 210 | 10 all sides |
| `a3` | 297 × 420 | 15 all sides |
| `a3_landscape` | 420 × 297 | 15 all sides |
| `letter` | 216 × 279 | 10 all sides |
| `letter_landscape` | 279 × 216 | 10 all sides |
| `square_200` | 200 × 200 | 10 all sides |
| `postcard` | 148 × 105 | 5 all sides |

**Inline format:** `WIDTHxHEIGHT[,MARGINS]` — e.g., `210x297,10` or `300x200,15,10,15,10` (T,R,B,L)

### Filters (applied in order)

| Name | Parameters | Description |
|------|------------|-------------|
| `grayscale` | `method=luminance\|lightness\|average\|red\|green\|blue` | Convert to single channel |
| `threshold` | `level=0-255`, `dither=none\|floyd_steinberg\|ordered` | Binarize (2 levels) |
| `posterize` | `levels=2-256`, `dither=none\|floyd_steinberg\|ordered` | Reduce to N tonal levels |
| `gaussian_blur` | `radius=float>=0` | Gaussian blur |
| `box_blur` | `radius=int>=0` | Box blur |
| `contrast` | `factor=float>=0` | Contrast adjustment (1.0 = no change) |
| `brightness` | `factor=float>=0` | Brightness adjustment (1.0 = no change) |
| `gamma` | `gamma=float>0` | Gamma correction (1.0 = no change) |
| `invert` | (none) | Invert colors (negative) |

---

## Configuration

User config at `~/.config/penpath/config.toml`:

```toml
# penpath user config
default_paper = "a4"
default_pen = "fine"
default_pfm = "sketch_lines"
vpype_path = "vpype"
output_dir = "."
log_level = "INFO"
```

Manage with:

```bash
penpath config show      # View current config
penpath config init      # Create default config
penpath config edit      # Open in $EDITOR
```

### Machine profiles

Machine profiles hold bed, feed and pen values for a plotter. Two built-ins
ship: `generic` (a plain Z-lifted plotter) and `aquila` (the Voxelab Aquila with
a pen offset, a ramped landing and a touch-spot pen change; its machine numbers
come from sergio's `aquila-gcode-reference` script, plus penpath's own 10 mm
safety margin). The Aquila profile pauses for each pen with `M0`; never use
`M25` to pause on this firmware. List the built-ins
and your own machines with `penpath info profiles`, which shows each machine's
safety margin; `penpath gcode --margin MM` overrides that margin for one run.
The file format and an example are in
[docs/CLI.md](docs/CLI.md#machine-profile-format).

For the full image → SVG → reviewed preview → G-code → SD card → plot operator
path on the Aquila, including the machine checklist and the equivalence check
against sergio's reference script, see [docs/AQUILA.md](docs/AQUILA.md). A small
runnable version is in [`examples/aquila/`](examples/aquila/).

---

## How It Works

```
Input Image
    │
    ▼
┌─────────────────────────────────────┐
│  Filter Pipeline (user-defined)     │
│  grayscale → threshold → blur → ... │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  PFM: Sketch Lines / Squares (DBV3) │
│  • Random-angle or grid-angle search│
│  • Darkest-pixel sampling           │
│  • Tonal shading branch             │
│  • Squiggle/erase variation         │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  Geometry Optimization              │
│  1. Simplify (RDP, tolerance)       │
│  2. Merge (linemerge + collinear)   │
│  3. Sort (greedy NN + 2-opt)        │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  vpype Pipeline (optional)          │
│  linemerge → linesimplify → reloop  │
│  → linesort (geometry only)         │
└─────────────────────────────────────┘
     │
     ▼
Output SVG (mm, one layer per used pen, written by penpath)

```

---

## Requirements

- Python ≥ 3.14
- `vpype` (optional, for best output) — `pip install "penpath[vpype]"`
- System dependencies for `shapely` (GEOS) — usually via wheels

---

## License

MIT — see [LICENSE](LICENSE).

---

## Links

- **Documentation**: [docs/CLI.md](docs/CLI.md)
- **Technical Plan**: [docs/PLAN.md](docs/PLAN.md)
- **Conventions**: [docs/CONVENTIONS.md](docs/CONVENTIONS.md)
- **Testing**: [docs/TESTING.md](docs/TESTING.md)
- **Issues**: [GitHub Issues](https://github.com/sermelo/penpath/issues)
- **Changelog**: [CHANGELOG.md](CHANGELOG.md) (if exists)