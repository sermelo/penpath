"""Optional outline pass that turns image edges into plottable contour strokes."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, Field
from shapely import LineString
from skimage.feature import canny
from skimage.filters import gaussian
from skimage.morphology import closing, disk, label, thin

if TYPE_CHECKING:
    from PIL import Image

_NEIGHBORS: tuple[tuple[int, int], ...] = (
    (0, -1),
    (1, -1),
    (1, 0),
    (1, 1),
    (0, 1),
    (-1, 1),
    (-1, 0),
    (-1, -1),
)


class OutlineSettings(BaseModel):
    """Settings for the edge/outline stroke pass.

    Parameters
    ----------
    blur_sigma : float
        Gaussian blur sigma applied before edge detection (0 - 10). Zero
        disables the extra blur. Defaults to 1.0 so JPEG noise does not become
        dozens of tiny contours.
    edge_sigma : float
        Sigma of scikit-image's Canny edge detector in pixels (0.1 - 10).
    low_threshold : float
        Canny's low gradient threshold on the 0 - 1 luminance scale (0 - 1).
    high_threshold : float
        Canny's high gradient threshold on the 0 - 1 luminance scale (0 - 1).
        Must be greater than ``low_threshold``.
    close_radius : int
        Radius of the disk used to close one-pixel gaps in edges (0 - 20).
        Zero disables closing.
    min_component_pixels : int
        Thin skeleton components with fewer pixels than this are dropped as
        specks (1 - 10000).
    min_length : float
        Minimum length in image pixels of an emitted stroke (1 - 10000).
    simplify_tolerance : float
        Shapely simplification tolerance in image pixels (0 - 100). Zero keeps
        every skeleton pixel.
    seed : int | None
        Accepted for symmetry with the other drawing settings. The tracer is
        fully deterministic and uses no randomness, so the seed has no effect.
    """

    blur_sigma: float = Field(default=1.0, ge=0.0, le=10.0)
    edge_sigma: float = Field(default=1.0, ge=0.1, le=10.0)
    low_threshold: float = Field(default=0.1, ge=0.0, le=1.0)
    high_threshold: float = Field(default=0.2, ge=0.0, le=1.0)
    close_radius: int = Field(default=1, ge=0, le=20)
    min_component_pixels: int = Field(default=12, ge=1, le=10000)
    min_length: float = Field(default=12.0, ge=1.0, le=10000.0)
    simplify_tolerance: float = Field(default=1.0, ge=0.0, le=100.0)
    seed: int | None = None

    def model_post_init(self, __context: object) -> None:
        if self.high_threshold <= self.low_threshold:
            raise ValueError("high_threshold must be greater than low_threshold")


def _edge_skeleton(gray: NDArray[np.float64], settings: OutlineSettings) -> NDArray[np.bool_]:
    """Detect, close, thin and clean image edges into a one-pixel skeleton."""
    if settings.blur_sigma > 0.0:
        gray = gaussian(  # type: ignore[no-untyped-call]
            gray, sigma=settings.blur_sigma, preserve_range=True
        )
    edges = canny(  # type: ignore[no-untyped-call]
        gray,
        sigma=settings.edge_sigma,
        low_threshold=settings.low_threshold,
        high_threshold=settings.high_threshold,
        use_quantiles=False,
    )
    if settings.close_radius > 0:
        footprint = disk(settings.close_radius)  # type: ignore[no-untyped-call]
        edges = closing(edges, footprint)
    skeleton = thin(edges)  # type: ignore[no-untyped-call]
    components = label(skeleton, connectivity=2)  # type: ignore[no-untyped-call]
    sizes = np.bincount(components.ravel())
    sizes[0] = 0
    return cast("NDArray[np.bool_]", sizes[components] >= settings.min_component_pixels)


def _pixel_set(skeleton: NDArray[np.bool_]) -> set[tuple[int, int]]:
    """Return the skeleton's ``(x, y)`` pixels as a set."""
    ys, xs = np.nonzero(skeleton)
    return {(int(x), int(y)) for x, y in zip(xs, ys, strict=True)}


