"""Unit tests for penpath.core.image.filters."""

import numpy as np
import pytest
from PIL import Image

from penpath.core.image.filters import (
    DitherMethod,
    GrayscaleMethod,
    _BAYER_8x8,
    _floyd_steinberg_dither,
    _grayscale_average,
    _grayscale_lightness,
    _grayscale_luminance,
    _ordered_dither,
    auto_equalize,
    box_blur,
    brightness,
    contrast,
    gamma,
    gaussian_blur,
    grayscale,
    invert,
    posterize,
    threshold,
)


class TestGrayscale:
    """Tests for grayscale function."""

    def test_grayscale_identity_l_mode(self) -> None:
        """Test grayscale on already grayscale image returns copy."""
        img = Image.new("L", (100, 100), color=128)
        result = grayscale(img)
        assert result.mode == "L"
        assert result is not img
        assert list(result.getdata()) == list(img.getdata())

    def test_grayscale_rgb_to_l(self) -> None:
        """Test RGB to grayscale conversion."""
        img = Image.new("RGB", (100, 100), color=(255, 128, 64))
        result = grayscale(img)
        assert result.mode == "L"
        assert result.size == (100, 100)

    def test_grayscale_rgba_to_l(self) -> None:
        """Test RGBA to grayscale conversion."""
        img = Image.new("RGBA", (100, 100), color=(255, 128, 64, 200))
        result = grayscale(img)
        assert result.mode == "L"

    @pytest.mark.parametrize("method", list(GrayscaleMethod))
    def test_grayscale_all_methods(self, method: GrayscaleMethod) -> None:
        """Test all grayscale methods work."""
        img = Image.new("RGB", (10, 10), color=(255, 128, 64))
        result = grayscale(img, method)
        assert result.mode == "L"
        assert result.size == (10, 10)

    def test_grayscale_method_string_input(self) -> None:
        """Test grayscale accepts string method."""
        img = Image.new("RGB", (10, 10), color=(255, 128, 64))
        result = grayscale(img, "luminance")
        assert result.mode == "L"

    def test_grayscale_invalid_method_raises(self) -> None:
        """Test grayscale raises for invalid method."""
        img = Image.new("RGB", (10, 10), color=(255, 128, 64))
        with pytest.raises(ValueError):
            grayscale(img, "invalid_method")

    def test_grayscale_luminance_values(self) -> None:
        """Test luminance method produces correct values."""
        img = Image.new("RGB", (2, 2))
        img.putpixel((0, 0), (255, 0, 0))  # Red
        img.putpixel((1, 0), (0, 255, 0))  # Green
        img.putpixel((0, 1), (0, 0, 255))  # Blue
        img.putpixel((1, 1), (255, 255, 255))  # White

        result = grayscale(img, GrayscaleMethod.LUMINANCE)
        # Luminance: 0.299*R + 0.587*G + 0.114*B
        assert result.getpixel((0, 0)) == round(0.299 * 255)  # 76
        assert result.getpixel((1, 0)) in (149, 150)  # 150 (may be 149 due to FP)
        assert result.getpixel((0, 1)) == round(0.114 * 255)  # 29
        assert result.getpixel((1, 1)) == 255

    def test_grayscale_lightness_values(self) -> None:
        """Test lightness method produces correct values."""
        img = Image.new("RGB", (2, 2))
        img.putpixel((0, 0), (255, 0, 0))  # Red: max=255, min=0, lightness=127
        img.putpixel((1, 1), (255, 255, 255))  # White: lightness=255

        result = grayscale(img, GrayscaleMethod.LIGHTNESS)
        assert result.getpixel((0, 0)) == 127
        assert result.getpixel((1, 1)) == 255

    def test_grayscale_average_values(self) -> None:
        """Test average method produces correct values."""
        img = Image.new("RGB", (1, 1), color=(255, 128, 64))
        result = grayscale(img, GrayscaleMethod.AVERAGE)
        assert result.getpixel((0, 0)) == round((255 + 128 + 64) / 3)  # ~149

    def test_grayscale_red_channel(self) -> None:
        """Test red channel extraction."""
        img = Image.new("RGB", (1, 1), color=(255, 128, 64))
        result = grayscale(img, GrayscaleMethod.RED)
        assert result.getpixel((0, 0)) == 255

    def test_grayscale_green_channel(self) -> None:
        """Test green channel extraction."""
        img = Image.new("RGB", (1, 1), color=(255, 128, 64))
        result = grayscale(img, GrayscaleMethod.GREEN)
        assert result.getpixel((0, 0)) == 128

    def test_grayscale_blue_channel(self) -> None:
        """Test blue channel extraction."""
        img = Image.new("RGB", (1, 1), color=(255, 128, 64))
        result = grayscale(img, GrayscaleMethod.BLUE)
        assert result.getpixel((0, 0)) == 64


