"""Unit tests for penpath.core.image.separate."""

import numpy as np
import pytest
from PIL import Image

from penpath.core.image.filters import grayscale
from penpath.core.image.separate import separate_palette
from penpath.core.models import Pen

RED = Pen(name="red", width_mm=0.4, color="#FF0000")
BLUE = Pen(name="blue", width_mm=0.4, color="#0000FF")
WHITE = Pen(name="white", width_mm=0.4, color="#FFFFFF")


def _three_region_image(size: int = 30) -> Image.Image:
    """Build a white image with a red square and a blue square."""
    image = Image.new("RGB", (size, size), "white")
    for y in range(2, 13):
        for x in range(2, 13):
            image.putpixel((x, y), (255, 0, 0))
    for y in range(16, 27):
        for x in range(16, 27):
            image.putpixel((x, y), (0, 0, 255))
    return image


def _region_mask(size: int, start: int, end: int) -> np.ndarray:
    mask = np.zeros((size, size), dtype=bool)
    mask[start:end, start:end] = True
    return mask


def test_separate_palette_regions_are_dark_only_for_own_pen() -> None:
    image = _three_region_image()
    pens = [RED, BLUE, WHITE]

    separated = separate_palette(image, pens)

    assert [pen for pen, _ in separated] == pens
    for _, layer in separated:
        assert layer.mode == "L"
        assert layer.size == image.size

    layers = {pen.name: np.asarray(layer) for pen, layer in separated}
    luminance = np.asarray(grayscale(image))
    red_mask = _region_mask(30, 2, 13)
    blue_mask = _region_mask(30, 16, 27)

    assert np.array_equal(layers["red"][red_mask], luminance[red_mask])
    assert np.all(layers["red"][~red_mask] == 255)
    assert np.array_equal(layers["blue"][blue_mask], luminance[blue_mask])
    assert np.all(layers["blue"][~blue_mask] == 255)
    assert np.all(layers["white"] == 255)


def test_separate_palette_follows_pen_order() -> None:
    separated = separate_palette(_three_region_image(), [BLUE, RED])

    assert [pen for pen, _ in separated] == [BLUE, RED]
    blue_layer = np.asarray(separated[0][1])
    red_layer = np.asarray(separated[1][1])
    blue_mask = _region_mask(30, 16, 27)
    red_mask = _region_mask(30, 2, 13)

    assert np.all(blue_layer[blue_mask] < 128)
    assert np.all(blue_layer[red_mask] == 255)
    assert np.all(red_layer[red_mask] < 128)
    assert np.all(red_layer[blue_mask] == 255)


def test_separate_palette_single_pen_keeps_all_luminance() -> None:
    image = _three_region_image()

    separated = separate_palette(image, [BLUE])

    assert len(separated) == 1
    assert separated[0][0] is BLUE
    assert np.array_equal(np.asarray(separated[0][1]), np.asarray(grayscale(image)))


def test_separate_palette_empty_palette_raises() -> None:
    with pytest.raises(ValueError, match="at least one pen"):
        separate_palette(_three_region_image(), [])


def test_separate_palette_no_pixels_raises() -> None:
    with pytest.raises(ValueError, match="at least one pixel"):
        separate_palette(Image.new("RGB", (0, 0)), [RED])


def test_separate_palette_invalid_pen_colour_names_pen() -> None:
    broken = Pen(name="broken", width_mm=0.4, color="not-a-colour")

    with pytest.raises(ValueError, match="broken"):
        separate_palette(_three_region_image(), [broken])
