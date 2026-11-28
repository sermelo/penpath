"""Unit tests for the shared preview renderer."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image
from shapely.geometry import LineString

from penpath.core import (
    Drawing,
    ImagePlacement,
    InvalidPaperColorError,
    Paper,
    Pen,
    PreviewError,
    RenderBudgetError,
    WorkingResolution,
    preview,
)

preview_core = import_module("penpath.core.preview")


def _svg() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
     xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
     width="100mm" height="100mm" viewBox="0 0 100 100">
  <g inkscape:groupmode="layer" inkscape:label="fine" id="layer1"
     stroke="#000000" stroke-width="2">
    <path d="M 10 25 L 90 25"/>
  </g>
  <g inkscape:groupmode="layer" inkscape:label="bold" id="layer2"
     stroke="#FF0000" stroke-width="2">
    <path d="M 10 75 L 90 75"/>
  </g>
</svg>"""


@pytest.fixture
def svg_path(tmp_path: Path) -> Path:
    path = tmp_path / "plot.svg"
    path.write_text(_svg(), encoding="utf-8")
    return path


@pytest.fixture
def drawing() -> Drawing:
    """A 100 mm page with one black stroke and one red stroke."""
    return Drawing(
        paper=Paper(name="test", width_mm=100, height_mm=100, margin_mm=0),
        pens=[
            Pen(name="fine", width_mm=2, color="#000000"),
            Pen(name="bold", width_mm=2, color="#FF0000"),
        ],
        strokes_by_pen=[
            [LineString([(10, 25), (90, 25)])],
            [LineString([(10, 75), (90, 75)])],
        ],
        image_placement=ImagePlacement(0, 0, 100, 100),
        resolution=WorkingResolution((100, 100), (100, 100), 1.0, 100, 100, 2.0),
        fit_mode="fit",
        clip_rect=None,
        source_size_px=(100, 100),
        working_size_px=(100, 100),
    )


def test_preview_svg_path_writes_expected_pixels(svg_path: Path, tmp_path: Path) -> None:
    output = tmp_path / "preview.png"

    result = preview(svg_path, output, px_per_mm=2)

    assert result == output
    with Image.open(output) as image:
        assert image.size == (200, 200)
        assert image.getpixel((50, 50)) == (0, 0, 0)
        assert image.getpixel((50, 150)) == (255, 0, 0)
        assert image.getpixel((50, 100)) == (255, 255, 255)


def test_preview_drawing_matches_its_svg(drawing: Drawing, tmp_path: Path) -> None:
    from_drawing = preview(drawing, tmp_path / "from-drawing.png", px_per_mm=2)
    svg_path = drawing.to_svg(tmp_path / "plot.svg", use_vpype=False)
    from_svg = preview(svg_path, tmp_path / "from-svg.png", px_per_mm=2)

    assert from_drawing.read_bytes() == from_svg.read_bytes()
    with Image.open(from_drawing) as image:
        assert image.size == (200, 200)
        assert image.getpixel((50, 50)) == (0, 0, 0)
        assert image.getpixel((50, 150)) == (255, 0, 0)


def test_preview_dpi_uses_real_dots_per_inch(svg_path: Path, tmp_path: Path) -> None:
    output = tmp_path / "dpi.png"

    preview(svg_path, output, dpi=100)

    with Image.open(output) as image:
        assert image.size == (394, 394)


def test_preview_layer_selects_one_pen(svg_path: Path, tmp_path: Path) -> None:
    all_path = preview(svg_path, tmp_path / "all.png", px_per_mm=2)
    one_path = preview(svg_path, tmp_path / "one.png", px_per_mm=2, layer="fine")

    with Image.open(all_path) as all_image, Image.open(one_path) as one_image:
        assert all_image.getpixel((50, 150)) == (255, 0, 0)
        assert one_image.getpixel((50, 150)) == (255, 255, 255)
        assert one_image.getpixel((50, 50)) == (0, 0, 0)


def test_preview_travel_draws_light_lines_under_ink(svg_path: Path, tmp_path: Path) -> None:
    ink_path = preview(svg_path, tmp_path / "ink.png", px_per_mm=2)
    travel_path = preview(svg_path, tmp_path / "travel.png", px_per_mm=2, travel=True)

    with Image.open(ink_path) as ink, Image.open(travel_path) as travel:
        assert ink.getpixel((100, 100)) == (255, 255, 255)
        assert travel.getpixel((100, 100)) == (200, 200, 200)
        assert travel.getpixel((50, 50)) == ink.getpixel((50, 50))


def test_preview_render_budget_rejects_before_allocating(
    svg_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    simulate = Mock(side_effect=AssertionError("simulate_plot must not be called"))
    monkeypatch.setattr(preview_core, "simulate_plot", simulate)
    output = tmp_path / "huge.png"

    with pytest.raises(RenderBudgetError, match=r"renders 100000x100000 px \(10000\.0 MP\)"):
        preview(svg_path, output, px_per_mm=1000)

    simulate.assert_not_called()
    assert not output.exists()


def test_preview_force_skips_only_the_budget(
    svg_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    simulate = Mock(return_value=Image.new("RGB", (8, 8), "white"))
    monkeypatch.setattr(preview_core, "simulate_plot", simulate)
    output = tmp_path / "forced.png"

    result = preview(svg_path, output, px_per_mm=1000, force=True)

    assert result == output
    assert simulate.call_args.kwargs["dpi_px_per_mm"] == 1000
    with Image.open(output) as image:
        assert image.size == (8, 8)


def test_preview_bad_paper_color_is_a_clean_error(svg_path: Path, tmp_path: Path) -> None:
    with pytest.raises(InvalidPaperColorError):
        preview(svg_path, tmp_path / "bad.png", paper_color="notacolour")
    assert not (tmp_path / "bad.png").exists()


def test_preview_missing_layer_is_an_error(svg_path: Path, tmp_path: Path) -> None:
    with pytest.raises(PreviewError, match="No pen strokes found"):
        preview(svg_path, tmp_path / "missing.png", layer="missing")
