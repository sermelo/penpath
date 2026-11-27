"""Unit tests for the pure measurement helpers of the Sketch Squares gate."""

from __future__ import annotations

import numpy as np
from PIL import Image
from sketch_squares_gate import dark_region_mask, readability

_PLACEMENT = (10.0, 20.0, 100.0, 50.0)


def test_dark_region_mask_rejects_ink_far_from_dark_pixels() -> None:
    """Only source-dark pixels and their tolerance neighbourhood are supported."""
    source = Image.new("L", (8, 8), 255)
    for row in range(2, 4):
        for column in range(2, 4):
            source.putpixel((column, row), 0)

    exact = dark_region_mask(source, tolerance_px=0)
    assert exact.sum() == 4
    assert bool(exact[2, 2]) and not bool(exact[7, 7])

    dilated = dark_region_mask(source, tolerance_px=1)
    assert dilated.sum() > exact.sum()
    assert bool(dilated[1, 3]) and not bool(dilated[7, 7])


def test_readability_scores_zero_for_a_blank_page() -> None:
    """A plot with no ink and no stroke points cannot pass the readability gate."""
    plot = Image.new("RGB", (440, 280), "white")
    source = Image.new("RGB", (8, 8), "black")
    values = readability(plot, source, _PLACEMENT, [])
    assert values.dark_recall == 0.0
    assert values.ink_precision == 0.0
    assert values.coverage_width == 0.0
    assert values.coverage_height == 0.0
    assert values.coverage_area == 0.0


def test_readability_rewards_ink_on_dark_source_areas() -> None:
    """Ink over the dark half scores recall and precision; the light half does not."""
    source = Image.new("RGB", (8, 8), "white")
    for row in range(8):
        for column in range(4):
            source.putpixel((column, row), (0, 0, 0))

    crop_left = round(_PLACEMENT[0] * 96 / 25.4)
    crop_top = round(_PLACEMENT[1] * 96 / 25.4)
    crop_width = round(_PLACEMENT[2] * 96 / 25.4)
    crop_height = round(_PLACEMENT[3] * 96 / 25.4)
    dark_plot = Image.new("RGB", (crop_left + crop_width + 4, crop_top + crop_height + 4), "white")
    dark_plot.paste(
        Image.new("RGB", (crop_width // 2, crop_height), "black"),
        (crop_left, crop_top),
    )
    points = [(10.0, 20.0), (60.0, 70.0)]
    values = readability(dark_plot, source, _PLACEMENT, points)
    assert values.dark_recall > 0.4
    assert values.ink_precision > 0.9
    assert values.coverage_width == 0.5
    assert values.coverage_height == 1.0

    light_plot = Image.new("RGB", (crop_left + crop_width + 4, crop_top + crop_height + 4), "white")
    light_plot.paste(
        Image.new("RGB", (crop_width // 2, crop_height), "black"),
        (crop_left + crop_width // 2, crop_top),
    )
    light_values = readability(light_plot, source, _PLACEMENT, points)
    assert light_values.ink_precision < 0.1
    assert not np.isnan(light_values.dark_recall)
