# penpath CLI Reference (MVP)

**Command**: `penpath`  
**Config File**: `~/.config/penpath/config.toml`  
**Project File**: `project.yaml` (or `.penpath.yaml`)

---

## Global Options

| Option | Short | Env Var | Description |
|--------|-------|---------|-------------|
| `--config PATH` | `-c` | — | Config file path (default: `~/.config/penpath/config.toml` or `$XDG_CONFIG_HOME/penpath/config.toml`) |
| `--project PATH` | `-p` | — | Project file (YAML) — loads all settings |
| `--verbose` | `-v` | — | Increase log level (repeat: `-vv`, `-vvv`) |
| `--quiet` | `-q` | — | Suppress non-error output |
| `--no-color` | — | `NO_COLOR` | Disable colored output (standard) |
| `--version` | `-V` | — | Show version and exit |
| `--help` | `-h` | — | Show help for command |

**Priority**: CLI flags > Project file > Config file > Defaults

**Note**: Config file location follows XDG spec: `$XDG_CONFIG_HOME/penpath/config.toml` or `~/.config/penpath/config.toml`.

---

## Commands

### `penpath convert` — Photo → SVG (Main Command)

Convert a raster image to a plottable SVG using the Sketch Lines algorithm.

```bash
penpath convert [OPTIONS] INPUT_PATH [OUTPUT_PATH]
```

#### Arguments

| Argument | Description |
|----------|-------------|
| `INPUT_PATH` | Path to input image (PNG, JPG, TIFF, BMP) |
| `OUTPUT_PATH` | Output SVG path (optional; default: `<input>_plot.svg` beside input). Equivalent to `-o/--output`. |

#### Image Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--filter NAME` | `-f` | — | Apply filter (repeatable: `-f grayscale -f threshold`). See **Filters** below. |
| `--no-auto-orient` | — | `false` | Disable EXIF auto-orientation |

#### Drawing Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--pfm NAME` | — | `sketch_lines` | Path-finding module (only `sketch_lines` in MVP) |
| `--pfm-setting KEY=VALUE` | `-s` | — | PFM-specific setting (repeatable). See **PFM Settings** below. |
| `--pen NAME` | — | `default` | Pen preset name or `width,color,type` (e.g., `0.3,#000000,fineliner`) |
| `--palette NAME\|LIST` | — | — | Built-in palette name (`stabilo_88`) or inline `name=width,#hex;name2=width,#hex`. Mutually exclusive with `--pen`. |
| `--paper NAME` | — | `a4` | Paper preset name or `WIDTHxHEIGHT[,margins]` (e.g., `a4`, `210x297,10`) |

A palette's order is the drawing order. Until colour separation lands, the
whole image is still drawn with **one** pen — the first pen of the palette — so
the SVG keeps a single pen layer. For `stabilo_88` that is
`stabilo_88_yellow` (`#F7E300`); the remaining pens are listed by
`penpath info palettes` and will get their layers when colour separation is
implemented. `--pen` and `--palette` cannot be combined: penpath reports a
usage error instead of choosing one silently.

#### Output Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--output PATH` | `-o` | — | Output SVG path, equivalent to the `OUTPUT_PATH` argument |
| `--no-vpype` | — | `false` | Skip vpype optimization (use direct SVG export) |
| `--vpype-path PATH` | — | `vpype` | Path to vpype executable |
| `--layer-per-pen` / `--single-layer` | — | `layer-per-pen` | SVG layer structure |

`OUTPUT_PATH` and `-o/--output` are two ways to name the same output file. Give
either one; if both are given and the paths differ, `penpath convert` exits 2 with
a usage error naming both paths. Giving the same path both ways is fine. An output
given on the command line also overrides `output.path` in a `--project` file.

#### Optional: vpype

The `vpype` extra is installed with:

```bash
pip install "penpath[vpype]"
```

Installing plain `pip install vpype` works too. Without vpype, the run prints
`vpype not found, falling back to direct SVG export (install it with: pip install "penpath[vpype]")`
and exports the SVG directly: penpath's own simplify → merge → sort still runs,
but vpype's extra `linemerge → linesimplify → reloop → linesort` pass and its SVG
writer do not. Use `--no-vpype` to skip vpype on purpose.

The SVG records where the source image was placed on the page, in millimetres:

```xml
<metadata>
  <penpath:image-placement x="10.0000" y="20.0000" width="190.0000" height="160.0000"/>
</metadata>
```

