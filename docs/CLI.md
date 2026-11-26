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
| `--auto-equalize` / `--no-auto-equalize` | — | `true` | Normalize the working image's luminance range (linear auto levels) once before drawing. Use `--no-auto-equalize` to keep the original tones. |
| `--background` / `--no-background` | — | mode-dependent | Mask paper-coloured pixels as no ink. On by default with `--palette`, off for a single pen; the flag overrides either mode. |
| `--background-threshold FLOAT` | — | `10` | Maximum CIE Lab distance from the detected paper colour treated as no ink. Giving it enables masking unless `--no-background` is also given. |
| `--background-method [global\|local]` | — | `local` | How paper is found: a smooth per-pixel field that follows lighting gradients and shadows, or one detected colour. Giving it enables masking unless `--no-background` is also given. |
| `--saturation FLOAT` | — | `1.0` | CIE Lab chroma multiplier for palette mode, in [0, 3]. `1.0` is off; `0` makes the image neutral. |
| `--palette-adapt` | — | `false` | Pick the multiplier automatically from the image and the palette. An explicit `--saturation` wins. |
| `--max-resolution PX` | — | derived | Longest side of the working image in pixels. Overrides the derived value (no clamp) and never enlarges. |
| `--no-downscale` | — | `false` | Keep the source pixels; do not downscale before drawing |

Auto equalization is on by default. After downscaling and before palette
separation, penpath stretches the working image's luminance range `[lo, hi]`
to `[0, 255]` with one linear lookup table applied to every colour channel;
alpha is left untouched. It is a no-op for images that already cover 0-255,
for images that already span at least 7/8 of 0-255 (224 levels), and for
near-uniform images, so a calibrated plot is unchanged. Pass
`--no-auto-equalize` to keep the original tones, or set `image.auto_equalize:
false` in a project file. This is one global pre-separation step, not a `-f`
filter, so every palette pen uses the same normalization and explicit filters
keep their meaning.

Background masking follows auto equalization and runs before palette
separation. With the default `--background-method local`, penpath builds a
smooth per-pixel paper field from a downsampled, median-filtered version of the
image and sets pixels within 10 CIE Lab ΔE of the field at that pixel to pure
white. The field follows lighting gradients and soft shadows, so a pale page
stays no-ink end to end; thin ink is removed before the estimate and dense
hatching is kept from becoming fake paper. `--background-method global` keeps
the original single-colour mask: it estimates paper from the median colour of a
thin border ring (falling back to the lightest near-neutral cluster when the
border is dark) and tests every pixel against that one colour. It is the
reproducible comparison: on the synthetic gradient page at
`--background-threshold 5` it leaves the dimmed half unmasked and a light pen
scribbles there, while `local` masks only the dark line at the same threshold.
Because white has luminance 255, masked pixels are white in every separated
pen channel, so no pen can draw the paper. The paper colour and method used,
plus the masked percentage, go to stderr; `--quiet` silences all of it. An
explicit `--background-method` enables masking on a single pen just like
`--background-threshold`, and `--no-background` always wins. The default
threshold of 10 ΔE was measured on the synthetic pencil-on-paper fixture:
after auto equalization paper noise reaches 4.4 ΔE at the 99th percentile while
the faintest ink starts at 17.4 ΔE, so the cut-off sits well below any ink.
Lowering it can leave paper noise unmasked; raising it too far can eat faint
ink.

A colour boost follows masking, still before palette separation. It multiplies
CIE Lab a* and b* by a factor and leaves L* alone, so tones and ink density do
not move. `--saturation FLOAT` sets the factor directly in [0, 3]; `1.0` is a
byte-for-byte no-op and `0` removes chroma. `--palette-adapt` instead chooses
the factor so the 90th-percentile chroma of non-background pixels reaches the
palette's median chroma, clamped to [1, 3]; an already-saturated image gets
`1.0`. Passing an explicit `--saturation` disables adaptation for that run.
The factor actually used goes to stderr (silenced by `--quiet`), for example
`Saturation factor: 3.00 (palette-adapted)`. Both options are meaningful only
with `--palette`: a single pen ignores them rather than failing.

