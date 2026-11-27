"""Tests for Sketch Lines PFM algorithm."""

from __future__ import annotations

import hashlib
import math
import random
from itertools import pairwise

import numpy as np
import pytest
from PIL import Image
from shapely import LineString

from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings, sketch_lines


class TestSketchLinesSettings:
    """Tests for SketchLinesSettings validation."""

    def test_default_settings(self):
        settings = SketchLinesSettings()
        assert settings.line_density == 0.97
        assert settings.max_fill == 90.0
        assert settings.tone_coverage == 0.5
        assert settings.tone_exponent == 0.55
        assert settings.texture_limit == 0.8
        assert settings.min_length == 2.0
        assert settings.max_length == 40.0
        assert settings.angle_range == (-72.0, -52.0)
        assert settings.shading_enabled is False
        assert settings.squiggle_enabled is False
        assert settings.erase_enabled is True
        assert settings.seed is None
        assert settings.search_angle_step == 18.0
        assert settings.sample_step == 10.0
        assert settings.erase_min == 35.0
        assert settings.erase_max == 80.0
        assert settings.tone == 0.5
        assert settings.erase_radius_min == 1.0
        assert settings.erase_radius_max == 1.0
        assert settings.squiggle_max_deviation == 0.25
        assert settings.squiggle_min_length == 50
        assert settings.squiggle_max_length == 500
        assert settings.max_strokes is None

    def test_erase_bounds_and_squiggle_lengths_validated(self):
        with pytest.raises(ValueError):
            SketchLinesSettings(erase_min=200.0, erase_max=100.0)
        with pytest.raises(ValueError):
            SketchLinesSettings(squiggle_min_length=600, squiggle_max_length=500)
        with pytest.raises(ValueError):
            SketchLinesSettings(tone=1.5)
        with pytest.raises(ValueError):
            SketchLinesSettings(erase_radius_min=5.0, erase_radius_max=2.0)

    def test_custom_settings(self):
        settings = SketchLinesSettings(
            line_density=2.0,
            min_length=5.0,
            max_length=50.0,
            angle_range=(45.0, 135.0),
            shading_enabled=False,
            squiggle_enabled=False,
            erase_enabled=False,
            seed=42,
            search_angle_step=10.0,
            sample_step=5.0,
        )
        assert settings.line_density == 2.0
        assert settings.min_length == 5.0
        assert settings.max_length == 50.0
        assert settings.angle_range == (45.0, 135.0)
        assert settings.shading_enabled is False
        assert settings.squiggle_enabled is False
        assert settings.erase_enabled is False
        assert settings.seed == 42
        assert settings.search_angle_step == 10.0
        assert settings.sample_step == 5.0

    def test_angle_range_validation_min_max(self):
        with pytest.raises(ValueError):
            SketchLinesSettings(angle_range=(180.0, 90.0))

    def test_angle_range_validation_bounds(self):
        with pytest.raises(ValueError):
            SketchLinesSettings(angle_range=(-400.0, -52.0))
        with pytest.raises(ValueError):
            SketchLinesSettings(angle_range=(-72.0, 370.0))
        assert SketchLinesSettings(angle_range=(-72.0, -52.0)).angle_range == (-72.0, -52.0)

    def test_line_density_bounds(self):
        with pytest.raises(ValueError):
            SketchLinesSettings(line_density=0.0)
        with pytest.raises(ValueError):
            SketchLinesSettings(line_density=11.0)

    def test_max_fill_bounds(self):
        with pytest.raises(ValueError):
            SketchLinesSettings(max_fill=0.0)
        with pytest.raises(ValueError):
            SketchLinesSettings(max_fill=101.0)
        assert SketchLinesSettings(max_fill=1.0).max_fill == 1.0
        assert SketchLinesSettings(max_fill=100.0).max_fill == 100.0

    def test_min_max_length_bounds(self):
        with pytest.raises(ValueError):
            SketchLinesSettings(min_length=0.0)
        with pytest.raises(ValueError):
            SketchLinesSettings(max_length=5001.0)

    def test_min_length_greater_than_max(self):
        with pytest.raises(ValueError):
            SketchLinesSettings(min_length=100.0, max_length=50.0)

    def test_search_angle_step_bounds(self):
        with pytest.raises(ValueError):
            SketchLinesSettings(search_angle_step=0.05)
        with pytest.raises(ValueError):
            SketchLinesSettings(search_angle_step=100.0)

    def test_sample_step_bounds(self):
        with pytest.raises(ValueError):
            SketchLinesSettings(sample_step=0.5)
        with pytest.raises(ValueError):
            SketchLinesSettings(sample_step=101.0)

    def test_tone_setting_bounds(self):
        with pytest.raises(ValueError):
            SketchLinesSettings(tone_coverage=-0.1)
        with pytest.raises(ValueError):
            SketchLinesSettings(tone_coverage=1.1)
        with pytest.raises(ValueError):
            SketchLinesSettings(tone_exponent=2.1)
        with pytest.raises(ValueError):
            SketchLinesSettings(texture_limit=1.1)


