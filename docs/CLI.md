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

Convert a raster image to a plottable SVG using a Pen Follower Module (PFM).
`sketch_lines` is the default; run `penpath info pfms` to list every registered
PFM, its settings and its presets.

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
| `--no-auto-orient` | — | `false` | Skip EXIF rotation and keep the stored pixel orientation and size (same as `auto_orient: false` in a project file) |
| `--auto-equalize` / `--no-auto-equalize` | — | `true` | Normalize the working image's luminance range (linear auto levels) once before drawing. Use `--no-auto-equalize` to keep the original tones. |
| `--max-coverage` | FLOAT (0, 1] | `0.8` | Largest share of the paper ink may cover where the image is black, measured with the pen width (stroke length × pen width). Lighter tones scale down in proportion. Algorithms with a regular line structure (Hatch, Patch Hatch, Engraving, Squiggle, Spiral) are calibrated on a black test patch first; then every algorithm's latest strokes are removed wherever ~3 mm windows still exceed the cap. Styles that step in whole layers or strokes land on the step at or just below the cap. `1` turns it off. Project file: `image.max_coverage`. |
| `--auto-levels-clip` | FLOAT 0–10 | `0` | Percent of pixels ignored at each end when auto equalize measures the tonal range. `0` uses the darkest and lightest pixel (a single speck or highlight can block the stretch); `0.5` stretches flat photos that have a few extreme pixels. Project file: `image.auto_levels_clip`. |
| `--equalize-levels` / `--no-equalize-levels` | — | `false` | Equalise each pen's image onto the drawing algorithm's own tone steps just before drawing, so every step gets about the same share of the inked pixels: Hatch's bands, Patch Hatch's layers (from pen width and spacing), Engraving's stroke counts, Contour's levels, or 8 even steps for continuous algorithms. Makes dark and flat photos readable; it deliberately changes the tones, so SSIM against the original usually drops. Project file: `image.equalize_levels`. |
| `--background` / `--no-background` | — | mode-dependent | Mask paper-coloured pixels as no ink. On by default with `--palette`, off for a single pen; the flag overrides either mode. |
| `--background-threshold FLOAT` | — | `10` | Maximum CIE Lab distance from the detected paper colour treated as no ink. Giving it enables masking unless `--no-background` is also given. |
| `--background-method [global\|local]` | — | `local` | How paper is found: a smooth per-pixel field that follows lighting gradients and shadows, or one detected colour. Giving it enables masking unless `--no-background` is also given. |
| `--saturation FLOAT` | — | `1.0` | CIE Lab chroma multiplier for palette mode, in [0, 3]. `1.0` is off; `0` makes the image neutral. |
| `--palette-adapt` | — | `false` | Pick the multiplier automatically from the image and the palette. An explicit `--saturation` wins. |
| `--max-resolution PX` | — | derived | Longest side of the working image in pixels. Overrides the derived value (no clamp) and never enlarges. |
| `--no-downscale` | — | `false` | Keep the source pixels; do not downscale before drawing |

Auto equalization is on by default: before separation penpath stretches the
working image's luminance range `[lo, hi]` to `[0, 255]` with one linear lookup
table on every colour channel, leaving alpha untouched. Pass
`--no-auto-equalize` (or `image.auto_equalize: false`) to keep original tones.
It is one global pre-separation step, not a `-f` filter, so every palette pen
uses the same normalization.

Background masking follows auto equalization, before separation. `local`
(default) builds a smooth per-pixel paper field that follows lighting
gradients; `global` tests against one detected colour. The cut-off is in CIE
Lab ΔE: lowering it leaves paper noise unmasked, raising it eats faint ink.
Giving `--background-method` or `--background-threshold` enables masking
unless `--no-background` wins (default on with `--palette`, off for one pen).
The paper colour, method and masked percentage go to stderr; `--quiet`
silences them.

A colour boost follows masking, before separation. `--saturation FLOAT`
multiplies CIE Lab a* and b* in [0, 3] (`1.0` is a no-op, `0` is neutral);
`--palette-adapt` picks the factor from the image and palette, and an explicit
`--saturation` wins. Both need `--palette`; a single pen ignores them. The
factor used goes to stderr, e.g. `Saturation factor: 3.00 (palette-adapted)`,
unless `--quiet`.

#### Drawing Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--pfm NAME` | — | `sketch_lines` | Registered PFM, legacy preset or qualified `PFM:PRESET` id (see **PFM Presets** below). Run `penpath info pfms` to list them. |
| `--pfm-setting KEY=VALUE` | `-s` | — | Setting of the selected PFM (repeatable). See **PFM Settings** below. |
| `--style [sketch\|hatch\|outline]` | — | — | Saved look: chooses the Sketch Lines settings, and the outline pass for `outline`. See **Saved Looks** below. |
| `--pen SPEC` | — | `fine` | Pen preset name or inline `WIDTH[,COLOR[,TYPE]]` (see **Pens** below) |
| `--palette NAME\|LIST` | — | — | Built-in palette name (`stabilo_88`) or inline `name=width,#hex;name2=width,#hex`. Mutually exclusive with `--pen`. |
| `--key-layer` / `--no-key-layer` | — | mode-dependent | Trace a final black layer of edge strokes. On with `--palette`, off for a single pen; the flag overrides either mode. |
| `--paper NAME` | — | `a4` | Paper preset name or `WIDTHxHEIGHT[,MARGINS]` (e.g., `a4`, `210x297,10`, `190x190,20,5,20,5`) |
| `--margin MM` | — | paper value | Override the paper margin for one run: one value or four in top,right,bottom,left order |
| `--fit [fit\|fill\|none]` | — | `fit` | Image placement on the paper: contain, cover and crop, or use the `--dpi` pixel size |

#### Paper Fit and Margins

`--fit` chooses how the source image is placed in the drawable area (the paper
inset by its margins):