#### Drawing Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--pfm NAME` | — | `sketch_lines` | PFM algorithm or built-in preset (see **PFM Presets** below) |
| `--pfm-setting KEY=VALUE` | `-s` | — | PFM-specific setting (repeatable). See **PFM Settings** below. |
| `--pen SPEC` | — | `fine` | Pen preset name or inline `WIDTH[,COLOR[,TYPE]]` (see **Pens** below) |
| `--palette NAME\|LIST` | — | — | Built-in palette name (`stabilo_88`) or inline `name=width,#hex;name2=width,#hex`. Mutually exclusive with `--pen`. |
| `--paper NAME` | — | `a4` | Paper preset name or `WIDTHxHEIGHT[,margins]` (e.g., `a4`, `210x297,10`) |

#### Pens (`--pen`)

A preset name is looked up first (user config, then the built-ins listed under
**Pen Presets**). Otherwise `--pen` takes the inline form
`WIDTH[,COLOR[,TYPE]]`:

```bash
penpath convert photo.jpg --pen 0.4                       # black rollerball
penpath convert photo.jpg --pen 0.4,#FF6600               # named or #RRGGBB colour
penpath convert photo.jpg --pen 0.4,#000000,fineliner     # explicit type
```

`WIDTH` is in millimetres, greater than 0 and at most 10. Omitted `COLOR`
defaults to `#000000`; omitted `TYPE` defaults to `rollerball`. The accepted
types are `ballpoint`, `fineliner`, `fountain`, `brush`, `marker`, `rollerball`
and `gel`. Pydantic validates every field: an invalid width, colour or type
exits 2 with a message naming the field and what it accepts. `--pen 0.4` is
supported; there is no `default` alias.

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

`--palette NAME|LIST` splits the loaded colour image before filtering: a pixel
with meaningful chroma goes to the pen with the closest hue angle, with chroma
and lightness only breaking ties, while a near-neutral pixel keeps the plain
nearest-in-CIE-Lab choice. That pen receives a full-size greyscale image
holding the luminance of its own pixels and white elsewhere. The filters and
the drawing algorithm then run once per pen, and geometry is simplified,
merged and sorted **within that pen only**. Paper masking is on by default in
palette mode so pale paper never becomes a light pen's drawing;
`--no-background` turns it off, `--background` forces it on for a single pen,
`--background-threshold` tunes the cut-off, and `--background-method global`
switches back to the old single-colour estimate. A very muted image can be
boosted before the split with `--saturation` or `--palette-adapt` so pixels
below the neutral cut-off join their hue family; the report of the factor used
is described under **Image Options**.

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
the counter ends at 5 when it is skipped. A `[n/N] Masking paper
background...` stage and a `Paper colour: #...... (local method); masked N% of
pixels as no ink` line appear when masking runs (palette mode by default),
raising the counter by one. The working-resolution line is written to stderr
too. `--quiet` removes all of this, including the "SVG saved to" line; errors
are still reported on stderr and the SVG is still written.

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
| `line_density` | float | 0.01–10.0 | `0.97` | Fraction of luminance progress at which drawing stops; higher draws more ink. With the tone rule on, values above 1 stop at full tone coverage. |
| `max_fill` | float | 1–100 % | `90.0` | Maximum ink coverage. Tones darker than `255 * (1 - max_fill / 100)` are treated as black; `100` keeps the full range. |
| `tone_coverage` | float | 0–1 | `0.5` | Fraction of a pixel's distance to white that may be spent on ink. `1` restores the pre-LUC-128 search. |
| `tone_exponent` | float | 0–2 | `0.55` | Shape of the tone budget curve; below 1 gives mid tones a clearer hatch step. |
| `texture_limit` | float | 0–1 | `0.8` | How much local texture reduces the budget in dark areas, so hair and foliage keep white gaps. |
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

