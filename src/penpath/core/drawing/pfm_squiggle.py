"""Squiggle PFM: rows of wavy lines whose waves follow the image's darkness.

Like "Squiggle Draw": parallel rows (horizontal by default) run across the
image, and each row is a wave whose amplitude and frequency grow with the
local darkness, so dark areas get tall, tight waves (more ink) and light
areas nearly straight lines. Each row is one stroke, so the plot is fast and
has few pen lifts.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, Field
from shapely import LineString
from shapely.geometry import box
from skimage.filters import gaussian

if TYPE_CHECKING:
    from PIL import Image


class SquiggleSettings(BaseModel):
    """Settings for the Squiggle PFM.

    Lengths are in millimetres on paper; the image scale is passed to
    :func:`squiggle_strokes`.

    Parameters
    ----------
    line_spacing : float
        Distance between rows in millimetres (> 0). Default 2.0.
    angle : float
        Row direction in degrees (-360 - 360); 0 is horizontal. Default 0.0.
    max_amplitude : float
        Wave height at full black as a fraction of half the row spacing
        (0 - 1.5); above 1 neighbouring rows may touch. Default 0.9.
    min_frequency : float
        Waves per millimetre at the lightest drawn tone (>= 0). Default 0.2.
    max_frequency : float
        Waves per millimetre at full black (>= ``min_frequency``). Never
        denser than one wave per two pen widths. Default 1.5.
    tone_gamma : float
        Exponent applied to darkness ``1 - L/255`` (> 0); above 1 keeps
        mid-tones calmer. Default 1.2.
    min_tone : float
        Darkness below which a row is a straight line (0 - 1). Default 0.05.
    skip_white : bool
        Lift the pen over areas lighter than ``min_tone`` instead of drawing
        a straight line through them; splits rows into several strokes.
        Default False.
    serpentine : bool
        Draw every other row in the opposite direction, so the next row
        starts near where the last one ended. Default True.
    seed : int | None
        Accepted for symmetry with the other PFMs; the algorithm is
        deterministic. Default None.
    """

    line_spacing: float = Field(default=2.0, gt=0.0)
    angle: float = Field(default=0.0, ge=-360.0, le=360.0)
    max_amplitude: float = Field(default=0.9, ge=0.0, le=1.5)
    min_frequency: float = Field(default=0.2, ge=0.0)
    max_frequency: float = Field(default=1.5, ge=0.0)
    tone_gamma: float = Field(default=1.2, gt=0.0)
    min_tone: float = Field(default=0.05, ge=0.0, le=1.0)
    skip_white: bool = False
    serpentine: bool = True
    seed: int | None = None

    def model_post_init(self, __context: object) -> None:
        """Check the frequency range."""
        if self.max_frequency < self.min_frequency:
            raise ValueError("max_frequency must be >= min_frequency")


def _bilinear(
    values: NDArray[np.float64], xs: NDArray[np.float64], ys: NDArray[np.float64]
) -> NDArray[np.float64]:
    """Bilinear samples of ``values`` at pixel coordinates (clamped)."""
    height, width = values.shape
    xs = np.clip(xs, 0.0, width - 1.0)
    ys = np.clip(ys, 0.0, height - 1.0)
    x0 = np.minimum(np.floor(xs).astype(np.int64), width - 2 if width > 1 else 0)
    y0 = np.minimum(np.floor(ys).astype(np.int64), height - 2 if height > 1 else 0)
    x1 = np.minimum(x0 + 1, width - 1)
    y1 = np.minimum(y0 + 1, height - 1)
    fx, fy = xs - x0, ys - y0
    top = values[y0, x0] * (1 - fx) + values[y0, x1] * fx
    bottom = values[y1, x0] * (1 - fx) + values[y1, x1] * fx
    return np.asarray(top * (1 - fy) + bottom * fy, dtype=np.float64)


def squiggle_strokes(
    image: Image.Image,
    settings: SquiggleSettings,
    pixels_per_mm: float,
    pen_width_mm: float,
) -> list[LineString]:
    """Draw the image as rows of waves whose height and frequency follow darkness.

    Parameters
    ----------
    image : PIL.Image.Image
        Input image (any mode, converted to greyscale).
    settings : SquiggleSettings
        Algorithm configuration, in millimetres on paper.
    pixels_per_mm : float
        Working-image pixels per paper millimetre. Must be positive.
    pen_width_mm : float
        Pen tip width in millimetres. Must be positive; waves are never
        tighter than two pen widths.

    Returns
    -------
    list[LineString]
        One stroke per row (more with ``skip_white``), in image pixel
        coordinates, inside the image.

    Raises
    ------
    ValueError
        If ``pixels_per_mm`` or ``pen_width_mm`` is not a positive number.
    """
    if not math.isfinite(pixels_per_mm) or pixels_per_mm <= 0.0:
        raise ValueError(
            "pixels_per_mm must be a positive number; pass the working image's "
            "pixels per paper millimetre (for example 10.0)"
        )
    if not math.isfinite(pen_width_mm) or pen_width_mm <= 0.0:
        raise ValueError(
            "pen_width_mm must be a positive number; pass the pen tip width in "
            "millimetres (for example 0.3)"
        )
    gray = image.convert("L") if image.mode != "L" else image
    darkness = 1.0 - np.asarray(gray, dtype=np.float64) / 255.0
    height, width = darkness.shape
    if height < 2 or width < 2:
        return []

    spacing_px = settings.line_spacing * pixels_per_mm
    # Average the tone across each row's band so a row sees its whole strip.
    tone = np.asarray(
        gaussian(darkness, sigma=max(0.5, spacing_px / 3.0), preserve_range=True),  # type: ignore[no-untyped-call]
        dtype=np.float64,
    )
    span = max(1e-6, 1.0 - settings.min_tone)
    level = np.clip((tone - settings.min_tone) / span, 0.0, 1.0) ** settings.tone_gamma

    max_frequency = min(settings.max_frequency, 1.0 / (2.0 * pen_width_mm))
    min_frequency = min(settings.min_frequency, max_frequency)
    amplitude_px = settings.max_amplitude * spacing_px / 2.0
    step_px = max(0.25, min(1.0, pixels_per_mm / (12.0 * max(max_frequency, 1e-6))))

    theta = math.radians(settings.angle)
    ux, uy = math.cos(theta), math.sin(theta)
    nx, ny = -uy, ux
    cx, cy = (width - 1) / 2.0, (height - 1) / 2.0
    reach = math.hypot(width, height)
    frame = box(0.0, 0.0, width - 1.0, height - 1.0)

    strokes: list[LineString] = []
    offsets = np.arange(-reach / 2.0 + spacing_px / 2.0, reach / 2.0, spacing_px)
    row_index = 0
    for offset in offsets.tolist():
        ox, oy = cx + nx * offset, cy + ny * offset
        base = LineString([(ox - ux * reach, oy - uy * reach), (ox + ux * reach, oy + uy * reach)])
        clipped = base.intersection(frame)
        if not isinstance(clipped, LineString) or clipped.length <= 0.0:
            continue
        (ax, ay), (bx, by) = clipped.coords[0], clipped.coords[-1]
        if (bx - ax) * ux + (by - ay) * uy < 0.0:
            ax, ay, bx, by = bx, by, ax, ay
        length = math.hypot(bx - ax, by - ay)
        count = max(2, math.ceil(length / step_px) + 1)
        ts = np.linspace(0.0, length, count)
        xs = ax + ux * ts
        ys = ay + uy * ts
        row_level = _bilinear(level, xs, ys)
        frequency_px = (min_frequency + (max_frequency - min_frequency) * row_level) / pixels_per_mm
        phase = (
            2.0
            * math.pi
            * np.concatenate(
                ([0.0], np.cumsum(0.5 * (frequency_px[1:] + frequency_px[:-1]) * np.diff(ts)))
            )
        )
        wave = amplitude_px * row_level * np.sin(phase)
        px = np.clip(xs + nx * wave, 0.0, width - 1.0)
        py = np.clip(ys + ny * wave, 0.0, height - 1.0)
        points = np.column_stack((px, py))
        if settings.serpentine and row_index % 2 == 1:
            points = points[::-1]
            drawn = row_level[::-1] > 0.0
        else:
            drawn = row_level > 0.0
        row_index += 1
        if not settings.skip_white:
            line = LineString(points)
            if line.length > 0.0:
                strokes.append(line)
            continue
        padded = np.concatenate(([False], drawn, [False]))
        changes = np.flatnonzero(padded[1:] != padded[:-1])
        for start, end in zip(changes[0::2].tolist(), changes[1::2].tolist(), strict=True):
            if end - start >= 2:
                line = LineString(points[start:end])
                if line.length > 0.0:
                    strokes.append(line)
    return strokes


__all__ = ["SquiggleSettings", "squiggle_strokes"]
