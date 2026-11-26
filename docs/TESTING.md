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
- **Speed**: measured 15.61 s for the full suite on `ubuntu-latest` (see "Measured suite speed" below)
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
- **Speed**: measured 23.48 s for the likeness gate and 170.31 s for the other integration tests on `ubuntu-latest` (see "Measured suite speed" below)
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

#### Golden G-code files (LUC-51 part 3)

The G-code emitter has its own golden files because its output is text: one
exact file per built-in profile.

- **Location**: `tests/fixtures/golden/gcode/<name>.gcode` for expected text;
  `tests/fixtures/svg/gcode/<name>.svg` for the input drawings. `simple.svg`
  holds one layer with two known polylines; `multi_pen.svg` holds two layers in
  document order, and `multi_pen.gcode` pins one pen-change block before the
  second layer.
- **Format**: the produced text is compared byte for byte (UTF-8, LF line
  endings, one trailing newline). The test
  `tests/integration/test_gcode_golden.py` loads the built-in profile through
  `load_profile`, parses the fixture SVG with `parse_svg_strokes`, runs
  `build_gcode` and compares the bytes.
- **Regenerate only with an explicit flag or env var**, never by hand:

  ```bash
  uv run pytest tests/integration/test_gcode_golden.py --update-golden
  PENPATH_UPDATE_GOLDEN=1 uv run pytest tests/integration/test_gcode_golden.py
  ```

  The flag writes the golden file from the emitter's real output. Review the
  diff before committing it: a golden only changes when the intended G-code
  shape changes (a D6/D7 decision, or a deliberate edit to the built-in
  profile). A changed profile value must be made in the profile YAML, not in
  the golden. CI runs without the flag and fails on any drift.
- **Coverage**: the golden pins the header, verbatim start/end blocks, layer
  comments, coordinate mapping (Y flip, pen offset, placement), the pen
  up/down state machine and the draw feed in one byte-for-byte check. Unit
  tests in `tests/unit/core/output/test_gcode.py` cover the same rules with
  synthetic profiles, including the out-of-bed error.
- **Part 7 (LUC-64)**: `tests/fixtures/profiles/ramped.yaml` is a user-profile
  fixture with `bed.pen_offset_mm` and a D7 ramp. The same
  `tests/integration/test_gcode_golden.py` run pins
  `tests/fixtures/golden/gcode/ramped.gcode` for `simple.svg`, so a change to
  the lead-in formula, the Z interpolation or the nozzle transform fails it.
  The generic and multi-pen goldens stay unchanged: a profile without those
  fields must still produce exactly the same text. The end-to-end
  `test_ramped_gcode_png_equals_svg_png` checks that the ramp's above-paper
  lead-in and lead-out are not inked, and
  `test_gcode_rejects_point_outside_derived_drawable_area` checks that the
  shifted nozzle range rejects a point with its coordinates.
- **Part 8 (LUC-65)**: `tests/fixtures/golden/gcode/aquila.gcode` pins the built-in
  `aquila` profile byte for byte from `tests/fixtures/svg/gcode/aquila_card.svg`,
  a 170x170 mm page that fits the machine's 177.3 x 171.4 mm usable area (its
  197.3 x 191.4 mm drawable area minus the 10 mm safety margin). A
  change to any reference number or verbatim block in `aquila.yaml` must be made
  in the profile and then regenerate the golden with `--update-golden`; unit
  tests in `tests/unit/core/test_aquila_profile.py` name each reference value,
  and the CLI test in `tests/integration/test_gcode_cli.py` checks the file a
  user gets from `penpath gcard.svg --profile aquila`. Plotting on the machine
  is the operator's evidence and is not a CI check.

### Measured suite speed (2026-11-25)

