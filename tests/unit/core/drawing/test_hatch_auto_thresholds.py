"""Tests for Hatch's photo-adaptive thresholds (``auto_thresholds``)."""

from __future__ import annotations

import itertools
import math

import numpy as np
import pytest
from PIL import Image

from penpath.core.drawing.pfm_hatch import HatchSettings, adaptive_thresholds, hatch_strokes


def _ramp(lo: int, hi: int) -> Image.Image:
    """A horizontal grey ramp from luminance ``lo`` to ``hi``."""
    row = np.linspace(lo, hi, 160)
    return Image.fromarray(np.tile(row, (80, 1)).astype(np.uint8))


def _angles_drawn(lines: list) -> set[int]:
    angles = set()
    for line in lines:
        (ax, ay), (bx, by) = line.coords[0], line.coords[-1]
        angles.add(round(math.degrees(math.atan2(by - ay, bx - ax))) % 180)
    return angles


def test_maps_thresholds_into_the_image_range() -> None:
    darkness = np.linspace(0.3, 0.5, 1000)
    fitted = adaptive_thresholds(darkness, (0.25, 0.5, 0.75))
    lo, hi = np.percentile(darkness, [2, 98])
    assert fitted == pytest.approx(
        (lo + 0.25 * (hi - lo), lo + 0.5 * (hi - lo), lo + 0.75 * (hi - lo))
    )


def test_ignores_white_paper() -> None:
    darkness = np.concatenate((np.zeros(10000), np.linspace(0.3, 0.5, 100)))
    fitted = adaptive_thresholds(darkness, (0.5,))
    assert 0.38 < fitted[0] < 0.42


def test_blank_or_flat_image_keeps_thresholds() -> None:
    assert adaptive_thresholds(np.zeros(100), (0.2, 0.4)) == (0.2, 0.4)
    assert adaptive_thresholds(np.full(100, 0.5), (0.2, 0.4)) == (0.2, 0.4)


def test_results_stay_increasing_and_inside_unit_interval() -> None:
    fitted = adaptive_thresholds(np.linspace(0.0, 1.0, 1000), (0.01, 0.02, 0.99))
    assert all(0.0 < v < 1.0 for v in fitted)
    assert all(b > a for a, b in itertools.pairwise(fitted))


def test_low_contrast_photo_uses_every_band() -> None:
    image = _ramp(120, 160)  # darkness 0.37 - 0.53: only two default bands fire
    fixed = hatch_strokes(image, HatchSettings(seed=1), 4.0, 0.3)
    fitted = hatch_strokes(image, HatchSettings(seed=1, auto_thresholds=True), 4.0, 0.3)
    assert len(_angles_drawn(fixed)) == 2
    assert len(_angles_drawn(fitted)) == 4


def test_off_by_default() -> None:
    assert HatchSettings().auto_thresholds is False
