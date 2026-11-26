"""Split a colour image into one greyscale image per palette pen.

Call this on the loaded colour image, before the filter pipeline: the caller
splits first and filters second. Applying the default ``grayscale`` filter
before the split destroys the colour information needed to choose a pen.

Each pixel goes to the pen whose colour is nearest in CIE Lab space, with one
change: a chromatic pixel is matched by circular hue angle first, using chroma
and lightness only as tie-breakers, so a muted green field picks a green pen
instead of collapsing to a pale blue or a neutral grey. Near-neutral pixels
keep the plain Lab assignment, so paper, pale greys and dark neutral pencil
strokes behave exactly as before. Neutral pens are not candidates for
chromatic pixels, so black cannot steal a saturated colour just because its
chroma is zero. A pen's image is full size, white everywhere except that
pen's pixels, which keep their luminance, so the drawing algorithm sees the
same geometry as before. A pen's assignment must form a connected region of
at least eight pixels; smaller specks are left white so a pen does not chase
single pixels a stroke cannot follow. Every pixel reaches the only pen when
the palette has one entry.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageColor
from skimage.color import rgb2lab
from skimage.measure import label

from penpath.core.image.filters import grayscale
from penpath.core.models import Pen

_MIN_REGION_PIXELS = 8
_NEUTRAL_CHROMA = 8.0
_HUE_WEIGHT = 1.0
_CHROMA_WEIGHT = 0.15
_LIGHTNESS_WEIGHT = 0.02


def _assign_pens(
    image_lab: NDArray[np.float32],
    palette_lab: NDArray[np.float32],
) -> NDArray[np.intp]:
    """Return the winning pen index for each pixel of a CIE Lab image.

    Chromatic pixels are ranked by circular hue difference from ``atan2(b, a)``;
    chroma and lightness break ties, with lightness carrying far less weight
    than either. Near-neutral pixels keep the old nearest-in-Lab rule and may
    still choose a neutral pen.
    """
    pixel_l, pixel_a, pixel_b = (
        image_lab[..., 0],
        image_lab[..., 1],
        image_lab[..., 2],
    )
    pixel_chroma = np.hypot(pixel_a, pixel_b)
    pixel_hue = np.degrees(np.arctan2(pixel_b, pixel_a))
    near_neutral = pixel_chroma < _NEUTRAL_CHROMA

    pen_l = palette_lab[:, 0]
    pen_a = palette_lab[:, 1]
    pen_b = palette_lab[:, 2]
    pen_chroma = np.hypot(pen_a, pen_b)
    pen_hue = np.degrees(np.arctan2(pen_b, pen_a))

    shape = pixel_l.shape
    best_lab = np.full(shape, np.inf, dtype=np.float32)
    best_lab_index = np.zeros(shape, dtype=np.intp)
    best_hue = np.full(shape, np.inf, dtype=np.float32)
    best_hue_index = np.zeros(shape, dtype=np.intp)
    chromatic_pens = 0

    for index in range(len(palette_lab)):
        lightness_gap = pixel_l - pen_l[index]
        lab_distance = (
            lightness_gap**2 + (pixel_a - pen_a[index]) ** 2 + (pixel_b - pen_b[index]) ** 2
        )
        lab_wins = lab_distance < best_lab
        best_lab = np.where(lab_wins, lab_distance, best_lab)
        best_lab_index = np.where(lab_wins, index, best_lab_index)

        if pen_chroma[index] < _NEUTRAL_CHROMA:
            continue
        chromatic_pens += 1
        raw_hue_gap = np.abs(pixel_hue - pen_hue[index])
        hue_gap = np.minimum(raw_hue_gap, 360.0 - raw_hue_gap)
        hue_distance = (
            (_HUE_WEIGHT * hue_gap) ** 2
            + (_CHROMA_WEIGHT * (pixel_chroma - pen_chroma[index])) ** 2
            + (_LIGHTNESS_WEIGHT * lightness_gap) ** 2
        )
        hue_wins = hue_distance < best_hue
        best_hue = np.where(hue_wins, hue_distance, best_hue)
        best_hue_index = np.where(hue_wins, index, best_hue_index)

    if chromatic_pens == 0:
        return best_lab_index
    return np.where(near_neutral, best_lab_index, best_hue_index)


@dataclass(frozen=True)
class PalettePenShare:
    """The share of an image inked by one palette pen."""

    order: int
    name: str
    color: str
    pixels: int
    percent: float


@dataclass(frozen=True)
class PaletteMatch:
    """Raw palette separation measurements for one image, before drawing."""

    width: int
    height: int
    rows: list[PalettePenShare]
    unassigned_pixels: int
    unassigned_percent: float


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
        A pixel assigned to a connected region smaller than eight pixels is
        left white, so isolated specks do not become a pen's region.

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

    luminance = np.asarray(grayscale(image), dtype=np.uint8)
    if len(pens) == 1:
        _pen_rgb(pens[0])
        return [(pens[0], Image.fromarray(luminance))]

    rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    image_lab = rgb2lab(rgb.astype(np.float32) / 255.0)
    palette_lab = rgb2lab(np.stack([_pen_rgb(pen) for pen in pens]))
    nearest = _assign_pens(image_lab, palette_lab)
    keep = np.zeros(nearest.shape, dtype=bool)
    for index in range(len(pens)):
        components = label(nearest == index)  # type: ignore[no-untyped-call]
        sizes = np.bincount(components.ravel())
        sizes[0] = 0
        keep |= sizes[components] >= _MIN_REGION_PIXELS
    nearest = np.where(keep, nearest, -1)

    separated: list[tuple[Pen, Image.Image]] = []
    for index, pen in enumerate(pens):
        channel = np.where(nearest == index, luminance, 255).astype(np.uint8)
        separated.append((pen, Image.fromarray(channel)))
    return separated


def palette_match(image: Image.Image, pens: list[Pen]) -> PaletteMatch:
    """Measure how many pixels raw palette separation gives to each pen.

    The measurement uses ``separate_palette`` on the loaded image as it is: no
    filters, background masking or saturation boost is applied, and nothing is
    drawn. A pen inks the pixels below 255 in its separated layer. Pixels no
    layer inks are paper pixels (white in every layer) plus pixels in connected
    regions smaller than eight pixels, which the separation drops as specks.

    Parameters
    ----------
    image : PIL.Image.Image
        Loaded colour image, before any conversion to greyscale.
    pens : list[Pen]
        Pens in drawing order; the returned rows follow the same order,
        including pens that inked no pixels.

    Returns
    -------
    PaletteMatch
        Image size, one row per pen with a pixel count and its percentage of
        all image pixels, and the unassigned count and percentage. Percentages
        are full precision; rows plus the unassigned share add to 100.

    Raises
    ------
    ValueError
        If the image has no pixels, the palette is empty, or a pen colour
        cannot be parsed.
    """
    total_pixels = image.width * image.height
    rows: list[PalettePenShare] = []
    inked_pixels = 0
    for order, (pen, layer) in enumerate(separate_palette(image, pens), start=1):
        pixels = int(np.count_nonzero(np.asarray(layer) < 255))
        inked_pixels += pixels
        rows.append(
            PalettePenShare(
                order=order,
                name=pen.name,
                color=pen.color,
                pixels=pixels,
                percent=100.0 * pixels / total_pixels,
            )
        )
    unassigned_pixels = total_pixels - inked_pixels
    return PaletteMatch(
        width=image.width,
        height=image.height,
        rows=rows,
        unassigned_pixels=unassigned_pixels,
        unassigned_percent=100.0 * unassigned_pixels / total_pixels,
    )


__all__ = ["PaletteMatch", "PalettePenShare", "palette_match", "separate_palette"]