These are measurements of the current suite, not budgets. The suite numbers
come from GitHub Actions
[run 45639769529](https://github.com/sermelo/penpath/actions/runs/45639769529)
(the LUC-81 merge on `main`) on GitHub-hosted `ubuntu-latest`, Python 3.14 and
vpype 1.15. The times are the `pytest` summary lines, so checkout, dependency
installation and apt setup are excluded.

| Suite | Command | Result | Test time |
|-------|---------|--------|----------:|
| Unit | `uv run pytest tests/unit -vs --cov=penpath --cov-fail-under=75 --cov-report=term-missing` | 609 passed | 15.61 s |
| Integration gate alone | `uv run pytest tests/integration/test_sketch_lines_gate.py tests/integration/test_gate_measures.py -vs` | 12 passed | 23.48 s |
| Integration, rest | `uv run pytest tests/integration --ignore=tests/integration/test_sketch_lines_gate.py --ignore=tests/integration/test_gate_measures.py -vs` | 99 passed | 170.31 s (2:50) |
| Integration total | gate + rest | 111 passed | 193.79 s (3:14) of test time |

The two integration jobs run in parallel in CI, so the integration stage took
about 2:50 of wall-clock time there. A full `uv run pytest` on a VPS (Ubuntu
24.04, aarch64, Python 3.14.10, vpype 1.15) ran 799 tests in 398.74 s (6:38);
an earlier run of 796 tests on the same machine took 632.43 s (10:32), so the
wall time moves with runner load. A slow full suite is why
[`.github/workflows/nightly.yml`](../.github/workflows/nightly.yml) runs it on a
schedule and on demand instead of as a pull-request check.

One `penpath convert` of a photo was timed on that same VPS with:

```bash
/usr/bin/time -f 'penpath convert wall time: %e s' \
  uv run penpath convert tests/fixtures/images/reference/photo.jpg \
    -o /tmp/nightly-photo.svg --pfm-setting seed=42 --quiet
```

It took **56.00 s** with the default A4 paper and 0.3 mm pen. The 12 MP case
under "Large input performance" below uses a 0.4 mm pen on 190x190 mm paper,
so it draws at a lower working resolution and took 11.49 s on the same class of
machine. The nightly workflow repeats this timed conversion on every run.

### Run the nightly workload locally

The workload itself lives in `scripts/nightly.sh`. The nightly workflow calls
that same script, so the scheduled job and a local run cannot drift apart. From
a checkout, with uv and the Pillow system libraries from the workflow installed:

```bash
bash scripts/nightly.sh
```

This runs exactly what the workflow runs after provisioning Python, the system
libraries and uv:

1. `uv sync --python 3.14 --extra dev --extra vpype` — the `--python 3.14` pin
   matches the workflow's `setup-python` step.
2. `uv pip install pytest pytest-cov`.
3. One timed conversion with the same seed and settings as the workflow, which
   prints `penpath convert wall time: <seconds> s` and writes
   `/tmp/nightly-photo.svg`.
4. `uv run pytest tests/unit tests/integration -vs`.

The script stops at the first failed command and exits with its status. On a
system where `/usr/bin/time` is not GNU time (for example macOS), point it at a
GNU-compatible binary with `PENPATH_NIGHTLY_TIME=gtime bash scripts/nightly.sh`.

---

## Test Data

### Images (`tests/fixtures/images/`)

Only files that are committed are listed here. Each fixture directory has a
README with the full set, sources and a rebuild command.

| File | Size | Purpose |
|------|------|---------|
| `basic/checkerboard.pbm` | 64×64 | Sharp edges, tests threshold |
| `reference/gradient.png` | 600×400 | Smooth ramp, tests shading |
| `reference/photo.jpg` | 1280×853 | Real photo, tests a detailed landscape |
| `colour/colour_blocks.png` | 826×422 | Synthetic hue blocks, tests many-pen separation |
| `colour/christmas_tree.jpg` | 920×1160 | CC0 colour photo, tests the 2% per-pen acceptance |

The other basic shapes (`black_square.pbm`, `white_square.pbm`, `black_disc.pbm`,
`horizontal_line.pbm`, `triangle.pbm`) and reference images (`circle.png`,
`sphere.png`, `face.jpg`) are listed in `tests/fixtures/images/basic/README.md`
and `tests/fixtures/images/reference/README.md`.

**Max size**: 500KB each. Committed to repo.

### Golden files (`tests/fixtures/golden/`)

No golden SVG files are committed. The directory holds only G-code goldens in
`tests/fixtures/golden/gcode/`: `aquila.gcode`,
`aquila_reference_two_layers.gcode`, `generic.gcode`, `multi_pen.gcode` and
`ramped.gcode`. "Golden G-code files" above describes how they are generated and
compared; the input SVGs for those tests are in `tests/fixtures/svg/gcode/`.

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

### Preview pen-up travel (LUC-136)

Travel rendering is **opt-in** with `penpath preview --travel`; the default
(`--no-travel`) stays ink-only and must keep producing a byte-for-byte identical
PNG. The default G-code-versus-SVG PNG equality test runs without the flag for
that reason. With the flag on, pen-up moves are straight two-point strokes with
the shared 0.01 mm gap rule, drawn as thin light grey (0.1 mm, `#C8C8C8`) under
the ink: a test for each input format compares the PNG with and without the flag,
checks that every inked pixel is identical, and checks that travel-only pixels
are light grey rather than black. A further test checks `--travel` together with
`--layer`, and `tests/integration/test_preview_evaluate.py` drives the CLI the way
a user does. The images in `docs/images/luc-136/` show the same `source.svg`
rendered ink-only, with `--travel`, and with `--travel` from its generated
G-code; the faint grey lines connect the four separated shapes.

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
produced, so that row moves with the stroke count. LUC-89 raised the gradient
floor from 0.46 to 0.47: with the new default its measurement is 0.5275, so
`measured - 0.05` is 0.4775. The other four floors are unchanged.

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

### Gate with downscale enabled (LUC-48 part 3, 2026-11-25)

`penpath convert` now downscales inputs above the working resolution, so the
same harness was run again through the default path with downscale enabled
(vpype 1.15, seed 42). "LUC-54" is the measurement above, before downscale
landed; "LUC-57" is the new measurement. Both clear the enforced floors.

| image | LUC-54 SSIM | LUC-57 SSIM | floor | strokes (LUC-54 → LUC-57) |
|-------|------------:|------------:|------:|---------------------------:|
| `circle.png` | 0.5474 | 0.5474 | 0.53 | 175 → 175 |
| `gradient.png` | 0.5401 | 0.5405 | 0.46 | 206 → 206 |
| `sphere.png` | 0.8135 | 0.8135 | 0.79 | 43 → 43 |
| `face.jpg` | 0.6481 | 0.6383 | 0.57 | 1163 → 1149 |
| `photo.jpg` | 0.5099 | 0.5744 | 0.18 | 1533 → 901 |

`uv run pytest tests/integration/test_sketch_lines_gate.py` reports
`2 passed`; all covered width, height, bbox, ink-spread and tone floors also
pass. The face and photo changed because they are the only references larger
than the working resolution and are therefore downscaled. Interpreting the
pixel settings in working-image pixels keeps their ink independent of the
source size; with the old source-ratio scaling, `face.jpg` drew for over 40 min
before the gate could finish.

### Max fill calibration (LUC-89, 2026-11-25)

`SketchLinesSettings.max_fill` caps ink coverage at a percentage below 100 by
lifting every luminance darker than `255 * (1 - max_fill / 100)` to that black
point before any average or stroke is taken. The calibration harness generates
three 400x400 images in code — a solid black square on white (`dark_figure`), a
light grey disc on white (`light_figure`, tone 190), and a left-to-right black
to white ramp (`gradient`) — then runs the real `penpath convert` and simulator
path with seed 42 for each value. Ink density is the share of simulated ink
pixels inside a source region; the ramp's three bands are its left, middle and
right thirds.

Reproduce the table with:

```bash
uv run pytest tests/integration/test_max_fill.py -s
```

| figure | max_fill | dark ink | light ink | band 1 | band 2 | band 3 | length mm | strokes | SSIM |
|--------|---------:|---------:|----------:|-------:|-------:|-------:|----------:|--------:|-----:|
| `dark_figure` | 60 | 0.3103 | 0.0000 | 0.3103 | n/a | n/a | 13326.9 | 34 | 0.7316 |
| `dark_figure` | 70 | 0.3618 | 0.0000 | 0.3618 | n/a | n/a | 16248.8 | 48 | 0.7363 |
| `dark_figure` | **80** | 0.4099 | 0.0000 | 0.4099 | n/a | n/a | 19128.7 | 55 | 0.7398 |
| `dark_figure` | 90 | 0.4604 | 0.0000 | 0.4604 | n/a | n/a | 22546.2 | 88 | 0.7436 |
| `dark_figure` | 100 | 0.5084 | 0.0000 | 0.5084 | n/a | n/a | 26078.6 | 100 | 0.7461 |
| `light_figure` | 60 | 0.1549 | 0.0000 | 0.1549 | n/a | n/a | 4954.2 | 4 | 0.9020 |
| `light_figure` | 70 | 0.1549 | 0.0000 | 0.1549 | n/a | n/a | 4954.2 | 4 | 0.9020 |
| `light_figure` | **80** | 0.1549 | 0.0000 | 0.1549 | n/a | n/a | 4954.2 | 4 | 0.9020 |
| `light_figure` | 90 | 0.1549 | 0.0000 | 0.1549 | n/a | n/a | 4954.2 | 4 | 0.9020 |
| `light_figure` | 100 | 0.1549 | 0.0000 | 0.1549 | n/a | n/a | 4954.2 | 4 | 0.9020 |
| `gradient` | 60 | 0.3384 | 0.0573 | 0.3384 | 0.2787 | 0.0573 | 38471.2 | 101 | 0.5308 |
| `gradient` | 70 | 0.3994 | 0.0441 | 0.3994 | 0.2690 | 0.0441 | 41827.3 | 109 | 0.5336 |
| `gradient` | **80** | 0.4352 | 0.0401 | 0.4352 | 0.2723 | 0.0401 | 44679.6 | 111 | 0.5449 |
| `gradient` | 90 | 0.4554 | 0.0396 | 0.4554 | 0.2712 | 0.0396 | 46680.6 | 124 | 0.5488 |
| `gradient` | 100 | 0.4681 | 0.0400 | 0.4681 | 0.2620 | 0.0400 | 47196.3 | 133 | 0.5416 |

The shipped default is **80**. Against full range it cuts the solid square's
ink density from 0.5084 to 0.4099 (19%) and its pen-down length from 26078.6 to
19128.7 mm (27%), while the light figure's 0.1549 ink density is unchanged
because tone 190 is above every black point in the sweep. The gradient keeps
its tone ordering (0.4352 > 0.2723 > 0.0401) and loses 5% of its length; SSIM
falls by 0.006 on the dark figure and rises by 0.003 on the gradient. Lower
values buy little: 60 gives only 0.3103 dark ink but the worst dark-figure
likeness (0.7316), and 100 is what the cap exists to avoid. `max_fill=100` is
the opt-in full range and is never the default.

### Sketch Lines likeness gate with the max_fill default (LUC-89, 2026-11-25)

The same harness as the LUC-48 measurement above was rerun with the shipped
`max_fill=80` (vpype 1.15, seed 42, default export path). Every enforced floor
still passes; the gradient SSIM floor was re-derived as `measured - 0.05 =
0.4775`, rounded down to 0.47, because 0.46 was now more than 0.05 below the
measurement.

| image | before SSIM (LUC-48) | after SSIM | floor | strokes before → after |
|-------|---------------------:|-----------:|------:|------------------------:|
| `circle.png` | 0.5474 | 0.5381 | 0.53 | 175 → 110 |
| `gradient.png` | 0.5405 | 0.5275 | 0.47 | 206 → 185 |
| `sphere.png` | 0.8135 | 0.8011 | 0.79 | 43 → 46 |
| `face.jpg` | 0.6383 | 0.6109 | 0.57 | 1149 → 917 |
| `photo.jpg` | 0.5740 | 0.5292 | 0.18 | 901 → 731 |

| image | covered W / H before → after | bbox before → after | ink min before → after | tone ratio before → after |
|-------|------------------------------|--------------------|------------------------|--------------------------|
| `circle.png` | 0.747 / 0.747 → 0.748 / 0.748 | 0.559 → 0.559 | 0.0009 → 0.0010 | 4442 → 3847 |
| `gradient.png` | 0.830 / 0.997 → 0.817 / 0.997 | 0.828 → 0.815 | 0.0019 → 0.0008 | 41.1 → 36.7 |
| `sphere.png` | 0.745 / 0.747 → 0.748 / 0.748 | 0.557 → 0.559 | 0.0005 → 0.0004 | 8115 → 5151 |
| `face.jpg` | 0.999 / 0.999 → 0.999 / 0.999 | 0.998 → 0.998 | 0.0155 → 0.0175 | 24.0 → 15.7 |
| `photo.jpg` | 0.999 / 0.998 → 0.999 / 0.998 | 0.997 → 0.997 | 0.0197 → 0.0238 | 3.31 → 2.93 |

Fewer strokes and a little less SSIM are the expected cost of capping solid
black. Coverage, ink spread and tone separation all stay above the LUC-47
floors, so the drawings remain recognisable and plottable.

### Auto equalization on by default (LUC-90, 2026-11-25)

`convert` stretches the working image's luminance range `[lo, hi]` to
`[0, 255]` with one linear lookup table before palette separation. It is a
no-op for images that already cover 0-255, that span at least 7/8 of 0-255
(224 levels), or that have a range narrower than 16 levels. All five likeness
references fall into one of those cases, so their converted SVGs are
**byte-identical to `main`** and the three gate suites report their `main`
values after the LUC-89 `max_fill` rebase:
`pytest tests/integration/test_sketch_lines_gate.py` reports 6 passed with the
LUC-89 baselines (sphere 0.8011, 46 strokes, ink min 0.0004),
`test_basic_shapes.py` reports 13 passed with every measured value identical,
and `test_multi_pen_gate.py` reports 12 passed with its pre-existing recorded
union tone-ratio failure at 1.5842, inside the harness's pinned tolerance.
No floor was moved. Reproduce with:

```bash
uv run pytest tests/integration/test_sketch_lines_gate.py -s
```

The 224-level no-op came from an Architect decision after an unrestricted
stretch regressed `sphere.png` (range 31-255). The measurements below are kept
as evidence: "before" is the same harness on the same runner with `convert`'s
`auto_equalize` monkeypatched to an identity copy, "after" is that rejected
unrestricted stretch.

| image | before SSIM | after SSIM | strokes before → after | ink min before → after | tone ratio before → after |
|-------|------------:|-----------:|-----------------------:|-----------------------:|--------------------------:|
| `circle.png` | 0.5474 | 0.5474 | 175 → 175 | 0.0009 → 0.0009 | 4442.16 → 4442.16 |
| `gradient.png` | 0.5405 | 0.5405 | 206 → 206 | 0.0019 → 0.0019 | 41.11 → 41.11 |
| `sphere.png` | 0.8135 | 0.8198 | 43 → 50 | 0.0005 → **0.0000** | 8114.67 → 5005.35 |
| `face.jpg` | 0.6383 | 0.6383 | 1149 → 1149 | 0.0155 → 0.0155 | 24.04 → 24.04 |
| `photo.jpg` | 0.5739 | 0.5740 | 901 → 901 | 0.0197 → 0.0197 | 3.31 → 3.31 |

At range 224 the largest stretch is 255/224 = 1.14. It raised SSIM but left
one corner cell of `sphere.png` with no ink (0.0000 < the enforced 0.0003
floor), so the gate reported **1 failed, 5 passed** with
`sphere.png: ink per 4x4 cell 0.0000 < 0.0003`. `photo.jpg`'s brightest
luminance is 254, so it barely moved; `circle.png`, `gradient.png` and
`face.jpg` already cover 0-255. Re-deriving the floor cannot accept a zero
cell, so the rule was refined instead and no floor was changed.

### Multi-pen per-layer gate (LUC-50 part 6, 2026-11-25)

One palette drawing has several pens, each responsible for a colour region.
The gate now has two levels: the union of all pens is judged against the whole
photo with the unchanged LUC-47 floors, and each pen is judged against its own
region with region-relative measures.

Reproduce the numbers with:

```bash
uv run pytest tests/integration/test_multi_pen_gate.py -s
```

The harness (`tests/integration/multi_pen_gate.py`) runs the real CLI on
`tests/fixtures/images/reference/photo.jpg` with `--palette stabilo_88` and
`-s seed=42`, on A4 with a 10 mm margin and vpype 1.15 on the default export
path; the recorded working image is 742x494 px and the placement is 190.0 x
126.6172 mm. It splits the photo with `separate_palette` — one full-size `L`
channel per pen, holding that pen's luminance on its own pixels and white
elsewhere. Strokes are selected with `parse_svg_strokes(svg, layer="layerN")`,
using the `id` of each Inkscape layer, not by stroke colour: a user palette can
repeat a colour without mixing two pens. They are then recoloured black so the
`< 128` ink threshold applies to every pen.

#### Level 1: union against the whole photo

All strokes of all used layers are simulated together as one black-ink plot
and scored with `measure_plot` against `photo.jpg`. The floors are the LUC-47
floors verbatim: SSIM >= 0.18, covered width >= 0.60, covered height >= 0.60,
bbox area >= 0.40, ink per 4x4 cell >= 0.0003 and dark/light tone ratio >= 2.0.

| measure | before LUC-85 | after LUC-85 | floor | result |
|---------|--------------:|-------------:|------:|--------|
| SSIM | 0.3183 | 0.3122 | 0.18 | pass |
| cov W | 0.999 | 0.999 | 0.60 | pass |
| cov H | 0.998 | 0.998 | 0.60 | pass |
| bbox | 0.997 | 0.997 | 0.40 | pass |
| ink min | 0.0427 | 0.0453 | 0.0003 | pass |
| tone ratio | 1.6074 | **1.6098** | 2.0 | recorded failure |

Five floors pass. LUC-85 re-measures the tone ratio at 1.6098; it stays within
the 0.05 tolerance that `KNOWN_UNION_FAILURES` pins for 1.6074, so the recorded
failure is unchanged. The tone ratio remains a real regression of the palette drawing:
the shipped Stabilo pens are 0.4 mm wide and their combined ink reaches too
much of the photo's light areas. Simulating the same strokes with the gate's
0.3 mm black pen gives a tone ratio of 2.2596 and SSIM 0.4645, so the miss is
driven by pen width, not by a second separation bug. The floor is **not**
lowered: `KNOWN_UNION_FAILURES` in the harness pins the 1.6074 measurement, the
test fails if it gets worse or if any other floor fails, and the finding is
reported to the Architect.

#### Level 2: region-relative measures per used pen

For pen `p`, the reference is its own separated channel. The region mask
`R = channel < 128` is thresholded on the **full** 1280x853 channel and then
mapped into the placement rectangle on the plot's 3.78 px/mm grid, so it is
never a shifted page-sized crop of the source. The drawing mask `I` is that
layer's simulated plot on the same grid. The tolerance is `R` dilated by half
the pen width (`round(0.4 / 2 * 3.78) = 1` px):

- **recall** = `|I & dilate(R)| / |R|` — a blank page scores 0;
- **precision** = `|I & dilate(R)| / |I|` — a random scribble scores low;
- **extent W / H** = drawing ink bbox divided by region bbox width/height;
- **bbox area** = overlap of the two bboxes divided by the region bbox;
- **cell recall** = of the 4x4 cells over the region bbox that contain region
  pixels, the share that also contain drawing ink.

`region px` is `|R|` on the plot grid after that mapping. Recall can exceed 1
when thick strokes ink pixels around a sparse region; that is expected and the
floors account for it. Per-layer SSIM (`SSIM*` below) is evidence only, printed
with all three baselines; it is not asserted. The blank page outscores the
light-blue and brown drawings on SSIM, which is why it cannot carry the gate.

Only three of the twelve palette pens produced strokes. After LUC-85, measured
with seed 42:

| layer | strokes | region px | mode | SSIM* | recall | prec | ext W | ext H | bbox | cell |
|-------|--------:|----------:|------|------:|-------:|-----:|------:|------:|-----:|-----:|
| `stabilo_88_light_blue` | 73 | 7702 | algorithm | 0.5610 | 1.1143 | 0.0739 | 1.000 | 1.013 | 0.997 | 0.923 |
| `stabilo_88_light_blue` | 73 | 7702 | blank | 0.7901 | 0.0000 | 0.0000 | 0.000 | 0.000 | 0.000 | 0.000 |
| `stabilo_88_light_blue` | 73 | 7702 | random | 0.2420 | 0.1532 | 0.0305 | 1.001 | 1.000 | 0.998 | 1.000 |
| `stabilo_88_light_blue` | 73 | 7702 | ideal | 0.9965 | 0.7466 | 0.0908 | 1.000 | 1.008 | 1.000 | 1.000 |
| `stabilo_88_brown` | 14 | 2866 | algorithm | 0.9591 | 1.0412 | 0.8444 | 0.946 | 0.973 | 0.915 | 0.700 |
| `stabilo_88_brown` | 14 | 2866 | blank | 0.9390 | 0.0000 | 0.0000 | 0.000 | 0.000 | 0.000 | 0.000 |
| `stabilo_88_brown` | 14 | 2866 | random | 0.7211 | 0.0356 | 0.0158 | 0.933 | 2.544 | 0.866 | 0.600 |
| `stabilo_88_brown` | 14 | 2866 | ideal | 0.9993 | 0.6172 | 0.9714 | 0.996 | 1.000 | 0.996 | 1.000 |
| `stabilo_88_black` | 375 | 156412 | algorithm | 0.7538 | 0.9802 | 0.9968 | 1.003 | 1.004 | 1.000 | 1.000 |
| `stabilo_88_black` | 375 | 156412 | blank | 0.5424 | 0.0000 | 0.0000 | 0.000 | 0.000 | 0.000 | 0.000 |
| `stabilo_88_black` | 375 | 156412 | random | 0.0871 | 0.4454 | 0.5189 | 1.003 | 0.998 | 0.996 | 1.000 |
| `stabilo_88_black` | 375 | 156412 | ideal | 0.9956 | 0.8504 | 0.9992 | 1.000 | 1.000 | 1.000 | 1.000 |

LUC-85's before/after numbers, re-measured with this region-relative gate (the
LUC-84 recall/outside-ink figures no longer apply because LUC-86 replaced that
measure with recall plus precision):

