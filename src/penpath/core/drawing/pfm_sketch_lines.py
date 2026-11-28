"""Sketch Lines PFM (Pen Follower Module) implementation.

Port of ``PFMSketchLinesBasic`` and ``AbstractSketchPFM`` from DrawingBotV3
(v1.6.25-stable-free). The algorithm repeatedly picks the darkest part of a
working copy of the image, walks dark rays from there, draws them, and lightens
the pixels it covered so the next stroke moves on to a different region. The
shipped defaults add a contrast-adaptive tone budget: search scores follow
local source tone and stop earlier where the source is textured, so dark areas
keep white gaps instead of becoming one solid mass.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

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
_TONE_DESIRED_LUMINANCE = 254.2
_TEXTURED_FRACTION = 0.18
_WHITE_STOP_RUN = 8
_DARKEST_QUANTILE = 0.10
# The cap counts one working-pixel centre per stroke step; a simulated 0.3 mm
# pen covers about 1.2 of those pixels, so the engine budget is scaled down to
# keep the simulated coverage at or below the named cap.
_TONE_INK_BLEED_FACTOR = 0.83
_LEGACY_MAX_FILL = 80.0
_LEGACY_LINE_DENSITY = 0.75


class SketchLinesSettings(BaseModel):
    """Settings for the Sketch Lines PFM algorithm.

    The beam-search and erase rules follow DrawingBotV3 v1.6.25-stable-free
    (``Register.registerPFMSettings``). Pixel values are in penpath's image
    scale, and the tone defaults are calibrated for photos (LUC-128): neutral
    ``tone_coverage=1``, ``tone_exponent=1`` and ``texture_limit=0`` restore
    the pre-LUC-128 search.

    Parameters
    ----------
    line_density : float
        Fraction of the luminance progress at which drawing stops
        (0.01 - 10.0). Higher = more ink.
    max_fill : float
        Maximum ink coverage as a percentage (1 - 100). Any source tone
        darker than ``255 * (1 - max_fill / 100)`` is treated as black. 100
        keeps the full range; the shipped default is lower so solid black
        areas stay plottable.
    white_threshold : float
        Luminance fraction (0 - 1) above which source pixels are blank paper.
        Rays and strokes stop at the last darker pixel before a run of at least
        eight such pixels, using the original grayscale source rather than the
        erasing working image. The default 0.92 is about 235/255; 1.0 opts out
        of the rule.
    tone_coverage : float
        Fraction of each pixel's distance to white that may be spent on ink
        (0 - 1). 1 keeps the legacy rule where a pixel is drawn until it is
        white; lower values stop a dark tone earlier and leave white gaps.
    tone_exponent : float
        Shape of the tone curve (0 - 2). 1 spends ink in proportion to
        darkness; below 1 gives mid tones more of the dark tones' ink so
        they show a distinct hatch step.
    texture_limit : float
        How much local texture reduces ``tone_coverage`` in dark areas
        (0 - 1). Textured dark tones get a higher stop point than flat ones,
        so hair, foliage and slopes do not turn into solid black.
    max_tone_ink : float
        Largest share of the darkest source pixels that may receive ink
        (0 - 1). The darkest tenth of the original grayscale is tracked while
        strokes are drawn and the run stops when that share is reached, so a
        tree mass or hair keeps white gaps instead of turning solid black.
        The default 0.85 leaves about 15% uninked; 1.0 opts out of the cap.
        Only the tone rule uses the cap; flat shapes, palette channels and
        Sketch Squares keep their existing behaviour.
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

    line_density: float = Field(default=0.97, ge=0.01, le=10.0)
    max_fill: float = Field(default=90.0, ge=1.0, le=100.0)
    white_threshold: float = Field(default=0.92, ge=0.0, le=1.0)
    tone_coverage: float = Field(default=0.5, ge=0.0, le=1.0)
    tone_exponent: float = Field(default=0.55, ge=0.0, le=2.0)
    texture_limit: float = Field(default=0.8, ge=0.0, le=1.0)
    max_tone_ink: float = Field(default=0.85, ge=0.0, le=1.0)
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


def _box_mean(values: NDArray[np.float64], radius: int) -> NDArray[np.float64]:
    """Return the mean of each pixel's square window using an integral image."""
    height, width = values.shape
    padded = np.pad(values, radius, mode="edge")
    integral = np.pad(padded, ((1, 0), (1, 0))).cumsum(axis=0).cumsum(axis=1)
    size = 2 * radius + 1
    total = (
        integral[size : size + height, size : size + width]
        - integral[:height, size : size + width]
        - integral[size : size + height, :width]
        + integral[:height, :width]
    )
    return total / (size * size)


