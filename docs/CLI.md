# penpath CLI Reference (MVP)

**Command**: `penpath`  
**Config File**: `~/.config/penpath/config.toml`  
**Project File**: `project.yaml` (or `.penpath.yaml`)

---

## Global Options

| Option | Short | Env Var | Description |
|--------|-------|---------|-------------|
| `--config PATH` | `-c` | `PENPATH_CONFIG` | Config file path (default: `~/.config/penpath/config.toml`) |
| `--project PATH` | `-p` | — | Project file (YAML) — loads all settings |
| `--verbose` | `-v` | — | Increase log level (repeat: `-vv`, `-vvv`) |
| `--quiet` | `-q` | — | Suppress non-error output |
| `--no-color` | — | `NO_COLOR` | Disable colored output |
| `--version` | `-V` | — | Show version and exit |
| `--help` | `-h` | — | Show help for command |

**Priority**: CLI flags > Project file > Config file > Defaults

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
| `OUTPUT_PATH` | Output SVG path (default: `<input>_plot.svg` beside input) |

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
| `--paper NAME` | — | `a4` | Paper preset name or `WIDTHxHEIGHT[,margins]` (e.g., `a4`, `210x297,10`) |

#### Output Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--no-vpype` | — | `false` | Skip vpype optimization (use direct SVG export) |
| `--vpype-path PATH` | — | `vpype` | Path to vpype executable |
| `--layer-per-pen` / `--single-layer` | — | `layer-per-pen` | SVG layer structure |

#### PFM Settings (Sketch Lines)

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `line_density` | float | `0.3` | Lines per mm (0.1–2.0) |
| `min_length` | float | `0.5` | Minimum line length (mm) |
| `max_length` | float | `10.0` | Maximum line length (mm) |
| `angle_range` | int | `180` | Search angle range (degrees, 1–180) |
| `shading` | bool | `true` | Enable tonal shading |
| `squiggles` | bool | `false` | Add squiggle variation |
| `erasing` | bool | `false` | Enable erasing (lighter areas) |
| `seed` | int | `random` | Random seed for reproducibility |

**Example**: `-s line_density=0.5 -s shading=true -s seed=42`

#### Filters (Applied in Order)

| Name | Params | Description |
|------|--------|-------------|
| `grayscale` | `method=luminance\|lightness\|average\|red\|green\|blue` | Convert to single channel |
| `threshold` | `levels=2-256`, `dither=none\|floyd-steinberg\|ordered` | Posterize to N levels |
| `blur` | `radius=0.5-10`, `type=gaussian\|box` | Blur filter |
| `contrast` | `factor=0.1-3.0` | Contrast adjustment |
| `brightness` | `factor=0.1-3.0` | Brightness adjustment |
| `gamma` | `value=0.1-3.0` | Gamma correction |
| `invert` | (none) | Invert colors |
| `crop` | `left,top,right,bottom` (px or %) | Crop image |
| `resize` | `width,height` or `scale=0.1-10` | Resize image |
| `rotate` | `angle=-180-180` | Rotate image |
| `fit` | `mode=contain\|cover\|stretch`, `dpi=72-600` | Fit to paper (implies resize) |

**Example**: `-f grayscale -f "threshold:levels=4,dither=floyd-steinberg" -f "blur:radius=1.5"`

#### Examples

