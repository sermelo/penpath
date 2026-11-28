"""TSP Art PFM: the whole picture as one continuous line.

Classic pen-plotter art: dots are placed with density following the image's
darkness (weighted Voronoi stippling: random weighted samples relaxed with a
few Lloyd iterations so they spread evenly), then joined into one tour that
visits every dot once (nearest-neighbour start, improved with 2-opt moves
between nearby dots so the line does not cross itself). The result is a
single stroke: one pen lift for the whole drawing.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, Field
from scipy.spatial import cKDTree  # type: ignore[import-untyped]
from shapely import LineString

if TYPE_CHECKING:
    from PIL import Image


class TSPSettings(BaseModel):
    """Settings for the TSP Art PFM.

    Lengths are in millimetres on paper; the image scale is passed to
    :func:`tsp_strokes`.

    Parameters
    ----------
    point_spacing : float
        Average distance between dots where the image is black, in
        millimetres (> 0). Lighter tones get proportionally fewer dots.
        Default 0.8.
    tone_gamma : float
        Exponent applied to darkness ``1 - L/255`` before it sets the dot
        density (> 0); above 1 keeps light areas emptier. Default 2.0.
    min_tone : float
        Darkness below which no dots are placed (0 - 1). Default 0.1.
    max_points : int
        Upper bound on the number of dots, to bound run time (100 - 200000).
        Default 30000.
    relax_iterations : int
        Lloyd relaxation iterations that spread the dots evenly (0 - 50).
        Default 8.
    two_opt_passes : int
        Passes of 2-opt improvement over each dot's nearest neighbours
        (0 - 20). Default 6.
    closed : bool
        Return to the first dot, closing the loop. When false (the default)
        the loop is opened at its longest jump, so no long straight segment
        crosses the picture. Default False.
    seed : int | None
        Random seed for dot placement. None is non-deterministic.
        Default None.
    """

    point_spacing: float = Field(default=0.8, gt=0.0)
    tone_gamma: float = Field(default=2.0, gt=0.0)
    min_tone: float = Field(default=0.1, ge=0.0, le=1.0)
    max_points: int = Field(default=30000, ge=100, le=200000)
    relax_iterations: int = Field(default=8, ge=0, le=50)
    two_opt_passes: int = Field(default=6, ge=0, le=20)
    closed: bool = False
    seed: int | None = None


def _weights(image: Image.Image, settings: TSPSettings) -> NDArray[np.float64]:
    """Dot density weight per pixel: stretched darkness raised to ``tone_gamma``."""
    gray = image.convert("L") if image.mode != "L" else image
    darkness = 1.0 - np.asarray(gray, dtype=np.float64) / 255.0
    span = max(1e-6, 1.0 - settings.min_tone)
    return np.asarray(
        np.clip((darkness - settings.min_tone) / span, 0.0, 1.0) ** settings.tone_gamma,
        dtype=np.float64,
    )


def stipple_points(
    weights: NDArray[np.float64],
    count: int,
    iterations: int,
    rng: np.random.Generator,
) -> NDArray[np.float64]:
    """Place ``count`` dots with density following ``weights`` (weighted Voronoi).

    Returns an ``(n, 2)`` array of ``(x, y)`` pixel coordinates.
    """
    width = weights.shape[1]
    flat = weights.ravel()
    total = float(flat.sum())
    if count <= 0 or total <= 0.0:
        return np.empty((0, 2), dtype=np.float64)
    chosen = rng.choice(flat.size, size=count, replace=True, p=flat / total)
    points = np.column_stack(
        (
            (chosen % width) + rng.uniform(-0.5, 0.5, count),
            (chosen // width) + rng.uniform(-0.5, 0.5, count),
        )
    )
    inked = np.flatnonzero(flat > 0.0)
    pixel_xy = np.column_stack(
        ((inked % width).astype(np.float64), (inked // width).astype(np.float64))
    )
    pixel_w = flat[inked]
    for _ in range(iterations):
        _, owner = cKDTree(points).query(pixel_xy, k=1, workers=1)
        mass = np.bincount(owner, weights=pixel_w, minlength=count)
        sum_x = np.bincount(owner, weights=pixel_w * pixel_xy[:, 0], minlength=count)
        sum_y = np.bincount(owner, weights=pixel_w * pixel_xy[:, 1], minlength=count)
        moved = mass > 0.0
        points[moved, 0] = sum_x[moved] / mass[moved]
        points[moved, 1] = sum_y[moved] / mass[moved]
    return points


def _nearest_neighbour_tour(points: NDArray[np.float64]) -> NDArray[np.int64]:
    """Greedy tour: always go to the nearest unvisited dot."""
    count = len(points)
    tree = cKDTree(points)
    visited = np.zeros(count, dtype=bool)
    order = np.empty(count, dtype=np.int64)
    current = 0
    visited[0] = True
    order[0] = 0
    for position in range(1, count):
        k = 8
        while True:
            _, candidates = tree.query(points[current], k=min(k, count))
            candidates = np.atleast_1d(candidates)
            free = candidates[~visited[candidates]]
            if free.size:
                current = int(free[0])
                break
            if k >= count:
                current = int(np.flatnonzero(~visited)[0])
                break
            k *= 4
        visited[current] = True
        order[position] = current
    return order


def _two_opt(
    points: NDArray[np.float64], order: NDArray[np.int64], passes: int, neighbours: int = 8
) -> NDArray[np.int64]:
    """Improve a closed tour with 2-opt moves between each dot's near neighbours."""
    count = len(order)
    if count < 4 or passes == 0:
        return order
    _, near = cKDTree(points).query(points, k=min(neighbours + 1, count))
    near_list = near[:, 1:].tolist()
    xs = points[:, 0].tolist()
    ys = points[:, 1].tolist()
    tour = order.tolist()
    position = [0] * count
    for index, node in enumerate(tour):
        position[node] = index

    def dist(a: int, b: int) -> float:
        return math.hypot(xs[a] - xs[b], ys[a] - ys[b])

    for _ in range(passes):
        improved = False
        for i in range(count):
            a = tour[i]
            b = tour[(i + 1) % count]
            d_ab = dist(a, b)
            for c in near_list[a]:
                j = position[c]
                if j in (i, (i + 1) % count):
                    continue
                d = tour[(j + 1) % count]
                if d == a:
                    continue
                delta = dist(a, c) + dist(b, d) - d_ab - dist(c, d)
                if delta < -1e-9:
                    # Reverse the segment between b and c (inclusive).
                    lo, hi = (i + 1, j) if i < j else (j + 1, i)
                    tour[lo : hi + 1] = tour[lo : hi + 1][::-1]
                    for index in range(lo, hi + 1):
                        position[tour[index]] = index
                    improved = True
                    b = tour[(i + 1) % count]
                    a = tour[i]
                    d_ab = dist(a, b)
            # Same move seen from b: pair edge (a, b) with the edge entering c.
            for c in near_list[b]:
                j = position[c]
                e = tour[j - 1]
                if c in (a, b) or e in (a, b):
                    continue
                delta = dist(a, e) + dist(b, c) - d_ab - dist(e, c)
                if delta < -1e-9:
                    # New edges (a, e) and (b, c): reverse b .. e (or c .. a).
                    lo, hi = (i + 1, j - 1) if i < j else (j, i)
                    if lo > hi:
                        continue
                    tour[lo : hi + 1] = tour[lo : hi + 1][::-1]
                    for index in range(lo, hi + 1):
                        position[tour[index]] = index
                    improved = True
                    a = tour[i]
                    b = tour[(i + 1) % count]
                    d_ab = dist(a, b)
        if not improved:
            break
    return np.asarray(tour, dtype=np.int64)


