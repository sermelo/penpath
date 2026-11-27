"""Spiral Sawtooth PFM (Pen Follower Module) implementation.

Port of ``PFMSpiralBasic`` from DrawingBotV3 (v1.6.25-stable-free) and its
registered Spiral settings. The spiral walks outwards from a centre point and
draws a radial sawtooth at every step, where the tooth length follows the
sampled luminance and the step length follows an ease-in-sine velocity curve.
As with the Sketch Lines and Sketch Squares ports, the ported logic follows
DrawingBotV3's GPL-3.0 licence handling (see the repository LICENSE).

Penpath builds the spiral in normalised coordinates and scales it to the
nearest page edge on each axis, so the default spiral stays on the page and
connected output is a single stroke; DrawingBotV3 stops at the far corner.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Literal

import numpy as np
from pydantic import BaseModel, Field
from shapely import LineString

if TYPE_CHECKING:
    from PIL import Image

SpiralType = Literal["archimedean", "parabolic"]
_PathPoint = tuple[float, float]
_WHITE_MASK = 240.0
_MAX_STEPS = 2_000_000


class SpiralSettings(BaseModel):
    """Settings for the Spiral Sawtooth PFM algorithm.

    Parameters
    ----------
    spiral_type : Literal["archimedean", "parabolic"]
        One spiral in one pass, or the reference's two opposed branches in two.
    centre_x : float
        Centre X as a fraction of image width (0 - 1); 0.5 is the middle.
    centre_y : float
        Centre Y as a fraction of image height (0 - 1); 0.5 is the middle.
    spiral_size : float
        Fraction (0.05 - 1) of the largest spiral that fits from the centre.
        Penpath measures against the nearest page edge on each axis, not
        DrawingBotV3's far corner, so the default spiral stays on the page.
    ring_spacing : float
        Distance between turns in working-image pixels (>0 - 1000); smaller
        values resolve more detail.
    amplitude : float
        Tooth multiplier (0 - 10): a tooth reaches at most
        ring_spacing/2 * amplitude pixels either side of the spiral.
    variable_velocity : bool
        True eases the step between min and max velocity by luminance; false
        uses ``min_velocity`` for every step.
    min_velocity : float
        Slowest angular step (1 - 3600); lower values draw more teeth.
    max_velocity : float
        Fastest angular step (1 - 3600); must be >= ``min_velocity``.
    connected_lines : bool
        True joins consecutive teeth into one LineString per pass; false gives
        one two-point LineString per tooth.
    ignore_white : bool
        True skips teeth whose sampled luminance is >= the reference's mask of
        240, breaking a connected stroke over white paper for palette layers.
    seed : int | None
        Accepted for API symmetry; the algorithm is deterministic, so any seed
        gives the same strokes.
    max_strokes : int | None
        Optional cap on emitted strokes (>=1), mainly for disconnected output.
    """

    spiral_type: SpiralType = "archimedean"
    centre_x: float = Field(default=0.5, ge=0.0, le=1.0)
    centre_y: float = Field(default=0.5, ge=0.0, le=1.0)
    spiral_size: float = Field(default=1.0, ge=0.05, le=1.0)
    ring_spacing: float = Field(default=7.0, gt=0.0, le=1000.0)
    amplitude: float = Field(default=1.0, ge=0.0, le=10.0)
    variable_velocity: bool = True
    min_velocity: float = Field(default=50.0, ge=1.0, le=3600.0)
    max_velocity: float = Field(default=150.0, ge=1.0, le=3600.0)
    connected_lines: bool = True
    ignore_white: bool = False
    seed: int | None = None
    max_strokes: int | None = Field(default=None, ge=1)

    def model_post_init(self, __context: object) -> None:
        if self.max_velocity < self.min_velocity:
            raise ValueError("max_velocity must be >= min_velocity")


def _ease_in_sine(value: float) -> float:
    """Return the reference's easeInSine of a value in 0 - 1."""
    return 1.0 - math.cos(value * math.pi / 2.0)