def _degree(pixel: tuple[int, int], pixels: set[tuple[int, int]]) -> int:
    """Count the skeleton neighbours of a pixel using 8-connectivity."""
    x, y = pixel
    return sum((x + dx, y + dy) in pixels for dx, dy in _NEIGHBORS)


def _trace_path(
    start: tuple[int, int],
    pixels: set[tuple[int, int]],
    degrees: dict[tuple[int, int], int],
) -> list[tuple[int, int]]:
    """Walk one skeleton path, preferring straight continuation at forks."""
    points = [start]
    pixels.remove(start)
    previous: tuple[int, int] | None = None
    current = start

    while True:
        neighbours = [
            (index, (current[0] + dx, current[1] + dy))
            for index, (dx, dy) in enumerate(_NEIGHBORS)
            if (current[0] + dx, current[1] + dy) in pixels
        ]
        if not neighbours:
            break

        direction = (
            (0, 0) if previous is None else (current[0] - previous[0], current[1] - previous[1])
        )
        next_pixel = max(
            neighbours,
            key=lambda item: (
                direction[0] * (item[1][0] - current[0]) + direction[1] * (item[1][1] - current[1]),
                -item[0],
            ),
        )[1]

        pixels.remove(next_pixel)
        points.append(next_pixel)
        previous, current = current, next_pixel
        if degrees[next_pixel] >= 3:
            break

    return points


def _trace_skeleton(skeleton: NDArray[np.bool_]) -> list[list[tuple[int, int]]]:
    """Chain skeleton pixels into paths, splitting where branches meet."""
    pixels = _pixel_set(skeleton)
    degrees = {pixel: _degree(pixel, pixels) for pixel in pixels}
    paths: list[list[tuple[int, int]]] = []

    for start in sorted(pixel for pixel, degree in degrees.items() if degree == 1):
        if start in pixels:
            paths.append(_trace_path(start, pixels, degrees))
    for start in sorted(pixel for pixel, degree in degrees.items() if degree >= 3):
        if start in pixels:
            paths.append(_trace_path(start, pixels, degrees))
    for start in sorted(pixels):
        if start in pixels:
            paths.append(_trace_path(start, pixels, degrees))

    return paths


def outline_strokes(image: Image.Image, settings: OutlineSettings) -> list[LineString]:
    """Extract clean contour strokes from an image, in image pixel coordinates.

    The image is converted to greyscale, smoothed, and passed through
    scikit-image's Canny detector. The edge pixels are closed, thinned to a
    one-pixel skeleton and stripped of small specks before a deterministic walk
    chains them into polylines. Each polyline is simplified with Shapely,
    clamped to the image bounds, and dropped when it degenerates or is shorter
    than ``settings.min_length``. No randomness is involved: the same image and
    settings always give the same strokes in the same order.

    This is a library-only pass. It does not change the default Sketch Lines
    path, and it is not wired into ``convert`` or ``--style`` yet.

    Parameters
    ----------
    image : PIL.Image.Image
        Input image in any mode (converted to greyscale).
    settings : OutlineSettings
        Edge detection and stroke cleaning configuration.

    Returns
    -------
    list[LineString]
        Contour strokes in image pixel coordinates (origin top-left), each
        inside the image bounds. An empty image or an image without detectable
        edges returns an empty list.
    """
    gray = np.asarray(image.convert("L"), dtype=np.float64) / 255.0
    height, width = gray.shape
    if height == 0 or width == 0:
        return []

    skeleton = _edge_skeleton(gray, settings)
    lines: list[LineString] = []
    for path in _trace_skeleton(skeleton):
        if len(path) < 2:
            continue
        line = LineString([(float(x), float(y)) for x, y in path]).simplify(
            settings.simplify_tolerance, preserve_topology=True
        )
        if line.is_empty or not line.is_valid:
            continue
        coords = [
            (min(max(x, 0.0), float(width - 1)), min(max(y, 0.0), float(height - 1)))
            for x, y in line.coords
        ]
        stroke = LineString(coords)
        if stroke.is_valid and stroke.length >= settings.min_length:
            lines.append(stroke)

    lines.sort(key=lambda line: (*line.bounds, line.wkb_hex))
    return lines


__all__ = ["OutlineSettings", "outline_strokes"]
