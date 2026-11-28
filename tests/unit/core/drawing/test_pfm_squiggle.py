"""Tests for the Squiggle PFM (rows of waves that follow darkness)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner
from PIL import Image
from pydantic import ValidationError

from penpath.cli.commands.convert import _resolve_pfm
from penpath.cli.main import main
from penpath.core.drawing.pfm_squiggle import SquiggleSettings, squiggle_strokes
from penpath.core.drawing.registry import get_pfm, list_pfms
from penpath.core.models import RegisteredPFM
from penpath.presets.pfms import SQUIGGLE_PRESETS, get_pfm_preset_by_id

PX_PER_MM = 4.0


def _grey(level: int, size: tuple[int, int] = (120, 80)) -> Image.Image:
    return Image.new("L", size, level)


def _draw(image: Image.Image, **overrides: object) -> list:
    return squiggle_strokes(image, SquiggleSettings(**overrides), PX_PER_MM, 0.3)  # type: ignore[arg-type]


def test_one_stroke_per_row() -> None:
    lines = _draw(_grey(100))
    # 80 px high at 4 px/mm with 2 mm rows: 10 rows.
    assert len(lines) == 10


def test_white_rows_are_straight() -> None:
    for line in _draw(_grey(255)):
        ys = np.asarray(line.coords)[:, 1]
        assert np.ptp(ys) < 1e-6


def test_darker_means_more_ink() -> None:
    lengths = [sum(line.length for line in _draw(_grey(level))) for level in (230, 160, 90, 20)]
    assert lengths == sorted(lengths)
    assert lengths[-1] > 2.0 * lengths[0]


def test_waves_stay_within_their_band() -> None:
    for line in _draw(_grey(0), max_amplitude=1.0):
        ys = np.asarray(line.coords)[:, 1]
        assert np.ptp(ys) <= 2.0 * PX_PER_MM + 1e-6


def test_frequency_never_tighter_than_two_pen_widths() -> None:
    lines = squiggle_strokes(_grey(0), SquiggleSettings(max_frequency=50.0), PX_PER_MM, 0.5)
    ys = np.asarray(lines[3].coords)[:, 1]
    crossings = np.count_nonzero(np.diff(np.sign(ys - ys.mean())) != 0)
    row_mm = 120 / PX_PER_MM
    assert crossings / 2.0 <= row_mm / (2 * 0.5) + 2


def test_serpentine_reverses_every_other_row() -> None:
    lines = _draw(_grey(255))
    assert lines[0].coords[0][0] < lines[0].coords[-1][0]
    assert lines[1].coords[0][0] > lines[1].coords[-1][0]
    straight = _draw(_grey(255), serpentine=False)
    assert straight[1].coords[0][0] < straight[1].coords[-1][0]


def test_skip_white_lifts_pen_over_paper() -> None:
    image = _grey(255)
    image.paste(0, (40, 0, 80, 80))
    assert len(_draw(image)) == 10
    split = _draw(image, skip_white=True)
    assert len(split) >= 10
    for line in split:
        xs = np.asarray(line.coords)[:, 0]
        assert xs.min() > 20 and xs.max() < 100


def test_angle_rotates_rows() -> None:
    lines = _draw(_grey(255), angle=90.0)
    xs = np.asarray(lines[0].coords)[:, 0]
    assert np.ptp(xs) < 1e-6


def test_settings_validation() -> None:
    with pytest.raises(ValidationError, match="max_frequency"):
        SquiggleSettings(min_frequency=2.0, max_frequency=1.0)


@pytest.mark.parametrize(("ppm", "pen"), [(0.0, 0.3), (4.0, 0.0), (math.nan, 0.3)])
def test_rejects_bad_scale(ppm: float, pen: float) -> None:
    with pytest.raises(ValueError):
        squiggle_strokes(_grey(0), SquiggleSettings(), ppm, pen)


def test_registered_with_presets() -> None:
    assert "squiggle" in list_pfms()
    fn, model = get_pfm("squiggle")
    assert fn is squiggle_strokes and model is SquiggleSettings
    for name, settings in SQUIGGLE_PRESETS.items():
        assert get_pfm_preset_by_id(f"squiggle:{name}") == ("squiggle", settings)
    result = CliRunner().invoke(main, ["info", "pfms", "--format", "json"])
    row = next(p for p in json.loads(result.stdout)["available_pfms"] if p["name"] == "squiggle")
    assert row["presets"] == ["squiggle:default", "squiggle:diagonal", "squiggle:fine"]


def test_cli_override() -> None:
    pfm = _resolve_pfm("squiggle:fine", {"angle": "30"})
    assert isinstance(pfm, RegisteredPFM)
    assert isinstance(pfm.settings, SquiggleSettings)
    assert pfm.settings.angle == 30.0
    assert pfm.settings.line_spacing == SQUIGGLE_PRESETS["fine"].line_spacing


def test_convert_writes_rows(tmp_path: Path) -> None:
    source = tmp_path / "grey.png"
    _grey(80).convert("RGB").save(source)
    output = tmp_path / "out.svg"
    result = CliRunner().invoke(
        main, ["convert", str(source), "-o", str(output), "--no-vpype", "--pfm", "squiggle"]
    )
    assert result.exit_code == 0, result.output
    assert "<path" in output.read_text() or "<polyline" in output.read_text()
