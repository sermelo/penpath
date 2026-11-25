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

**Note**: Config file location follows XDG spec: `$XDG_CONFIG_HOME/penpath/config.toml` or `~/.config/penpath/config.toml`. `--quiet` is currently implemented on `penpath convert`; see its Reporting Options below.

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
| `--max-resolution PX` | — | derived | Longest side of the working image in pixels. Overrides the derived value (no clamp) and never enlarges. |
| `--no-downscale` | — | `false` | Keep the source pixels; do not downscale before drawing |

#### Drawing Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--pfm NAME` | — | `sketch_lines` | PFM algorithm or built-in preset (see **PFM Presets** below) |
| `--pfm-setting KEY=VALUE` | `-s` | — | PFM-specific setting (repeatable). See **PFM Settings** below. |
| `--pen NAME` | — | `default` | Pen preset name or `width,color,type` (e.g., `0.3,#000000,fineliner`) |
| `--palette NAME\|LIST` | — | — | Built-in palette name (`stabilo_88`) or inline `name=width,#hex;name2=width,#hex`. Mutually exclusive with `--pen`. |
| `--paper NAME` | — | `a4` | Paper preset name or `WIDTHxHEIGHT[,margins]` (e.g., `a4`, `210x297,10`) |

#### Working Resolution

Large photos are downscaled before drawing so a 12 MP phone photo finishes in
seconds instead of hours. The working resolution is the longest side of the
image the drawing algorithm works on:

```
working_px = paper_longest_side_mm / pen_width_mm
```

The derived value is clamped to **256–1024 px**. The source is never enlarged
and its aspect ratio is kept: with a 190x190 mm paper and a 0.4 mm pen, a
4080x3072 photo is drawn at 475x358 px. The pixel-valued Sketch Lines settings
(`min_length`, `max_length`, `sample_step`) are interpreted in working-image
pixels and are not scaled.

`--max-resolution PX` replaces the derived value without clamping (and still
never enlarges); `--no-downscale` draws at the source resolution. The chosen
resolution is reported to stderr before drawing (and is silenced by `--quiet`):

```
Working resolution: 475x358 px (source 4080x3072 px, scale 0.116)
```

`penpath info image` shows the resolution penpath would plan for an image,
using the paper and pen from the config defaults.

`--palette NAME|LIST` splits the loaded colour image before filtering: each
pixel goes to the pen whose colour is nearest in CIE Lab space, and that pen
receives a full-size greyscale image holding the luminance of its own pixels
and white elsewhere. The filters and the drawing algorithm then run once per
pen, and geometry is simplified, merged and sorted **within that pen only**.

The palette's order is the drawing order and the order of the SVG layers. Each
pen that produced strokes becomes one Inkscape layer named `layerN`, where `N`
counts only the used pens from 1: an unused pen gets no layer and does not
shift the numbering. The built-in `stabilo_88` palette is listed light → dark
by `penpath info palettes`; an inline list is used exactly as given. `--pen`
and `--palette` cannot be combined: penpath reports a usage error instead of
choosing one silently. Without `--palette`, the default single pen draws the
whole image and produces a single layer, exactly as before.

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

#### Reporting Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--quiet` | `-q` | `false` | Suppress progress, the working-resolution line and the final summary on stderr. Errors are still printed. |

#### Progress output

All `convert` messages go to stderr; stdout stays empty in every case, so the
command is safe in a pipeline. On a terminal, a live `rich` progress bar shows a
spinner, the current stage, a percentage and the elapsed time; the completed bar
and the final summary stay on screen. When stderr is redirected to a file or a
pipe, each finished stage becomes one plain line, flushed immediately so the log
fills in while the command is still running:

```
[1/6] Loading image... done in 0.1 s
[2/6] Downscaling image... done in 1.4 s
[3/6] Applying filters... done in 0.0 s
[4/6] Generating lines (PFM)... done in 19.1 s
[5/6] Optimizing geometry... done in 0.2 s
[6/6] Exporting SVG... done in 0.1 s
Done in 20.9 s
✓ SVG saved to: plot.svg
```

