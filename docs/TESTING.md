# penpath Testing Strategy (MVP)

**Status**: Mandatory QA process  
**Goal**: Prove each MVP feature works correctly, regressions caught

---

## Test Pyramid

```
                    ┌─────────────┐
                    │  E2E / CLI  │  ← 5 tests (critical paths)
                    ├─────────────┤
              ┌─────│ Integration │─────┐  ← 10 tests (pipeline stages)
              │     └─────────────┘     │
      ┌───────┼─────────────────────────┼───────┐
      │       │        Unit             │       │  ← 100+ tests (functions)
      │       └─────────────────────────┘       │
      ▼                                         ▼
 Fast, isolated                          Full pipeline
 No external deps                        vpype, file I/O
```

---

## Test Categories

### 1. Unit Tests (`tests/unit/`)
- **Scope**: Single function/class, no I/O, no external deps
- **Speed**: <10ms each, full suite <5s
- **Coverage Target**: ≥90% core logic
- **Fixtures**: Synthetic data (arrays, simple geometries), `tmp_path` for file ops

#### Key Unit Test Modules
| Module | Tests |
|--------|-------|
| `core.image.load` | EXIF orient (all 8 orientations), unsupported format, missing file |
| `core.image.filters` | Each filter: identity, bounds, parameter combos, chaining |
| `core.image.pipeline` | Order preservation, enable/disable, serialization |
| `core.drawing.pfm_sketch_lines` | Deterministic seed, parameter bounds, empty image, all-white, all-black |
| `core.geometry.simplify` | Zero tolerance = identity, high tolerance = fewer points, topology |
| `core.geometry.merge` | Collinear join, angle threshold, disjoint lines unchanged |
| `core.geometry.sort` | Travel distance reduction, start point honored, empty/single line |
| `core.output.vpype` | CLI arg construction, layer mapping, error handling |
| `core.output.svg` | Layer structure, viewBox, pen attributes, empty input |
| `core.project` | Round-trip YAML, field validation, defaults, migration |
| `cli.config` | Load/save TOML, defaults, merge priority (CLI > project > config > defaults) |

### 2. Integration Tests (`tests/integration/`)
- **Scope**: Multi-stage pipeline, real file I/O, vpype subprocess
- **Speed**: <30s each, full suite <2min
- **Coverage Target**: ≥80% CLI commands, full pipeline paths
- **Fixtures**: Real test images (`tests/fixtures/images/`), golden SVGs (`tests/fixtures/golden/`)

#### Key Integration Tests
| Test | Description |
|------|-------------|
| `test_full_pipeline_basic` | `penpath convert input.png -o out.svg` → valid SVG, correct layers |
| `test_full_pipeline_with_filters` | Grayscale → threshold → blur → Sketch Lines → optimize → SVG |
| `test_full_pipeline_project_file` | `penpath convert --project project.yaml` matches flag-based run |
| `test_vpype_optimization` | Raw lines → vpype → fewer segments, sorted, reloop'd |
| `test_multiple_pens_single_pfm` | Single PFM, two pens (different densities) → two SVG layers |
| `test_paper_sizes` | A4, A3, custom → correct viewBox, centering |
| `test_seed_determinism` (`tests/integration/test_convert.py`) | Same seed → identical SVG (byte-for-byte after normalization). The test uses `--no-vpype`; vpype embeds a temporary input path in its SVG, so vpype output is compared by geometry instead (out of scope here). |
| `test_cli_help_and_errors` | All commands show help, invalid args exit 2 with message |

### 3. Golden File Tests
- **Location**: `tests/fixtures/golden/`
- **Format**: Normalized SVG (sorted attributes, stripped whitespace, deterministic IDs)
- **Update**: `pytest --update-golden` (CI fails if golden files drift)
- **Scope**: One per major pipeline configuration (basic, high-density, multi-pen, etc.)

---

## Test Data

