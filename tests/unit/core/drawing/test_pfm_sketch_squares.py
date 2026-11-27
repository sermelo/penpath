"""Tests for the Sketch Squares PFM algorithm."""

from __future__ import annotations

import hashlib
from collections.abc import Callable

import pytest
from PIL import Image, ImageDraw
from shapely import LineString

from penpath.core.drawing import pfm_sketch_squares as squares_module
from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings
from penpath.core.drawing.pfm_sketch_squares import SketchSquaresSettings, sketch_squares


def _dark_square_image(width: int = 100, height: int = 100) -> Image.Image:
    image = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, width - 21, height - 21), fill=0)
    return image


def _signature(lines: list[LineString]) -> str:
    return hashlib.sha256(repr([tuple(line.coords) for line in lines]).encode()).hexdigest()


class TestSketchSquaresSettings:
    """Tests for SketchSquaresSettings validation."""

    def test_default_settings(self):
        settings = SketchSquaresSettings()
        assert settings.grid_angle == 45.0
        assert settings.line_density == 0.75
        assert settings.min_length == 2.0
        assert settings.max_length == 40.0
        assert settings.max_fill == 80.0
        assert settings.white_threshold == 0.92
        assert settings.seed is None
        assert settings.max_strokes is None

    def test_min_length_greater_than_max_length_raises(self):
        with pytest.raises(ValueError, match="min_length must be <= max_length"):
            SketchSquaresSettings(min_length=100.0, max_length=50.0)

    def test_grid_angle_bounds(self):
        with pytest.raises(ValueError):
            SketchSquaresSettings(grid_angle=-360.1)
        with pytest.raises(ValueError):
            SketchSquaresSettings(grid_angle=360.1)
        assert SketchSquaresSettings(grid_angle=-360.0).grid_angle == -360.0
        assert SketchSquaresSettings(grid_angle=360.0).grid_angle == 360.0

    def test_line_density_bounds(self):
        with pytest.raises(ValueError):
            SketchSquaresSettings(line_density=0.0)
        with pytest.raises(ValueError):
            SketchSquaresSettings(line_density=11.0)
        assert SketchSquaresSettings(line_density=0.01).line_density == 0.01
        assert SketchSquaresSettings(line_density=10.0).line_density == 10.0

    def test_max_fill_bounds(self):
        with pytest.raises(ValueError):
            SketchSquaresSettings(max_fill=0.0)
        with pytest.raises(ValueError):
            SketchSquaresSettings(max_fill=101.0)
        assert SketchSquaresSettings(max_fill=1.0).max_fill == 1.0
        assert SketchSquaresSettings(max_fill=100.0).max_fill == 100.0

    def test_white_threshold_bounds(self):
        with pytest.raises(ValueError):
            SketchSquaresSettings(white_threshold=-0.01)
        with pytest.raises(ValueError):
            SketchSquaresSettings(white_threshold=1.01)
        assert SketchSquaresSettings(white_threshold=1.0).white_threshold == 1.0

    def test_length_bounds(self):
        with pytest.raises(ValueError):
            SketchSquaresSettings(min_length=0.0)
        with pytest.raises(ValueError):
            SketchSquaresSettings(max_length=5001.0)


class TestSketchSquaresAlgorithm:
    """Tests for the sketch_squares algorithm."""

    def test_white_threshold_is_forwarded_to_the_shared_engine(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: list[float] = []

        def fake_engine(
            image: Image.Image,
            settings: SketchLinesSettings,
            angle_provider: Callable[..., float],
            shading_enabled: bool,
            squiggle_enabled: bool,
            shading_threshold: float,
        ) -> list[LineString]:
            captured.append(settings.white_threshold)
            return []

        monkeypatch.setattr(squares_module, "_run_sketch_engine", fake_engine)
        sketch_squares(Image.new("L", (20, 20), 255), SketchSquaresSettings(white_threshold=0.75))
        assert captured == [0.75]

    def test_same_seed_produces_identical_strokes(self):
        image = _dark_square_image()
        settings = SketchSquaresSettings(seed=42, max_strokes=20)
        first = sketch_squares(image, settings)
        second = sketch_squares(image, settings)
        assert first
        assert _signature(first) == _signature(second)

    def test_different_seed_produces_different_strokes(self):
        image = _dark_square_image()
        first = sketch_squares(image, SketchSquaresSettings(seed=1, max_strokes=20))
        second = sketch_squares(image, SketchSquaresSettings(seed=2, max_strokes=20))
        assert first and second
        assert _signature(first) != _signature(second)

    def test_all_points_inside_image(self):
        width, height = 64, 48
        image = Image.new("L", (width, height), 0)
        lines = sketch_squares(image, SketchSquaresSettings(seed=42, max_strokes=10))
        assert lines
        for line in lines:
            for x, y in line.coords:
                assert 0 <= x <= width - 1
                assert 0 <= y <= height - 1

    def test_no_zero_length_strokes(self):
        image = _dark_square_image()
        lines = sketch_squares(image, SketchSquaresSettings(seed=42, max_strokes=20))
        assert lines
        assert all(line.length > 0 for line in lines)

    def test_blank_image_returns_no_strokes(self):
        image = Image.new("L", (100, 100), 255)
        assert sketch_squares(image, SketchSquaresSettings(seed=42)) == []

    def test_rgb_image_input(self):
        image = Image.new("RGB", (100, 100), (255, 255, 255))
        draw = ImageDraw.Draw(image)
        draw.rectangle((30, 30, 69, 69), fill=(0, 0, 0))
        lines = sketch_squares(image, SketchSquaresSettings(seed=42, max_strokes=10))
        assert lines
        assert all(line.is_valid and line.length > 0 for line in lines)
        for line in lines:
            for x, y in line.coords:
                assert 0 <= x <= 99
                assert 0 <= y <= 99
