# penpath Conventions

**Status**: Mandatory for all contributors  
**Enforced by**: CI (ruff, mypy, pytest)

---

## Language & Tooling

| Item | Version / Tool | Notes |
|------|----------------|-------|
| Python | ≥3.14 | `tomllib`, `zoneinfo`, `dataclasses`, `typing.Self` |
| Package Manager | `uv` (preferred) or `pip` | `uv sync` for reproducible installs |
| Build Backend | `hatchling` | `pyproject.toml` only, no `setup.py` |
| Formatter | `ruff format` | 100-char line length |
| Linter | `ruff check` | All rules enabled except `D` (docstrings) |
| Type Checker | `mypy --strict` | No `ignore_errors`, no `Any` without comment |
| Test Runner | `pytest` | `pytest -vs` for dev, `pytest --cov` for CI |
| Pre-commit | `pre-commit` | `ruff format`, `ruff check`, `mypy`, `pytest` |

**CI Matrix**: Python 3.14 on Ubuntu latest

---

## Project Structure

```
penpath/
├── pyproject.toml          # Single source of truth
├── src/
│   └── penpath/            # Importable package
│       ├── __init__.py     # `__version__` from `importlib.metadata`
│       ├── __main__.py     # `python -m penpath`
│       ├── cli/            # Typer app only
│       ├── core/           # Pure logic, no CLI deps
│       └── presets/        # Built-in defaults
├── tests/
│   ├── unit/               # Fast, isolated, no external deps
│   ├── integration/        # Full pipeline, vpype, file I/O
│   └── fixtures/           # Golden files, test images
├── docs/
│   ├── FEATURES.md
│   ├── PLAN.md
│   ├── CONVENTIONS.md
│   ├── TESTING.md
│   └── CLI.md
└── .github/workflows/      # CI/CD
```

**Import Rule**: `from penpath.core import ...` — never relative imports across `core/`/`cli/` boundary.

---

## Code Style

### Formatting (ruff)
- Line length: 100
- Target version: py314
- Quote style: double
- Indent: 4 spaces
- Trailing commas: always (where valid)

### Naming
| Kind | Convention | Example |
|------|------------|---------|
| Modules | `snake_case` | `pfm_sketch_lines.py` |
| Classes | `PascalCase` | `SketchLinesPFM` |
| Functions | `snake_case` | `simplify_lines` |
| Constants | `UPPER_SNAKE` | `DEFAULT_PAPER_DPI` |
| Type vars | `PascalCase` + `_T` | `LineString_T` |
| Private | `_leading_underscore` | `_internal_helper` |

### Type Hints
- **All** public functions: full annotations (args + return)
- Use `from __future__ import annotations` (PEP 563)
- Prefer `list[T]`, `dict[K, V]`, `tuple[T, ...]` (Python 3.9+)
- Use `TypedDict` for JSON/YAML shapes
- No `Any` without `# type: ignore[reason]` comment
- `Self` for fluent builders, `Type[T]` for class factories

### Docstrings
- **Required**: Public classes, public methods, CLI commands
- **Style**: NumPy (multi-line) or one-liner for simple functions
- **Not required**: Private helpers, obvious getters/setters, test functions

```python
def simplify_lines(lines: list[LineString], tolerance_mm: float, dpi: int) -> list[LineString]:
    """Simplify lines using Ramer-Douglas-Peucker algorithm.

    Parameters
    ----------
    lines : list[LineString]
        Input geometries in image coordinates (pixels).
    tolerance_mm : float
        Maximum deviation in millimetres.
    dpi : int
        Image DPI for mm→pixel conversion.

    Returns
    -------
    list[LineString]
        Simplified lines, same coordinate system.
    """
```

---

## Testing Conventions

### Test Organization
```
tests/
├── unit/
│   ├── core/
│   │   ├── image/
│   │   │   ├── test_load.py
│   │   │   ├── test_filters.py
│   │   │   └── test_pipeline.py
│   │   ├── drawing/
│   │   │   └── test_pfm_sketch_lines.py
│   │   ├── geometry/
│   │   │   ├── test_simplify.py
│   │   │   ├── test_merge.py
│   │   │   └── test_sort.py
│   │   ├── output/
│   │   │   ├── test_vpype.py
│   │   │   └── test_svg.py
│   │   └── test_project.py
│   └── cli/
│       ├── test_config.py
│       └── test_convert.py
├── integration/
│   ├── test_full_pipeline.py
│   └── test_project_roundtrip.py
└── fixtures/
    ├── images/           # Small test images (<100KB each)
    ├── golden/           # Expected SVG outputs (checked in)
    └── projects/         # Sample project.yaml files
```