### Images (`tests/fixtures/images/`)
| File | Size | Purpose |
|------|------|---------|
| `gradient.png` | 100×100 | Smooth ramp, tests shading |
| `checkerboard.png` | 64×64 | Sharp edges, tests threshold |
| `noise.png` | 200×200 | Gaussian noise, tests blur |
| `photo_small.jpg` | 400×300 | Real photo, EXIF orient=1 |
| `photo_exif_6.jpg` | 300×400 | Real photo, EXIF orient=6 (rotated) |
| `transparent.png` | 100×100 | Alpha channel, tests background |

**Max size**: 500KB each. Committed to repo.

### Golden SVGs (`tests/fixtures/golden/`)
| File | Pipeline Config |
|------|-----------------|
| `basic_sketch_lines.svg` | Default settings, A4, 0.3mm pen |
| `high_density.svg` | Line density 0.5, shading on |
| `threshold_binary.svg` | Threshold 2 levels, no shading |
| `multi_pen.svg` | Two pens (0.3mm, 0.5mm), same PFM |
| `a3_landscape.svg` | A3 paper, landscape, custom margins |

### Project Files (`tests/fixtures/projects/`)
| File | Description |
|------|-------------|
| `basic.yaml` | Minimal project (input, output, paper) |
| `full_pipeline.yaml` | All filters, PFM settings, pen, paper |
| `multi_pen.yaml` | Two pens, single PFM |

---

## Tolerances & Acceptance Criteria

### Geometry Comparison
- **Line count**: ±5% vs golden (algorithm variance)
- **Total length**: ±2% vs golden
- **Bounding box**: Exact match (paper-defined)
- **Point coordinates**: ±0.01mm after vpype normalization

### Image Comparison (Preview Renders)
- **SSIM**: ≥0.95 vs golden PNG render (if preview implemented)
- **Pixel diff**: ≤1% pixels differ by >5/255

### Likeness Scoring (LUC-30)
- **Measure**: Structural Similarity Index (SSIM) from scikit-image
- **Target size**: 256×256 pixels — balances detail retention with noise suppression
- **Blur sigma**: 1.5 — Gaussian blur before SSIM to tolerate minor misalignments and stroke width variation
- **Rationale**: SSIM correlates well with human perception of structural similarity. The downscale to 256×256 makes scoring fast and resolution-independent. Blur sigma of 1.5 (at 256px) smooths pen stroke texture while preserving overall form, so a well-hatched drawing scores high even if individual strokes don't perfectly match pixel positions.
- **Acceptance**: Matching drawing (hatched square vs square image) scores >0.7; empty drawing scores <0.3; different shape scores clearly lower. Ordering of scores is tested, not exact values.

## Sketch Lines likeness gate (LUC-47)

This is the likeness gate for the Sketch Lines PFM. Parts 1 and 2 defined and
enforced it; part 3 (LUC-54) shipped the calibrated defaults, refreshed the
numbers below and published before/after evidence. It is green on `main` with
the shipped defaults — `uv run pytest tests/integration/test_sketch_lines_gate.py`
passes for all five reference images.

Reproduce the numbers with:

```bash
uv run pytest tests/integration/test_sketch_lines_gate.py -s
```

The harness (`tests/integration/sketch_lines_gate.py`) runs the default
`penpath convert` pipeline for all five images in
`tests/fixtures/images/reference/` with seed 42, reads the recorded placement
rectangle from the SVG, parses the strokes and simulates the plot the same way
`penpath evaluate` does. It uses A4 paper (10 mm margin), the default 0.3 mm
black pen, and 96/25.4 px per mm. The values below were measured with vpype
1.15 installed, i.e. on `convert`'s default export path.

### What each measure means

- **SSIM**: `penpath.core.likeness.compute_likeness` applied to the simulated
  plot cropped to the recorded placement rectangle, at the same 256x256 size
  and blur sigma 1.5 used by `evaluate`. No second SSIM implementation is
  used. 1.0 means a perfect match.