def open_at_longest_jump(path: NDArray[np.float64]) -> NDArray[np.float64]:
    """Rotate a closed tour so its longest edge becomes the (dropped) closing edge.

    The tour is a cycle; drawing it as an open path that starts right after
    its longest jump removes that jump, which a nearest-neighbour start can
    leave across the whole picture.
    """
    if len(path) < 3:
        return path
    following = np.roll(path, -1, axis=0)
    lengths = np.hypot(*(following - path).T)
    start = (int(np.argmax(lengths)) + 1) % len(path)
    return np.roll(path, -start, axis=0)


def tsp_strokes(
    image: Image.Image,
    settings: TSPSettings,
    pixels_per_mm: float,
    pen_width_mm: float,
) -> list[LineString]:
    """Draw the image as one continuous line through darkness-weighted dots.

    Parameters
    ----------
    image : PIL.Image.Image
        Input image (any mode, converted to greyscale).
    settings : TSPSettings
        Algorithm configuration, in millimetres on paper.
    pixels_per_mm : float
        Working-image pixels per paper millimetre. Must be positive.
    pen_width_mm : float
        Pen tip width in millimetres. Must be positive; accepted for the same
        call signature as the other millimetre-based PFMs.

    Returns
    -------
    list[LineString]
        One stroke in image pixel coordinates, or an empty list for a blank
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
    weights = _weights(image, settings)
    height, width = weights.shape
    spacing_px = settings.point_spacing * pixels_per_mm
    wanted = round(float(weights.sum()) / (spacing_px * spacing_px))
    count = min(settings.max_points, wanted)
    if count < 2:
        return []
    rng = np.random.default_rng(settings.seed)
    points = stipple_points(weights, count, settings.relax_iterations, rng)
    order = _two_opt(points, _nearest_neighbour_tour(points), settings.two_opt_passes)
    path = open_at_longest_jump(points[order])
    if settings.closed:
        path = np.vstack((path, path[:1]))
    path[:, 0] = np.clip(path[:, 0], 0.0, width - 1.0)
    path[:, 1] = np.clip(path[:, 1], 0.0, height - 1.0)
    line = LineString(path)
    return [line] if line.length > 0.0 else []


__all__ = ["TSPSettings", "open_at_longest_jump", "stipple_points", "tsp_strokes"]