The downscale stage is reported only when the image is actually downscaled, so
the counter ends at 5 when it is skipped. The working-resolution line is written
to stderr too. `--quiet` removes all of this, including the "SVG saved to" line;
errors are still reported on stderr and the SVG is still written.

#### Optional: vpype

The `vpype` extra is installed with:

```bash
pip install "penpath[vpype]"
```

Installing plain `pip install vpype` works too. Without vpype, the run prints
`vpype not found, falling back to direct SVG export (install it with: pip install "penpath[vpype]")`.
Penpath's own simplify → merge → sort still runs, but vpype's extra
`linemerge → linesimplify → reloop → linesort` pass does not. Use `--no-vpype`
to skip vpype on purpose. vpype contributes geometry only; penpath writes the
final SVG on both paths. Each used pen gets an Inkscape layer with `id="layerN"`
and the pen name as `inkscape:label`, and the page uses millimetres throughout.
Do not feed the result back to `vpype read`: vpype reads its layer number from
the digits in the label, so `stabilo_88_red` and `stabilo_88_green` would merge.

The SVG records where the source image was placed on the page, in millimetres:

```xml
<metadata>
  <penpath:image-placement x="10.0000" y="20.0000" width="190.0000" height="160.0000"
      image-width="475" image-height="358" source-width="4080" source-height="3072"/>
</metadata>
```

`image-width`/`image-height` are the working size the drawing was made at;
`source-width`/`source-height` are the source image size. The placement
rectangle itself is always derived from the source image, so it does not move
when downscaling.

`penpath.core.svg_parse.get_image_placement(svg_path, image_size_px)` reads this
rectangle and ignores the size attributes; for SVGs without it, the image is
fitted to the page keeping its aspect ratio and centered. `penpath.core.svg_parse.parse_svg_strokes(svg_path)`
returns the plotted strokes as `PenStroke` objects in millimetres.

#### PFM Settings (Sketch Lines)

Every field of `SketchLinesSettings` is accepted by `-s KEY=VALUE`; the flag
forwards the key to the algorithm unchanged. Booleans accept `true`, `1`,
`yes` or `on` (and their opposites for false). `angle_range` takes two
comma-separated degrees. Invalid keys, values or out-of-range numbers exit 2
with a message naming the setting.

| Key | Type | Range | Default | Effect |
|-----|------|-------|---------|--------|
| `line_density` | float | 0.01–10.0 | `0.75` | Ink-density multiplier in the luminance-progress stop rule; higher draws more ink. |
| `max_fill` | float | 1–100 % | `80.0` | Maximum ink coverage. Tones darker than `255 * (1 - max_fill / 100)` are treated as black; `100` keeps the full range, and the lower default keeps solid black areas plottable. |
| `min_length` | float | 1–1000 px | `2.0` | Shortest segment the ray search may end at (pixels). Must be ≤ `max_length`. |
| `max_length` | float | 1–5000 px | `40.0` | Longest segment the ray search may take (pixels). Must be ≥ `min_length`. |
| `angle_range` | tuple | −360–360° each | `-72,-52` | Band of degrees for each random ray's start angle; the reference uses −72..−52. Min ≤ max. |
| `search_angle_step` | float | 0.1–90° | `18.0` | Degrees between candidate rays (360/step tests); smaller searches more angles and is slower. |
| `sample_step` | float | 1–100 px | `10.0` | Side of the tiles used to find the next darkest pixel; smaller follows detail more closely. |
| `shading_enabled` | bool | — | `false` | After `shading_threshold`, test only two opposite directions. |
| `shading_threshold` | float | 0–1 | `0.5` | Fraction of luminance progress at which shading starts. |
| `squiggle_enabled` | bool | — | `false` | Add perpendicular noise to segments (a penpath addition; the reference has none). |
| `squiggle_max_deviation` | float | 0–10 | `0.25` | How far a squiggle may wander above the starting darkness, as a fraction of 253.5. |
| `squiggle_min_length` | int | 1–100000 | `50` | Segments before the darkness rule may end a squiggle. Must be ≤ `squiggle_max_length`. |
| `squiggle_max_length` | int | 1–100000 | `500` | Hard upper bound on segments in one squiggle. |
| `erase_enabled` | bool | — | `true` | Lighten drawn pixels so later strokes move elsewhere. Off gives a dense, dark scribble. |
| `erase_min` | float | 0–255 | `35.0` | Brightness added to a very dark pixel by one stroke. Must be ≤ `erase_max`. |
| `erase_max` | float | 0–255 | `80.0` | Brightness added to a very bright pixel by one stroke. Must be ≥ `erase_min`. |
| `tone` | float | 0–1 | `0.5` | Cubic/linear blend of the erase amount and brush radius (0 = linear). |
| `erase_radius_min` | float | 0–50 px | `1.0` | Erase-brush radius for a very dark pixel. Must be ≤ `erase_radius_max`. |
| `erase_radius_max` | float | 0–50 px | `1.0` | Erase-brush radius for a very bright pixel. |
| `max_strokes` | int | ≥1 or `auto` | `auto` | Hard stroke cap; derived from image size and density unless set explicitly. |
| `seed` | int | any | random | Fix the random seed for byte-identical reruns. |

