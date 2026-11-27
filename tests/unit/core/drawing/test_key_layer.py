"""Tests for the black key edge layer."""

from __future__ import annotations

from PIL import Image, ImageDraw
from shapely import LineString

from penpath.core import (
    STYLE_PRESETS,
    key_layer_strokes,
    outline_strokes,
)
from penpath.core.drawing import key_layer_strokes as drawing_key_layer_strokes
from penpath.core.drawing.key_layer import key_layer_strokes as module_key_layer_strokes


def _rectangle() -> Image.Image:
    image = Image.new("L", (128, 128), 255)
    ImageDraw.Draw(image).rectangle((20, 20, 100, 100), fill=0)
    return image


class TestKeyLayerStrokes:
    def test_public_exports_point_to_same_function(self) -> None:
        assert key_layer_strokes is drawing_key_layer_strokes is module_key_layer_strokes

    def test_simple_shape_gives_non_empty_deterministic_strokes(self) -> None:
        image = _rectangle()
        strokes = key_layer_strokes(image)
        assert strokes
        assert strokes == key_layer_strokes(image)
        assert all(isinstance(stroke, LineString) and stroke.length >= 24.0 for stroke in strokes)
        assert all(0 <= x <= 127 and 0 <= y <= 127 for stroke in strokes for x, y in stroke.coords)

    def test_blank_image_returns_no_strokes(self) -> None:
        assert key_layer_strokes(Image.new("RGB", (64, 64), "white")) == []
        assert key_layer_strokes(Image.new("L", (0, 0), 255)) == []

    def test_reuses_outline_style_settings(self) -> None:
        settings = STYLE_PRESETS["outline"].outline
        assert settings is not None
        image = _rectangle()
        assert key_layer_strokes(image) == outline_strokes(image, settings)
