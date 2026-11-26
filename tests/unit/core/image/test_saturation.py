"""Unit tests for the Lab-chroma boost and palette adaptation."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image
from skimage.color import rgb2lab

from penpath.core.image.saturation import adapt_saturation, boost_saturation
from penpath.core.models import Pen
from penpath.presets.palettes import get_palette

PALETTE = get_palette("stabilo_88").pens


def _lab(image: Image.Image) -> np.ndarray:
    """Return the CIE Lab array of an image."""
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    return rgb2lab(rgb)


def _chroma(image: Image.Image) -> np.ndarray:
    """Return the CIE Lab chroma of each pixel."""
    lab = _lab(image)
    return np.hypot(lab[..., 1], lab[..., 2])


def _muted_image() -> Image.Image:
    """Return a white-framed image whose ink is a muted green."""
    rgb = np.full((24, 24, 3), 244, dtype=np.uint8)
    rgb[4:20, 4:20] = (150, 160, 145)
    return Image.fromarray(rgb)


class TestBoostSaturation:
    def test_factor_one_returns_byte_identical_rgb(self) -> None:
        image = Image.fromarray(np.arange(3 * 8 * 8, dtype=np.uint8).reshape(8, 8, 3))
        assert boost_saturation(image, 1.0).tobytes() == image.tobytes()
        assert boost_saturation(image, 1.0).mode == image.mode

    def test_factor_one_returns_byte_identical_rgba(self) -> None:
        rgb = np.full((8, 8, 3), (130, 150, 120), dtype=np.uint8)
        alpha = np.arange(64, dtype=np.uint8).reshape(8, 8)
        image = Image.fromarray(np.dstack((rgb, alpha)))
        result = boost_saturation(image, 1.0)
        assert result.tobytes() == image.tobytes()
        assert result.mode == "RGBA"

    def test_factor_two_raises_chroma_without_moving_lightness(self) -> None:
        image = _muted_image()
        before = _lab(image)
        after = _lab(boost_saturation(image, 2.0))
        p90_before = float(np.percentile(_chroma(image)[4:20, 4:20], 90))
        p90_after = float(np.percentile(_chroma(boost_saturation(image, 2.0))[4:20, 4:20], 90))
        assert p90_after > p90_before * 1.5
        assert float(np.abs(after[..., 0] - before[..., 0]).mean()) < 1.0

    def test_factor_zero_gives_neutral_chroma(self) -> None:
        image = Image.new("RGB", (12, 12), (150, 160, 145))
        chroma = _chroma(boost_saturation(image, 0.0))
        assert float(np.abs(chroma).max()) < 1.0

    @pytest.mark.parametrize("factor", [-1.0, float("nan"), float("inf"), -float("inf")])
    def test_invalid_factor_is_rejected(self, factor: float) -> None:
        with pytest.raises(ValueError, match="finite, non-negative"):
            boost_saturation(Image.new("RGB", (2, 2), "red"), factor)

    def test_alpha_is_preserved(self) -> None:
        rgb = np.full((12, 12, 3), (150, 160, 145), dtype=np.uint8)
        alpha = np.arange(144, dtype=np.uint8).reshape(12, 12)
        image = Image.fromarray(np.dstack((rgb, alpha)))
        result = boost_saturation(image, 2.5)
        assert result.mode == "RGBA"
        assert np.array_equal(np.asarray(result)[..., 3], alpha)


class TestAdaptSaturation:
    def test_muted_image_gets_a_factor_above_one(self) -> None:
        factor = adapt_saturation(_muted_image(), PALETTE)
        assert 1.0 < factor <= 3.0

    def test_saturated_image_gets_one(self) -> None:
        saturated = Image.new("RGB", (12, 12), (0, 150, 62))
        assert adapt_saturation(saturated, PALETTE) == 1.0

    def test_neutral_image_is_capped_at_three(self) -> None:
        neutral = Image.new("RGB", (12, 12), (128, 128, 128))
        assert adapt_saturation(neutral, PALETTE) == 3.0

    def test_all_white_image_gets_one(self) -> None:
        assert adapt_saturation(Image.new("RGB", (12, 12), "white"), PALETTE) == 1.0

    def test_empty_palette_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one pen"):
            adapt_saturation(_muted_image(), [])

    def test_single_pen_matches_its_own_colour(self) -> None:
        pen = Pen(name="green", width_mm=0.4, color="#00963E")
        image = Image.new("RGB", (12, 12), (0, 150, 62))
        assert adapt_saturation(image, [pen]) == 1.0
