"""Tests for the Spiral Sawtooth PFM algorithm."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from shapely import LineString

from penpath.core.drawing.pfm_spiral import SpiralSettings, spiral_strokes
from penpath.core.image.load import load_image
from penpath.core.models import Paper, Pen
from penpath.core.output.svg import write_penpath_svg
from penpath.core.svg_parse import parse_svg_strokes

_REFERENCE_IMAGE = Path(__file__).resolve().parents[3] / "fixtures/images/reference/sphere.png"


def _sphere_image(width: int = 100, height: int = 120) -> Image.Image:
    """Return a bright gradient with a dark sphere, as an L image."""
    yy, xx = np.mgrid[0:height, 0:width]
    gradient = 255.0 - 120.0 * xx / max(1, width - 1)
    sphere = ((xx - width / 2) ** 2 + (yy - height / 2) ** 2) < (min(width, height) / 3) ** 2
    luminance = np.where(sphere, 30.0, gradient)
    return Image.fromarray(luminance.astype(np.uint8))


def _signature(lines: list[LineString]) -> str:
    return repr([tuple(line.coords) for line in lines])


class TestSpiralSettings:
    """Tests for SpiralSettings validation."""

    def test_default_settings(self):
        defaults = {
            "spiral_type": "archimedean",
            "centre_x": 0.5,
            "centre_y": 0.5,
            "spiral_size": 1.0,
            "ring_spacing": 7.0,
            "amplitude": 1.0,
            "variable_velocity": True,
            "min_velocity": 50.0,
            "max_velocity": 150.0,
            "connected_lines": True,
            "ignore_white": False,
            "seed": None,
            "max_strokes": None,
        }
        settings = SpiralSettings()
        for field, value in defaults.items():
            assert getattr(settings, field) == value

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"spiral_type": "logarithmic"}, "spiral_type"),
            ({"centre_x": -0.01}, "centre_x"),
            ({"centre_x": 1.01}, "centre_x"),
            ({"centre_y": -0.01}, "centre_y"),
            ({"centre_y": 1.01}, "centre_y"),
            ({"min_velocity": 150.0, "max_velocity": 50.0}, "max_velocity"),
            ({"ring_spacing": 0.0}, "ring_spacing"),
            ({"ring_spacing": -1.0}, "ring_spacing"),
            ({"spiral_size": 0.01}, "spiral_size"),
            ({"amplitude": 10.01}, "amplitude"),
            ({"max_strokes": 0}, "max_strokes"),
        ],
    )
    def test_invalid_settings_raise(self, kwargs: dict[str, object], message: str):
        with pytest.raises(ValueError, match=message):
            SpiralSettings(**kwargs)


class TestSpiralStrokes:
    """Tests for the spiral_strokes algorithm."""

    def test_same_settings_and_seed_are_deterministic(self):
        image = _sphere_image()
        settings = SpiralSettings()
        first = spiral_strokes(image, settings)
        second = spiral_strokes(image, settings)
        seeded_one = spiral_strokes(image, SpiralSettings(seed=1))
        seeded_two = spiral_strokes(image, SpiralSettings(seed=2))
        assert first
        assert _signature(first) == _signature(second)
        assert _signature(seeded_one) == _signature(seeded_two)

    def test_non_empty_strokes_stay_inside_image(self):
        width, height = 100, 120
        lines = spiral_strokes(_sphere_image(width, height), SpiralSettings())
        assert lines
        for line in lines:
            for x, y in line.coords:
                assert 0.0 <= x <= width - 1
                assert 0.0 <= y <= height - 1
        off_centre = spiral_strokes(
            _sphere_image(width, height), SpiralSettings(centre_x=0.25, centre_y=0.75)
        )
        assert len(off_centre) == 1
        assert all(
            0.0 <= x <= width - 1 and 0.0 <= y <= height - 1 for x, y in off_centre[0].coords
        )

    def test_no_zero_length_segments(self):
        lines = spiral_strokes(_sphere_image(), SpiralSettings())
        assert lines
        for line in lines:
            assert line.length > 0.0
            for (x0, y0), (x1, y1) in zip(line.coords, line.coords[1:], strict=False):
                assert math.hypot(x1 - x0, y1 - y0) > 0.0

    def test_default_archimedean_connected_is_one_stroke(self):
        lines = spiral_strokes(_sphere_image(), SpiralSettings())
        assert len(lines) == 1
        assert len(lines[0].coords) > 2
        assert spiral_strokes(_sphere_image(), SpiralSettings(variable_velocity=False))

    def test_parabolic_connected_has_at_most_two_strokes(self):
        lines = spiral_strokes(_sphere_image(), SpiralSettings(spiral_type="parabolic"))
        assert lines
        assert len(lines) <= 2
        assert all(line.length > 0.0 for line in lines)

    def test_disconnected_emits_two_point_teeth_and_respects_cap(self):
        lines = spiral_strokes(_sphere_image(), SpiralSettings(connected_lines=False))
        assert len(lines) > 10
        assert all(len(line.coords) == 2 and line.length > 0.0 for line in lines)
        capped = spiral_strokes(
            _sphere_image(), SpiralSettings(connected_lines=False, max_strokes=5)
        )
        assert len(capped) == 5

    def test_ignore_white_breaks_the_line_over_white_paper(self):
        image = _sphere_image()
        connected = spiral_strokes(image, SpiralSettings())
        broken = spiral_strokes(image, SpiralSettings(ignore_white=True))
        assert len(connected) == 1
        assert len(broken) > 1

    def test_ignore_white_on_blank_image_returns_no_strokes(self):
        image = Image.fromarray(np.full((100, 100), 255, dtype=np.uint8))
        assert spiral_strokes(image, SpiralSettings(ignore_white=True)) == []


def test_exports_are_available_from_core():
    from penpath.core import SpiralSettings as CoreSpiralSettings
    from penpath.core import spiral_strokes as core_spiral_strokes
    from penpath.core.drawing import SpiralSettings as DrawingSpiralSettings
    from penpath.core.drawing import spiral_strokes as drawing_spiral_strokes

    assert CoreSpiralSettings is SpiralSettings
    assert core_spiral_strokes is spiral_strokes
    assert DrawingSpiralSettings is SpiralSettings
    assert drawing_spiral_strokes is spiral_strokes


def test_end_to_end_reference_image_to_svg(tmp_path: Path):
    """A user can load a reference image, draw it and write a plottable SVG."""
    image = load_image(_REFERENCE_IMAGE)
    lines = spiral_strokes(image, SpiralSettings())
    assert len(lines) == 1

    paper = Paper(name="square", width_mm=100.0, height_mm=100.0, dpi=400)
    scale = paper.width_mm / max(image.width, image.height)
    paper_lines = [LineString([(x * scale, y * scale) for x, y in line.coords]) for line in lines]
    pen = Pen(name="black", width_mm=0.3)
    output = tmp_path / "spiral.svg"
    write_penpath_svg([paper_lines], paper, [pen], output)

    parsed = parse_svg_strokes(output)
    assert len(parsed) == 1
    assert parsed[0].polyline
    for x, y in parsed[0].polyline:
        assert 0.0 <= x <= paper.width_mm
        assert 0.0 <= y <= paper.height_mm
