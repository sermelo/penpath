"""Tests for the weighted Poisson-disk Stipple PFM."""

from __future__ import annotations

import math

import pytest
from PIL import Image
from pydantic import ValidationError
from shapely import LineString

from penpath.core.drawing import StippleSettings, stipple
from penpath.core.drawing.pfm_stipple import _dot_radius, _exclusion_radius
from penpath.core.drawing.registry import get_pfm, list_pfms
from penpath.presets.pfms import (
    get_pfm_for_preset,
    get_pfm_preset_settings,
    list_presets_for_pfm,
)


def _dark_square(width: int = 100, height: int = 100, tone: int = 0) -> Image.Image:
    image = Image.new("L", (width, height), 255)
    for y in range(height // 4, 3 * height // 4):
        for x in range(width // 4, 3 * width // 4):
            image.putpixel((x, y), tone)
    return image


DASH_SEED42_COORDS: tuple[tuple[float, float], ...] = (
    ((19.62857851731117, 24.76796107711976), (25.570130731901088, 25.60339945384281)),
    ((0.15229728469020998, 3.9437103608720463), (5.84770271530979, 2.0562896391279537)),
    ((1.6215382292937415, 7.9576066333519915), (4.3784617707062585, 13.286712804822537)),
    ((33.29239754076448, 6.870913899954462), (38.70760245923552, 9.454623576169492)),
    ((16.234647631743485, 26.169528383772374), (19.959644287295603, 30.87318652570037)),
    ((0.06152756722258079, 26.021457375228984), (5.938472432777419, 27.230390395387104)),
    ((24.7511311947028, 37.65194815783521), (28.38608911094591, 32.87836659394196)),
    ((16.140662376874573, 4.908489335977755), (21.29124032696278, 1.8309015175613346)),
)


class TestStippleSettings:
    def test_defaults(self) -> None:
        settings = StippleSettings()
        assert settings.dot_density == 1.0
        assert settings.min_radius == 1.0
        assert settings.max_radius == 3.0
        assert settings.jitter == 1.0
        assert settings.dot_shape == "dash"
        assert settings.seed is None
        assert settings.max_strokes == 10000

    def test_min_radius_must_not_exceed_max_radius(self) -> None:
        with pytest.raises(ValueError, match="min_radius must be <= max_radius"):
            StippleSettings(min_radius=4.0, max_radius=2.0)

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"dot_density": 0.0},
            {"dot_density": 11.0},
            {"min_radius": 0.0},
            {"max_radius": 101.0},
            {"jitter": -0.1},
            {"jitter": 1.1},
            {"max_strokes": 0},
        ],
    )
    def test_out_of_range_values_rejected(self, kwargs: dict[str, object]) -> None:
        with pytest.raises(ValueError):
            StippleSettings.model_validate(kwargs)

    @pytest.mark.parametrize("shape", ["dash", "circle", "tap"])
    def test_dot_shape_accepts_the_three_values(self, shape: str) -> None:
        assert StippleSettings.model_validate({"dot_shape": shape}).dot_shape == shape

    def test_unknown_dot_shape_is_rejected_naming_the_setting(self) -> None:
        with pytest.raises(ValidationError) as info:
            StippleSettings.model_validate({"dot_shape": "square"})
        assert "dot_shape" in str(info.value)

    def test_equal_radii_are_allowed(self) -> None:
        assert StippleSettings(min_radius=2.0, max_radius=2.0).max_radius == 2.0