| Mode | Result |
|------|--------|
| `fit` (default) | Contain the whole image in the drawable area, keeping its aspect ratio and centred; one dimension touches the area edge. |
| `fill` | Cover the drawable area, keeping the aspect ratio, and crop the ink that falls outside it. |
| `none` | Draw at the image's pixel size at `--dpi`, centred on the paper; the drawing can run off the page. |

`--dpi` therefore sets the drawn size **only** with `--fit none`: `fit` and
`fill` scale the image to the paper and ignore the DPI for sizing. `--dpi`
defaults to 300.

`--margin MM` replaces the paper's margins for that run, including when
`--project` supplies the paper. Give one non-negative millimetre value for all
four sides, or four comma-separated values in **top,right,bottom,left** order.
`--paper WIDTHxHEIGHT[,MARGINS]` takes the same one-or-four margin form, with
the same order. A negative, non-finite or wrongly counted margin is a usage
error (exit 2) naming the option; a margin that leaves no drawable area is
rejected with a message suggesting a smaller margin or a larger paper.

In a project file the same controls are `paper.margin_mm` (a scalar or a
four-item list) and `paper.fit`; `--margin` and `--fit` override them for one
run. See [Project File Format](#project-file-format-projectyaml).

#### Saved Looks (`--style`)

`--style` picks one of three saved looks, so a recognisable drawing needs no
tuning. Any other value exits 2 and lists the valid names. Leaving the flag out
keeps the part 1 defaults exactly: the same settings, the same outline-free
pipeline and the same SVG.

| Style | Look |
|-------|------|
| `sketch` | The shipped part 1 default: tone-adaptive lines with visible tone steps. |
| `hatch` | Directional cross-hatching (45–135°, shading on) with clear tone steps and a lighter ink budget. |
| `outline` | The deterministic edge pass first, then a light tone pass; shapes stay readable with minimal ink. |

Precedence, from strongest to weakest:

1. `-s KEY=VALUE` overrides any single value, whichever look or PFM supplied it.
2. An explicit non-default `--pfm NAME` (or the `pfm:` settings saved in a
   project file) supplies the PFM settings.
3. `--style NAME` (or `style:` in a project file) supplies the look's settings.
   `--pfm default` is *not* a non-default PFM, so the style still applies.
4. The built-in defaults apply when nothing else is given.

The look still decides the outline pass even if a non-default `--pfm` supplies
the tone settings: `--style outline --pfm fine` draws fine pen strokes plus
edge strokes. With `--project`, adding only `-s` overrides the file's saved
settings; adding `--style` or `--pfm` replaces them from that look or preset.
`--style` also overrides the file's `style:` field for that run. The library
counterparts are `penpath.core.get_style`, `list_styles` and
`draw_styled_lines`.

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

Large photos are downscaled before drawing. The working resolution is the
longest side of the image the drawing algorithm works on:

```
working_px = paper_longest_side_mm / pen_width_mm
```

The derived value is clamped to **256–1024 px**; the source is never enlarged
and keeps its aspect ratio. Pixel-valued Sketch Lines settings (`min_length`,
`max_length`, `sample_step`) are interpreted in working-image pixels and are not
scaled. A smaller page derives a smaller working resolution and recomposes the
image; to reproduce a reviewed drawing at another paper size, fix
`--max-resolution PX` and keep the settings so only the export scales — e.g.
`--max-resolution 475 --pen "0.4,#000000,fineliner"` maps 190x107 mm strokes
onto a 130x73 mm page. `--max-resolution` replaces the derived value without
clamping (never enlarging); `--no-downscale` draws at source resolution. The
chosen resolution goes to stderr, silenced by `--quiet`:

```
Working resolution: 475x358 px (source 4080x3072 px, scale 0.116)
```

`penpath info image` shows the planned resolution using the config defaults.

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

Pens draw light → dark, with a near-black pen (sRGB relative luminance `<=
0.02`) always last, so light ink never runs over black ink. The palette's own
order is only the stable tie-breaker for pens of equal lightness: it never
changes which pixel a pen receives, because separation still uses the order
given by `--palette`. Each pen that produced strokes becomes one Inkscape layer
named `layerN`, where `N` counts only the used pens from 1 in drawing order: an
unused pen gets no layer and does not shift the numbering. An inline list is
used exactly as given for separation, but its layers follow ink order.
`penpath info palettes` reports that drawing order in its `order` column; the
built-in `stabilo_88` definition table keeps its original order. `--pen` and
`--palette` cannot be combined: penpath reports a usage error instead of
choosing one silently. Without `--palette`, the default single pen draws the
whole image and produces a single layer, exactly as before. The library helper
behind both paths is `penpath.core.order_pens_for_drawing(pens)`.

A final **key layer** traces the working colour image's edges once, after paper
masking and saturation and before palette separation, and draws them on top of
the colour layers in one black layer. It is on by default in palette mode (more
than one pen) and off for a single pen; `--key-layer` forces it on and
`--no-key-layer` forces it off in either mode. The strokes reuse the already
tuned edge settings of the `outline` saved look through the library function
`penpath.core.key_layer_strokes(image)`, which returns deterministic strokes in
image pixel coordinates. In palette mode the key strokes join the palette's
near-black pen (relative luminance `<= 0.02`), which drawing order places last,
so colour-black strokes and key edges share one final layer. If the palette has
no black pen, penpath appends `Pen(name="key", color="#000000")` at the smallest
palette pen width as the last pen; a single pen with `--key-layer` gets that
extra layer too. The key pass does not change the Sketch Lines, `outline` style
or any other PFM.

#### Output Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--output PATH` | `-o` | — | Output SVG path, equivalent to the `OUTPUT_PATH` argument |
| `--no-vpype` | — | `false` | Skip vpype optimization (use direct SVG export) |
| `--vpype-path PATH` | — | `vpype` | Path to vpype executable |

`OUTPUT_PATH` and `-o/--output` name the same file; if both are given and differ,
exit 2 names both paths. A command-line output overrides `output.path` in a
`--project` file.

#### Reporting Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--quiet` | `-q` | `false` | Suppress progress, the working-resolution line and the final summary on stderr. Errors are still printed. |

#### Progress output

All `convert` messages go to stderr; stdout stays empty in every case. On a
terminal a live `rich` progress bar shows stage, percentage and elapsed time.
When stderr is redirected, each finished stage becomes one flushed plain line:

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

The downscale stage appears only when downscaling happens; masking adds a
`[n/N] Masking paper background...` stage and a `Paper colour: #...... (local
method); masked N% of pixels as no ink` line, and the key layer adds a
`[n/N] Tracing key edges...` stage. The working-resolution line is on stderr
too. `--quiet` removes all of it, including "SVG saved to"; errors remain and
the SVG is still written.

#### Optional: vpype

The `vpype` extra is installed with:

```bash
pip install "penpath[vpype]"
```

Plain `pip install vpype` works too. Without it the run prints
`vpype not found, falling back to direct SVG export (install it with: pip install "penpath[vpype]")`;
penpath's own simplify → merge → sort still runs but vpype's extra
`linemerge → linesimplify → reloop → linesort` pass does not. `--no-vpype`
skips it on purpose; penpath writes the final SVG on both paths. Each used pen
gets an Inkscape layer `id="layerN"` with the pen name as `inkscape:label`, and
the page uses millimetres. No background rect is written, so `vpype read` sees
only pen strokes; paper colour is a preview/evaluate option (`--paper-color`,
default `#FFFFFF`). Do not feed the SVG back to `vpype read`: vpype takes the
layer number from digits in the label, so `stabilo_88_red` and
`stabilo_88_green` would merge.

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

`-s KEY=VALUE` (short `-s`) sets any field of the selected PFM, including the
default `sketch_lines`. It is repeatable and wins over a preset, a saved look
and a project file. Booleans accept `true`/`false`, `1`/`0`, `yes`/`no` and
`on`/`off`; tuple fields such as `angle_range` take comma-separated values. An
unknown key, a bad value or an out-of-range number exits 2 naming the setting.
Paired limits are validated too: `min_length <= max_length`,
`erase_min <= erase_max`, `erase_radius_min <= erase_radius_max`,
`squiggle_min_length <= squiggle_max_length`, `min_velocity <= max_velocity`,
`min_frequency <= max_frequency`, `min_patch_size <= patch_size`, and Hatch's
`join_runs=true` requires `serpentine=true`.

The live list is in the CLI, so settings tables are not duplicated here:

```bash
penpath info pfms               # every PFM, its description and preset ids
penpath info pfm sketch_lines   # one PFM's fields, defaults and help
```

`penpath info pfms --format json` and `penpath info pfm NAME --format json`
give the same data for scripts. Every field of every PFM is reported there,
with its default and a one-paragraph help text; a field only belongs in this
document if `penpath info pfm NAME` does not report it.

**Example**: `penpath convert photo.jpg -s line_density=0.5 -s shading_enabled=true -s seed=42`

#### PFM Presets (`--pfm NAME`)

`--pfm` accepts a registered algorithm name (`sketch_lines`, `sketch_squares`,
`contour`, `stipple`, `spiral_sawtooth`, `hatch`, `squiggle`, `engraving`, `tsp`,
`patch_hatch`), a legacy bare preset name, or a qualified `PFM:PRESET` id. A
preset supplies a bundle of that PFM's settings and `-s` overrides individual
values on top.

Run `penpath info pfms` for the complete, canonical list of preset ids — every
id is listed there, along with a one-line description of its PFM. Running
`--pfm NAME` with no preset uses that algorithm's defaults. Bare names are the
legacy Sketch Lines, Contour and Stipple preset names (`fine` still means
`sketch_lines:fine`); a bare name that exists only for another PFM is rejected
with the qualified id in the message. `-s` wins over the preset's value, and
an invalid key or value exits 2 naming the setting.

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
| `equalize` | (none) | Global histogram equalisation of the luminance (colour kept) |
| `clahe` | `clip_limit=float (0,1]`, `tiles=int 2-64` | Local contrast equalisation (CLAHE): evens out contrast region by region; defaults 0.01 and 8 |

**Example**: `-f grayscale -f "threshold:level=128,dither=floyd_steinberg" -f "gaussian_blur:radius=1.5"`

#### Examples

```bash
# Basic usage; name the output positionally or with -o
penpath convert photo.jpg
penpath convert photo.jpg plot.svg

# Filters and -s overrides together, reproducible with a fixed seed
penpath convert photo.jpg -o art.svg -f grayscale -f "posterize:levels=6,dither=floyd_steinberg" \
  -s line_density=0.4 -s shading_enabled=true -s seed=12345 --pen fine --paper a4

# Other PFMs: structured grid, continuous spiral, measured hatch, patch hatch
penpath convert photo.jpg -o grid.svg --pfm sketch_squares:crosshatch-grid -s seed=42
penpath convert photo.jpg -o spiral.svg --pfm spiral_sawtooth -s seed=42
penpath convert photo.jpg -o crosshatch.svg --pfm hatch:crosshatch -s seed=42
penpath convert photo.jpg -o patches.svg --pfm patch_hatch -s seed=42

# Saved looks: sketch (the default), hatch, outline
penpath convert photo.jpg --style outline -o outline.svg

# Project file
penpath convert --project my_project.yaml

# Built-in palette or inline list (list order assigns colours; drawing is light → dark)
penpath convert photo.jpg --palette stabilo_88
penpath convert photo.jpg --palette "red=0.4,#E4002B;blue=0.4,#1B4C9E"

# Paper fit, margin forms, and --dpi which sizes only --fit none
penpath convert photo.jpg -o fit.svg --paper 190x190 --fit fit
penpath convert photo.jpg -o fill.svg --paper 190x190 --fit fill
penpath convert photo.jpg -o none.svg --paper 190x190 --fit none --dpi 300
penpath convert photo.jpg -o sides.svg --paper 190x190 --margin 20,5,20,5

# Background masking, original tones, working resolution, direct SVG export
penpath convert photo.jpg --palette stabilo_88 --background-method global --background-threshold 5
penpath convert photo.jpg --no-auto-equalize
penpath convert photo.jpg --max-resolution 800
penpath convert photo.jpg --no-downscale
penpath convert photo.jpg --no-vpype

# stdout stays empty: collect progress in a log, or silence stderr
penpath convert photo.jpg 2>convert.log
penpath convert photo.jpg --quiet

# Batch processing
for img in photos/*.jpg; do
  penpath convert "$img" -o "output/$(basename "$img" .jpg).svg" --project batch.yaml
done

# Debug the pipeline stages
penpath info image photo.jpg
penpath convert photo.jpg -f grayscale -f posterize --no-vpype -o debug.svg
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
| `--dpi FLOAT` | — | `101.6` | Resolution in **real dots per inch**, converted with `/25.4` |
| `--px-per-mm FLOAT` | — | `4.0` | Resolution in **pixels per millimetre** |
| `--force` | — | `false` | Render even if the raster exceeds 40 MP (bypasses only the pixel budget) |
| `--paper-color COLOR` | — | `#FFFFFF` | Paper background colour (hex or named CSS colour) |
| `--layer LABEL` | — | all | Only preview this pen layer (layer label or id; for G-code, the pen name; bed and page outlines stay visible) |
| `--travel/--no-travel` | — | `false` | Draw pen-up travel moves as thin light lines |

`--dpi` and `--px-per-mm` are mutually exclusive (exit 2), each finite and
greater than zero, including with `--force`; 4 px/mm is about 101 DPI. The 40 MP
budget is checked before allocation, so an over-limit request writes no file:

```
Error: Render too large: renders 148000x210000 px (31080.0 MP), above the 40 MP limit. Lower --px-per-mm (or --dpi) or pass --force.
```

`--force` skips only that check. An SVG page size comes from `width`/`height` or
`viewBox` (else A4); G-code with a known profile uses the bed and draws thin grey
bed and page outlines under the ink. All messages go to stderr.

#### Previewing G-code

A `.gcode` file is interpreted for `G0`/`G1`, `Z` and `F`; everything else is
ignored and **arcs (`G2`/`G3`) fail with a clear error**. The header carries the
profile, `page=WIDTHxHEIGHT` (three decimals), `place=<name>`, `page_origin=XxY`
and Z heights; a pen at or below `z_touch` draws (or `z_down` when no touch is
declared). A file without a header uses its lowest Z as "down".

With an installed profile the canvas is the bed in pen space, Y drawn downwards;
the header's `page_origin` places the page (older headers fall back to
`page_origin_mm()`). Strokes are inverted from nozzle to page space with that
origin, pen offset and `bed.invert_y`, so ink matches the reviewed SVG even when
the page is smaller than the bed or uses `reachable_corner`. Thin grey bed and
page outlines (0.2 mm, `#A0A0A0`) are always drawn under the ink and are not
filtered by `--layer`; without a usable profile the canvas stays page-sized.