| layer | measure | before | after | floor |
|-------|---------|-------:|------:|------:|
| `stabilo_88_brown` | strokes | 5 | 14 | — |
| `stabilo_88_brown` | region px | 4324 | 2866 | — |
| `stabilo_88_brown` | recall | 0.3481 | **1.0412** | 0.30 |
| `stabilo_88_brown` | precision (was outside ink) | 0.8811 | 0.8444 | 0.50 |
| `stabilo_88_brown` | extent W | 0.893 | 0.946 | 0.60 |
| `stabilo_88_brown` | extent H | 0.373 | 0.973 | 0.30 |
| `stabilo_88_brown` | bbox | 0.333 | 0.915 | 0.30 |
| `stabilo_88_brown` | cell recall | 0.455 | 0.700 | 0.40 |
| `stabilo_88_light_blue` | recall / precision | 1.0748 / 0.0746 | 1.1143 / 0.0739 | 0.30 / 0.05 |
| `stabilo_88_black` | recall / precision | 0.9797 / 0.9968 | 0.9802 / 0.9968 | 0.55 / 0.60 |

Before LUC-85 brown already cleared every floor, but only just: five strokes
left extent H 0.373, bbox 0.333 and cell recall 0.455 close to their floors.
After the fix it covers its region strongly; precision falls slightly as the
stroke count grows but stays well above 0.50. Blue and black keep drawing the
same number of strokes and clear their floors with or without the fix.

