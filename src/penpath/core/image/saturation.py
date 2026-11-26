"""Boost the chroma of a working image before palette separation.

A muted photo can be so close to neutral that every pixel lands on a dark or
light grey pen, even though a colour pen would describe it better. Boosting
scales CIE Lab a* and b* only: L* is kept, so tones and the ink density the PFM
sees do not change. The boost runs after background masking and auto
equalization, on the working image, before :func:`separate_palette`.

:func:`boost_saturation` is the manual path. :func:`adapt_saturation` chooses a
factor from the image and the palette: a muted image is stretched until its
90th-percentile chroma of non-background pixels reaches the palette's median
chroma, capped at 3.0, and an already-saturated image gets 1.0. Background
pixels are the pure white ones left by masking, so paper never drives the
factor. The palette's median rather than its brightest pen keeps the estimate
stable when a single pen is unusually vivid.
"""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageColor
from skimage.color import lab2rgb, rgb2lab

from penpath.core.models import Pen

NO_BOOST_FACTOR = 1.0
_ADAPT_PERCENTILE = 90.0
_MIN_ADAPT_FACTOR = 1.0
_MAX_ADAPT_FACTOR = 3.0


def _check_factor(factor: float) -> None:
    """Reject negative, NaN and infinite boost factors."""
    if not math.isfinite(factor) or factor < 0.0:
        raise ValueError("saturation factor must be a finite, non-negative number")


def _pen_rgb(pen: Pen) -> NDArray[np.float32]:
    """Return a pen's colour as float RGB in [0, 1]."""
    try:
        color = ImageColor.getrgb(pen.color)
    except ValueError as exc:
        raise ValueError(f"Pen {pen.name!r} has invalid colour {pen.color!r}") from exc
    return (np.asarray(color[:3], dtype=np.float32) / 255.0).astype(np.float32)


def boost_saturation(image: Image.Image, factor: float) -> Image.Image:
    """Scale CIE Lab chroma by ``factor`` without changing lightness.

    Parameters
    ----------
    image : PIL.Image.Image
        Working colour image, after masking and equalization.
    factor : float
        Multiplier for a* and b*. ``1.0`` is a no-op, ``0.0`` makes the image
        neutral. Must be finite and non-negative.

    Returns
    -------
    PIL.Image.Image
        Image in the input mode (alpha, when present, copied unchanged), with
        sRGB values clamped to [0, 255] after the round trip. At ``factor=1.0``
        a byte-identical copy of the input is returned without a colour
        conversion.

    Raises
    ------
    ValueError
        If ``factor`` is negative, NaN or infinite.
    """
    _check_factor(factor)
    if factor == NO_BOOST_FACTOR:
        return image.copy()

    rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    lab = rgb2lab(rgba[..., :3].astype(np.float32) / 255.0)
    lab[..., 1] *= factor
    lab[..., 2] *= factor
    rgb = np.clip(np.rint(lab2rgb(lab) * 255.0), 0, 255).astype(np.uint8)

    if "A" in image.getbands():
        return Image.fromarray(np.dstack((rgb, rgba[..., 3:4])))
    return Image.fromarray(rgb)


def adapt_saturation(image: Image.Image, pens: list[Pen]) -> float:
    """Choose a chroma boost that brings non-background ink up to the palette.

    The target is the median CIE Lab chroma of the palette's pen colours; the
    measured value is the 90th percentile chroma of pixels that are not pure
    white. The ratio is clamped to [1.0, 3.0], so an already-saturated image
    returns 1.0 and a neutral one cannot be amplified without bound.

    Parameters
    ----------
    image : PIL.Image.Image
        Working colour image after background masking: paper is pure white.
    pens : list[Pen]
        Palette pens, used for their colours only; order does not matter.

    Returns
    -------
    float
        Factor in [1.0, 3.0] to pass to :func:`boost_saturation`.

    Raises
    ------
    ValueError
        If the palette is empty, the image has no pixels, or a pen colour
        cannot be parsed.
    """
    if not pens:
        raise ValueError("adapt_saturation needs at least one pen")
    if image.width == 0 or image.height == 0:
        raise ValueError("adapt_saturation needs an image with at least one pixel")

    rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    lab = rgb2lab(rgb.astype(np.float32) / 255.0)
    chroma = np.hypot(lab[..., 1], lab[..., 2])
    ink = np.any(rgb != 255, axis=-1)
    if not np.any(ink):
        return 1.0

    measured = float(np.percentile(chroma[ink], _ADAPT_PERCENTILE))
    palette_lab = rgb2lab(np.stack([_pen_rgb(pen) for pen in pens]))
    target = float(np.median(np.hypot(palette_lab[:, 1], palette_lab[:, 2])))
    if measured <= 0.0 or target <= measured:
        return 1.0
    return float(np.clip(target / measured, _MIN_ADAPT_FACTOR, _MAX_ADAPT_FACTOR))


__all__ = ["NO_BOOST_FACTOR", "adapt_saturation", "boost_saturation"]
