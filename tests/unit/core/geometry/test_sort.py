"""Unit tests for line sorting (greedy NN + 2-opt)."""

from __future__ import annotations

import math
import random
import time

import pytest
from shapely import LineString, Point

from penpath.core.geometry.sort import sort_lines


class TestSortLines:
    """Tests for sort_lines function."""

    def test_sort_lines_empty_list(self):
        """Empty list should return empty list."""
        result = sort_lines([])
        assert result == []

    def test_sort_lines_single_line(self):
        """Single line should be returned unchanged."""
        line = LineString([(0, 0), (100, 100)])
        result = sort_lines([line])
        assert len(result) == 1
        assert list(result[0].coords) == [(0.0, 0.0), (100.0, 100.0)]

    def test_sort_lines_two_lines_start_point(self):
        """Should pick line closest to start_point first."""
        lines = [
            LineString([(100, 100), (200, 100)]),  # Far from origin
            LineString([(0, 0), (50, 0)]),  # Near origin
        ]
        result = sort_lines(lines, start_point=Point(0, 0))
        # First line should be the one starting at (0, 0)
        assert next(iter(result[0].coords)) == (0.0, 0.0)

    def test_sort_lines_reverses_direction(self):
        """Should reverse line direction if it reduces travel distance."""
        lines = [
            LineString([(100, 0), (0, 0)]),  # Points toward origin (backwards)
            LineString([(0, 100), (100, 100)]),
        ]
        result = sort_lines(lines, start_point=Point(0, 0))
        # First line should be reversed to start at (0, 0)
        assert next(iter(result[0].coords)) == (0.0, 0.0)
        assert list(result[0].coords)[-1] == (100.0, 0.0)

    def test_sort_lines_three_lines_greedy_order(self):
        """Should order three lines by nearest neighbour."""
        lines = [
            LineString([(200, 0), (300, 0)]),  # Far right
            LineString([(0, 0), (100, 0)]),  # Left
            LineString([(100, 0), (200, 0)]),  # Middle
        ]
        result = sort_lines(lines, start_point=Point(0, 0))
        # Should be in order: left -> middle -> right
        coords_0 = list(result[0].coords)
        coords_1 = list(result[1].coords)
        coords_2 = list(result[2].coords)
        assert coords_0[0] == (0.0, 0.0)
        assert coords_1[0] == (100.0, 0.0)
        assert coords_2[0] == (200.0, 0.0)

    def test_sort_lines_reduces_travel_distance(self):
        """Sorted lines should have less travel distance than random order."""
        # Create lines in a scrambled order
        lines = [
            LineString([(300, 0), (400, 0)]),
            LineString([(0, 0), (100, 0)]),
            LineString([(200, 0), (300, 0)]),
            LineString([(100, 0), (200, 0)]),
        ]
        result = sort_lines(lines, start_point=Point(0, 0))

        # Calculate travel distance of result
        travel = 0.0
        for i in range(len(result) - 1):
            _, end_curr = next(iter(result[i].coords)), list(result[i].coords)[-1]
            start_next, _ = next(iter(result[i + 1].coords)), list(result[i + 1].coords)[-1]
            dx = start_next[0] - end_curr[0]
            dy = start_next[1] - end_curr[1]
            travel += (dx * dx + dy * dy) ** 0.5

        # Should be minimal (just the gaps between consecutive lines = 0)
        assert travel == 0.0

    def test_sort_lines_2opt_improvement(self):
        """2-opt pass should improve over greedy alone in some cases."""
        # Create a case where greedy makes a suboptimal choice
        # Lines arranged such that greedy picks wrong order
        lines = [
            LineString([(0, 0), (10, 0)]),  # A: start at origin
            LineString([(20, 10), (30, 10)]),  # B: upper right
            LineString([(20, -10), (30, -10)]),  # C: lower right
            LineString([(10, 0), (20, 0)]),  # D: middle connector
        ]
        result = sort_lines(lines, start_point=Point(0, 0))

        # The optimal path should go A -> D -> (B or C) -> (C or B)
        # Total travel should be minimal
        travel = 0.0
        for i in range(len(result) - 1):
            end_curr = list(result[i].coords)[-1]
            start_next = next(iter(result[i + 1].coords))
            dx = start_next[0] - end_curr[0]
            dy = start_next[1] - end_curr[1]
            travel += (dx * dx + dy * dy) ** 0.5

        # Should be very small (lines connect or are very close)
        assert travel < 50.0  # Much less than naive ordering

    def test_sort_lines_start_point_none_uses_first_line(self):
        """When start_point is None, should use first line's start."""
        lines = [
            LineString([(100, 100), (200, 100)]),
            LineString([(0, 0), (50, 0)]),
        ]
        result = sort_lines(lines, start_point=None)
        # Should start with first line in input
        assert next(iter(result[0].coords)) == (100.0, 100.0)

    def test_sort_lines_preserves_line_geometry(self):
        """Sorting should not modify line coordinates, only order and direction."""
        lines = [
            LineString([(0, 0), (50, 25), (100, 0)]),  # Curved line
            LineString([(100, 100), (150, 125), (200, 100)]),
        ]
        result = sort_lines(lines, start_point=Point(0, 0))

        # Check that coordinates are preserved (possibly reversed)
        all_coords = []
        for line in result:
            all_coords.extend(list(line.coords))

        # Original coordinates should all be present (in some order/direction)
        original_coords = [(0, 0), (50, 25), (100, 0), (100, 100), (150, 125), (200, 100)]
        for orig in original_coords:
            assert orig in all_coords

    def test_sort_lines_vertical_lines(self):
        """Should handle vertical lines correctly."""
        lines = [
            LineString([(100, 200), (100, 300)]),
            LineString([(100, 0), (100, 100)]),
            LineString([(100, 100), (100, 200)]),
        ]
        result = sort_lines(lines, start_point=Point(100, 0))

        # Should be ordered bottom to top
        assert next(iter(result[0].coords)) == (100.0, 0.0)
        assert next(iter(result[1].coords)) == (100.0, 100.0)
        assert next(iter(result[2].coords)) == (100.0, 200.0)

    def test_sort_lines_filters_empty_lines(self):
        """Empty lines should be filtered out."""
        lines = [
            LineString([(0, 0), (100, 0)]),
            LineString(),  # Empty
            LineString([(100, 0), (200, 0)]),
        ]
        result = sort_lines(lines)
        assert len(result) == 2

    def test_sort_lines_handles_invalid_geometries(self):
        """Invalid geometries should be filtered out."""
        # Empty line is invalid
        lines = [
            LineString([(0, 0), (100, 0)]),
            LineString(),  # Empty - invalid
        ]
        result = sort_lines(lines)
        assert len(result) == 1
        assert result[0].is_valid

    def test_sort_lines_tie_break_earliest_line_and_start(self):
        """Equal distances go to the earliest line, and a start before an end."""
        tied = [
            LineString([(1, 0), (9, 0)]),
            LineString([(9, 0), (1, 0)]),
        ]
        result = sort_lines(tied, start_point=Point(0, 0))
        assert list(result[0].coords) == [(1.0, 0.0), (9.0, 0.0)]

        symmetrical = [LineString([(1, 0), (-1, 0)])]
        result = sort_lines(symmetrical, start_point=Point(0, 0))
        assert list(result[0].coords) == [(1.0, 0.0), (-1.0, 0.0)]

    def test_sort_lines_complex_shape(self):
        """Test with a more complex arrangement of lines."""
        # Create a spiral-like pattern
        lines = []
        for i in range(10):
            angle = i * 0.5
            r = 50 + i * 10
            x1 = r * math.cos(angle)
            y1 = r * math.sin(angle)
            x2 = (r + 10) * math.cos(angle)
            y2 = (r + 10) * math.sin(angle)
            lines.append(LineString([(x1, y1), (x2, y2)]))

        result = sort_lines(lines, start_point=Point(50, 0))
        assert len(result) == 10

        # Travel distance should be reasonable
        travel = 0.0
        for i in range(len(result) - 1):
            end_curr = list(result[i].coords)[-1]
            start_next = next(iter(result[i + 1].coords))
            dx = start_next[0] - end_curr[0]
            dy = start_next[1] - end_curr[1]
            travel += (dx * dx + dy * dy) ** 0.5

        # Should be much less than random order
        assert travel < 500.0


