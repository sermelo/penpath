"""Assert the Stipple likeness and plot-cost thresholds recorded in docs/TESTING.md.

The harness in ``stipple_gate.py`` runs the real ``penpath convert`` CLI and
reuses the Sketch Lines gate's simulation and likeness helpers. This module
turns those numbers into pass/fail checks: the dots must cover the placed
image, spread ink across every quarter and follow the source's tone, while a
single-pen A4-class plot stays cheap. SSIM is printed as evidence only: on
smooth tonal images a blank page scores higher than a stipple plot, so SSIM
cannot carry this gate.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner
from PIL import Image
from sketch_lines_gate import PlotMeasures
from stipple_gate import (
    GATE_PRESET,
    PEN_WIDTH_MM,
    REFERENCE_DIR,
    REFERENCE_NAMES,
    StippleReport,
    all_report_values_finite,
    print_measurement_table,
)

from penpath.cli.main import main as cli_main
from penpath.core.svg_parse import list_svg_layers, parse_svg_strokes

COVERAGE_WIDTH_MIN = 0.70
COVERAGE_HEIGHT_MIN = 0.70
BBOX_AREA_MIN = 0.51
INK_CELL_MIN = 0.0004
TONE_RATIO_MIN = 8.0
MAX_LENGTH_MM = 20000.0
MAX_TRAVEL_MM = 14000.0
MAX_LIFTS = 10000
MAX_TINY_SEGMENTS = 0
MAX_TINY_FRACTION = 0.0
PALETTE = "red=0.4,#E4002B;blue=0.4,#1B4C9E"


def floor_failures(measures: PlotMeasures) -> list[str]:
    """Return the non-SSIM floors a set of measurements fails."""
    checks = (
        ("covered width", measures.coverage_width, COVERAGE_WIDTH_MIN),
        ("covered height", measures.coverage_height, COVERAGE_HEIGHT_MIN),
        ("bbox area", measures.coverage_area, BBOX_AREA_MIN),
        ("ink per 4x4 cell", measures.ink_spread_min, INK_CELL_MIN),
        ("tone ratio", measures.tone_ratio, TONE_RATIO_MIN),
    )
    return [f"{name} {value:.4f} < {floor:.4f}" for name, value, floor in checks if value < floor]


@pytest.fixture(scope="session")
def stipple_report_factory(
    tmp_path_factory: pytest.TempPathFactory,
) -> Callable[[str], StippleReport]:
    """Convert and measure each reference once per test session."""
    from stipple_gate import measure

    work_dir = tmp_path_factory.mktemp("stipple-gate")
    cache: dict[str, StippleReport] = {}

    def report_for(reference: str) -> StippleReport:
        if reference not in cache:
            cache[reference] = measure(
                REFERENCE_DIR / reference, GATE_PRESET, work_dir / Path(reference).stem
            )
        return cache[reference]

    return report_for


def test_gate_measures_every_reference(
    stipple_report_factory: Callable[[str], StippleReport],
) -> None:
    """The harness measures every committed reference in the published order."""
    reports = [stipple_report_factory(name) for name in REFERENCE_NAMES]
    assert [report.reference for report in reports] == list(REFERENCE_NAMES)
    print_measurement_table(reports)


@pytest.mark.parametrize("reference", REFERENCE_NAMES)
def test_stipple_drawing_beats_blank_and_random(
    stipple_report_factory: Callable[[str], StippleReport], reference: str
) -> None:
    """One reference's dots clear every non-SSIM floor and reject both baselines."""
    report = stipple_report_factory(reference)
    assert report.reference == reference
    assert report.preset == GATE_PRESET
    assert report.stroke_count > 0
    assert report.placement[2] > 0 and report.placement[3] > 0
    assert all_report_values_finite(report)

    algorithm_failures = floor_failures(report.algorithm)
    assert not algorithm_failures, f"{reference}: " + "; ".join(algorithm_failures)

    blank_failures = floor_failures(report.blank)
    random_failures = floor_failures(report.random)
    assert blank_failures, f"{reference}: blank page passed every floor"
    assert random_failures, f"{reference}: random scribble passed every floor"
    assert report.algorithm.ssim > report.random.ssim
    assert report.ideal.ssim > report.algorithm.ssim