class TestThreshold:
    """Tests for threshold function."""

    def test_threshold_identity_level_0(self) -> None:
        """Test threshold with level=0 makes everything white."""
        img = Image.new("L", (10, 10), color=128)
        result = threshold(img, level=0)
        assert all(p == 255 for p in result.getdata())

    def test_threshold_identity_level_255(self) -> None:
        """Test threshold with level=255 makes almost everything black."""
        img = Image.new("L", (10, 10), color=128)
        result = threshold(img, level=255)
        assert all(p == 0 for p in result.getdata())

    def test_threshold_mid_level(self) -> None:
        """Test threshold at mid level."""
        img = Image.new("L", (10, 10))
        for i in range(100):
            img.putdata([i % 256 for _ in range(100)])
        result = threshold(img, level=128)
        # Values >= 128 become 255, others 0
        data = list(result.getdata())
        assert all(p in (0, 255) for p in data)

    def test_threshold_invalid_level_low_raises(self) -> None:
        """Test threshold raises for level < 0."""
        img = Image.new("L", (10, 10))
        with pytest.raises(ValueError, match="0-255"):
            threshold(img, level=-1)

    def test_threshold_invalid_level_high_raises(self) -> None:
        """Test threshold raises for level > 255."""
        img = Image.new("L", (10, 10))
        with pytest.raises(ValueError, match="0-255"):
            threshold(img, level=256)

    @pytest.mark.parametrize("dither", list(DitherMethod))
    def test_threshold_all_dither_methods(self, dither: DitherMethod) -> None:
        """Test all dithering methods work."""
        img = Image.new("L", (20, 20), color=128)
        result = threshold(img, level=128, dither=dither)
        assert result.mode == "L"
        assert result.size == (20, 20)
        assert all(p in (0, 255) for p in result.getdata())

    def test_threshold_dither_string_input(self) -> None:
        """Test threshold accepts string dither method."""
        img = Image.new("L", (10, 10), color=128)
        result = threshold(img, level=128, dither="floyd_steinberg")
        assert result.mode == "L"

    def test_threshold_invalid_dither_raises(self) -> None:
        """Test threshold raises for invalid dither method."""
        img = Image.new("L", (10, 10))
        with pytest.raises(ValueError):
            threshold(img, level=128, dither="invalid")

    def test_threshold_converts_rgb_to_gray(self) -> None:
        """Test threshold converts RGB input to grayscale."""
        img = Image.new("RGB", (10, 10), color=(255, 0, 0))
        result = threshold(img, level=128)
        assert result.mode == "L"

    def test_floyd_steinberg_dither_pattern(self) -> None:
        """Test Floyd-Steinberg dithering produces expected pattern."""
        img = Image.new("L", (10, 10), color=128)
        result = _floyd_steinberg_dither(img, 128)
        # With constant 128 and threshold 128, should alternate
        data = list(result.getdata())
        assert all(p in (0, 255) for p in data)

    def test_ordered_dither_pattern(self) -> None:
        """Test ordered dithering produces expected pattern."""
        img = Image.new("L", (16, 16), color=128)
        result = _ordered_dither(img, 128)
        data = list(result.getdata())
        assert all(p in (0, 255) for p in data)


