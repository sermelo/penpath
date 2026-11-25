"""Split a colour image into one greyscale image per palette pen.

Call this on the loaded colour image, before the filter pipeline: the caller
splits first and filters second. Applying the default ``grayscale`` filter
before the split destroys the colour information needed to choose a pen.

Each pixel goes to the pen whose colour is nearest in CIE Lab space. A pen's
image is full size, white everywhere except that pen's pixels, which keep
their luminance, so the drawing algorithm sees the same geometry as before.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageColor
from skimage.color import rgb2lab

from penpath.core.image.filters import grayscale
from penpath.core.models import Pen


def _pen_rgb(pen: Pen) -> NDArray[np.float32]:
    """Return a pen's colour as float RGB in [0, 1]."""
    try:
        color = ImageColor.getrgb(pen.color)
    except ValueError as exc:
        raise ValueError(f"Pen {pen.name!r} has invalid colour {pen.color!r}") from exc
    return (np.asarray(color[:3], dtype=np.float32) / 255.0).astype(np.float32)


def separate_palette(
    image: Image.Image,
    pens: list[Pen],
) -> list[tuple[Pen, Image.Image]]:
    """Split a colour image into one full-size greyscale image per pen.

    Parameters
    ----------
    image : PIL.Image.Image
        Loaded colour image, before any filter has converted it to greyscale.
    pens : list[Pen]
        Pens in drawing order; the returned images follow the same order.

    Returns
    -------
    list[tuple[Pen, Image.Image]]
        One ``L``-mode image per pen, in the given pen order. Each image holds
        the luminance of the pixels assigned to that pen and white elsewhere.

    Raises
    ------
    ValueError
        If the image has no pixels, the palette is empty, or a pen colour
        cannot be parsed.
    """
    if not pens:
        raise ValueError("separate_palette needs at least one pen")
    if image.width == 0 or image.height == 0:
        raise ValueError("separate_palette needs an image with at least one pixel")

    rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    luminance = np.asarray(grayscale(image), dtype=np.uint8)
    image_lab = rgb2lab(rgb.astype(np.float32) / 255.0)
    palette_lab = rgb2lab(np.stack([_pen_rgb(pen) for pen in pens]))

    squared_distances = np.stack(
        [np.sum((image_lab - colour) ** 2, axis=-1) for colour in palette_lab],
        axis=-1,
    )
    nearest = np.argmin(squared_distances, axis=-1)

    separated: list[tuple[Pen, Image.Image]] = []
    for index, pen in enumerate(pens):
        channel = np.where(nearest == index, luminance, 255).astype(np.uint8)
        separated.append((pen, Image.fromarray(channel)))
    return separated


__all__ = ["separate_palette"]