- **Coverage**: the rectangle spanned by the stroke points, clipped to the
  placement rectangle. "W" and "H" are its width and height divided by the
  placement width and height; "bbox" is the product, i.e. the fraction of the
  placement area inside that bounding box. A drawing squeezed into one strip
  has a small W, H or bbox value.
- **Ink spread**: an ink pixel is a simulated pixel darker than 128 (halfway
  between black pen and white paper). The placement rectangle is divided into
  a 4x4 grid; each cell's share is its ink pixels divided by all ink pixels in
  the rectangle. "ink min" and "ink max" are the smallest and largest of the
  16 shares. A drawing sitting in one corner has one share near 1 and the
  rest near 0.
- **Tone**: the original image's greyscale quartiles split its pixels into the
  darkest 25% and the lightest 25%. Ink density is the share of pixels in each
  group covered by ink in the simulated crop; the tone ratio is dark density
  divided by light density, with one ink pixel smoothed over the crop area so
  the number stays finite when the light group has no ink. The ratio is 1.0
  for a blank page and must be above 1 when dark areas get more ink.
- **Blank page**: the same SVG page and placement metadata with no strokes at
  all. **Random lines**: as many seeded two-point strokes as the real output
  had, with endpoints uniform in the placement rectangle; this catches a
  drawing that is no better than scribbling. **Ideal**: the original image
  blurred (sigma 1) and Floyd-Steinberg dithered to the simulator's two ink
  levels (black ink, white paper), placed in the same rectangle and scored by
  the same `compute_likeness`. It is an upper bound, not a target: dithering is
  how a pen can represent the photo's tones, and it scores about 0.99 because
  the comparison blurs away the dither texture.

### Measured SSIM

| image | current `main` | blank page | random lines | ideal |
|-------|---------------:|-----------:|-------------:|------:|
| `circle.png` | 0.5930 | 0.4848 | 0.4736 | 0.9998 |
| `gradient.png` | 0.6492 | 0.6508 | 0.5979 | 0.9898 |
| `sphere.png` | 0.7806 | 0.7405 | 0.6749 | 0.9980 |
| `face.jpg` | 0.3098 | 0.2618 | 0.2329 | 0.9943 |
| `photo.jpg` | 0.4917 | 0.4993 | 0.3798 | 0.9931 |

### Measured coverage, spread and tone

| image | mode | bbox W | bbox H | bbox area | ink min | ink max | dark ink | light ink | tone ratio |
|-------|------|-------:|-------:|----------:|--------:|--------:|---------:|----------:|-----------:|
| `circle.png` | current | 0.750 | 0.755 | 0.566 | 0.0011 | 0.1182 | 0.631 | 0.0009 | 728.0 |
| `circle.png` | ideal | 1.000 | 1.000 | 1.000 | 0.0010 | 0.1423 | 0.9996 | 0.0003 | 3386.8 |
| `gradient.png` | current | 0.047 | 0.997 | 0.047 | 0.0000 | 0.2602 | 0.115 | 0.0000 | 39681.4 |
| `gradient.png` | ideal | 1.000 | 1.000 | 1.000 | 0.0155 | 0.1094 | 0.878 | 0.126 | 6.97 |
| `sphere.png` | current | 0.618 | 0.620 | 0.383 | 0.0000 | 0.2716 | 0.306 | 0.0000 | 157525.8 |
| `sphere.png` | ideal | 1.000 | 1.000 | 1.000 | 0.0004 | 0.2058 | 0.690 | 0.0002 | 3591.4 |
| `face.jpg` | current | 0.999 | 0.315 | 0.315 | 0.0000 | 0.3170 | 0.470 | 0.0000 | 303066.4 |
| `face.jpg` | ideal | 1.000 | 1.000 | 1.000 | 0.0226 | 0.0916 | 0.994 | 0.162 | 6.15 |
| `photo.jpg` | current | 0.407 | 0.980 | 0.399 | 0.0000 | 0.3699 | 0.245 | 0.0001 | 1613.9 |
| `photo.jpg` | ideal | 1.000 | 1.000 | 1.000 | 0.0309 | 0.0973 | 0.887 | 0.307 | 2.89 |

