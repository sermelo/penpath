"""Sketch Lines PFM (Pen Follower Module) implementation.

Port of ``PFMSketchLinesBasic`` from DrawingBotV3 (v1.6.25-stable). The
algorithm repeatedly picks the darkest part of a working copy of the image,
walks a dark ray from there, draws it, and lightens the pixels it covered so
the next stroke moves on to a different region.
"""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, Field, field_validator
from shapely import LineString

if TYPE_CHECKING:
    from PIL import Image

_DESIRED_LUMINANCE = 253.5
_MAX_FAILS = 1000
_WHITE = 255.0


class SketchLinesSettings(BaseModel):
    """Settings for the Sketch Lines PFM algorithm.

    Parameters
    ----------
    line_density : float
        Overall line density multiplier (0.01 - 10.0). Higher = more ink.
    min_length : float
        Minimum line length in pixels (1 - 1000).
    max_length : float
        Maximum line length in pixels (1 - 5000).
    angle_range : tuple[float, float]
        Min/max start angle in degrees (0 - 360).
    shading_enabled : bool
        Whether to search only two opposite directions once the image is
        halfway to its target luminance.
    squiggle_enabled : bool
        Whether to add perpendicular noise to each segment.
    erase_enabled : bool
        Whether drawing lightens the working image. When false the image
        never lightens, so only ``max_strokes`` stops the run and the result
        is dense and dark.
    seed : int | None
        Random seed for deterministic output. None = non-deterministic.
    search_angle_step : float
        Angular step in degrees between candidate rays (0.1 - 90).
    sample_step : float
        Pixel size of the tiles used to find the next darkest pixel.
    erase_min : float
        Brightness added to a very dark pixel when a stroke is drawn.
    erase_max : float
        Brightness added to a very bright pixel when a stroke is drawn.
    tone : float
        Weight of the cubic easing in the erase amount (0 - 1).
    squiggle_max_deviation : float
        How far above the starting darkness a squiggle may wander, as a
        fraction of 253.5 (default 0.25, i.e. about +63 luminance).
    squiggle_min_length : int
        Number of segments before a squiggle may end on the darkness rule.
    squiggle_max_length : int
        Hard upper bound on the number of segments in one squiggle.
    shading_threshold : float
        Fraction of luminance progress at which shading starts (0 - 1).
    max_strokes : int | None
        Hard cap on strokes, needed when erasing is disabled. When None a
        generous cap is derived from the image size and line density.
    """

    line_density: float = Field(default=0.75, ge=0.01, le=10.0)
    min_length: float = Field(default=10.0, ge=1.0, le=1000.0)
    max_length: float = Field(default=100.0, ge=1.0, le=5000.0)
    angle_range: tuple[float, float] = Field(default=(0.0, 360.0))
    shading_enabled: bool = False
    squiggle_enabled: bool = True
    erase_enabled: bool = True
    seed: int | None = None
    search_angle_step: float = Field(default=5.0, ge=0.1, le=90.0)
    sample_step: float = Field(default=10.0, ge=1.0, le=100.0)
    erase_min: float = Field(default=50.0, ge=0.0, le=255.0)
    erase_max: float = Field(default=125.0, ge=0.0, le=255.0)
    tone: float = Field(default=0.5, ge=0.0, le=1.0)
    squiggle_max_deviation: float = Field(default=0.25, ge=0.0, le=10.0)
    squiggle_min_length: int = Field(default=25, ge=1, le=100000)
    squiggle_max_length: int = Field(default=500, ge=1, le=100000)
    shading_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    max_strokes: int | None = Field(default=None, ge=1)

    @field_validator("angle_range")
    @classmethod
    def validate_angle_range(cls, v: tuple[float, float]) -> tuple[float, float]:
        if len(v) != 2:
            raise ValueError("angle_range must be a tuple of 2 floats")
        min_angle, max_angle = v
        if not (0.0 <= min_angle <= 360.0 and 0.0 <= max_angle <= 360.0):
            raise ValueError("angle_range values must be in [0, 360]")
        if min_angle > max_angle:
            raise ValueError("angle_range min must be <= max")
        return v

    def model_post_init(self, __context: object) -> None:
        if self.min_length > self.max_length:
            raise ValueError("min_length must be <= max_length")
        if self.squiggle_min_length > self.squiggle_max_length:
            raise ValueError("squiggle_min_length must be <= squiggle_max_length")
        if self.erase_min > self.erase_max:
            raise ValueError("erase_min must be <= erase_max")


