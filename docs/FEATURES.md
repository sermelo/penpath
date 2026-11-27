# penpath Feature Proposal

**Status**: For board decision (MVP / planned / later / out)  
**Reference**: DrawingBotV3 v1.6.25-stable-free (read-only)  
**Goal**: Smallest CLI that turns a photo into a good, plottable SVG

---

## Feature Table

| # | Feature | User value | Settings | Source (DrawingBotV3) | Size | Dependencies | Decision |
|---|---------|------------|----------|----------------------|------|--------------|----------|
| **Input** |||||||
| 1 | Load raster image (PNG, JPG, TIFF, BMP) | Starting point for all workflows | Path, auto-orient (EXIF) | `files/loaders/ImageFileLoader.java` | S | Pillow / imageio | **MVP** |
| 2 | Load SVG as reference layer | Trace over existing vector art | Path, scale, opacity | `files/loaders/` (partial) | M | svgpathtools | **later** |
| 3 | Batch input directory | Process many images at once | Glob pattern, output dir template | New | S | stdlib | **later** |
| **Image Filters** |||||||
| 4 | Grayscale / luminance extraction | Convert to single channel for drawing | Method (luminance, lightness, average, R/G/B) | `image/PixelData*.java` | S | Pillow / OpenCV | **MVP** |
| 5 | Threshold / posterize | Reduce to N tones for multi-pen | Levels (2–256), dither (none, Floyd-Steinberg, ordered) | `image/filters/ThresholdFilter.java`, `PosterizeFilter` | S | Pillow / OpenCV | **MVP** |
| 6 | Blur (Gaussian, Box) | Remove noise, soften detail | Radius, sigma | `image/filters/GaussianFilter.java`, `BoxBlurFilter.java` | S | Pillow / OpenCV | **MVP** |
| 7 | Contrast / brightness / gamma | Adjust tonal range before drawing | Contrast, brightness, gamma | `image/filters/HSBAdjustFilter.java` (partial) | S | Pillow / OpenCV | **MVP** |
| 8 | Invert | Negative image for light-on-dark | — | `image/filters/InvertFilter.java` | XS | Pillow | **MVP** |
| 9 | Crop / resize / rotate | Frame and scale to paper | Box, target DPI, fit mode (contain/cover/stretch) | `image/format/ImageCropping.java` | S | Pillow | **MVP** |
| 10 | Edge detect (Canny, Sobel) | Extract contours for outline styles | Method, thresholds, sigma | `image/filters/*Edge*.java` | M | OpenCV | **later** |
| 11 | Stylize filters (oil, emboss, stamp, halftone) | Artistic pre-processing | Per-filter params | `image/filters/*` (STYLIZE category) | M | OpenCV / custom | **out** — not core to "photo → plottable SVG" |
| 12 | Filter pipeline / presets | Chain and save filter sequences | Ordered list, enable/disable per step | `image/ImageFilterSettings.java` | S | — | **later** |
| **Drawing Algorithms (PFMs)** |||||||
| 13 | Sketch Lines (hatching) | Versatile pen-and-ink look from photos | Line density, max fill, min/max length, angle range, shading on/off, squiggles, erasing, seed | `pfm/PFMSketchLinesBasic.java` + settings in `Register.java` | L | NumPy, custom geometry | **MVP** |
| 14 | Sketch Squares (grid hatching) | Structured, graphic look | Grid angle, line density, min/max length, max fill, seed, stroke cap | `pfm/PFMSketchSquaresBasic.java` | M | NumPy | **implemented** — LUC-137 part 2 (registry, presets, CLI and project file), part 3 previews [coarse](images/luc-137/santa_coarse.png) / [fine](images/luc-137/santa_fine.png) / [crosshatch](images/luc-137/santa_crosshatch-grid.png) and [readability + cost gate](TESTING.md#sketch-squares-readability-and-plot-cost-gate-luc-149-2026-11-27); built and merged |
| 15 | Spiral (sawtooth) | Continuous-line, single-pass plots | Spiral type (Archimedean/parabolic), centre, ring spacing, amplitude, velocity range, connected lines | `pfm/PFMSpiralBasic.java` | M | NumPy | **done** — LUC-138 ported the algorithm, registered `spiral_sawtooth` with presets and CLI support, and shipped the previews [default](images/luc-138/santa_spiral_default.png), [fine](images/luc-138/santa_spiral_fine.png), [bold](images/luc-138/santa_spiral_bold.png), [parabolic](images/luc-138/santa_spiral_parabolic.png) and the [readability + cost gate](TESTING.md#spiral-sawtooth-gate-luc-138-2026-11-27); one continuous line is proven on the free Santa portrait |
| 16 | Contour tracing (potrace-style) | Clean vector outlines from thresholded image | Turn policy, turd size, alpha max, opticurve | New (DrawingBotV3 Premium only) | L | scikit-image, Shapely | **done** — registered `contour` PFM with presets and `-s` settings (LUC-144/145); no DrawingBotV3 code ported. Previews: [portrait](images/luc-139/contour_portrait.png), [silhouette](images/luc-139/contour_silhouette.png); [readability and cost gate](TESTING.md#contour-readability-and-plot-cost-gate-luc-146-2026-11-27) |
| 17 | Stippling / pointillism | Dot-based shading | Dot density, min/max radius, jitter, seed, stroke cap | New | M | NumPy, Poisson disk | **MVP** — shipped in LUC-140; registered `stipple` PFM with three presets and `-s` settings (LUC-153/154). Previews: [default](images/luc-140/stipple_default.png), [fine](images/luc-140/stipple_fine.png), [bold](images/luc-140/stipple_bold.png); [likeness and cost gate](TESTING.md#stipple-likeness-and-plot-cost-gate-luc-154-2026-11-27) |
| 18 | Multi-pen / colour separation | CMYK, RGB, or custom palette splits | Separation mode (CMYK, RGB, threshold layers), per-layer PFM | `drawing/ColorSeparationHandler.java` (Default only in free) | L | — | **MVP** — sergio approved on 2026-11-24; the Christmas card needs it and the default path stays simple: one pen gives one layer, exactly as before |
| **Pens & Colour** |||||||
| 19 | Hatch / cross-hatch (PFM) | Engraving-style straight and woven lines | Spacing (mm), band angles and darkness thresholds, min length/gap, variable spacing, serpentine, join runs, jitter, seed | New | M | NumPy, Shapely | **implemented** — LUC-167 part 1 ported the algorithm with explicit millimetre scale arguments, part 2 registered `hatch` with four presets and `-s` settings, part 3 added the opt-in `join_runs` setting; previews [face default](images/luc-167/face_hatch_default.png) / [face crosshatch](images/luc-167/face_hatch_crosshatch.png) / [photo default](images/luc-167/photo_hatch_default.png) / [photo crosshatch](images/luc-167/photo_hatch_crosshatch.png) / [gradient](images/luc-167/gradient_hatch_default.png) / [sphere](images/luc-167/sphere_hatch_default.png) and the [acceptance gate](TESTING.md#hatch-acceptance-gate-luc-167-2026-11-27); all acceptance lines met, including 5x fewer pen lifts on `photo.jpg` |
| 20 | Pen library (width, colour, type) | Match physical pens | Width (mm), colour (hex/CMYK), type (ballpoint, fountain, brush, marker), opacity | `files/json/presets/PresetDrawingPen*.java` | S | — | **MVP** |
| 21 | Pen pressure / width variation | Expressive strokes | Min/max width, pressure curve | New (DrawingBotV3 has easing) | M | — | **later** |
| 22 | Virtual paper (size, margins, colour) | Preview composition | Paper size (A4, A3, custom), margins, background colour | `plotting/canvas/*.java` | S | — | **MVP** |
| **Line Optimisation** |||||||
| 23 | Line simplification (RDP) | Reduce points, keep shape | Tolerance (mm) | `geom/operation/GeometryOperationSimplify.java` | S | shapely / custom | **MVP** |
| 24 | Line sorting (TSP / nearest-neighbour) | Minimize pen-up travel | Algorithm (greedy, 2-opt, OR-Tools), start point | `geom/spatial/TSPSequencer*.java`, `STRTreeSequencer*.java` | M | OR-Tools / custom | **MVP** |
| 25 | Line merging / join collinear | Reduce segments | Angle tolerance, distance tolerance | `geom/operation/GeometryOperationOptimize.java` | S | shapely | **MVP** |
| 26 | vpype pipeline integration | Industry-standard optimization & export | vpype commands (linemerge, linesimplify, reloop, linesort, write) | `integrations/vpype/*.java` | M | vpype (Python) | **MVP** — use vpype CLI as backend |
| **Output** |||||||
| 27 | SVG export (layers per pen) | Standard vector format for plotters | Paper size, DPI, layer naming, inkscape:groupmode, background layer | `files/exporters/SVGExporter.java` | S | svgwrite / lxml | **MVP** |
| 28 | GCode export | Direct machine control | Pen up/down commands, feed rates, units, header/footer | `files/exporters/GCodeExporter.java` | M | — | **planned** — LUC-51 Phase 7 (machine profiles); built and merged |
| 29 | HPGL / DXF export | Legacy cutter support | — | New | M | — | **out** |
| 30 | PNG/PDF preview | Quick visual check | DPI, antialiasing, show pen-up moves | `files/exporters/ImageExporter.java`, `PDFExporter.java` | S | Cairo / reportlab | **later** |
| **Presets & Config** |||||||
| 31 | Project file (JSON/YAML) | Save/load full pipeline | All settings above | `files/json/projects/*.java` | M | pyyaml | **MVP** |
| 32 | Preset system (filters, PFM, pens, paper) | Reuse/share configurations | Name, description, tags | `files/json/presets/*.java` | M | — | **later** |
| 33 | CLI config file (TOML) | Persistent defaults | Default paper, pen, PFM, vpype path | New | XS | toml | **MVP** |

---

## PFM comparison contact sheet (LUC-141/160)

`penpath compare IMAGE -o sheet.png` draws one labelled tile per registered PFM
and preset on the same image, using the library functions
`penpath.core.render_contact_sheet()` and `penpath.presets.list_sheet_entries()`.
It is a PNG for choosing a look before plotting, not a step in the SVG → G-code
path. The [committed sheet](images/luc-141/contact_sheet.png) and the
[readability check](TESTING.md#contact-sheet-readability-luc-141-2026-11-27)
show every look on the Santa portrait.

## Library-only outline pass (LUC-129, part 2 of 3)

`penpath.core.outline_strokes(image, OutlineSettings)` extracts contour strokes
from an image before tone is applied: it detects edges with the project's
scikit-image dependency, thins them to a one-pixel skeleton, chains the pixels
into polylines, simplifies them and drops specks. The result is a
`list[shapely.LineString]` in image pixel coordinates, deterministic for a given
image and settings, with every point inside the image bounds. Settings such as
`blur_sigma`, `edge_sigma`, `low_threshold`, `high_threshold`, `close_radius`,
`min_component_pixels`, `min_length` and `simplify_tolerance` are validated by
the `OutlineSettings` Pydantic model.

```python
from penpath.core import OutlineSettings, load_image, outline_strokes

image = load_image("photo.jpg")
strokes = outline_strokes(image, OutlineSettings())
```

`penpath convert --style outline` now runs this pass before a light Sketch Lines
tone pass. `penpath.core.get_style` and `draw_styled_lines` expose the same
saved looks to library callers; `--style sketch` and no style at all keep the
Sketch Lines defaults unchanged.

---

## Decision Rationale

### MVP (18 features) — "Photo → good, plottable SVG"
| # | Feature | Why MVP |
|---|---------|---------|
| 1 | Load raster image | Absolute prerequisite |
| 4 | Grayscale | Single-channel input for drawing algos |
| 5 | Threshold | Enables multi-tone → multi-pen later; also binary for contour |
| 6 | Blur | Essential denoising for photos |
| 7 | Contrast/brightness/gamma | Photos need tonal adjustment before drawing |
| 8 | Invert | Light-on-dark workflows |
| 9 | Crop/resize/rotate | Fit to paper, set DPI |
| 13 | Sketch Lines | Most versatile free PFM; handles shading, texture, artistic control |
| 18 | Multi-pen / colour separation | sergio approved on 2026-11-24; the Christmas card needs it and the default path stays simple: one pen gives one layer, exactly as before |
| 19 | Pen library | Physical pen matching is core to plotting |
| 21 | Virtual paper | Defines output bounds |
| 22 | Line simplification | Raw PFM output is dense; RDP makes it plottable |
| 23 | Line sorting | Unsorted lines = hours of pen-up travel |
| 24 | Line merging | Collinear segments waste time |
| 25 | vpype pipeline | Battle-tested optimization + SVG export; we wrap it, not reimplement |
| 26 | SVG export | Primary deliverable format |
| 30 | Project file | Reproducibility, handoff |
| 32 | CLI config | Sensible defaults without flags every run |

**MVP Scope**: Two PFMs (Sketch Lines and Contour), one pen by default and an ordered palette for multi-pen, vpype for optimization/export, minimal but complete filter chain for photo prep.

### Later (9 features) — "Polish and versatility"
- Sketch Squares, Spiral (additional styles)
- Edge detect (outline mode)
- Filter pipeline/presets, pen pressure, preview renders, preset system
- Batch input

### Out (6 features) — "Not core, niche, or premium-only in ref"
- Stylize filters (artistic, not "photo → plottable")
- Stippling (can be approximated with Sketch Lines)
- HPGL/DXF (legacy, low demand)
- Premium PFMs (not in free reference)
- Colour splitters beyond Default (Premium in DrawingBotV3)
- Video/transition filters (irrelevant for stills)

---

## Implementation Approach for MVP Features

| Feature | Build Strategy |
|---------|----------------|
| Load image | `Pillow.Image.open()` — standard, handles EXIF |
| Grayscale / Threshold / Blur / Contrast / Invert / Crop/resize | `Pillow.ImageOps` + `ImageFilter` + `ImageEnhance` — pure Python, zero native deps beyond Pillow |
| Sketch Lines | Port logic from `PFMSketchLinesBasic.java` → Python/NumPy. Core: random-angle line search, darkest-pixel sampling, shading branch, squiggle/erase helpers. ~300 LOC. |
| Pen library | Dataclass + JSON/YAML serialization. Built-in presets for common pens (0.3mm fineliner, 0.5mm rollerball, etc.) |
| Virtual paper | Dataclass (size, margins, bg). Used for coordinate scaling and SVG viewBox. |
| Line simplification | `shapely.simplify()` (RDP) — fast, robust, C-backed. |
| Line sorting | Greedy nearest-neighbour + 2-opt pass (pure Python, no OR-Tools dep). Good enough for MVP. |
| Line merging | `shapely.ops.linemerge()` + custom collinear join. |
| vpype pipeline | Shell out to `vpype` CLI (installed separately). Input: raw geometries → `linemerge linesimplify reloop linesort write`. Keeps penpath lightweight. |
| SVG export | `svgwrite` — generate `<g id="pen-...">` layers, inkscape:groupmode, viewBox from paper. |
| Project file | Pydantic model → YAML (human-readable, diffable). Round-trip safe. |
| CLI config | `tomllib` (stdlib 3.14+) / `tomli` fallback. `~/.config/penpath/config.toml`. |

---

## Dependency Summary (MVP)

| Runtime | Purpose | Install |
|---------|---------|---------|
| Python ≥3.14 | Core | — |
| Pillow | Image I/O, filters | `pip install pillow` |
| NumPy | Sketch Lines math | `pip install numpy` |
| shapely | Geometry ops (simplify, merge) | `pip install shapely` |
| svgwrite | SVG output | `pip install svgwrite` |
| pyyaml | Project files | `pip install pyyaml` |
| vpype (external) | Line optimization + final SVG | `pip install vpype` (user installs) |

**Total direct deps**: 5 pure-Python or manylinux wheels. No Rust, no C++ toolchain.

---

## Non-Goals (Explicit)

- GUI / preview window
- Real-time parameter tuning
- Plugin system (v1)
- Cloud / batch service
- Premium PFM parity (closed source)

---

## Next Steps

1. Board reviews and marks each row **MVP / later / out**
2. Architect writes `docs/PLAN.md`, `docs/CONVENTIONS.md`, `docs/TESTING.md`, `docs/CLI.md`
3. PM (sergio) creates tickets from plan
4. Build starts with shared core (image I/O, geometry, CLI scaffold)