The cross-field limits above are validated, so `min_length=100 -s
max_length=50` fails with a clear error rather than drawing nothing.

**Example**: `-s line_density=0.5 -s max_fill=90 -s shading_enabled=true -s seed=42`

To draw the image's full tonal range, including near-solid black, opt into
`-s max_fill=100`; 100 is never the default.

**Breaking change**: `line_density` now scales the luminance-progress stop
rule instead of counting lines per millimetre, and `min_length` and
`max_length` are image pixels rather than millimetres.

#### PFM Presets (`--pfm NAME`)

`--pfm` accepts both the registered algorithm name (`sketch_lines`) and a
built-in preset name. A preset supplies a bundle of the settings above; any
`-s` override is applied on top of it. Run `penpath info pfms` to list them.

| Preset | Character |
|--------|-----------|
| `default` | Shipped defaults below; passes the SSIM likeness gate for all five reference images. |
| `fine` | Short, thin strokes with fine sampling and squiggles; quirky detail work. |
| `bold` | Fewer, much longer strokes at higher density; graphic, high-contrast look. |
| `shaded` | Dense, many-angled sampling of both shading directions; smooth tone. |
| `squiggly` | Erasing off (`erase_enabled=false`): a dense, dark decorative scribble, not a photo likeness. |
| `crosshatch` | Angles restricted to 45–135°, so strokes cross in a woven grid. |
| `hatch_horizontal` | Angles near 85–95°, giving near-horizontal hatching. |
| `hatch_vertical` | Angles near 0–10°, giving near-vertical hatching. |