def _travel(lines: list[LineString]) -> float:
    """Total pen-up travel distance of an ordered sequence of lines."""
    total = 0.0
    for i in range(len(lines) - 1):
        end = list(lines[i].coords)[-1]
        start = next(iter(lines[i + 1].coords))
        total += math.hypot(start[0] - end[0], start[1] - end[1])
    return total


def _strokes(lines: list[LineString]) -> set[tuple[tuple[float, float], ...]]:
    """Stroke coordinates with direction removed, for set comparisons."""
    result = set()
    for line in lines:
        coords = tuple((float(x), float(y)) for x, y in line.coords)
        result.add(min(coords, coords[::-1]))
    return result


def _reference_sort_lines(
    lines: list[LineString], start_point: Point | None = None
) -> list[LineString]:
    """The pre-optimization algorithm, kept as a correctness oracle for tests."""

    def endpoints(line: LineString):
        coords = list(line.coords)
        if not coords:
            return (0.0, 0.0), (0.0, 0.0)
        return (coords[0][0], coords[0][1]), (coords[-1][0], coords[-1][1])

    def distance(p1, p2) -> float:
        return math.hypot(p2[0] - p1[0], p2[1] - p1[1])

    remaining = list(lines)
    ordered: list[LineString] = []
    if start_point is not None:
        current = (start_point.x, start_point.y)
    else:
        current = endpoints(remaining[0])[0]

    while remaining:
        best_idx = -1
        best_dist = float("inf")
        best_reversed = False
        for idx, line in enumerate(remaining):
            start, end = endpoints(line)
            dist_to_start = distance(current, start)
            if dist_to_start < best_dist:
                best_dist, best_idx, best_reversed = dist_to_start, idx, False
            dist_to_end = distance(current, end)
            if dist_to_end < best_dist:
                best_dist, best_idx, best_reversed = dist_to_end, idx, True
        chosen = remaining.pop(best_idx)
        if best_reversed:
            chosen = LineString(list(chosen.coords)[::-1])
        ordered.append(chosen)
        current = endpoints(chosen)[1]

    if len(ordered) >= 3:
        best_distance = _travel(ordered)
        for _ in range(10):
            improved = False
            for i in range(len(ordered)):
                candidate = ordered[:]
                candidate[i] = LineString(list(candidate[i].coords)[::-1])
                candidate_distance = _travel(candidate)
                if candidate_distance < best_distance:
                    best_distance, ordered, improved = candidate_distance, candidate, True
            if not improved:
                break
    return ordered


