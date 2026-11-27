"""Line sorting using greedy nearest-neighbour and 2-opt optimization.

This module provides line sorting to minimize pen-up travel distance
between line segments.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray
from shapely import LineString, Point

if TYPE_CHECKING:
    from collections.abc import Iterable


DEFAULT_PAPER_DPI = 300


def _line_endpoints(line: LineString) -> tuple[tuple[float, float], tuple[float, float]]:
    """Get start and end points of a line as (start, end) tuples."""
    coords = line.coords
    if len(coords) == 0:
        return ((0.0, 0.0), (0.0, 0.0))
    first = coords[0]
    last = coords[-1]
    return ((float(first[0]), float(first[1])), (float(last[0]), float(last[1])))


def _endpoints_arrays(lines: list[LineString]) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Build the start/end coordinate arrays used by both sorting phases."""
    endpoints = [_line_endpoints(line) for line in lines]
    starts = np.asarray([start for start, _ in endpoints], dtype=np.float64)
    ends = np.asarray([end for _, end in endpoints], dtype=np.float64)
    return starts, ends


def _distance(p1: NDArray[np.float64], p2: NDArray[np.float64]) -> float:
    """Calculate Euclidean distance between two points."""
    return math.hypot(float(p2[0]) - float(p1[0]), float(p2[1]) - float(p1[1]))


def _reverse_line(line: LineString) -> LineString:
    """Return a reversed copy of the line."""
    coords = list(line.coords)
    return LineString(coords[::-1])


def _travel_distance(starts: NDArray[np.float64], ends: NDArray[np.float64]) -> float:
    """Calculate total pen-up travel distance for oriented endpoints."""
    total = 0.0
    for i in range(len(starts) - 1):
        total += _distance(ends[i], starts[i + 1])
    return total


def _greedy_nearest_neighbour(
    lines: list[LineString],
    starts: NDArray[np.float64],
    ends: NDArray[np.float64],
    start_point: Point | None = None,
) -> tuple[list[LineString], NDArray[np.float64], NDArray[np.float64]]:
    """Sort lines using greedy nearest-neighbour algorithm.

    At each step, picks the line (in either direction) whose start point
    is closest to the current position. Ties go to the earliest remaining
    line, and a line's start beats its end.

    Parameters
    ----------
    lines : list[LineString]
        Lines to sort.
    starts : NDArray[np.float64]
        Start point of each line, in the same order as `lines`.
    ends : NDArray[np.float64]
        End point of each line, in the same order as `lines`.
    start_point : Point | None
        Optional starting position. If None, uses first line's start.

    Returns
    -------
    tuple[list[LineString], NDArray[np.float64], NDArray[np.float64]]
        Sorted lines and their oriented endpoints.
    """
    count = len(lines)
    sorted_lines: list[LineString] = []
    sorted_starts = np.empty((count, 2), dtype=np.float64)
    sorted_ends = np.empty((count, 2), dtype=np.float64)
    remaining = np.ones(count, dtype=bool)

    if start_point is not None:
        cx, cy = float(start_point.x), float(start_point.y)
    else:
        cx, cy = float(starts[0, 0]), float(starts[0, 1])

    for k in range(count):
        dist_to_start = np.hypot(starts[:, 0] - cx, starts[:, 1] - cy)
        dist_to_end = np.hypot(ends[:, 0] - cx, ends[:, 1] - cy)
        dist_to_start[~remaining] = np.inf
        dist_to_end[~remaining] = np.inf

        flat_index = int(np.argmin(np.stack((dist_to_start, dist_to_end), axis=1).ravel()))
        idx, reversed_flag = divmod(flat_index, 2)
        remaining[idx] = False

        line = lines[idx]
        if reversed_flag:
            line = _reverse_line(line)
            sorted_starts[k] = ends[idx]
            sorted_ends[k] = starts[idx]
        else:
            sorted_starts[k] = starts[idx]
            sorted_ends[k] = ends[idx]
        sorted_lines.append(line)
        cx, cy = float(sorted_ends[k, 0]), float(sorted_ends[k, 1])

    return sorted_lines, sorted_starts, sorted_ends


def _two_opt(
    lines: list[LineString],
    starts: NDArray[np.float64],
    ends: NDArray[np.float64],
    max_iterations: int = 10,
) -> list[LineString]:
    """Apply 2-opt optimization to reduce travel distance.

    Reversing line i only changes the two links touching it, so each
    candidate is judged by that delta rather than a full travel sum.

    Parameters
    ----------
    lines : list[LineString]
        Lines to optimize.
    starts : NDArray[np.float64]
        Current start point of each line.
    ends : NDArray[np.float64]
        Current end point of each line.
    max_iterations : int
        Maximum number of optimization passes.

    Returns
    -------
    list[LineString]
        Optimized lines.
    """
    count = len(lines)
    if count < 3:
        return lines

    current_starts = starts.copy()
    current_ends = ends.copy()
    best_distance = _travel_distance(current_starts, current_ends)

    for _ in range(max_iterations):
        improved = False
        for i in range(count):
            old_before = 0.0
            new_before = 0.0
            old_after = 0.0
            new_after = 0.0
            if i > 0:
                previous_end = current_ends[i - 1]
                old_before = _distance(previous_end, current_starts[i])
                new_before = _distance(previous_end, current_ends[i])
            if i < count - 1:
                next_start = current_starts[i + 1]
                old_after = _distance(current_ends[i], next_start)
                new_after = _distance(current_starts[i], next_start)

            delta = new_before + new_after - old_before - old_after
            if best_distance + delta < best_distance:
                current_starts[i], current_ends[i] = (
                    current_ends[i].copy(),
                    current_starts[i].copy(),
                )
                lines[i] = _reverse_line(lines[i])
                best_distance = _travel_distance(current_starts, current_ends)
                improved = True
        if not improved:
            break

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

    # A tap's two identical points make the geometry invalid to GEOS, but a tap
    # is still a stroke to plot and must stay in the sorted drawing.
    valid_lines = [
        line
        for line in lines_list
        if not line.is_empty
        and len(list(line.coords)) >= 2
        and (line.is_valid or line.length <= 0.0)
    ]

    if not valid_lines:
        return []

    starts, ends = _endpoints_arrays(valid_lines)
    sorted_lines, sorted_starts, sorted_ends = _greedy_nearest_neighbour(
        valid_lines, starts, ends, start_point
    )
    return _two_opt(sorted_lines, sorted_starts, sorted_ends)


__all__ = [
    "DEFAULT_PAPER_DPI",
    "sort_lines",
]