The three hatch presets and `squiggly` are style choices: they deliberately
give up photo likeness for a particular look. Only `default` is calibrated
against the gate in [docs/TESTING.md](TESTING.md#sketch-lines-likeness-gate-luc-47).

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
# The ordered pens become layer1, layer2, ... in drawing order; pens that
# receive no strokes are skipped, so a palette of twelve may yield fewer layers.

# Skip vpype (faster, less optimized)
penpath convert photo.jpg --no-vpype

# Cap the working image at 800 px on its longest side, or keep source pixels
penpath convert photo.jpg --max-resolution 800
penpath convert photo.jpg --no-downscale

# Collect progress in a log while the command runs (stdout stays empty)
penpath convert photo.jpg 2>convert.log

# Silent conversion: no stderr output, errors still reported, SVG still written
penpath convert photo.jpg --quiet
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
penpath preview plot.svg -o fine.png --layer fine
```

---

### `penpath gcode` — SVG → G-code for a machine

Turn a reviewed SVG into machine G-code using a machine profile. Penpath never
guesses which machine it is talking to: `--profile` is required.

```bash
penpath gcode DRAWING_SVG --profile NAME [OPTIONS]
```

#### Arguments

| Argument | Description |
|----------|-------------|
| `DRAWING_SVG` | Reviewed SVG (penpath SVG or plain stroke SVG), in millimetres |

#### Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--profile NAME` | — | — | Machine profile name (required; see `penpath info profiles`) |
| `--output PATH` | `-o` | `<input>.gcode` | Output file, beside the input SVG |
| `--profiles PATH` | — | user config | Alternate user profiles YAML file for this run |
| `--dry-run` | — | `false` | Write G-code to stdout; send every message to stderr |

Each Inkscape pen layer (`<g inkscape:groupmode="layer">`) becomes a G-code
layer in document order, which is the drawing order of the pens. Strokes inside
a layer are sorted by nearest-neighbour travel before they are emitted. Layers
with no strokes are skipped entirely, so an unused pen never causes a pause.
Exactly one pen-change block is emitted before each used layer according to the
profile's `pen_change.mode`: `between` skips the first layer, `each` pauses
before every layer (needed by machines that set the pen at a touch spot before
the first stroke), and `none` never changes pens. The pen name and both layer
and pen indices are available to the block's messages and to the layer code
blocks through the placeholders below.

The default output path replaces the SVG suffix: `card.svg` becomes
`card.gcode` beside the input. It is printed to stderr with the summary.
`--profiles PATH` replaces the default user file for one run; a profile there
overrides a built-in of the same name. See **Machine Profile Format** below for
the YAML shape.

With `--dry-run`, stdout carries only G-code (no file is written), so the output
can be piped to a printer or captured by a script. Without it, stdout stays
empty. Every message, including the output path and the summary, goes to
stderr in both cases.

The stderr summary reports the number of layers, drawing length, pen-up travel
and pen lifts measured from the SVG's strokes, plus an estimated plot time
from the profile's draw, travel and Z feeds (one down and one up per stroke plus
a final lift). A point outside the drawable area (minus `bed.margin_mm`) fails
the run with its coordinates instead of writing G-code the machine cannot
follow.

Exit codes: **2** for a missing or unknown `--profile` (the message lists the
available profiles), **3** for an unreadable or invalid profile file or a point
outside the drawable area, and 1 for other file errors.

#### Examples

```bash
penpath gcode card.svg --profile generic -o card.gcode
penpath gcode card.svg --profile generic             # writes card.gcode
penpath gcode card.svg --profile generic --dry-run > card.gcode
penpath gcode card.svg --profile my_plotter --profiles ./profiles.yaml

# A palette SVG: one G-code layer per used pen, with a pen change between layers
penpath gcode christmas_card.svg --profile generic -o card.gcode
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
penpath evaluate photo.jpg plot.svg --dpi 5 --layer fine
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
| `profiles` | List built-in and user machine profiles (source, description, bed size, feeds) |
| `filters` | List available filters with parameters |
| `image PATH` | Show image info (size, mode, EXIF, DPI, planned working resolution) |
| `config` | Show resolved config (config + project + defaults) |

#### Options

| Option | Description |
|--------|-------------|
| `--format json\|yaml\|table` | Output format (default: table) |
| `--config PATH` (`-c`) | Config file path; sets the default paper and pen used for the planned working resolution |

Every `info` subcommand writes to stdout: a rich table by default (colours are
disabled when stdout is not a terminal) or one machine-readable document with
`--format json` / `--format yaml`. `penpath info profiles --format json` prints
one object with a `profiles` array, whose rows have `name`, `source`,
`description`, `bed_width_mm`, `bed_height_mm`, `travel_mm_s`, `draw_mm_s` and
`z_mm_s` (the Z feed falls back to the travel feed when the profile omits it).

#### Examples

```bash
penpath info pens
penpath info palettes
penpath info palettes --format json
penpath info papers --format yaml
penpath info pfms
penpath info profiles
penpath info profiles --format json
penpath info filters
penpath info image photo.jpg
penpath info image photo.jpg --format json
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

## Machine Profile Format (`profiles.yaml`)

A machine profile holds every value `penpath gcode` needs to drive a plotter:
bed geometry, feed rates, pen heights, verbatim G-code blocks and pen-change
steps. Machine values live in the profile, never in penpath's code. Paper size,
pen colours and pen widths stay in the reviewed SVG.

### Where profiles live

- **Built-in**: one YAML file per machine in `src/penpath/presets/profiles/`.
  `generic` ships today. The profile name is the file name.