@pytest.mark.parametrize("reference", REFERENCE_NAMES)
def test_stipple_plot_cost_is_bounded(
    stipple_report_factory: Callable[[str], StippleReport], reference: str
) -> None:
    """The dot budget and the machine's work stay inside the measured caps."""
    report = stipple_report_factory(reference)
    assert not report.geometry_failures, report.geometry_failures[:5]
    cost = report.cost
    assert report.stroke_count == cost.strokes
    assert cost.strokes > 0
    assert cost.strokes <= cost.max_strokes
    assert cost.length_mm <= MAX_LENGTH_MM
    assert cost.travel_mm <= MAX_TRAVEL_MM
    assert cost.lifts <= MAX_LIFTS
    assert cost.tiny_segments <= MAX_TINY_SEGMENTS
    assert cost.tiny_fraction <= MAX_TINY_FRACTION


def test_two_pen_palette_runs_once_per_pen(tmp_path: Path) -> None:
    """Two pens produce two layers with no colour or region mixed between them."""
    image_path = tmp_path / "twopen.png"
    image = Image.new("RGB", (120, 120), "white")
    for y in range(120):
        for x in range(120):
            image.putpixel((x, y), (228, 0, 43) if x < 60 else (27, 76, 158))
    image.save(image_path)

    svg_path = tmp_path / "twopen.svg"
    result = CliRunner().invoke(
        cli_main,
        [
            "convert",
            str(image_path),
            "-o",
            str(svg_path),
            "--pfm",
            "stipple",
            "--paper",
            "60x60,5",
            "--palette",
            PALETTE,
            "--no-background",
            "--no-vpype",
            "-s",
            "seed=42",
            "--quiet",
        ],
        env={"XDG_CONFIG_HOME": str(tmp_path / "config")},
    )
    assert result.exit_code == 0, result.output

    layers = list_svg_layers(svg_path)
    assert layers == [("layer1", "red"), ("layer2", "blue")]
    for layer_id, color, side in (("red", "#E4002B", -1), ("blue", "#1B4C9E", 1)):
        strokes = parse_svg_strokes(svg_path, layer=layer_id)
        assert strokes, f"{layer_id} drew no dots: the PFM did not run for that pen"
        assert all(stroke.color == color for stroke in strokes)
        assert all(stroke.width_mm == 0.4 for stroke in strokes)
        midpoints = [(stroke.polyline[0][0] + stroke.polyline[-1][0]) / 2.0 for stroke in strokes]
        assert sum((x - 30.0) * side > 0 for x in midpoints) / len(midpoints) >= 0.90


def test_convert_santa_and_preview_a_readable_portrait(tmp_path: Path) -> None:
    """The documented stipple_fine command writes a non-blank portrait PNG."""
    svg_path = tmp_path / "santa.svg"
    png_path = tmp_path / "santa.png"
    runner = CliRunner()
    converted = runner.invoke(
        cli_main,
        [
            "convert",
            str(REFERENCE_DIR / "santa.jpg"),
            "-o",
            str(svg_path),
            "--pfm",
            "stipple_fine",
            "--paper",
            "190x190,10",
            "--pen",
            f"{PEN_WIDTH_MM}",
            "--no-vpype",
            "-s",
            "seed=42",
            "--quiet",
        ],
        env={"XDG_CONFIG_HOME": str(tmp_path / "config")},
    )
    assert converted.exit_code == 0, converted.output
    previewed = runner.invoke(
        cli_main, ["preview", str(svg_path), "-o", str(png_path), "--dpi", "4"]
    )
    assert previewed.exit_code == 0, previewed.output
    with Image.open(png_path) as opened:
        greyscale = np.asarray(opened.convert("L"))
    assert greyscale.shape == (760, 760)
    assert greyscale.min() < 128 < greyscale.max()