#### Enforced region floors

The floors are derived from these blank/random/ideal runs: above both trivial
baselines, below the measured drawing, and no more than about 70% of the gap
from the higher baseline to the ideal where the ideal exceeds the baseline.
Where a random scribble already scores above a floor, recall and precision
carry the rejection of that baseline instead.

| pen | recall >= | precision >= | ext W >= | ext H >= | bbox >= | cell >= |
|-----|----------:|-------------:|---------:|---------:|--------:|--------:|
| `stabilo_88_light_blue` | 0.30 | 0.05 | 0.60 | 0.60 | 0.40 | 0.75 |
| `stabilo_88_brown` | 0.30 | 0.50 | 0.60 | 0.30 | 0.30 | 0.40 |
| `stabilo_88_black` | 0.55 | 0.60 | 0.60 | 0.60 | 0.40 | 0.75 |
| `stabilo_88_blue` | 0.30 | 0.10 | 0.60 | 0.60 | 0.40 | 0.75 |
| `stabilo_88_light_green` | 0.30 | 0.50 | 0.60 | 0.45 | 0.40 | 0.50 |
| `stabilo_88_purple` | 0.30 | 0.50 | 0.60 | 0.12 | 0.10 | 0.30 |

The last three rows are LUC-123's derived floors for new sparse layers; their
derivation is recorded in "Palette colour choice and the LUC-123 re-measurement"
below. A blank page fails recall and precision for every pen; a random scribble
fails both for light blue and brown and recall for black, and recall or
precision rejects it for the LUC-123 pens whose extent/bbox/cell scores are high.
The example floors in the task (recall 0.30, precision 0.50, extent 0.60, bbox
0.40, cell 0.75)
cannot all be used here: light blue's dark region is only 2.4% of the source,
so even the ideal channel scores 0.0939 precision and its drawing 0.0746;
brown's five strokes before LUC-85 spanned only 0.373 / 0.333 / 0.455 of extent
H / bbox / cell recall against an ideal of 0.694 / 0.693 / 0.909, while black's
random scribble reaches 0.4504 recall and 0.5183 precision. The per-pen floors
stay above the trivial baselines and below the measured drawing; they are not
lowered to let a blank or random page pass. LUC-85 closes brown's gap (extent H
0.973, bbox 0.915, cell recall 0.700) without changing these floors. The
light-blue precision gap and the black random baseline stay recorded as
limitations, out of scope here.