class TestSortPerformanceAndEquivalence:
    """Scale and equivalence checks for the optimized sort."""

    def test_sort_lines_3000_lines_within_generous_ceiling(self):
        """3000 lines must finish far below the old implementation's cost."""
        lines = [
            LineString(
                [
                    ((i * 37) % 3000, (i * 91) % 3000),
                    ((i * 37) % 3000 + 10, (i * 91) % 3000 + 10),
                ]
            )
            for i in range(3000)
        ]

        started = time.perf_counter()
        result = sort_lines(lines)
        elapsed = time.perf_counter() - started

        assert len(result) == 3000
        assert elapsed < 60.0

    def test_sort_lines_travel_distance_not_worse_than_reference(self):
        """The optimized result must not travel further than the old algorithm."""
        rng = random.Random(42)
        lines = [
            LineString(
                [
                    (rng.uniform(0, 400), rng.uniform(0, 400)),
                    (rng.uniform(0, 400), rng.uniform(0, 400)),
                ]
            )
            for _ in range(60)
        ]
        start = Point(0, 0)

        expected = _reference_sort_lines(lines, start)
        actual = sort_lines(lines, start)

        assert _travel(actual) <= _travel(expected) + 1e-9
        assert _strokes(actual) == _strokes(expected) == _strokes(lines)

    def test_sort_lines_exact_order_matches_reference(self):
        """Optimized order, including each direction, matches the old algorithm."""
        for seed in (1, 2, 3):
            rng = random.Random(seed)
            lines = [
                LineString(
                    [
                        (rng.uniform(0, 200), rng.uniform(0, 200)),
                        (rng.uniform(0, 200), rng.uniform(0, 200)),
                    ]
                )
                for _ in range(30)
            ]
            start = Point(0, 0)
            actual = [list(line.coords) for line in sort_lines(lines, start)]
            expected = [list(line.coords) for line in _reference_sort_lines(lines, start)]
            assert actual == expected

    def test_sort_lines_is_deterministic(self):
        """Repeated calls on the same input produce identical order and direction."""
        rng = random.Random(7)
        lines = [
            LineString(
                [
                    (rng.uniform(0, 100), rng.uniform(0, 100)),
                    (rng.uniform(0, 100), rng.uniform(0, 100)),
                ]
            )
            for _ in range(40)
        ]
        first = [list(line.coords) for line in sort_lines(lines)]
        second = [list(line.coords) for line in sort_lines(lines)]
        assert first == second


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])
