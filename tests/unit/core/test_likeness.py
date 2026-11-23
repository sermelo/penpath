"""Unit tests for likeness scoring."""

from __future__ import annotations

import inspect

import numpy as np
import pytest
from PIL import Image, ImageDraw

from penpath.core.likeness import compute_likeness, prepare_for_comparison
from penpath.core.simulation import simulate_plot

PX_PER_MM = 96 / 25.4


def rect_from_px(
    x_px: float, y_px: float, w_px: float, h_px: float
) -> tuple[float, float, float, float]:
    return (x_px / PX_PER_MM, y_px / PX_PER_MM, w_px / PX_PER_MM, h_px / PX_PER_MM)


def test_public_api_exports():
    """Test that likeness functions are available via the public penpath.core API."""
    from penpath.core import compute_likeness as public_compute_likeness
    from penpath.core import prepare_for_comparison as public_prepare_for_comparison

    assert public_compute_likeness is compute_likeness
    assert public_prepare_for_comparison is prepare_for_comparison


class TestPrepareForComparison:
    """Tests for prepare_for_comparison function."""

    def test_grayscale_conversion(self):
        """Test that RGB image is converted to grayscale."""
        rgb_img = Image.new("RGB", (100, 100), color="red")
        result = prepare_for_comparison(rgb_img, (32, 32), 0.0)

        assert result.shape == (32, 32)
        assert result.dtype == np.float32
        assert 0.0 <= result.min() <= result.max() <= 1.0

    def test_grayscale_input_unchanged_mode(self):
        """Test that already grayscale image works."""
        gray_img = Image.new("L", (100, 100), color=128)
        result = prepare_for_comparison(gray_img, (32, 32), 0.0)

        assert result.shape == (32, 32)

    def test_resize_to_target_size(self):
        """Test that image is resized to target size."""
        img = Image.new("L", (200, 100), color=200)
        result = prepare_for_comparison(img, (64, 32), 0.0)

        assert result.shape == (32, 64)

    def test_blur_sigma_zero_no_blur(self):
        """Test that blur_sigma=0 applies no blur."""
        img = Image.new("L", (100, 100), color=255)
        # Add a sharp edge
        arr = np.array(img)
        arr[:, 50:] = 0
        sharp_img = Image.fromarray(arr)

        result = prepare_for_comparison(sharp_img, (32, 32), 0.0)

        # With no blur, the edge should still be relatively sharp
        # (though downscaling will soften it somewhat)
        assert result.shape == (32, 32)

    def test_blur_sigma_positive_applies_blur(self):
        """Test that positive blur_sigma applies Gaussian blur."""
        img = Image.new("L", (100, 100), color=255)
        arr = np.array(img)
        arr[:, 50:] = 0
        sharp_img = Image.fromarray(arr)

        result_no_blur = prepare_for_comparison(sharp_img, (32, 32), 0.0)
        result_blur = prepare_for_comparison(sharp_img, (32, 32), 1.0)

        # Blurred version should have less extreme values (more gradual transition)
        assert result_blur.std() < result_no_blur.std()

    def test_output_range_0_to_1(self):
        """Test that output values are normalized to [0, 1]."""
        img = Image.new("L", (100, 100), color=255)
        result = prepare_for_comparison(img, (32, 32), 0.0)

        assert result.min() >= 0.0
        assert result.max() <= 1.0
        assert np.isclose(result.max(), 1.0)

    def test_different_modes(self):
        """Test with different input image modes."""
        for mode in ["RGB", "RGBA", "L", "LA"]:
            if mode == "LA":
                img = Image.new("LA", (100, 100), color=(128, 255))
            elif mode == "RGBA":
                img = Image.new("RGBA", (100, 100), color=(255, 0, 0, 255))
            else:
                img = Image.new(mode, (100, 100), color="red" if mode != "L" else 128)

            result = prepare_for_comparison(img, (32, 32), 0.0)
            assert result.shape == (32, 32)


