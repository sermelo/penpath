"""Assert the Contour gate thresholds recorded in docs/TESTING.md (LUC-146).

The harness in ``contour_gate.py`` measures every built-in contour preset on
each reference through the real ``penpath convert`` path. This module turns
those numbers into pass/fail checks: contour points must sit on source edges,
the drawing must cover the image, and a single-pen A4 plot must stay cheap.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner
from contour_gate import (
    EDGE_TOLERANCE_PX,
    PRESETS,
    REFERENCE_DIR,
    REFERENCE_NAMES,
    ContourReport,
    print_measurement_table,
)
from PIL import Image

from penpath.cli.main import main as cli_main

pytestmark = pytest.mark.slow

EDGE_ALIGNMENT_MIN = 0.60
COVERAGE_WIDTH_MIN = 0.60
COVERAGE_HEIGHT_MIN = 0.60
COVERAGE_AREA_MIN = 0.40
MAX_STROKES = 250
MAX_LENGTH_MM = 28000.0
MAX_TINY_SEGMENTS = 10
MAX_TINY_FRACTION = 0.05


def test_gate_measures_every_reference_with_every_preset(
    contour_report_factory: Callable[[str, str], ContourReport],
) -> None:
    """The harness measures all six reference/preset combinations once."""
    reports = [
        contour_report_factory(reference, preset)
        for reference in REFERENCE_NAMES
        for preset in PRESETS
    ]
    assert [report.reference for report in reports] == [
        reference for reference in REFERENCE_NAMES for _ in PRESETS
    ]
    print_measurement_table(reports)


@pytest.mark.parametrize("reference", REFERENCE_NAMES)
@pytest.mark.parametrize("preset", PRESETS)
def test_contour_preset_is_valid_readable_and_cheap(
    contour_report_factory: Callable[[str, str], ContourReport],
    reference: str,
    preset: str,
) -> None:
    """One preset on one image is a real, edge-following, low-cost plot."""
    report = contour_report_factory(reference, preset)
    assert report.reference == reference
    assert report.preset == preset
    assert report.stroke_count > 0
    assert report.sampled_points > 0
    assert report.matched_points > 0
    assert report.placement[2] > 0 and report.placement[3] > 0
    assert not report.geometry_failures, report.geometry_failures[:5]

    failures: list[str] = []
    if report.edge_alignment < EDGE_ALIGNMENT_MIN:
        failures.append(
            f"edge alignment {report.edge_alignment:.3f} < {EDGE_ALIGNMENT_MIN:.2f} "
            f"({EDGE_TOLERANCE_PX} px to Canny edge)"
        )
    for name, value, floor in (
        ("covered width", report.coverage_width, COVERAGE_WIDTH_MIN),
        ("covered height", report.coverage_height, COVERAGE_HEIGHT_MIN),
        ("bbox area", report.coverage_area, COVERAGE_AREA_MIN),
    ):
        if value < floor:
            failures.append(f"{name} {value:.3f} < {floor:.2f}")

    cost = report.cost
    if cost.strokes > MAX_STROKES:
        failures.append(f"strokes {cost.strokes} > {MAX_STROKES}")
    if cost.length_mm > MAX_LENGTH_MM:
        failures.append(f"drawing length {cost.length_mm:.1f} mm > {MAX_LENGTH_MM:.0f} mm")
    if cost.tiny_segments > MAX_TINY_SEGMENTS:
        failures.append(f"tiny segments {cost.tiny_segments} > {MAX_TINY_SEGMENTS}")
    if cost.tiny_fraction > MAX_TINY_FRACTION:
        failures.append(f"tiny segment share {cost.tiny_fraction:.3f} > {MAX_TINY_FRACTION}")
    assert not failures, f"{reference}/{preset}: " + "; ".join(failures)


def test_user_can_convert_santa_and_preview_a_plot(tmp_path: Path) -> None:
    """The documented CLI sequence writes a non-blank PNG of the free portrait."""
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
            "contour_portrait",
            "--paper",
            "a4",
            "--pen",
            "0.3",
            "--dpi",
            "96",
            "--max-resolution",
            "384",
            "--no-vpype",
            "--quiet",
        ],
    )
    assert converted.exit_code == 0, converted.output
    previewed = runner.invoke(
        cli_main, ["preview", str(svg_path), "-o", str(png_path), "--px-per-mm", "4"]
    )
    assert previewed.exit_code == 0, previewed.output
    with Image.open(png_path) as opened:
        greyscale = np.asarray(opened.convert("L"))
    assert greyscale.shape == (1188, 840)
    assert greyscale.min() < 128 < greyscale.max()
