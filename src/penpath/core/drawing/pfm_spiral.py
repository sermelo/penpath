"""Spiral Sawtooth PFM (Pen Follower Module) implementation.

Port of ``PFMSpiralBasic`` from DrawingBotV3 (v1.6.25-stable-free) and its
registered Spiral settings. The spiral walks outwards from a centre point and
draws a radial sawtooth at every step, where the tooth length follows the
sampled luminance and the step length follows an ease-in-sine velocity curve.
As with the Sketch Lines and Sketch Squares ports, the ported logic follows
DrawingBotV3's GPL-3.0 licence handling (see the repository LICENSE).

Penpath builds the spiral in normalised coordinates. ``shape="circle"`` (the
default) grows true circular rings out to the nearest page edge,
``shape="ellipse"`` keeps the original per-axis scaling, and
``shape="cover"`` grows circular rings out to the farthest page corner with
teeth clipped to the page. Connected output is one stroke (parabolic at most
two); DrawingBotV3 stops at the far corner without clipping.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import numpy as np
from pydantic import BaseModel, Field
from shapely import LineString

if TYPE_CHECKING:
    from PIL import Image

SpiralType = Literal["archimedean", "parabolic"]
SpiralShape = Literal["circle", "ellipse", "cover"]
_PathPoint = tuple[float, float]
_WHITE_MASK = 240.0
_MAX_STEPS = 2_000_000
_COVER_MIN_STEP = 1.5


class SpiralSettings(BaseModel):
    """Settings for the Spiral Sawtooth PFM algorithm.

    Parameters
    ----------
    spiral_type : Literal["archimedean", "parabolic"]
        One spiral in one pass, or the reference's two opposed branches in two.
    shape : Literal["circle", "ellipse", "cover"]
        Ring geometry. ``circle`` (default) grows round rings to the nearest
        page edge; ``ellipse`` keeps the original per-axis scaling; ``cover``
        grows round rings to the farthest corner and clips teeth to the page.
    centre_x : float
        Centre X as a fraction of image width (0 - 1); 0.5 is the middle.
    centre_y : float
        Centre Y as a fraction of image height (0 - 1); 0.5 is the middle.
    spiral_size : float
        Fraction (0.05 - 1) of the largest spiral that fits from the centre.
        ``circle`` and ``ellipse`` measure against the nearest page edge;
        ``cover`` measures against the farthest page corner. The tooth reach
        is reserved so teeth stay on the page for circle and ellipse.
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
    shape: SpiralShape = "circle"
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


@dataclass(frozen=True, slots=True)
class _Geometry:
    """Derived ring geometry and step sizes, in image pixels and degrees."""

    width: int
    height: int
    centre_x: float
    centre_y: float
    scale_x: float
    scale_y: float
    scale: float
    shape: SpiralShape
    parabolic: bool
    ring_spacing: float
    tooth_reach: float
    end_radius: float
    min_velocity: float
    max_velocity: float


def _build_geometry(settings: SpiralSettings, width: int, height: int) -> _Geometry | None:
    """Derive the ring geometry, or None when the image cannot hold a spiral."""
    centre_x = settings.centre_x * (width - 1)
    centre_y = settings.centre_y * (height - 1)
    scale_x = min(centre_x, (width - 1) - centre_x)
    scale_y = min(centre_y, (height - 1) - centre_y)
    if scale_x <= 0.0 or scale_y <= 0.0:
        return None
    scale = min(scale_x, scale_y)
    shape = settings.shape
    parabolic = settings.spiral_type == "parabolic"
    ring_spacing = settings.ring_spacing / 10.0 if parabolic else settings.ring_spacing
    amplitude = settings.amplitude / 1.5 if parabolic else settings.amplitude
    tooth_reach = (ring_spacing / 2.0) * amplitude
    if shape == "cover":
        base_radius = math.hypot(
            max(centre_x, (width - 1) - centre_x),
            max(centre_y, (height - 1) - centre_y),
        )
    else:
        base_radius = scale
    if shape == "ellipse":
        end_radius = base_radius * settings.spiral_size - tooth_reach * (
            max(scale_x, scale_y) / scale
        )
    else:
        end_radius = base_radius * settings.spiral_size - tooth_reach
    if end_radius <= 0.0:
        return None
    min_velocity = settings.min_velocity / 10.0 if parabolic else settings.min_velocity
    max_velocity = settings.max_velocity / 10.0 if parabolic else settings.max_velocity
    if not settings.variable_velocity:
        max_velocity = min_velocity
    return _Geometry(
        width=width,
        height=height,
        centre_x=centre_x,
        centre_y=centre_y,
        scale_x=scale_x,
        scale_y=scale_y,
        scale=scale,
        shape=shape,
        parabolic=parabolic,
        ring_spacing=ring_spacing,
        tooth_reach=tooth_reach,
        end_radius=end_radius,
        min_velocity=min_velocity,
        max_velocity=max_velocity,
    )


def _position(geometry: _Geometry, radius: float, alpha: float, pass_index: int) -> _PathPoint:
    """Return the spiral point at a radius and angle for one pass."""
    theta = math.radians(alpha)
    offset = radius * (-1.0 if pass_index == 2 else 1.0) if geometry.parabolic else radius
    if geometry.parabolic:
        offset *= math.sqrt(theta)
    if geometry.shape == "ellipse":
        fraction = offset / geometry.scale
        x = geometry.centre_x + fraction * geometry.scale_x * math.cos(theta)
        y = geometry.centre_y + fraction * geometry.scale_y * math.sin(theta)
    else:
        x = geometry.centre_x + offset * math.cos(theta)
        y = geometry.centre_y + offset * math.sin(theta)
    return x, y


