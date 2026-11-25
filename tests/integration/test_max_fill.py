"""Assert the ``max_fill`` calibration measured in ``max_fill_gate.py`` (LUC-89).

The sweep runs the real convert/simulate path on a dark figure, a light figure
and a gradient. It justifies shipping a default below 100: solid black areas
receive less ink, light tones keep their ink, and the gradient keeps its tone
ordering while likeness stays close to the full-range drawing.
"""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner
from max_fill_gate import (
    DEFAULT_MAX_FILL,
    FIGURE_NAMES,
    SWEEP,
    FillReport,
    measurement_for,
    print_measurement_table,
)

from penpath.cli.main import main
from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings


@pytest.fixture(scope="session")
def sweep_reports(tmp_path_factory: pytest.TempPathFactory) -> list[FillReport]:
    """Run every figure at every sweep point once and print the measured table."""
    from max_fill_gate import measure_sweep

    reports = measure_sweep(tmp_path_factory.mktemp("max-fill-calibration"))
    print_measurement_table(reports)
    return reports


def test_shipped_default_matches_the_calibrated_value() -> None:
    """The harness and the settings model agree on the shipped default."""
    assert DEFAULT_MAX_FILL < 100.0
    assert SketchLinesSettings().max_fill == DEFAULT_MAX_FILL


def test_sweep_covers_every_figure_and_value(sweep_reports: list[FillReport]) -> None:
    """Each of the three figures was drawn at all five sweep points."""
    assert len(sweep_reports) == len(FIGURE_NAMES) * len(SWEEP)
    assert {report.figure for report in sweep_reports} == set(FIGURE_NAMES)
    assert {report.max_fill for report in sweep_reports} == set(SWEEP)
    for report in sweep_reports:
        assert report.measures.num_strokes > 0
        assert report.measures.drawing_length_mm > 0
        assert np.isfinite(report.measures.ssim)


def test_default_reduces_ink_in_the_solid_dark_figure(sweep_reports: list[FillReport]) -> None:
    """Ink in the solid black square falls monotonically as max_fill falls."""
    densities = [measurement_for(sweep_reports, "dark_figure", value).dark_ink for value in SWEEP]
    assert all(lower < higher for lower, higher in pairwise(densities))
    capped = measurement_for(sweep_reports, "dark_figure", DEFAULT_MAX_FILL).dark_ink
    full = measurement_for(sweep_reports, "dark_figure", 100.0).dark_ink
    assert capped < 0.9 * full


def test_light_figure_still_receives_ink(sweep_reports: list[FillReport]) -> None:
    """A tone lighter than the black point is drawn exactly as in full range."""
    capped = measurement_for(sweep_reports, "light_figure", DEFAULT_MAX_FILL)
    full = measurement_for(sweep_reports, "light_figure", 100.0)
    assert capped.dark_ink > 0.05
    assert capped.dark_ink == pytest.approx(full.dark_ink, abs=1e-9)
    assert capped.drawing_length_mm == pytest.approx(full.drawing_length_mm, abs=1e-6)


def test_gradient_keeps_tone_ordering(sweep_reports: list[FillReport]) -> None:
    """Dark, middle and light bands get decreasing ink at the shipped default."""
    capped = measurement_for(sweep_reports, "gradient", DEFAULT_MAX_FILL)
    full = measurement_for(sweep_reports, "gradient", 100.0)
    assert capped.bands[0] > capped.bands[1] > capped.bands[2]
    assert capped.bands[0] < full.bands[0]
    assert capped.bands[2] == pytest.approx(full.bands[2], abs=0.01)


def test_default_lowers_machine_cost(sweep_reports: list[FillReport]) -> None:
    """The black area and the gradient take fewer millimetres of pen-down travel."""
    for figure in ("dark_figure", "gradient"):
        capped = measurement_for(sweep_reports, figure, DEFAULT_MAX_FILL)
        full = measurement_for(sweep_reports, figure, 100.0)
        assert capped.drawing_length_mm < full.drawing_length_mm
        assert capped.num_strokes < full.num_strokes


def test_default_keeps_likeness_close_to_full_range(sweep_reports: list[FillReport]) -> None:
    """The cap spends a little SSIM to make the solid black area plottable."""
    for figure in ("dark_figure", "gradient"):
        capped = measurement_for(sweep_reports, figure, DEFAULT_MAX_FILL)
        full = measurement_for(sweep_reports, figure, 100.0)
        assert capped.ssim > full.ssim - 0.03


@pytest.mark.parametrize("value", ["0", "101"])
def test_cli_rejects_out_of_range_max_fill(value: str, tmp_path: Path) -> None:
    """Out-of-range values are actionable usage errors that name the setting."""
    from max_fill_gate import make_figures

    work_dir = tmp_path / "figures"
    make_figures(work_dir)
    result = CliRunner().invoke(
        main,
        [
            "convert",
            str(work_dir / "dark_figure.png"),
            "-o",
            str(tmp_path / "plot.svg"),
            "-s",
            f"max_fill={value}",
        ],
        env={"XDG_CONFIG_HOME": str(tmp_path / "config")},
    )
    assert result.exit_code == 2
    assert "PFM setting" in result.output
    assert "max_fill" in result.output