class TestPosterize:
    """Tests for posterize function."""

    def test_posterize_identity_levels_256(self) -> None:
        """Test posterize with 256 levels returns copy."""
        img = Image.new("L", (10, 10), color=128)
        result = posterize(img, levels=256)
        assert list(result.getdata()) == list(img.getdata())

    def test_posterize_2_levels(self) -> None:
        """Test posterize with 2 levels (binary)."""
        img = Image.new("L", (10, 10))
        for i in range(100):
            img.putdata([i % 256 for _ in range(100)])
        result = posterize(img, levels=2)
        data = list(result.getdata())
        # Should only have 2 values
        unique = set(data)
        assert len(unique) <= 2

    def test_posterize_4_levels(self) -> None:
        """Test posterize with 4 levels."""
        img = Image.new("L", (10, 10))
        for i in range(100):
            img.putdata([i % 256 for _ in range(100)])
        result = posterize(img, levels=4)
        data = list(result.getdata())
        unique = set(data)
        assert len(unique) <= 4

    def test_posterize_invalid_levels_low_raises(self) -> None:
        """Test posterize raises for levels < 2."""
        img = Image.new("L", (10, 10))
        with pytest.raises(ValueError, match="2-256"):
            posterize(img, levels=1)

    def test_posterize_invalid_levels_high_raises(self) -> None:
        """Test posterize raises for levels > 256."""
        img = Image.new("L", (10, 10))
        with pytest.raises(ValueError, match="2-256"):
            posterize(img, levels=257)

    @pytest.mark.parametrize("dither", list(DitherMethod))
    def test_posterize_all_dither_methods(self, dither: DitherMethod) -> None:
        """Test all dithering methods work with posterize."""
        img = Image.new("L", (20, 20), color=128)
        result = posterize(img, levels=4, dither=dither)
        assert result.mode == "L"
        assert result.size == (20, 20)

    def test_posterize_converts_rgb_to_gray(self) -> None:
        """Test posterize converts RGB input to grayscale."""
        img = Image.new("RGB", (10, 10), color=(255, 0, 0))
        result = posterize(img, levels=4)
        assert result.mode == "L"

    def test_posterize_step_calculation(self) -> None:
        """Test posterize step calculation is correct."""
        img = Image.new("L", (4, 1))
        img.putpixel((0, 0), 0)
        img.putpixel((1, 0), 85)
        img.putpixel((2, 0), 170)
        img.putpixel((3, 0), 255)

        result = posterize(img, levels=4)
        # With 4 levels, step = 64, centers at 32, 96, 160, 224
        # 0 -> 32, 85 -> 96, 170 -> 160, 255 -> 224
        assert result.getpixel((0, 0)) == 32
        assert result.getpixel((1, 0)) == 96
        assert result.getpixel((2, 0)) == 160
        assert result.getpixel((3, 0)) == 224


class TestGaussianBlur:
    """Tests for gaussian_blur function."""

    def test_gaussian_blur_identity_radius_0(self) -> None:
        """Test gaussian blur with radius=0 returns copy."""
        img = Image.new("RGB", (100, 100), color="red")
        result = gaussian_blur(img, radius=0)
        assert list(result.getdata()) == list(img.getdata())

    def test_gaussian_blur_small_radius(self) -> None:
        """Test gaussian blur with small radius."""
        img = Image.new("RGB", (100, 100), color="red")
        result = gaussian_blur(img, radius=1.0)
        assert result.size == (100, 100)
        assert result.mode == "RGB"

    def test_gaussian_blur_large_radius(self) -> None:
        """Test gaussian blur with large radius."""
        img = Image.new("RGB", (100, 100), color="red")
        result = gaussian_blur(img, radius=10.0)
        assert result.size == (100, 100)

    def test_gaussian_blur_invalid_radius_raises(self) -> None:
        """Test gaussian blur raises for negative radius."""
        img = Image.new("RGB", (100, 100))
        with pytest.raises(ValueError, match=">= 0"):
            gaussian_blur(img, radius=-1.0)

    def test_gaussian_blur_preserves_mode(self) -> None:
        """Test gaussian blur preserves image mode."""
        for mode in ["L", "RGB", "RGBA"]:
            img = Image.new(mode, (50, 50), color=128)
            result = gaussian_blur(img, radius=2.0)
            assert result.mode == mode


class TestBoxBlur:
    """Tests for box_blur function."""

    def test_box_blur_identity_radius_0(self) -> None:
        """Test box blur with radius=0 returns copy."""
        img = Image.new("RGB", (100, 100), color="red")
        result = box_blur(img, radius=0)
        assert list(result.getdata()) == list(img.getdata())

    def test_box_blur_small_radius(self) -> None:
        """Test box blur with small radius."""
        img = Image.new("RGB", (100, 100), color="red")
        result = box_blur(img, radius=1)
        assert result.size == (100, 100)

    def test_box_blur_large_radius(self) -> None:
        """Test box blur with large radius."""
        img = Image.new("RGB", (100, 100), color="red")
        result = box_blur(img, radius=10)
        assert result.size == (100, 100)

    def test_box_blur_invalid_radius_raises(self) -> None:
        """Test box blur raises for negative radius."""
        img = Image.new("RGB", (100, 100))
        with pytest.raises(ValueError, match=">= 0"):
            box_blur(img, radius=-1)

    def test_box_blur_preserves_mode(self) -> None:
        """Test box blur preserves image mode."""
        for mode in ["L", "RGB", "RGBA"]:
            img = Image.new(mode, (50, 50), color=128)
            result = box_blur(img, radius=2)
            assert result.mode == mode


