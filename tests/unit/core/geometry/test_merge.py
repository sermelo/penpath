"""Unit tests for line merging and collinear join."""

from __future__ import annotations

import pytest
from shapely import LineString

from penpath.core.geometry.merge import (
    merge_lines,
    mm_to_pixels,
)


class TestMmToPixels:
    """Tests for mm_to_pixels conversion in merge module."""

    def test_mm_to_pixels_standard_dpi(self):
        """Test conversion at standard 300 DPI."""
        assert mm_to_pixels(25.4, 300) == 300.0

    def test_mm_to_pixels_zero(self):
        """Test zero millimetres returns zero pixels."""
        assert mm_to_pixels(0.0, 300) == 0.0


class TestMergeLines:
    """Tests for merge_lines function."""

    def test_merge_lines_empty_list(self):
        """Empty list should return empty list."""
        result = merge_lines([], angle_tol_deg=5.0, dist_tol_mm=0.1, paper_dpi=300)
        assert result == []

    def test_merge_lines_single_line(self):
        """Single line should be returned unchanged."""
        line = LineString([(0, 0), (100, 100)])
        result = merge_lines([line], angle_tol_deg=5.0, dist_tol_mm=0.1, paper_dpi=300)
        assert len(result) == 1
        assert list(result[0].coords) == [(0.0, 0.0), (100.0, 100.0)]

    def test_merge_lines_exact_endpoint_join(self):
        """Lines sharing exact endpoints should be merged by linemerge."""
        lines = [
            LineString([(0, 0), (100, 0)]),
            LineString([(100, 0), (200, 0)]),
        ]
        result = merge_lines(lines, angle_tol_deg=5.0, dist_tol_mm=0.1, paper_dpi=300)
        assert len(result) == 1
        coords = list(result[0].coords)
        assert coords == [(0.0, 0.0), (100.0, 0.0), (200.0, 0.0)]

    def test_merge_lines_keeps_zero_length_strokes(self):
        """A tap is a real stroke and must not be dropped by linemerge."""
        taps = [
            LineString([(5, 5), (5, 5)]),
            LineString([(9, 9), (9, 9)]),
            LineString([(20, 20), (30, 20)]),
        ]

        result = merge_lines(taps, angle_tol_deg=5.0, dist_tol_mm=0.1, paper_dpi=300)

        assert [list(line.coords) for line in result] == [
            [(20.0, 20.0), (30.0, 20.0)],
            [(5.0, 5.0), (5.0, 5.0)],
            [(9.0, 9.0), (9.0, 9.0)],
        ]

    def test_merge_lines_disjoint_lines_unchanged(self):
        """Disjoint lines should remain separate."""
        lines = [
            LineString([(0, 0), (100, 0)]),
            LineString([(200, 0), (300, 0)]),
        ]
        result = merge_lines(lines, angle_tol_deg=5.0, dist_tol_mm=0.1, paper_dpi=300)
        assert len(result) == 2

    def test_merge_lines_collinear_join_small_gap(self):
        """Near-collinear lines with small gap should be joined."""
        lines = [
            LineString([(0, 0), (100, 0)]),
            LineString([(101, 0), (200, 0)]),  # 1 pixel gap
        ]
        # 0.1mm at 300 DPI = ~1.18 pixels
        result = merge_lines(lines, angle_tol_deg=5.0, dist_tol_mm=0.1, paper_dpi=300)
        assert len(result) == 1
        coords = list(result[0].coords)
        assert coords[0] == (0.0, 0.0)
        assert coords[-1] == (200.0, 0.0)

    def test_merge_lines_collinear_join_large_gap_not_joined(self):
        """Near-collinear lines with large gap should NOT be joined."""
        lines = [
            LineString([(0, 0), (100, 0)]),
            LineString([(150, 0), (200, 0)]),  # 50 pixel gap
        ]
        # 0.1mm at 300 DPI = ~1.18 pixels, gap is much larger
        result = merge_lines(lines, angle_tol_deg=5.0, dist_tol_mm=0.1, paper_dpi=300)
        assert len(result) == 2

    def test_merge_lines_angle_tolerance(self):
        """Lines within angle tolerance should be joined."""
        # Two lines at 2 degree angle
        lines = [
            LineString([(0, 0), (100, 0)]),
            LineString([(100, 0), (200, 7)]),  # ~2 degrees
        ]
        result = merge_lines(lines, angle_tol_deg=5.0, dist_tol_mm=0.1, paper_dpi=300)
        assert len(result) == 1

    def test_merge_lines_angle_exceeds_tolerance(self):
        """Lines exceeding angle tolerance should NOT be joined."""
        # Two lines at 10 degree angle with small gap (so linemerge doesn't join)
        lines = [
            LineString([(0, 0), (100, 0)]),
            LineString([(101, 0), (201, 35)]),  # ~10 degrees, 1 pixel gap
        ]
        result = merge_lines(lines, angle_tol_deg=5.0, dist_tol_mm=0.1, paper_dpi=300)
        assert len(result) == 2

    def test_merge_lines_opposite_direction(self):
        """Lines in opposite directions (180 deg) should not join with default tolerance."""
        lines = [
            LineString([(0, 0), (100, 0)]),
            LineString([(101, 0), (1, 0)]),  # Back along same path, small gap
        ]
        result = merge_lines(lines, angle_tol_deg=5.0, dist_tol_mm=0.1, paper_dpi=300)
        # 180 degrees > 5 degrees, so should not join
        assert len(result) == 2

    def test_merge_lines_opposite_direction_high_tolerance(self):
        """Lines in opposite directions should join with high angle tolerance."""
        lines = [
            LineString([(0, 0), (100, 0)]),
            LineString([(101, 0), (1, 0)]),  # Back along same path, small gap
        ]
        result = merge_lines(lines, angle_tol_deg=180.0, dist_tol_mm=0.1, paper_dpi=300)
        assert len(result) == 1

    def test_merge_lines_preserves_order(self):
        """Merged lines should preserve the order of input segments."""
        lines = [
            LineString([(0, 0), (100, 0)]),
            LineString([(100, 0), (200, 0)]),
            LineString([(200, 0), (300, 0)]),
        ]
        result = merge_lines(lines, angle_tol_deg=5.0, dist_tol_mm=0.1, paper_dpi=300)
        assert len(result) == 1
        coords = list(result[0].coords)
        assert coords == [(0.0, 0.0), (100.0, 0.0), (200.0, 0.0), (300.0, 0.0)]

    def test_merge_lines_complex_branch(self):
        """Branching lines should only merge collinear sequences."""
        lines = [
            LineString([(0, 0), (100, 0)]),  # Horizontal
            LineString([(100, 0), (200, 0)]),  # Continues horizontal
            LineString([(100, 0), (100, 100)]),  # Branch up
        ]
        result = merge_lines(lines, angle_tol_deg=5.0, dist_tol_mm=0.1, paper_dpi=300)
        # Should merge first two, keep branch separate
        assert len(result) == 2
        # Find the long horizontal line
        horiz = max(result, key=lambda line: line.length)
        coords = list(horiz.coords)
        assert coords == [(0.0, 0.0), (100.0, 0.0), (200.0, 0.0)]

    def test_merge_lines_custom_dpi(self):
        """Should respect custom DPI for distance tolerance."""
        lines = [
            LineString([(0, 0), (100, 0)]),
            LineString([(105, 0), (200, 0)]),  # 5 pixel gap
        ]
        # At 300 DPI: 0.5mm = ~5.9 pixels -> should join
        result_300 = merge_lines(lines, angle_tol_deg=5.0, dist_tol_mm=0.5, paper_dpi=300)
        # At 600 DPI: 0.5mm = ~11.8 pixels -> should also join (gap is 5px)
        result_600 = merge_lines(lines, angle_tol_deg=5.0, dist_tol_mm=0.5, paper_dpi=600)
        assert len(result_300) == 1
        assert len(result_600) == 1

        # At 300 DPI: 0.1mm = ~1.18 pixels -> should NOT join (gap is 5px)
        result_tight = merge_lines(lines, angle_tol_deg=5.0, dist_tol_mm=0.1, paper_dpi=300)
        assert len(result_tight) == 2


