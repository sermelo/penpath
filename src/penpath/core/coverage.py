"""Cap the real ink coverage of a drawing, measured with the pen width.

``max_coverage`` is the largest share of the paper that ink may cover where
the source image is black (0.8 = at most 80% ink). It works the same way
for every drawing algorithm, in two steps:

1. **Calibration** (:func:`calibrate_darkness_scale`): the algorithm draws a
   small uniform patch at the real scale and pen width; its real coverage
   (strokes drawn as pen-wide lines) is measured, and the darkness scale
   ``s`` that makes a black patch land on ``max_coverage`` is found by
   bisection. The image's darkness is multiplied by ``s`` before drawing
   (:func:`scale_darkness`), so every tone shrinks in proportion and each
   algorithm keeps its own line structure.
2. **Safety pass** (:func:`cap_coverage`): after drawing, the real coverage
   is measured in windows of a few millimetres; where it still exceeds the
   cap (an algorithm can behave differently on a photo than on the test
   patch), the most recently drawn strokes there are removed until it fits.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw

if TYPE_CHECKING:
    from shapely import LineString

CALIBRATION_PATCH_MM = 30.0
"""Side of the square test patch drawn during calibration."""

_TOLERANCE = 0.02


def _raster_scale(pen_width_mm: float) -> float:
    """Raster pixels per millimetre so a pen width spans at least 4 pixels."""
    return max(8.0, 4.0 / pen_width_mm)


def coverage_map(
    lines: list[LineString],
    shape_px: tuple[int, int],
    pixels_per_mm: float,
    pen_width_mm: float,
) -> tuple[NDArray[np.bool_], float]:
    """Rasterise ``lines`` as pen-wide strokes.

    Parameters
    ----------
    lines : list[shapely.LineString]
        Strokes in working-image pixel coordinates.
    shape_px : tuple[int, int]
        Working image size as ``(height, width)``.
    pixels_per_mm : float
        Working-image pixels per paper millimetre.
    pen_width_mm : float
        Pen tip width in millimetres.

    Returns
    -------
    tuple[numpy.ndarray, float]
        Boolean ink raster and its pixels per millimetre.
    """
    scale_mm = _raster_scale(pen_width_mm)
    factor = scale_mm / pixels_per_mm
    height = max(1, math.ceil(shape_px[0] * factor))
    width = max(1, math.ceil(shape_px[1] * factor))
    canvas = Image.new("1", (width, height), 0)
    draw = ImageDraw.Draw(canvas)
    stroke_px = max(1, round(pen_width_mm * scale_mm))
    for line in lines:
        coords = [(x * factor, y * factor) for x, y in line.coords]
        if len(coords) >= 2:
            draw.line(coords, fill=1, width=stroke_px, joint="curve")
    return np.asarray(canvas, dtype=bool), scale_mm


def measure_coverage(
    lines: list[LineString],
    shape_px: tuple[int, int],
    pixels_per_mm: float,
    pen_width_mm: float,
    margin_mm: float = 2.0,
) -> float:
    """Share of the paper covered by ink, ignoring a margin at the edges."""
    ink, scale_mm = coverage_map(lines, shape_px, pixels_per_mm, pen_width_mm)
    margin = round(margin_mm * scale_mm)
    inner = ink[margin : ink.shape[0] - margin, margin : ink.shape[1] - margin]
    if inner.size == 0:
        inner = ink
    return float(inner.mean()) if inner.size else 0.0


def scale_darkness(image: Image.Image, scale: float) -> Image.Image:
    """Greyscale copy of ``image`` with darkness ``1 - L/255`` multiplied by ``scale``."""
    gray = image.convert("L") if image.mode != "L" else image
    values = np.asarray(gray, dtype=np.float64)
    scaled = 255.0 - (255.0 - values) * min(max(scale, 0.0), 1.0)
    return Image.fromarray(np.clip(np.rint(scaled), 0, 255).astype(np.uint8))


def calibrate_darkness_scale(
    draw: Callable[[Image.Image], list[LineString]],
    max_coverage: float,
    pixels_per_mm: float,
    pen_width_mm: float,
    iterations: int = 6,
) -> float:
    """Darkness scale that makes a black patch land on ``max_coverage``.

    ``draw`` is the drawing algorithm with all its settings bound; it is run
    on a uniform :data:`CALIBRATION_PATCH_MM` square patch at the real scale.
    Returns 1.0 when black already covers no more than ``max_coverage``
    (nothing to change) or when the cap is 1 or more.

    Parameters
    ----------
    draw : Callable[[PIL.Image.Image], list[shapely.LineString]]
        The bound drawing function.
    max_coverage : float
        Largest share of ink for black (0 - 1).
    pixels_per_mm : float
        Working-image pixels per paper millimetre.
    pen_width_mm : float
        Pen tip width in millimetres.
    iterations : int, optional
        Bisection steps. Default 6 (scale accurate to about 1.5%).

    Returns
    -------
    float
        Scale in (0, 1].
    """
    if max_coverage >= 1.0:
        return 1.0
    side = max(16, round(CALIBRATION_PATCH_MM * pixels_per_mm))

    def coverage_at(darkness: float) -> float:
        level = round(255.0 * (1.0 - darkness))
        patch = Image.new("L", (side, side), level)
        # Only the central half counts: edges and corners (a spiral's empty
        # corners, a hatch's line ends) would pull the average down.
        return measure_coverage(
            draw(patch),
            (side, side),
            pixels_per_mm,
            pen_width_mm,
            margin_mm=side / pixels_per_mm / 4.0,
        )

    if coverage_at(1.0) <= max_coverage + _TOLERANCE:
        return 1.0
    low, high = 0.0, 1.0
    for _ in range(iterations):
        middle = (low + high) / 2.0
        if coverage_at(middle) > max_coverage:
            high = middle
        else:
            low = middle
    return max(low, 1e-3)


def cap_coverage(
    lines: list[LineString],
    shape_px: tuple[int, int],
    pixels_per_mm: float,
    pen_width_mm: float,
    max_coverage: float,
    window_mm: float = 3.0,
) -> list[LineString]:
    """Remove the latest strokes where windowed real coverage exceeds the cap.

    Coverage is the share of pen-wide ink in a ``window_mm`` square around
    each point. Strokes are first cut into pieces about ``window_mm`` long,
    so a single long stroke (a spiral, a hatch line) can be thinned locally.
    Pieces are visited from the last drawn to the first; a piece is removed
    when most of it lies where the coverage is still over ``max_coverage``
    (plus a 2% tolerance), and the coverage is updated. Kept consecutive
    pieces of a stroke are joined again; strokes keep their original order.
    """
    if max_coverage >= 1.0 or not lines:
        return lines
    from scipy import ndimage  # type: ignore[import-untyped]

    # Cheap check first: nothing to do if no window is over the cap.
    ink, scale_mm = coverage_map(lines, shape_px, pixels_per_mm, pen_width_mm)
    window = max(3, round(window_mm * scale_mm))
    density = ndimage.uniform_filter(ink.astype(np.float64), size=window)
    if float(density.max()) <= max_coverage + _TOLERANCE:
        return lines
    pieces, parents = _cut(lines, window_mm * pixels_per_mm)
    kept = _thin(pieces, shape_px, pixels_per_mm, pen_width_mm, max_coverage, window_mm)
    if all(kept):
        return lines
    return _rejoin(pieces, parents, kept)


def _cut(lines: list[LineString], length_px: float) -> tuple[list[LineString], list[int]]:
    """Cut strokes at vertices into consecutive pieces about ``length_px`` long.

    One cumulative-length pass per stroke, so a stroke with tens of thousands
    of points (a spiral) is cut in linear time. Pieces share their end and
    start vertex, so :func:`_rejoin` can glue kept neighbours back together.
    """
    from shapely import LineString as _Line

    pieces: list[LineString] = []
    parents: list[int] = []
    step = max(length_px, 1e-6)
    for index, line in enumerate(lines):
        coords = np.asarray(line.coords, dtype=np.float64)
        if len(coords) < 2 or line.length <= step:
            pieces.append(line)
            parents.append(index)
            continue
        cumulative = np.concatenate(([0.0], np.cumsum(np.hypot(*np.diff(coords, axis=0).T))))
        bucket = np.floor(cumulative / step).astype(np.int64)
        breaks = np.flatnonzero(np.diff(bucket)) + 1
        bounds = [0, *breaks.tolist(), len(coords) - 1]
        for a, b in itertools.pairwise(bounds):
            if b > a:
                pieces.append(_Line(coords[a : b + 1]))
                parents.append(index)
    return pieces, parents


def _rejoin(pieces: list[LineString], parents: list[int], kept: list[bool]) -> list[LineString]:
    """Join kept consecutive pieces of the same stroke back into one stroke."""
    from shapely import LineString as _Line

    result: list[LineString] = []
    current: list[tuple[float, float]] = []
    current_parent = -1
    for piece, parent, keep in zip(pieces, parents, kept, strict=True):
        coords = [(float(x), float(y)) for x, y in piece.coords]
        if keep and parent == current_parent and current and current[-1] == coords[0]:
            current.extend(coords[1:])
            continue
        if len(current) >= 2:
            result.append(_Line(current))
        current, current_parent = (coords, parent) if keep else ([], -1)
    if len(current) >= 2:
        result.append(_Line(current))
    return result


def _thin(
    lines: list[LineString],
    shape_px: tuple[int, int],
    pixels_per_mm: float,
    pen_width_mm: float,
    max_coverage: float,
    window_mm: float,
) -> list[bool]:
    """Which pieces to keep so windowed coverage stays under the cap."""
    from scipy import ndimage

    ink, scale_mm = coverage_map(lines, shape_px, pixels_per_mm, pen_width_mm)
    factor = scale_mm / pixels_per_mm
    stroke_px = max(1, round(pen_width_mm * scale_mm))
    window = max(3, round(window_mm * scale_mm))
    limit = max_coverage + _TOLERANCE
    density = ndimage.uniform_filter(ink.astype(np.float64), size=window)
    # Only pieces near an over-cap window can be removed; stamp just those.
    near = ndimage.maximum_filter(density > limit, size=window)
    candidate = []
    for line in lines:
        coords = np.asarray(line.coords) * factor
        rows = np.clip(np.rint(coords[:, 1]).astype(np.int64), 0, ink.shape[0] - 1)
        cols = np.clip(np.rint(coords[:, 0]).astype(np.int64), 0, ink.shape[1] - 1)
        candidate.append(bool(near[rows, cols].any()))
    base, _ = coverage_map(
        [line for line, hit in zip(lines, candidate, strict=True) if not hit],
        shape_px,
        pixels_per_mm,
        pen_width_mm,
    )
    counts = base.astype(np.float64)

    # Per-pixel stroke count so removing one stroke only clears pixels it alone inked.
    stamps: list[tuple[int, int, NDArray[np.bool_]]] = []
    for line, hit in zip(lines, candidate, strict=True):
        if not hit:
            stamps.append((0, 0, np.zeros((0, 0), dtype=bool)))
            continue
        points = [(x * factor, y * factor) for x, y in line.coords]
        xs = [c[0] for c in points]
        ys = [c[1] for c in points]
        pad = stroke_px + 1
        x0 = max(0, math.floor(min(xs)) - pad)
        y0 = max(0, math.floor(min(ys)) - pad)
        x1 = min(ink.shape[1], math.ceil(max(xs)) + pad + 1)
        y1 = min(ink.shape[0], math.ceil(max(ys)) + pad + 1)
        if x1 <= x0 or y1 <= y0 or len(points) < 2:
            stamps.append((0, 0, np.zeros((0, 0), dtype=bool)))
            continue
        local = Image.new("1", (x1 - x0, y1 - y0), 0)
        ImageDraw.Draw(local).line(
            [(x - x0, y - y0) for x, y in points], fill=1, width=stroke_px, joint="curve"
        )
        stamp = np.asarray(local, dtype=bool)
        counts[y0:y1, x0:x1] += stamp
        stamps.append((y0, x0, stamp))

    density = ndimage.uniform_filter((counts > 0).astype(np.float64), size=window)
    keep = [True] * len(lines)
    if float(density.max()) <= limit:
        return keep
    half = window // 2 + 1
    removed = 0
    for index in range(len(lines) - 1, -1, -1):
        y0, x0, stamp = stamps[index]
        if stamp.size == 0:
            continue
        rows, cols = np.nonzero(stamp)
        over = density[rows + y0, cols + x0] > limit
        if over.size == 0 or over.mean() < 0.5:
            continue
        keep[index] = False
        h, w = stamp.shape
        counts[y0 : y0 + h, x0 : x0 + w] -= stamp
        # Refresh the windowed density around the removed stroke.
        ry0, rx0 = max(0, y0 - half), max(0, x0 - half)
        ry1 = min(counts.shape[0], y0 + h + half)
        rx1 = min(counts.shape[1], x0 + w + half)
        gy0, gx0 = max(0, ry0 - half), max(0, rx0 - half)
        gy1, gx1 = min(counts.shape[0], ry1 + half), min(counts.shape[1], rx1 + half)
        block = ndimage.uniform_filter(
            (counts[gy0:gy1, gx0:gx1] > 0).astype(np.float64), size=window
        )
        density[ry0:ry1, rx0:rx1] = block[ry0 - gy0 : ry1 - gy0, rx0 - gx0 : rx1 - gx0]
        removed += 1
        # A full-image check is costly; only look every 256 removals.
        if removed % 256 == 0 and float(density.max()) <= limit:
            break
    return keep


__all__ = [
    "CALIBRATION_PATCH_MM",
    "calibrate_darkness_scale",
    "cap_coverage",
    "coverage_map",
    "measure_coverage",
    "scale_darkness",
]
