"""Line sorting using greedy nearest-neighbour and 2-opt optimization.

This module provides line sorting to minimize pen-up travel distance
between line segments.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from shapely import LineString, Point

if TYPE_CHECKING:
    from collections.abc import Iterable


DEFAULT_PAPER_DPI = 300


def _distance(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    """Calculate Euclidean distance between two points."""
    return math.hypot(p2[0] - p1[0], p2[1] - p1[1])


def _line_endpoints(line: LineString) -> tuple[tuple[float, float], tuple[float, float]]:
    """Get start and end points of a line as (start, end) tuples."""
    coords = list(line.coords)
    if not coords:
        return ((0.0, 0.0), (0.0, 0.0))
    start = (float(coords[0][0]), float(coords[0][1]))
    end = (float(coords[-1][0]), float(coords[-1][1]))
    return (start, end)


def _reverse_line(line: LineString) -> LineString:
    """Return a reversed copy of the line."""
    coords = list(line.coords)
    return LineString(coords[::-1])


def _travel_distance(lines: list[LineString]) -> float:
    """Calculate total pen-up travel distance for a sequence of lines."""
    if len(lines) <= 1:
        return 0.0

    total = 0.0
    for i in range(len(lines) - 1):
        _, end_curr = _line_endpoints(lines[i])
        start_next, _ = _line_endpoints(lines[i + 1])
        total += _distance(end_curr, start_next)
    return total


def _greedy_nearest_neighbour(
    lines: list[LineString], start_point: Point | None = None
) -> list[LineString]:
    """Sort lines using greedy nearest-neighbour algorithm.

    At each step, picks the line (in either direction) whose start point
    is closest to the current position.

    Parameters
    ----------
    lines : list[LineString]
        Lines to sort.
    start_point : Point | None
        Optional starting position. If None, uses first line's start.

    Returns
    -------
    list[LineString]
        Sorted lines with optimal direction for each.
    """
    if not lines:
        return []

    remaining = list(lines)
    sorted_lines: list[LineString] = []

    # Determine starting position
    if start_point is not None:
        current_pos = (start_point.x, start_point.y)
    else:
        # Use first line's start point
        first_start, _ = _line_endpoints(remaining[0])
        current_pos = first_start

    while remaining:
        best_idx = -1
        best_dist = float("inf")
        best_reversed = False

        # Find the closest line endpoint to current position
        for idx, line in enumerate(remaining):
            start, end = _line_endpoints(line)

            # Check distance to start (normal direction)
            dist_to_start = _distance(current_pos, start)
            if dist_to_start < best_dist:
                best_dist = dist_to_start
                best_idx = idx
                best_reversed = False

            # Check distance to end (reversed direction)
            dist_to_end = _distance(current_pos, end)
            if dist_to_end < best_dist:
                best_dist = dist_to_end
                best_idx = idx
                best_reversed = True

        # Take the best line and orient it correctly
        best_line = remaining.pop(best_idx)
        if best_reversed:
            best_line = _reverse_line(best_line)

        sorted_lines.append(best_line)

        # Update current position to end of chosen line
        _, current_pos = _line_endpoints(best_line)

    return sorted_lines


def _two_opt(lines: list[LineString]) -> list[LineString]:
    """Apply 2-opt optimization to reduce travel distance.

    Iteratively tries swapping pairs of lines to see if it reduces
    the total pen-up travel distance.

    Parameters
    ----------
    lines : list[LineString]
        Lines to optimize (modified in place and returned).

    Returns
    -------
    list[LineString]
        Optimized lines.
    """
    if len(lines) < 3:
        return lines

    # Work with a copy to avoid modifying during iteration issues
    lines = list(lines)
    improved = True

    while improved:
        improved = False
        best_distance = _travel_distance(lines)

        # Try all pairs (i, j) where i < j
        for i in range(len(lines) - 1):
            for j in range(i + 1, len(lines)):
                # Create candidate by swapping lines[i] and lines[j]
                candidate = lines[:]
                candidate[i], candidate[j] = candidate[j], candidate[i]

                # Also try reversing one or both
                for rev_i in (False, True):
                    for rev_j in (False, True):
                        test_candidate = candidate[:]
                        if rev_i:
                            test_candidate[i] = _reverse_line(test_candidate[i])
                        if rev_j:
                            test_candidate[j] = _reverse_line(test_candidate[j])

                        dist = _travel_distance(test_candidate)
                        if dist < best_distance:
                            best_distance = dist
                            lines = test_candidate
                            improved = True

    return lines


def sort_lines(
    lines: Iterable[LineString],
    start_point: Point | None = None,
) -> list[LineString]:
    """Sort lines to minimize pen-up travel distance.

    Uses a two-phase approach:
    1. Greedy nearest-neighbour: build initial path by always picking
       the closest line endpoint to current position
    2. 2-opt pass: iteratively swap line pairs to further reduce travel

    Each line may be reversed if it reduces travel distance to the next line.

    Parameters
    ----------
    lines : Iterable[LineString]
        Input line geometries in pixel coordinates.
    start_point : Point | None, optional
        Starting position for the sort. If None, uses the start of the
        first line in the input.

    Returns
    -------
    list[LineString]
        Sorted lines with optimal direction, same coordinate system.

    Examples
    --------
    >>> from shapely import LineString, Point
    >>> lines = [
    ...     LineString([(100, 100), (200, 100)]),
    ...     LineString([(0, 0), (100, 0)]),
    ... ]
    >>> sorted_lines = sort_lines(lines, start_point=Point(0, 0))
    >>> # First line should be the one starting near (0, 0)
    >>> list(sorted_lines[0].coords)[:2]
    [(0.0, 0.0), (100.0, 0.0)]
    """
    lines_list = list(lines)

    if not lines_list:
        return []

    # Filter out empty/invalid lines
    valid_lines = [line for line in lines_list if not line.is_empty and line.is_valid]

    if not valid_lines:
        return []

    # Phase 1: Greedy nearest-neighbour
    sorted_lines = _greedy_nearest_neighbour(valid_lines, start_point)

    # Phase 2: 2-opt optimization
    sorted_lines = _two_opt(sorted_lines)

    return sorted_lines


__all__ = [
    "DEFAULT_PAPER_DPI",
    "sort_lines",
]