class TestMergeLinesErrorHandling:
    """Tests for error handling in merge_lines."""

    def test_merge_lines_negative_angle_tolerance_raises(self):
        """Negative angle tolerance should raise ValueError."""
        lines = [LineString([(0, 0), (100, 0)])]
        with pytest.raises(ValueError, match="angle_tol_deg must be in"):
            merge_lines(lines, angle_tol_deg=-1.0, dist_tol_mm=0.1, paper_dpi=300)

    def test_merge_lines_angle_tolerance_too_high_raises(self):
        """Angle tolerance > 180 should raise ValueError."""
        lines = [LineString([(0, 0), (100, 0)])]
        with pytest.raises(ValueError, match="angle_tol_deg must be in"):
            merge_lines(lines, angle_tol_deg=181.0, dist_tol_mm=0.1, paper_dpi=300)

    def test_merge_lines_negative_distance_tolerance_raises(self):
        """Negative distance tolerance should raise ValueError."""
        lines = [LineString([(0, 0), (100, 0)])]
        with pytest.raises(ValueError, match="dist_tol_mm must be >="):
            merge_lines(lines, angle_tol_deg=5.0, dist_tol_mm=-0.1, paper_dpi=300)

    def test_merge_lines_zero_dpi_raises(self):
        """Zero DPI should raise ValueError."""
        lines = [LineString([(0, 0), (100, 0)])]
        with pytest.raises(ValueError, match="paper_dpi must be > 0"):
            merge_lines(lines, angle_tol_deg=5.0, dist_tol_mm=0.1, paper_dpi=0)