class TestComputeLikeness:
    """Tests for compute_likeness function."""

    def create_square_image(self, size: int = 200, color: int = 255) -> Image.Image:
        """Create a white square on black background."""
        img = Image.new("L", (size, size), color=0)
        # Draw a square in the middle
        from PIL import ImageDraw

        draw = ImageDraw.Draw(img)
        margin = size // 4
        draw.rectangle([margin, margin, size - margin, size - margin], fill=color)
        return img

    def create_hatched_square_image(self, size: int = 200) -> Image.Image:
        """Create a hatched square (simulating pen plot)."""
        img = Image.new("L", (size, size), color=0)
        from PIL import ImageDraw

        draw = ImageDraw.Draw(img)
        margin = size // 4
        square_size = size // 2

        # Draw horizontal hatch lines
        for y in range(margin, margin + square_size, 4):
            draw.line([margin, y, margin + square_size, y], fill=255, width=1)

        return img

    def create_bar_image(self, size: int = 200) -> Image.Image:
        """Create a horizontal bar, clearly distinct from a square."""
        img = Image.new("L", (size, size), color=0)
        from PIL import ImageDraw

        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, size, size // 5], fill=255)
        return img

    def test_identical_images_score_high(self):
        """Test that identical images score close to 1.0."""
        img = self.create_square_image()
        placement_rect = rect_from_px(0, 0, 200, 200)

        score = compute_likeness(img, img, placement_rect)

        assert score > 0.95

    def test_matching_drawing_scores_high(self):
        """Test that hatched square vs solid square scores high."""
        solid = self.create_square_image()
        hatched = self.create_hatched_square_image()

        placement_rect = rect_from_px(0, 0, 200, 200)

        score = compute_likeness(hatched, solid, placement_rect)

        # Matches docs/TESTING.md acceptance threshold for a matching drawing
        assert score > 0.7

    def test_empty_drawing_scores_low(self):
        """Test that empty (black) drawing vs solid white image scores low."""
        solid = Image.new("L", (200, 200), color=255)
        empty = Image.new("L", (200, 200), color=0)

        placement_rect = rect_from_px(0, 0, 200, 200)

        score = compute_likeness(empty, solid, placement_rect)

        assert score < 0.3

    def test_different_shape_scores_lower(self):
        """Test that a clearly different shape scores lower than a matching one."""
        square = self.create_square_image()
        bar = self.create_bar_image()
        hatched_square = self.create_hatched_square_image()

        placement_rect = rect_from_px(0, 0, 200, 200)

        score_hatched_vs_square = compute_likeness(hatched_square, square, placement_rect)
        score_hatched_vs_bar = compute_likeness(hatched_square, bar, placement_rect)

        # A different shape should score clearly lower, not just marginally lower
        assert score_hatched_vs_square > score_hatched_vs_bar + 0.1

    def test_score_ordering_not_exact_values(self):
        """Test that relative ordering is correct, not exact values."""
        solid_square = self.create_square_image()
        hatched_square = self.create_hatched_square_image()
        bar = self.create_bar_image()
        empty = Image.new("L", (200, 200), color=0)
        white = Image.new("L", (200, 200), color=255)

        placement_rect = rect_from_px(0, 0, 200, 200)

        scores = {
            "identical": compute_likeness(solid_square, solid_square, placement_rect),
            "hatched_vs_square": compute_likeness(hatched_square, solid_square, placement_rect),
            "hatched_vs_bar": compute_likeness(hatched_square, bar, placement_rect),
            "empty_vs_white": compute_likeness(empty, white, placement_rect),
        }

        # Ordering: identical > hatched_vs_square > hatched_vs_bar > empty_vs_white
        assert scores["identical"] > scores["hatched_vs_square"]
        assert scores["hatched_vs_square"] > scores["hatched_vs_bar"]
        assert scores["hatched_vs_bar"] > scores["empty_vs_white"]

    def test_placement_rect_cropping(self):
        """Test that placement_rect correctly crops the simulated image."""
        # Create a larger simulated image with a square in the top-left
        sim_img = Image.new("L", (400, 400), color=0)
        from PIL import ImageDraw

        draw = ImageDraw.Draw(sim_img)
        draw.rectangle([50, 50, 150, 150], fill=255)  # Square at (50,50) to (150,150)

        # Original is just the square
        orig_img = Image.new("L", (100, 100), color=255)

        placement_rect = rect_from_px(50, 50, 100, 100)

        score = compute_likeness(sim_img, orig_img, placement_rect)

        assert score > 0.9

    def test_explicit_px_per_mm_matches_default(self):
        """Test that the explicit pixels-per-mm argument matches the default scale."""
        img = self.create_square_image()
        placement_rect = rect_from_px(0, 0, 200, 200)

        default_score = compute_likeness(img, img, placement_rect)
        explicit_score = compute_likeness(img, img, placement_rect, dpi_px_per_mm=PX_PER_MM)

        assert default_score == explicit_score

    def test_default_scale_matches_simulate_plot(self):
        """Test that both functions share one pixels-per-mm scale unit and default."""
        likeness_default = inspect.signature(compute_likeness).parameters["dpi_px_per_mm"].default
        simulation_default = inspect.signature(simulate_plot).parameters["dpi_px_per_mm"].default

        assert likeness_default == simulation_default == PX_PER_MM

    def test_placement_rect_out_of_bounds_clamped(self):
        """Test that out-of-bounds placement rect is clamped."""
        sim_img = Image.new("L", (200, 200), color=255)
        orig_img = Image.new("L", (100, 100), color=255)

        # Placement rect extends beyond image
        placement_rect = (-10.0, -10.0, 50.0, 50.0)

        score = compute_likeness(sim_img, orig_img, placement_rect)

        # Should not crash, score should be valid
        assert 0.0 <= score <= 1.0

    def test_custom_target_size(self):
        """Test with custom target size."""
        img = self.create_square_image()
        placement_rect = rect_from_px(0, 0, 200, 200)

        score_64 = compute_likeness(img, img, placement_rect, target_size=(64, 64))
        score_256 = compute_likeness(img, img, placement_rect, target_size=(256, 256))

        # Both should be high for identical images
        assert score_64 > 0.9
        assert score_256 > 0.9

    def test_custom_blur_sigma(self):
        """Test with custom blur sigma."""
        img = self.create_square_image()
        placement_rect = rect_from_px(0, 0, 200, 200)

        score_no_blur = compute_likeness(img, img, placement_rect, blur_sigma=0.0)
        score_blur = compute_likeness(img, img, placement_rect, blur_sigma=2.0)

        # Both should be high for identical images
        assert score_no_blur > 0.9
        assert score_blur > 0.9

    def test_score_in_range(self):
        """Test that score is always in [0, 1]."""
        solid = self.create_square_image()
        empty = Image.new("L", (200, 200), color=0)
        placement_rect = rect_from_px(0, 0, 200, 200)

        for sim, orig in [(solid, solid), (solid, empty), (empty, solid), (empty, empty)]:
            score = compute_likeness(sim, orig, placement_rect)
            assert 0.0 <= score <= 1.0

    def test_rgb_images_work(self):
        """Test that RGB input images work."""
        rgb_solid = Image.new("RGB", (200, 200), color="white")
        draw = ImageDraw.Draw(rgb_solid)
        draw.rectangle([50, 50, 150, 150], fill="black")

        rgb_orig = Image.new("RGB", (200, 200), color="white")
        draw = ImageDraw.Draw(rgb_orig)
        draw.rectangle([50, 50, 150, 150], fill="black")

        placement_rect = rect_from_px(0, 0, 200, 200)

        score = compute_likeness(rgb_solid, rgb_orig, placement_rect)
        assert score > 0.9


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])
