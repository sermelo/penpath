"""Unit tests for line sorting (greedy NN + 2-opt)."""

from __future__ import annotations

import math

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


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])
