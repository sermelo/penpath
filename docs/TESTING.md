# penpath Testing Guide

**Status**: Mandatory QA process
**Goal**: Prove the image → SVG → G-code path works, and keep it working

This guide says how to run the tests and lists every gate the suite enforces.
Per-task measurement histories were removed; the evidence lives in the task
threads and in git history. Measurement-only work (Patch Hatch, TSP, Squiggle,
Engraving) is not a gate and is deliberately absent from the table below.

## Test layout

- `tests/unit/` — fast, isolated checks of functions in `src/penpath`.
- `tests/integration/` — the full pipeline, the real CLI, file I/O and vpype.
- `tests/fixtures/images/` — reference photos and generated basic-shape fixtures.
- `tests/fixtures/golden/` — checked-in SVG and G-code outputs, compared byte for
  byte.
- `tests/fixtures/projects/` and `tests/fixtures/profiles/` — sample inputs.
- `tests/benchmarks/` — scripts run by path, not collected by pytest.

`pyproject.toml` registers the `slow` marker and sets
`addopts = "-vs --strict-markers -m 'not slow'"`. A bare pytest run is fast;
an explicit `-m` replaces that default rather than adding to it. Install the
tools once with `uv sync --extra dev --extra vpype` (vpype is needed by the
integration tests). All commands below start at the repository root.

The reference images are `tests/fixtures/images/reference/circle.png`,
`gradient.png`, `sphere.png`, `face.jpg`, `photo.jpg` and `santa.jpg`. Basic
shapes are generated PBM files under `tests/fixtures/images/basic/`, with their
pixel counts pinned in `tests/integration/test_basic_shapes.py`.

## How gates are measured

Likeness gates render the shipped defaults through the same image → SVG →
strokes → simulator path a user gets from `penpath convert` and `penpath
evaluate`, then compare the simulated plot with the source image. They assert
SSIM and coverage, bbox area, ink spread and tone measures; a blank page and a
random scribble must fail. Cost gates read the same strokes and bound pen-up
travel, pen lifts, stroke counts and tiny segments. Every gate fixes the seed
(42) and uses the shipped settings: a floor is never met by special test-only
settings. Golden tests compare output bytes, and CLI tests assert exit codes
rather than parsing human-readable output.

## Run the tests

### Fast run (default)

```bash
uv run pytest
```

Runs only fast tests: this is what a pull request runs.

### Unit tests only

```bash
uv run pytest tests/unit -q
```

CI runs the same selection with a coverage floor:

```bash
uv run pytest tests/unit -vs -m 'not slow' --cov=penpath --cov-fail-under=75 --cov-report=term-missing
```

### Integration tests

```bash
uv run pytest tests/integration -q
```

CI splits the fast Sketch Lines gate helper checks from the rest of integration:

```bash
uv run pytest tests/integration/test_gate_measures.py -vs -m 'not slow'
uv run pytest tests/integration -vs -m 'not slow' --ignore=tests/integration/test_sketch_lines_gate.py --ignore=tests/integration/test_gate_measures.py
```

### Slow quality gates

```bash
uv run pytest -m slow
uv run pytest -m 'slow or not slow'
```

The first runs only the render-and-assert quality gates; the second runs
everything, as CI on `main` and the nightly runner do. A single gate can also be
run by path, for example `uv run pytest tests/integration/test_hatch_gate.py -s`.
The `slow` marker is reserved for tests that render reference images and assert
likeness, readability or plot-cost floors.

### Nightly workload

```bash
bash scripts/nightly.sh
```

`tests/unit/test_ci_config.py` asserts this exact command appears in README.md
and in this file. The script syncs the `dev` and `vpype` extras, times one
`penpath convert` of `tests/fixtures/images/reference/photo.jpg` with seed 42,
then runs `uv run pytest tests/unit tests/integration -vs -m 'slow or not slow'`.
It stops at the first failed command. On a host without GNU time, use
`PENPATH_NIGHTLY_TIME=gtime bash scripts/nightly.sh`.

### Coverage, types and lint

```bash
uv run pytest --cov=penpath --cov-report=term-missing
uv run mypy --strict src
uv run ruff check src tests
uv run ruff format --check src tests
```

The coverage-report job runs `uv run pytest tests/unit --cov=penpath --cov-report=xml
--cov-report=term-missing`; it reports but does not block a pull request. The
blocking CI jobs are `Lint & Format`, `Type Check (mypy)`, `Unit Tests`,
`Integration Tests` and `Build Wheel`, plus the `Quality Gates (Slow)` job on
`main`.

## Enforced gates