class TestContrast:
    """Tests for contrast function."""

    def test_contrast_identity_factor_1(self) -> None:
        """Test contrast with factor=1 returns copy."""
        img = Image.new("RGB", (100, 100), color=(128, 64, 192))
        result = contrast(img, factor=1.0)
        assert list(result.getdata()) == list(img.getdata())

    def test_contrast_zero_factor(self) -> None:
        """Test contrast with factor=0 gives gray image."""
        img = Image.new("RGB", (10, 10), color=(255, 0, 0))
        result = contrast(img, factor=0.0)
        # All pixels should be the same (middle gray)
        data = list(result.getdata())
        assert all(p == data[0] for p in data)

    def test_contrast_high_factor(self) -> None:
        """Test contrast with factor > 1 increases contrast."""
        img = Image.new("RGB", (10, 10), color=(128, 128, 128))
        result = contrast(img, factor=2.0)
        assert result.size == (10, 10)

    def test_contrast_invalid_factor_raises(self) -> None:
        """Test contrast raises for negative factor."""
        img = Image.new("RGB", (10, 10))
        with pytest.raises(ValueError, match=">= 0"):
            contrast(img, factor=-1.0)

    def test_contrast_preserves_mode(self) -> None:
        """Test contrast preserves image mode."""
        for mode in ["L", "RGB", "RGBA"]:
            img = Image.new(mode, (50, 50), color=128)
            result = contrast(img, factor=1.5)
            assert result.mode == mode


class TestBrightness:
    """Tests for brightness function."""

    def test_brightness_identity_factor_1(self) -> None:
        """Test brightness with factor=1 returns copy."""
        img = Image.new("RGB", (100, 100), color=(128, 64, 192))
        result = brightness(img, factor=1.0)
        assert list(result.getdata()) == list(img.getdata())

    def test_brightness_zero_factor(self) -> None:
        """Test brightness with factor=0 gives black image."""
        img = Image.new("RGB", (10, 10), color=(255, 255, 255))
        result = brightness(img, factor=0.0)
        assert all(p == (0, 0, 0) for p in result.getdata())

    def test_brightness_high_factor(self) -> None:
        """Test brightness with factor > 1 brightens image."""
        img = Image.new("RGB", (10, 10), color=(128, 128, 128))
        result = brightness(img, factor=2.0)
        assert all(p == (255, 255, 255) for p in result.getdata())

    def test_brightness_invalid_factor_raises(self) -> None:
        """Test brightness raises for negative factor."""
        img = Image.new("RGB", (10, 10))
        with pytest.raises(ValueError, match=">= 0"):
            brightness(img, factor=-1.0)

    def test_brightness_preserves_mode(self) -> None:
        """Test brightness preserves image mode."""
        for mode in ["L", "RGB", "RGBA"]:
            img = Image.new(mode, (50, 50), color=128)
            result = brightness(img, factor=1.5)
            assert result.mode == mode


class TestGamma:
    """Tests for gamma function."""

    def test_gamma_identity_gamma_1(self) -> None:
        """Test gamma with gamma=1 returns copy."""
        img = Image.new("RGB", (100, 100), color=(128, 64, 192))
        result = gamma(img, gamma=1.0)
        assert list(result.getdata()) == list(img.getdata())

    def test_gamma_less_than_1_brightens(self) -> None:
        """Test gamma < 1 brightens midtones."""
        img = Image.new("L", (10, 10), color=128)
        result = gamma(img, gamma=0.5)
        assert all(p > 128 for p in result.getdata())

    def test_gamma_greater_than_1_darkens(self) -> None:
        """Test gamma > 1 darkens midtones."""
        img = Image.new("L", (10, 10), color=128)
        result = gamma(img, gamma=2.0)
        assert all(p < 128 for p in result.getdata())

    def test_gamma_invalid_zero_raises(self) -> None:
        """Test gamma raises for gamma <= 0."""
        img = Image.new("RGB", (10, 10))
        with pytest.raises(ValueError, match="> 0"):
            gamma(img, gamma=0)

    def test_gamma_invalid_negative_raises(self) -> None:
        """Test gamma raises for negative gamma."""
        img = Image.new("RGB", (10, 10))
        with pytest.raises(ValueError, match="> 0"):
            gamma(img, gamma=-1.0)

    def test_gamma_preserves_mode(self) -> None:
        """Test gamma preserves image mode."""
        for mode in ["L", "RGB", "RGBA"]:
            img = Image.new(mode, (50, 50), color=128)
            result = gamma(img, gamma=1.5)
            assert result.mode == mode


