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

### Optional: `vpype`

For best results (line merging, sorting, optimization), install the `vpype`
extra, which pulls in [vpype](https://vpype.readthedocs.io/):

```bash
pip install "penpath[vpype]"
```

Installing vpype directly with `pip install vpype` works too; the `test` extra
also pulls it in. Without vpype, penpath prints
`vpype not found, falling back to direct SVG export (install it with: pip install "penpath[vpype]")`
and writes the SVG directly. Penpath's own simplify → merge → sort still runs,
but vpype's extra `linemerge → linesimplify → reloop → linesort` pass and its SVG
writer do not, so the output is less optimized. Use `--no-vpype` to skip vpype
on purpose.

---

## Core Concepts

| Concept | Description |
|---------|-------------|
| **PFM** (Pen Follower Module) | Algorithm that converts pixels to lines. MVP includes `sketch_lines` (ported from DrawingBotV3). |
| **Filters** | Image preprocessing: grayscale, threshold, blur, contrast, etc. Applied in order before PFM. |
| **Geometry optimization** | Simplify (RDP), merge (collinear join), sort (greedy NN + 2-opt) — runs automatically. |
| **vpype** | External CLI for final SVG optimization (linemerge, linesimplify, reloop, linesort). |
| **Project file** | YAML file capturing all settings for reproducible, iterative workflows. |

---

## Commands Overview

| Command | Purpose |
|---------|---------|
| `penpath convert` | Photo → SVG (main command) |
| `penpath preview` | Simulate an SVG and save a preview image |
| `penpath evaluate` | Score an SVG's likeness to the original image and its machine cost |
| `penpath info` | List presets, show image details, inspect config |
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
penpath convert photo.jpg -f grayscale -f "threshold:levels=4,dither=floyd_steinberg"

# Adjust PFM (Sketch Lines) settings
penpath convert photo.jpg -s line_density=0.5 -s shading=true -s seed=42

# Choose pen and paper
penpath convert photo.jpg --pen fineliner_03 --paper a4

# Skip vpype (faster, less optimized)
penpath convert photo.jpg --no-vpype

# Preview the simulated plot as an image
penpath preview plot.svg -o preview.png --dpi 10

# Evaluate likeness and machine cost (JSON for scripts)
penpath evaluate photo.jpg plot.svg
penpath evaluate photo.jpg plot.svg --json | jq '.likeness'
```

---

## Project Files: Reproducible Workflows

Save your entire pipeline in a YAML file for version control and iteration.

```bash
# Create a project file manually (see minimal example below)
# Edit my_project.yaml to taste
penpath convert --project my_project.yaml
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
  - threshold:
      levels: 4
      dither: floyd_steinberg
  - blur:
      radius: 1.0
      type: gaussian

pfm:
  name: sketch_lines
  settings:
    line_density: 0.3
    min_length: 0.5
    max_length: 10.0
    angle_range: 180
    shading: true
    squiggles: false
    erasing: false
    seed: null

pen:
  name: default
  # or inline:
  # width_mm: 0.3
  # color: "#000000"
  # type: fineliner

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
  -f grayscale -f "threshold:levels=6,dither=floyd_steinberg" \
  -s line_density=0.4 -s shading=true -s seed=12345 \
  --pen fineliner_03 --paper a4
```

### Project-Based Iteration

```bash
# Create project file manually from the minimal example
# Edit portrait.yaml: tweak filters, PFM settings, pen, paper
penpath convert --project portrait.yaml
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

### Reproducible Results

Use `--seed` for deterministic output:

```bash
penpath convert photo.jpg -s seed=42 -o plot1.svg
penpath convert photo.jpg -s seed=42 -o plot2.svg
# plot1.svg and plot2.svg are byte-for-byte identical
```

---

## Built-in Presets

### Pens

| Name | Width | Color | Type |
|------|-------|-------|------|
| `default` | 0.3mm | Black | fineliner |
| `fineliner_03` | 0.3mm | Black | fineliner |
| `fineliner_05` | 0.5mm | Black | fineliner |
| `rollerball_05` | 0.5mm | Black | rollerball |
| `rollerball_07` | 0.7mm | Black | rollerball |
| `fountain_f` | 0.4mm | Black | fountain |
| `fountain_m` | 0.6mm | Black | fountain |
| `marker_10` | 1.0mm | Black | marker |
| `red_03` | 0.3mm | Red | fineliner |
| `blue_03` | 0.3mm | Blue | fineliner |

**Inline format:** `WIDTH,COLOR,TYPE` — e.g., `0.4,#FF6600,fountain`

### Palettes

The built-in `stabilo_88` palette has twelve 0.4 mm Stabilo Point 88 pens in
light → dark drawing order:

```bash
penpath convert photo.jpg --palette stabilo_88
penpath info palettes
```

A project file can use `palette: stabilo_88` or an explicit ordered `pens:` list
instead of `pen:`. Palette order is drawing order. Until colour separation
lands, the whole image is drawn with the first palette pen, so the SVG keeps a
single pen layer.

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
default_pen = "default"
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
penpath config set default_paper a3
```

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
│  PFM: Sketch Lines (DrawingBotV3)   │
│  • Random-angle line search         │
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
│  → linesort → write (per-pen layers)│
└─────────────────────────────────────┘
    │
    ▼
Output SVG (layers per pen, viewBox from paper)
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