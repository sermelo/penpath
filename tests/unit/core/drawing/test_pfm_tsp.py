"""Tests for the TSP Art PFM (one continuous line through weighted dots)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner
from PIL import Image, ImageDraw
from shapely import LineString

from penpath.cli.commands.convert import _resolve_pfm
from penpath.cli.main import main
from penpath.core.drawing.pfm_tsp import TSPSettings, stipple_points, tsp_strokes
from penpath.core.drawing.registry import get_pfm, list_pfms
from penpath.core.models import RegisteredPFM
from penpath.presets.pfms import TSP_PRESETS, get_pfm_preset_by_id

PX_PER_MM = 4.0


def _disc(size: int = 120) -> Image.Image:
    image = Image.new("L", (size, size), 255)
    ImageDraw.Draw(image).ellipse((20, 20, size - 20, size - 20), fill=0)
    return image


def _draw(image: Image.Image, **overrides: object) -> list[LineString]:
    settings = TSPSettings(seed=3, **overrides)  # type: ignore[arg-type]
    return tsp_strokes(image, settings, PX_PER_MM, 0.3)


def _crossings(line: LineString) -> int:
    coords = list(line.coords)
    segments = [LineString(coords[i : i + 2]) for i in range(len(coords) - 1)]
    count = 0
    for i, first in enumerate(segments):
        for second in segments[i + 2 :]:
            if first.crosses(second):
                count += 1
    return count


def test_one_closed_stroke() -> None:
    lines = _draw(_disc())
    assert len(lines) == 1
    assert lines[0].coords[0] == lines[0].coords[-1]


def test_open_path_when_not_closed() -> None:
    (line,) = _draw(_disc(), closed=False)
    assert line.coords[0] != line.coords[-1]


def test_blank_image_draws_nothing() -> None:
    assert _draw(Image.new("L", (80, 80), 255)) == []


def test_dots_follow_darkness() -> None:
    (line,) = _draw(_disc())
    coords = np.asarray(line.coords)
    inside = np.hypot(coords[:, 0] - 60, coords[:, 1] - 60) <= 42
    assert inside.mean() > 0.95


def test_seed_is_deterministic() -> None:
    first = _draw(_disc())[0].coords[:]
    second = _draw(_disc())[0].coords[:]
    assert first == second


def test_point_count_follows_spacing_and_cap() -> None:
    dense = len(_draw(_disc(), point_spacing=0.5)[0].coords)
    sparse = len(_draw(_disc(), point_spacing=1.0)[0].coords)
    assert dense > 3 * sparse
    capped = len(_draw(_disc(), point_spacing=0.2, max_points=150)[0].coords)
    assert capped == 151  # closed loop repeats the first dot


def test_two_opt_removes_crossings() -> None:
    raw = _draw(_disc(), point_spacing=1.5, two_opt_passes=0)[0]
    improved = _draw(_disc(), point_spacing=1.5)[0]
    assert improved.length < raw.length
    assert _crossings(improved) < _crossings(raw)


def test_stipple_points_spread_evenly() -> None:
    weights = np.ones((60, 60))
    points = stipple_points(weights, 36, 10, np.random.default_rng(0))
    gaps = [
        min(math.dist(p, q) for j, q in enumerate(points) if j != i) for i, p in enumerate(points)
    ]
    assert min(gaps) > 5.0  # relaxed towards a 10 px grid


@pytest.mark.parametrize(("ppm", "pen"), [(0.0, 0.3), (4.0, -1.0), (math.inf, 0.3)])
def test_rejects_bad_scale(ppm: float, pen: float) -> None:
    with pytest.raises(ValueError):
        tsp_strokes(_disc(), TSPSettings(), ppm, pen)


def test_registered_with_presets() -> None:
    assert "tsp" in list_pfms()
    fn, model = get_pfm("tsp")
    assert fn is tsp_strokes and model is TSPSettings
    for name, settings in TSP_PRESETS.items():
        assert get_pfm_preset_by_id(f"tsp:{name}") == ("tsp", settings)
    result = CliRunner().invoke(main, ["info", "pfms", "--format", "json"])
    row = next(p for p in json.loads(result.stdout)["available_pfms"] if p["name"] == "tsp")
    assert row["presets"] == ["tsp:default", "tsp:fine"]


def test_cli_override() -> None:
    pfm = _resolve_pfm("tsp:fine", {"closed": "no"})
    assert isinstance(pfm, RegisteredPFM)
    assert isinstance(pfm.settings, TSPSettings)
    assert pfm.settings.closed is False
    assert pfm.settings.point_spacing == TSP_PRESETS["fine"].point_spacing


def test_convert_writes_one_path(tmp_path: Path) -> None:
    source = tmp_path / "disc.png"
    _disc().convert("RGB").save(source)
    output = tmp_path / "out.svg"
    result = CliRunner().invoke(
        main,
        ["convert", str(source), "-o", str(output), "--no-vpype", "--pfm", "tsp", "-s", "seed=1"],
    )
    assert result.exit_code == 0, result.output
    text = output.read_text()
    assert text.count("<path") + text.count("<polyline") == 1