`penpath.core.svg_parse.get_image_placement(svg_path, image_size_px)` reads this
rectangle; for SVGs without it, the image is fitted to the page keeping its
aspect ratio and centered. `penpath.core.svg_parse.parse_svg_strokes(svg_path)`
returns the plotted strokes as `PenStroke` objects in millimetres.

#### PFM Settings (Sketch Lines)

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `line_density` | float | `0.75` | Ink-density multiplier in the luminance-progress stop rule (0.01–10) |
| `min_length` | float | `2.0` | Minimum segment length in image pixels |
| `max_length` | float | `40.0` | Maximum segment length in image pixels |
| `angle_range` | tuple | `-72,-52` | Random start-angle band in degrees (−360–360) |
| `search_angle_step` | float | `18.0` | Degrees between candidate rays (20 angle tests) |
| `shading_enabled` | bool | `false` | Search two opposite directions late in the run |
| `squiggle_enabled` | bool | `false` | Add perpendicular noise (a penpath addition; the reference has none) |
| `erase_enabled` | bool | `true` | Lighten drawn pixels so strokes move on |
| `erase_min` | float | `35.0` | Brightness added to a dark pixel |
| `erase_max` | float | `80.0` | Brightness added to a bright pixel |
| `tone` | float | `0.5` | Cubic/linear blend of the erase amount and brush radius |
| `erase_radius_min` | float | `1.0` | Erase brush radius in pixels for a dark pixel |
| `erase_radius_max` | float | `1.0` | Erase brush radius in pixels for a bright pixel |
| `squiggle_max_deviation` | float | `0.25` | How far a squiggle may stray from the starting darkness |
| `squiggle_min_length` | int | `50` | Segments before the darkness rule may end a squiggle |
| `squiggle_max_length` | int | `500` | Hard limit on segments in one squiggle |
| `shading_threshold` | float | `0.5` | Progress at which shading starts |
| `max_strokes` | int | `auto` | Hard stroke cap (needed when erasing is off) |
| `seed` | int | `random` | Random seed for reproducibility |

**Example**: `-s line_density=0.5 -s shading_enabled=true -s seed=42`

**Breaking change**: `line_density` now scales the luminance-progress stop
rule instead of counting lines per millimetre, and `min_length` and
`max_length` are image pixels rather than millimetres.

#### Filters (Applied in Order)

| Name | Params | Description |
|------|--------|-------------|
| `grayscale` | `method=luminance\|lightness\|average\|red\|green\|blue` | Convert to single channel |
| `threshold` | `level=0-255`, `dither=none\|floyd_steinberg\|ordered` | Binarize image (2 levels) |
| `posterize` | `levels=2-256`, `dither=none\|floyd_steinberg\|ordered` | Reduce to N tonal levels |
| `gaussian_blur` | `radius=float>=0` | Gaussian blur |
| `box_blur` | `radius=int>=0` | Box blur |
| `contrast` | `factor=float>=0` | Contrast adjustment (1.0 = no change) |
| `brightness` | `factor=float>=0` | Brightness adjustment (1.0 = no change) |
| `gamma` | `gamma=float>0` | Gamma correction (1.0 = no change) |
| `invert` | (none) | Invert colors (negative) |

**Example**: `-f grayscale -f "threshold:level=128,dither=floyd_steinberg" -f "gaussian_blur:radius=1.5"`

#### Examples

```bash
# Basic usage
penpath convert photo.jpg

# Name the output as a positional argument (or with -o: penpath convert photo.jpg -o plot.svg)
penpath convert photo.jpg plot.svg

# With custom settings
penpath convert photo.jpg -o plot.svg -f grayscale -f "posterize:levels=4" -s line_density=0.5 -s seed=42

# Using project file
penpath convert --project my_project.yaml

# Override project settings
penpath convert --project my_project.yaml --pen "0.5,#FF0000" -o red_plot.svg

# Use a built-in palette or an inline ordered list
penpath convert photo.jpg --palette stabilo_88
penpath convert photo.jpg --palette "red=0.4,#E4002B;blue=0.4,#1B4C9E"

# Skip vpype (faster, less optimized)
penpath convert photo.jpg --no-vpype
```

---

### `penpath preview` — Simulate a plot as an image

Render an SVG's pen strokes with the core plot simulator, so you can check how
the finished plot will look before plotting.

```bash
penpath preview DRAWING_SVG -o OUTPUT [OPTIONS]
```

#### Arguments

| Argument | Description |
|----------|-------------|
| `DRAWING_SVG` | SVG to preview (penpath SVG or plain stroke SVG) |

#### Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--output PATH` | `-o` | — | Output image path (required, PNG) |
| `--dpi FLOAT` | — | `10.0` | Resolution in **pixels per millimetre** |
| `--paper-color COLOR` | — | `#FFFFFF` | Paper background colour (hex or named CSS colour) |
| `--layer LABEL` | — | all | Only preview this pen layer (layer label or id) |

The page size is read from the SVG (`width`/`height` or `viewBox`); SVGs without
one fall back to A4. All progress messages go to stderr, so stdout stays clean.

#### Examples

```bash
penpath preview plot.svg -o preview.png
penpath preview plot.svg -o preview.png --dpi 20 --paper-color "#F5F5DC"
penpath preview plot.svg -o fine.png --layer "Pen: fine"
```

---

### `penpath evaluate` — Score likeness and machine cost

Simulate the SVG at the chosen resolution, crop it to the recorded image
placement, and compare it with the original using SSIM. Also reports machine
cost (drawing length, pen-up travel, pen lifts, short segments and stroke
count) per pen layer and in total.

```bash
penpath evaluate IMAGE DRAWING_SVG [OPTIONS]
```

#### Arguments

| Argument | Description |
|----------|-------------|
| `IMAGE` | Original source image |
| `DRAWING_SVG` | SVG to evaluate (penpath SVG or plain stroke SVG) |

#### Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--json` | — | `false` | Print only JSON on stdout (for scripts/agents) |
| `--dpi FLOAT` | — | `96/25.4` | Resolution in **pixels per millimetre**, shared by simulation and likeness |
| `--paper-color COLOR` | — | `#FFFFFF` | Paper background colour |
| `--layer LABEL` | — | all | Only evaluate this pen layer |

For SVGs without placement metadata, the image is fitted to the page keeping
its aspect ratio and centered — the same fallback used by
`penpath.core.svg_parse.get_image_placement`.

With `--json`, stdout contains only a single object (safe to pipe to `jq`):

```json
{
  "likeness": 0.82,
  "machine_cost": {
    "per_layer": {"#000000": {"drawing_length_mm": 123.4}},
    "total": {"drawing_length_mm": 123.4}
  }
}
```

#### Examples

```bash
penpath evaluate photo.jpg plot.svg
penpath evaluate photo.jpg plot.svg --json | jq '.likeness'
penpath evaluate photo.jpg plot.svg --dpi 5 --layer "Pen: fine"
```

---

### `penpath info` — Show Presets & Capabilities

```bash
penpath info [SUBCOMMAND] [OPTIONS]
```

#### Subcommands

| Subcommand | Description |
|------------|-------------|
| `pens` | List built-in pen presets |
| `palettes` | List built-in palettes and their pens in drawing order |
| `papers` | List built-in paper presets |
| `pfms` | List available PFMs (MVP: only `sketch_lines`) |
| `filters` | List available filters with parameters |
| `image PATH` | Show image info (size, mode, EXIF, DPI) |
| `config` | Show resolved config (config + project + defaults) |

#### Options

| Option | Description |
|--------|-------------|
| `--format json\|yaml\|table` | Output format (default: table) |

#### Examples

```bash
penpath info pens
penpath info palettes
penpath info palettes --format json
penpath info papers --format yaml
penpath info pfms
penpath info filters
penpath info image photo.jpg
penpath info config --project project.yaml
```

---

### `penpath config` — Manage User Config

```bash
penpath config [SUBCOMMAND] [OPTIONS]
```

#### Subcommands

| Subcommand | Description |
|------------|-------------|
| `show` | Print current config (merged with defaults) |
| `edit` | Open config in `$EDITOR` (creates if missing) |
| `init` | Create default config file |
| `get KEY` | Get single config value |
| `set KEY VALUE` | Set config value |
| `reset` | Delete config file (revert to defaults) |

#### Config Keys

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `default_paper` | string | `a4` | Paper preset for `convert` |
| `default_pen` | string | `fine` | Pen preset for `convert` |
| `output_dir` | string | `.` | Default output directory |

#### Examples

```bash
penpath config show
penpath config init
penpath config set default_paper a3
penpath config get default_pen
penpath config edit
```

---

## Project File Format (`project.yaml`)

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
    min_length: 0.5
    max_length: 10.0
    angle_range: 180
    shading: true
    squiggles: false
    erasing: false
    seed: null

pen:
  name: fine
  # or inline:
  # width_mm: 0.3
  # color: "#000000"