Layers use their pen's width and colour from the built-in presets; an unknown pen
renders black at 0.3 mm. A `penpath gcode --frame` rectangle is ink, so it shows
in the preview; its `; frame pen=NAME` comment lets `--layer NAME` select it even
when its pen differs from the drawing's.

#### Showing pen-up travel

`--travel` adds thin light grey (0.1 mm, `#C8C8C8`) pen-up moves: for an SVG the
gaps between consecutive strokes, for G-code the gaps between drawn strokes.
Both use the two-point rule with a 0.01 mm gap threshold from
`penpath.core.svg_parse.parse_svg_strokes(..., include_pen_up=True)`. Travel is
drawn under the ink. `--no-travel` (default) is byte-for-byte the old PNG;
`--travel` also works with `--layer`.

#### Examples

```bash
penpath preview plot.svg -o preview.png
penpath preview plot.svg -o preview.png --px-per-mm 20 --paper-color "#F5F5DC"
penpath preview plot.svg -o fine.png --layer fine
penpath preview plot.svg -o travel.png --travel

# Inspect a preset before plotting, then check G-code against the reviewed SVG
penpath convert santa.jpg -o santa_grid.svg --pfm sketch_squares:crosshatch-grid -s seed=42 --max-resolution 384 --no-vpype
penpath preview santa_grid.svg -o santa_grid.png --px-per-mm 4
penpath gcode card.svg --profile generic -o card.gcode
penpath preview card.gcode -o card.png
penpath preview card.gcode -o red.png --layer stabilo_88_red
```

