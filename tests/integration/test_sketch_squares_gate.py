"""Assert the Sketch Squares readability and plot-cost floors (LUC-149).

The harness in ``sketch_squares_gate.py`` measures every built-in preset on the
three portrait/photo references through the real ``penpath convert`` path. This
module turns those numbers into pass/fail checks: the ink must follow dark source
areas, span the placement, and cost a reasonable amount of pen time. Visual
acceptance is by looking at the previews, not by these numbers alone.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner
from PIL import Image
from sketch_squares_gate import (
    PRESETS,
    REFERENCE_DIR,
    REFERENCE_NAMES,
    SquaresReport,
    print_measurement_table,
)

from penpath.cli.main import main as cli_main

DARK_RECALL_MIN = 0.19
INK_PRECISION_MIN = 0.67
COVERAGE_WIDTH_MIN = 0.94
COVERAGE_HEIGHT_MIN = 0.94
COVERAGE_AREA_MIN = 0.94
MAX_STROKES = 600
MAX_LENGTH_MM = 170000.0
MAX_TINY_SEGMENTS = 25
MAX_TINY_FRACTION = 0.01


def test_gate_measures_every_reference_with_every_preset(
    squares_report_factory: Callable[[str, str], SquaresReport],
) -> None:
    """The harness measures all nine reference/preset combinations once."""
    reports = [
        squares_report_factory(reference, preset)
        for reference in REFERENCE_NAMES
        for preset in PRESETS
    ]
    assert [report.preset for report in reports] == [
        preset for _ in REFERENCE_NAMES for preset in PRESETS
    ]
    print_measurement_table(reports)


@pytest.mark.parametrize("reference", REFERENCE_NAMES)
@pytest.mark.parametrize("preset", PRESETS)
def test_sketch_squares_preset_is_valid_readable_and_cheap(
    squares_report_factory: Callable[[str, str], SquaresReport],
    reference: str,
    preset: str,
) -> None:
    """One preset on one image is a real, dark-following, low-cost plot."""
    report = squares_report_factory(reference, preset)
    assert report.reference == reference
    assert report.preset == preset
    assert report.stroke_count > 0
    assert not report.geometry_failures, report.geometry_failures[:5]

    failures: list[str] = []
    for name, value, floor in (
        ("dark recall", report.algorithm.dark_recall, DARK_RECALL_MIN),
        ("ink precision", report.algorithm.ink_precision, INK_PRECISION_MIN),
        ("covered width", report.algorithm.coverage_width, COVERAGE_WIDTH_MIN),
        ("covered height", report.algorithm.coverage_height, COVERAGE_HEIGHT_MIN),
        ("bbox area", report.algorithm.coverage_area, COVERAGE_AREA_MIN),
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


def test_blank_page_fails_readability(
    squares_report_factory: Callable[[str, str], SquaresReport],
) -> None:
    """An empty page inks nothing and spans nothing, so it cannot pass the gate."""
    for reference in REFERENCE_NAMES:
        for preset in PRESETS:
            blank = squares_report_factory(reference, preset).blank
            assert blank.dark_recall == 0.0, f"{reference}/{preset}"
            assert blank.ink_precision == 0.0, f"{reference}/{preset}"
            assert blank.coverage_area == 0.0, f"{reference}/{preset}"
            assert blank.dark_recall < DARK_RECALL_MIN
            assert blank.coverage_width < COVERAGE_WIDTH_MIN


def test_random_scribble_fails_readability(
    squares_report_factory: Callable[[str, str], SquaresReport],
) -> None:
    """Random strokes may span the page but do not follow its dark areas."""
    for reference in REFERENCE_NAMES:
        for preset in PRESETS:
            random = squares_report_factory(reference, preset).random
            assert random.dark_recall < DARK_RECALL_MIN, f"{reference}/{preset}"


def test_user_can_convert_and_preview_every_preset(tmp_path: Path) -> None:
    """The documented CLI sequence writes a non-blank PNG for each preset."""
    runner = CliRunner()
    images: list[np.ndarray] = []
    for preset in PRESETS:
        svg_path = tmp_path / f"santa_{preset}.svg"
        png_path = tmp_path / f"santa_{preset}.png"
        converted = runner.invoke(
            cli_main,
            [
                "convert",
                str(REFERENCE_DIR / "santa.jpg"),
                "-o",
                str(svg_path),
                "--pfm",
                f"sketch_squares:{preset}",
                "-s",
                "seed=42",
                "--max-resolution",
                "384",
                "--no-vpype",
                "--quiet",
            ],
        )
        assert converted.exit_code == 0, converted.output
        previewed = runner.invoke(
            cli_main, ["preview", str(svg_path), "-o", str(png_path), "--dpi", "4"]
        )
        assert previewed.exit_code == 0, previewed.output
        with Image.open(png_path) as opened:
            greyscale = np.asarray(opened.convert("L"))
        assert greyscale.shape == (1188, 840)
        assert greyscale.min() < 128 < greyscale.max()
        images.append(greyscale)
    assert len({image.tobytes() for image in images}) == len(PRESETS)