### Palette colour choice and the LUC-123 re-measurement (2026-11-26)

Hue-led separation changes which pen draws a colour region, not the ink density
inside it. On `tests/fixtures/images/saturation/muted_landscape.png` with
`--palette stabilo_88`, seed 42 and direct SVG export:

| run | `stabilo_88_light_green` | `stabilo_88_light_blue` | saturation report |
|-----|-------------------------:|------------------------:|-------------------|
| default | 10 strokes | 0 | none |
| `--palette-adapt` (factor 3.00) | 12 strokes | 0 | `Saturation factor: 3.00 (palette-adapted)` |
| `--saturation 2.0` | 12 strokes | 0 | `Saturation factor: 2.00 (manual)` |

Before LUC-123 the default field went to `stabilo_88_light_blue` and only an
opt-in boost moved it to green; the boost now still reports its factor and
still helps pixels below the C* 8 neutral cut-off. With `--no-auto-equalize`, a
C* 7 green swatch goes to `light_blue` by default and to `light_green` with
`--saturation 3.0`. Reproduce with
`uv run pytest tests/integration/test_saturation_boost.py -s`.

Re-measuring `photo.jpg` with `-s seed=42` on the LUC-86 harness gives:

| layer | mode | SSIM* | recall | prec | ext W | ext H | bbox | cell | strokes |
|-------|------|------:|-------:|-----:|------:|------:|-----:|-----:|--------:|
| `stabilo_88_blue` | algorithm | 0.7627 | 1.3189 | 0.2116 | 1.000 | 0.996 | 0.989 | 0.929 | 62 |
| `stabilo_88_blue` | blank | 0.7603 | 0.0000 | 0.0000 | 0.000 | 0.000 | 0.000 | 0.000 | 62 |
| `stabilo_88_blue` | random | 0.2695 | 0.2271 | 0.0583 | 1.001 | 0.992 | 0.992 | 1.000 | 62 |
| `stabilo_88_blue` | ideal | 0.9970 | 1.0035 | 0.1330 | 1.000 | 1.000 | 1.000 | 1.000 | 62 |
| `stabilo_88_light_green` | algorithm | 0.9536 | 0.8458 | 0.9647 | 1.003 | 0.584 | 0.584 | 0.636 | 20 |
| `stabilo_88_light_green` | blank | 0.8912 | 0.0000 | 0.0000 | 0.000 | 0.000 | 0.000 | 0.000 | 20 |
| `stabilo_88_light_green` | random | 0.6257 | 0.0652 | 0.0591 | 0.965 | 1.132 | 0.935 | 0.909 | 20 |
| `stabilo_88_light_green` | ideal | 0.9992 | 0.7963 | 0.9894 | 1.000 | 0.998 | 0.998 | 1.000 | 20 |
| `stabilo_88_purple` | algorithm | 0.9563 | 0.6667 | 0.5699 | 0.803 | 0.191 | 0.153 | 0.444 | 10 |
| `stabilo_88_purple` | blank | 0.9250 | 0.0000 | 0.0000 | 0.000 | 0.000 | 0.000 | 0.000 | 10 |
| `stabilo_88_purple` | random | 0.7366 | 0.0000 | 0.0000 | 1.009 | 1.301 | 0.937 | 0.556 | 10 |
| `stabilo_88_purple` | ideal | 0.9993 | 0.6157 | 0.6157 | 0.998 | 1.000 | 0.998 | 1.000 | 10 |
| `stabilo_88_black` | algorithm | 0.8012 | 0.9826 | 0.9944 | 1.003 | 1.004 | 1.000 | 1.000 | 282 |
| `stabilo_88_black` | blank | 0.5400 | 0.0000 | 0.0000 | 0.000 | 0.000 | 0.000 | 0.000 | 282 |
| `stabilo_88_black` | random | 0.1005 | 0.3861 | 0.4923 | 1.003 | 0.998 | 0.996 | 1.000 | 282 |
| `stabilo_88_black` | ideal | 0.9959 | 0.8536 | 0.9984 | 1.000 | 1.000 | 1.000 | 1.000 | 282 |

The union now clears every LUC-47 floor: SSIM 0.5116, covered W/H 0.999/0.998,
bbox 0.997, ink per cell 0.0007 and tone ratio 45.32. `KNOWN_UNION_FAILURES` is
therefore empty; the recorded tone failure is gone and a new union failure now
fails the test. Brown and light blue no longer own pixels and draw no layer;
blue, light green and purple are new used layers. Blue misses the *default*
precision floor (0.2116 < 0.50), and light green and purple miss the default
extent-H / bbox / cell floors. Their regions are sparse (2.6% and 3.8% of the
source), so the PFM draws only 20 and 10 strokes on their canvases.

The Architect's 2026-11-26 decision is to derive per-pen floors for these three
genuinely new layers with the existing LUC-86 rule (above both the blank and
random baselines, below the measured drawing, and no more than about 70% of the
gap from the higher baseline to the ideal), with recall and precision carrying
the rejection of a random scribble where the random baseline already scores
above a floor. Blue's own ideal channel only reaches 0.1330 precision, below
the 0.50 default, so that default was never attainable for it; light green's
and purple's ideal channels clear the defaults but their sparse drawings do
not. The derived floors are:

| pen | measure | default | random | ideal | algorithm | derived floor |
|-----|---------|--------:|-------:|------:|----------:|--------------:|
| `stabilo_88_blue` | precision | 0.50 | 0.0583 | 0.1330 | 0.2116 | **0.10** |
| `stabilo_88_light_green` | extent H | 0.60 | 1.132 | 0.998 | 0.5844 | **0.45** |
| `stabilo_88_light_green` | cell recall | 0.75 | 0.909 | 1.000 | 0.6364 | **0.50** |
| `stabilo_88_purple` | extent H | 0.60 | 1.301 | 1.000 | 0.1910 | **0.12** |
| `stabilo_88_purple` | bbox area | 0.40 | 0.937 | 0.998 | 0.1528 | **0.10** |
| `stabilo_88_purple` | cell recall | 0.75 | 0.556 | 1.000 | 0.4444 | **0.30** |