---

### `penpath compare` — Compare PFM styles on one contact sheet

Draw every registered PFM and preset on one labelled-tile contact sheet so you
can pick a look before plotting. Thin CLI over
`penpath.core.render_contact_sheet()`: the image is downsampled, equalized and
simulated on 60 mm tiles; no SVG or G-code is written.

```bash
penpath compare INPUT -o OUTPUT [OPTIONS]
```

#### Arguments

| Argument | Description |
|----------|-------------|
| `INPUT` | Raster image (PNG, JPEG, TIFF or BMP) loaded with EXIF orientation |

#### Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--output PATH` | `-o` | — | Output sheet path (required, PNG) |
| `--dpi FLOAT` | — | `4.0` | Pixels per millimetre for tiles and captions |
| `--max-resolution INT` | — | `256` | Longest working-image side in pixels; larger images are downscaled, never enlarged |
| `--columns INT` | — | `4` | Tiles per row |
| `--paper-color COLOR` | — | `#FFFFFF` | Tile paper colour (hex or named CSS colour) |

`--dpi`, `--max-resolution` and `--columns` must be greater than zero (exit 2
otherwise, naming the flag); an unreadable image or empty catalog is exit 1.
There is no per-tile timeout: use the shell's `timeout` and keep
`--max-resolution` / `--dpi` small for a quick pass.

