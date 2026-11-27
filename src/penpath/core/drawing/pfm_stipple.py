"""Stippling PFM: weighted Poisson-disk dots in image pixel coordinates.

A darkness map (``1 - L/255``) weights candidate pixels. A candidate is
accepted when no earlier dot lies within its local exclusion radius, so dark
regions gather more dots and each accepted dot is larger there. Every dot is
one stroke: a dash, a closed circle, or a zero-length tap, so the cost of each
dot stays explicit to the optimizer.
"""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Final, Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, Field
from shapely import LineString

if TYPE_CHECKING:
    from PIL import Image


class StippleSettings(BaseModel):
    """Settings for the weighted Poisson-disk Stipple PFM algorithm.

    Parameters
    ----------
    dot_density : float
        Density multiplier for the target dot count (0 - 10). The target is the
        image's total darkness divided by the area of a largest dot, times this
        multiplier; higher values put more dots on the page. Default 1.0.
    min_radius : float
        Radius in working-image pixels of the faintest sampled dot (greater
        than 0). Dot length is twice the radius. Default 1.0.
    max_radius : float
        Radius in working-image pixels of a dot on a perfectly black pixel
        (greater than 0, at least ``min_radius``). It also sets both the target
        dot count and the largest exclusion radius. Default 3.0.
    jitter : float
        Rotation jitter in [0, 1]. A dot's angle is drawn uniformly from
        plus or minus ``jitter`` quarter turns; 0 draws every dot horizontally,
        1 allows every orientation. Default 1.0. No-op for ``circle`` and
        ``tap``, which have no random angle.
    dot_shape : {'dash', 'circle', 'tap'}
        Shape of one dot. ``dash`` is the two-point stroke at a jittered angle
        (the shipped default), ``circle`` is one closed ring per dot, and ``tap``
        is a zero-length stroke that lifts the pen in place.
    seed : int | None
        Random seed for deterministic output. None = non-deterministic.
    max_strokes : int
        Hard cap on the number of dots, and therefore on pen lifts (at least
        1). Default 10000, because every dot is a separate stroke.
    """

    dot_density: float = Field(default=1.0, gt=0.0, le=10.0)
    min_radius: float = Field(default=1.0, gt=0.0, le=100.0)
    max_radius: float = Field(default=3.0, gt=0.0, le=100.0)
    jitter: float = Field(default=1.0, ge=0.0, le=1.0)
    dot_shape: Literal["tap", "circle", "dash"] = "dash"
    seed: int | None = None
    max_strokes: int = Field(default=10000, ge=1)

    def model_post_init(self, __context: object) -> None:
        if self.min_radius > self.max_radius:
            raise ValueError("min_radius must be <= max_radius")


_CIRCLE_POINTS: Final = 12


def _darkness_map(image: Image.Image) -> NDArray[np.float64]:
    """Return ``1 - L/255`` for an image of any mode."""
    gray = image.convert("L") if image.mode != "L" else image
    return 1.0 - np.asarray(gray, dtype=np.float64) / 255.0


def _dot_radius(darkness: float, min_radius: float, max_radius: float) -> float:
    """Interpolate the dot radius from local darkness."""
    return min_radius + darkness * (max_radius - min_radius)


def _circle_line(
    center_x: float,
    center_y: float,
    radius: float,
    width: int,
    height: int,
) -> LineString:
    """Return a closed ring centred on an accepted dot, clamped to the image."""
    points = [
        (
            min(
                max(center_x + radius * math.cos(2 * math.pi * i / _CIRCLE_POINTS), 0.0), width - 1
            ),
            min(
                max(center_y + radius * math.sin(2 * math.pi * i / _CIRCLE_POINTS), 0.0), height - 1
            ),
        )
        for i in range(_CIRCLE_POINTS)
    ]
    return LineString([*points, points[0]])


def _exclusion_radius(darkness: float, max_radius: float) -> float:
    """Give darker candidates a smaller exclusion radius, so dots pack tighter."""
    return max_radius * (2.0 - darkness)