The three tone settings apply when the image has local texture: at least 18%
of pixels have a luminance standard deviation of 20 or more in a window the
size of `sample_step`. Flat shapes and smooth gradients keep the calibrated
luminance-progress rule so their ink spread does not change. To restore the
pre-LUC-128 search on a photo, use `-s tone_coverage=1 -s tone_exponent=1
-s texture_limit=0` together with `-s max_fill=80 -s line_density=0.75`.

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

# Paper masking: local follows lighting gradients (default); global is the old
# single-colour mask. Lower the cut-off to see the gradient repro.
penpath convert photo.jpg --palette stabilo_88 --background-method local
penpath convert photo.jpg --palette stabilo_88 --background-method global --background-threshold 5

# Keep the original tonal range (auto equalization is on by default)
penpath convert photo.jpg --no-auto-equalize

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

Render an SVG's or G-code file's pen strokes with the core plot simulator, so
you can check how the finished plot will look before plotting. The input format
is chosen by suffix: `.gcode` is interpreted as G-code, everything else as SVG.

```bash
penpath preview DRAWING -o OUTPUT [OPTIONS]
```

#### Arguments

| Argument | Description |
|----------|-------------|
| `DRAWING` | SVG (penpath SVG or plain stroke SVG) or `.gcode` file written by `penpath gcode` |

#### Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--output PATH` | `-o` | — | Output image path (required, PNG) |
| `--dpi FLOAT` | — | `10.0` | Resolution in **pixels per millimetre** |
| `--paper-color COLOR` | — | `#FFFFFF` | Paper background colour (hex or named CSS colour) |
| `--layer LABEL` | — | all | Only preview this pen layer (layer label or id; for G-code, the pen name) |
| `--travel/--no-travel` | — | `false` | Draw pen-up travel moves as thin light lines |

For an SVG the page size is read from `width`/`height` or `viewBox`; SVGs without
one fall back to A4. For G-code the page is the `page=WIDTHxHEIGHT` value in the
header (the source SVG page in millimetres), falling back to the bed of the
profile named in the header and then to A4. All messages go to stderr, so stdout
stays clean.

#### Previewing G-code

A `.gcode` file is read by a small interpreter for `G0`/`G1` moves, `Z` pen
up/down, `F` feeds and comments; everything else is ignored. **Arcs (`G2`/`G3`)
are not supported** and fail with a clear error. The header carries the profile
name, the source page size as `page=WIDTHxHEIGHT` in millimetres (three decimals,
as the Z fields), and Z values: a segment is drawn when the pen is at or below
`z_touch`, or `z_down` when no touch height is declared. A file without a header
uses its lowest Z as "down". The preview flips Y around the header page height
and undoes the page origin, pen offset and Y inversion with the same shared
`page_origin_mm()` helper the emitter uses, so the G-code PNG matches the SVG
PNG at the same `--dpi` even when the page differs from the bed or the profile
uses `reachable_corner`. Layers use the width and colour of their pen from the
built-in presets (`stabilo_88_*`, `red_fine`, ...); an unknown pen renders black
at 0.3 mm because G-code carries no colours.

#### Showing pen-up travel

`--travel` adds thin light grey (0.1 mm, `#C8C8C8`) lines for pen-up moves, so
long travels between strokes are easy to spot. For an SVG these are the gaps
between consecutive strokes in document order; for G-code they are the gaps
between the strokes the machine actually draws, in G-code order. Both use the
same straight two-point travel rule with a 0.01 mm gap threshold as
`penpath.core.svg_parse.parse_svg_strokes(..., include_pen_up=True)`. The travel
lines are drawn **under** the ink, so every inked pixel is unchanged. The default
is `--no-travel`, which renders ink only and produces byte-for-byte the same PNG
as before. `--travel` also works with `--layer`, where only that pen's strokes
and travels are shown.

#### Examples

