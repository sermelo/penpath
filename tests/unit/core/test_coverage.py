"""Tests for the real ink coverage cap (penpath.core.coverage)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner
from PIL import Image
from shapely import LineString

from penpath.cli.main import main
from penpath.core.coverage import (
    calibrate_darkness_scale,
    cap_coverage,
    measure_coverage,
    scale_darkness,
)

PPM = 4.0
PEN = 0.5


def _parallel(spacing_px: float, size: int = 160) -> list[LineString]:
    """Horizontal lines ``spacing_px`` apart across a ``size`` square."""
    return [
        LineString([(0.0, y), (size - 1.0, y)]) for y in np.arange(0.0, size, spacing_px).tolist()
    ]


def test_measure_coverage_matches_pen_over_spacing() -> None:
    # 0.5 mm pen every 1 mm (4 px): half the paper is ink.
    coverage = measure_coverage(_parallel(4.0), (160, 160), PPM, PEN)
    assert coverage == pytest.approx(0.5, abs=0.06)


def test_scale_darkness() -> None:
    image = Image.new("L", (4, 4), 0)
    assert np.asarray(scale_darkness(image, 0.5)).max() == 128
    assert np.asarray(scale_darkness(Image.new("L", (2, 2), 255), 0.3)).min() == 255


def _hatch_like(image: Image.Image) -> list[LineString]:
    """Lines whose spacing follows the patch's darkness (coverage ~ darkness)."""
    darkness = 1.0 - float(np.asarray(image).mean()) / 255.0
    if darkness <= 0.01:
        return []
    spacing_px = PEN * PPM / darkness
    return _parallel(spacing_px, image.width)


def test_calibration_finds_scale_for_the_cap() -> None:
    scale = calibrate_darkness_scale(_hatch_like, 0.6, PPM, PEN)
    assert scale == pytest.approx(0.6, abs=0.05)


def test_calibration_keeps_light_algorithms() -> None:
    assert (
        calibrate_darkness_scale(lambda image: _parallel(20.0, image.width), 0.8, PPM, PEN) == 1.0
    )
    assert calibrate_darkness_scale(_hatch_like, 1.0, PPM, PEN) == 1.0


def test_cap_coverage_thins_overfull_areas() -> None:
    lines = _parallel(2.0)  # 0.5 mm pen every 0.5 mm: solid
    assert measure_coverage(lines, (160, 160), PPM, PEN) > 0.9
    capped = cap_coverage(lines, (160, 160), PPM, PEN, 0.6)
    assert measure_coverage(capped, (160, 160), PPM, PEN) <= 0.66


def test_cap_coverage_cuts_a_single_long_stroke() -> None:
    zigzag = LineString(
        [(x, 0.0 if i % 2 else 159.0) for i, x in enumerate(np.arange(0, 160, 2.0))]
    )
    capped = cap_coverage([zigzag], (160, 160), PPM, PEN, 0.6)
    assert capped, "the stroke is thinned, not deleted"
    assert measure_coverage(capped, (160, 160), PPM, PEN) <= 0.7


def test_cap_coverage_leaves_light_drawings_alone() -> None:
    lines = _parallel(16.0)
    assert cap_coverage(lines, (160, 160), PPM, PEN, 0.8) == lines
    assert cap_coverage(lines, (160, 160), PPM, PEN, 1.0) is lines


def test_convert_caps_black(tmp_path: Path) -> None:
    source = tmp_path / "black.png"
    Image.new("RGB", (120, 120), "black").save(source)
    outputs = {}
    for cap in ("1.0", "0.6"):
        output = tmp_path / f"{cap}.svg"
        result = CliRunner().invoke(
            main,
            [
                "convert",
                str(source),
                "-o",
                str(output),
                "--no-vpype",
                "--no-background",
                "--pen",
                "0.5",
                "--pfm",
                "hatch:crosshatch",
                "--max-coverage",
                cap,
            ],
        )
        assert result.exit_code == 0, result.output
        outputs[cap] = output.read_text()
    assert len(outputs["0.6"]) < len(outputs["1.0"])