Blue's precision floor is capped by `random + 0.7 x (ideal - random) = 0.1106`;
0.10 is below that cap and above random's 0.0583. For light green and purple
the random baseline already exceeds the new extent/bbox/cell floors, so recall
and precision reject it (light green random 0.0652 / 0.0591, purple 0.0000 /
0.0000). A test asserts that every pen's ideal baseline clears every floor
enforced on that pen, so no floor can sit above what its own channel can reach.
Every default floor and every existing override (light blue, brown, black) is
unchanged: no floor was lowered. Widening the LUC-85 sparse-canvas PFM trigger
(`_NEARLY_BLANK_MEAN`, `pfm_sketch_lines`) is a separate follow-up, out of scope
here. Reproduce with `uv run pytest tests/integration/test_multi_pen_gate.py -s`.

### Colour fixture acceptance (LUC-124, 2026-11-26)

This is the end-to-end acceptance for LUC-115: palette separation must use many
pens, not three. The committed set is
`tests/fixtures/images/colour/` — `colour_blocks.png` (synthetic blocks with
one clear region per Stabilo hue family) and `christmas_tree.jpg` (a CC0
Wikimedia Commons crop). Sources, author, licence and exact fetch/crop commands
are in [`tests/fixtures/images/colour/README.md`](../tests/fixtures/images/colour/README.md).
The test is `tests/integration/test_colour_palette.py`; it uses the committed
photo, so it never touches the network.

```bash
uv run pytest tests/integration/test_colour_palette.py -s
```

The exact conversion in both cases, with A4 (10 mm margin) defaults, is:

```bash
uv run penpath convert tests/fixtures/images/colour/colour_blocks.png \
  -o /tmp/colour_blocks.svg --palette stabilo_88 -s seed=42 --no-vpype --quiet
uv run penpath convert tests/fixtures/images/colour/christmas_tree.jpg \
  -o /tmp/christmas_tree.svg --palette stabilo_88 -s seed=42 --no-vpype --quiet
```

`colour_blocks.png` yields **7 distinct used pens** (red, green, yellow,
orange, blue, purple and black); the test requires at least 6. For the tree,
the test computes each pen's share with `separate_palette` — the same
assignment the drawing uses — and requires more than 2.0% for red, yellow and
black, and for green as `stabilo_88_green` plus `stabilo_88_light_green`. It
then requires a non-empty SVG layer for each of those pens, so a passing test
proves drawn layers rather than assignment alone.

| pen | share of tree pixels | 2.0% floor |
|-----|---------------------:|-----------:|
| `stabilo_88_red` | 3.87% | pass |
| `stabilo_88_yellow` | 9.65% | pass |
| `stabilo_88_black` | 6.10% | pass |
| `stabilo_88_green` + `stabilo_88_light_green` | 7.85% | pass |

Simulated-plot previews of both conversions are committed under
[`docs/images/luc-124/`](../images/luc-124/):

| fixture | preview | what it shows |
|---------|---------|---------------|
| `colour_blocks.png` | [blocks.jpg](../images/luc-124/blocks.jpg) | Seven hatched squares in red, green, yellow, orange, blue, purple and black, separated by white gaps. |
| `christmas_tree.jpg` | [tree.jpg](../images/luc-124/tree.jpg) | A tree in many inks: green foliage, a large red tinsel region, gold and light-blue areas, and black wall and shadow detail. |

The tree is the 1280 px Commons thumbnail cropped to `x=140..1060`,
`y=120..1280` and saved as 920x1160 JPEG at quality 85 (426 KB). The crop was
chosen to grow the red decorations' share; the 2.0% floor was **not** lowered
and no pixels were faked. Rebuild the synthetic blocks with:

```bash
uv run python tests/fixtures/images/colour/generate_colour.py
```

It uses only NumPy and Pillow, takes no random input, and a unit test checks
that the committed PNG matches a fresh regeneration.

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

### Large input performance (LUC-48 part 3)

The budget case is a 12 MP photo (4080x3072 px) converted for 190x190 mm paper
with a 0.4 mm pen: under about **30 s on the VPS**. Reproduce it with:

```bash
uv run python tests/benchmarks/benchmark_convert.py
uv run python tests/benchmarks/benchmark_convert.py --budget 120
uv run python tests/benchmarks/benchmark_convert.py --image photo.jpg --output plot.svg
```

The script is run by path, not through pytest. It builds a deterministic
4080x3072 greyscale image when `--image` is not given, drives `penpath convert`
through the real CLI entry point with `--quiet`, and prints one line per stage,
the wall-clock total and the budget. Exit 0 means the total is within the
budget; exit 1 means it exceeded the budget or the conversion failed.

Measured on the VPS (Ubuntu 24.04, aarch64, Python 3.14, vpype 1.15):

| Stage | Time (s) |
|-------|---------:|
| Loading image | 0.15 |
| Downscaling image | 0.23 |
| Applying filters | 0.00 |
| Generating lines (PFM) | 3.89 |
| Optimizing geometry | 5.44 |
| Exporting SVG | 1.78 |
| **Total (wall clock)** | **11.49** |
| Budget | 30.00 |

A repeat on the shared VPS while other jobs ran took 13.09 s; an earlier run
with five concurrent jobs took 21.32 s. All three are inside the 30 s budget.

`tests/integration/test_performance.py` converts a 1200x900 image with the same
paper and pen and asserts a generous **120 s CI bound** so a slow shared runner
cannot make CI flaky; the whole test module ran in 15 s on the VPS. The 30 s
figure remains the VPS budget, enforced by the benchmark script above. The
smaller image proves the same point because the working resolution does not
depend on the input size: only load and downscale grow with source pixels.

This is fast now because the working resolution is fixed by paper and pen
(`paper_longest_side_mm / pen_width_mm`, clamped to 256-1024 px): a 190 mm sheet
and a 0.4 mm pen draw at 475 px on the longest side whether the source is 4 MP
or 12 MP. The PFM receives its pixel settings in working-image pixels, so each
stroke covers the same fraction of the canvas and the amount of ink does not
depend on the source size. Before that correction, scaling the settings by the
source ratio (0.116 for 12 MP) shrank the maximum stroke to about 5 px, hit the
10,000-stroke cap, and took 59 s in the PFM plus over 2 min in geometry
optimization; the 30 s budget was missed.

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
3. Manual smoke test: `penpath convert tests/fixtures/images/reference/photo.jpg -o /tmp/test.svg`
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

---

## Basic shapes gate (LUC-75)

Parts 1 and 2 of LUC-75 define and measure a small gate for six simple shapes.
Part 3 (LUC-78) turns those measurements into assertions in
`tests/integration/test_basic_shapes.py`, which runs on every pull request. The
six shapes are converted once per test session through the shared fixture; each
shape and both baselines are then checked against the table below. That table
is copied from `SHAPE_THRESHOLDS` in `tests/integration/basic_shapes_gate.py`,
the one place to change the enforced numbers.

### Fixtures and format

The fixtures live in `tests/fixtures/images/basic/` and are plain-text PBM (P1)
files: the first line is `P1`, the second `64 64`, and the 64 following lines
hold one character per pixel (`1` black, `0` white). An agent that cannot open
a raster image can read every pixel as text. They are test data only; `.pbm` is
not a product input format.

