"""Unit tests for likeness scoring."""

from __future__ import annotations

import inspect

import numpy as np
import pytest
from PIL import Image, ImageDraw

from penpath.core.likeness import (
    compute_edge_likeness,
    compute_likeness,
    prepare_for_comparison,
)
from penpath.core.simulation import simulate_plot

PX_PER_MM = 96 / 25.4


def rect_from_px(
    x_px: float, y_px: float, w_px: float, h_px: float
) -> tuple[float, float, float, float]:
    return (x_px / PX_PER_MM, y_px / PX_PER_MM, w_px / PX_PER_MM, h_px / PX_PER_MM)


def test_public_api_exports():
    """Test that likeness functions are available via the public penpath.core API."""
    from penpath.core import compute_edge_likeness as public_compute_edge_likeness
    from penpath.core import compute_likeness as public_compute_likeness
    from penpath.core import prepare_for_comparison as public_prepare_for_comparison

    assert public_compute_edge_likeness is compute_edge_likeness
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


class TestComputeEdgeLikeness:
    """Edge SSIM penalises structure the original does not have."""

    def create_square_image(self, size: int = 200, dark: int = 0) -> Image.Image:
        """Solid dark square on white, with the same outline as the original."""
        image = Image.new("L", (size, size), color=255)
        draw = ImageDraw.Draw(image)
        margin = size // 4
        draw.rectangle([margin, margin, size - margin, size - margin], fill=dark)
        return image

    def create_outline_image(self, size: int = 200) -> Image.Image:
        """Only the square's outline, as a plotted drawing would draw it."""
        image = Image.new("L", (size, size), color=255)
        draw = ImageDraw.Draw(image)
        margin = size // 4
        draw.rectangle([margin, margin, size - margin, size - margin], outline=0, width=3)
        return image

    def create_scribble_image(self, size: int = 200, line_value: int = 220) -> Image.Image:
        """Faint horizontal lines covering a near-blank page."""
        image = Image.new("L", (size, size), color=255)
        draw = ImageDraw.Draw(image)
        for y in range(2, size, 6):
            draw.line([(2, y), (size - 3, y)], fill=line_value)
        return image

    def test_identical_images_score_one(self) -> None:
        image = self.create_square_image()
        score = compute_edge_likeness(image, image, rect_from_px(0, 0, 200, 200))
        assert score == pytest.approx(1.0)

    def test_both_zero_edge_maps_score_one(self) -> None:
        """Two uniform images have the same (absent) structure."""
        blank = Image.new("L", (200, 200), color=255)
        other_blank = Image.new("L", (200, 200), color=128)
        score = compute_edge_likeness(blank, other_blank, rect_from_px(0, 0, 200, 200))
        assert score == pytest.approx(1.0)

    def test_blank_vs_faint_scribble_penalises_spurious_edges(self) -> None:
        """The greyscale blind spot: faint full-page lines look neutral in tone."""
        blank = Image.new("L", (200, 200), color=255)
        scribble = self.create_scribble_image()
        rect = rect_from_px(0, 0, 200, 200)

        grey = compute_likeness(scribble, blank, rect)
        edge = compute_edge_likeness(scribble, blank, rect)

        assert grey > 0.7
        assert edge < 0.05
        assert edge < grey - 0.5

    def test_shared_maximum_keeps_a_blank_page_from_making_false_edges(self) -> None:
        """Scaling only the scribble's contrast cannot change its edge SSIM."""
        blank = Image.new("L", (200, 200), color=255)
        rect = rect_from_px(0, 0, 200, 200)
        faint = compute_edge_likeness(self.create_scribble_image(220), blank, rect)
        darker = compute_edge_likeness(self.create_scribble_image(180), blank, rect)
        assert faint == pytest.approx(darker, abs=0.01)
        assert faint < 0.05

    def test_matching_edges_score_high(self) -> None:
        """A drawing that follows the original's outline keeps a high edge score."""
        score = compute_edge_likeness(
            self.create_outline_image(),
            self.create_square_image(),
            rect_from_px(0, 0, 200, 200),
        )
        assert score > 0.7

    def test_hatched_square_matching_edges_score(self) -> None:
        """A hatched version of the solid square keeps its edges (measured 0.7215)."""
        hatched = Image.new("L", (200, 200), color=255)
        draw = ImageDraw.Draw(hatched)
        for y in range(50, 151, 4):
            draw.line([(50, y), (150, y)], fill=0, width=2)

        score = compute_edge_likeness(
            hatched,
            self.create_square_image(),
            rect_from_px(0, 0, 200, 200),
        )
        assert score == pytest.approx(0.7215, abs=0.001)
        assert score > 0.70

    def test_placement_crop_ignores_edges_outside_the_rectangle(self) -> None:
        """Structure outside the placement must not be scored as spurious ink."""
        simulated = Image.new("L", (400, 400), color=255)
        draw = ImageDraw.Draw(simulated)
        draw.rectangle([50, 50, 150, 150], outline=0, width=3)
        draw.rectangle([250, 50, 350, 150], outline=0, width=3)
        original = simulated.crop((50, 50, 150, 150))

        cropped = compute_edge_likeness(simulated, original, rect_from_px(50, 50, 100, 100))
        whole_page = compute_edge_likeness(simulated, original, rect_from_px(0, 0, 400, 400))

        assert cropped > 0.7
        assert cropped > whole_page + 0.2

    def test_defaults_match_compute_likeness(self) -> None:
        edge_params = inspect.signature(compute_edge_likeness).parameters
        grey_params = inspect.signature(compute_likeness).parameters
        for name in ("target_size", "blur_sigma", "dpi_px_per_mm"):
            assert edge_params[name].default == grey_params[name].default

    def test_score_in_range(self) -> None:
        rect = rect_from_px(0, 0, 200, 200)
        images = [
            Image.new("L", (200, 200), color=255),
            self.create_square_image(),
            self.create_scribble_image(),
        ]
        for simulated in images:
            for original in images:
                score = compute_edge_likeness(simulated, original, rect)
                assert 0.0 <= score <= 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])
