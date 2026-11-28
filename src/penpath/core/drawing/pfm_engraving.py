"""Engraving PFM: parallel lines that swell where the image is darker.

Copper-plate engraving builds tone with line *width*: evenly spaced lines get
thicker in the shadows and thin out to nothing in the highlights. A pen has a
fixed width, so each engraved line is drawn as a bundle of up to ``N``
strokes one pen width apart (``N = line_spacing / pen_width``); the darker
the image, the more strokes of the bundle are drawn, from the centre out,
one side at a time.
One bundle covers ``strokes * pen_width / line_spacing`` of the paper, so the
plotted tone follows the image for any pen.

The lines are level lines of a scalar field, so their layout is a choice:

- ``straight``: parallel lines at ``angle``.
- ``swirl``: the same lines twisted around a centre, more strongly near it
  (after the screen-space "Lines" sketches by Jaume Sanchez, spite/sketch).
- ``contour``: lines parallel to the image's main edges, so they echo the
  shapes like the rings of a topographic engraving.

Every stroke is the level line ``f = k`` of the field ``f`` measured in pen
widths; stroke ``k`` belongs to bundle ``k // N`` at position ``k % N``.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Literal, cast

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, Field
from scipy import ndimage  # type: ignore[import-untyped]
from shapely import LineString
from skimage.filters import gaussian
from skimage.measure import find_contours
from skimage.transform import resize as _resize

from penpath.core.drawing.outline import OutlineSettings, outline_strokes

if TYPE_CHECKING:
    from PIL import Image

EngravingLayout = Literal["straight", "swirl", "contour"]

_MAX_GRID_PIXELS = 10_000_000


class EngravingSettings(BaseModel):
    """Settings for the Engraving PFM.

    Lengths are in millimetres on paper; the image scale and pen width are
    passed to :func:`engraving_strokes`.

    Parameters
    ----------
    line_spacing : float
        Distance between engraved lines in millimetres (> 0). Each line can
        hold ``line_spacing / pen_width`` strokes. Default 1.5.
    layout : {"straight", "swirl", "contour"}
        How the lines run (see the module docs). Default "straight".
    angle : float
        Line direction in degrees for ``straight`` and ``swirl``
        (-360 - 360). Default 45.0.
    swirl_turns : float
        For ``swirl``: how far the lines twist at the centre, in turns
        (-5 - 5); the twist fades to zero at the image corners. Default 0.75.
    swirl_center : tuple[float, float]
        For ``swirl``: centre as a fraction of the image width and height.
        Default ``(0.5, 0.5)``.
    max_width : float
        Line width at full black as a fraction of ``line_spacing``
        (0 - 1); 1 lets neighbouring lines touch. Default 1.0.
    tone_gamma : float
        Exponent applied to darkness before it sets the width (> 0).
        Default 1.0.
    min_tone : float
        Darkness at or below which lines vanish (0 - 1); darker tones are
        stretched so ``min_tone`` maps to no ink. Default 0.05.
    tone_blur : float
        Blur of the tone map in millimetres (0 - 10), so the width changes
        smoothly. Default 1.0.
    hairline : bool
        Keep the centre stroke of every line wherever the image is not paper
        white, as in classic engraving. Default False.
    edge_low : float
        For ``contour``: low Canny threshold (0 - 1). Default 0.12.
    edge_high : float
        For ``contour``: high Canny threshold (0 - 1, above ``edge_low``).
        Default 0.25.
    contour_min_length : float
        For ``contour``: shortest edge kept, in millimetres (> 0).
        Default 8.0.
    min_length : float
        Shortest stroke kept, in millimetres (>= 0). Default 1.0.
    seed : int | None
        Accepted for symmetry with the other PFMs; the algorithm is
        deterministic. Default None.
    """

    line_spacing: float = Field(default=1.5, gt=0.0)
    layout: EngravingLayout = "straight"
    angle: float = Field(default=45.0, ge=-360.0, le=360.0)
    swirl_turns: float = Field(default=0.75, ge=-5.0, le=5.0)
    swirl_center: tuple[float, float] = (0.5, 0.5)
    max_width: float = Field(default=1.0, ge=0.0, le=1.0)
    tone_gamma: float = Field(default=1.0, gt=0.0)
    min_tone: float = Field(default=0.05, ge=0.0, le=1.0)
    tone_blur: float = Field(default=1.0, ge=0.0, le=10.0)
    hairline: bool = False
    edge_low: float = Field(default=0.12, ge=0.0, le=1.0)
    edge_high: float = Field(default=0.25, ge=0.0, le=1.0)
    contour_min_length: float = Field(default=8.0, gt=0.0)
    min_length: float = Field(default=1.0, ge=0.0)
    seed: int | None = None

    def model_post_init(self, __context: object) -> None:
        """Check paired thresholds."""
        if self.edge_high <= self.edge_low:
            raise ValueError("edge_high must be greater than edge_low")


def _resize_to(values: NDArray[np.float64], shape: tuple[int, int]) -> NDArray[np.float64]:
    """Bilinear resize with a typed result."""
    result = _resize(values, shape, order=1, anti_aliasing=False)  # type: ignore[no-untyped-call]
    return np.asarray(result, dtype=np.float64)


def strokes_per_line(
    level: NDArray[np.float64], per_line: int, max_width: float
) -> NDArray[np.float64]:
    """Number of strokes (pen widths) a line holds for each tone ``level`` (0 - 1).

    The line width is ``level * max_width * line_spacing``, i.e.
    ``level * max_width * per_line`` pen widths. :func:`engraving_strokes`
    draws the stroke of rank ``r`` (0 = centre, then alternating sides) where
    this width is at least ``r + 1``.
    """
    return np.clip(level, 0.0, 1.0) * max_width * per_line


def _field(
    settings: EngravingSettings,
    shape: tuple[int, int],
    pen_px: float,
    outlines: list[LineString] | None,
    scale: float,
) -> NDArray[np.float64]:
    """The scalar field whose integer level lines are the strokes, in pen widths."""
    rows, cols = np.indices(shape, dtype=np.float64)
    if settings.layout == "contour" and outlines:
        seeds = np.zeros(shape, dtype=bool)
        height, width = shape
        for line in outlines:
            coords = np.asarray(line.coords, dtype=np.float64) * scale
            segment = np.hypot(*np.diff(coords, axis=0).T)
            total = float(segment.sum())
            if total <= 0.0:
                continue
            positions = np.linspace(0.0, total, max(2, math.ceil(total / 0.5) + 1))
            cumulative = np.concatenate(([0.0], np.cumsum(segment)))
            xs = np.interp(positions, cumulative, coords[:, 0])
            ys = np.interp(positions, cumulative, coords[:, 1])
            seeds[
                np.clip(np.rint(ys), 0, height - 1).astype(np.int64),
                np.clip(np.rint(xs), 0, width - 1).astype(np.int64),
            ] = True
        if seeds.any():
            distance = np.asarray(ndimage.distance_transform_edt(~seeds), dtype=np.float64)
            smooth = gaussian(distance, sigma=2.0, preserve_range=True)  # type: ignore[no-untyped-call]
            return np.asarray(smooth, dtype=np.float64) / pen_px
    theta = math.radians(settings.angle)
    if settings.layout == "swirl":
        cy = settings.swirl_center[1] * (shape[0] - 1)
        cx = settings.swirl_center[0] * (shape[1] - 1)
        dy, dx = rows - cy, cols - cx
        radius = np.hypot(dx, dy)
        reach = max(1.0, float(radius.max()))
        twist = 2.0 * math.pi * settings.swirl_turns * (1.0 - radius / reach) ** 2
        cos_t, sin_t = np.cos(twist), np.sin(twist)
        cols = cx + dx * cos_t - dy * sin_t
        rows = cy + dx * sin_t + dy * cos_t
    return (-cols * math.sin(theta) + rows * math.cos(theta)) / pen_px


def engraving_strokes(
    image: Image.Image,
    settings: EngravingSettings,
    pixels_per_mm: float,
    pen_width_mm: float,
) -> list[LineString]:
    """Draw engraved lines whose width (number of strokes) follows darkness.

    Parameters
    ----------
    image : PIL.Image.Image
        Input image (any mode, converted to greyscale).
    settings : EngravingSettings
        Algorithm configuration, in millimetres on paper.
    pixels_per_mm : float
        Working-image pixels per paper millimetre. Must be positive.
    pen_width_mm : float
        Pen tip width in millimetres. Must be positive; strokes of a line are
        one pen width apart.

    Returns
    -------
    list[LineString]
        Strokes in image pixel coordinates (origin top-left), inside the
        image.

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
    if height < 2 or width < 2 or float(darkness.max()) <= settings.min_tone:
        return []

    pen_px = pen_width_mm * pixels_per_mm
    # Strokes one pen width apart need >= 3 grid pixels per pen width.
    # The grid is capped at about 10 megapixels; on a very coarse image the
    # strokes are then spaced wider than the pen, never closer than 3 grid
    # pixels (closer level lines would alias into noise).
    max_scale = max(1, math.floor(math.sqrt(_MAX_GRID_PIXELS / (height * width))))
    scale = float(min(max_scale, max(1, math.ceil(3.0 / pen_px))))
    fine_shape = (round(height * scale), round(width * scale))
    pen_fine = max(pen_px * scale, 3.0)
    per_line = max(1, round(settings.line_spacing * pixels_per_mm * scale / pen_fine))

    tone = darkness
    if settings.tone_blur > 0.0:
        blurred = gaussian(tone, sigma=settings.tone_blur * pixels_per_mm, preserve_range=True)  # type: ignore[no-untyped-call]
        tone = np.asarray(blurred, dtype=np.float64)
    span = max(1e-6, 1.0 - settings.min_tone)
    level = np.clip((tone - settings.min_tone) / span, 0.0, 1.0) ** settings.tone_gamma
    level = _resize_to(level, fine_shape)
    width_pens = strokes_per_line(level, per_line, settings.max_width)

    outlines: list[LineString] | None = None
    if settings.layout == "contour":
        outlines = outline_strokes(
            gray,
            OutlineSettings(
                blur_sigma=min(10.0, 0.6 * pixels_per_mm),
                low_threshold=settings.edge_low,
                high_threshold=settings.edge_high,
                min_length=max(1.0, settings.contour_min_length * pixels_per_mm),
                min_component_pixels=max(1, round(settings.contour_min_length * pixels_per_mm)),
                simplify_tolerance=0.5,
            ),
        )
    field = _field(settings, fine_shape, pen_fine, outlines, scale)

    inked = level > 0.0
    if not inked.any():
        return []
    wave = np.sin(np.pi * field)
    min_length_fine = settings.min_length * pixels_per_mm * scale
    centre = (per_line - 1) / 2.0
    # Strokes join a line from the centre out, alternating sides, so every
    # count from 1 to per_line is possible (finer tone steps).
    order = sorted(range(per_line), key=lambda m: (abs(m - centre), -(m - centre)))
    rank_of = {m: rank for rank, m in enumerate(order)}
    max_x, max_y = float(width - 1), float(height - 1)
    strokes: list[LineString] = []
    for contour in find_contours(wave, 0.0, mask=inked):  # type: ignore[no-untyped-call]
        if len(contour) < 2:
            continue
        rows = np.clip(np.rint(contour[:, 0]).astype(np.int64), 0, fine_shape[0] - 1)
        cols = np.clip(np.rint(contour[:, 1]).astype(np.int64), 0, fine_shape[1] - 1)
        index = int(np.rint(np.median(field[rows, cols])))
        rank = rank_of[index % per_line]
        # A stroke is drawn where the line is at least rank + 1 pens wide.
        keep = width_pens[rows, cols] >= rank + 1.0
        if settings.hairline and rank == 0:
            keep = keep | (level[rows, cols] > 0.0)
        padded = np.concatenate(([False], keep, [False]))
        changes = np.flatnonzero(padded[1:] != padded[:-1])
        for start, end in zip(changes[0::2].tolist(), changes[1::2].tolist(), strict=True):
            piece = contour[start:end]
            if len(piece) < 2:
                continue
            if float(np.hypot(*np.diff(piece, axis=0).T).sum()) < min_length_fine:
                continue
            xs = np.clip(piece[:, 1] / scale, 0.0, max_x)
            ys = np.clip(piece[:, 0] / scale, 0.0, max_y)
            line = cast(LineString, LineString(np.column_stack((xs, ys))).simplify(0.25))
            if line.length > 0.0:
                strokes.append(line)
    return strokes


__all__ = ["EngravingLayout", "EngravingSettings", "engraving_strokes", "strokes_per_line"]
