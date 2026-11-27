"""Unit tests for the three paper placement modes (LUC-162)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from shapely import LineString

from penpath.core.models import Paper, Pen
from penpath.core.output.svg import (
    MM_PER_INCH,
    PENPATH_NAMESPACE,
    ImagePlacement,
    add_placement_metadata,
    export_pen_layers,
    export_svg,
    fit_image_placement,
)
from penpath.core.svg_parse import get_image_placement, parse_svg_strokes

IMAGE_SIZES = [(100, 200), (200, 100), (100, 100)]
PAPERS = [
    Paper(name="portrait", width_mm=210.0, height_mm=297.0, margin_mm=10.0),
    Paper(
        name="landscape",
        width_mm=200.0,
        height_mm=150.0,
        margin_mm=[10.0, 20.0, 30.0, 40.0],
    ),
]
EPS = 1e-9


def _placement(
    image_size_px: tuple[int, int], paper: Paper, mode: str, dpi: int = 300
) -> ImagePlacement:
    origin_x, origin_y = paper.drawable_origin_mm
    return fit_image_placement(
        image_size_px,
        paper.drawable_width_mm,
        paper.drawable_height_mm,
        image_dpi=dpi,
        offset_x_mm=origin_x,
        offset_y_mm=origin_y,
        mode=mode,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize("paper", PAPERS, ids=[paper.name for paper in PAPERS])
@pytest.mark.parametrize("image_size_px", IMAGE_SIZES, ids=["portrait", "landscape", "square"])
def test_fit_mode_contains_image_and_matches_the_legacy_default(
    image_size_px: tuple[int, int], paper: Paper
) -> None:
    origin_x, origin_y = paper.drawable_origin_mm
    placement = _placement(image_size_px, paper, "fit")
    legacy = fit_image_placement(
        image_size_px,
        paper.drawable_width_mm,
        paper.drawable_height_mm,
        image_dpi=300,
        offset_x_mm=origin_x,
        offset_y_mm=origin_y,
    )

    assert placement == legacy
    assert placement.width <= paper.drawable_width_mm + EPS
    assert placement.height <= paper.drawable_height_mm + EPS
    assert placement.width / placement.height == pytest.approx(image_size_px[0] / image_size_px[1])
    assert placement.x - origin_x == pytest.approx((paper.drawable_width_mm - placement.width) / 2)
    assert placement.y - origin_y == pytest.approx(
        (paper.drawable_height_mm - placement.height) / 2
    )


@pytest.mark.parametrize("paper", PAPERS, ids=[paper.name for paper in PAPERS])
@pytest.mark.parametrize("image_size_px", IMAGE_SIZES, ids=["portrait", "landscape", "square"])
def test_fill_mode_covers_the_drawable_area_and_preserves_aspect(
    image_size_px: tuple[int, int], paper: Paper
) -> None:
    origin_x, origin_y = paper.drawable_origin_mm
    placement = _placement(image_size_px, paper, "fill")

    assert placement.width >= paper.drawable_width_mm - EPS
    assert placement.height >= paper.drawable_height_mm - EPS
    assert (
        abs(placement.width - paper.drawable_width_mm) < EPS
        or abs(placement.height - paper.drawable_height_mm) < EPS
    )
    assert placement.width / placement.height == pytest.approx(image_size_px[0] / image_size_px[1])
    assert placement.x - origin_x == pytest.approx((paper.drawable_width_mm - placement.width) / 2)
    assert placement.y - origin_y == pytest.approx(
        (paper.drawable_height_mm - placement.height) / 2
    )


@pytest.mark.parametrize("paper", PAPERS, ids=[paper.name for paper in PAPERS])
@pytest.mark.parametrize("image_size_px", IMAGE_SIZES, ids=["portrait", "landscape", "square"])
@pytest.mark.parametrize("dpi", [72, 300])
def test_none_mode_uses_the_dpi_size_and_ignores_the_paper(
    image_size_px: tuple[int, int], paper: Paper, dpi: int
) -> None:
    placement = _placement(image_size_px, paper, "none", dpi)
    other_paper = PAPERS[0] if paper is PAPERS[1] else PAPERS[1]
    other = _placement(image_size_px, other_paper, "none", dpi)

    assert placement.width == pytest.approx(image_size_px[0] * MM_PER_INCH / dpi)
    assert placement.height == pytest.approx(image_size_px[1] * MM_PER_INCH / dpi)
    assert (placement.width, placement.height) == pytest.approx((other.width, other.height))
    origin_x, origin_y = paper.drawable_origin_mm
    assert placement.x - origin_x == pytest.approx((paper.drawable_width_mm - placement.width) / 2)
    assert placement.y - origin_y == pytest.approx(
        (paper.drawable_height_mm - placement.height) / 2
    )


def test_fit_image_placement_rejects_an_unknown_mode() -> None:
    with pytest.raises(ValueError, match="Unknown fit mode 'stretch'"):
        fit_image_placement((100, 100), 100.0, 100.0, mode="stretch")  # type: ignore[arg-type]


def _crossing_lines(image_size_px: tuple[int, int]) -> list[LineString]:
    width, height = image_size_px
    return [
        LineString([(0.0, 0.0), (float(width), float(height))]),
        LineString([(0.0, float(height)), (float(width), 0.0)]),
        LineString([(float(width) / 2, -5.0), (float(width) / 2, float(height) + 5.0)]),
        LineString([(-5.0, float(height) / 2), (float(width) + 5.0, float(height) / 2)]),
    ]


def _metadata(svg_path: Path) -> dict[str, str]:
    element = ET.parse(svg_path).getroot().find(f".//{{{PENPATH_NAMESPACE}}}image-placement")
    assert element is not None
    return dict(element.attrib)


def _points(svg_path: Path) -> list[tuple[float, float]]:
    return [point for stroke in parse_svg_strokes(svg_path) for point in stroke.polyline]


@pytest.mark.parametrize("paper", PAPERS, ids=[paper.name for paper in PAPERS])
@pytest.mark.parametrize("image_size_px", IMAGE_SIZES, ids=["portrait", "landscape", "square"])
def test_fill_export_clips_ink_on_all_four_sides(
    tmp_path: Path, image_size_px: tuple[int, int], paper: Paper
) -> None:
    placement = _placement(image_size_px, paper, "fill")
    origin_x, origin_y = paper.drawable_origin_mm
    clip = ImagePlacement(origin_x, origin_y, paper.drawable_width_mm, paper.drawable_height_mm)
    svg_path = tmp_path / "fill.svg"

    export_pen_layers(
        [_crossing_lines(image_size_px)],
        paper,
        [Pen(name="fine", width_mm=0.3)],
        svg_path,
        placement,
        image_size_px,
        mode="fill",
        clip_rect=clip,
    )

    points = _points(svg_path)
    assert points
    assert all(origin_x - 0.001 <= x <= origin_x + clip.width + 0.001 for x, _ in points)
    assert all(origin_y - 0.001 <= y <= origin_y + clip.height + 0.001 for _, y in points)
    assert min(x for x, _ in points) == pytest.approx(origin_x, abs=0.001)
    assert max(x for x, _ in points) == pytest.approx(origin_x + clip.width, abs=0.001)
    assert min(y for _, y in points) == pytest.approx(origin_y, abs=0.001)
    assert max(y for _, y in points) == pytest.approx(origin_y + clip.height, abs=0.001)

    attributes = _metadata(svg_path)
    assert attributes["fit"] == "fill"
    assert attributes["clip-x"] == f"{origin_x:.4f}"
    assert attributes["clip-y"] == f"{origin_y:.4f}"
    assert attributes["clip-width"] == f"{clip.width:.4f}"
    assert attributes["clip-height"] == f"{clip.height:.4f}"
    assert get_image_placement(svg_path, image_size_px) == pytest.approx(placement)


def test_export_svg_accepts_the_same_clip_rectangle(tmp_path: Path) -> None:
    paper = Paper(name="square", width_mm=100.0, height_mm=100.0, margin_mm=10.0)
    placement = _placement((100, 100), paper, "fill")
    clip = ImagePlacement(10.0, 10.0, 80.0, 80.0)
    svg_path = tmp_path / "direct.svg"

    export_svg(
        [LineString([(0.0, 0.0), (100.0, 100.0)])],
        paper,
        [Pen(name="fine", width_mm=0.3)],
        svg_path,
        image_placement=placement,
        image_size_px=(100, 100),
        mode="fill",
        clip_rect=clip,
    )

    assert all(10.0 - 0.001 <= x <= 90.0 + 0.001 for x, _ in _points(svg_path))
    assert _metadata(svg_path)["fit"] == "fill"
    assert _metadata(svg_path)["clip-width"] == "80.0000"


def test_none_export_records_the_dpi_rectangle_without_a_clip(tmp_path: Path) -> None:
    paper = Paper(name="small", width_mm=60.0, height_mm=60.0, margin_mm=10.0)
    image_size_px = (120, 120)
    placement = _placement(image_size_px, paper, "none", dpi=72)
    svg_path = tmp_path / "none.svg"

    export_pen_layers(
        [_crossing_lines(image_size_px)],
        paper,
        [Pen(name="fine", width_mm=0.3)],
        svg_path,
        placement,
        image_size_px,
        mode="none",
    )

    attributes = _metadata(svg_path)
    assert attributes["fit"] == "none"
    assert not any(key.startswith("clip-") for key in attributes)
    assert get_image_placement(svg_path, image_size_px) == pytest.approx(placement, abs=0.001)
    assert placement.width > paper.drawable_width_mm
    assert any(x < paper.drawable_origin_mm[0] for x, _ in _points(svg_path))


def test_default_export_metadata_stays_byte_identical(tmp_path: Path) -> None:
    paper = Paper(name="square", width_mm=100.0, height_mm=100.0)
    placement = ImagePlacement(10.0, 10.0, 80.0, 80.0)
    lines = [LineString([(0.0, 0.0), (100.0, 100.0)])]
    legacy_path = tmp_path / "legacy.svg"
    explicit_path = tmp_path / "explicit.svg"

    export_svg(
        lines,
        paper,
        [Pen(name="fine", width_mm=0.3)],
        legacy_path,
        image_placement=placement,
        image_size_px=(100, 100),
    )
    export_svg(
        lines,
        paper,
        [Pen(name="fine", width_mm=0.3)],
        explicit_path,
        image_placement=placement,
        image_size_px=(100, 100),
        mode="fit",
    )

    assert explicit_path.read_bytes() == legacy_path.read_bytes()
    assert "fit" not in _metadata(legacy_path)


def test_add_placement_metadata_round_trips_mode_and_clip(tmp_path: Path) -> None:
    paper = Paper(name="square", width_mm=100.0, height_mm=100.0)
    placement = ImagePlacement(-5.0, -5.0, 110.0, 110.0)
    clip = ImagePlacement(10.0, 10.0, 80.0, 80.0)
    svg_path = tmp_path / "patched.svg"
    export_svg(
        [LineString([(0.0, 0.0), (100.0, 100.0)])],
        paper,
        [Pen(name="fine", width_mm=0.3)],
        svg_path,
    )

    add_placement_metadata(svg_path, placement, mode="fill", clip_rect=clip)
    add_placement_metadata(svg_path, placement, mode="fill", clip_rect=clip)

    assert svg_path.read_text().count("image-placement") == 1
    assert _metadata(svg_path)["fit"] == "fill"
    assert _metadata(svg_path)["clip-x"] == "10.0000"
    assert get_image_placement(svg_path, (100, 100)) == pytest.approx(placement)
