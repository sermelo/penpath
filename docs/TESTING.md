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
| `test_seed_determinism` | Same seed → identical SVG (byte-for-byte after normalization) |
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