```bash
penpath preview plot.svg -o preview.png
penpath preview plot.svg -o preview.png --dpi 20 --paper-color "#F5F5DC"
penpath preview plot.svg -o fine.png --layer fine
# Show pen-up travel as thin light lines under the ink (default: ink only)
penpath preview plot.svg -o travel.png --travel

# Check the G-code against the reviewed SVG (the two PNGs match)
penpath gcode card.svg --profile generic -o card.gcode
penpath preview card.gcode -o card.png
penpath preview card.gcode -o red.png --layer stabilo_88_red
penpath preview card.gcode -o card_travel.png --travel
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
| `--margin MM` | — | profile value | Override the profile safety margin for this run in mm; `0` is allowed but not recommended on the Aquila |
| `--dry-run` | — | `false` | Write G-code to stdout; send every message to stderr |
| `--fit/--no-fit` | — | `--fit` | Fit a drawing past the usable area into it (default), with a warning on stderr; `--no-fit` keeps the strict error |

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

`--margin MM` replaces the loaded profile's safety margin with one non-negative
value on all four sides for this run, before the fit, the strict check and the
G-code are built. The G-code header then reports the overridden usable area, so
`penpath preview` renders the same placement. `--margin 0` removes the margin;
it is allowed but not recommended on the Aquila, where the margin keeps strokes
away from the edges of the paper. The option works with `--fit`, `--no-fit` and
`--dry-run`, and the original profile file is never changed.

The stderr summary reports the number of layers, drawing length, pen-up travel
and pen lifts measured from the SVG's strokes, plus an estimated plot time
from the profile's draw, travel and Z feeds (one down and one up per stroke plus
a final lift).

The first G-code line is a header comment written for `penpath preview`. It
carries the profile name, page size, the page origin that was used, the usable
area bounds and the Z heights, for example
`; penpath gcode profile=aquila page=170.000x170.000 page_origin=17.300,10.000 usable_x=10.000..187.300 usable_y=10.000..181.400 z_up=12.500 ...`.
The preview reads `page_origin` so a one-run margin override placed through the
profile is inverted with the same origin the emitter used.

#### Fitting an oversized page

By default `penpath gcode` fits a reviewed page that reaches past the machine's
usable area instead of refusing it. `penpath.core.fit_layers_to_drawable`
maps the strokes into pen space the same way the emitter does, reserves the four
per-side `bed.margin_mm` values plus the ramp lead-in on every side so ramped
landings stay reachable, then shifts the drawing the shortest way that fits. It
scales the drawing down uniformly only when it is larger than the available area. When the
fit changes the drawing, one warning goes to stderr naming the overshoot, the
scale and the applied pen-space shift, for example:

```
Warning: drawing is 0.881 mm past the aquila usable area; fitted with scale 1.000 and shift (-0.881, 0.000) mm
```

The overshoot includes the reserved ramp lead-in, so it can exceed the amount
the strict check reports for the same page. Overruns of `FIT_TOLERANCE_MM =
0.05` mm or less are float rounding: the drawing is left untouched and no
warning is printed. The warning never goes to stdout, so `--dry-run` output is
still G-code only. No `.gcode` file is written unless the complete document was
built successfully.

Pass `--no-fit` to keep the strict check: a point outside the usable area (the
drawable area minus `bed.margin_mm`) then fails with exit 3, naming its
coordinates, the per-axis overshoot and the fix:

```
Error: point (x=187.431, y=170.000) mm is outside the usable area X 10.000..187.300, Y 10.000..181.400 mm (drawable area minus a 10.000 mm margin); overshoot x=0.131 mm, y=0.000 mm Pass --fit (the default) or use a smaller --paper.
```

#### Ramped landing

When a profile sets `pen.ramp_mm` together with `z_touch` and `z_hover`, each
stroke gains a lead-in of
`lead_in_mm = ramp_mm * (z_hover - z_touch) / (z_touch - z_down)` before its
first point and an equal lead-out after its last. Z falls linearly from
`z_hover` to `z_down` over `lead_in_mm + ramp_mm` and rises the same way at the
end, so the pen lands and lifts **while moving** and no ink dot is left at a
stroke start. The lead-in and lead-out are above the paper and are not previewed
as ink: `penpath preview` clips Z-interpolated moves at `z_touch`, so the G-code
PNG still matches the reviewed SVG. The G-code is written in nozzle coordinates
(`nozzle = pen - bed.pen_offset_mm`) and every emitted point, including the
lead-in and lead-out, is checked against the usable area. A profile without
`ramp_mm` keeps the plain travel → pen-down → draw → pen-up stroke and produces
exactly the same G-code as before. `pen.z_touch` must be above `pen.z_down` and
`pen.z_hover` must not be below `pen.z_touch` when ramping.

Exit codes: **2** for a missing or unknown `--profile` (the message lists the
available profiles), **3** for an unreadable or invalid profile file, a drawing
that cannot be fitted, or (with `--no-fit`) a point outside the usable area,
and 1 for other file errors.

#### Examples

```bash
penpath gcode card.svg --profile generic -o card.gcode
penpath gcode card.svg --profile generic             # writes card.gcode
penpath gcode card.svg --profile generic --dry-run > card.gcode
penpath gcode card.svg --profile my_plotter --profiles ./profiles.yaml