def spiral_strokes(image: Image.Image, settings: SpiralSettings) -> list[LineString]:
    """Generate Spiral Sawtooth strokes from an image.

    The reference loop is kept: the current spiral point is sampled, its
    luminance is averaged with the previous sample, and the result sets both
    the radial tooth length (dark = long) and the ease-in-sine step velocity.
    Parabolic runs the reference's two passes with ring spacing and velocity
    divided by 10 and amplitude divided by 1.5. Coordinates are in image
    pixels (origin top-left), always inside ``[0, width-1] x [0, height-1]``;
    skipped teeth close a stroke instead of bridging white paper or off-page
    space, and duplicate consecutive points are dropped.

    Parameters
    ----------
    image : PIL.Image.Image
        Input image (any mode, converted to grayscale).
    settings : SpiralSettings
        Algorithm configuration.

    Returns
    -------
    list[LineString]
        Strokes in image pixel coordinates, never zero-length.
    """
    luminance = np.asarray(image.convert("L"), dtype=np.float64)
    height, width = (int(size) for size in luminance.shape)
    if width < 2 or height < 2:
        return []

    centre_x = settings.centre_x * (width - 1)
    centre_y = settings.centre_y * (height - 1)
    scale_x = min(centre_x, (width - 1) - centre_x)
    scale_y = min(centre_y, (height - 1) - centre_y)
    if scale_x <= 0.0 or scale_y <= 0.0:
        return []

    scale = min(scale_x, scale_y)
    parabolic = settings.spiral_type == "parabolic"
    ring_spacing = settings.ring_spacing / 10.0 if parabolic else settings.ring_spacing
    amplitude = settings.amplitude / 1.5 if parabolic else settings.amplitude
    tooth_reach = (ring_spacing / 2.0) * amplitude
    end_radius = scale * settings.spiral_size - tooth_reach * (max(scale_x, scale_y) / scale)
    if end_radius <= 0.0:
        return []
    min_velocity = settings.min_velocity / 10.0 if parabolic else settings.min_velocity
    max_velocity = settings.max_velocity / 10.0 if parabolic else settings.max_velocity
    if not settings.variable_velocity:
        max_velocity = min_velocity

    strokes: list[LineString] = []
    current: list[_PathPoint] = []
    stroke_count = 0

    def flush() -> None:
        nonlocal current, stroke_count
        if len(current) >= 2 and (line := LineString(current)).length > 0.0:
            strokes.append(line)
            stroke_count += 1
        current = []

    def append(point: _PathPoint) -> None:
        if not current or current[-1] != point:
            current.append(point)

    def on_page(point: _PathPoint) -> bool:
        x, y = point
        return 0.0 <= x <= width - 1 and 0.0 <= y <= height - 1

    def position(radius: float, alpha: float, pass_index: int) -> _PathPoint:
        theta = math.radians(alpha)
        offset = radius * (-1.0 if pass_index == 2 else 1.0) if parabolic else radius
        if parabolic:
            offset *= math.sqrt(theta)
        fraction = offset / scale
        x = centre_x + fraction * scale_x * math.cos(theta)
        y = centre_y + fraction * scale_y * math.sin(theta)
        return x, y

    def advance(radius: float, alpha: float, velocity: float) -> tuple[float, float]:
        step = (velocity / 2.0) / radius
        return alpha + step, radius + ring_spacing * step / 360.0

    for pass_index in range(1, 3 if parabolic else 2):
        alpha = 0.0
        radius = min_velocity / 360.0
        last_luminance = 255.0
        steps = 0

        while True:
            effective = radius * math.sqrt(math.radians(alpha)) if parabolic else radius
            capped = settings.max_strokes is not None and stroke_count >= settings.max_strokes
            if effective >= end_radius or steps >= _MAX_STEPS or capped:
                break
            steps += 1

            point = position(radius, alpha, pass_index)
            sample_x = min(max(round(point[0]), 0), width - 1)
            sample_y = min(max(round(point[1]), 0), height - 1)
            sampled = float(luminance[sample_y, sample_x])
            tone = (sampled + last_luminance) / 2.0
            last_luminance = sampled

            tooth = (1.0 - tone / 255.0) * tooth_reach
            velocity = min_velocity + _ease_in_sine(tone / 255.0) * (max_velocity - min_velocity)

            alpha, radius = advance(radius, alpha, min_velocity)
            alpha, radius = advance(radius, alpha, velocity)
            tooth_start = position(radius + tooth, alpha, pass_index)
            alpha, radius = advance(radius, alpha, velocity)
            tooth_end = position(radius - tooth, alpha, pass_index)

            off_page = not (on_page(tooth_start) and on_page(tooth_end))
            if off_page or (settings.ignore_white and tone >= _WHITE_MASK):
                flush()
                continue

            if settings.connected_lines:
                append(tooth_start)
                append(tooth_end)
            elif tooth_start != tooth_end:
                line = LineString([tooth_start, tooth_end])
                if line.length > 0.0:
                    strokes.append(line)
                    stroke_count += 1

        flush()

    return strokes


__all__ = ["SpiralSettings", "spiral_strokes"]
