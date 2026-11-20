"""Line simplification using Ramer-Douglas-Peucker algorithm.

This module provides line simplification via shapely's RDP implementation,
with tolerance specified in millimetres and converted to pixels using paper DPI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from shapely import LineString

if TYPE_CHECKING:
    from collections.abc import Iterable


DEFAULT_PAPER_DPI = 300


def mm_to_pixels(mm: float, dpi: int) -> float:
    """Convert millimetres to pixels at given DPI.

    Parameters
    ----------
    mm : float
        Distance in millimetres.
    dpi : int
        Dots per inch (pixels per inch).

    Returns
    -------
    float
        Distance in pixels.
    """
    return mm * dpi / 25.4


def pixels_to_mm(pixels: float, dpi: int) -> float:
    """Convert pixels to millimetres at given DPI.

    Parameters
    ----------
    pixels : float
        Distance in pixels.
    dpi : int
        Dots per inch (pixels per inch).

    Returns
    -------
    float
        Distance in millimetres.
    """
    return pixels * 25.4 / dpi


def simplify_line(
    line: LineString,
    tolerance_mm: float,
    paper_dpi: int,
) -> LineString:
    """Simplify a single LineString using Ramer-Douglas-Peucker algorithm.

    Parameters
    ----------
    line : LineString
        Input line geometry in pixel coordinates.
    tolerance_mm : float
        Maximum deviation tolerance in millimetres.
    paper_dpi : int
        Image DPI for mm-to-pixel conversion.

    Returns
    -------
    LineString
        Simplified line in the same coordinate system.
    """
    if tolerance_mm < 0:
        raise ValueError("tolerance_mm must be >= 0")
    if paper_dpi <= 0:
        raise ValueError("paper_dpi must be > 0")

    if line.is_empty:
        return line

    if tolerance_mm == 0:
        return line

    tolerance_px = mm_to_pixels(tolerance_mm, paper_dpi)
    simplified = line.simplify(tolerance_px, preserve_topology=True)

    # Ensure we always return a LineString
    if simplified.geom_type == "LineString":
        return simplified  # type: ignore[return-value]
    elif simplified.geom_type == "Point":
        # If simplification collapses to a point, return a minimal line
        coords = list(line.coords)
        if len(coords) >= 2:
            return LineString([coords[0], coords[-1]])
        return line
    else:
        # Fallback: return original line
        return line


def simplify(
    lines: Iterable[LineString],
    tolerance_mm: float,
    paper_dpi: int = DEFAULT_PAPER_DPI,
) -> list[LineString]:
    """Simplify a collection of lines using Ramer-Douglas-Peucker algorithm.

    Uses `shapely.simplify` (RDP) with tolerance converted from mm to pixels
    based on the paper DPI. Topology is preserved to avoid self-intersections.

    Parameters
    ----------
    lines : Iterable[LineString]
        Input line geometries in pixel coordinates (origin top-left).
    tolerance_mm : float
        Maximum deviation tolerance in millimetres. Must be >= 0.
    paper_dpi : int, optional
        Image DPI for mm-to-pixel conversion. Defaults to 300.

    Returns
    -------
    list[LineString]
        Simplified lines in the same coordinate system, same order as input.

    Raises
    ------
    ValueError
        If tolerance_mm is negative or paper_dpi is not positive.

    Examples
    --------
    >>> from shapely import LineString
    >>> lines = [LineString([(0, 0), (10, 0), (20, 0)])]
    >>> simplified = simplify(lines, tolerance_mm=0.5, paper_dpi=300)
    >>> len(simplified)
    1
    """
    if tolerance_mm < 0:
        raise ValueError("tolerance_mm must be >= 0")
    if paper_dpi <= 0:
        raise ValueError("paper_dpi must be > 0")

    if tolerance_mm == 0:
        return list(lines)

    return [simplify_line(line, tolerance_mm, paper_dpi) for line in lines]


__all__ = [
    "DEFAULT_PAPER_DPI",
    "mm_to_pixels",
    "pixels_to_mm",
    "simplify",
    "simplify_line",
]
