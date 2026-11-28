"""Tests for the equalize and clahe filters."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from penpath.core.image.filters import clahe, equalize
from penpath.core.image.pipeline import get_filter


def _flat_ramp(mode: str = "L") -> Image.Image:
    row = np.linspace(110, 150, 120)
    image = Image.fromarray(np.tile(row, (60, 1)).astype(np.uint8))
    return image.convert(mode)


def test_equalize_spreads_a_flat_image() -> None:
    values = np.asarray(equalize(_flat_ramp()))
    assert values.max() - values.min() > 200


def test_equalize_keeps_colour_and_mode() -> None:
    image = Image.new("RGB", (40, 20), (200, 40, 40))
    image.paste((120, 20, 20), (0, 0, 20, 20))
    result = equalize(image)
    assert result.mode == "RGB"
    red, green, blue = np.asarray(result).reshape(-1, 3).mean(axis=0)
    assert red > green and red > blue  # still red


def test_clahe_raises_local_contrast() -> None:
    before = np.asarray(_flat_ramp(), dtype=float)
    after = np.asarray(clahe(_flat_ramp(), clip_limit=0.03), dtype=float)
    assert after.std() > before.std()


def test_clahe_keeps_alpha() -> None:
    result = clahe(_flat_ramp("RGBA"))
    assert result.mode == "RGBA"
    assert np.asarray(result)[:, :, 3].min() == 255


@pytest.mark.parametrize(("clip", "tiles"), [(0.0, 8), (1.5, 8), (0.01, 1), (0.01, 100)])
def test_clahe_rejects_bad_settings(clip: float, tiles: int) -> None:
    with pytest.raises(ValueError):
        clahe(_flat_ramp(), clip_limit=clip, tiles=tiles)


def test_filters_are_registered() -> None:
    assert get_filter("equalize") is equalize
    assert get_filter("clahe") is clahe
