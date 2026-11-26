"""Detect paper colour and mask paper-level pixels before palette separation.

Paper is estimated from the median colour of a thin border ring: a real page
usually reaches the image edge, so a dark drawing or a pale sky in the middle
cannot move a median that is taken from the outside of the frame. The ring is
5% of the longer side (at least one pixel, at most 16), and the median is taken
per channel, so up to half of the border can be covered by ink before the
estimate changes. If that border median is dark (CIE Lab L* below 60), the
image is treated as full bleed and the median of the lightest 10% of pixels is
used instead, provided that cluster is near-neutral (CIE Lab C* at most 25).
A saturated full-bleed colour keeps the border median rather than losing one
of its own colour regions.

A pixel is paper when its CIE Lab distance (CIE76, D65) from the detected
colour is at most ``DEFAULT_BACKGROUND_THRESHOLD``. Masked pixels become pure
white in the colour image; because white has luminance 255, every subsequent
palette channel is white there too, so no pen can draw paper.

Limits: the border heuristic needs paper at the edge or a light subject; it
cannot recover paper colour from a fully inked frame that is uniformly dark.
The threshold is tuned for scanned pencil sketches, not for coloured paper
with large tone variation. Pass ``paper_color`` and ``threshold`` explicitly
to override either estimate.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageColor
from skimage.color import rgb2lab

DEFAULT_BACKGROUND_THRESHOLD = 10.0
_BORDER_FRACTION = 0.05
_MIN_BORDER_PX = 1
_MAX_BORDER_PX = 16
_DARK_BORDER_LIGHTNESS = 60.0
_LIGHT_CLUSTER_PERCENTILE = 90.0
_MAX_PAPER_CHROMA = 25.0


@dataclass(frozen=True)
class BackgroundResult:
    """The masked image and the measurements taken while masking it.

    Attributes
    ----------
    image : PIL.Image.Image
        RGB image with paper-level pixels set to pure white.
    paper_color : str
        Colour used as paper, as ``#RRGGBB``.
    masked_percent : float
        Percentage of pixels turned to no ink, in [0, 100].
    """

    image: Image.Image
    paper_color: str
    masked_percent: float


def _border_pixels(rgb: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """Return the pixels in a thin ring around the image border."""
    height, width = rgb.shape[:2]
    ring = max(_MIN_BORDER_PX, min(_MAX_BORDER_PX, round(max(height, width) * _BORDER_FRACTION)))
    ring = min(ring, max(1, height // 2), max(1, width // 2))
    border = np.zeros((height, width), dtype=bool)
    border[:ring, :] = True
    border[-ring:, :] = True
    border[:, :ring] = True
    border[:, -ring:] = True
    return rgb[border]


def _to_hex(rgb: NDArray[np.floating]) -> str:
    """Return a float RGB triple as an uppercase ``#RRGGBB`` string."""
    channels = np.clip(np.rint(rgb), 0, 255).astype(int)
    return f"#{channels[0]:02X}{channels[1]:02X}{channels[2]:02X}"


def detect_paper_color(image: Image.Image) -> str:
    """Estimate the paper colour of a loaded colour image.

    Parameters
    ----------
    image : PIL.Image.Image
        Loaded image; alpha, when present, is ignored.

    Returns
    -------
    str
        Estimated paper colour as ``#RRGGBB``.

    Raises
    ------
    ValueError
        If the image has no pixels.
    """
    rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    if rgb.size == 0:
        raise ValueError("detect_paper_color needs an image with at least one pixel")

    paper_rgb = np.median(_border_pixels(rgb), axis=0)
    border_lab = rgb2lab(paper_rgb.reshape(1, 1, 3).astype(np.float32) / 255.0)
    if float(border_lab[0, 0, 0]) < _DARK_BORDER_LIGHTNESS:
        image_lab = rgb2lab(rgb.astype(np.float32) / 255.0)
        lightness = image_lab[..., 0]
        light = lightness >= np.percentile(lightness, _LIGHT_CLUSTER_PERCENTILE)
        chroma = np.hypot(image_lab[..., 1], image_lab[..., 2])
        neutral_light = light & (chroma <= _MAX_PAPER_CHROMA)
        if np.any(neutral_light):
            paper_rgb = np.median(rgb[neutral_light], axis=0)
    return _to_hex(paper_rgb)