- **User**: `$XDG_CONFIG_HOME/penpath/profiles.yaml`, or
  `~/.config/penpath/profiles.yaml` when `XDG_CONFIG_HOME` is unset. One file
  holds several machines as a mapping of names to profiles; a profile with a
  built-in's name **overrides** the built-in.

`penpath info profiles` lists both, marks the source of each (`built-in` or
`user`) and shows its description, bed size and feeds. `penpath gcode` reads
these files through `--profile` and `--profiles`. Creating or editing profiles
is done by hand for now.

### Complete example

This profile is complete and loads unchanged. Save it as
`~/.config/penpath/profiles.yaml` under a name (see below), or as a built-in
file with the same body minus the outer name.

```yaml
version: 1
name: my_plotter
description: Example machine with a Z-lifted pen and an offset toolhead

bed:
  size_mm: [220.0, 220.0]              # physical bed, X and Y in mm
  pen_offset_mm: [-22.7, -28.6]        # pen relative to the nozzle
  nozzle_range_mm: [[0.0, 220.0], [0.0, 220.0]]  # where the nozzle may go
  margin_mm: 2.0                       # keep the drawing this far from the edge
  page:
    placement: reachable_corner        # fixed | reachable_corner
    origin_mm: [0.0, 0.0]              # pen-space page origin (fixed only)
  invert_y: true                       # machine Y grows up, SVG Y grows down

feed:
  travel_mm_s: 100.0                   # G0 speed
  draw_mm_s: 25.0                      # G1 speed
  z_mm_s: 10.0                         # Z speed (optional, defaults to travel)

pen:
  z_up: 12.5                           # Z that lifts the pen
  z_down: 9.0                          # Z that lowers the pen
  z_touch: 10.0                        # Z where the pen touches the paper
  z_hover: 10.5                        # Z just above the paper before landing
  ramp_mm: 1.5                         # landing/lift distance (optional)
  touch_xy_mm: [190.0, 12.0]           # pen-space spot where the pen is set
  up_code: null                        # machines needing a command, not a Z
  down_code: null

gcode:
  comment_prefix: ";"
  start: |
    G21
    G90
    G28
  end: |
    M2
  layer_start: "; layer {layer_index}/{layer_count}, pen {pen} ({pen_index}/{pen_count})"
  layer_end: ""

pen_change:
  mode: each                           # between | each | none
  steps:
    - {z: up, feed: z}
    - {xy: touch, feed: travel}
    - {raw: "M300 S1000 P300"}
    - {message: "Change to {pen} ({pen_index}/{pen_count})"}
    - {pause: "Press the knob"}
```

To put that example in your user file, indent the whole block under `my_plotter:`
(two spaces); the inner `name:` key must match. Unknown keys are rejected so
typos fail loudly. `version` must be `1`; `name`
must be omitted or match the built-in file name or user mapping key. Required
sections are `bed` (with `size_mm`), `feed` (with `travel_mm_s` and
`draw_mm_s`) and `pen` (with `z_up` and `z_down`). All other keys above are
optional; the shipped `generic.yaml` is a smaller, complete profile.

### Profile fields

