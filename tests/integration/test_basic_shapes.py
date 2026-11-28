"""Check the basic-shape fixtures and enforce the thresholds in docs/TESTING.md.

The gate table lives in ``basic_shapes_gate.py`` so there is one place to change
it. All tests share the session-cached measurements: each shape is converted
once, then the algorithm's drawing and both baselines are checked against it.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import click
import pytest
from basic_shapes_gate import (
    PREVIEW_PANEL,
    PREVIEW_WIDTH,
    SHAPE_NAMES,
    ShapeMeasures,
    ShapeReport,
    all_finite,
    format_threshold_violations,
    measure_all,
    print_measurement_table,
    threshold_violations,
    write_previews,
)
from PIL import Image

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "images" / "basic"
GENERATOR_PATH = FIXTURES_DIR / "generate_basic.py"
FIXTURE_NAMES = (
    "black_square.pbm",
    "white_square.pbm",
    "black_disc.pbm",
    "horizontal_line.pbm",
    "checkerboard.pbm",
    "triangle.pbm",
)
BLACK_PIXELS = {
    "black_square.pbm": 625,
    "white_square.pbm": 3471,
    "black_disc.pbm": 1568,
    "horizontal_line.pbm": 102,
    "checkerboard.pbm": 2048,
    "triangle.pbm": 1742,
}


def _load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("generate_basic", GENERATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_basic_fixtures_are_reproducible(tmp_path: Path) -> None:
    """Regenerating the fixtures into an empty directory matches the committed bytes."""
    generator = _load_generator()
    generator.write_fixtures(tmp_path)
    for name in FIXTURE_NAMES:
        assert (tmp_path / name).read_bytes() == (FIXTURES_DIR / name).read_bytes(), name


def test_basic_fixtures_are_well_formed() -> None:
    """Every fixture is a 64x64 P1 file with only 0/1 pixels and the expected ink count."""
    for name in FIXTURE_NAMES:
        lines = (FIXTURES_DIR / name).read_bytes().splitlines()
        assert lines[0] == b"P1", name
        assert lines[1] == b"64 64", name
        assert len(lines) == 66, name
        pixels = b"".join(lines[2:])
        assert len(pixels) == 64 * 64, name
        assert set(pixels) <= {ord("0"), ord("1")}, name
        assert pixels.count(b"1") == BLACK_PIXELS[name], name


@pytest.fixture(scope="session")
def gate_data(tmp_path_factory: pytest.TempPathFactory) -> tuple[list[ShapeReport], Path]:
    """Run the real pipeline once for every basic shape and keep its work directory."""
    work_dir = tmp_path_factory.mktemp("basic-shapes-gate")
    reports = measure_all(work_dir)
    print_measurement_table(reports)
    return reports, work_dir


@pytest.fixture(scope="session")
def gate_reports(gate_data: tuple[list[ShapeReport], Path]) -> list[ShapeReport]:
    """Measurements from one pipeline run shared by the checks below."""
    return gate_data[0]


def _algorithm_measurements(gate_reports: list[ShapeReport], shape: str) -> ShapeMeasures:
    for report in gate_reports:
        if report.shape == shape:
            return report.algorithm
    raise AssertionError(f"no measurements recorded for {shape}")


def _assert_shape_meets_thresholds(gate_reports: list[ShapeReport], shape: str) -> None:
    violations = threshold_violations(shape, _algorithm_measurements(gate_reports, shape))
    assert not violations, f"{shape} gate not met:\n{format_threshold_violations(violations)}"


def test_threshold_violations_distinguish_floors_and_caps() -> None:
    """The comparator accepts a passing drawing and names each kind of failure."""
    passing = ShapeMeasures(0.90, 0.01, 0.90, 3.0, 1000.0, 2, 2)
    assert threshold_violations("black_square", passing) == []

    failing = ShapeMeasures(0.10, 0.90, 0.90, 3.0, 1000.0, 0, 1000)
    violations = threshold_violations("black_square", failing)
    assert {(violation.measure, violation.is_floor) for violation in violations} == {
        ("likeness", True),
        ("ink_outside", False),
        ("num_strokes", True),
        ("num_lifts", False),
    }


@pytest.mark.slow
def test_basic_shapes_gate_runs(gate_reports: list[ShapeReport]) -> None:
    """The real pipeline runs for every shape and all reported numbers are finite."""
    assert [report.shape for report in gate_reports] == list(SHAPE_NAMES)
    for report in gate_reports:
        assert report.placement.width > 0
        assert report.placement.height > 0
        for measured in (report.algorithm, report.blank, report.random):
            assert all_finite(measured)
        assert report.algorithm.num_strokes >= 1
        assert report.algorithm.drawing_length_mm > 0
        assert report.algorithm.dark_coverage > 0
        assert report.algorithm.likeness != report.blank.likeness


@pytest.mark.slow
def test_basic_shape_previews_are_greyscale(
    gate_data: tuple[list[ShapeReport], Path],
    tmp_path: Path,
) -> None:
    """The helper writes one 600 px greyscale preview for each measured shape."""
    _, work_dir = gate_data
    output_dir = tmp_path / "previews"
    paths = write_previews(work_dir, output_dir)
    assert [path.name for path in paths] == [f"{name}.png" for name in SHAPE_NAMES]
    for path in paths:
        with Image.open(path) as image:
            assert image.mode == "L"
            assert image.size == (PREVIEW_WIDTH, PREVIEW_PANEL)


@pytest.mark.slow
def test_basic_shape_black_square(gate_reports: list[ShapeReport]) -> None:
    """The black square drawing meets every floor and cap in the gate table."""
    _assert_shape_meets_thresholds(gate_reports, "black_square")


@pytest.mark.slow
def test_basic_shape_white_square(gate_reports: list[ShapeReport]) -> None:
    """The white square drawing meets every floor and cap in the gate table."""
    _assert_shape_meets_thresholds(gate_reports, "white_square")


@pytest.mark.slow
def test_basic_shape_black_disc(gate_reports: list[ShapeReport]) -> None:
    """The black disc drawing meets every floor and cap in the gate table."""
    _assert_shape_meets_thresholds(gate_reports, "black_disc")


@pytest.mark.slow
def test_basic_shape_horizontal_line(gate_reports: list[ShapeReport]) -> None:
    """The horizontal line drawing meets every floor and cap in the gate table."""
    _assert_shape_meets_thresholds(gate_reports, "horizontal_line")


@pytest.mark.slow
def test_basic_shape_checkerboard(gate_reports: list[ShapeReport]) -> None:
    """The checkerboard drawing meets every floor and cap in the gate table."""
    _assert_shape_meets_thresholds(gate_reports, "checkerboard")


@pytest.mark.slow
def test_basic_shape_triangle(gate_reports: list[ShapeReport]) -> None:
    """The triangle drawing meets every floor and cap in the gate table."""
    _assert_shape_meets_thresholds(gate_reports, "triangle")


@pytest.mark.slow
def test_blank_page_fails_every_shape(gate_reports: list[ShapeReport]) -> None:
    """Inking nothing fails dark_coverage and likeness for every shape."""
    passing: list[str] = []
    for report in gate_reports:
        violations = threshold_violations(report.shape, report.blank)
        key = [
            violation
            for violation in violations
            if violation.measure in ("dark_coverage", "likeness")
        ]
        click.echo(f"blank {report.shape}: " + "; ".join(str(violation) for violation in key))
        if not violations or len(key) != 2:
            passing.append(report.shape)
    assert not passing, f"blank page passes a required floor for: {', '.join(passing)}"


@pytest.mark.slow
def test_random_scribble_fails_every_shape(gate_reports: list[ShapeReport]) -> None:
    """Seeded random strokes fail ink_outside and likeness for every shape."""
    passing: list[str] = []
    for report in gate_reports:
        violations = threshold_violations(report.shape, report.random)
        key = [
            violation
            for violation in violations
            if violation.measure in ("ink_outside", "likeness")
        ]
        click.echo(f"random {report.shape}: " + "; ".join(str(violation) for violation in key))
        if not violations or len(key) != 2:
            passing.append(report.shape)
    assert not passing, f"random scribble passes a required floor for: {', '.join(passing)}"
