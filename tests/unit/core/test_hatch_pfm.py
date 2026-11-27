"""Tests for the straight / cross-hatching PFM core algorithm."""

from __future__ import annotations

import math
from itertools import pairwise

import pytest
from PIL import Image
from shapely import LineString, box

from penpath.core import HatchSettings as CoreHatchSettings
from penpath.core import hatch_strokes as core_hatch_strokes
from penpath.core.drawing import HatchSettings, hatch_strokes

PPM = 10.0
PEN_WIDTH = 0.3


def _hatch(image: Image.Image, **overrides: object) -> list[LineString]:
    return hatch_strokes(image, HatchSettings.model_validate(overrides), PPM, PEN_WIDTH)


def _column_image(width: int, height: int, dark_columns: set[int]) -> Image.Image:
    image = Image.new("L", (width, height), 255)
    for y in range(height):
        for x in dark_columns:
            image.putpixel((x, y), 0)
    return image


def _gradient_image(width: int, height: int) -> Image.Image:
    image = Image.new("L", (width, height))
    for x in range(width):
        tone = round(255.0 * (1.0 - x / (width - 1)))
        for y in range(height):
            image.putpixel((x, y), tone)
    return image


class TestHatchSettings:
    def test_defaults(self) -> None:
        settings = HatchSettings()
        assert settings.spacing == 1.0
        assert settings.angles == (45.0, 135.0, 0.0, 90.0)
        assert settings.thresholds == (0.2, 0.4, 0.6, 0.8)
        assert settings.min_length == 0.5
        assert settings.min_gap == 0.3
        assert settings.variable_spacing is False
        assert settings.serpentine is True
        assert settings.jitter == 0.0
        assert settings.seed is None

    def test_unequal_band_lengths_rejected(self) -> None:
        with pytest.raises(ValueError, match="angles and thresholds must have the same length"):
            HatchSettings(angles=(0.0, 90.0), thresholds=(0.2,))

    def test_non_increasing_thresholds_rejected(self) -> None:
        with pytest.raises(ValueError, match="thresholds must be strictly increasing"):
            HatchSettings(angles=(0.0, 90.0), thresholds=(0.5, 0.5))

    @pytest.mark.parametrize("threshold", [0.0, 1.0, -0.1, 1.1])
    def test_out_of_range_thresholds_rejected(self, threshold: float) -> None:
        with pytest.raises(ValueError, match="each threshold must be in"):
            HatchSettings(thresholds=(threshold,))

    @pytest.mark.parametrize("angle", [-361.0, 361.0])
    def test_out_of_range_angles_rejected(self, angle: float) -> None:
        with pytest.raises(ValueError, match="each angle must be in"):
            HatchSettings(angles=(angle,))

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"spacing": 0.0},
            {"spacing": -1.0},
            {"min_length": -0.1},
            {"min_gap": -0.1},
            {"jitter": -0.1},
        ],
    )
    def test_invalid_lengths_rejected(self, kwargs: dict[str, object]) -> None:
        with pytest.raises(ValueError):
            HatchSettings.model_validate(kwargs)

    def test_valid_single_band_accepted(self) -> None:
        settings = HatchSettings(angles=(0.0,), thresholds=(0.5,))
        assert settings.angles == (0.0,)
        assert settings.thresholds == (0.5,)


class TestHatchScaleValidation:
    @pytest.mark.parametrize("scale", [0.0, -1.0])
    def test_non_positive_pixels_per_mm_rejected(self, scale: float) -> None:
        with pytest.raises(ValueError, match="pixels_per_mm must be a positive number"):
            hatch_strokes(Image.new("L", (10, 10), 255), HatchSettings(), scale, PEN_WIDTH)

    @pytest.mark.parametrize("width", [0.0, -0.3])
    def test_non_positive_pen_width_rejected(self, width: float) -> None:
        with pytest.raises(ValueError, match="pen_width_mm must be a positive number"):
            hatch_strokes(Image.new("L", (10, 10), 255), HatchSettings(), PPM, width)