One row per gate the suite actually enforces. Thresholds are copied from the
test constants; fixtures and bounds come from the same modules. Withdrawn
targets and measured values are not gates and are not listed. In the last
column, paths are arguments to `uv run pytest` from the repository root;
`(slow)` means the test needs `-m slow` or its explicit path to be selected.

| Gate | Fixtures / scope | Enforced thresholds | Command or marker |
|------|------------------|---------------------|-------------------|
| Sketch Lines likeness (LUC-47) | `circle.png`, `gradient.png`, `sphere.png`, `face.jpg`, `photo.jpg`; A4 210x297 mm, margin 10 mm, 0.3 mm pen, seed 42, 4x4 grid; blank and random baselines | SSIM floors: circle 0.53, gradient 0.47, sphere 0.79, face 0.57, photo 0.18; covered width/height 0.60; bbox area 0.40; ink per 4x4 cell 0.0003; tone ratio 2.0; white ink < 0.01; dark-decile ink < 0.85; rank >= 0.75 (blank and random < 0.75); dark-tile ink 0.20–0.92; dark tiles >= 8 | `tests/integration/test_sketch_lines_gate.py -s` (slow) |
| Sketch Lines photo readability (LUC-128) | `face.jpg`, `photo.jpg`; medium pen, 180x180 mm, 10 px/mm preview | dark textured tiles >= 8; rank >= 0.75; max dark-tile ink 0.20–0.92 | `tests/integration/test_sketch_lines_readability.py -s` (slow) |
| Basic shapes (LUC-75/78) | Six 64x64 PBM fixtures rendered at 400x400, seed 42, A4 / 0.3 mm; blank and random baselines | Fields per shape: likeness min / ink-outside max / dark-coverage min / tone-ratio min / drawing length mm max / strokes max / lifts max. `black_square` 0.82/0.10/0.35/2.0/23000/80/80; `white_square` 0.14/0.12/0.36/1.05/135000/440/440; `black_disc` 0.57/0.10/0.36/2.0/60000/200/200; `horizontal_line` 0.96/0.25/0.30/2.0/3000/12/12; `checkerboard` 0.49/0.20/0.36/2.0/78000/300/300; `triangle` 0.54/0.10/0.36/2.0/67000/220/220; strokes >= 1 | `tests/integration/test_basic_shapes.py -s` (slow subset) |
| Max fill calibration (LUC-89) | `dark_figure`, `light_figure`, `gradient`, 400x400; sweep 60/70/80/90/100; seed 42; `--no-auto-equalize` | default `max_fill` 80; capped ink < 0.9 x full; capped dark ink > 0.05; capped SSIM > full SSIM - 0.03; the three tone bands strictly descend; CLI `max_fill=0` and `max_fill=101` exit 2 | `tests/integration/test_max_fill.py -s` (slow subset) |
| Multi-pen per-layer (LUC-50/123) | `photo.jpg`, `stabilo_88` palette, A4 margin 10 mm, `--background-method global --no-key-layer`, seed 42, 4x4 grid; union and per-pen regions | Union: SSIM 0.18, width 0.60, height 0.60, bbox 0.40, ink/cell 0.0003, tone ratio 2.0. Region defaults: recall 0.30, precision 0.50, extent width/height 0.60, bbox 0.40, cell recall 0.75. Overrides: `light_blue` precision 0.05; `brown` height 0.30/bbox 0.30/cell 0.40; `black` recall 0.55/precision 0.60; `blue` precision 0.10; `light_green` height 0.45/cell 0.50; `purple` height 0.12/bbox 0.10/cell 0.30. Sparse-layer pins `abs=0.02` | `tests/integration/test_multi_pen_gate.py -s` (slow subset) |
| Contour (LUC-146) | `face.jpg`, `photo.jpg`, `santa.jpg`; `contour_portrait`, `contour_silhouette`; A4, 0.3 mm pen, DPI 96, max resolution 512, 2 px edge tolerance, 0.5 mm tiny segment | edge alignment >= 0.60; coverage width/height >= 0.60; area >= 0.40; strokes <= 250; length <= 28000 mm; tiny segments <= 10 and <= 0.05 fraction; santa preview 1188x840 with ink | `tests/integration/test_contour_gate.py -s` (slow) |
| Sketch Squares (LUC-149) | `face.jpg`, `photo.jpg`, `santa.jpg`; presets `coarse`, `fine`, `crosshatch-grid`; A4, 0.3 mm pen, DPI 96, max resolution 384, 3 px dark tolerance; blank and random baselines | dark recall >= 0.19; ink precision >= 0.67; coverage width/height/area >= 0.94; strokes <= 600; length <= 170000 mm; tiny segments <= 25 and <= 0.01 fraction | `tests/integration/test_sketch_squares_gate.py -s` (slow) |
| Stipple (LUC-154) | `circle.png`, `gradient.png`, `sphere.png`, `face.jpg`, `photo.jpg`, `santa.jpg`; `stipple_default`, 190x190 mm margin 10 mm, 0.4 mm pen, seed 42, 4x4 grid; blank, random and ideal baselines | width/height >= 0.70; bbox area >= 0.51; ink/cell >= 0.0004; tone ratio >= 8.0; length <= 20000 mm; travel <= 14000 mm; lifts <= 10000; tiny segments 0 and 0 fraction; strokes <= `max_strokes`; two-pen midpoint share >= 0.90 | `tests/integration/test_stipple_gate.py -s` (slow) |
| Spiral Sawtooth (LUC-138/203) | `face.jpg`, `photo.jpg`, `santa.jpg`; presets `spiral_sawtooth`, `:fine`, `:bold`, `:parabolic`; shapes `circle`, `ellipse`, `cover`; 190x190 mm, margin 0, 0.4 mm pen, seed 42 | width >= 0.85; height >= 0.80; bbox >= 0.70; ink/cell >= 0.0025; tone ratio >= 0.60; dark textured ink >= 0.65; lifts <= 3; length <= 100000 mm; tiny segments 0 and 0 fraction; raw and final strokes 1 and lifts 0 | `tests/integration/test_spiral_gate.py -s` (slow) |
| Hatch (LUC-167) | `face.jpg`, `photo.jpg`, `gradient.png`, `sphere.png`; `hatch:default` and `hatch:crosshatch`; A5 margin 10 mm, 0.4 mm pen, seed 42; blank, random and ideal baselines | face: SSIM 0.48, width/height/area 0.94, ink spread 0.017, tone ratio 5.0, rank 0.75, dark-textured ink max 0.75. photo: SSIM 0.54, width/height/area 0.94, ink spread 0.017, tone ratio 1.5, rank 0.86, dark-textured ink max 0.75. 8 gradient strips spread > 0.01 with ends >= 0.5 apart; spacing >= PEN_WIDTH_MM (0.4) - SPACING_TOLERANCE_MM (0.01); photo lifts x 5 <= Sketch Lines lifts; working width 525 px; wall time < 30 s; seeded SVG byte-identical | `tests/integration/test_hatch_gate.py -s` (slow) |
| Compare contact sheet (LUC-141) | Synthetic 64x64 dark/light image; `penpath compare --dpi=2 --max-resolution=64 --columns=3` | size `(398, 16 + rows*146 + (rows-1)*8)` with `rows = ceil(entries/3)`; PNG/RGB; stdout empty; stderr carries output path, ` px, ` and `N entries`; nonpositive options exit 2; bad image exit 1; a failed entry still writes the sheet | `tests/integration/test_compare_cli.py` (fast) |
| Performance and render budgets | 4080x3072 benchmark on 190x190 mm / 0.4 mm; 1200x900 CLI test; A5 148x210 mm at 3 and 50 px/mm | benchmark budget 30 s (exit 1 over); CI convert bound 120 s; `MAX_RENDER_MEGAPIXELS` 40.0; A5 at 3 px/mm gives (444, 630); 50 px/mm gives (7400, 10500) and is refused before allocation | `tests/benchmarks/benchmark_convert.py` (by path); `tests/integration/test_performance.py`, `tests/integration/test_render_budget.py` (fast) |
| Golden files | Checked-in SVG for `convert` and background masking; G-code for `generic`, `multi_pen`, `ramped` and `aquila` profiles | produced bytes equal golden bytes; regenerate only with `--update-golden` or `PENPATH_UPDATE_GOLDEN=1` | `tests/integration/test_convert_core_golden.py`, `test_background_masking.py`, `test_gcode_golden.py`, `test_gcode_cli.py` (fast) |
| CLI exit codes | CLI and API commands across the unit and integration suites | 0 success; 1 runtime error; 2 usage error; 3 validation error | unit CLI tests plus `tests/integration/test_gcode_cli.py`, `test_preview_evaluate.py`, `test_compare_cli.py` (fast) |

Older per-task gate links still resolve to this table:

<a id="sketch-lines-likeness-gate-luc-47"></a>
<a id="sketch-squares-readability-and-plot-cost-gate-luc-149-2026-11-27"></a>
<a id="contour-readability-and-plot-cost-gate-luc-146-2026-11-27"></a>
<a id="stipple-likeness-and-plot-cost-gate-luc-154-2026-11-27"></a>
<a id="hatch-acceptance-gate-luc-167-2026-11-27"></a>
<a id="contact-sheet-readability-luc-141-2026-11-27"></a>
</content>
