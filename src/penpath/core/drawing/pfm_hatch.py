"""Hatch PFM: engraving-style parallel and cross-hatched lines.

Darkness ``1 - L/255`` drives a set of bands. Band ``i`` draws straight lines
at ``angles[i]`` wherever darkness reaches ``thresholds[i]``, so darker areas
receive more line directions. Each line is clipped to the image, sampled, and
split into runs that are bridged across short gaps and trimmed to a minimum
length. All settings are in millimetres on paper; the caller supplies the
working-image scale explicitly, keeping the model serialisable in project
files.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, Field, field_validator
from shapely import LineString
from shapely.geometry import box

if TYPE_CHECKING:
    from PIL import Image

_SAMPLE_STEP_PX = 0.5
_EPS = 1e-9

PALETTE_ANGLE_STEP_DEG = 30.0
"""Degrees to rotate the hatch angles for each successive palette pen."""


class HatchSettings(BaseModel):
    """Settings for the straight / cross-hatching PFM algorithm.

    All lengths are in millimetres on paper, not image pixels. The image scale
    is passed to :func:`hatch_strokes` as ``pixels_per_mm``.

    Parameters
    ----------
    spacing : float
        Distance between parallel lines in millimetres (greater than 0).
        The effective spacing used by a band is never below ``pen_width_mm``.
        Default 1.0.
    angles : tuple[float, ...]
        Line direction in degrees for each band, each in [-360, 360]. Bands
        are drawn in order, so darker areas get more directions. Must have the
        same length as ``thresholds``. Default ``(45, 135, 0, 90)``.
    thresholds : tuple[float, ...]
        Minimum darkness ``1 - L/255`` for a band, each in (0, 1) and strictly
        increasing. Must have the same length as ``angles``. Default
        ``(0.2, 0.4, 0.6, 0.8)``.
    min_length : float
        Shortest run to keep, in millimetres (>= 0). Default 0.5.
    min_gap : float
        Gaps shorter than this, in millimetres, are bridged (>= 0). Default
        0.3.
    variable_spacing : bool
        When true, band ``i`` uses ``spacing * (1 - 0.5 * thresholds[i])`` so
        darker bands get denser lines as well as more directions. Always
        clamped to at least the pen width. Default False.
    serpentine : bool
        Reverse every other line so the end of one line is near the start of
        the next. Default True.
    join_runs : bool
        Join runs on adjacent lines of the same band into continuous zig-zag
        strokes: the end of a run connects to the start of the nearest
        overlapping run on the next line, drawing the short connector, and a
        run without an overlapping partner starts a new stroke. Requires
        ``serpentine``. Default False.
    jitter : float
        Seeded perpendicular position wobble in millimetres (>= 0). Default
        0.0, i.e. perfectly straight parallel lines.
    auto_thresholds : bool
        Fit the thresholds to this image's own tonal range: with ``lo`` and
        ``hi`` the 2nd and 98th percentiles of the darkness of the non-white
        pixels, threshold ``t`` becomes ``lo + t * (hi - lo)``. A flat,
        low-contrast photo then still uses every band. Default False.
    seed : int | None
        Random seed for the jitter. None is non-deterministic. Default None.
    """

    spacing: float = Field(default=1.0, gt=0.0)
    angles: tuple[float, ...] = (45.0, 135.0, 0.0, 90.0)
    thresholds: tuple[float, ...] = (0.2, 0.4, 0.6, 0.8)
    min_length: float = Field(default=0.5, ge=0.0)
    min_gap: float = Field(default=0.3, ge=0.0)
    variable_spacing: bool = False
    serpentine: bool = True
    join_runs: bool = False
    jitter: float = Field(default=0.0, ge=0.0)
    auto_thresholds: bool = False
    seed: int | None = None

    @field_validator("angles")
    @classmethod
    def validate_angles(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        """Require every angle to lie in [-360, 360]."""
        for angle in value:
            if not -360.0 <= angle <= 360.0:
                raise ValueError(f"each angle must be in [-360, 360]; got {angle}")
        return value

    @field_validator("thresholds")
    @classmethod
    def validate_thresholds(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        """Require every threshold to lie strictly between 0 and 1."""
        for threshold in value:
            if not 0.0 < threshold < 1.0:
                raise ValueError(f"each threshold must be in (0, 1); got {threshold}")
        return value

    def model_post_init(self, __context: object) -> None:
        """Check the paired bands, thresholds and joining requirements."""
        if len(self.angles) != len(self.thresholds):
            raise ValueError(
                "angles and thresholds must have the same length "
                f"(got {len(self.angles)} angles and {len(self.thresholds)} thresholds)"
            )
        if any(later <= earlier for earlier, later in pairwise(self.thresholds)):
            raise ValueError(f"thresholds must be strictly increasing; got {self.thresholds}")
        if self.join_runs and not self.serpentine:
            raise ValueError(
                "join_runs requires serpentine=True; set serpentine=true or join_runs=false"
            )


def with_angle_offset(settings: HatchSettings, degrees: float) -> HatchSettings:
    """Return a copy of ``settings`` with every angle rotated by ``degrees``.

    Palette conversion passes ``index * PALETTE_ANGLE_STEP_DEG`` so successive
    pens lay their bands in different directions instead of drawing exactly on
    top of each other. Angles wrap modulo 180 degrees, so a 180-degree offset
    reproduces the original settings. The input model is not mutated.

    Parameters
    ----------
    settings : HatchSettings
        Original hatch settings, typically from a preset.
    degrees : float
        Rotation in degrees to add to each band angle.

    Returns
    -------
    HatchSettings
        A new settings model with rotated angles and all other fields unchanged.
    """
    offset = degrees % 180.0
    angles = tuple((angle + offset) % 180.0 for angle in settings.angles)
    return settings.model_copy(update={"angles": angles})


def _darkness_map(image: Image.Image) -> NDArray[np.float64]:
    """Return ``1 - L/255`` for an image of any mode."""
    gray = image.convert("L") if image.mode != "L" else image
    return 1.0 - np.asarray(gray, dtype=np.float64) / 255.0


def adaptive_thresholds(
    darkness: NDArray[np.float64], thresholds: tuple[float, ...]
) -> tuple[float, ...]:
    """Map ``thresholds`` into the image's own darkness range.

    The range is the 2nd to 98th percentile of the darkness of pixels that
    are not pure white (darkness above 1/255). Threshold ``t`` becomes
    ``lo + t * (hi - lo)``; results stay strictly increasing inside (0, 1).
    An image with no ink, or a range narrower than 0.02, returns
    ``thresholds`` unchanged.

    Parameters
    ----------
    darkness : numpy.ndarray
        Darkness map ``1 - L/255``.
    thresholds : tuple[float, ...]
        Strictly increasing thresholds in (0, 1).

    Returns
    -------
    tuple[float, ...]
        The fitted thresholds.
    """
    inked = darkness[darkness > 1.0 / 255.0]
    if inked.size == 0:
        return thresholds
    lo, hi = (float(v) for v in np.percentile(inked, [2.0, 98.0]))
    if hi - lo < 0.02:
        return thresholds
    fitted: list[float] = []
    for threshold in thresholds:
        value = min(0.999, max(0.001, lo + threshold * (hi - lo)))
        if fitted and value <= fitted[-1]:
            value = min(0.9999, fitted[-1] + 1e-4)
        fitted.append(value)
    return tuple(fitted)


def _sample_darkness(darkness: NDArray[np.float64], x: float, y: float) -> float:
    """Bilinearly sample the darkness map at a point inside the image."""
    height, width = darkness.shape
    x0 = min(math.floor(x), width - 1)
    y0 = min(math.floor(y), height - 1)
    x1 = min(x0 + 1, width - 1)
    y1 = min(y0 + 1, height - 1)
    fx = min(max(x - x0, 0.0), 1.0)
    fy = min(max(y - y0, 0.0), 1.0)
    top = darkness[y0, x0] * (1.0 - fx) + darkness[y0, x1] * fx
    bottom = darkness[y1, x0] * (1.0 - fx) + darkness[y1, x1] * fx
    return float(top * (1.0 - fy) + bottom * fy)


def _runs_at_or_above(values: list[float], threshold: float) -> list[list[int]]:
    """Return inclusive index ranges where values reach the threshold."""
    runs: list[list[int]] = []
    index = 0
    while index < len(values):
        if values[index] >= threshold:
            end = index
            while end + 1 < len(values) and values[end + 1] >= threshold:
                end += 1
            runs.append([index, end])
            index = end + 1
        else:
            index += 1
    return runs


def _keep_runs(
    runs: list[list[int]],
    sample_distance: float,
    min_gap_px: float,
    min_length_px: float,
) -> list[tuple[int, int]]:
    """Bridge short gaps between runs and drop runs shorter than the minimum."""
    merged: list[list[int]] = []
    for start, end in runs:
        if merged and (start - merged[-1][1]) * sample_distance < min_gap_px:
            merged[-1][1] = end
        else:
            merged.append([start, end])
    kept = [
        (start, end)
        for start, end in merged
        if start != end and (end - start) * sample_distance + _EPS >= min_length_px
    ]
    return kept


@dataclass
class _SerpentinePath:
    """A stroke being joined across adjacent lines of one band.

    ``low``/``high`` are the projection interval of the most recent run along
    the band direction, used to find overlapping runs on the next line;
    ``end`` is that run's exit point, the start of the next short connector.
    """

    points: list[tuple[float, float]]
    low: float
    high: float
    end: tuple[float, float]


def hatch_strokes(
    image: Image.Image,
    settings: HatchSettings,
    pixels_per_mm: float,
    pen_width_mm: float,
) -> list[LineString]:
    """Generate straight parallel and cross-hatching strokes from an image.

    The image is converted to greyscale and sampled as darkness ``1 - L/255``.
    For each band, parallel lines at ``angles[i]`` are laid ``spacing`` mm apart
    (clamped to the pen width and optionally narrowed by ``variable_spacing``),
    clipped to the image, and sampled. Consecutive samples at or above
    ``thresholds[i]`` form runs; gaps shorter than ``min_gap`` are bridged and
    runs shorter than ``min_length`` are dropped. Jitter offsets each line
    perpendicular to its direction using a seeded random generator and
    ``serpentine`` reverses every other line. When ``join_runs`` is on (which
    requires ``serpentine``), runs on adjacent lines of the same band are
    joined into continuous zig-zag strokes: the end of a run connects to the
    start of the nearest overlapping run on the next line, drawing the short
    connector, and a run without an overlapping partner starts a new stroke.
    Otherwise each run stays its own stroke. Output is in image pixel
    coordinates, always inside the image, with no zero-length strokes.

    Parameters
    ----------
    image : PIL.Image.Image
        Input image (any mode, converted to greyscale).
    settings : HatchSettings
        Algorithm configuration, in millimetres on paper.
    pixels_per_mm : float
        Working-image pixels per paper millimetre. Must be positive.
    pen_width_mm : float
        Pen tip width in millimetres. Must be positive; it is the lower bound
        for the effective line spacing.

    Returns
    -------
    list[LineString]
        Hatching strokes in image pixel coordinates (origin top-left).

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

    darkness = _darkness_map(image)
    height, width = darkness.shape
    if height == 0 or width == 0 or (width == 1 and height == 1):
        return []

    frame = box(0.0, 0.0, float(width - 1), float(height - 1))
    centre_x = (width - 1) / 2.0
    centre_y = (height - 1) / 2.0
    reach = 2.0 * math.hypot(width - 1, height - 1) + 1.0
    min_gap_px = settings.min_gap * pixels_per_mm
    min_length_px = settings.min_length * pixels_per_mm
    rng = random.Random(settings.seed)
    strokes: list[LineString] = []

    thresholds = (
        adaptive_thresholds(darkness, settings.thresholds)
        if settings.auto_thresholds
        else settings.thresholds
    )
    for angle, threshold in zip(settings.angles, thresholds, strict=True):
        raw_spacing = settings.spacing
        if settings.variable_spacing:
            raw_spacing *= 1.0 - 0.5 * threshold
        spacing_px = max(raw_spacing, pen_width_mm) * pixels_per_mm
        jitter_px = settings.jitter * pixels_per_mm

        theta = math.radians(angle)
        direction_x, direction_y = math.cos(theta), math.sin(theta)
        if abs(direction_x) < _EPS:
            direction_x = 0.0
        if abs(direction_y) < _EPS:
            direction_y = 0.0
        normal_x, normal_y = -direction_y, direction_x
        radius = max(
            abs(normal_x * (px - centre_x) + normal_y * (py - centre_y))
            for px in (0.0, float(width - 1))
            for py in (0.0, float(height - 1))
        )

        active: list[_SerpentinePath] = []
        line_index = 0
        offset = -radius
        while offset <= radius + _EPS:
            wobble = rng.uniform(-jitter_px, jitter_px) if jitter_px > 0.0 else 0.0
            origin_x = centre_x + normal_x * (offset + wobble)
            origin_y = centre_y + normal_y * (offset + wobble)
            infinite = LineString(
                [
                    (origin_x - direction_x * reach, origin_y - direction_y * reach),
                    (origin_x + direction_x * reach, origin_y + direction_y * reach),
                ]
            )
            clipped = infinite.intersection(frame)
            if isinstance(clipped, LineString) and clipped.length > 0.0:
                first = clipped.coords[0]
                last = clipped.coords[-1]
                length = math.hypot(last[0] - first[0], last[1] - first[1])
                count = max(2, math.ceil(length / _SAMPLE_STEP_PX) + 1)
                step_x = (last[0] - first[0]) / (count - 1)
                step_y = (last[1] - first[1]) / (count - 1)
                points: list[tuple[float, float]] = []
                values: list[float] = []
                for sample_index in range(count):
                    x = min(max(first[0] + sample_index * step_x, 0.0), float(width - 1))
                    y = min(max(first[1] + sample_index * step_y, 0.0), float(height - 1))
                    points.append((x, y))
                    values.append(_sample_darkness(darkness, x, y))

                kept = _keep_runs(
                    _runs_at_or_above(values, threshold),
                    length / (count - 1),
                    min_gap_px,
                    min_length_px,
                )
                if not settings.join_runs:
                    for start, end in kept:
                        begin, finish = points[start], points[end]
                        if settings.serpentine and line_index % 2 == 1:
                            begin, finish = finish, begin
                        stroke = LineString([begin, finish])
                        if stroke.is_valid and stroke.length > 0.0:
                            strokes.append(stroke)
                else:
                    next_active: list[_SerpentinePath] = []
                    continued: set[int] = set()
                    for start, end in kept:
                        entry, far = points[start], points[end]
                        if line_index % 2 == 1:
                            entry, far = far, entry
                        projection_start = (
                            points[start][0] * direction_x + points[start][1] * direction_y
                        )
                        projection_end = points[end][0] * direction_x + points[end][1] * direction_y
                        low, high = (
                            min(projection_start, projection_end),
                            max(projection_start, projection_end),
                        )
                        best_index = -1
                        best_distance = math.inf
                        for index, path in enumerate(active):
                            if index in continued or max(path.low, low) > min(path.high, high):
                                continue
                            distance = math.dist(path.end, entry)
                            if distance < best_distance:
                                best_index, best_distance = index, distance
                        if best_index < 0:
                            next_active.append(_SerpentinePath([entry, far], low, high, far))
                        else:
                            path = active[best_index]
                            path.points.extend((entry, far))
                            path.low, path.high, path.end = low, high, far
                            continued.add(best_index)
                            next_active.append(path)
                    for index, path in enumerate(active):
                        if index not in continued:
                            stroke = LineString(path.points)
                            if stroke.is_valid and stroke.length > 0.0:
                                strokes.append(stroke)
                    active = next_active
            offset += spacing_px
            line_index += 1

        for path in active:
            stroke = LineString(path.points)
            if stroke.is_valid and stroke.length > 0.0:
                strokes.append(stroke)

    return strokes


__all__ = [
    "PALETTE_ANGLE_STEP_DEG",
    "HatchSettings",
    "adaptive_thresholds",
    "hatch_strokes",
    "with_angle_offset",
]