# Instead of `pen`, use a built-in palette:
# palette: stabilo_88
# Or an explicit ordered list of pens (drawing order):
# pens:
#   - name: my_red
#     width_mm: 0.4
#     color: "#E4002B"
#   - name: my_blue
#     width_mm: 0.4
#     color: "#1B4C9E"

paper:
  name: a4
  # or inline:
  # size_mm: [210, 297]
  # margin_mm: 10

output:
  path: "plot.svg"
  vpype: true
  layer_per_pen: true
```

`pen:`, `palette:` and `pens:` are mutually exclusive: a project file that
sets more than one of them fails to load with a clear error. A file with only
`pen:` keeps its old meaning (one pen). `save_yaml` writes a built-in palette
back as `palette:` and an explicit list back as `pens:`.

**Minimal Example**:
```yaml
version: 1
input:
  path: "photo.jpg"
output:
  path: "plot.svg"
```

---

## Config File Format (`~/.config/penpath/config.toml`)

```toml
# penpath user config
default_paper = "a4"
default_pen = "fine"
output_dir = "."

# Custom pens (optional)
[pens.my_pen]
width = 0.4
color = "#000000"
opacity = 1.0

# Custom papers (optional)
[papers.my_paper]
width = 300.0
height = 200.0
margin = 15.0
```

---

## Pen Presets (Built-in)

| Name | Width (mm) | Color | Description |
|------|------------|-------|-------------|
| `fine` | 0.3 | Black | General purpose (default) |
| `medium` | 0.5 | Black | Standard lines |
| `bold` | 0.8 | Black | Bold strokes |
| `extra_fine` | 0.2 | Black | Very fine detail |
| `brush` | 1.0 | Black | Broad brush strokes |
| `red_fine` | 0.3 | Red | Red accent |
| `blue_fine` | 0.3 | Blue | Blue accent |
| `green_fine` | 0.3 | Green | Green accent |

**Inline Format**: `WIDTH,COLOR` — e.g., `0.4,#FF6600` (color defaults to black if omitted)

---

## Palette Presets (Built-in)

| Name | Pens | Width | Drawing order |
|------|------|-------|---------------|
| `stabilo_88` | 12 Stabilo Point 88 colours | 0.4 mm | light → dark, as listed by `penpath info palettes` |

---

## Paper Presets (Built-in)

| Name | Size (mm) | Margins (mm) |
|------|-----------|--------------|
| `a4` | 210 × 297 | 10 all sides |
| `a3` | 297 × 420 | 10 all sides |
| `a5` | 148 × 210 | 10 all sides |
| `letter` | 215.9 × 279.4 | 10 all sides |
| `legal` | 215.9 × 355.6 | 10 all sides |
| `tabloid` | 279.4 × 431.8 | 10 all sides |
| `square_200` | 200 × 200 | 10 all sides |
| `square_300` | 300 × 300 | 10 all sides |

**Inline Format**: `WIDTHxHEIGHT[,MARGIN]` — e.g., `210x297,10` or `300x200,15`

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Runtime error (file not found, vpype failed, image load failed) |
| 2 | Usage error (invalid args, missing required, bad filter param) |
| 3 | Validation error (project file invalid, config invalid, PFM settings invalid) |

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `NO_COLOR` | Disable colors (standard, respected by `rich`) |
| `EDITOR` | Editor for `config edit` command |
| `XDG_CONFIG_HOME` | Base directory for config (default: `~/.config`) |

---

## Examples: Common Workflows

### Quick Start
```bash
penpath convert photo.jpg
# → photo_plot.svg
```
### Reproducible Art Print

```bash
penpath convert photo.jpg -o art.svg \
  -f grayscale -f "posterize:levels=6,dither=floyd_steinberg" \
  -s line_density=0.4 -s shading=true -s seed=12345 \
  --pen fine --paper a4
```
### Project-Based Workflow

```bash
# Create project file from the minimal example (copy and edit)
cat > portrait.yaml << 'EOF'
version: 1
input:
  path: "photo.jpg"
output:
  path: "plot.svg"
EOF
# Edit portrait.yaml to taste
penpath convert --project portrait.yaml
# Iterate: edit YAML, re-run
```

### Batch Processing (Shell)
```bash
for img in photos/*.jpg; do
  penpath convert "$img" -o "output/$(basename "$img" .jpg).svg" --project batch.yaml
done
```
### Debug Pipeline Stages

```bash
# See what filters do
penpath info image photo.jpg
penpath convert photo.jpg -f grayscale -f posterize --no-vpype -o debug.svg
# Inspect debug.svg in browser/Inkscape
```