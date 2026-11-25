# penpath Technical Plan (MVP)

**Status**: Draft for PM approval  
**Based on**: `docs/FEATURES.md` (board-accepted MVP scope)  
**Goal**: Smallest CLI that turns a photo into a good, plottable SVG

---

## Architecture Overview

```
penpath/
├── cli/                    # Typer CLI entry points
│   ├── __init__.py
│   ├── main.py             # `penpath` command, subcommands
│   ├── config.py           # TOML config loading (~/.config/penpath/config.toml)
│   └── commands/
│       ├── __init__.py
│       ├── convert.py      # `penpath convert` — photo → SVG
│       ├── info.py         # `penpath info` — show image/PFM/pen details
│       └── config_cmd.py   # `penpath config` — view/edit config
├── core/                   # Pure-Python pipeline, no CLI deps
│   ├── __init__.py
│   ├── models.py           # Pydantic models: Image, Paper, Pen, Project, Pipeline
│   ├── image/
│   │   ├── __init__.py
│   │   ├── load.py         # Pillow-based load + EXIF orient
│   │   ├── filters.py      # Grayscale, threshold, blur, contrast, invert, crop/resize
│   │   └── pipeline.py     # Filter chain application
│   ├── drawing/
│   │   ├── __init__.py
│   │   ├── pfm_sketch_lines.py   # Port of PFMSketchLinesBasic.java
│   │   └── registry.py    # PFM registry (extensible for later PFMs)
│   ├── geometry/
│   │   ├── __init__.py
│   │   ├── simplify.py     # RDP via shapely
│   │   ├── sort.py         # Greedy NN + 2-opt
│   │   └── merge.py        # linemerge + collinear join
│   ├── output/
│   │   ├── __init__.py
│   │   ├── svg.py          # svgwrite export (layers per pen)
│   │   └── vpype.py        # vpype CLI wrapper
│   └── project.py          # YAML load/save (Pydantic round-trip)
├── presets/                # Built-in pen/paper/PFM presets
│   ├── __init__.py
│   ├── pens.py
│   ├── papers.py
│   └── pfms.py
└── __main__.py             # `python -m penpath` entry
```

**Data Flow**: `convert` command → load image → filter pipeline → PFM (Sketch Lines) → geometry ops (simplify → merge → sort) → vpype pipeline → SVG export

---

## Package Layout & Libraries

| Package | Purpose | Key Dependencies |
|---------|---------|------------------|
| `penpath.cli` | Typer app, config, commands | `typer`, `rich` (pretty output) |
| `penpath.core.models` | Pydantic v2 data models | `pydantic`, `pydantic-settings` |
| `penpath.core.image` | Image I/O + filter chain | `Pillow` |
| `penpath.core.drawing` | PFM implementations | `numpy` |
| `penpath.core.geometry` | Line optimization | `shapely` |
| `penpath.core.output` | SVG + vpype integration | `svgwrite`, `vpype` (external) |
| `penpath.core.project` | Project file persistence | `pyyaml` |
| `penpath.presets` | Built-in defaults | — |

**External Tools**: `vpype` (user-installed, `pip install vpype`)

**Python Version**: ≥3.14 (stdlib `tomllib`, `zoneinfo`, `dataclasses`)

---

## Work Order (Ticket-Sized Units)

### Phase 0: Scaffold & Config (1 ticket)
- [ ] `pyproject.toml` with deps, `src/penpath` layout, `ruff`, `pytest`, `mypy` config
- [ ] `penpath/__main__.py`, `cli/main.py` with `typer.Typer()`, `config.py` (TOML load)
- [ ] `cli/commands/config_cmd.py` — `penpath config show|edit|init`
- [ ] Built-in `presets/pens.py`, `presets/papers.py` (dataclasses + JSON/YAML)

### Phase 1: Image I/O & Filters (2 tickets)
- [ ] `core/image/load.py` — `load_image(path) → PIL.Image` with EXIF auto-orient
- [ ] `core/image/filters.py` — grayscale, threshold (levels + dither), Gaussian blur, contrast/brightness/gamma, invert, crop/resize/rotate (fit modes)
- [ ] `core/image/pipeline.py` — `FilterPipeline` class: ordered steps, enable/disable, `apply(image) → image`
- [ ] Unit tests: each filter, pipeline composition, EXIF orient