def _advance(
    radius: float, alpha: float, velocity: float, ring_spacing: float
) -> tuple[float, float]:
    """Advance the angular position and radius by one velocity-scaled step."""
    step = (velocity / 2.0) / radius
    return alpha + step, radius + ring_spacing * step / 360.0


def _tooth_and_velocity(geometry: _Geometry, tone: float) -> tuple[float, float]:
    """Turn a sampled tone into its radial tooth reach and angular velocity."""
    brightness = tone / 255.0
    tooth = (1.0 - brightness) * geometry.tooth_reach
    velocity = geometry.min_velocity + _ease_in_sine(brightness) * (
        geometry.max_velocity - geometry.min_velocity
    )
    return tooth, velocity


class _StrokeCollector:
    """Accumulate teeth into non-zero strokes, breaking over white paper."""

    def __init__(self, geometry: _Geometry, settings: SpiralSettings) -> None:
        self._geometry = geometry
        self._connected = settings.connected_lines
        self._ignore_white = settings.ignore_white
        self._max_strokes = settings.max_strokes
        self.strokes: list[LineString] = []
        self._current: list[_PathPoint] = []
        self.stroke_count = 0

    @property
    def capped(self) -> bool:
        return self._max_strokes is not None and self.stroke_count >= self._max_strokes

    def flush(self) -> None:
        if len(self._current) >= 2 and (line := LineString(self._current)).length > 0.0:
            self.strokes.append(line)
            self.stroke_count += 1
        self._current = []

    def append(self, point: _PathPoint) -> None:
        if not self._current:
            self._current.append(point)
            return
        last = self._current[-1]
        if last == point:
            return
        if (
            self._geometry.shape == "cover"
            and math.hypot(point[0] - last[0], point[1] - last[1]) < _COVER_MIN_STEP
        ):
            return
        self._current.append(point)

    def add(self, tone: float, tooth_start: _PathPoint, tooth_end: _PathPoint) -> None:
        if self._ignore_white and tone >= _WHITE_MASK:
            self.flush()
            return
        tooth_start = self._clamp(tooth_start)
        tooth_end = self._clamp(tooth_end)
        if self._connected:
            self.append(tooth_start)
            self.append(tooth_end)
        elif tooth_start != tooth_end:
            line = LineString([tooth_start, tooth_end])
            if line.length > 0.0:
                self.strokes.append(line)
                self.stroke_count += 1

    def _clamp(self, point: _PathPoint) -> _PathPoint:
        x, y = point
        return (
            min(max(x, 0.0), self._geometry.width - 1),
            min(max(y, 0.0), self._geometry.height - 1),
        )


def _run_pass(
    geometry: _Geometry,
    luminance: np.ndarray,
    pass_index: int,
    collector: _StrokeCollector,
) -> None:
    """Sample and draw every tooth of one spiral pass."""
    alpha = 0.0
    radius = geometry.min_velocity / 360.0
    last_luminance = 255.0
    steps = 0
    while True:
        effective = radius * math.sqrt(math.radians(alpha)) if geometry.parabolic else radius
        if effective >= geometry.end_radius or steps >= _MAX_STEPS or collector.capped:
            break
        steps += 1
        point = _position(geometry, radius, alpha, pass_index)
        sample_x = min(max(round(point[0]), 0), geometry.width - 1)
        sample_y = min(max(round(point[1]), 0), geometry.height - 1)
        sampled = float(luminance[sample_y, sample_x])
        tone = (sampled + last_luminance) / 2.0
        last_luminance = sampled

        tooth, velocity = _tooth_and_velocity(geometry, tone)
        alpha, radius = _advance(radius, alpha, geometry.min_velocity, geometry.ring_spacing)
        alpha, radius = _advance(radius, alpha, velocity, geometry.ring_spacing)
        tooth_start = _position(geometry, radius + tooth, alpha, pass_index)
        alpha, radius = _advance(radius, alpha, velocity, geometry.ring_spacing)
        tooth_end = _position(geometry, radius - tooth, alpha, pass_index)
        collector.add(tone, tooth_start, tooth_end)

    collector.flush()


def spiral_strokes(image: Image.Image, settings: SpiralSettings) -> list[LineString]:
    """Generate Spiral Sawtooth strokes from an image.

    The reference loop is kept: the current spiral point is sampled, its
    luminance is averaged with the previous sample, and the result sets both
    the radial tooth length (dark = long) and the ease-in-sine step velocity.
    Parabolic runs the reference's two passes with ring spacing and velocity
    divided by 10 and amplitude divided by 1.5. ``shape="circle"`` grows round
    rings to the nearest page edge, ``shape="ellipse"`` keeps the original
    per-axis scaling and ``shape="cover"`` grows round rings to the farthest
    corner with every point clipped to the page. Coordinates are in image pixels
    (origin top-left), always inside ``[0, width-1] x [0, height-1]``: teeth
    reaching the page edge are clamped to it so a connected pass stays one
    stroke, while teeth skipped over white paper (``ignore_white``) close a
    stroke, and duplicate consecutive points are dropped. For ``cover``,
    clamped teeth that barely advance are dropped too, so the clipped rings have
    no sub-pixel segments.

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
    geometry = _build_geometry(settings, width, height)
    if geometry is None:
        return []
    collector = _StrokeCollector(geometry, settings)
    for pass_index in range(1, 3 if geometry.parabolic else 2):
        _run_pass(geometry, luminance, pass_index, collector)
    return collector.strokes


__all__ = ["SpiralSettings", "spiral_strokes"]