# A palette SVG: one G-code layer per used pen, with a pen change between layers
penpath gcode christmas_card.svg --profile generic -o card.gcode

# The built-in aquila profile: page against the usable corner, ramped landings,
# a pen set at the touch spot before every layer, and no M2 at the end
penpath gcode card.svg --profile aquila -o card.gcode
# A slightly oversized page is fitted with a warning on stderr
penpath gcode card.svg --profile aquila
# --no-fit restores the strict exit-3 error
penpath gcode card.svg --profile aquila --no-fit
```

The complete operator workflow and checklist for the Aquila, with the
reference-versus-penpath equivalence check, are in
[docs/AQUILA.md](AQUILA.md).

---

### `penpath evaluate` — Score likeness and machine cost

Simulate the SVG at the chosen resolution, crop it to the recorded image
placement, and compare it with the original using two SSIM scores. `likeness`
compares **greyscale** images: pale ink on a near-blank page looks almost
neutral there, so this score alone can accept a page-covering light-blue
scribble. `edge_likeness` compares the Sobel gradient magnitudes of the same
two prepared images, so spurious structure the original does not have is
penalised. Both use the same crop, 256x256 size and blur sigma 1.5. Also
reports machine cost (drawing length, pen-up travel, pen lifts, short segments
and stroke count) plus ink coverage and the pen name per pen layer and in
total. Coverage is the share of the whole page inked by a layer's pen-down
strokes at the chosen `--dpi`; per-layer shares may overlap, so they need not
add up to the total.

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
| `--coverage-warn PCT` | — | `50` | Warn on stderr when a layer covers more than this percentage of the page; `0` disables the warning; value must be `>= 0` |

For SVGs without placement metadata, the image is fitted to the page keeping
its aspect ratio and centered — the same fallback used by
`penpath.core.svg_parse.get_image_placement`.

In the human-readable machine-cost table, `Layer` is the stroke hex and `Pen`
is the name of the Inkscape layer that uses it (the layer's `inkscape:label`,
or its id when no label exists). A colour with no matching layer shows the hex
again. The `TOTAL` row has no pen. When a layer exceeds `--coverage-warn`, one
warning per layer is written to stderr naming the layer and its percentage,
and suggesting `--background-threshold` and `--saturation`. A warning changes
neither the exit code nor the result; it is also printed in `--json` mode,
where stdout stays pure JSON.

With `--json`, stdout contains only a single object (safe to pipe to `jq`):

```json
{
  "likeness": 0.82,
  "edge_likeness": 0.74,
  "machine_cost": {
    "per_layer": {
      "#8CCFE8": {
        "drawing_length_mm": 123.4,
        "ink_coverage_pct": 12.3,
        "pen": "stabilo_88_light_blue"
      },
      "#000000": {
        "drawing_length_mm": 45.6,
        "ink_coverage_pct": 4.5,
        "pen": "stabilo_88_black"
      }
    },
    "total": {"drawing_length_mm": 169.0, "ink_coverage_pct": 16.8}
  }
}
```

The human Likeness table shows both scores as `SSIM` and `Edge SSIM`. Edge
SSIM divides both edge maps by one shared maximum before comparing them, so a
blank page is not normalised into false edges; when both maps are zero it is
1.0. Neither score changes the calibrated LUC-47/LUC-78/LUC-86 gates:
`edge_likeness` is a diagnostic, not a new pass/fail gate.

Every per-layer entry keeps its existing numeric keys and gains `pen`; `total`
is unchanged. The name comes from
`penpath.core.svg_parse.get_layer_pen_names(svg_path)`, which maps each
normalised `#RRGGBB` stroke colour to the first Inkscape layer using it; a
colour with no layer falls back to its hex.