def _local_texture(
    source: NDArray[np.float64],
    radius: int,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Return the local mean and standard deviation of the source luminance."""
    mean = _box_mean(source, radius)
    variance = np.maximum(0.0, _box_mean(source * source, radius) - mean * mean)
    return mean, np.sqrt(variance)


def _tone_budgets(
    source: NDArray[np.float64],
    mean: NDArray[np.float64],
    std: NDArray[np.float64],
    tone_coverage: float,
    tone_exponent: float,
    texture_limit: float,
) -> NDArray[np.float64]:
    """Return the luminance worth of ink each pixel may still receive.

    A flat pixel may gain at most ``255 * tone_coverage * darkness**exponent``
    before it stops receiving ink. Local texture, measured as the standard
    deviation of the source in a square window, reduces that budget in dark
    areas only, so textured dark regions keep white gaps between strokes.
    """
    if tone_coverage >= 1.0 and math.isclose(tone_exponent, 1.0) and texture_limit <= 0.0:
        return np.zeros_like(source)
    darkness = np.clip((_WHITE - source) / _WHITE, 0.0, 1.0)
    texture = np.clip(std / 24.0, 0.0, 1.0) * darkness
    budget = tone_coverage * darkness**tone_exponent * (1.0 - texture_limit * texture)
    return _WHITE * budget


def _sample_rays(
    luminance: NDArray[np.float64],
    x0: int,
    y0: int,
    dxs: NDArray[np.int64],
    dys: NDArray[np.int64],
    min_length: int,
    source: NDArray[np.float64] | None = None,
    white_cutoff: float | None = None,
) -> tuple[NDArray[np.float64], NDArray[np.int64], NDArray[np.int64]]:
    """Apply the running-mean endpoint rule to a batch of rays at once.

    Following ``LuminanceTestLine.addSample``, each endpoint is the pixel where
    the mean of all sampled pixels so far is lowest, considering only prefixes
    longer than ``min_length``. Reaching the image edge ends a ray and uses its
    last in-bounds pixel rather than reporting a failure. When ``source`` and
    ``white_cutoff`` are given, the first run of at least ``_WHITE_STOP_RUN``
    source pixels at or above the cutoff also ends the ray, at the last darker
    pixel before it; a dark pixel beyond that run cannot be reached. A ray with
    no prefix long enough reports white so it cannot win as the darkest
    candidate.
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
    if source is not None and white_cutoff is not None:
        source_values = source[np.clip(ys, 0, h - 1), np.clip(xs, 0, w - 1)]
        blocked = inside & (source_values >= white_cutoff)
        run = np.zeros_like(blocked)
        if blocked.shape[1] >= _WHITE_STOP_RUN:
            windows = [
                blocked[:, offset : blocked.shape[1] - _WHITE_STOP_RUN + 1 + offset]
                for offset in range(_WHITE_STOP_RUN)
            ]
            run[:, : windows[0].shape[1]] = np.logical_and.reduce(windows)
        last = np.where(run.any(axis=1), np.minimum(last, np.argmax(run, axis=1) - 1), last)
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
    source: NDArray[np.float64] | None = None,
    white_cutoff: float | None = None,
) -> tuple[float, int, int]:
    """Search candidate rays from (x0, y0) and return the darkest endpoint found.

    With ``shading`` only the two opposite directions separated by
    ``shading_angle`` are tested; otherwise ``num_tests`` rays cover the full
    circle. Rays are not clamped: the edge and white-source rules live in
    :func:`_sample_rays`, which uses the last eligible pixel.
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
    lums, end_xs, end_ys = _sample_rays(
        luminance, x0, y0, dxs, dys, min_length, source, white_cutoff
    )

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
    *,
    score: NDArray[np.float64] | None = None,
    tone_offsets: NDArray[np.float64] | None = None,
    caps: NDArray[np.float64] | None = None,
    inked: NDArray[np.bool_] | None = None,
    darkest: NDArray[np.bool_] | None = None,
) -> int:
    """Lighten pixels under a segment with the reference's round erase brush.

    When ``inked`` and ``darkest`` are given, mark the centre pixel of each
    Bresenham step and return how many new darkest-tone pixels it inked. The
    count is used by the per-tone cap; the erase brush itself is unchanged.
    """
    h, w = working.shape
    progress = _erase_progress(float(working[y0, x0]), tone)
    amount = int(erase_min + progress * (erase_max - erase_min))
    if amount <= 0:
        return 0
    radius = radius_min + progress * (radius_max - radius_min)
    offsets = _brush_offsets(radius)
    covered: set[tuple[int, int]] = set()
    newly_inked = 0
    for px, py in _bresenham_line(x0, y0, x1, y1):
        if (
            inked is not None
            and darkest is not None
            and 0 <= px < w
            and 0 <= py < h
            and darkest[py, px]
            and not inked[py, px]
        ):
            inked[py, px] = True
            newly_inked += 1
        for dx, dy in offsets:
            x, y = px + dx, py + dy
            if 0 <= x < w and 0 <= y < h and (x, y) not in covered:
                covered.add((x, y))
                working[y, x] = min(_WHITE, working[y, x] + amount)
                if score is not None and tone_offsets is not None and caps is not None:
                    score[y, x] = min(caps[y, x], working[y, x] + tone_offsets[y, x])
    return newly_inked


class _SketchEngineSettings(Protocol):
    """Settings fields shared by every PFM that uses the sketch engine."""

    line_density: float
    max_fill: float
    white_threshold: float
    min_length: float
    max_length: float
    erase_enabled: bool
    seed: int | None
    search_angle_step: float
    sample_step: float
    erase_min: float
    erase_max: float
    tone: float
    erase_radius_min: float
    erase_radius_max: float
    squiggle_max_deviation: float
    squiggle_min_length: int
    squiggle_max_length: int
    max_strokes: int | None
    tone_coverage: float
    tone_exponent: float
    texture_limit: float
    max_tone_ink: float

    @property
    def model_fields_set(self) -> set[str]:
        """Fields explicitly set by the caller, used for the legacy fallback."""
        ...


_AngleProvider = Callable[[random.Random, int, int, int], float]


def _run_sketch_engine(
    image: Image.Image,
    settings: _SketchEngineSettings,
    angle_provider: _AngleProvider,
    shading_enabled: bool,
    squiggle_enabled: bool,
    shading_threshold: float,
) -> list[LineString]:
    """Run the shared sketch engine, asking ``angle_provider`` for each ray angle.

    The provider is called after the segment length is drawn, with the RNG, the
    current pixel and the segment index, so Sketch Lines keeps its exact random
    draw order while other PFMs can supply a deterministic angle field. Ray
    endpoints are capped at runs of near-white source pixels, so a stroke never
    bridges blank paper even when an earlier stroke erased the pixels around it.
    """
    rng = random.Random(settings.seed)
    gray = image.convert("L") if image.mode != "L" else image
    working = np.asarray(gray, dtype=np.float64).copy()
    source = working.copy()
    h, w = working.shape
    if h == 0 or w == 0:
        return []

    sample_step = int(settings.sample_step)
    _raw_mean, raw_std = _local_texture(working, max(2, sample_step))
    textured = bool(np.mean(raw_std >= 20.0) >= _TEXTURED_FRACTION)
    sparse_canvas = bool((working < _WHITE).any()) and bool(
        _NEARLY_BLANK_MEAN <= float(np.mean(working)) < _BLANK_CANVAS_MEAN
    )
    tone_rule = bool(
        not sparse_canvas
        and settings.erase_enabled
        and textured
        and (
            settings.tone_coverage < 1.0
            or not math.isclose(settings.tone_exponent, 1.0)
            or settings.texture_limit > 0.0
        )
    )
    # The cap is a share of the darkest source-tone pixels that may receive
    # ink. It uses the pre-max_fill grayscale, so a clamped black point cannot
    # change which pixels count as darkest. Only the tone path tracks it: flat
    # shapes, sparse palette channels and Sketch Squares keep their old look.
    ink_cap = settings.max_tone_ink * _TONE_INK_BLEED_FACTOR
    cap_tone_ink = tone_rule and settings.max_tone_ink < 1.0
    darkest: NDArray[np.bool_] | None = None
    inked: NDArray[np.bool_] | None = None
    darkest_total = 0
    inked_dark = 0
    if cap_tone_ink:
        darkest = source <= np.quantile(source, _DARKEST_QUANTILE)
        darkest_total = int(np.count_nonzero(darkest))
        cap_tone_ink = darkest_total > 0
        if cap_tone_ink:
            inked = np.zeros_like(working, dtype=np.bool_)
    max_fill = settings.max_fill
    line_density = settings.line_density
    if not tone_rule:
        if "max_fill" not in settings.model_fields_set:
            max_fill = _LEGACY_MAX_FILL
        if "line_density" not in settings.model_fields_set:
            line_density = _LEGACY_LINE_DENSITY
    black_point = _WHITE * (1.0 - max_fill / 100.0)
    if black_point > 0.0:
        np.maximum(working, black_point, out=working)

    white_cutoff = settings.white_threshold * _WHITE if settings.white_threshold < 1.0 else None
    min_len = int(max(1, settings.min_length))
    max_len = int(max(min_len, settings.max_length))
    line_density = max(0.01, line_density)
    num_tests = max(1, round(360.0 / settings.search_angle_step))

    canvas_avg = float(np.mean(working))
    ink_pixels = working < _WHITE
    sparse_canvas = bool(ink_pixels.any()) and _NEARLY_BLANK_MEAN <= canvas_avg < _BLANK_CANVAS_MEAN
    local_mean, local_std = _local_texture(working, max(2, sample_step))
    offsets = np.zeros_like(working)
    if tone_rule:
        offsets = _tone_budgets(
            working,
            local_mean,
            local_std,
            settings.tone_coverage,
            settings.tone_exponent,
            settings.texture_limit,
        )
    caps = np.where(
        working >= _WHITE,
        _WHITE,
        _WHITE - 0.5 - 0.5 * (working / _WHITE),
    )
    score = np.minimum(caps, working + offsets) if tone_rule else working
    progress_pixels = ink_pixels if sparse_canvas else None
    initial_avg = (
        float(np.mean(score[progress_pixels]))
        if progress_pixels is not None
        else float(np.mean(score))
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
        if cap_tone_ink and inked_dark / darkest_total >= ink_cap:
            break
        canvas_avg = float(np.mean(score))
        if float(np.min(score)) >= _WHITE:
            break
        current_avg = (
            float(np.mean(score[progress_pixels])) if progress_pixels is not None else canvas_avg
        )
        if settings.erase_enabled:
            if tone_rule:
                target = min(_TONE_DESIRED_LUMINANCE, float(np.mean(caps)))
                density = min(1.0, line_density)
            else:
                target = _DESIRED_LUMINANCE
                density = line_density
            if initial_avg >= target:
                break
            lum_progress = (current_avg - initial_avg) / ((target - initial_avg) * density)
            if lum_progress >= 1.0:
                break
        else:
            lum_progress = 0.0

        start_x, start_y = _find_darkest_pixel(score, sample_step, rng)
        initial_darkness = float(score[start_y, start_x])
        if settings.erase_enabled:
            allowable = initial_darkness + max(
                1.0, _DESIRED_LUMINANCE * settings.squiggle_max_deviation
            )
        else:
            allowable = _DESIRED_LUMINANCE

        current_x, current_y = start_x, start_y
        points: list[tuple[float, float]] = [(float(start_x), float(start_y))]
        shading = bool(shading_enabled and lum_progress > shading_threshold)

        for s in range(settings.squiggle_max_length):
            line_len = rng.randint(min_len, max_len)
            start_angle = angle_provider(rng, current_x, current_y, s)
            avg_lum, next_x, next_y = _find_darkest_line(
                score,
                current_x,
                current_y,
                min_len,
                line_len,
                shading,
                start_angle,
                num_tests,
                180.0,
                source,
                white_cutoff,
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

            if squiggle_enabled and s > 0:
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
                newly_inked = _apply_erase(
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
                    score=score if tone_rule else None,
                    tone_offsets=offsets if tone_rule else None,
                    caps=caps if tone_rule else None,
                    inked=inked,
                    darkest=darkest,
                )
                if cap_tone_ink:
                    inked_dark += newly_inked
                    if inked_dark / darkest_total >= ink_cap:
                        break
            current_x, current_y = next_x, next_y

        if len(points) >= 2:
            line = LineString(points)
            if line.is_valid and line.length > 0:
                lines.append(line)
                fails = 0
                continue
        working[current_y, current_x] = _WHITE
        if tone_rule:
            score[current_y, current_x] = _WHITE
        fails += 1

    return lines


def sketch_lines(image: Image.Image, settings: SketchLinesSettings) -> list[LineString]:
    """Generate sketch lines from an image using the Sketch Lines PFM algorithm.

    Strokes are returned in image pixel coordinates (origin top-left) and are
    always inside the image. Drawing lightens the working image, so the run
    stops when its average luminance reaches the target given by
    ``line_density``. Segments stop at the last source pixel below
    ``white_threshold``, so near-white source areas stay blank paper. The search
    score is a per-pixel source-tone ink budget lowered as strokes spend it:
    pixels darker than their local surroundings
    keep more budget, while textured dark pixels lose part of theirs to
    ``texture_limit``, so dark areas keep white gaps instead of saturating.
    The darkest tenth of that source is also tracked while strokes are drawn:
    once ``max_tone_ink`` of it has received ink the run stops, leaving the
    rest as visible white gaps. Flat shapes and near-white pixels keep a small
    budget so every part of the image can receive ink. On a nearly blank canvas
    (mean from 252.5 to below 254),
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

    def angle_provider(rng: random.Random, _x: int, _y: int, _step: int) -> float:
        angle_min, angle_max = settings.angle_range
        return rng.uniform(angle_min, angle_max)

    return _run_sketch_engine(
        image,
        settings,
        angle_provider,
        shading_enabled=settings.shading_enabled,
        squiggle_enabled=settings.squiggle_enabled,
        shading_threshold=settings.shading_threshold,
    )


__all__ = ["SketchLinesSettings", "sketch_lines"]