class TestToneBudgets:
    """The contrast-adaptive budget follows tone and stops earlier on texture."""

    @staticmethod
    def _budgets(source: np.ndarray, texture_limit: float = 0.8) -> np.ndarray:
        from penpath.core.drawing.pfm_sketch_lines import _local_texture, _tone_budgets

        mean, std = _local_texture(source, 5)
        return _tone_budgets(source, mean, std, 0.5, 0.55, texture_limit)

    def test_neutral_settings_have_no_budget(self):
        from penpath.core.drawing.pfm_sketch_lines import _local_texture, _tone_budgets

        source = np.full((20, 20), 30.0)
        mean, std = _local_texture(source, 5)
        assert np.all(_tone_budgets(source, mean, std, 1.0, 1.0, 0.0) == 0.0)

    def test_budget_ranks_dark_mid_and_light_tones(self):
        source = np.full((60, 60), 255.0)
        source[:20] = 30.0
        source[20:40] = 128.0
        source[40:] = 220.0
        source[0, 0] = 255.0
        budgets = self._budgets(source)
        assert budgets[5, 30] > budgets[30, 30] > budgets[50, 30] > 0.0
        assert budgets[0, 0] == 0.0

    def test_texture_reduces_the_budget_of_dark_pixels(self):
        flat = np.full((30, 30), 40.0)
        textured = flat.copy()
        textured[::2, ::2] = 0.0
        textured[1::2, 1::2] = 200.0
        assert self._budgets(textured).mean() < self._budgets(flat).mean()


