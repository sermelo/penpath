"""Sketch Lines PFM (Pen Follower Module) implementation.

Port of ``PFMSketchLinesBasic`` and ``AbstractSketchPFM`` from DrawingBotV3
(v1.6.25-stable-free). The algorithm repeatedly picks the darkest part of a
working copy of the image, walks dark rays from there, draws them, and lightens
the pixels it covered so the next stroke moves on to a different region.
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
_NEARLY_BLANK_MEAN = 252.5
_BLANK_CANVAS_MEAN = 254.0


class SketchLinesSettings(BaseModel):
    """Settings for the Sketch Lines PFM algorithm.

    Defaults mirror DrawingBotV3 v1.6.25-stable-free's registered settings
    (``Register.registerPFMSettings``), except where a value is expressed in
    penpath's image-pixel scale.

    Parameters
    ----------
    line_density : float
        Overall ink density multiplier (0.01 - 10.0). Higher = more ink.
    max_fill : float
        Maximum ink coverage as a percentage (1 - 100). Any source tone
        darker than ``255 * (1 - max_fill / 100)`` is treated as black. 100
        keeps the full range; the shipped default is lower so solid black
        areas stay plottable.
    min_length : float
        Minimum line length in image pixels (1 - 1000). Reference default 2.
    max_length : float
        Maximum line length in image pixels (1 - 5000). Reference default 40.
    angle_range : tuple[float, float]
        Min/max random start angle in degrees (-360 - 360). The reference
        band is -72 to -52 degrees.
    shading_enabled : bool
        Whether to search only two opposite directions once the image is
        halfway to its target luminance.
    squiggle_enabled : bool
        Whether to add perpendicular noise to each segment. This is a
        penpath addition; the reference has no such noise, so it is off by
        default.
    erase_enabled : bool
        Whether drawing lightens the working image. When false the image
        never lightens, so only ``max_strokes`` stops the run and the result
        is dense and dark.
    seed : int | None
        Random seed for deterministic output. None = non-deterministic.
    search_angle_step : float
        Angular step in degrees between candidate rays (0.1 - 90). The
        reference's 20 angle tests over 360 degrees give 18 degrees.
    sample_step : float
        Pixel size of the tiles used to find the next darkest pixel.
    erase_min : float
        Brightness added to a very dark pixel when a stroke is drawn. The
        reference uses 50; 35 is calibrated for penpath's pixel scale.
    erase_max : float
        Brightness added to a very bright pixel when a stroke is drawn. The
        reference uses 125; 80 is calibrated for penpath's pixel scale.
    tone : float
        Weight of the cubic easing in the erase amount (0 - 1).
    erase_radius_min : float
        Brush radius in pixels used to erase a very dark pixel.
    erase_radius_max : float
        Brush radius in pixels used to erase a very bright pixel.
    squiggle_max_deviation : float
        How far above the starting darkness a squiggle may wander, as a
        fraction of 253.5 (default 0.25, i.e. about +63 luminance).
    squiggle_min_length : int
        Number of segments before a squiggle may end on the darkness rule.
        The reference uses 25; 50 is calibrated for penpath's pixel scale.
    squiggle_max_length : int
        Hard upper bound on the number of segments in one squiggle.
    shading_threshold : float
        Fraction of luminance progress at which shading starts (0 - 1).
    max_strokes : int | None
        Hard cap on strokes, needed when erasing is disabled. When None a
        generous cap is derived from the image size and line density.
    """

    line_density: float = Field(default=0.75, ge=0.01, le=10.0)
    max_fill: float = Field(default=80.0, ge=1.0, le=100.0)
    min_length: float = Field(default=2.0, ge=1.0, le=1000.0)
    max_length: float = Field(default=40.0, ge=1.0, le=5000.0)
    angle_range: tuple[float, float] = Field(default=(-72.0, -52.0))
    shading_enabled: bool = False
    squiggle_enabled: bool = False
    erase_enabled: bool = True
    seed: int | None = None
    search_angle_step: float = Field(default=18.0, ge=0.1, le=90.0)
    sample_step: float = Field(default=10.0, ge=1.0, le=100.0)
    erase_min: float = Field(default=35.0, ge=0.0, le=255.0)
    erase_max: float = Field(default=80.0, ge=0.0, le=255.0)
    tone: float = Field(default=0.5, ge=0.0, le=1.0)
    erase_radius_min: float = Field(default=1.0, ge=0.0, le=50.0)
    erase_radius_max: float = Field(default=1.0, ge=0.0, le=50.0)
    squiggle_max_deviation: float = Field(default=0.25, ge=0.0, le=10.0)
    squiggle_min_length: int = Field(default=50, ge=1, le=100000)
    squiggle_max_length: int = Field(default=500, ge=1, le=100000)
    shading_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    max_strokes: int | None = Field(default=None, ge=1)

    @field_validator("angle_range")
    @classmethod
    def validate_angle_range(cls, v: tuple[float, float]) -> tuple[float, float]:
        if len(v) != 2:
            raise ValueError("angle_range must be a tuple of 2 floats")
        min_angle, max_angle = v
        if not (-360.0 <= min_angle <= 360.0 and -360.0 <= max_angle <= 360.0):
            raise ValueError("angle_range values must be in [-360, 360]")
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
        if self.erase_radius_min > self.erase_radius_max:
            raise ValueError("erase_radius_min must be <= erase_radius_max")


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
    last in-bounds pixel rather than reporting a failure. A ray with no prefix
    long enough reports white so it cannot win as the darkest candidate.
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
    candidates = np.where(eligible, means, np.inf)
    has_eligible = eligible.any(axis=1)
    best = np.where(has_eligible, np.argmin(candidates, axis=1), last)
    zero_length = last <= 0
    row = np.arange(len(dxs))
    chosen_mean = np.where(zero_length, _WHITE, means[row, best])
    return chosen_mean, xs[row, best], ys[row, best]


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


def _erase_progress(luminance: float, tone: float) -> float:
    """Cubic/linear blend used by ``AbstractSketchPFM.eraseGeometry``."""
    x_progress = min(1.0, max(0.0, luminance / _WHITE))
    return x_progress**3 * tone + x_progress * (1.0 - tone)


def _erase_amount(luminance: float, erase_min: float, erase_max: float, tone: float) -> int:
    """Brightness added by ``AbstractSketchPFM.eraseGeometry`` for a pixel."""
    return int(erase_min + _erase_progress(luminance, tone) * (erase_max - erase_min))


def _brush_offsets(radius: float) -> list[tuple[int, int]]:
    """Pixel offsets inside a round brush of the given radius."""
    extent = max(0, math.floor(radius))
    squared = radius * radius
    return [
        (dx, dy)
        for dy in range(-extent, extent + 1)
        for dx in range(-extent, extent + 1)
        if dx * dx + dy * dy <= squared
    ]


def _apply_erase(
    working: NDArray[np.float64],
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    erase_min: float,
    erase_max: float,
    tone: float,
    radius_min: float = 1.0,
    radius_max: float = 1.0,
) -> None:
    """Lighten pixels under a segment with the reference's round erase brush."""
    h, w = working.shape
    progress = _erase_progress(float(working[y0, x0]), tone)
    amount = int(erase_min + progress * (erase_max - erase_min))
    if amount <= 0:
        return
    radius = radius_min + progress * (radius_max - radius_min)
    offsets = _brush_offsets(radius)
    covered: set[tuple[int, int]] = set()
    for px, py in _bresenham_line(x0, y0, x1, y1):
        for dx, dy in offsets:
            x, y = px + dx, py + dy
            if 0 <= x < w and 0 <= y < h and (x, y) not in covered:
                covered.add((x, y))
                working[y, x] = min(_WHITE, working[y, x] + amount)