class TestHatchAlgorithm:
    def test_blank_white_image_has_no_strokes(self) -> None:
        assert _hatch(Image.new("L", (80, 80), 255)) == []

    def test_black_image_draws_every_band_direction(self) -> None:
        strokes = _hatch(Image.new("L", (80, 80), 0), seed=42)
        assert strokes
        expected = {0.0, 45.0, 90.0, 135.0}
        seen: set[float] = set()
        for stroke in strokes:
            (x0, y0), (x1, y1) = stroke.coords
            angle = math.degrees(math.atan2(y1 - y0, x1 - x0)) % 180.0
            chosen = min(expected, key=lambda item: abs(item - angle))
            assert abs(angle - chosen) < 1.0
            seen.add(chosen)
        assert seen == expected

    def test_points_inside_image_and_no_zero_length(self) -> None:
        image = _gradient_image(90, 70)
        settings = HatchSettings(variable_spacing=True, jitter=0.5, seed=7)
        strokes = hatch_strokes(image, settings, PPM, PEN_WIDTH)
        assert strokes
        for stroke in strokes:
            assert isinstance(stroke, LineString)
            assert stroke.is_valid
            assert stroke.length > 0.0
            for x, y in stroke.coords:
                assert 0.0 <= x <= image.width - 1
                assert 0.0 <= y <= image.height - 1

    def test_tiny_spacing_respects_pen_width(self) -> None:
        strokes = _hatch(
            Image.new("L", (100, 100), 0),
            angles=(0.0,),
            thresholds=(0.5,),
            spacing=0.001,
            serpentine=False,
        )
        assert len(strokes) >= 5
        rows = sorted({round(y, 6) for stroke in strokes for _x, y in stroke.coords})
        assert all(later - earlier >= PEN_WIDTH * PPM - 1e-6 for earlier, later in pairwise(rows))

    def test_min_gap_bridges_short_gap(self) -> None:
        image = _column_image(100, 80, set(range(10, 40)) | set(range(45, 90)))
        separate = _hatch(
            image, angles=(0.0,), thresholds=(0.5,), min_gap=0.0, min_length=0.0, spacing=5.0
        )
        bridged = _hatch(
            image, angles=(0.0,), thresholds=(0.5,), min_gap=2.0, min_length=0.0, spacing=5.0
        )
        assert len(separate) == 4
        assert len(bridged) == 2
        assert all(stroke.length > max(line.length for line in separate) for stroke in bridged)

    def test_min_length_drops_short_run(self) -> None:
        image = _column_image(100, 80, {10, 11, 12})
        kept = _hatch(image, angles=(0.0,), thresholds=(0.5,), min_length=0.0, spacing=5.0)
        dropped = _hatch(image, angles=(0.0,), thresholds=(0.5,), min_length=1.0, spacing=5.0)
        assert len(kept) == 2
        assert dropped == []

    def test_serpentine_false_keeps_direction_true_alternates(self) -> None:
        image = Image.new("L", (80, 80), 0)
        forward = _hatch(image, angles=(0.0,), thresholds=(0.5,), spacing=2.0, serpentine=False)
        alternating = _hatch(image, angles=(0.0,), thresholds=(0.5,), spacing=2.0, serpentine=True)
        assert len(forward) == len(alternating) >= 3
        assert all(stroke.coords[-1][0] > stroke.coords[0][0] for stroke in forward)
        for index, stroke in enumerate(alternating):
            expected_sign = 1 if index % 2 == 0 else -1
            actual_sign = 1 if stroke.coords[-1][0] > stroke.coords[0][0] else -1
            assert actual_sign == expected_sign

    def test_density_increases_towards_dark(self) -> None:
        image = _gradient_image(120, 80)
        strokes = _hatch(image, seed=42)
        assert strokes
        light = box(0.0, 0.0, 60.0, image.height - 1)
        dark = box(60.0, 0.0, image.width - 1, image.height - 1)
        light_length = sum(stroke.intersection(light).length for stroke in strokes)
        dark_length = sum(stroke.intersection(dark).length for stroke in strokes)
        assert dark_length > light_length * 2.0

    def test_same_seed_repeats_and_different_seed_changes_strokes(self) -> None:
        image = Image.new("L", (80, 80), 0)
        first = _hatch(image, jitter=0.4, seed=42)
        second = _hatch(image, jitter=0.4, seed=42)
        third = _hatch(image, jitter=0.4, seed=43)
        assert first == second
        assert [list(stroke.coords) for stroke in first] == [
            list(stroke.coords) for stroke in second
        ]
        assert [list(stroke.coords) for stroke in first] != [
            list(stroke.coords) for stroke in third
        ]

    def test_variable_spacing_makes_darker_band_denser(self) -> None:
        strokes = _hatch(
            Image.new("L", (100, 100), 0),
            angles=(0.0, 90.0),
            thresholds=(0.2, 0.8),
            spacing=1.0,
            variable_spacing=True,
        )
        horizontal = sum(
            1
            for stroke in strokes
            if math.isclose(stroke.coords[0][1], stroke.coords[-1][1], abs_tol=1e-6)
        )
        vertical = sum(
            1
            for stroke in strokes
            if math.isclose(stroke.coords[0][0], stroke.coords[-1][0], abs_tol=1e-6)
        )
        assert vertical > horizontal

    def test_l_and_rgb_twins_match(self) -> None:
        gray = _gradient_image(70, 60)
        rgb = Image.merge("RGB", (gray, gray, gray))
        assert _hatch(gray, seed=1) == _hatch(rgb, seed=1)

    def test_exports_are_available_from_core(self) -> None:
        assert CoreHatchSettings is HatchSettings
        assert core_hatch_strokes is hatch_strokes

    def test_public_api_end_to_end_from_core(self) -> None:
        image = _gradient_image(100, 80)
        strokes = core_hatch_strokes(image, CoreHatchSettings(seed=42), PPM, PEN_WIDTH)
        assert strokes
        assert all(stroke.is_valid and stroke.length > 0.0 for stroke in strokes)
        assert all(
            0.0 <= x <= image.width - 1 and 0.0 <= y <= image.height - 1
            for stroke in strokes
            for x, y in stroke.coords
        )
