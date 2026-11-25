"""Unit tests for the pure measurement helpers of the Sketch Lines gate."""

from __future__ import annotations

import numpy as np
from PIL import Image
from sketch_lines_gate import (
    INK_CUTOFF,
    PX_PER_MM,
    coverage_fractions,
    ink_mask,
    ink_spread,
    make_ideal_plot,
    placement_crop,
    tone_metrics,
)


def test_placement_crop_rounds_and_clamps_like_likeness() -> None:
    """The crop used for ink measures matches compute_likeness's placement crop."""
    assert placement_crop((400, 400), (10, 20, 50, 40), px_per_mm=1.0) == (10, 20, 60, 60)
    assert placement_crop((30, 30), (20, 20, 50, 50), px_per_mm=1.0) == (20, 20, 30, 30)


def test_coverage_fractions_for_full_quarter_and_empty() -> None:
    """Coverage reports the clipped bounding box of the stroke points."""
    placement = (0.0, 0.0, 100.0, 50.0)
    assert coverage_fractions([(0, 0), (100, 50)], placement) == (1.0, 1.0, 1.0)
    assert coverage_fractions([(0, 0), (50, 25)], placement) == (0.5, 0.5, 0.25)
    assert coverage_fractions([], placement) == (0.0, 0.0, 0.0)
    assert coverage_fractions([(-10, -10), (200, 100)], placement) == (1.0, 1.0, 1.0)


def test_ink_spread_detects_a_single_corner() -> None:
    """All ink in one cell gives min 0 and max 1; uniform ink gives equal shares."""
    corner = np.zeros((16, 16), dtype=bool)
    corner[:4, :4] = True
    assert ink_spread(corner) == (0.0, 1.0)

    uniform = np.ones((16, 16), dtype=bool)
    minimum, maximum = ink_spread(uniform)
    assert minimum == maximum == 1 / 16


def test_ink_mask_uses_the_pen_cutoff() -> None:
    """Only pixels darker than halfway between pen and paper count as ink."""
    plot = Image.new("RGB", (4, 4), "white")
    plot.putpixel((0, 0), (INK_CUTOFF - 1, INK_CUTOFF - 1, INK_CUTOFF - 1))
    plot.putpixel((1, 1), (INK_CUTOFF + 1, INK_CUTOFF + 1, INK_CUTOFF + 1))
    mask = ink_mask(plot, (0, 0, 4, 4))
    assert bool(mask[0, 0])
    assert not bool(mask[1, 1])


def test_tone_metrics_favours_dark_pixels_and_stays_finite() -> None:
    """Ink in the dark quarter raises the ratio; a blank page gives 1.0."""
    original = Image.new("L", (16, 16), 255)
    for column in range(4):
        for row in range(16):
            original.putpixel((column, row), 0)
    mask = np.zeros((16, 16), dtype=bool)
    mask[:, :4] = True

    dark, light, ratio = tone_metrics(mask, original)
    assert dark == 1.0
    assert light == 0.0
    assert ratio > 1.0

    blank = np.zeros((16, 16), dtype=bool)
    assert tone_metrics(blank, original)[2] == 1.0


def test_ideal_plot_uses_only_pen_ink_levels() -> None:
    """The ideal drawing contains pure pen black and paper white pixels."""
    original = Image.new("L", (32, 32))
    for column in range(16):
        for row in range(32):
            original.putpixel((column, row), 0)
    side = 100
    placement = (0.0, 0.0, side / PX_PER_MM, side / PX_PER_MM)
    ideal = make_ideal_plot(original, (side, side), placement)

    assert ideal.size == (side, side)
    assert set(ideal.convert("L").getdata()) <= {0, 255}