class TestInvert:
    """Tests for invert function."""

    def test_invert_rgb(self) -> None:
        """Test invert on RGB image."""
        img = Image.new("RGB", (10, 10), color=(255, 128, 64))
        result = invert(img)
        assert result.getpixel((0, 0)) == (0, 127, 191)

    def test_invert_l(self) -> None:
        """Test invert on grayscale image."""
        img = Image.new("L", (10, 10), color=128)
        result = invert(img)
        assert result.getpixel((0, 0)) == 127

    def test_invert_rgba(self) -> None:
        """Test invert on RGBA image preserves alpha."""
        img = Image.new("RGBA", (10, 10), color=(255, 128, 64, 200))
        result = invert(img)
        # RGB inverted, alpha preserved
        assert result.getpixel((0, 0)) == (0, 127, 191, 200)

    def test_invert_double_returns_original(self) -> None:
        """Test double invert returns original."""
        img = Image.new("RGB", (10, 10), color=(255, 128, 64))
        result = invert(invert(img))
        assert list(result.getdata()) == list(img.getdata())

    def test_invert_preserves_size(self) -> None:
        """Test invert preserves image size."""
        img = Image.new("RGB", (123, 456), color="red")
        result = invert(img)
        assert result.size == (123, 456)


class TestAutoEqualize:
    """Tests for linear levels normalization."""

    def test_auto_equalize_full_range_l_is_byte_identical(self) -> None:
        """An image covering 0-255 is copied without changing a pixel."""
        img = Image.new("L", (4, 1))
        img.putdata([0, 85, 170, 255])
        result = auto_equalize(img)
        assert result is not img
        assert list(result.getdata()) == list(img.getdata())

    def test_auto_equalize_wide_range_l_is_byte_identical(self) -> None:
        """An image spanning 31-255 (7/8 of the range) is left unchanged."""
        img = Image.new("L", (4, 1))
        img.putdata([31, 80, 160, 255])
        result = auto_equalize(img)
        assert result is not img
        assert list(result.getdata()) == list(img.getdata())

    def test_auto_equalize_wide_range_rgb_is_byte_identical(self) -> None:
        """The wide-range no-op applies to RGB luminance as well."""
        img = Image.new("RGB", (2, 1))
        img.putdata([(31, 31, 31), (255, 255, 255)])
        result = auto_equalize(img)
        assert list(result.getdata()) == list(img.getdata())

    def test_auto_equalize_low_contrast_l_stretches_to_full_range(self) -> None:
        """A narrow luminance range is stretched to 0-255."""
        img = Image.new("L", (4, 1))
        img.putdata([64, 106, 149, 191])
        result = auto_equalize(img)
        assert result.mode == "L"
        assert min(result.getdata()) == 0
        assert max(result.getdata()) == 255

    def test_auto_equalize_low_contrast_rgb_uses_one_luminance_table(self) -> None:
        """The same table reaches every colour channel."""
        img = Image.new("RGB", (2, 1))
        img.putdata([(50, 60, 70), (150, 160, 170)])
        result = auto_equalize(img)
        assert result.mode == "RGB"
        assert result.getpixel((0, 0))[0] == 0
        assert result.getpixel((1, 0))[2] == 255

    def test_auto_equalize_near_uniform_is_unchanged(self) -> None:
        """A range narrower than 16 levels is not amplified."""
        img = Image.new("L", (4, 1))
        img.putdata([100, 101, 102, 103])
        result = auto_equalize(img)
        assert list(result.getdata()) == list(img.getdata())

    def test_auto_equalize_preserves_alpha(self) -> None:
        """RGBA colour channels are stretched but alpha is copied through."""
        img = Image.new("RGBA", (2, 1))
        img.putdata([(50, 60, 70, 7), (150, 160, 170, 9)])
        result = auto_equalize(img)
        assert result.mode == "RGBA"
        assert [pixel[3] for pixel in result.getdata()] == [7, 9]
        assert result.getpixel((0, 0))[:3] != img.getpixel((0, 0))[:3]

    def test_auto_equalize_supports_la(self) -> None:
        """LA mode stretches lightness and keeps alpha."""
        img = Image.new("LA", (2, 1))
        img.putdata([(50, 200), (150, 100)])
        result = auto_equalize(img)
        assert result.mode == "LA"
        assert result.getpixel((0, 0)) == (0, 200)
        assert result.getpixel((1, 0)) == (255, 100)

    def test_auto_equalize_does_not_mutate_input(self) -> None:
        """The source image keeps every pixel."""
        img = Image.new("RGB", (2, 1))
        img.putdata([(50, 60, 70), (150, 160, 170)])
        before = list(img.getdata())
        auto_equalize(img)
        assert list(img.getdata()) == before

    def test_auto_equalize_unsupported_mode_raises(self) -> None:
        """Other modes fail with an actionable message."""
        img = Image.new("P", (2, 2))
        with pytest.raises(TypeError, match="L, LA, RGB and RGBA"):
            auto_equalize(img)