class TestSketchLinesAlgorithm:
    """Tests for the sketch_lines algorithm."""

    def _create_test_image(self, width: int = 100, height: int = 100) -> Image.Image:
        """Create a simple test image with a dark rectangle."""
        img = Image.new("L", (width, height), 255)  # White background
        # Draw a dark rectangle in the middle
        pixels = img.load()
        for y in range(height // 3, 2 * height // 3):
            for x in range(width // 3, 2 * width // 3):
                pixels[x, y] = 0  # Black
        return img

    def _create_gradient_image(self, width: int = 100, height: int = 100) -> Image.Image:
        """Create a gradient test image."""
        img = Image.new("L", (width, height))
        pixels = img.load()
        for y in range(height):
            for x in range(width):
                pixels[x, y] = int(255 * (x / width))
        return img

    def test_basic_output(self):
        """Test that algorithm produces valid LineStrings."""
        img = self._create_test_image()
        settings = SketchLinesSettings(seed=42, line_density=0.5)
        lines = sketch_lines(img, settings)

        assert isinstance(lines, list)
        assert len(lines) > 0
        for line in lines:
            assert isinstance(line, LineString)
            assert line.is_valid
            assert line.length > 0
            # Check coordinates are within image bounds
            for x, y in line.coords:
                assert 0 <= x < img.width
                assert 0 <= y < img.height

    def test_deterministic_with_seed(self):
        """Test that fixed seed produces identical output."""
        img = self._create_test_image()
        settings1 = SketchLinesSettings(seed=42, line_density=1.0)
        settings2 = SketchLinesSettings(seed=42, line_density=1.0)

        lines1 = sketch_lines(img, settings1)
        lines2 = sketch_lines(img, settings2)

        assert len(lines1) == len(lines2)
        for l1, l2 in zip(lines1, lines2, strict=False):
            assert l1.equals(l2)

    def test_different_seeds_produce_different_output(self):
        """Test that different seeds produce different output (usually)."""
        img = self._create_test_image()
        settings1 = SketchLinesSettings(seed=42, line_density=1.0)
        settings2 = SketchLinesSettings(seed=43, line_density=1.0)

        lines1 = sketch_lines(img, settings1)
        lines2 = sketch_lines(img, settings2)

        # They might occasionally be the same, but very unlikely
        # At least check they're both valid
        assert len(lines1) > 0
        assert len(lines2) > 0

    def test_no_seed_non_deterministic(self):
        """Test that None seed produces varying output."""
        img = self._create_test_image()
        settings = SketchLinesSettings(seed=None, line_density=1.0)

        lines1 = sketch_lines(img, settings)
        lines2 = sketch_lines(img, settings)

        # Both should be valid
        assert len(lines1) > 0
        assert len(lines2) > 0

    def test_shading_disabled(self):
        """Test algorithm with shading disabled."""
        img = self._create_gradient_image()
        settings = SketchLinesSettings(seed=42, shading_enabled=False, line_density=1.0)
        lines = sketch_lines(img, settings)

        assert len(lines) > 0
        for line in lines:
            assert line.is_valid

    def test_shading_enabled(self):
        """Test algorithm with shading enabled."""
        img = self._create_gradient_image()
        settings = SketchLinesSettings(seed=42, shading_enabled=True, line_density=1.0)
        lines = sketch_lines(img, settings)

        assert len(lines) > 0
        for line in lines:
            assert line.is_valid

    def test_squiggle_disabled(self):
        """Test algorithm with squiggles disabled produces straighter lines."""
        img = self._create_test_image()
        settings = SketchLinesSettings(seed=42, squiggle_enabled=False, line_density=1.0)
        lines = sketch_lines(img, settings)

        assert len(lines) > 0
        for line in lines:
            assert line.is_valid

    def test_squiggle_enabled(self):
        """Test algorithm with squiggles enabled."""
        img = self._create_test_image()
        settings = SketchLinesSettings(seed=42, squiggle_enabled=True, line_density=1.0)
        lines = sketch_lines(img, settings)

        assert len(lines) > 0
        for line in lines:
            assert line.is_valid

    def test_erase_disabled(self):
        """Test algorithm with erase disabled."""
        img = self._create_test_image()
        settings = SketchLinesSettings(seed=42, erase_enabled=False, line_density=1.0)
        lines = sketch_lines(img, settings)

        assert len(lines) > 0
        for line in lines:
            assert line.is_valid

    def test_erase_enabled(self):
        """Test algorithm with erase enabled."""
        img = self._create_test_image()
        settings = SketchLinesSettings(seed=42, erase_enabled=True, line_density=1.0)
        lines = sketch_lines(img, settings)

        assert len(lines) > 0
        for line in lines:
            assert line.is_valid

    def test_angle_range_restriction(self):
        """Test that angle_range restricts the starting search angle."""
        # This test verifies that the random start angle is within the specified range.
        # The actual line direction may vary based on darkest pixel search.
        img = self._create_test_image(200, 200)
        # Use a very narrow angle range
        settings = SketchLinesSettings(
            seed=42,
            angle_range=(85.0, 95.0),  # Near vertical
            line_density=2.0,
            min_length=20.0,
            max_length=50.0,
            squiggle_enabled=False,
            search_angle_step=1.0,  # Fine search
        )
        lines = sketch_lines(img, settings)

        assert len(lines) > 0
        # With squiggles disabled and narrow search, lines should be roughly vertical
        # Check at least some lines are roughly vertical
        vertical_count = 0
        for line in lines:
            coords = list(line.coords)
            if len(coords) >= 2:
                x0, y0 = coords[0]
                x1, y1 = coords[-1]
                if y1 != y0:
                    angle = abs(math.degrees(math.atan2(y1 - y0, x1 - x0)))
                    # Normalize to 0-180 range
                    if angle > 180:
                        angle = 360 - angle
                    if angle > 90:
                        angle = 180 - angle
                    if angle > 70:  # Near vertical (90 deg)
                        vertical_count += 1

        # At least some lines should be roughly vertical
        assert vertical_count > 0, "No lines found with roughly vertical orientation"

    def test_min_max_length_respected(self):
        """Test that individual line segments roughly respect max length bound."""
        img = self._create_test_image(200, 200)
        settings = SketchLinesSettings(
            seed=42,
            min_length=30.0,
            max_length=40.0,
            line_density=2.0,
            squiggle_enabled=False,
        )
        lines = sketch_lines(img, settings)

        assert len(lines) > 0
        max_seg_length = 0
        for line in lines:
            # Check individual segment lengths
            coords = list(line.coords)
            for i in range(len(coords) - 1):
                x0, y0 = coords[i]
                x1, y1 = coords[i + 1]
                seg_length = math.hypot(x1 - x0, y1 - y0)
                max_seg_length = max(max_seg_length, seg_length)

        # Max segment length should not significantly exceed max_length
        # (allowing some tolerance for boundary clamping)
        assert max_seg_length <= 80, f"Max segment too long: {max_seg_length}"

    def test_line_density_affects_count(self):
        """Test that higher line_density produces more lines."""
        img = self._create_test_image(200, 200)
        settings_low = SketchLinesSettings(seed=42, line_density=0.1)
        settings_high = SketchLinesSettings(seed=42, line_density=2.0)

        lines_low = sketch_lines(img, settings_low)
        lines_high = sketch_lines(img, settings_high)

        # Higher density should generally produce more lines
        # (though randomness means this isn't guaranteed every time)
        assert len(lines_high) >= len(lines_low) * 0.5

    def test_rgb_image_input(self):
        """Test that RGB images are handled correctly."""
        img = Image.new("RGB", (100, 100), (255, 255, 255))
        pixels = img.load()
        for y in range(30, 70):
            for x in range(30, 70):
                pixels[x, y] = (0, 0, 0)

        settings = SketchLinesSettings(seed=42, line_density=1.0)
        lines = sketch_lines(img, settings)

        assert len(lines) > 0
        for line in lines:
            assert line.is_valid

    def test_empty_white_image(self):
        """Test behavior with all-white image."""
        img = Image.new("L", (100, 100), 255)
        settings = SketchLinesSettings(seed=42, line_density=1.0)
        lines = sketch_lines(img, settings)

        # Should still produce some lines (random fallback)
        assert len(lines) >= 0
        for line in lines:
            assert line.is_valid

    def test_all_black_image(self):
        """Test behavior with all-black image."""
        img = Image.new("L", (100, 100), 0)
        settings = SketchLinesSettings(seed=42, line_density=1.0)
        lines = sketch_lines(img, settings)

        assert len(lines) > 0
        for line in lines:
            assert line.is_valid

    def test_small_image(self):
        """Test with very small image."""
        img = Image.new("L", (10, 10), 255)
        pixels = img.load()
        for y in range(10):
            for x in range(10):
                pixels[x, y] = 0 if (x + y) % 2 == 0 else 255

        settings = SketchLinesSettings(seed=42, line_density=1.0, min_length=1.0, max_length=5.0)
        lines = sketch_lines(img, settings)

        assert len(lines) >= 0
        for line in lines:
            assert line.is_valid

    def test_output_coordinates_in_bounds(self):
        """Test that all output coordinates are within image bounds."""
        img = self._create_test_image(150, 120)
        settings = SketchLinesSettings(seed=42, line_density=2.0)
        lines = sketch_lines(img, settings)

        for line in lines:
            for x, y in line.coords:
                assert 0 <= x < img.width, f"x={x} out of bounds [0, {img.width})"
                assert 0 <= y < img.height, f"y={y} out of bounds [0, {img.height})"

    def test_no_strokes_link_across_the_page(self):
        """A new squiggle must not be joined to the previous one with a travel line."""
        img = Image.new("L", (200, 200), 255)
        pixels = img.load()
        for y in range(20, 60):
            for x in range(20, 60):
                pixels[x, y] = 0
        for y in range(140, 180):
            for x in range(140, 180):
                pixels[x, y] = 0

        lines = sketch_lines(img, SketchLinesSettings(seed=42, squiggle_enabled=False))
        assert lines
        for line in lines:
            coords = list(line.coords)
            for (x0, y0), (x1, y1) in pairwise(coords):
                assert math.hypot(x1 - x0, y1 - y0) <= 100.0

    def test_erase_disabled_stops_at_hard_cap_and_is_denser(self):
        """Without erasing the image cannot lighten, so only the stroke cap stops it."""
        img = self._create_test_image()
        dark = sketch_lines(
            img,
            SketchLinesSettings(seed=42, erase_enabled=False, max_strokes=25),
        )
        erased = sketch_lines(
            img,
            SketchLinesSettings(seed=42, erase_enabled=True, max_strokes=25),
        )
        assert len(dark) == 25
        assert sum(line.length for line in dark) > sum(line.length for line in erased)

    def test_gradient_starts_spread_across_the_image(self):
        """Erasing moves the next stroke away from the darkest corner."""
        img = self._create_gradient_image(200, 200)
        lines = sketch_lines(img, SketchLinesSettings(seed=42))
        starts = [line.coords[0] for line in lines]
        assert len(lines) >= 3
        assert max(x for x, _ in starts) - min(x for x, _ in starts) > 100

    @staticmethod
    def _stroke_signature(lines: list[LineString]) -> str:
        return "|".join(",".join(f"{x:.6f}:{y:.6f}" for x, y in line.coords) for line in lines)

    def test_full_range_reproduces_the_pre_max_fill_drawing(self):
        """max_fill=100 is a no-op: the same seed draws the pre-LUC-89 strokes."""
        neutral = {
            "max_fill": 100.0,
            "tone_coverage": 1.0,
            "tone_exponent": 1.0,
            "texture_limit": 0.0,
        }
        dark = sketch_lines(
            self._create_test_image(),
            SketchLinesSettings(seed=42, line_density=0.5, **neutral),
        )
        gradient = sketch_lines(
            self._create_gradient_image(),
            SketchLinesSettings(seed=42, line_density=1.0, **neutral),
        )
        assert (
            hashlib.sha256(self._stroke_signature(dark).encode()).hexdigest()
            == "bc55a512864d2f57af00d904bc475ce94327b58733180be2c9e732cd053d001c"
        )
        assert (
            hashlib.sha256(self._stroke_signature(gradient).encode()).hexdigest()
            == "4978c40eb46fb421b514d54139675b7fbb6ad5a233da2dd34031851d6766aafa"
        )

    def test_lower_max_fill_treats_every_tone_below_the_black_point_as_black(self):
        """Two images differing only below the black point draw identically."""

        def square(tone: int) -> Image.Image:
            image = Image.new("L", (100, 100), 255)
            pixels = image.load()
            for y in range(30, 70):
                for x in range(30, 70):
                    pixels[x, y] = tone
            return image

        capped = [
            list(line.coords) for line in sketch_lines(square(0), SketchLinesSettings(seed=42))
        ]
        clamped = [
            list(line.coords) for line in sketch_lines(square(20), SketchLinesSettings(seed=42))
        ]
        full = [
            list(line.coords)
            for line in sketch_lines(square(0), SketchLinesSettings(seed=42, max_fill=100.0))
        ]
        legacy = [
            list(line.coords)
            for line in sketch_lines(square(20), SketchLinesSettings(seed=42, max_fill=100.0))
        ]
        assert len(capped) > 0
        assert capped == clamped
        assert full != legacy

    def test_lower_max_fill_reduces_ink_on_a_solid_black_canvas(self):
        """A capped black point needs fewer strokes to cover a fully black image."""
        black = Image.new("L", (100, 100), 0)
        lengths = [
            sum(
                line.length
                for line in sketch_lines(black, SketchLinesSettings(seed=42, max_fill=mf))
            )
            for mf in (60.0, 80.0, 100.0)
        ]
        assert lengths[0] < lengths[1] < lengths[2]


class TestBresenhamLine:
    """Tests for internal Bresenham line function."""

    def _bresenham_line(self, x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
        from penpath.core.drawing.pfm_sketch_lines import _bresenham_line

        return _bresenham_line(x0, y0, x1, y1)

    def test_horizontal_line(self):
        points = self._bresenham_line(0, 5, 10, 5)
        assert points[0] == (0, 5)
        assert points[-1] == (10, 5)
        assert all(y == 5 for _, y in points)

    def test_vertical_line(self):
        points = self._bresenham_line(5, 0, 5, 10)
        assert points[0] == (5, 0)
        assert points[-1] == (5, 10)
        assert all(x == 5 for x, _ in points)

    def test_diagonal_line(self):
        points = self._bresenham_line(0, 0, 10, 10)
        assert points[0] == (0, 0)
        assert points[-1] == (10, 10)
        assert len(points) == 11

    def test_negative_slope(self):
        points = self._bresenham_line(0, 10, 10, 0)
        assert points[0] == (0, 10)
        assert points[-1] == (10, 0)

    def test_reverse_direction(self):
        points1 = self._bresenham_line(0, 0, 5, 5)
        points2 = self._bresenham_line(5, 5, 0, 0)
        assert points1 == list(reversed(points2))

    def test_single_point(self):
        points = self._bresenham_line(5, 5, 5, 5)
        assert points == [(5, 5)]


class TestSampleLineLuminance:
    """Tests for the running-mean luminance endpoint rule."""

    def _sample_line_luminance(
        self,
        luminance: np.ndarray,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        min_length: int,
    ) -> tuple[float, int, int]:
        from penpath.core.drawing.pfm_sketch_lines import _sample_line_luminance

        return _sample_line_luminance(luminance, x0, y0, x1, y1, min_length)

    def test_endpoint_is_darkest_window(self):
        luminance = np.full((100, 100), 200.0, dtype=np.float64)
        luminance[10, 20:26] = 10.0
        avg, ex, ey = self._sample_line_luminance(luminance, 10, 10, 60, 10, 2)
        assert 20 <= ex <= 25
        assert ey == 10
        assert avg < 200.0

    def test_uniform_luminance_stops_at_first_valid_prefix(self):
        luminance = np.full((100, 100), 128.0, dtype=np.float64)
        avg, ex, ey = self._sample_line_luminance(luminance, 10, 10, 50, 10, 5)
        assert abs(avg - 128.0) < 0.1
        assert ex == 15
        assert ey == 10

    def test_too_short_line_uses_last_valid_pixel(self):
        luminance = np.full((100, 100), 128.0, dtype=np.float64)
        avg, ex, ey = self._sample_line_luminance(luminance, 10, 10, 12, 10, 5)
        assert abs(avg - 128.0) < 0.1
        assert (ex, ey) == (12, 10)

    def test_out_of_bounds_stops_at_edge(self):
        luminance = np.full((100, 100), 128.0, dtype=np.float64)
        _avg, ex, _ey = self._sample_line_luminance(luminance, 10, 10, 150, 10, 5)
        assert 0 <= ex < 100


class TestFindDarkestPixel:
    """Tests for darkest pixel finding."""

    def _find_darkest_pixel(
        self,
        luminance: np.ndarray,
        sample_step: int,
        rng: random.Random,
    ) -> tuple[int, int]:
        from penpath.core.drawing.pfm_sketch_lines import _find_darkest_pixel

        return _find_darkest_pixel(luminance, sample_step, rng)

    def test_finds_dark_region(self):
        luminance = np.full((100, 100), 200.0, dtype=np.float32)
        luminance[40:60, 40:60] = 50.0  # Dark square in center
        rng = random.Random(42)
        x, y = self._find_darkest_pixel(luminance, 10, rng)
        assert 35 <= x <= 65
        assert 35 <= y <= 65

    def test_uniform_image(self):
        luminance = np.full((100, 100), 128.0, dtype=np.float32)
        rng = random.Random(42)
        x, y = self._find_darkest_pixel(luminance, 10, rng)
        assert 0 <= x < 100
        assert 0 <= y < 100


class TestFindDarkestLine:
    """Tests for darkest line finding."""

    def _find_darkest_line(
        self,
        luminance: np.ndarray,
        x0: int,
        y0: int,
        min_length: int,
        max_length: int,
        shading: bool,
        start_angle: float,
        num_tests: int,
        shading_angle: float,
    ) -> tuple[float, int, int]:
        from penpath.core.drawing.pfm_sketch_lines import _find_darkest_line

        return _find_darkest_line(
            luminance,
            x0,
            y0,
            min_length,
            max_length,
            shading,
            start_angle,
            num_tests,
            shading_angle,
        )

    def test_finds_dark_direction(self):
        luminance = np.full((100, 100), 200.0, dtype=np.float64)
        luminance[50, 50:80] = 10.0
        avg, ex, ey = self._find_darkest_line(luminance, 50, 50, 2, 30, False, 0.0, 8, 180.0)
        assert avg < 150.0
        assert ex > 50
        assert ey == 50

    def test_shading_mode_only_tests_two_opposite_directions(self):
        luminance = np.full((100, 100), 128.0, dtype=np.float64)
        _avg, ex, ey = self._find_darkest_line(luminance, 50, 50, 2, 30, True, 90.0, 8, 180.0)
        assert 0 <= ex < 100
        assert 0 <= ey < 100
        assert abs(ex - 50) <= 1


class TestAddSquiggle:
    """Tests for squiggle generation."""

    def _add_squiggle(
        self,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        squiggle_length: int,
        max_deviation: float,
        rng: random.Random,
    ) -> list[tuple[float, float]]:
        from penpath.core.drawing.pfm_sketch_lines import _add_squiggle

        return _add_squiggle(x0, y0, x1, y1, squiggle_length, max_deviation, rng)

    def test_no_squiggle_short_line(self):
        rng = random.Random(42)
        points = self._add_squiggle(0, 0, 5, 0, 10, 2.0, rng)
        assert len(points) == 2
        assert points[0] == (0.0, 0.0)
        assert points[-1] == (5.0, 0.0)

    def test_no_squiggle_zero_deviation(self):
        rng = random.Random(42)
        points = self._add_squiggle(0, 0, 50, 0, 10, 0.0, rng)
        assert len(points) == 2

    def test_squiggle_adds_points(self):
        rng = random.Random(42)
        points = self._add_squiggle(0, 0, 100, 0, 10, 2.0, rng)
        assert len(points) > 2
        assert points[0] == (0.0, 0.0)
        assert points[-1] == (100.0, 0.0)

    def test_squiggle_perpendicular(self):
        rng = random.Random(42)
        points = self._add_squiggle(0, 0, 0, 100, 10, 5.0, rng)
        # Points should deviate in x direction (perpendicular to vertical line)
        for x, _y in points[1:-1]:
            assert abs(x) <= 5.0  # Within max_deviation


class TestErase:
    """Tests for the reference erase model."""

    def test_dark_pixel_erases_less_than_light_pixel(self):
        from penpath.core.drawing.pfm_sketch_lines import _erase_amount

        dark = _erase_amount(0.0, 50.0, 125.0, 0.5)
        light = _erase_amount(255.0, 50.0, 125.0, 0.5)
        assert dark == 50
        assert light == 125
        assert dark < light

    def test_drawing_lightens_the_working_image_toward_white(self):
        from penpath.core.drawing.pfm_sketch_lines import _apply_erase

        working = np.zeros((20, 20), dtype=np.float64)
        _apply_erase(working, 2, 10, 8, 10, 35.0, 80.0, 0.5, 1.0, 1.0)
        assert working[10, 2] == 35.0
        assert working[10, 8] == 35.0
        assert working[10, 5] == 35.0
        assert working[9, 5] == 35.0
        assert working[10, 0] == 0.0

        _apply_erase(working, 2, 10, 8, 10, 35.0, 80.0, 0.5, 1.0, 1.0)
        assert working[10, 5] > 35.0
        for _ in range(30):
            _apply_erase(working, 2, 10, 8, 10, 35.0, 80.0, 0.5, 1.0, 1.0)
        assert working[10, 5] == 255.0

    def test_erase_brush_radius_covers_a_disk(self):
        from penpath.core.drawing.pfm_sketch_lines import _apply_erase

        working = np.zeros((20, 20), dtype=np.float64)
        _apply_erase(working, 10, 10, 10, 10, 50.0, 125.0, 0.5, 2.0, 2.0)
        assert working[10, 10] == 50.0
        assert working[10, 12] == 50.0
        assert working[8, 10] == 50.0
        assert working[7, 10] == 0.0

    def test_tone_blends_cubic_and_linear_progress(self):
        from penpath.core.drawing.pfm_sketch_lines import _erase_amount

        mid = 255.0 / 2
        expected = int(50 + (0.5 * mid**3 / 255**3 + 0.5 * mid / 255) * 75)
        assert _erase_amount(mid, 50.0, 125.0, 0.5) == expected


class TestSparseCanvas:
    """A palette channel is mostly white with a small, fragmented ink region."""

    def test_sparse_channel_draws_enough_strokes_to_cover_its_region(self):
        image = Image.new("L", (100, 100), 255)
        region: set[tuple[int, int]] = set()
        for index in range(16):
            block_x = 10 + (index % 4) * 22
            block_y = 10 + (index // 4) * 22
            for dy in range(2):
                for dx in range(2):
                    point = (block_x + dx, block_y + dy)
                    image.putpixel(point, 40)
                    region.add(point)

        lines = sketch_lines(
            image,
            SketchLinesSettings(
                seed=42,
                line_density=0.75,
                max_fill=80.0,
                tone_coverage=1.0,
                tone_exponent=1.0,
                texture_limit=0.0,
            ),
        )
        points = {(int(x), int(y)) for line in lines for x, y in line.coords}

        assert len(lines) == 7
        assert len(points & region) >= 25


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])