class TestMergeLinesRealWorld:
    """Tests with more realistic scenarios."""

    def test_merge_lines_sketch_output_simulation(self):
        """Simulate merging output from sketch lines (many short segments)."""
        # Simulate a long line broken into many small segments
        coords = [(i * 10, 5 * (i % 2)) for i in range(20)]  # Wiggly but mostly horizontal
        lines = [LineString([coords[i], coords[i + 1]]) for i in range(len(coords) - 1)]

        result = merge_lines(lines, angle_tol_deg=10.0, dist_tol_mm=0.5, paper_dpi=300)
        # Should merge most segments into fewer lines
        assert len(result) < len(lines)
        assert len(result) >= 1

    def test_merge_lines_preserves_geometry_validity(self):
        """All output lines should be valid geometries."""
        lines = [
            LineString([(0, 0), (100, 0)]),
            LineString([(100, 0), (200, 0)]),
            LineString([(200, 0), (200, 100)]),
        ]
        result = merge_lines(lines, angle_tol_deg=5.0, dist_tol_mm=0.1, paper_dpi=300)
        for line in result:
            assert line.is_valid
            assert not line.is_empty

    def test_merge_lines_filters_empty_lines(self):
        """Empty lines in input should be filtered out."""
        lines = [
            LineString([(0, 0), (100, 0)]),
            LineString(),  # Empty
            LineString([(100, 0), (200, 0)]),
        ]
        result = merge_lines(lines, angle_tol_deg=5.0, dist_tol_mm=0.1, paper_dpi=300)
        assert len(result) == 1
        coords = list(result[0].coords)
        assert coords == [(0.0, 0.0), (100.0, 0.0), (200.0, 0.0)]

    def test_merge_lines_handles_invalid_geometries(self):
        """Invalid geometries should be handled gracefully."""
        # Create a valid line and an invalid one (self-intersecting)
        lines = [
            LineString([(0, 0), (100, 0)]),
            LineString([(0, 0), (100, 100), (0, 100), (100, 0)]),  # Self-intersecting
        ]
        result = merge_lines(lines, angle_tol_deg=5.0, dist_tol_mm=0.1, paper_dpi=300)
        # Should only return valid lines
        for line in result:
            assert line.is_valid

    def test_merge_lines_zero_distance_tolerance(self):
        """Zero distance tolerance should only join exact endpoints."""
        lines = [
            LineString([(0, 0), (100, 0)]),
            LineString([(100, 0), (200, 0)]),  # Exact endpoint
            LineString([(201, 0), (300, 0)]),  # 1 pixel gap
        ]
        result = merge_lines(lines, angle_tol_deg=5.0, dist_tol_mm=0.0, paper_dpi=300)
        assert len(result) == 2  # First two join, third separate
        # Find the merged line
        merged = max(result, key=lambda line: line.length)
        coords = list(merged.coords)
        assert coords == [(0.0, 0.0), (100.0, 0.0), (200.0, 0.0)]


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])
