"""End-to-end check of image to outline strokes to a plottable SVG."""

from __future__ import annotations

from pathlib import Path

import pytest
from shapely import LineString

from penpath.core import (
    OutlineSettings,
    Paper,
    Pen,
    load_image,
    outline_strokes,
    parse_svg_strokes,
)
from penpath.core.output.svg import fit_image_placement, write_penpath_svg

_REFERENCES = Path(__file__).parent.parent / "fixtures" / "images" / "reference"


@pytest.mark.parametrize("name", ["face.jpg", "photo.jpg"])
def test_outline_strokes_render_to_svg_for_reference_images(tmp_path: Path, name: str) -> None:
    """A library user can load a reference photo, outline it and write an SVG."""
    image = load_image(_REFERENCES / name)
    strokes = outline_strokes(image, OutlineSettings())
    assert len(strokes) >= 100

    paper = Paper(name="outline", width_mm=100.0, height_mm=100.0, margin_mm=0.0)
    placement = fit_image_placement(image.size, paper.width_mm, paper.height_mm)
    scale = placement.width / image.width

    scaled = [
        LineString([(placement.x + x * scale, placement.y + y * scale) for x, y in stroke.coords])
        for stroke in strokes
    ]
    output = tmp_path / "outline.svg"
    write_penpath_svg([scaled], paper, [Pen(name="outline", width_mm=0.3)], output)

    parsed = parse_svg_strokes(output)
    assert len(parsed) == len(strokes)
    assert all(not stroke.pen_up for stroke in parsed)
    for stroke in parsed:
        for x, y in stroke.polyline:
            assert placement.x - 0.01 <= x <= placement.x + placement.width + 0.01
            assert placement.y - 0.01 <= y <= placement.y + placement.height + 0.01