### Test Naming
- `test_<function>_<scenario>_<expected>`
- Example: `test_simplify_lines_zero_tolerance_returns_original`

### Fixtures
- `@pytest.fixture(scope="session")` for expensive resources (large images)
- `tmp_path` for all file I/O
- Golden files in `tests/fixtures/golden/` — compare with `filecmp` or normalized XML

### Coverage Targets
| Module Type | Target |
|-------------|--------|
| Core logic (geometry, drawing, filters) | ≥90% |
| CLI commands | ≥80% |
| Config / presets | ≥80% |
| Overall | ≥85% |

---

## Git & PR Conventions

### Branch Names
- `feature/<short-desc>` — new capability
- `fix/<short-desc>` — bug fix
- `docs/<short-desc>` — documentation only
- `refactor/<short-desc>` — no behavior change
- `chore/<short-desc>` — tooling, deps, CI

### Commit Messages
```
<type>(<scope>): <imperative summary>

<body if needed>

Fixes #<issue>
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`

### PR Requirements
- All CI checks pass
- `mypy --strict` clean
- `ruff check` clean
- Tests added/updated for changes
- `CHANGELOG.md` entry (Keep a Changelog format)
- Review by at least one other engineer

---

## Dependency Management

### Adding a Dependency
1. Justify in PR: why not stdlib / existing dep?
2. Prefer pure-Python or manylinux wheels
3. Add to `pyproject.toml` `[project.optional-dependencies]` if optional
4. Update `uv.lock` via `uv lock`
5. Document in `docs/CONVENTIONS.md` if runtime behavior changes

### Pinning
- Direct deps: `>=min,<next-major` (e.g., `pillow>=10,<11`)
- Lock file (`uv.lock`) committed
- `uv sync --frozen` in CI

---

## Configuration Files

### `pyproject.toml` Structure
```toml
[project]
name = "penpath"
version = "0.1.0"
description = "Photo to plottable SVG CLI"
readme = "README.md"
requires-python = ">=3.14"
dependencies = [
    "typer>=0.12,<1",
    "rich>=13,<14",
    "pillow>=10,<11",
    "numpy>=1.26,<2",
    "shapely>=2,<3",
    "svgwrite>=1.4,<2",
    "pyyaml>=6,<7",
    "pydantic>=2,<3",
    "pydantic-settings>=2,<3",
]
optional-dependencies = {
    "dev" = ["ruff", "mypy", "pytest", "pytest-cov", "pre-commit", "hatch"],
    "docs" = ["mkdocs", "mkdocs-material"],
}

[tool.ruff]
line-length = 100
target-version = "py314"
[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP", "B", "C4", "T20", "PTH", "SIM", "RUF"]
ignore = ["D"]  # docstrings handled separately

[tool.mypy]
strict = true
python_version = "3.14"
warn_return_any = true
warn_unused_ignores = true

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
addopts = "-vs --strict-markers"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

---

## Versioning & Releases

- **Scheme**: SemVer (MAJOR.MINOR.PATCH)
- **Pre-1.0**: Minor = breaking, Patch = fix/feature
- **Release**: Git tag `vX.Y.Z` → GitHub Action builds wheel → PyPI trusted publishing
- **Changelog**: `CHANGELOG.md` (Keep a Changelog), updated in PR

---

## Security

- No secrets in code, config, or tests
- `vpype` CLI invoked via `subprocess.run` with explicit args (no shell=True)
- User-provided paths validated (exist, readable, within allowed dirs)
- Dependency scanning: `uv audit` in CI

---

## Accessibility (CLI Output)

- `rich` for colors, progress, tables — auto-disables on non-TTY
- `--no-color` flag respected
- `--quiet` / `--verbose` for log levels
- Error messages: actionable, suggest fix, include `--help` hint