#### Examples

```bash
penpath evaluate photo.jpg plot.svg
penpath evaluate photo.jpg plot.svg --json | jq '.likeness'
penpath evaluate photo.jpg plot.svg --json | jq '.edge_likeness'
penpath evaluate photo.jpg plot.svg --dpi 5 --layer fine
penpath evaluate photo.jpg plot.svg --coverage-warn 75
penpath evaluate photo.jpg plot.svg --coverage-warn 0
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
| `palette-match PATH` | Show which palette pens raw colour separation picks and each pen's pixel share |
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
`description`, `bed_width_mm`, `bed_height_mm`, `margin_mm`, `travel_mm_s`,
`draw_mm_s` and `z_mm_s` (the Z feed falls back to the travel feed when the
profile omits it). `margin_mm` is the profile's raw value: a scalar for a
uniform margin or `[top, right, bottom, left]` for a per-side margin. The table
shows a `Margin (mm)` column with the same value, printing `10` or `10/5/10/5`.

#### `penpath info palette-match`

```bash
penpath info palette-match IMAGE_PATH [OPTIONS]
```

Measures the **raw, pre-drawing** colour separation of the loaded image: it
runs the same `separate_palette` as `convert` and counts the pixels each pen's
layer actually inks (a layer pixel below 255). No filters, background masking,
auto equalization or saturation boost is applied, and nothing is drawn, so the
numbers describe the pixels before the convert pipeline changes them. Pixels in
connected regions smaller than 8 px are dropped by separation and count as
unassigned, together with paper pixels. Percentages are of all image pixels;
unused pens are kept with a zero count so they are easy to spot.

| Option | Default | Description |
|--------|---------|-------------|
| `--palette NAME\|LIST` | `stabilo_88` | Built-in palette name or inline `name=width,#hex;...` (same parser as `convert --palette`) |
| `--format json\|yaml\|table` | `table` | Output format; table columns are Order, Pen name, Colour, Pixels, Percent and end with an unassigned row |

JSON and YAML contain `path`, `palette`, `width`, `height`, a `rows` array with
`order`, `name`, `color`, `pixels` and full-precision `percent` for every palette
pen in drawing order, plus `unassigned_pixels` and `unassigned_percent`. The
percentages in the table are rounded to one decimal. An invalid palette is a
usage error (exit 2); an unreadable image is reported as a click error naming
the image problem (exit 1).

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
penpath info palette-match photo.jpg
penpath info palette-match photo.jpg --palette "red=0.4,#FF0000;blue=0.4,#0000FF"
penpath info palette-match photo.jpg --palette stabilo_88 --format json
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
  auto_equalize: true   # linear levels normalization before drawing (default)
  background: true             # mask paper before separation (palette default)
  background_threshold: 10.0   # CIE Lab ΔE treated as paper
  background_method: local     # local paper field, or global single colour
  saturation: 1.0              # Lab chroma multiplier (0-3; 1.0 = off)
  palette_adapt: false         # choose the multiplier from image and palette

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
back as `palette:` and an explicit list back as `pens:`. `image.auto_equalize`
defaults to `true`, so older YAML without the field loads with normalization
on; set it to `false` to keep the original tones, or pass
`--auto-equalize` / `--no-auto-equalize` to override it for one run.

