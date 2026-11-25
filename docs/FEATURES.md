# penpath Feature Proposal

**Status**: For board decision (MVP / later / out)  
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
| 13 | Sketch Lines (hatching) | Versatile pen-and-ink look from photos | Line density, min/max length, angle range, shading on/off, squiggles, erasing, seed | `pfm/PFMSketchLinesBasic.java` + settings in `Register.java` | L | NumPy, custom geometry | **MVP** |
| 14 | Sketch Squares (grid hatching) | Structured, graphic look | Grid angle, line density, min/max length | `pfm/PFMSketchSquaresBasic.java` | M | NumPy | **later** |
| 15 | Spiral (sawtooth) | Continuous-line, single-pass plots | Spiral type (Archimedean/parabolic), centre, ring spacing, amplitude, velocity range, connected lines | `pfm/PFMSpiralBasic.java` | M | NumPy | **later** |
| 16 | Contour tracing (potrace-style) | Clean vector outlines from thresholded image | Turn policy, turd size, alpha max, opticurve | New (DrawingBotV3 Premium only) | L | potrace / pypotrace | **later** |
| 17 | Stippling / pointillism | Dot-based shading | Dot density, min/max radius, jitter, seed | New | M | NumPy, Poisson disk | **out** — niche, can be built on Sketch Lines |
| 18 | Multi-pen / colour separation | CMYK, RGB, or custom palette splits | Separation mode (CMYK, RGB, threshold layers), per-layer PFM | `drawing/ColorSeparationHandler.java` (Default only in free) | L | — | **MVP** — sergio approved on 2026-11-24; the Christmas card needs it and the default path stays simple: one pen gives one layer, exactly as before |
| **Pens & Colour** |||||||
| 19 | Pen library (width, colour, type) | Match physical pens | Width (mm), colour (hex/CMYK), type (ballpoint, fountain, brush, marker), opacity | `files/json/presets/PresetDrawingPen*.java` | S | — | **MVP** |
| 20 | Pen pressure / width variation | Expressive strokes | Min/max width, pressure curve | New (DrawingBotV3 has easing) | M | — | **later** |
| 21 | Virtual paper (size, margins, colour) | Preview composition | Paper size (A4, A3, custom), margins, background colour | `plotting/canvas/*.java` | S | — | **MVP** |
| **Line Optimisation** |||||||
| 22 | Line simplification (RDP) | Reduce points, keep shape | Tolerance (mm) | `geom/operation/GeometryOperationSimplify.java` | S | shapely / custom | **MVP** |
| 23 | Line sorting (TSP / nearest-neighbour) | Minimize pen-up travel | Algorithm (greedy, 2-opt, OR-Tools), start point | `geom/spatial/TSPSequencer*.java`, `STRTreeSequencer*.java` | M | OR-Tools / custom | **MVP** |
| 24 | Line merging / join collinear | Reduce segments | Angle tolerance, distance tolerance | `geom/operation/GeometryOperationOptimize.java` | S | shapely | **MVP** |
| 25 | vpype pipeline integration | Industry-standard optimization & export | vpype commands (linemerge, linesimplify, reloop, linesort, write) | `integrations/vpype/*.java` | M | vpype (Python) | **MVP** — use vpype CLI as backend |
| **Output** |||||||
| 26 | SVG export (layers per pen) | Standard vector format for plotters | Paper size, DPI, layer naming, inkscape:groupmode, background layer | `files/exporters/SVGExporter.java` | S | svgwrite / lxml | **MVP** |
| 27 | GCode export | Direct machine control | Pen up/down commands, feed rates, units, header/footer | `files/exporters/GCodeExporter.java` | M | — | **later** |
| 28 | HPGL / DXF export | Legacy cutter support | — | New | M | — | **out** |
| 29 | PNG/PDF preview | Quick visual check | DPI, antialiasing, show pen-up moves | `files/exporters/ImageExporter.java`, `PDFExporter.java` | S | Cairo / reportlab | **later** |
| **Presets & Config** |||||||
| 30 | Project file (JSON/YAML) | Save/load full pipeline | All settings above | `files/json/projects/*.java` | M | pyyaml | **MVP** |
| 31 | Preset system (filters, PFM, pens, paper) | Reuse/share configurations | Name, description, tags | `files/json/presets/*.java` | M | — | **later** |
| 32 | CLI config file (TOML) | Persistent defaults | Default paper, pen, PFM, vpype path | New | XS | toml | **MVP** |

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

**MVP Scope**: One PFM (Sketch Lines), one pen by default and an ordered palette for multi-pen, vpype for optimization/export, minimal but complete filter chain for photo prep.

### Later (11 features) — "Polish and versatility"
- Sketch Squares, Spiral (additional styles)
- Contour tracing (clean outlines)
- Edge detect (outline mode)
- Filter pipeline/presets, pen pressure, GCode, preview renders, preset system
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