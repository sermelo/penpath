"""Line merging and collinear segment joining.

This module provides line merging via shapely's linemerge plus custom
collinear join logic based on angle and distance tolerances.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from shapely import LineString
from shapely.ops import linemerge

if TYPE_CHECKING:
    from collections.abc import Iterable


DEFAULT_PAPER_DPI = 300


def mm_to_pixels(mm: float, dpi: int) -> float:
    """Convert millimetres to pixels at given DPI."""
    return mm * dpi / 25.4


def _angle_between_lines(line1: LineString, line2: LineString) -> float:
    """Calculate the angle between the end of line1 and start of line2 in degrees.

    Returns angle in [0, 180] where 0 = perfectly collinear (same direction),
    180 = opposite direction.
    """
    if line1.is_empty or line2.is_empty:
        return 180.0

    coords1 = list(line1.coords)
    coords2 = list(line2.coords)

    if len(coords1) < 2 or len(coords2) < 2:
        return 180.0

    # Direction vector of line1 (from second-to-last to last point)
    x1, y1 = coords1[-2]
    x2, y2 = coords1[-1]
    dx1 = x2 - x1
    dy1 = y2 - y1

    # Direction vector of line2 (from first to second point)
    x3, y3 = coords2[0]
    x4, y4 = coords2[1]
    dx2 = x4 - x3
    dy2 = y4 - y3

    # Handle zero-length segments
    len1 = math.hypot(dx1, dy1)
    len2 = math.hypot(dx2, dy2)

    if len1 == 0 or len2 == 0:
        return 180.0

    # Normalize
    dx1, dy1 = dx1 / len1, dy1 / len1
    dx2, dy2 = dx2 / len2, dy2 / len2

    # Dot product gives cosine of angle
    dot = dx1 * dx2 + dy1 * dy2
    dot = max(-1.0, min(1.0, dot))  # Clamp for numerical stability

    angle = math.degrees(math.acos(dot))
    return angle


def _distance_between_lines(line1: LineString, line2: LineString) -> float:
    """Calculate the distance between the end of line1 and start of line2 in pixels."""
    if line1.is_empty or line2.is_empty:
        return float("inf")

    coords1 = list(line1.coords)
    coords2 = list(line2.coords)

    if not coords1 or not coords2:
        return float("inf")

    x1, y1 = coords1[-1]
    x2, y2 = coords2[0]

    return math.hypot(x2 - x1, y2 - y1)


def _can_join(
    line1: LineString,
    line2: LineString,
    angle_tol_deg: float,
    dist_tol_px: float,
) -> bool:
    """Check if two lines can be joined based on angle and distance tolerance."""
    angle = _angle_between_lines(line1, line2)
    dist = _distance_between_lines(line1, line2)

    return angle <= angle_tol_deg and dist <= dist_tol_px


def _join_lines(line1: LineString, line2: LineString) -> LineString:
    """Join two lines into one, removing the duplicate point at the junction."""
    coords1 = list(line1.coords)
    coords2 = list(line2.coords)

    if not coords1:
        return line2
    if not coords2:
        return line1

    # Combine coords, skipping the duplicate start point of line2
    combined = coords1 + coords2[1:]
    return LineString(merged for merged in combined)


def _merge_collinear_segments(
    lines: list[LineString],
    angle_tol_deg: float,
    dist_tol_px: float,
) -> list[LineString]:
    """Merge collinear adjacent segments in a list of lines."""
    if len(lines) <= 1:
        return lines

    merged: list[LineString] = [lines[0]]

    for line in lines[1:]:
        if not merged:
            merged.append(line)
            continue

        last = merged[-1]

        if _can_join(last, line, angle_tol_deg, dist_tol_px):
            # Join the lines
            merged[-1] = _join_lines(last, line)
        else:
            merged.append(line)

    return merged


def merge_lines(
    lines: Iterable[LineString],
    angle_tol_deg: float,
    dist_tol_mm: float,
    paper_dpi: int = DEFAULT_PAPER_DPI,
) -> list[LineString]:
    """Merge lines using shapely.ops.linemerge plus custom collinear join.

    First applies shapely's linemerge to connect lines that share endpoints.
    Then performs a custom collinear join pass to merge segments that are
    nearly collinear and within distance tolerance but don't share exact endpoints.

    Parameters
    ----------
    lines : Iterable[LineString]
        Input line geometries in pixel coordinates.
    angle_tol_deg : float
        Maximum angle deviation in degrees for collinear join (0-180).
    dist_tol_mm : float
        Maximum gap distance in millimetres for collinear join.
    paper_dpi : int, optional
        Image DPI for mm-to-pixel conversion. Defaults to 300.

    Returns
    -------
    list[LineString]
        Merged lines in the same coordinate system.

    Raises
    ------
    ValueError
        If angle_tol_deg not in [0, 180], dist_tol_mm negative, or paper_dpi not positive.

    Examples
    --------
    >>> from shapely import LineString
    >>> lines = [LineString([(0, 0), (10, 0)]), LineString([(10, 0), (20, 0)])]
    >>> merged = merge_lines(lines, angle_tol_deg=1.0, dist_tol_mm=0.1, paper_dpi=300)
    >>> len(merged)
    1
    >>> list(merged[0].coords)
    [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)]
    """
    if not (0 <= angle_tol_deg <= 180):
        raise ValueError("angle_tol_deg must be in [0, 180]")
    if dist_tol_mm < 0:
        raise ValueError("dist_tol_mm must be >= 0")
    if paper_dpi <= 0:
        raise ValueError("paper_dpi must be > 0")

    lines_list = list(lines)

    if not lines_list:
        return []

    # A zero-length stroke is a tap: GEOS treats it as invalid and drops it in
    # linemerge, so it is carried through unchanged beside the merged set.
    present_lines = [
        line for line in lines_list if not line.is_empty and len(list(line.coords)) >= 2
    ]
    drawable_lines = [line for line in present_lines if line.is_valid and line.length > 0.0]
    taps = [line for line in present_lines if line.length <= 0.0]

    if not present_lines:
        return []

    # Step 1: Use shapely's linemerge to join lines sharing exact endpoints
    try:
        merged_geom = linemerge(drawable_lines) if drawable_lines else None
        # Extract individual LineStrings from the merged result
        if merged_geom is None:
            linemerged_lines = []
        elif merged_geom.geom_type == "LineString":
            linemerged_lines = [merged_geom]
        elif merged_geom.geom_type == "MultiLineString":
            linemerged_lines = list(merged_geom.geoms)
        else:
            # Fallback: treat as individual lines
            linemerged_lines = drawable_lines
    except Exception:
        # If linemerge fails, fall back to original lines
        linemerged_lines = drawable_lines

    # Step 2: Custom collinear join for near-collinear segments within distance tolerance
    dist_tol_px = mm_to_pixels(dist_tol_mm, paper_dpi)
    result = _merge_collinear_segments(linemerged_lines, angle_tol_deg, dist_tol_px)

    return [*result, *taps]


__all__ = [
    "DEFAULT_PAPER_DPI",
    "merge_lines",
    "mm_to_pixels",
]