#### Entry list and dedupe

One tile per PFM and per preset of that PFM, sorted by `(pfm, preset)`; a preset
named `default` is skipped as the PFM default covers `sketch_lines:default`. The
catalog has 23 tiles. A failing entry shows `Type: message` instead of ink.

#### Output and stderr contract

**stdout is always empty.** stderr has one `Failed entry LABEL: Type: message`
line per failure, then the path, pixel size and entry count; a failed tile still
exits 0 so one PFM cannot hide the other styles:

```
Contact sheet saved to sheet.png (1008x2156 px, 23 entries)
```

#### Examples

```bash
penpath compare photo.jpg -o sheet.png
penpath compare photo.jpg -o quick.png --dpi 2 --max-resolution 64 --columns 3
penpath compare photo.jpg -o cream.png --paper-color "#FFFDD0"
# Bound a full run with the shell; stdout stays empty either way
timeout 180 penpath compare santa.jpg -o sheet.png --dpi 4 --max-resolution 256
```

---

### `penpath gcode` — SVG → G-code for a machine

Turn a reviewed SVG into machine G-code using a machine profile. `--profile` is
required — penpath never guesses the machine.

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
| `--place NAME` | — | profile placement | Put the page at `center`, `front-right`, `front-left`, `back-right`, `back-left` or `origin`; mutually exclusive with `--at` |
| `--at X,Y` | — | — | Put the page lower-left at pen-space bed millimetres, e.g. `20,10`; mutually exclusive with `--place` |
| `--dry-run` | — | `false` | Write G-code to stdout; send every message to stderr |
| `--fit/--no-fit` | — | `--fit` | Fit a page or drawing past the usable area into it (default), with a warning on stderr; `--no-fit` keeps the strict error |
| `--frame` | — | `false` | Plot one closed rectangle around the page before the drawing |
| `--frame-margin MM` | — | `2` | Distance in mm from the page edge to the frame; `0` is the page edge. Needs `--frame` |
| `--frame-pen NAME` | — | first layer's pen | Pen name for the frame. Needs `--frame` |
| `--frame-pause` | — | `false` | Pause with `M0` after the frame to check the paper. Needs `--frame` |