Random lines span at least 0.674 of the width, 0.652 of the height and 0.439
of the area of every placement rectangle. The ideal places at least 0.00035
of the ink in every grid cell (sphere) and has a tone ratio of at least 2.89
(photo). Those numbers set the non-SSIM floors below.

### SSIM thresholds

For each image the threshold is (a) above both the blank and random scores,
(b) above the broken algorithm's score (0.29 on the photo in the earlier
measurement, 0.4917 for current `main` here), and (c) no more than about 70%
of the way from the higher baseline to the ideal. "Gap used" is the threshold's
share of that baseline-to-ideal gap.

| image | higher baseline | ideal | current `main` | 70% cap | threshold | gap used |
|-------|----------------:|------:|---------------:|--------:|----------:|---------:|
| `circle.png` | 0.4848 blank | 0.9998 | 0.5930 | 0.845 | **0.75** | 51% |
| `gradient.png` | 0.6508 blank | 0.9898 | 0.6492 | 0.888 | **0.80** | 44% |
| `sphere.png` | 0.7405 blank | 0.9980 | 0.7806 | 0.921 | **0.88** | 54% |
| `face.jpg` | 0.2618 blank | 0.9943 | 0.3098 | 0.775 | **0.70** | 60% |
| `photo.jpg` | 0.4993 blank | 0.9931 | 0.4917 | 0.845 | **0.75** | 51% |

- `circle.png`: 0.75 is well above the 0.4848 blank and the 0.4736 random
  scores; current `main` (0.5930) fails it because it covers only 57% of the
  rectangle.
- `gradient.png`: even the blank page (0.6508) beats current `main` (0.6492),
  so the threshold has to start above the blank; 0.80 uses only 44% of the gap
  to the 0.9898 ideal and catches the 5%-wide strip current `main` draws.
- `sphere.png`: the blank score is already 0.7405, so 0.88 leaves room for a
  real shaded sphere while still rejecting the current 0.7806.
- `face.jpg`: the blank score is low (0.2618) and the ideal high (0.9943), but
  a face is the hardest subject here; 0.70 uses 60% of the gap and still leaves
  current `main` (0.3098) and the historical 0.29 score far below.
- `photo.jpg`: the blank page scores 0.4993, above current `main` (0.4917) and
  the earlier 0.29 measurement. A threshold of 0.75 is halfway to the ideal
  and demands a real likeness rather than an empty page.

### Non-SSIM minimums

These floors come from what the baselines and the ideal actually achieved, so
they are reachable; a drawing below one of them is worse than a blank, random
or ideally tone-mapped page in that respect. Part 2 will assert them together
with the SSIM thresholds.

| Measure | Minimum | Why this number |
|---------|--------:|-----------------|
| Covered width | 0.60 | Random strokes span at least 0.674 of the width and the ideal spans 1.0, so a plot covering under 60% of the rectangle width is worse than scribbling (`gradient.png` currently 0.047, `photo.jpg` 0.407). |
| Covered height | 0.60 | Random strokes span at least 0.652 of the height and the ideal spans 1.0; `face.jpg` currently covers only 0.315. |
| Bounding-box area | 0.40 | Random strokes reach at least 0.439 and the ideal 1.0, so a smaller area means the drawing is confined to a strip or corner. |
| Ink per 4x4 cell | 0.0003 | The ideal puts at least 0.00035 of all ink in its sparsest cell (sphere); rounded down, every cell must receive some ink, which rejects drawings that ignore a whole quarter of the rectangle. |
| Dark/light tone ratio | 2.0 | The ideal's weakest dark-vs-light ratio is 2.89 (photo); a floor of 2.0 still requires dark image areas to receive at least twice the ink density of light ones. |