def _bresenham_line(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
    """Return the integer pixels on the segment from (x0, y0) to (x1, y1)."""
    points: list[tuple[int, int]] = []
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy

    x, y = x0, y0
    while True:
        points.append((x, y))
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x += sx
        if e2 < dx:
            err += dx
            y += sy
    return points


def _sample_rays(
    luminance: NDArray[np.float64],
    x0: int,
    y0: int,
    dxs: NDArray[np.int64],
    dys: NDArray[np.int64],
    min_length: int,
) -> tuple[NDArray[np.float64], NDArray[np.int64], NDArray[np.int64]]:
    """Apply the running-mean endpoint rule to a batch of rays at once.

    Following ``LuminanceTestLine.addSample``, each endpoint is the pixel where
    the mean of all sampled pixels so far is lowest, considering only prefixes
    longer than ``min_length``. Reaching the image edge ends a ray and uses its
    last in-bounds pixel rather than reporting a failure.
    """
    h, w = luminance.shape
    lengths = np.maximum(np.abs(dxs), np.abs(dys)) + 1
    n_max = int(lengths.max())
    t = np.arange(n_max, dtype=np.float64)[None, :] / np.maximum(lengths - 1, 1)[:, None]
    xs = np.rint(x0 + dxs[:, None] * t).astype(np.int64)
    ys = np.rint(y0 + dys[:, None] * t).astype(np.int64)

    inside = (
        (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h) & (np.arange(n_max)[None, :] < lengths[:, None])
    )
    outside = ~inside
    has_outside = outside.any(axis=1)
    edge = np.argmax(outside, axis=1)
    last = np.where(has_outside, edge - 1, lengths - 1)
    valid = np.arange(n_max)[None, :] <= last[:, None]

    values = np.where(valid, luminance[np.clip(ys, 0, h - 1), np.clip(xs, 0, w - 1)], 0.0)
    counts = np.cumsum(valid, axis=1)
    means = np.cumsum(values, axis=1) / np.maximum(counts, 1)
    eligible = counts > min_length
    eligible &= counts > 0
    fallback = np.maximum(last, 0)
    candidates = np.where(eligible, means, np.inf)
    fallback_mask = ~eligible.any(axis=1)
    best = np.where(fallback_mask, fallback, np.argmin(candidates, axis=1))
    row = np.arange(len(dxs))
    return means[row, best], xs[row, best], ys[row, best]


def _sample_line_luminance(
    luminance: NDArray[np.float64],
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    min_length: int,
) -> tuple[float, int, int]:
    """Walk one ray and return its lowest running mean and the pixel where it occurs."""
    if (x1, y1) == (x0, y0):
        return _WHITE, x0, y0
    lum, end_x, end_y = _sample_rays(
        luminance,
        x0,
        y0,
        np.array([x1 - x0], dtype=np.int64),
        np.array([y1 - y0], dtype=np.int64),
        min_length,
    )
    return float(lum[0]), int(end_x[0]), int(end_y[0])


def _find_darkest_pixel(
    luminance: NDArray[np.float64],
    sample_step: int,
    rng: random.Random,
) -> tuple[int, int]:
    """Find the darkest pixel using the darkest tile then its darkest pixel."""
    h, w = luminance.shape
    tiles_x = (w + sample_step - 1) // sample_step
    tiles_y = (h + sample_step - 1) // sample_step
    padded = np.full((tiles_y * sample_step, tiles_x * sample_step), _WHITE, dtype=np.float64)
    padded[:h, :w] = luminance
    tiles = padded.reshape(tiles_y, sample_step, tiles_x, sample_step)
    tile_means = np.mean(tiles, axis=(1, 3))

    flat = int(np.argmin(tile_means))
    ty, tx = divmod(flat, tiles_x)
    region = tiles[ty, :, tx, :]
    index = int(np.argmin(region))
    darkest_y = ty * sample_step + index // sample_step
    darkest_x = tx * sample_step + index % sample_step

    if tile_means[ty, tx] >= 254.0:
        darkest_x = rng.randrange(w)
        darkest_y = rng.randrange(h)

    return min(darkest_x, w - 1), min(darkest_y, h - 1)


def _find_darkest_line(
    luminance: NDArray[np.float64],
    x0: int,
    y0: int,
    min_length: int,
    max_length: int,
    shading: bool,
    start_angle: float,
    num_tests: int,
    shading_angle: float,
) -> tuple[float, int, int]:
    """Search candidate rays from (x0, y0) and return the darkest endpoint found.

    With ``shading`` only the two opposite directions separated by
    ``shading_angle`` are tested; otherwise ``num_tests`` rays cover the full
    circle. Rays are not clamped: the edge rule lives in
    :func:`_sample_line_luminance`, which uses the last in-bounds pixel.
    """
    best_lum = _WHITE
    best_x, best_y = x0, y0

    if shading:
        angles: tuple[float, ...] = (start_angle, start_angle + shading_angle)
    else:
        step = 360.0 / max(1, num_tests)
        angles = tuple(start_angle + step * i for i in range(max(1, num_tests)))

    radians = np.radians(np.asarray(angles, dtype=np.float64))
    dxs = np.trunc(np.cos(radians) * max_length).astype(np.int64)
    dys = np.trunc(np.sin(radians) * max_length).astype(np.int64)
    lums, end_xs, end_ys = _sample_rays(luminance, x0, y0, dxs, dys, min_length)

    best = int(np.argmin(lums))
    if lums[best] < best_lum:
        best_lum, best_x, best_y = float(lums[best]), int(end_xs[best]), int(end_ys[best])
    return best_lum, best_x, best_y


def _add_squiggle(
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    squiggle_length: int,
    max_deviation: float,
    rng: random.Random,
    bounds: tuple[int, int] | None = None,
) -> list[tuple[float, float]]:
    """Add perpendicular noise to a segment, keeping every point in bounds."""
    dx = x1 - x0
    dy = y1 - y0
    length = math.hypot(dx, dy)

    if length < squiggle_length or max_deviation <= 0:
        return [(float(x0), float(y0)), (float(x1), float(y1))]

    perp_x = -dy / length
    perp_y = dx / length
    num_segments = max(2, int(length / squiggle_length))
    points: list[tuple[float, float]] = [(float(x0), float(y0))]

    for i in range(1, num_segments):
        t = i / num_segments
        noise = rng.uniform(-max_deviation, max_deviation)
        sx = x0 + dx * t + perp_x * noise
        sy = y0 + dy * t + perp_y * noise
        if bounds:
            w, h = bounds
            sx = max(0.0, min(float(w - 1), sx))
            sy = max(0.0, min(float(h - 1), sy))
        points.append((sx, sy))

    end_x, end_y = float(x1), float(y1)
    if bounds:
        w, h = bounds
        end_x = max(0.0, min(float(w - 1), end_x))
        end_y = max(0.0, min(float(h - 1), end_y))
    points.append((end_x, end_y))
    return points


def _erase_amount(luminance: float, erase_min: float, erase_max: float, tone: float) -> int:
    """Brightness added by ``AbstractSketchPFM.eraseGeometry`` for a pixel."""
    x_progress = min(1.0, max(0.0, luminance / _WHITE))
    y_progress = x_progress**3 * tone + x_progress * (1.0 - tone)
    return int(erase_min + y_progress * (erase_max - erase_min))


def _apply_erase(
    working: NDArray[np.float64],
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    erase_min: float,
    erase_max: float,
    tone: float,
) -> None:
    """Lighten the pixels under a segment toward white by the erase amount."""
    h, w = working.shape
    amount = _erase_amount(float(working[y0, x0]), erase_min, erase_max, tone)
    if amount <= 0:
        return
    for px, py in _bresenham_line(x0, y0, x1, y1):
        if 0 <= px < w and 0 <= py < h:
            working[py, px] = min(_WHITE, working[py, px] + amount)


def sketch_lines(image: Image.Image, settings: SketchLinesSettings) -> list[LineString]:
    """Generate sketch lines from an image using the Sketch Lines PFM algorithm.

    Strokes are returned in image pixel coordinates (origin top-left) and are
    always inside the image. Drawing lightens the working image, so the run
    stops when its average luminance reaches the target given by
    ``line_density``. With ``erase_enabled=False`` the image never lightens;
    only the stroke cap stops the run and the result is dense and dark.

    Parameters
    ----------
    image : PIL.Image.Image
        Input image (any mode, converted to grayscale).
    settings : SketchLinesSettings
        Algorithm configuration.

    Returns
    -------
    list[LineString]
        Strokes in image pixel coordinates.
    """
    rng = random.Random(settings.seed)
    gray = image.convert("L") if image.mode != "L" else image
    working = np.asarray(gray, dtype=np.float64).copy()
    h, w = working.shape
    if h == 0 or w == 0:
        return []

    min_len = int(max(1, settings.min_length))
    max_len = int(max(min_len, settings.max_length))
    line_density = max(0.01, settings.line_density)
    angle_min, angle_max = settings.angle_range
    sample_step = int(settings.sample_step)
    num_tests = max(1, round(360.0 / settings.search_angle_step))
    squiggle_dev_px = 2.0

    initial_avg = float(np.mean(working))
    if settings.max_strokes is not None:
        max_strokes = settings.max_strokes
    elif settings.erase_enabled:
        max_strokes = max(100, min(10000, int(w * h * line_density * 0.1)))
    else:
        max_strokes = max(100, min(200, int(w * h * line_density * 0.02)))

    lines: list[LineString] = []
    fails = 0
    while len(lines) < max_strokes and fails < _MAX_FAILS:
        current_avg = float(np.mean(working))
        if settings.erase_enabled:
            if initial_avg >= _DESIRED_LUMINANCE:
                break
            lum_progress = (current_avg - initial_avg) / (
                (_DESIRED_LUMINANCE - initial_avg) * line_density
            )
            if lum_progress >= 1.0:
                break
        else:
            lum_progress = 0.0

        start_x, start_y = _find_darkest_pixel(working, sample_step, rng)
        initial_darkness = float(working[start_y, start_x])
        if settings.erase_enabled:
            allowable = initial_darkness + max(
                1.0, _DESIRED_LUMINANCE * settings.squiggle_max_deviation
            )
        else:
            allowable = _DESIRED_LUMINANCE

        start_angle = rng.uniform(angle_min, angle_max)
        current_x, current_y = start_x, start_y
        points: list[tuple[float, float]] = [(float(start_x), float(start_y))]
        failed = False
        shading = bool(settings.shading_enabled and lum_progress > settings.shading_threshold)

        for s in range(settings.squiggle_max_length):
            line_len = rng.randint(min_len, max_len)
            avg_lum, next_x, next_y = _find_darkest_line(
                working,
                current_x,
                current_y,
                min_len,
                line_len,
                shading,
                start_angle,
                num_tests,
                180.0,
            )

            if (next_x, next_y) == (current_x, current_y):
                failed = True
                break

            if settings.erase_enabled:
                if s >= settings.squiggle_min_length and (
                    avg_lum > allowable or avg_lum > current_avg
                ):
                    break
            elif avg_lum > allowable:
                failed = True
                break

            if settings.squiggle_enabled and s > 0:
                segment = _add_squiggle(
                    current_x,
                    current_y,
                    next_x,
                    next_y,
                    min_len,
                    squiggle_dev_px,
                    rng,
                    (w, h),
                )
                points.extend(segment[1:])
            else:
                points.append((float(next_x), float(next_y)))

            if settings.erase_enabled:
                _apply_erase(
                    working,
                    current_x,
                    current_y,
                    next_x,
                    next_y,
                    settings.erase_min,
                    settings.erase_max,
                    settings.tone,
                )
            current_x, current_y = next_x, next_y

        if len(points) >= 2 and not failed:
            line = LineString(points)
            if line.is_valid and line.length > 0:
                lines.append(line)
                fails = 0
                continue
        working[start_y, start_x] = _WHITE
        fails += 1

    return lines


__all__ = ["SketchLinesSettings", "sketch_lines"]