Each Inkscape pen layer (`<g inkscape:groupmode="layer">`) becomes a G-code
layer in document order (the pens' drawing order); strokes in a layer are
nearest-neighbour sorted and empty layers are skipped. One pen-change block is
emitted before each used layer per `pen_change.mode`: `between` skips the first,
`each` covers every layer, `none` never changes. Pen name and layer/pen indices
are available through the placeholders below.

`--profiles PATH` replaces the default user file for one run and overrides a
built-in of the same name; see **Machine Profile Format** below. `--dry-run`
puts only G-code on stdout (no file is written) and every message on stderr;
otherwise stdout stays empty. `--margin MM` replaces the profile's safety
margin for this run before fitting; the header reports the overridden usable
area so `penpath preview` renders the same placement. The profile file is
never changed.

#### Placing the page on the bed

`--place NAME` puts the page at a named spot in the machine's usable area:
`center`, `front-right`, `front-left`, `back-right`, `back-left` or `origin`.
`--at X,Y` instead puts the page's lower-left corner at an exact pen-space bed
coordinate in millimetres. The two flags are mutually exclusive: giving both is
a usage error (exit 2) that names both, and a malformed `--at` value is also a
usage error (exit 2).

With neither flag the default is the profile's `bed.page.placement`:
`front-right` on the Aquila, `origin` on `generic` and `ramped`. A page that
does not fit is shifted the shortest way into the area with one stderr warning;
`--no-fit` instead makes it an exit-3 error naming the origin, valid range and
fix, and writes no file. A page shift can be followed by a drawing-fit warning.
Every successful run prints these two stderr lines, also under `--dry-run`:

```
Page placed at 33.650, 59.200 (bed 220x220)
Drawing placed at X 13.512..187.300, Y 10.000..181.400 mm
```

The second line is the pen-space bounding box of the emitted drawing at three
decimals, after fitting and excluding the frame. The stderr summary reports
layers, drawing length, pen-up travel and pen lifts measured from the emitted
(post-fit) strokes, plus an estimated time from the profile's feeds.

The first G-code line is a `penpath preview` header carrying the profile, page
size, placement, page origin, usable bounds and Z heights, e.g.
`; penpath gcode profile=aquila page=170.000x170.000 place=front-right page_origin=17.300x10.000 usable_x=10.000..187.300 usable_y=10.000..181.400 z_up=12.500 ...`.

#### Fitting an oversized page

By default a page past the usable area is fitted, not refused:
`penpath.core.fit_layers_to_drawable` reserves the per-side margin and ramp
lead-in, then shifts the drawing the shortest way that fits and scales it down
only if it is larger than the area. One stderr warning names the overshoot,
scale and shift:

```
Warning: drawing is 0.881 mm past the aquila usable area; fitted with scale 1.000 and shift (-0.881, 0.000) mm
```

The overshoot includes the ramp lead-in. Overruns of `FIT_TOLERANCE_MM = 0.05`
mm or less are float rounding and leave the drawing untouched. The warning is
never on stdout, and no file is written unless the whole document was built.

Pass `--no-fit` to keep the strict check: a point outside the usable area (the
drawable area minus `bed.margin_mm`) then fails with exit 3, naming its
coordinates, the per-axis overshoot and the fix:

```
Error: point (x=187.431, y=170.000) mm is outside the usable area X 10.000..187.300, Y 10.000..181.400 mm (drawable area minus a 10.000 mm margin); overshoot x=0.131 mm, y=0.000 mm Pass --fit (the default) or use a smaller --paper.
```

#### Drawing a frame first

`--frame` plots one closed rectangle before the drawing so paper position can
be checked. `penpath.core.frame_polyline` expands the page box by
`--frame-margin` on all sides, from `(-m, -m)` to `(W + m, H + m)`; `0` puts it
on the page edge. The rectangle starts 2 mm along its closing edge and returns
to that corner (the overlap is clamped to the shorter side).

Emission order: header/start block, the first layer's pen-change block when
`mode: each`, the frame with the same ramp and Z heights, then
`M0 Frame drawn: check paper position, press knob to plot` if `--frame-pause`
was given, then the real layers. No `M25` is emitted. By default the frame uses
the first used pen with no extra change; `--frame-pen NAME` picks another, and
`pen_change.mode` decides the changes (`each` changes before the frame and
before layer 1; `between` and `none` leave mounting to the operator). The
summary counts the frame's cost but **Layers** stays the number of real SVG
layers.

The page plus frame margin plus ramp lead-in must fit the usable area: `--fit`
shifts or scales frame and drawing together under one warning starting
`Warning: drawing and frame are ...`, while `--no-fit` makes a frame point past
the area an exit-3 error. The frame is ink, so `penpath preview card.gcode`
shows it and `--layer <frame pen>` filters to it; `convert` does not draw it.

#### Ramped landing

With `pen.ramp_mm`, `z_touch` and `z_hover`, each stroke gains a lead-in of
`lead_in_mm = ramp_mm * (z_hover - z_touch) / (z_touch - z_down)` and an equal
lead-out. Z falls from `z_hover` to `z_down` over `lead_in_mm + ramp_mm` and
rises the same way, so the pen lands and lifts **while moving** with no ink dot
at the start. The lead-in/out are above the paper and are not inked in previews
(the simulator clips at `z_touch`), so the PNG still matches the reviewed SVG.
G-code uses nozzle coordinates (`nozzle = pen - bed.pen_offset_mm`) and every
emitted point, lead-in/out included, is checked against the usable area.
Without `ramp_mm` the plain travel → down → draw → up stroke is unchanged.
`z_touch` must be above `z_down` and `z_hover` not below `z_touch`.

Exit codes: **2** for a missing/unknown `--profile` (message lists available
profiles), both `--place` and `--at`, a bad `--at`, a negative `--frame-margin`,
or a frame option without `--frame`; **3** for a bad profile file, a page or
drawing that cannot be fitted, or (with `--no-fit`) a point outside the usable
area; 1 for other file errors.

#### Examples

```bash
penpath gcode card.svg --profile generic -o card.gcode   # default: card.gcode
penpath gcode card.svg --profile generic --dry-run > card.gcode
penpath gcode card.svg --profile my_plotter --profiles ./profiles.yaml

# Aquila: page against the usable corner, ramped landings, touch-spot changes
penpath gcode card.svg --profile aquila -o card.gcode
penpath gcode card.svg --profile aquila --no-fit          # strict exit-3 error

# Place the page by name or exact lower-left corner
penpath gcode card.svg --profile aquila --place center -o centred.gcode
penpath gcode card.svg --profile aquila --at 20,20 -o corner.gcode

# Check the paper first: a 2 mm frame and pause, with another pen on the edge
penpath gcode card.svg --profile aquila --place center --frame --frame-pause -o card.gcode
penpath preview card.gcode -o framed.png
penpath gcode card.svg --profile aquila --place center --frame --frame-pen stabilo_88_red \
  --frame-margin 0 -o red_frame.gcode
```

The complete operator workflow and checklist for the Aquila, with the
reference-versus-penpath equivalence check, are in
[docs/AQUILA.md](AQUILA.md).

---

### `penpath evaluate` — Score likeness and machine cost

Simulate the SVG at the chosen resolution, crop it to the recorded image
placement and compare with the original. `likeness` is greyscale SSIM over the
whole page (a near-blank plot can score well on a mostly-white source);
`masked_likeness` averages SSIM over the source's ink pixels only, so a blank
plot cannot cheat by agreeing with paper; `edge_likeness` compares Sobel
gradients. All three use the same 256x256 crop and blur sigma 1.5. Machine cost
(drawing length, pen-up travel, pen lifts, short segments, stroke count) and ink
coverage are reported per pen layer and in total; coverage is the share of the
whole page inked by pen-down strokes, so per-layer shares may overlap.

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
| `--dpi FLOAT` | — | `96` | Resolution in **real dots per inch**, converted with `/25.4` |
| `--px-per-mm FLOAT` | — | `96/25.4` | Resolution in **pixels per millimetre**, shared by simulation and likeness |
| `--force` | — | `false` | Evaluate even if the simulation exceeds 40 MP (bypasses only the pixel budget) |
| `--paper-color COLOR` | — | `#FFFFFF` | Paper background colour |
| `--layer LABEL` | — | all | Only evaluate this pen layer |
| `--coverage-warn PCT` | — | `50` | Warn on stderr when a layer covers more than this percentage of the page; `0` disables the warning; value must be `>= 0` |

`--dpi` and `--px-per-mm` are mutually exclusive (exit 2 naming both); each
must be finite and greater than zero, including with `--force`. The default 96
DPI equals 96/25.4 px/mm. The 40 MP budget is checked before any allocation, so
an over-limit request writes no JSON and reports:

```
Error: Render too large: renders 148000x210000 px (31080.0 MP), above the 40 MP limit. Lower --px-per-mm (or --dpi) or pass --force.
```

`--force` skips only that check. SVGs without placement metadata are fitted to
the page keeping their aspect ratio, as in
`penpath.core.svg_parse.get_image_placement`.

In the human table, `Layer` is the stroke hex and `Pen` the Inkscape layer name
(`inkscape:label`, or its id); a colour with no layer shows its hex, and
`TOTAL` has no pen. A layer above `--coverage-warn` adds one stderr warning
naming it and suggesting `--background-threshold` and `--saturation`; it
changes neither exit code nor result and also appears in `--json` mode.

With `--json`, stdout contains only a single object (safe to pipe to `jq`):

```json
{
  "likeness": 0.82,
  "masked_likeness": 0.41,
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

The human table shows `SSIM (whole page)`, `SSIM (ink only)` and `Edge SSIM`.
The ink-only mask uses pixels over 10.0 CIE76 Lab units from the source paper
colour at 256x256 (`penpath.core.background_mask`), using the source paper even
when `--paper-color` changes the plot; a source with no ink scores 0.0. Edge SSIM
normalises both maps by one shared maximum, and is 1.0 when both are zero.
These two scores are diagnostics, not pass/fail gates.

`penpath.core.svg_parse.get_layer_pen_names` maps a normalised `#RRGGBB` colour
to the first Inkscape layer using it, falling back to the hex.

#### Examples

```bash
penpath evaluate photo.jpg plot.svg
penpath evaluate photo.jpg plot.svg --json | jq '.likeness, .masked_likeness, .edge_likeness'
penpath evaluate photo.jpg plot.svg --px-per-mm 5 --layer fine
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
| `pfms` | List registered PFMs with a one-line description and their canonical preset ids |
| `pfm NAME` | Show one registered PFM's description, preset ids, settings, defaults and help |
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

Every `info` subcommand writes stdout: a rich table by default (colours off on
non-TTY) or one document with `--format json` / `--format yaml`. `info profiles
--format json` gives a `profiles` array with `name`, `source`, `description`,
`bed_width_mm`, `bed_height_mm`, `margin_mm`, `travel_mm_s`, `draw_mm_s` and
`z_mm_s` (Z falls back to travel). `margin_mm` is the raw scalar or
`[top, right, bottom, left]` list; the table shows `10` or `10/5/10/5`.

`penpath info palettes` gives each palette's pens an `order` column in drawing
order (light first, near-black last) from `penpath.core.order_pens_for_drawing`;
definition order still governs separation.

`penpath info pfms` prints one row per PFM with **Name**, **Description** and
**Preset ids** (canonical `PFM:PRESET` ids); settings are in `info pfm NAME`.

`--format json` / `yaml` keep the script-facing keys: an `available_pfms` array
with `name`, `description`, `settings_model`, `default_settings`, `presets` and
`preset_ids`, plus top-level `presets` and `preset_ids`, all canonical qualified
ids. This is the source of truth for `--pfm`:

```bash
penpath info pfms --format json | python -c 'import json,sys; print([p["name"] for p in json.load(sys.stdin)["available_pfms"]])'
```

#### `penpath info pfm NAME`

```bash
penpath info pfm NAME [OPTIONS]
```

`NAME` is a registered PFM name such as `sketch_lines`, **not** a preset id. The
table shows the description, canonical preset ids and every settings field with
**Setting**, **Default** (`None` for null, `-` for required) and **Help** (from
the settings model). An unknown name is a click error listing the available
PFMs.

`--format json` and `--format yaml` return one object with `name`,
`description`, `presets` (canonical ids) and a `settings` array whose rows have
`name`, `default` and `help`.

```bash
penpath info pfm sketch_lines
penpath info pfm contour --format json
```

#### `penpath info palette-match`

```bash
penpath info palette-match IMAGE_PATH [OPTIONS]
```

Measures the **raw, pre-drawing** colour separation: the same `separate_palette`
as `convert`, counting pixels each pen's layer inks (below 255). No filters,
masking, equalization or saturation is applied and nothing is drawn. Regions
under 8 px are dropped by separation and count as unassigned with paper pixels.
Percentages are of all image pixels; unused pens are kept at zero.

| Option | Default | Description |
|--------|---------|-------------|
| `--palette NAME\|LIST` | `stabilo_88` | Built-in palette name or inline `name=width,#hex;...` (same parser as `convert --palette`) |
| `--format json\|yaml\|table` | `table` | Output format; table columns are Order, Pen name, Colour, Pixels, Percent and end with an unassigned row |

JSON and YAML contain `path`, `palette`, `width`, `height`, `rows` (`order`,
`name`, `color`, `pixels`, full-precision `percent`) in drawing order, plus
`unassigned_pixels` and `unassigned_percent`; table percentages are rounded to
one decimal. An invalid palette is exit 2, an unreadable image exit 1.

#### Examples

```bash
penpath info pens
penpath info palettes
penpath info pfms
penpath info pfms --format json
penpath info pfm sketch_lines
penpath info profiles
penpath info filters
penpath info image photo.jpg
penpath info palette-match photo.jpg
penpath info palette-match photo.jpg --palette "red=0.4,#FF0000;blue=0.4,#0000FF"
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

style: hatch                 # saved look: sketch, hatch or outline (optional)

input:
  path: "photo.jpg"
  auto_orient: true
  auto_equalize: true   # linear levels normalization before drawing (default)
  background: true             # mask paper before separation (palette default)
  background_threshold: 10.0   # CIE Lab ΔE treated as paper
  background_method: local     # local paper field, or global single colour
  key_layer: null              # final black edge layer (palette on, single pen off)
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
# Or an explicit ordered list of pens (colour assignment; drawing is light → dark):
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
  # width_mm: 210
  # height_mm: 297
  # margin_mm: 10
  # or four per-side margins in [top, right, bottom, left] order:
  # margin_mm: [10, 20, 10, 20]
  # fit: fit                   # fit, fill or none (default: fit)

output:
  path: "plot.svg"
  vpype: true
```

`pen:`, `palette:` and `pens:` are mutually exclusive (a file setting more than
one fails to load). `save_yaml` writes a built-in palette as `palette:` and an
explicit list as `pens:`. `image.auto_equalize` defaults to `true`, so older
YAML loads with normalization on; set it to `false` for original tones, or use
`--auto-equalize` / `--no-auto-equalize` for one run.

Background keys under `image:`: `background: true|false` forces masking,
`background_threshold: 10.0` sets the Lab cut-off and
`background_method: local|global` chooses the estimate. Leaving `background`
out follows the mode (on for `palette:`/`pens:`, off for a single `pen:`); old
files load as `local`, and an unset `background` is omitted by `save_yaml`.
The four `--background*` flags override the file for one run and
`--no-background` wins.

`image.key_layer` is tri-state: `true`/`false` force the final black edge layer
on/off, while `null` (or omitted) follows the mode (palette on, single pen off).
Old files load as `null`; `save_yaml` writes `key_layer: true|false|null`.
`--key-layer` / `--no-key-layer` override it for one run.

Paper keys are `width_mm`, `height_mm`, `margin_mm` and `fit`: a scalar margin
covers all sides, a four-item list is `[top, right, bottom, left]`, and `fit`
is `fit`/`fill`/`none` (default `fit`). `--paper`, `--margin` and `--fit`
override them, with `--margin` winning over margins in `--paper`.

`style: sketch|hatch|outline` is optional; an old file without it runs the
default path. Its values are resolved into `pfm.settings`, so saved `pfm:`
settings win on load and an `outline` look still adds the edge pass. `--style`
replaces the file's look and settings for that run, and `-s` overrides
individual keys.

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

The chroma keys are under `image:` too: `saturation: 2.0` is a manual multiplier
in [0, 3] (default `1.0`), and `palette_adapt: true` chooses it from the image
and palette. Old files load as `1.0`/`false` unchanged. `--saturation` overrides
the file and disables adaptation; `--palette-adapt` overrides the manual factor.
Both are no-ops for a single pen.

The `pfm` block selects the algorithm by `pfm_type`; the `settings` shape is
that algorithm's settings model. Sketch Squares round-trips as:

```yaml
pfm:
  pfm_type: sketch_squares
  settings:
    grid_angle: 0.0
    line_density: 0.75
    seed: 42
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

## Machine Profile Format

A machine profile in `profiles.yaml` holds every value `penpath gcode` needs to drive a plotter:
bed geometry, feed rates, pen heights, verbatim G-code blocks and pen-change
steps. Machine values live in the profile, never in penpath's code. Paper size,
pen colours and pen widths stay in the reviewed SVG.

### Where profiles live

- **Built-in**: one YAML file per machine in `src/penpath/presets/profiles/`;
  the profile name is the file name. `generic` (plain Z-lifted plotter) and
  `aquila` (pen offset, ramped landing, touch-spot pen change) ship today.
- **User**: `$XDG_CONFIG_HOME/penpath/profiles.yaml`, or
  `~/.config/penpath/profiles.yaml` when `XDG_CONFIG_HOME` is unset. One file
  holds several machines as a mapping; a user profile **overrides** a built-in
  of the same name.

`penpath info profiles` lists both with their source, description, bed size and
feeds; `penpath gcode` reads them through `--profile` and `--profiles`. Editing
profiles is done by hand.

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

To use it in a user file, indent the block under `my_plotter:`; `name:` must
match. Unknown keys are rejected. `version` must be `1`; `name` must be omitted
or match the file/mapping key. Required sections are `bed` (with `size_mm`),
`feed` (`travel_mm_s`, `draw_mm_s`) and `pen` (`z_up`, `z_down`); the rest is
optional. `generic.yaml` is a smaller, complete profile.

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

There are **no coordinate placeholders**: code blocks are verbatim machine-space
G-code, so coordinates are literal numbers. Penpath-managed coordinates come
from the profile's pen-space fields.

### Coordinates: pen space vs machine space

- **SVG page**: millimetres, origin top-left, Y down.
- **Pen space**: millimetres, bed front-left origin, X right and Y towards the
  back. `bed.page.origin_mm` and `pen.touch_xy_mm` are pen space.
- **Machine space**: nozzle coordinates used by G-code, with
  `nozzle = pen - bed.pen_offset_mm`; coordinates in verbatim `gcode` blocks
  are already machine space.

With `placement: fixed`, the page's bottom-left corner sits at
`bed.page.origin_mm`. With `placement: reachable_corner`, the page's
bottom-right corner sits at the usable area's front-right corner
(`x = usable_x_max - page_width`, `y = usable_y_min`). Stroke points map as:

```
X_pen = page_origin_x + x_svg
Y_pen = page_origin_y + page_height - y_svg   # invert_y: true
Y_pen = page_origin_y + y_svg                 # invert_y: false
```

In the example, offset `[-22.7, -28.6]` on a 220 x 220 mm bed gives a drawable
area X 0..197.3, Y 0..191.4 mm. Aquila's `bed.margin_mm: 10` makes its usable
area X 10..187.3, Y 10..181.4 mm, so a 170 x 170 mm page lands at pen
(17.3, 10.0); its touch spot (190, 12) is in the margin and is not checked.
Coordinates use three decimals; a point outside the usable area fails the run.

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

**Inline Format**: `WIDTH[,COLOR[,TYPE]]` (`0.4`, `0.4,#FF6600`,
`0.4,#000000,fineliner`). Colour defaults to `#000000`, type to `rollerball`;
types are `ballpoint`, `fineliner`, `fountain`, `brush`, `marker`, `rollerball`,
`gel`. See **Pens (`--pen`)**.

---

## Palette Presets (Built-in)

| Name | Pens | Width | Drawing order |
|------|------|-------|---------------|
| `stabilo_88` | 12 Stabilo Point 88 colours | 0.4 mm | light → dark, black last, as listed by `penpath info palettes` |

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

**Inline Format**: `WIDTHxHEIGHT[,MARGINS]` — one margin, e.g. `210x297,10`, or
four in top,right,bottom,left order, e.g. `300x200,15,10,15,10`.

**Project files** accept a scalar `paper.margin_mm` or `[top, right, bottom,
left]`, both round-tripping through `save_yaml`. The drawable area insets each
side and starts at `(left, top)`. `--margin` overrides for one run, `--fit
fit|fill|none` places the image (default `fit`), and `--dpi` sizes only `--fit
none`. A margin leaving no drawable area is a usage error.

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

