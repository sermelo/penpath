"""Unit tests for paper detection and background masking."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from penpath.core import (
    DEFAULT_BACKGROUND_THRESHOLD,
    detect_paper_color,
    mask_background,
    remove_background,
    separate_palette,
)
from penpath.core.image import (
    BackgroundResult,
)
from penpath.core.image import (
    detect_paper_color as image_detect_paper_color,
)
from penpath.core.image import (
    remove_background as image_remove_background,
)
from penpath.presets.palettes import get_palette

PAPER = np.array([232, 230, 223], dtype=np.uint8)
PAPER_HEX = "#E8E6DF"


def _page(paper: np.ndarray = PAPER, size: int = 120) -> Image.Image:
    """Return a flat page of the given colour."""
    array = np.broadcast_to(paper, (size, size, 3)).astype(np.uint8).copy()
    return Image.fromarray(array)


def _with_drawing(
    drawing: np.ndarray,
    paper: np.ndarray = PAPER,
    box: tuple[int, int, int, int] = (40, 40, 80, 80),
) -> Image.Image:
    """Return a paper page with a solid dark rectangle in the middle."""
    image = _page(paper)
    x0, y0, x1, y1 = box
    array = np.asarray(image).copy()
    array[y0:y1, x0:x1] = drawing
    return Image.fromarray(array)


class TestDetectPaperColor:
    """The border ring estimates paper without looking at the drawing."""

    def test_detect_ignores_central_dark_drawing(self) -> None:
        assert (
            detect_paper_color(_with_drawing(np.array([60, 58, 55], dtype=np.uint8))) == PAPER_HEX
        )

    def test_detect_ignores_pale_sky_in_a_landscape(self) -> None:
        image = _with_drawing(np.array([205, 225, 245], dtype=np.uint8))
        array = np.asarray(image).copy()
        array[20:60, 20:100] = np.array([210, 230, 250], dtype=np.uint8)
        array[60:100, 20:100] = np.array([80, 110, 70], dtype=np.uint8)
        assert detect_paper_color(Image.fromarray(array)) == PAPER_HEX

    def test_detect_falls_back_to_light_cluster_for_a_dark_border(self) -> None:
        paper = np.array([240, 238, 230], dtype=np.uint8)
        image = _with_drawing(
            paper, paper=np.array([45, 42, 40], dtype=np.uint8), box=(12, 12, 108, 108)
        )
        assert detect_paper_color(image) == "#F0EEE6"

    def test_detect_does_not_adopt_a_saturated_full_bleed_colour(self) -> None:
        array = np.zeros((120, 120, 3), dtype=np.uint8)
        array[:, :60] = np.array([255, 0, 0], dtype=np.uint8)
        array[:, 60:] = np.array([0, 0, 255], dtype=np.uint8)
        image = Image.fromarray(array)
        assert detect_paper_color(image) not in ("#FF0000", "#0000FF")
        assert np.array_equal(np.asarray(remove_background(image)), array)

    def test_detect_empty_image_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one pixel"):
            detect_paper_color(Image.new("RGB", (0, 1)))


class TestRemoveBackground:
    """Paper pixels become white and drawing pixels keep their colour."""

    def test_remove_background_keeps_strokes_and_whites_paper(self) -> None:
        rng = np.random.default_rng(7)
        array = np.broadcast_to(PAPER, (120, 120, 3)).astype(np.int16).copy()
        array += rng.integers(-2, 3, (120, 120, 1))
        array[40:80, 40:80] = np.array([78, 76, 73], dtype=np.int16)
        original = Image.fromarray(array.astype(np.uint8))
        result = remove_background(original)

        output = np.asarray(result)
        source = np.asarray(original)
        assert result.mode == "RGB"
        assert np.all(output[:30, :] == 255)
        assert np.all(output[40:80, 40:80] == source[40:80, 40:80])

    def test_remove_background_threshold_edges(self) -> None:
        colors = np.array(
            [[128, 128, 128], [135, 135, 135], [150, 150, 150], [160, 160, 160]],
            dtype=np.uint8,
        )
        image = Image.fromarray(colors.reshape(2, 2, 3))
        masked = np.asarray(remove_background(image, paper_color="#808080", threshold=10))
        assert np.all(masked.reshape(-1, 3)[:3] == 255)
        assert np.array_equal(masked.reshape(-1, 3)[3], colors[3])

        exact = np.asarray(remove_background(image, paper_color="#808080", threshold=0))
        assert np.all(exact.reshape(-1, 3)[0] == 255)
        assert np.array_equal(exact.reshape(-1, 3)[1], colors[1])

        everything = np.asarray(remove_background(image, paper_color="#808080", threshold=100))
        assert np.all(everything == 255)

    def test_mask_background_reports_color_and_coverage(self) -> None:
        source = np.broadcast_to(PAPER, (10, 10, 3)).astype(np.uint8).copy()
        source[:, :5] = np.array([60, 58, 55], dtype=np.uint8)
        result = mask_background(Image.fromarray(source))
        assert isinstance(result, BackgroundResult)
        assert result.paper_color == PAPER_HEX
        assert result.masked_percent == 50.0
        assert np.all(np.asarray(result.image)[:, 5:] == 255)
        assert np.array_equal(
            np.asarray(result.image)[:, :5], np.asarray(Image.fromarray(source))[:, :5]
        )

    @pytest.mark.parametrize("threshold", [-1.0, float("nan"), float("inf")])
    def test_remove_background_rejects_invalid_threshold(self, threshold: float) -> None:
        with pytest.raises(ValueError, match="finite, non-negative"):
            remove_background(_page(), threshold=threshold)

    def test_remove_background_rejects_invalid_color(self) -> None:
        with pytest.raises(ValueError, match="Invalid paper colour"):
            remove_background(_page(), paper_color="not-a-colour")

    def test_remove_background_empty_image_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one pixel"):
            remove_background(Image.new("RGB", (1, 0)))

    def test_default_threshold_is_measured_value(self) -> None:
        assert DEFAULT_BACKGROUND_THRESHOLD == 10.0

    def test_masked_pixels_are_white_in_every_palette_channel(self) -> None:
        image = _with_drawing(np.array([60, 58, 55], dtype=np.uint8))
        masked = remove_background(image)
        channels = separate_palette(masked, get_palette("stabilo_88").pens)
        assert channels
        for _, channel in channels:
            pixels = np.asarray(channel)
            assert np.all(pixels[:30, :] == 255)

    def test_core_and_image_packages_export_background_helpers(self) -> None:
        assert image_detect_paper_color is detect_paper_color
        assert image_remove_background is remove_background
