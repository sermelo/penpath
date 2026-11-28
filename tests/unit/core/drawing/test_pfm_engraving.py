"""Tests for the Engraving PFM (lines whose width follows darkness)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner
from PIL import Image, ImageDraw
from pydantic import ValidationError
from shapely import LineString

from penpath.cli.commands.convert import _resolve_pfm
from penpath.cli.main import main
from penpath.core.drawing.pfm_engraving import (
    EngravingSettings,
    engraving_strokes,
    strokes_per_line,
)
from penpath.core.drawing.registry import get_pfm, list_pfms
from penpath.core.models import RegisteredPFM
from penpath.presets.pfms import ENGRAVING_PRESETS, get_pfm_preset_by_id

PX_PER_MM = 4.0
PEN = 0.3


def _grey(level: int, size: tuple[int, int] = (120, 120)) -> Image.Image:
    return Image.new("L", size, level)


def _draw(image: Image.Image, **overrides: object) -> list[LineString]:
    settings = EngravingSettings(tone_blur=0.0, **overrides)  # type: ignore[arg-type]
    return engraving_strokes(image, settings, PX_PER_MM, PEN)


def _ink(lines: list[LineString]) -> float:
    return sum(line.length for line in lines)


def test_white_draws_nothing() -> None:
    assert _draw(_grey(255)) == []


def test_ink_grows_with_darkness_in_steps() -> None:
    inks = [_ink(_draw(_grey(level))) for level in (220, 170, 120, 70, 0)]
    assert inks == sorted(inks)
    assert inks[-1] > 3.0 * inks[0]


def test_black_fills_every_stroke_of_a_line() -> None:
    # 1.5 mm lines with a 0.3 mm pen hold 5 strokes; black draws all of them.
    black = _draw(_grey(0), angle=0.0)
    ys = sorted({round(float(np.mean(np.asarray(line.coords)[:, 1])), 1) for line in black})
    gaps = np.diff(ys)
    assert np.allclose(gaps, PEN * PX_PER_MM, atol=0.3)


def test_strokes_follow_angle() -> None:
    for line in _draw(_grey(60), angle=0.0):
        ys = np.asarray(line.coords)[:, 1]
        assert np.ptp(ys) < 0.6


def test_hairline_keeps_centre_stroke_in_light_areas() -> None:
    light = _grey(235)
    without = _draw(light, min_tone=0.05)
    with_hair = _draw(light, min_tone=0.05, hairline=True)
    assert _ink(with_hair) > _ink(without)


def test_swirl_bends_the_lines() -> None:
    lines = _draw(_grey(100), layout="swirl", swirl_turns=1.0, angle=0.0)
    straight_ish = sum(np.ptp(np.asarray(line.coords)[:, 1]) < 1.0 for line in lines)
    assert straight_ish < len(lines) / 2


def test_contour_layout_echoes_a_shape() -> None:
    image = Image.new("L", (160, 160), 90)
    ImageDraw.Draw(image).ellipse((50, 50, 110, 110), fill=230)
    lines = _draw(image, layout="contour")
    assert lines
    # Rings around the disc: many strokes curve (not straight lines).
    curved = sum(
        LineString(line.coords).length > 1.2 * math.dist(line.coords[0], line.coords[-1])
        for line in lines
    )
    assert curved > 0


def test_strokes_per_line_scales_with_level() -> None:
    assert strokes_per_line(np.array([0.0, 0.5, 1.0]), 5, 1.0).tolist() == [0.0, 2.5, 5.0]


def test_strokes_inside_image() -> None:
    lines = _draw(_grey(40, (90, 70)))
    coords = np.concatenate([np.asarray(line.coords) for line in lines])
    assert coords[:, 0].min() >= 0 and coords[:, 0].max() <= 89
    assert coords[:, 1].min() >= 0 and coords[:, 1].max() <= 69


def test_settings_validation() -> None:
    with pytest.raises(ValidationError):
        EngravingSettings(layout="spiral")  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="edge_high"):
        EngravingSettings(edge_low=0.3, edge_high=0.2)


@pytest.mark.parametrize(("ppm", "pen"), [(0.0, 0.3), (4.0, 0.0), (math.nan, 0.3)])
def test_rejects_bad_scale(ppm: float, pen: float) -> None:
    with pytest.raises(ValueError):
        engraving_strokes(_grey(0), EngravingSettings(), ppm, pen)


def test_registered_with_presets() -> None:
    assert "engraving" in list_pfms()
    fn, model = get_pfm("engraving")
    assert fn is engraving_strokes and model is EngravingSettings
    for name, settings in ENGRAVING_PRESETS.items():
        assert get_pfm_preset_by_id(f"engraving:{name}") == ("engraving", settings)
    result = CliRunner().invoke(main, ["info", "pfms", "--format", "json"])
    row = next(p for p in json.loads(result.stdout)["available_pfms"] if p["name"] == "engraving")
    assert set(row["presets"]) == {f"engraving:{n}" for n in ENGRAVING_PRESETS}


def test_cli_override() -> None:
    pfm = _resolve_pfm("engraving:swirl", {"swirl_turns": "2"})
    assert isinstance(pfm, RegisteredPFM)
    assert isinstance(pfm.settings, EngravingSettings)
    assert pfm.settings.layout == "swirl"
    assert pfm.settings.swirl_turns == 2.0


def test_convert_cli(tmp_path: Path) -> None:
    source = tmp_path / "grey.png"
    _grey(90).convert("RGB").save(source)
    output = tmp_path / "out.svg"
    result = CliRunner().invoke(
        main, ["convert", str(source), "-o", str(output), "--no-vpype", "--pfm", "engraving"]
    )
    assert result.exit_code == 0, result.output
    assert "<path" in output.read_text() or "<polyline" in output.read_text()
