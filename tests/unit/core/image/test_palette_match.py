"""Unit tests for penpath.core.image.separate.palette_match."""

import pytest
from PIL import Image

from penpath.core.image.separate import palette_match
from penpath.core.models import Pen

RED = Pen(name="red", width_mm=0.4, color="#FF0000")
BLUE = Pen(name="blue", width_mm=0.4, color="#0000FF")
WHITE = Pen(name="paper", width_mm=0.4, color="#FFFFFF")


def _region_image(size: int = 30) -> Image.Image:
    image = Image.new("RGB", (size, size), "white")
    for y in range(2, 13):
        for x in range(2, 13):
            image.putpixel((x, y), (255, 0, 0))
    for y in range(16, 27):
        for x in range(16, 27):
            image.putpixel((x, y), (0, 0, 255))
    image.putpixel((0, 0), (255, 0, 0))
    return image


def test_palette_match_counts_inked_pixels_and_unassigned_specks() -> None:
    image = _region_image()
    total = image.width * image.height

    result = palette_match(image, [RED, BLUE, WHITE])

    assert (result.width, result.height) == (30, 30)
    assert [row.order for row in result.rows] == [1, 2, 3]
    assert [row.name for row in result.rows] == ["red", "blue", "paper"]
    assert [row.color for row in result.rows] == ["#FF0000", "#0000FF", "#FFFFFF"]
    assert [row.pixels for row in result.rows] == [121, 121, 0]
    assert result.rows[0].percent == pytest.approx(100 * 121 / total)
    assert result.rows[2].percent == 0
    assert result.unassigned_pixels == total - 242
    assert result.unassigned_percent == pytest.approx(100 * (total - 242) / total)
    shares = [row.percent for row in result.rows] + [result.unassigned_percent]
    assert sum(shares) == pytest.approx(100.0)


def test_palette_match_single_pen_counts_all_non_white_pixels() -> None:
    image = Image.new("RGB", (10, 10), "white")
    for y in range(4):
        for x in range(4):
            image.putpixel((x, y), (0, 0, 0))

    result = palette_match(image, [BLUE])

    assert [row.pixels for row in result.rows] == [16]
    assert result.rows[0].percent == pytest.approx(16.0)
    assert result.unassigned_pixels == 84
    assert result.unassigned_percent == pytest.approx(84.0)


def test_palette_match_empty_palette_raises() -> None:
    with pytest.raises(ValueError, match="at least one pen"):
        palette_match(_region_image(), [])