### Phase 2: Sketch Lines PFM (LUC-47, 3 tickets)
**Acceptance criterion:** the shipped defaults must pass the SSIM-gated likeness
test for all five reference images. The enforced floors — SSIM plus covered
width/height, bounding-box area, ink spread and tone ratio — are recorded in
[docs/TESTING.md](TESTING.md#sketch-lines-likeness-gate-luc-47), measured on the
same image → SVG → strokes → simulator path used by `penpath convert` and
`penpath evaluate`. Part 1 (LUC-52) defined the yardstick, part 2 (LUC-53)
rewrote the algorithm to meet it, and part 3 (LUC-54) calibrated the defaults,
documented every setting in [docs/CLI.md](CLI.md#pfm-settings-sketch-lines) and
published the before/after evidence.

- [x] `core/drawing/pfm_sketch_lines.py` — port `PFMSketchLinesBasic.java`:
    - Settings: line density, min/max length, angle range, shading on/off, squiggles, erasing, seed, erase curve and brush, stop condition
    - Core algorithm: random-angle search, darkest-pixel sampling, shading branch, squiggle/erase helpers
    - Output: `list[LineString]` (shapely) in image coordinates
- [x] `core/drawing/registry.py` — `PFMRegistry` with `sketch_lines` entry; extensible for later PFMs
- [x] Unit tests: deterministic output with fixed seed, parameter bounds, output geometry validity
- [x] Integration gate: `tests/integration/test_sketch_lines_gate.py` asserts the floors for all five reference images with the shipped defaults

### Phase 3: Geometry Optimization (2 tickets)
- [ ] `core/geometry/simplify.py` — `simplify(lines, tolerance_mm, paper_dpi) → lines` via `shapely.simplify`
- [ ] `core/geometry/merge.py` — `merge_lines(lines, angle_tol_deg, dist_tol_mm) → lines` via `linemerge` + collinear join
- [ ] `core/geometry/sort.py` — `sort_lines(lines, start_point=None) → lines` greedy NN + 2-opt pass
- [ ] Pipeline: `optimize(lines, paper) → lines` (simplify → merge → sort)
- [ ] Unit tests: tolerance behavior, travel distance reduction, topology preservation

### Phase 4: vpype Integration & SVG Export (2 tickets)
- [ ] `core/output/vpype.py` — `run_vpype(geometries, paper, pens, vpype_path="vpype") → svg_bytes`
    - Pipeline: `linemerge linesimplify reloop linesort write --page-size <paper> --center`
    - Pen layers: write each pen's geometries to separate layer via `--layer`
- [ ] `core/output/svg.py` — fallback direct SVG via `svgwrite` (if vpype unavailable)
    - Layers per pen, `inkscape:groupmode="layer"`, viewBox from paper, background layer
- [ ] Integration test: round-trip photo → SVG → vpype read → geometry count

### Phase 5: Project File & Convert Command (2 tickets)
- [ ] `core/project.py` — `Project` Pydantic model (image, filters, PFM, pens, paper, output), `load_yaml/save_yaml`
- [ ] `cli/commands/convert.py` — `penpath convert`:
    - Args: `input`, `-o/--output`, `--project`, `--pfm`, `--pen`, `--paper`, `--filter` (repeatable)
    - Reads project file or builds from flags, runs pipeline, writes SVG
    - Progress via `rich.progress`
- [ ] `cli/commands/info.py` — `penpath info image|pfm|pen|paper` — show details/presets

### Phase 6: Polish & Docs (1 ticket)
- [ ] `docs/CLI.md` complete (every command/option)
- [ ] README with quickstart, project file example
- [ ] GitHub Actions: lint, typecheck, test, build wheel
- [ ] PyPI publish config (trusted publishing)

### Phase 7: G-code and machine profiles (8 tickets)

Eight parts in order, from the approved LUC-51 plan; one pull request each:
- [ ] Part 1: machine profile schema (D5), YAML loader and one built-in `generic` profile
- [ ] Part 2: `penpath info profiles` and the profile format in the docs
- [ ] Part 3: G-code emitter — one layer, no pen change
- [ ] Part 4: CLI `penpath gcode`
- [ ] Part 5: multi-pen — one pen-change block per layer, in layer order
- [ ] Part 6: G-code preview — `penpath preview file.gcode -o file.png`
- [ ] Part 7: pen geometry — pen offset, drawable area, ramped landing
- [ ] Part 8: the `aquila` built-in profile

---

## Milestones

| Milestone | Target | Deliverable |
|-----------|--------|-------------|
| M0: Scaffold | Week 1 | Runnable `penpath config show` |
| M1: Image Pipeline | Week 2 | `penpath convert --filter grayscale --filter threshold input.png -o out.svg` (no drawing yet) |
| M2: Sketch Lines | Week 3 | Sketch Lines PFM passes the SSIM-gated likeness test in [docs/TESTING.md](TESTING.md#sketch-lines-likeness-gate-luc-47) for all five reference images |
| M3: Optimized SVG | Week 4 | `penpath convert input.png -o out.svg` produces plottable SVG |
| M4: Project Files | Week 5 | `penpath convert --project project.yaml` round-trips |
| M5: Release Prep | Week 6 | PyPI package, docs, CI green |

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Sketch Lines port correctness | Medium | High | Test against DrawingBotV3 reference outputs (golden files) |
| vpype CLI version drift | Low | Medium | Pin tested version in CI; fallback to direct svgwrite |
| Shapely GEOS binary wheels | Low | High | Use manylinux wheels; document system deps for Alpine |
| Performance on large images | Medium | Medium | Downsample filter preview; process at target DPI only |

---

## Out of Scope (MVP)

- GUI / preview window
- Multi-pen / colour separation
- Additional PFMs (Sketch Squares, Spiral, Contour)
- GCode / HPGL / DXF export
- Batch directory processing
- Plugin system
- Real-time parameter tuning