`test_sketch_lines_gate.py` now asserts the enforced floors under "Enforced
gate" below; the withdrawn thresholds in this section are kept as the record of
why the floor had to be re-derived.

### Enforced gate (LUC-47 part 2, re-derived 2026-11-24)

`test_sketch_lines_gate.py` now asserts the floors below. The five SSIM floors
above are **withdrawn**. They measured the 0.99 raster stipple rather than a
pen plot: thinning that ideal by dropping random ink pixels drops its circle
score from 0.9998 to 0.6482 at 98% ink, so 0.75 asks a line drawing for a
near-solid disc, and the same ideal smeared into 2 px dashes scores 0.35-0.74.
The replacement rule is `max(blank page, random lines) + 0.05`, never below
`measured - 0.05`; where a drawing cannot beat both trivial baselines the
floor is `random lines + 0.05` and the non-SSIM floors carry the quality.
The non-SSIM floors above stay verbatim.

| image | new SSIM floor | derived from | algorithm measured |
|-------|---------------:|--------------|-------------------:|
| `circle.png` | 0.53 | blank 0.4848 + 0.05 | 0.5474 |
| `gradient.png` | 0.46 | previous port 0.5051 - 0.05 | 0.5401 |
| `sphere.png` | 0.79 | blank 0.7405 + 0.05 | 0.8135 |
| `face.jpg` | 0.57 | previous port 0.6189 - 0.05 | 0.6481 |
| `photo.jpg` | 0.18 | previous random lines 0.1266 + 0.05 | 0.5099 |

Measured with part 1's harness unchanged (vpype 1.15, A4 with the 10 mm
margin, seed 42, `compute_likeness`) after the LUC-53 defaults and the
reference-fidelity fixes; the same run gives covered width/height 0.747/0.747
(circle), 0.830/0.997 (gradient), 0.745/0.747 (sphere), 0.999/0.999 (face and
photo), bbox area 0.559 / 0.828 / 0.557 / 0.998 / 0.998, minimum 4x4 ink share
0.0009 / 0.0019 / 0.0005 / 0.0158 / 0.0212, tone ratio 4442 / 41.1 / 8115 /
27.7 / 2.87, and stroke counts 175 / 206 / 43 / 1163 / 1533. The random-lines
row is report-only: the harness draws as many strokes as the algorithm
produced, so that row moves with the stroke count.

### Final shipped-defaults measurement (LUC-54, 2026-11-25)

Remeasured with the same harness, vpype 1.15, seed 42 and the defaults shipped
in `SketchLinesSettings()`. "Before" is the algorithm at `ac3206d`, the commit
before part 2; both runs use the same image, placement, pen and simulator.

| image | before SSIM | after SSIM | enforced floor | stroke count before → after |
|-------|------------:|-----------:|---------------:|----------------------------:|
| `circle.png` | 0.5933 | **0.5474** | 0.53 | 80 → 175 |
| `gradient.png` | 0.6492 | **0.5401** | 0.46 | 141 → 206 |
| `sphere.png` | 0.7806 | **0.8135** | 0.79 | 78 → 43 |
| `face.jpg` | 0.3097 | **0.6481** | 0.57 | 415 → 1163 |
| `photo.jpg` | 0.4917 | **0.5099** | 0.18 | 601 → 1533 |

SSIM alone goes *down* on the circle and gradient. The old algorithm covered
little or no area with a near-solid stipple, which SSIM rewards but a pen cannot
plot; that is why part 1's stipple-based floors were withdrawn. The fix spends
that score on the measures that make a plot recognizable: coverage, ink spread
and tone separation. Every after value clears its enforced floor, and the photo
now scores above its blank page (0.4993).