| Fixture | What it is | What it catches |
|---------|------------|-----------------|
| `black_square.pbm` | Black square, rows/columns 19:44 (25x25), centred on white | Filling a compact solid area in the middle of the canvas |
| `white_square.pbm` | The same square in white, on a black canvas | Inverted tone: 85% of the canvas is black |
| `black_disc.pbm` | Black disc, centre (31.5, 31.5), radius `64 * 0.35` | Curved edges and even coverage of a round shape |
| `horizontal_line.pbm` | Black bar, rows 31:33 (2 px), columns 6:57 (51 px) | Very thin features: a shape only two pixels tall |
| `checkerboard.pbm` | 8x8 cells of 8x8 px, black when row + col is even | Sharp alternating edges and repeated detail |
| `triangle.pbm` | Filled triangle, apex up, spanning `32 +/- int(y * 0.45)` at row y | Slanted edges and growing width towards the base |

### Harness and pipeline

`tests/integration/basic_shapes_gate.py` loads each PBM with Pillow and resizes
it to **400x400 with nearest neighbour** before running the CLI. This keeps the
same pixel scale as the reference images in LUC-47: at the native 64x64 the
algorithm's ink purity on the black square drops from 0.99 to 0.56. The CLI
reads only PNG/JPEG/TIFF/BMP, so the harness writes a PNG twin of each fixture
into a temporary folder. The command it runs is:

```bash
penpath convert shape.png -o plot.svg --pfm-setting seed=42
```

Settings are the shipped defaults: A4 paper with a 10 mm margin, the default
0.3 mm black pen, 96/25.4 px per mm, vpype 1.15 on the default export path and
seed 42. The harness reads the recorded placement from the SVG, parses the
strokes and simulates the plot the same way `penpath evaluate` does.

- **likeness**: `compute_likeness` (SSIM at 256x256, blur sigma 1.5) on the
  simulated plot and the original in the placement crop.
- **ink_outside**: share of simulated ink pixels darker than 128 that fall
  outside the original's dark region (luminance < 128), with the original
  resized to the placement crop.
- **dark_coverage**: share of the original's dark pixels that receive ink.
- **tone_ratio**: ink density in the darkest quarter divided by ink density in
  the lightest quarter of the original, smoothed by one ink pixel over the
  crop area (the same measure as the LUC-47 gate).
- **drawing_length_mm / strokes / lifts**: `compute_machine_cost` with
  `include_pen_up=True`, as reported by `penpath evaluate`.
- **blank**: an SVG with the same page and placement metadata but no strokes.
  **random**: as many seeded two-point strokes as the real output had, with
  endpoints uniform in the placement rectangle. Both are measured identically
  for every shape.

Reproduce the table with:

```bash
uv run pytest tests/integration/test_basic_shapes.py -vs
```

### Measured numbers (2026-11-25, shipped `max_fill=80`)

| shape | mode | likeness | ink_outside | dark_coverage | tone_ratio | length mm | strokes | lifts |
|-------|------|---------:|------------:|--------------:|-----------:|----------:|--------:|------:|
| `black_square` | algorithm | 0.8407 | 0.010 | 0.404 | 31987.00 | 11371.2 | 38 | 37 |
| `black_square` | blank | 0.8082 | 1.000 | 0.000 | 1.00 | 0.0 | 0 | 0 |
| `black_square` | random | 0.5813 | 0.710 | 0.050 | 1.21 | 4063.3 | 38 | 37 |
| `white_square` | algorithm | 0.1621 | 0.002 | 0.415 | 1.18 | 66188.4 | 216 | 215 |
| `white_square` | blank | 0.1298 | 1.000 | 0.000 | 1.00 | 0.0 | 0 | 0 |
| `white_square` | random | 0.0320 | 0.273 | 0.110 | 0.85 | 21477.9 | 216 | 215 |
| `black_disc` | algorithm | 0.5977 | 0.002 | 0.413 | 11178.08 | 29710.5 | 95 | 94 |
| `black_disc` | blank | 0.5464 | 1.000 | 0.000 | 1.00 | 0.0 | 0 | 0 |
| `black_disc` | random | 0.3266 | 0.394 | 0.098 | 2.50 | 9951.2 | 95 | 94 |
| `horizontal_line` | algorithm | 0.9721 | 0.000 | 0.350 | 4416.00 | 1454.9 | 6 | 5 |
| `horizontal_line` | blank | 0.9404 | 1.000 | 0.000 | 1.00 | 0.0 | 0 | 0 |
| `horizontal_line` | random | 0.8721 | 0.947 | 0.010 | 1.04 | 721.7 | 6 | 5 |
| `checkerboard` | algorithm | 0.5190 | 0.020 | 0.415 | 1271.99 | 38916.2 | 148 | 147 |
| `checkerboard` | blank | 0.2650 | 1.000 | 0.000 | 1.00 | 0.0 | 0 | 0 |
| `checkerboard` | random | 0.1224 | 0.501 | 0.092 | 1.01 | 14929.3 | 148 | 147 |
| `triangle` | algorithm | 0.5656 | 0.004 | 0.414 | 6516.84 | 33081.8 | 109 | 108 |
| `triangle` | blank | 0.5175 | 1.000 | 0.000 | 1.00 | 0.0 | 0 | 0 |
| `triangle` | random | 0.2612 | 0.492 | 0.083 | 1.39 | 11251.5 | 109 | 108 |

LUC-89's `max_fill=80` default clamps the fixtures' pure black to luminance 51,
so every shape draws fewer strokes and inks less of its dark region. Before →
after on the algorithm rows: likeness 0.8471 → 0.8407 (black square), 0.5602 →
0.5190 (checkerboard), 0.5736 → 0.5656 (triangle); dark coverage 0.502 → 0.404,
0.509 → 0.415 and 0.510 → 0.414 for those same three; pen-down length 15624.5 →
11371.2 mm on the black square and 89579.3 → 66188.4 mm on the white square.
The blank and random baselines do not change. The floors below were re-derived
from these numbers with the same rules; the unchanged `tone_ratio` and
`ink_outside` bounds still reject every baseline. The last digits of
`tone_ratio` and `drawing_length_mm` move in the fourth decimal between runs
because the mm SVG layout rounds coordinates; the caps have a factor of two of
headroom for that reason.

### Enforced gate (LUC-78, re-derived for LUC-89 on 2026-11-25)

`test_basic_shapes.py` asserts every cell below for the algorithm's drawing,
one test per shape, plus `num_strokes >= 1` for every shape. Two more tests
prove the gate is meaningful: the blank page fails `dark_coverage` for every
shape, and the random scribble fails `ink_outside` for every shape; both also
fail the `likeness` floor. Without them a threshold could pass for every
possible drawing. These numbers are mirrored by `SHAPE_THRESHOLDS` in
`tests/integration/basic_shapes_gate.py`, the one place to change them.

| shape | likeness >= | ink_outside <= | dark_coverage >= | tone_ratio >= | drawing_length_mm <= | num_strokes <= | num_lifts <= |
|-------|------------:|---------------:|-----------------:|--------------:|---------------------:|---------------:|---------------:|
| `black_square` | 0.82 | 0.10 | 0.35 | 2.0 | 23000 | 80 | 80 |
| `white_square` | 0.14 | 0.12 | 0.36 | 1.05 | 135000 | 440 | 440 |
| `black_disc` | 0.57 | 0.10 | 0.36 | 2.0 | 60000 | 200 | 200 |
| `horizontal_line` | 0.96 | 0.25 | 0.30 | 2.0 | 3000 | 12 | 12 |
| `checkerboard` | 0.49 | 0.20 | 0.36 | 2.0 | 78000 | 300 | 300 |
| `triangle` | 0.54 | 0.10 | 0.36 | 2.0 | 67000 | 220 | 220 |