| Key | Meaning |
|-----|---------|
| `description` | Text shown by `penpath info profiles`. |
| `bed.size_mm` | Physical bed `[X, Y]` in millimetres; both must be positive. |
| `bed.pen_offset_mm` | Pen position relative to the nozzle; the emitted G-code uses `nozzle = pen - offset`. Defaults to `[0, 0]`. |
| `bed.nozzle_range_mm` | Optional `[[xmin, xmax], [ymin, ymax]]` for where the nozzle may travel. The drawable area is this range shifted by the pen offset and clipped to the bed; without it the bed itself is drawable. |
| `bed.margin_mm` | Keep every point this far inside the drawable area. Defaults to `0`. |
| `bed.page.placement` | `fixed` puts the page bottom-left at `origin_mm`; `reachable_corner` puts the page bottom-right at the drawable area's front-right corner. |
| `bed.page.origin_mm` | Pen-space page origin used with `placement: fixed`. |
| `bed.invert_y` | `true` when machine Y grows up while SVG Y grows down. Defaults to `true`. |
| `feed.travel_mm_s` / `feed.draw_mm_s` | G0 / G1 speed in mm per second; both must be positive. |
| `feed.z_mm_s` | Z speed; falls back to `travel_mm_s` when omitted. |
| `pen.z_up` / `pen.z_down` | Pen-up and pen-down Z; `z_down` must be lower than `z_up`. |
| `pen.z_touch` / `pen.z_hover` | Optional Z heights between down and up, used by the landing ramp and the pen change. |
| `pen.ramp_mm` | Optional landing/lift distance; requires both `z_touch` and `z_hover`. |
| `pen.touch_xy_mm` | Optional pen-space point where the pen is set during a pen change. |
| `pen.up_code` / `pen.down_code` | Optional commands for machines that lift with a command instead of a Z move. |
| `gcode.comment_prefix` | Comment prefix, `";"` by default. |
| `gcode.start` / `gcode.end` | Verbatim G-code written once at the top / bottom of the file. |
| `gcode.layer_start` / `gcode.layer_end` | Verbatim G-code written before / after each layer's strokes. |
| `pen_change.mode` | `each` changes before every used layer including the first; `between` skips the first; `none` never changes. Layers with no strokes are not used layers. |
| `pen_change.steps` | Ordered steps of one pen change. Each step has exactly one action: `z` (`up`, `down`, `touch`, `hover` or a number), `xy` (`touch` or `[x, y]`), `raw` (one verbatim G-code line), `message` (`M117`) or `pause` (`M0`, optionally with text). An optional `feed: travel\|draw\|z` selects the feed for `z` and `xy` moves: without it the move is `G0`, with it the move is `G1` at the profile's feed in mm/min. `z: touch\|hover` and `xy: touch` need the matching `pen` fields in the profile. |

### Placeholders

`{pen}`, `{pen_index}`, `{pen_count}`, `{layer_index}` and `{layer_count}`
work in every `pen_change` text (`raw`, `message`, `pause`) and in all `gcode`
code blocks (`start`, `end`, `layer_start`, `layer_end`). Code blocks also
accept the profile's own scalars: `{z_up}`, `{z_down}`, `{z_touch}`,
`{z_hover}`, `{feed_travel}`, `{feed_draw}`, `{feed_z}`, `{ramp_mm}` and
`{lead_in_mm}`.

There are **no coordinate placeholders**. Code blocks are verbatim
machine-space G-code, so any coordinate written in one is a literal number.
The coordinates penpath manages (page placement and the pen-change touch spot)
come from the profile's pen-space fields instead.

### Coordinates: pen space vs machine space

- The **SVG page** is millimetres, origin top-left, Y growing down.
- **Pen space** is millimetres, origin at the bed's front-left corner, X to the
  right and Y towards the back. `bed.page.origin_mm` and `pen.touch_xy_mm` are
  pen space, as are the page and touch-spot coordinates the emitter computes.
- **Machine space** is what the emitted G-code uses: nozzle coordinates. For
  every pen-space point, `nozzle = pen - bed.pen_offset_mm`. Coordinates in
  verbatim `gcode` blocks are already machine space and are passed through
  unchanged.

With `placement: fixed`, the page's bottom-left corner sits at
`bed.page.origin_mm`. With `placement: reachable_corner`, the page's
bottom-right corner sits at the drawable area's front-right corner
(`x = drawable_x_max - page_width`, `y = drawable_y_min`). Stroke points map as:

```
X_pen = page_origin_x + x_svg
Y_pen = page_origin_y + page_height - y_svg   # invert_y: true
Y_pen = page_origin_y + y_svg                 # invert_y: false
```

For the example above, the pen offset `[-22.7, -28.6]` on a 220 x 220 mm bed
with a 0..220 nozzle range gives a drawable area of X 0..197.3 mm and Y
0..191.4 mm. Coordinates are written with three decimals (0.001 mm); a point
outside the drawable area (minus `margin_mm`) fails the run with its
coordinates instead of writing G-code the machine cannot follow.

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
| 3 | Validation error (project file invalid, config invalid, PFM settings invalid, profile file invalid or drawing outside the bed) |

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
  -s line_density=0.4 -s shading_enabled=true -s seed=12345 \
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