def _too_close(
    x: float,
    y: float,
    exclusion: float,
    cell: tuple[int, int],
    cell_size: int,
    cells: dict[tuple[int, int], list[tuple[float, float, float]]],
) -> bool:
    """Check the accepted dots in the neighbouring grid cells."""
    cell_x, cell_y = cell
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            for ax, ay, _ in cells.get((cell_x + dx, cell_y + dy), ()):
                if math.hypot(x - ax, y - ay) < exclusion:
                    return True
    return False


def stipple(image: Image.Image, settings: StippleSettings) -> list[LineString]:
    """Generate stipple dots from an image using weighted Poisson-disk sampling.

    Candidate pixels are drawn with probability proportional to darkness
    cubed: a dark region takes much more of the dot budget than a mid-tone, so
    light areas stay mostly empty paper. A candidate becomes a dot when no
    accepted dot is closer than its local exclusion radius, and the run stops at
    the target dot count or ``max_strokes``. Darker pixels have smaller exclusion
    radii and larger dot radii, so tone is carried by both dot count and dot
    size. A blank or empty image produces no strokes, and every emitted point
    stays inside the image.

    Parameters
    ----------
    image : PIL.Image.Image
        Input image (any mode, converted to grayscale).
    settings : StippleSettings
        Algorithm configuration.

    Returns
    -------
    list[LineString]
        One stroke per accepted dot, in image pixel coordinates: a two-point
        dash, a closed 12-point ring, or a zero-length tap.
    """
    darkness = _darkness_map(image)
    h, w = darkness.shape
    if h == 0 or w == 0 or not np.any(darkness > 0.0):
        return []

    rng = random.Random(settings.seed)
    flat = darkness.ravel()
    total_darkness = float(darkness.sum())
    target = min(
        settings.max_strokes,
        max(1, int(total_darkness * settings.dot_density / (math.pi * settings.max_radius**2))),
    )

    cell_size = max(1, math.ceil(2.0 * settings.max_radius))
    cells: dict[tuple[int, int], list[tuple[float, float, float]]] = {}
    max_span = float(min(w - 1, h - 1))
    lines: list[LineString] = []
    population = range(h * w)
    weights = [value**3 for value in flat.tolist()]
    batch_size = min(max(target * 20, 1000), 200_000)

    for _ in range(4):
        for index in rng.choices(population, weights=weights, k=batch_size):
            if len(lines) >= target:
                break
            darkness_here = float(flat[index])
            if darkness_here <= 0.0:
                continue

            y, x = divmod(index, w)
            radius = _dot_radius(darkness_here, settings.min_radius, settings.max_radius)
            if 2.0 * radius > max_span:
                continue

            center_x = min(max(float(x) + rng.uniform(-0.5, 0.5), radius), float(w - 1) - radius)
            center_y = min(max(float(y) + rng.uniform(-0.5, 0.5), radius), float(h - 1) - radius)
            exclusion = _exclusion_radius(darkness_here, settings.max_radius)
            cell = (int(center_x // cell_size), int(center_y // cell_size))
            if _too_close(center_x, center_y, exclusion, cell, cell_size, cells):
                continue

            if settings.dot_shape == "dash":
                angle = settings.jitter * rng.uniform(-math.pi / 2.0, math.pi / 2.0)
                dx, dy = math.cos(angle) * radius, math.sin(angle) * radius
                start = (
                    min(max(center_x - dx, 0.0), float(w - 1)),
                    min(max(center_y - dy, 0.0), float(h - 1)),
                )
                end = (
                    min(max(center_x + dx, 0.0), float(w - 1)),
                    min(max(center_y + dy, 0.0), float(h - 1)),
                )
                if start == end:
                    continue

                line = LineString([start, end])
                if not line.is_valid or line.length <= 0.0:
                    continue
            elif settings.dot_shape == "circle":
                line = _circle_line(center_x, center_y, radius, w, h)
            else:
                point = (center_x, center_y)
                line = LineString([point, point])

            lines.append(line)
            cells.setdefault(cell, []).append((center_x, center_y, exclusion))
        if len(lines) >= target:
            break

    return lines


__all__ = ["StippleSettings", "stipple"]