class TestStippleAlgorithm:
    def test_deterministic_with_seed(self) -> None:
        image = _dark_square()
        first = stipple(image, StippleSettings(seed=42))
        second = stipple(image, StippleSettings(seed=42))
        assert first == second
        assert [list(line.coords) for line in first] == [list(line.coords) for line in second]

    def test_different_seeds_change_the_output(self) -> None:
        image = _dark_square()
        first = stipple(image, StippleSettings(seed=42))
        second = stipple(image, StippleSettings(seed=43))
        assert [list(line.coords) for line in first] != [list(line.coords) for line in second]

    def test_no_seed_is_not_deterministic(self) -> None:
        image = _dark_square()
        settings = StippleSettings()
        assert [list(line.coords) for line in stipple(image, settings)] != [
            list(line.coords) for line in stipple(image, settings)
        ]

    def test_points_stay_inside_the_image(self) -> None:
        image = _dark_square(120, 90)
        lines = stipple(image, StippleSettings(seed=42))
        assert lines
        for line in lines:
            for x, y in line.coords:
                assert 0.0 <= x <= image.width - 1
                assert 0.0 <= y <= image.height - 1

    def test_no_zero_length_strokes(self) -> None:
        lines = stipple(_dark_square(), StippleSettings(seed=42))
        assert lines
        for line in lines:
            assert isinstance(line, LineString)
            assert line.is_valid
            assert line.length > 0.0

    def test_radius_bounds_are_respected(self) -> None:
        settings = StippleSettings(seed=42, min_radius=1.0, max_radius=3.0)
        lines = stipple(_dark_square(150, 150), settings)
        assert lines
        for line in lines:
            radius = line.length / 2.0
            assert settings.min_radius - 1e-9 <= radius <= settings.max_radius + 1e-9

    def test_dark_image_gets_more_and_bigger_dots_than_light_image(self) -> None:
        dark = stipple(Image.new("L", (100, 100), 20), StippleSettings(seed=42))
        light = stipple(Image.new("L", (100, 100), 240), StippleSettings(seed=42))
        assert dark and light
        assert len(dark) > len(light)
        assert sum(line.length for line in dark) / len(dark) > sum(
            line.length for line in light
        ) / len(light)

    def test_max_strokes_caps_the_dot_count(self) -> None:
        lines = stipple(Image.new("L", (100, 100), 0), StippleSettings(seed=42, max_strokes=25))
        assert len(lines) == 25

    def test_dot_density_changes_the_dot_count(self) -> None:
        image = _dark_square(150, 150)
        sparse = stipple(image, StippleSettings(seed=42, dot_density=0.5))
        dense = stipple(image, StippleSettings(seed=42, dot_density=2.0))
        assert len(dense) > len(sparse)

    def test_blank_image_returns_no_strokes(self) -> None:
        assert stipple(Image.new("L", (100, 100), 255), StippleSettings(seed=42)) == []

    def test_empty_image_returns_no_strokes(self) -> None:
        assert stipple(Image.new("L", (0, 10)), StippleSettings(seed=42)) == []

    def test_works_on_an_l_image_and_matches_an_rgb_twin(self) -> None:
        gray = _dark_square()
        rgb = Image.merge("RGB", (gray, gray, gray))
        lines = stipple(gray, StippleSettings(seed=42))
        assert lines
        assert lines == stipple(rgb, StippleSettings(seed=42))

    def test_zero_jitter_draws_horizontal_dots(self) -> None:
        lines = stipple(_dark_square(), StippleSettings(seed=42, jitter=0.0))
        assert lines
        for line in lines:
            (x0, y0), (x1, y1) = line.coords
            assert y0 == y1
            assert x1 > x0

    def test_local_exclusion_shrinks_as_darkness_grows(self) -> None:
        settings = StippleSettings()
        assert _exclusion_radius(0.0, settings.max_radius) > _exclusion_radius(
            1.0, settings.max_radius
        )
        assert _dot_radius(0.0, settings.min_radius, settings.max_radius) == settings.min_radius
        assert _dot_radius(1.0, settings.min_radius, settings.max_radius) == settings.max_radius

    def test_dash_output_is_byte_identical_to_the_shipped_default(self) -> None:
        lines = stipple(Image.new("L", (40, 40), 0), StippleSettings(seed=42, max_strokes=8))

        assert [tuple(line.coords) for line in lines] == list(DASH_SEED42_COORDS)

    def test_circle_is_a_closed_ring_inside_the_image(self) -> None:
        settings = StippleSettings(seed=42, dot_shape="circle", max_strokes=12)
        lines = stipple(_dark_square(120, 90), settings)
        assert lines
        for line in lines:
            coords = list(line.coords)
            assert line.is_valid and line.is_ring
            assert len(coords) == 13
            assert coords[0] == coords[-1]
            assert len(set(coords)) >= 9
            center_x = sum(x for x, _ in coords[:-1]) / 12.0
            center_y = sum(y for _, y in coords[:-1]) / 12.0
            for x, y in coords[:-1]:
                radius = math.hypot(x - center_x, y - center_y)
                assert settings.min_radius - 1e-9 <= radius <= settings.max_radius + 1e-9
            for x, y in coords:
                assert 0.0 <= x <= 119.0
                assert 0.0 <= y <= 89.0

    def test_tap_is_one_zero_length_stroke(self) -> None:
        lines = stipple(_dark_square(), StippleSettings(seed=42, dot_shape="tap", max_strokes=10))

        assert len(lines) == 10
        for line in lines:
            assert len(list(line.coords)) == 2
            assert line.coords[0] == line.coords[1]
            assert line.length == 0.0

    @pytest.mark.parametrize("shape", ["dash", "circle", "tap"])
    def test_every_shape_is_deterministic_for_a_seed(self, shape: str) -> None:
        settings = StippleSettings(seed=42, dot_shape=shape, max_strokes=10)
        image = _dark_square()

        first = stipple(image, settings)
        assert first
        assert first == stipple(image, settings)

    @pytest.mark.parametrize("shape", ["circle", "tap"])
    def test_jitter_is_a_no_op_for_circle_and_tap(self, shape: str) -> None:
        image = _dark_square()
        no_jitter = stipple(image, StippleSettings(seed=42, dot_shape=shape, jitter=0.0))
        full_jitter = stipple(image, StippleSettings(seed=42, dot_shape=shape, jitter=1.0))

        assert no_jitter == full_jitter


class TestStippleRegistryAndPresets:
    def test_stipple_is_registered_with_its_settings_model(self) -> None:
        assert "stipple" in list_pfms()
        function, model = get_pfm("stipple")
        assert function is stipple
        assert model is StippleSettings
        assert model().max_strokes == 10000

    def test_presets_are_namespaced_and_owned_by_stipple(self) -> None:
        for name in ("stipple_default", "stipple_fine", "stipple_bold"):
            assert get_pfm_for_preset(name) == "stipple"
            assert isinstance(get_pfm_preset_settings(name), StippleSettings)
            assert name in list_presets_for_pfm("stipple")

    def test_preset_radii_are_ordered_fine_default_bold(self) -> None:
        fine = get_pfm_preset_settings("stipple_fine")
        default = get_pfm_preset_settings("stipple_default")
        bold = get_pfm_preset_settings("stipple_bold")
        assert isinstance(fine, StippleSettings)
        assert isinstance(default, StippleSettings)
        assert isinstance(bold, StippleSettings)
        assert fine.max_radius < default.max_radius < bold.max_radius
        assert all(
            StippleSettings.model_validate(settings.model_dump()) == settings
            for settings in (fine, default, bold)
        )

    def test_exports_are_available_from_core(self) -> None:
        from penpath.core import StippleSettings as CoreStippleSettings
        from penpath.core import stipple as core_stipple

        assert CoreStippleSettings is StippleSettings
        assert core_stipple is stipple
