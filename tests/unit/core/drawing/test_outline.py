"""Tests for the optional edge/outline stroke pass."""

from __future__ import annotations

import math

import pytest
from PIL import Image, ImageDraw
from pydantic import ValidationError
from shapely import LineString

from penpath.core import OutlineSettings, outline_strokes
from penpath.core.drawing import outline_strokes as drawing_outline_strokes
from penpath.core.drawing.outline import outline_strokes as module_outline_strokes


def _rectangle(speck: bool = False) -> Image.Image:
    image = Image.new("L", (128, 128), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 100, 100), fill=0)
    if speck:
        draw.rectangle((115, 115, 117, 117), fill=0)
    return image


class TestOutlineSettings:
    def test_defaults(self) -> None:
        settings = OutlineSettings()
        assert settings.blur_sigma == 1.0
        assert settings.edge_sigma == 1.0
        assert settings.low_threshold == 0.1
        assert settings.high_threshold == 0.2
        assert settings.close_radius == 1
        assert settings.min_component_pixels == 12
        assert settings.min_length == 12.0
        assert settings.simplify_tolerance == 1.0
        assert settings.seed is None

    @pytest.mark.parametrize(
        "field,value",
        [
            ("blur_sigma", -0.1),
            ("blur_sigma", 10.1),
            ("edge_sigma", 0.0),
            ("edge_sigma", 11.0),
            ("low_threshold", -0.01),
            ("low_threshold", 1.01),
            ("high_threshold", -0.01),
            ("high_threshold", 1.01),
            ("high_threshold", 0.1),
            ("close_radius", -1),
            ("close_radius", 21),
            ("min_component_pixels", 0),
            ("min_component_pixels", 10001),
            ("min_length", 0.0),
            ("min_length", 10001.0),
            ("simplify_tolerance", -0.1),
            ("simplify_tolerance", 101.0),
        ],
    )
    def test_out_of_range_values_are_rejected(self, field: str, value: object) -> None:
        with pytest.raises(ValidationError):
            OutlineSettings(**{field: value})

    def test_equal_thresholds_are_rejected(self) -> None:
        with pytest.raises(ValidationError, match="high_threshold must be greater"):
            OutlineSettings(low_threshold=0.5, high_threshold=0.5)

    def test_range_boundaries_are_accepted(self) -> None:
        settings = OutlineSettings(
            blur_sigma=0.0,
            edge_sigma=10.0,
            low_threshold=0.0,
            high_threshold=1.0,
            close_radius=0,
            min_component_pixels=1,
            min_length=1.0,
            simplify_tolerance=0.0,
        )
        assert settings.close_radius == 0
        assert settings.high_threshold == 1.0


class TestOutlineStrokes:
    def test_public_exports_point_to_same_function(self) -> None:
        assert outline_strokes is drawing_outline_strokes is module_outline_strokes

    def test_blank_and_empty_images_return_no_strokes(self) -> None:
        settings = OutlineSettings()
        assert outline_strokes(Image.new("L", (64, 64), 255), settings) == []
        assert outline_strokes(Image.new("L", (64, 64), 0), settings) == []
        assert outline_strokes(Image.new("L", (0, 0), 255), settings) == []

    def test_rectangle_gets_outline_coverage_on_every_side(self) -> None:
        strokes = outline_strokes(_rectangle(), OutlineSettings())
        assert strokes
        points = [(x, y) for stroke in strokes for x, y in stroke.coords]

        sides = (
            [y for x, y in points if abs(x - 20) <= 4 and 20 <= y <= 100],
            [y for x, y in points if abs(x - 100) <= 4 and 20 <= y <= 100],
            [x for x, y in points if abs(y - 20) <= 4 and 20 <= x <= 100],
            [x for x, y in points if abs(y - 100) <= 4 and 20 <= x <= 100],
        )
        for positions in sides:
            assert positions
            assert max(positions) - min(positions) >= 60

    def test_circle_gets_outline_coverage_around_the_ring(self) -> None:
        image = Image.new("L", (128, 128), 255)
        ImageDraw.Draw(image).ellipse((20, 20, 100, 100), fill=0)
        strokes = outline_strokes(image, OutlineSettings())
        points = [(x, y) for stroke in strokes for x, y in stroke.coords]
        on_ring = [(x, y) for x, y in points if abs(math.hypot(x - 60.0, y - 60.0) - 40.0) <= 5.0]
        assert len(on_ring) >= 0.8 * len(points)
        assert len({int(math.degrees(math.atan2(y - 60, x - 60)) // 15) for x, y in on_ring}) >= 8

    def test_isolated_speck_is_rejected(self) -> None:
        strokes = outline_strokes(_rectangle(speck=True), OutlineSettings())
        assert strokes
        assert not any(x >= 110 and y >= 110 for stroke in strokes for x, y in stroke.coords)

        tiny = Image.new("L", (128, 128), 255)
        ImageDraw.Draw(tiny).rectangle((20, 20, 22, 22), fill=0)
        assert outline_strokes(tiny, OutlineSettings()) == []

    def test_strokes_are_valid_in_bounds_and_long_enough(self) -> None:
        settings = OutlineSettings(min_length=25.0, simplify_tolerance=0.0)
        image = _rectangle(speck=True)
        strokes = outline_strokes(image, settings)
        assert strokes
        width, height = image.size
        for stroke in strokes:
            assert isinstance(stroke, LineString)
            assert stroke.is_valid
            assert stroke.length >= settings.min_length
            for x, y in stroke.coords:
                assert 0.0 <= x <= width - 1
                assert 0.0 <= y <= height - 1

    def test_same_image_and_settings_give_identical_strokes(self) -> None:
        settings = OutlineSettings(seed=42)
        first = outline_strokes(_rectangle(), settings)
        second = outline_strokes(_rectangle(), OutlineSettings(seed=7))
        assert [list(line.coords) for line in first] == [list(line.coords) for line in second]

    def test_simplification_drops_vertices(self) -> None:
        image = _rectangle()
        fine = outline_strokes(image, OutlineSettings(simplify_tolerance=0.0))
        coarse = outline_strokes(image, OutlineSettings(simplify_tolerance=5.0))
        assert sum(len(list(line.coords)) for line in coarse) < sum(
            len(list(line.coords)) for line in fine
        )

    def test_changed_settings_change_the_strokes(self) -> None:
        image = _rectangle()
        default = outline_strokes(image, OutlineSettings())
        blurred = outline_strokes(image, OutlineSettings(blur_sigma=3.0))
        assert [list(line.coords) for line in default] != [list(line.coords) for line in blurred]