And for every shape: `num_strokes >= 1`.

How each number was chosen:

- **likeness**: `max(higher of blank and random + 0.02, measured - 0.02)`,
  rounded down to two decimals. For example `black_square`: blank 0.8082 +
  0.02 = 0.8282, measured 0.8407 - 0.02 = 0.8207, floor 0.82.
  `checkerboard`: measured 0.5190 - 0.02 = 0.4990 dominates its blank 0.2650
  and random 0.1224 baselines, floor 0.49. `horizontal_line`: blank 0.9404 +
  0.02 = 0.9604, measured 0.9721 - 0.02 = 0.9521, floor 0.96. Every blank page
  and every random scribble fails this floor.
- **ink_outside**: caps unchanged from the original decision (0.10, 0.12, 0.10,
  0.25, 0.20, 0.10 in table order). The algorithm inks at most 0.020 outside a
  shape; a blank page reports 1.0 and a random scribble at least 0.273, so
  these caps are what reject both baselines.
- **dark_coverage**: `max(higher baseline + 0.05, measured - 0.05)`, rounded
  down to two decimals. The measured value minus 0.05 dominates for every
  shape (e.g. `white_square` 0.4148 - 0.05 = 0.3648, floor 0.36;
  `horizontal_line` 0.3502 - 0.05 = 0.3002, floor 0.30). A blank page inks
  nothing (0.0) and a random scribble at most 0.110, so both fail every shape.
- **tone_ratio**: floors unchanged from the original decision (2.0, except
  1.05 for `white_square`). The algorithm clears them with room; the random
  scribble reaches 2.50 on `black_disc`, the one baseline that passes a tone
  floor, but that scribble fails both the likeness floor and the ink-outside
  cap.
- **machine cost**: per-shape caps at twice the measured value, rounded to a
  round number — `black_square` 11371.2 mm → 23000, 38 strokes → 80, 37 lifts
  → 80; `white_square` 66188.4 → 135000, 216 → 440, 215 → 440; `black_disc`
  29710.5 → 60000, 95 → 200, 94 → 200; `horizontal_line` 1454.9 → 3000, 6 →
  12, 5 → 12; `checkerboard` 38916.2 → 78000, 148 → 300, 147 → 300;
  `triangle` 33081.8 → 67000, 109 → 220, 108 → 220. The old global rule
  "`num_lifts <= 5` for every shape" is **withdrawn**: it described the
  pre-LUC-53 algorithm, not the shape.

The six numbers above are the ones in `SHAPE_THRESHOLDS`; keep the two in sync.
The next section records the withdrawn pre-LUC-53 target and is not enforced.

### Withdrawn pre-LUC-53 target (recorded, not enforced)

The first version of this gate was measured on commit `ac3206d`, before LUC-53
("rewrite Sketch Lines to reference PFM semantics", merged 2026-11-25) replaced
the drawing algorithm. The old algorithm produced a few long meandering
strokes; the new one produces many short segments that vpype chains into long
paths. Running this same harness on `ac3206d` reproduces the published numbers
(black square likeness 0.9339, tone 121.09, 4 strokes; blank 0.8082; random
0.7680), so those numbers describe an algorithm that no longer exists. They are
kept here the way the withdrawn LUC-47 SSIM floors above are kept.

| shape | likeness >= | ink_outside <= | dark_coverage >= | tone_ratio >= | drawing_length_mm <= |
|-------|------------:|---------------:|-----------------:|--------------:|---------------------:|
| `black_square` | 0.87 | 0.10 | 0.70 | 2.0 | 225000 |
| `white_square` | 0.04 | 0.12 | 0.12 | 1.05 | 125000 |
| `black_disc` | 0.60 | 0.10 | 0.45 | 2.0 | 235000 |
| `horizontal_line` | 0.96 | 0.25 | 0.70 | 2.0 | 125000 |
| `checkerboard` | 0.28 | 0.20 | 0.10 | 2.0 | 80000 |
| `triangle` | 0.55 | 0.10 | 0.30 | 2.0 | 195000 |

Plus the withdrawn global rule `num_lifts <= 5` for every shape. The old
`white_square` likeness floor of 0.04 was a smoke check: the old algorithm
inked only 20% of the dark region, scored 0.073 against the blank page's 0.130,
and put 5% of its ink outside the square. Those thresholds are **not** used by
the current gate and the current algorithm fails several of them (with the
LUC-89 default, black square likeness 0.8407 < 0.87, coverage 0.404 < 0.70 and
37 lifts > 5; horizontal line coverage 0.350 < 0.70).

### Open limitations of the LUC-53 algorithm

1. **SSIM has almost no headroom on a mostly-white image.** A blank page already
   scores 0.8082 on `black_square`, 0.9404 on `horizontal_line`, 0.5175 on
    `triangle` and 0.5464 on `black_disc`; the algorithm beats it by only 0.032
    to 0.051. The likeness floor is a smoke check that rejects a blank page and
   a scribble; the real guards are `ink_outside`, `dark_coverage` and
   `tone_ratio`.
2. **The tone measure degenerates on `white_square`.** 85% of that fixture's
   pixels are black, so the lightest quarter is black as well and the ratio is
   `1 / 0.85` by construction. Today's 1.18 is exactly what the ideal plot
   scores too, so the 1.05 floor is a smoke check on that shape.
3. **Machine cost went up for simple shapes.** With the LUC-89 default a solid
   black square needs 38 strokes and 37 pen lifts (the pre-LUC-53 algorithm
   drew it in 4 strokes), and the white square 216 strokes and 215 lifts. The
   ink stays inside the shape, but the plot is many separate paths.
4. **The plot is lighter than the source.** The algorithm inks about 0.35 to
   0.42 of the dark region on every shape against 0.984 for the pre-LUC-53
   black square, and the black square's likeness fell from 0.9339 to 0.8407.

Points 3 and 4 are candidate work for a later task. They are recorded here, not
fixed here. The flaw described in the first version of this task *is fixed*:
`white_square` is no longer lighter than the original. It now inks 41% of the
dark region (was 20%) and scores 0.1621, above the blank page's 0.1298, so the
0.14 likeness floor is a real floor again.

### Previews

Greyscale 600 px side-by-side previews — the 400x400 fixture on the left, the
simulated plot cropped to its placement on the right — are committed under
[`docs/images/luc-75/`](../images/luc-75/). They are evidence for reviewers,
not golden files; no test compares against them.

| shape | preview |
|-------|---------|
| `black_square` | [black_square.png](../images/luc-75/black_square.png) |
| `white_square` | [white_square.png](../images/luc-75/white_square.png) |
| `black_disc` | [black_disc.png](../images/luc-75/black_disc.png) |
| `horizontal_line` | [horizontal_line.png](../images/luc-75/horizontal_line.png) |
| `checkerboard` | [checkerboard.png](../images/luc-75/checkerboard.png) |
| `triangle` | [triangle.png](../images/luc-75/triangle.png) |