def _parse_paper_color(paper_color: str) -> NDArray[np.uint8]:
    """Parse a paper colour given as hex or a CSS colour name."""
    try:
        color = ImageColor.getrgb(paper_color)
    except ValueError as exc:
        raise ValueError(
            f"Invalid paper colour {paper_color!r}: use '#RRGGBB' or a CSS colour name"
        ) from exc
    return np.asarray(color[:3], dtype=np.uint8)


def _background_mask(
    rgb: NDArray[np.uint8], paper_rgb: NDArray[np.uint8], threshold: float
) -> NDArray[np.bool_]:
    """Return the boolean mask of pixels within ``threshold`` of paper in Lab."""
    if not np.isfinite(threshold) or threshold < 0:
        raise ValueError("background threshold must be a finite, non-negative Lab distance")
    image_lab = rgb2lab(rgb.astype(np.float32) / 255.0)
    paper_lab = rgb2lab(paper_rgb.reshape(1, 1, 3).astype(np.float32) / 255.0)
    distance: NDArray[np.float32] = np.linalg.norm(image_lab - paper_lab, axis=-1)
    mask: NDArray[np.bool_] = distance <= threshold
    return mask


def mask_background(
    image: Image.Image,
    *,
    paper_color: str | None = None,
    threshold: float = DEFAULT_BACKGROUND_THRESHOLD,
) -> BackgroundResult:
    """Turn paper-level pixels white and report the colour and masked area.

    Parameters
    ----------
    image : PIL.Image.Image
        Loaded colour image, after downscaling and auto equalization.
    paper_color : str | None, optional
        Paper colour as ``#RRGGBB`` or a CSS colour name. When omitted, it is
        detected with :func:`detect_paper_color`.
    threshold : float, optional
        Maximum CIE76 Delta-E distance from the paper colour treated as no ink.

    Returns
    -------
    BackgroundResult
        RGB image with paper set to white, the colour used, and the masked
        percentage of pixels.

    Raises
    ------
    ValueError
        If the image has no pixels, the colour cannot be parsed, or the
        threshold is negative or not finite.
    """
    rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    if rgb.size == 0:
        raise ValueError("mask_background needs an image with at least one pixel")

    paper = detect_paper_color(image) if paper_color is None else paper_color
    mask = _background_mask(rgb, _parse_paper_color(paper), threshold)
    output = rgb.copy()
    output[mask] = 255
    return BackgroundResult(
        image=Image.fromarray(output),
        paper_color=paper,
        masked_percent=float(mask.mean() * 100.0),
    )


def remove_background(
    image: Image.Image,
    *,
    paper_color: str | None = None,
    threshold: float = DEFAULT_BACKGROUND_THRESHOLD,
) -> Image.Image:
    """Set pixels close to the paper colour to pure white.

    Parameters
    ----------
    image : PIL.Image.Image
        Loaded colour image; drawing pixels are copied unchanged.
    paper_color : str | None, optional
        Paper colour as ``#RRGGBB`` or a CSS colour name; auto-detected when
        omitted.
    threshold : float, optional
        Maximum CIE76 Delta-E distance from paper treated as no ink.

    Returns
    -------
    PIL.Image.Image
        RGB image with paper-level pixels white and all other pixels unchanged.
    """
    return mask_background(image, paper_color=paper_color, threshold=threshold).image


__all__ = [
    "DEFAULT_BACKGROUND_THRESHOLD",
    "BackgroundResult",
    "detect_paper_color",
    "mask_background",
    "remove_background",
]