```bash
# Basic usage
penpath convert photo.jpg

# With custom settings
penpath convert photo.jpg -o plot.svg -f grayscale -f "threshold:levels=4" -s line_density=0.5 -s seed=42

# Using project file
penpath convert --project my_project.yaml

# Override project settings
penpath convert --project my_project.yaml --pen "0.5,#FF0000,rollerball" -o red_plot.svg

# Skip vpype (faster, less optimized)
penpath convert photo.jpg --no-vpype
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
| `default_pen` | string | `default` | Pen preset for `convert` |
| `default_pfm` | string | `sketch_lines` | PFM for `convert` |
| `vpype_path` | string | `vpype` | Path to vpype executable |
| `output_dir` | string | `.` | Default output directory |
| `log_level` | string | `INFO` | Default log level |

#### Examples

```bash
penpath config show
penpath config init
penpath config set default_paper a3
penpath config get vpype_path
penpath config edit
```

---

### `penpath project` — Project File Helpers

```bash
penpath project [SUBCOMMAND] [OPTIONS]
```

#### Subcommands

| Subcommand | Description |
|------------|-------------|
| `create` | Interactive wizard → writes `project.yaml` |
| `validate PATH` | Validate project file, print resolved settings |
| `template` | Print minimal project.yaml template |

#### Options

| Option | Description |
|--------|-------------|
| `--output PATH` | `-o` | Output path for `create`/`template` (default: `project.yaml`) |

#### Examples

```bash
penpath project create -o my_project.yaml
penpath project validate my_project.yaml
penpath project template --output project.yaml
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
  - threshold:
      levels: 4
      dither: floyd-steinberg
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
default_pen = "default"
default_pfm = "sketch_lines"
vpype_path = "vpype"
output_dir = "."
log_level = "INFO"
```

---

## Pen Presets (Built-in)

| Name | Width (mm) | Color | Type | Description |
|------|------------|-------|------|-------------|
| `default` | 0.3 | `#000000` | fineliner | General purpose |
| `fineliner_03` | 0.3 | `#000000` | fineliner | Fine detail |
| `fineliner_05` | 0.5 | `#000000` | fineliner | Standard |
| `rollerball_05` | 0.5 | `#000000` | rollerball | Smooth flow |
| `rollerball_07` | 0.7 | `#000000` | rollerball | Bold |
| `fountain_f` | 0.4 | `#000000` | fountain | Fine nib |
| `fountain_m` | 0.6 | `#000000` | fountain | Medium nib |
| `marker_10` | 1.0 | `#000000` | marker | Broad strokes |
| `red_03` | 0.3 | `#FF0000` | fineliner | Red accent |
| `blue_03` | 0.3 | `#0000FF` | fineliner | Blue accent |

**Inline Format**: `WIDTH,COLOR,TYPE` — e.g., `0.4,#FF6600,fountain`

---

## Paper Presets (Built-in)

| Name | Size (mm) | Margins (mm) | Orientation |
|------|-----------|--------------|-------------|
| `a4` | 210 × 297 | 10 all sides | Portrait |
| `a4_landscape` | 297 × 210 | 10 all sides | Landscape |
| `a3` | 297 × 420 | 15 all sides | Portrait |
| `a3_landscape` | 420 × 297 | 15 all sides | Landscape |
| `letter` | 216 × 279 | 10 all sides | Portrait |
| `letter_landscape` | 279 × 216 | 10 all sides | Landscape |
| `square_200` | 200 × 200 | 10 all sides | Square |
| `postcard` | 148 × 105 | 5 all sides | Portrait |

**Inline Format**: `WIDTHxHEIGHT[,MARGINS]` — e.g., `210x297,10` or `300x200,15,10,15,10` (T,R,B,L)

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

| Variable | Equivalent Flag | Description |
|----------|-----------------|-------------|
| `PENPATH_CONFIG` | `--config` | Config file path |
| `NO_COLOR` | `--no-color` | Disable colors |
| `EDITOR` | `config edit` | Editor for `config edit` |
| `PENPATH_VTYPE_PATH` | `--vpype-path` | vpype executable path |

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
  -f grayscale -f "threshold:levels=6,dither=floyd-steinberg" \
  -s line_density=0.4 -s shading=true -s seed=12345 \
  --pen fineliner_03 --paper a4
```

### Project-Based Workflow
```bash
# Create project
penpath project create -o portrait.yaml
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
penpath convert photo.jpg -f grayscale -f threshold --no-vpype -o debug.svg
# Inspect debug.svg in browser/Inkscape
```

---

## Hidden / Debug Commands (Not in `--help`)

| Command | Purpose |
|---------|---------|
| `penpath _dump-config` | Print full resolved config as JSON |
| `penpath _version-json` | Machine-readable version info |

*Subject to change/removal without notice.*