The background keys live under `image:` in a file written by `save_yaml`:
`background: true|false` forces masking on or off,
`background_threshold: 10.0` sets the Lab cut-off, and
`background_method: local|global` chooses the paper estimate. Leaving
`background` out follows the mode: on for `palette:`/`pens:`, off for a single
`pen:`. Old files without the method load as `local`, and `save_yaml` omits an
unset `background` so a single-pen project round-trips with today's output.
`--background`, `--no-background`, `--background-threshold` and
`--background-method` override the file for one run; `--no-background` wins on
the same command line.

```yaml
image:
  path: "photo.jpg"
  filters:
    steps: []
  dpi: 300
  background: false
  background_threshold: 4.5
  background_method: local
  saturation: 2.0
  palette_adapt: false
```

The chroma keys live under `image:` as well. `saturation: 2.0` is a manual
multiplier in [0, 3] (default `1.0`), and `palette_adapt: true` chooses it from
the image and the palette. Old files without the keys load as `1.0` and
`false`, so their output is unchanged. `--saturation` on the command line
overrides the file and disables `palette_adapt`; `--palette-adapt` overrides the
file's manual factor. As at the CLI, both keys are no-ops for a single pen.

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
  `generic` (plain Z-lifted plotter) and `aquila` (Voxelab Aquila with a pen
  offset, ramped landing and touch-spot pen change) ship today. The profile
  name is the file name. The Aquila's numbers come from sergio's reference
  script on the read-only `aquila-gcode-reference` branch
  (`reference/aquila_gcode/aquila_plot.py`); its start, pen-change and end
  blocks are verbatim from that script.
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
| `bed.margin_mm` | Safety margin inside the drawable area: one non-negative number for all four sides, or `[top, right, bottom, left]` (four non-negative numbers). In pen space top is the back/max Y, right is max X, bottom is the front/min Y and left is min X. Defaults to `0`. The drawable area inset by these margins is the **usable area**, used by fitting, `reachable_corner` placement, the strict point check and the G-code header. |
| `bed.page.placement` | `fixed` puts the page bottom-left at `origin_mm`; `reachable_corner` puts the page bottom-right at the usable area's front-right corner. |
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
bottom-right corner sits at the usable area's front-right corner
(`x = usable_x_max - page_width`, `y = usable_y_min`). Stroke points map as:

```
X_pen = page_origin_x + x_svg
Y_pen = page_origin_y + page_height - y_svg   # invert_y: true
Y_pen = page_origin_y + y_svg                 # invert_y: false
```

For the example above, the pen offset `[-22.7, -28.6]` on a 220 x 220 mm bed
with a 0..220 nozzle range gives a drawable area of X 0..197.3 mm and Y
0..191.4 mm. The built-in `aquila` profile sets `bed.margin_mm: 10`, so its
usable area is X 10..187.3 mm and Y 10..181.4 mm: the largest page that fits is
about 177 x 171 mm, and a 170 x 170 mm page lands at pen (17.3, 10.0). The
touch spot at pen (190, 12) sits in the safety margin and is not a drawing
point, so it is never checked against the usable area. Coordinates are written
with three decimals (0.001 mm); a point outside the usable area fails the run
with its coordinates instead of writing G-code the machine cannot follow.

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

**Inline Format**: `WIDTH[,COLOR[,TYPE]]` — e.g., `0.4`, `0.4,#FF6600`, or
`0.4,#000000,fineliner`. Colour defaults to `#000000`, type defaults to
`rollerball`; accepted types are `ballpoint`, `fineliner`, `fountain`, `brush`,
`marker`, `rollerball`, `gel`. See **Pens (`--pen`)** above.

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
| 3 | Validation error (project file invalid, config invalid, PFM settings invalid, profile file invalid, drawing cannot be fitted, or `--no-fit` drawing outside the bed) |

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