| image | covered W before → after | covered H before → after | bbox area before → after | ink per cell (min) before → after | tone ratio before → after |
|-------|-------------------------:|-------------------------:|-------------------------:|----------------------------------:|--------------------------:|
| `circle.png` | 0.750 → 0.747 | 0.755 → 0.747 | 0.566 → 0.559 | 0.0011 → 0.0009 | 725 → 4442 |
| `gradient.png` | 0.047 → 0.830 | 0.997 → 0.997 | 0.047 → 0.828 | 0.0000 → 0.0019 | 39689 → 41 |
| `sphere.png` | 0.617 → 0.745 | 0.620 → 0.747 | 0.383 → 0.557 | 0.0000 → 0.0005 | 157490 → 8115 |
| `face.jpg` | 0.999 → 0.999 | 0.315 → 0.999 | 0.315 → 0.998 | 0.0000 → 0.0158 | 303078 → 27.7 |
| `photo.jpg` | 0.407 → 0.999 | 0.980 → 0.999 | 0.399 → 0.998 | 0.0000 → 0.0212 | 1500 → 2.87 |

The striking coverage gains are the gradient (a 5%-wide strip becomes a full
83%-wide drawing), the face (31% of the height becomes 99%) and the photo (41%
of the width becomes 99%). Ink now reaches every 4x4 cell of the placement
instead of none in three images. Tone ratios are lower but stay well above the
2.0 floor; the very large before values came from light areas receiving almost
no ink at all.

Simulated-plot previews for every image, before and after, are committed under
[`docs/images/luc-47/`](../images/luc-47/) (greyscale, 600 px wide):

| image | before | after |
|-------|--------|-------|
| `circle.png` | [before](../images/luc-47/circle_before.png) | [after](../images/luc-47/circle_after.png) |
| `gradient.png` | [before](../images/luc-47/gradient_before.png) | [after](../images/luc-47/gradient_after.png) |
| `sphere.png` | [before](../images/luc-47/sphere_before.png) | [after](../images/luc-47/sphere_after.png) |
| `face.jpg` | [before](../images/luc-47/face_before.png) | [after](../images/luc-47/face_after.png) |
| `photo.jpg` | [before](../images/luc-47/photo_before.png) | [after](../images/luc-47/photo_after.png) |

### Machine Cost (LUC-27)

Machine cost measures how much work the plotter does, independently of how the
plot looks. `penpath evaluate` reports these metrics per pen layer (grouped by
stroke colour) and in total:

| Metric | Meaning |
|--------|---------|
| `drawing_length_mm` | Length of pen-down strokes — ink laid on the paper. |
| `pen_up_travel_mm` | Length of pen-up moves — the pen travelling without drawing. |
| `num_lifts` | Number of pen-up transitions between drawing strokes. |
| `num_short_segments` | Segments shorter than 0.5 mm — tiny moves that waste pen time. |
| `num_strokes` | Number of pen-down strokes. A pen-up move is not a stroke. |

The likeness score and its blur are described in "Likeness Scoring" above:
SSIM compares the simulated plot with the original after both are downscaled
to 256x256 and blurred with sigma 1.5.

**How pen-up travel is derived.** The SVG parser reads strokes in document
order. With `include_pen_up=True`, if the straight gap between the end of one
stroke and the start of the next is larger than 0.01 mm, the parser inserts a
two-point pen-up stroke between them. Its length is exactly the distance the
machine travels with the pen raised, and it takes the colour of the following
stroke (the pen about to draw). Strokes that meet end-to-start are contiguous:
they produce no travel move and no lift. Library callers keep the old,
draw-only behaviour unless they pass `include_pen_up=True`; `penpath evaluate`
passes it, `penpath preview` does not because travel moves are never drawn.

**Acceptance**: a hand-made SVG with three 80 mm horizontal lines 30 mm apart
(drawn in alternating directions) reports exactly 240 mm drawn, 60 mm travel
and 2 lifts; a single stroke reports 0 travel and 0 lifts; per-layer numbers
add up to the total.

### Running `preview` and `evaluate`

Render a simulated plot of an SVG to an image, and score an SVG against its
original image:

```bash
penpath preview plot.svg -o preview.png
penpath evaluate photo.jpg plot.svg
penpath evaluate photo.jpg plot.svg --json | jq '.machine_cost.total'
```

`preview` reads the same strokes but skips travel moves, so it shows the ink
only. `evaluate --json` writes one JSON object (`likeness` and `machine_cost`)
to stdout and prints its human tables to stderr, so it is safe to pipe. Use
`--dpi` (pixels per millimetre) to change the simulation resolution and
`--layer` to evaluate just one pen layer. See `docs/CLI.md` for every option.

### Performance Budgets (CI)
| Operation | Max Time (400×300 image) |
|-----------|--------------------------|
| Load + filters | 500ms |
| Sketch Lines (default) | 3s |
| Geometry optimize | 1s |
| vpype pipeline | 2s |
| SVG write | 200ms |
| **Total** | **<7s** |

### CLI Exit Codes
| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Runtime error (file not found, vpype failed, etc.) |
| 2 | Usage error (invalid args, missing required) |
| 3 | Validation error (project file invalid, config invalid) |

---

## CI Pipeline

```yaml
# .github/workflows/ci.yml
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --frozen --group dev
      - run: uv run ruff check src tests
      - run: uv run ruff format --check src tests
      - run: uv run mypy --strict src

  test:
    runs-on: ubuntu-latest
    needs: lint
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --frozen --group dev
      - run: pip install vpype  # external dep
      - run: uv run pytest -xvs --cov=penpath --cov-fail-under=85

  integration:
    runs-on: ubuntu-latest
    needs: lint
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --frozen --group dev
      - run: pip install vpype
      - run: uv run pytest tests/integration -xvs

  golden-check:
    runs-on: ubuntu-latest
    needs: test
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --frozen --group dev
      - run: pip install vpype
      - run: uv run pytest tests/integration --golden-check
```

---

## Local Development

### Run All Tests
```bash
uv sync --group dev
pip install vpype
uv run pytest -xvs
```

### Run Unit Only (Fast)
```bash
uv run pytest tests/unit -xvs
```

### Update Golden Files
```bash
uv run pytest tests/integration --update-golden
```

### Coverage Report
```bash
uv run pytest --cov=penpath --cov-report=html
open htmlcov/index.html
```

### Type Check Only
```bash
uv run mypy --strict src
```

### Lint Only
```bash
uv run ruff check src tests
uv run ruff format --check src tests
```

---

## Regression Prevention

### Pre-commit Hooks (`.pre-commit-config.yaml`)
```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.5.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.10.0
    hooks:
      - id: mypy
        args: [--strict, src]
  - repo: local
    hooks:
      - id: pytest-unit
        name: pytest (unit)
        entry: uv run pytest tests/unit -x
        language: system
        pass_filenames: false
        stages: [commit]
```

### Golden File Drift Detection
- CI fails if `tests/integration` produces different output than committed goldens
- `--update-golden` requires explicit local run + commit

### Dependency Vulnerability Scan
- `uv audit` in weekly scheduled workflow
- Fail on `HIGH`/`CRITICAL` CVEs in direct deps

---

## Release Validation (Pre-Publish)

Before tagging a release:
1. All CI green on `main`
2. `uv run pytest tests/ -xvs --tb=short`
3. Manual smoke test: `penpath convert tests/fixtures/images/photo_small.jpg -o /tmp/test.svg`
4. Verify `/tmp/test.svg` opens in Inkscape, plots on hardware (if available)
5. Check `CHANGELOG.md` updated
6. Tag: `git tag -a vX.Y.Z -m "Release vX.Y.Z"` → `git push origin vX.Y.Z`

---

## Out of Scope (MVP Testing)

- Visual regression (pixel-perfect) across OS/renderers
- Hardware plotter integration tests
- Load/stress testing (large images, batch)
- Accessibility testing (screen readers)
- Internationalization (non-ASCII paths)