def sketch_lines(image: Image.Image, settings: SketchLinesSettings) -> list[LineString]:
    """Generate sketch lines from an image using the Sketch Lines PFM algorithm.

    Strokes are returned in image pixel coordinates (origin top-left) and are
    always inside the image. Drawing lightens the working image, so the run
    stops when its average luminance reaches the target given by
    ``line_density``. On a nearly blank canvas (mean from 252.5 to below 254),
    that average is taken over the ink-bearing pixels only: a sparse palette
    channel is mostly white, so a whole-canvas average collapses the stop
    target and ends the run after a handful of strokes. Canvases below 252.5
    and near-blank canvases at 254 or above keep the whole-canvas rule. With
    ``erase_enabled=False`` the image never lightens; only the stroke cap stops
    the run and the result is dense and dark.

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
    black_point = _WHITE * (1.0 - settings.max_fill / 100.0)
    if black_point > 0.0:
        np.maximum(working, black_point, out=working)
    h, w = working.shape
    if h == 0 or w == 0:
        return []

    min_len = int(max(1, settings.min_length))
    max_len = int(max(min_len, settings.max_length))
    line_density = max(0.01, settings.line_density)
    angle_min, angle_max = settings.angle_range
    sample_step = int(settings.sample_step)
    num_tests = max(1, round(360.0 / settings.search_angle_step))

    canvas_avg = float(np.mean(working))
    ink_pixels = working < _WHITE
    sparse_canvas = bool(ink_pixels.any()) and _NEARLY_BLANK_MEAN <= canvas_avg < _BLANK_CANVAS_MEAN
    progress_pixels = ink_pixels if sparse_canvas else None
    initial_avg = (
        float(np.mean(working[progress_pixels])) if progress_pixels is not None else canvas_avg
    )
    if settings.max_strokes is not None:
        max_strokes = settings.max_strokes
    elif settings.erase_enabled:
        max_strokes = max(100, min(10000, int(w * h * line_density * 0.1)))
    else:
        max_strokes = max(100, min(200, int(w * h * line_density * 0.02)))

    lines: list[LineString] = []
    fails = 0
    while len(lines) < max_strokes and fails < _MAX_FAILS:
        canvas_avg = float(np.mean(working))
        current_avg = (
            float(np.mean(working[progress_pixels])) if progress_pixels is not None else canvas_avg
        )
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

        current_x, current_y = start_x, start_y
        points: list[tuple[float, float]] = [(float(start_x), float(start_y))]
        shading = bool(settings.shading_enabled and lum_progress > settings.shading_threshold)

        for s in range(settings.squiggle_max_length):
            line_len = rng.randint(min_len, max_len)
            start_angle = rng.uniform(angle_min, angle_max)
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
                break

            if settings.erase_enabled:
                if s >= settings.squiggle_min_length and (
                    avg_lum > allowable or avg_lum > canvas_avg
                ):
                    break
            elif avg_lum > allowable:
                break

            if settings.squiggle_enabled and s > 0:
                segment = _add_squiggle(
                    current_x,
                    current_y,
                    next_x,
                    next_y,
                    min_len,
                    2.0,
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
                    settings.erase_radius_min,
                    settings.erase_radius_max,
                )
            current_x, current_y = next_x, next_y

        if len(points) >= 2:
            line = LineString(points)
            if line.is_valid and line.length > 0:
                lines.append(line)
                fails = 0
                continue
        working[current_y, current_x] = _WHITE
        fails += 1

    return lines


__all__ = ["SketchLinesSettings", "sketch_lines"]