class TestFilterChaining:
    """Tests for chaining multiple filters."""

    def test_grayscale_then_threshold(self) -> None:
        """Test grayscale followed by threshold."""
        img = Image.new("RGB", (100, 100), color=(200, 100, 50))
        gray = grayscale(img)
        thresh = threshold(gray, level=128)
        assert thresh.mode == "L"
        assert all(p in (0, 255) for p in thresh.getdata())

    def test_grayscale_then_posterize(self) -> None:
        """Test grayscale followed by posterize."""
        img = Image.new("RGB", (100, 100), color=(200, 100, 50))
        gray = grayscale(img)
        poster = posterize(gray, levels=4)
        assert poster.mode == "L"
        assert len(set(poster.getdata())) <= 4

    def test_blur_then_contrast(self) -> None:
        """Test blur followed by contrast."""
        img = Image.new("RGB", (100, 100), color=(128, 128, 128))
        blurred = gaussian_blur(img, radius=2.0)
        contrasted = contrast(blurred, factor=2.0)
        assert contrasted.size == (100, 100)

    def test_complex_chain(self) -> None:
        """Test a complex filter chain."""
        img = Image.new("RGB", (200, 200), color=(200, 100, 50))
        result = grayscale(img)
        result = gaussian_blur(result, radius=1.0)
        result = contrast(result, factor=1.5)
        result = brightness(result, factor=1.1)
        result = gamma(result, gamma=0.9)
        result = threshold(result, level=128, dither=DitherMethod.FLOYD_STEINBERG)
        assert result.mode == "L"
        assert all(p in (0, 255) for p in result.getdata())


class TestHelperFunctions:
    """Tests for internal helper functions."""

    def test_bayer_8x8_values(self) -> None:
        """Test Bayer 8x8 matrix has correct properties."""
        assert _BAYER_8x8.shape == (8, 8)
        assert _BAYER_8x8.min() >= 0
        assert _BAYER_8x8.max() <= 255

    def test_grayscale_luminance_helper(self) -> None:
        """Test _grayscale_luminance helper."""
        rgb = Image.new("RGB", (2, 2))
        rgb.putpixel((0, 0), (255, 0, 0))
        rgb.putpixel((1, 1), (255, 255, 255))
        result = _grayscale_luminance(rgb)
        assert result.mode == "L"

    def test_grayscale_lightness_helper(self) -> None:
        """Test _grayscale_lightness helper."""
        rgb = Image.new("RGB", (1, 1), color=(255, 0, 0))
        result = _grayscale_lightness(rgb)
        assert result.getpixel((0, 0)) == 127

    def test_grayscale_average_helper(self) -> None:
        """Test _grayscale_average helper."""
        rgb = Image.new("RGB", (1, 1), color=(255, 128, 64))
        result = _grayscale_average(rgb)
        assert result.getpixel((0, 0)) == round((255 + 128 + 64) / 3)


def test_auto_equalize_ignores_a_few_extreme_pixels() -> None:
    """A flat photo with one black speck and one white highlight is stretched."""
    row = np.linspace(110, 150, 200)
    values = np.tile(row, (100, 1)).astype(np.uint8)
    values[0, 0], values[0, 1] = 0, 255
    image = Image.fromarray(values)
    assert np.array_equal(np.asarray(auto_equalize(image)), values)  # default: unchanged
    result = np.asarray(auto_equalize(image, clip_percent=0.5))
    assert np.percentile(result, 1) < 20 and np.percentile(result, 99) > 235
