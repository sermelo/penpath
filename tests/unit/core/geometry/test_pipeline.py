"""Unit tests for geometry optimization pipeline."""

from __future__ import annotations

import pytest
from shapely import LineString

from penpath.core.geometry.pipeline import optimize
from penpath.core.models import Paper


class TestOptimize:
    """Tests for optimize pipeline function."""

    def test_optimize_empty_list(self):
        """Empty list should return empty list."""
        paper = Paper(name="A4", width_mm=210, height_mm=297)
        result = optimize([], paper)
        assert result == []

    def test_optimize_single_line(self):
        """Single line should pass through pipeline."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        line = LineString([(0, 0), (100, 100)])
        result = optimize([line], paper)
        assert len(result) == 1
        assert result[0].is_valid

    def test_optimize_simplify_step(self):
        """Simplify step should reduce points on wiggly line."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        # Wiggly line with many points
        coords = [(i * 10, 10 * (i % 2)) for i in range(20)]
        line = LineString(coords)
        result = optimize([line], paper, simplify_tol_mm=1.0)
        # Should have fewer points
        assert len(result[0].coords) < len(coords)

    def test_optimize_simplify_zero_tolerance_skips(self):
        """Zero simplify tolerance should skip simplification."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        coords = [(i * 10, 10 * (i % 2)) for i in range(20)]
        line = LineString(coords)
        result = optimize([line], paper, simplify_tol_mm=0.0)
        # Should preserve all points (within floating point)
        assert len(result[0].coords) >= len(coords) - 1

    def test_optimize_merge_step(self):
        """Merge step should join collinear segments."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        lines = [
            LineString([(0, 0), (100, 0)]),
            LineString([(100, 0), (200, 0)]),
            LineString([(200, 0), (300, 0)]),
        ]
        result = optimize(lines, paper, merge_angle_deg=5.0, merge_dist_mm=0.1)
        assert len(result) == 1
        coords = list(result[0].coords)
        assert coords == [(0.0, 0.0), (100.0, 0.0), (200.0, 0.0), (300.0, 0.0)]

    def test_optimize_sort_step(self):
        """Sort step should reorder lines to minimize travel."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        # Use lines with gaps so they don't get merged
        lines = [
            LineString([(300, 0), (400, 0)]),
            LineString([(0, 0), (100, 0)]),
            LineString([(150, 0), (250, 0)]),  # Gap from 100 to 150
            LineString([(350, 0), (450, 0)]),  # Gap from 300 to 350
        ]
        result = optimize(lines, paper, merge_dist_mm=0.0)  # No gap merging
        # Should be in order from left to right
        assert next(iter(result[0].coords)) == (0.0, 0.0)
        assert next(iter(result[1].coords)) == (150.0, 0.0)
        assert next(iter(result[2].coords)) == (300.0, 0.0)
        assert next(iter(result[3].coords)) == (350.0, 0.0)

    def test_optimize_full_pipeline_order(self):
        """Pipeline should execute in correct order: simplify -> merge -> sort."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)

        # Create lines that need all three steps
        # 1. Wiggly segments that can be simplified
        # 2. Collinear segments that can be merged
        # 3. Scrambled order that needs sorting
        lines = [
            LineString([(300, 0), (310, 5), (320, 0), (330, 5), (340, 0)]),  # Segment 3
            LineString([(0, 0), (10, 5), (20, 0), (30, 5), (40, 0)]),        # Segment 0
            LineString([(100, 0), (110, 5), (120, 0), (130, 5), (140, 0)]),  # Segment 1
            LineString([(200, 0), (210, 5), (220, 0), (230, 5), (240, 0)]),  # Segment 2
        ]

        result = optimize(
            lines,
            paper,
            simplify_tol_mm=1.0,
            merge_angle_deg=10.0,
            merge_dist_mm=1.0,
        )

        # Should have fewer lines after merge (they connect)
        assert len(result) <= len(lines)
        # Should be sorted left to right
        assert next(iter(result[0].coords))[0] < next(iter(result[-1].coords))[0]

    def test_optimize_reduces_travel_distance(self):
        """Full pipeline should reduce travel distance vs unsorted input."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)

        lines = [
            LineString([(300, 0), (400, 0)]),
            LineString([(0, 0), (100, 0)]),
            LineString([(200, 0), (300, 0)]),
            LineString([(100, 0), (200, 0)]),
        ]

        result = optimize(lines, paper)

        # Calculate travel distance
        travel = 0.0
        for i in range(len(result) - 1):
            end_curr = list(result[i].coords)[-1]
            start_next = next(iter(result[i + 1].coords))
            dx = start_next[0] - end_curr[0]
            dy = start_next[1] - end_curr[1]
            travel += (dx * dx + dy * dy) ** 0.5

        # Should be minimal (lines connect end-to-end)
        assert travel < 10.0

    def test_optimize_custom_paper_dpi(self):
        """Should respect paper DPI for mm conversions."""
        paper_300 = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        paper_600 = Paper(name="A4", width_mm=210, height_mm=297, dpi=600)

        line = LineString([(0, 0), (10, 5), (20, 0), (30, 5), (40, 0)])

        result_300 = optimize([line], paper_300, simplify_tol_mm=0.5)
        result_600 = optimize([line], paper_600, simplify_tol_mm=0.5)

        # Higher DPI = more pixels per mm = tighter tolerance = less simplification
        # So 600 DPI should preserve more points
        assert len(result_600[0].coords) >= len(result_300[0].coords)

    def test_optimize_preserves_geometry_validity(self):
        """All output lines should be valid."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        lines = [
            LineString([(0, 0), (100, 0)]),
            LineString([(100, 0), (200, 0)]),
            LineString([(200, 0), (200, 100)]),
        ]
        result = optimize(lines, paper)
        for line in result:
            assert line.is_valid
            assert not line.is_empty

    def test_optimize_handles_invalid_input_lines(self):
        """Invalid input lines should be filtered out."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        lines = [
            LineString([(0, 0), (100, 0)]),
            LineString([(0, 0), (100, 100), (0, 100), (100, 0)]),  # Self-intersecting
        ]
        result = optimize(lines, paper)
        for line in result:
            assert line.is_valid


class TestOptimizeErrorHandling:
    """Tests for error handling in optimize."""

    def test_optimize_negative_simplify_tolerance_raises(self):
        """Negative simplify tolerance should raise ValueError."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        lines = [LineString([(0, 0), (100, 0)])]
        with pytest.raises(ValueError, match="simplify_tol_mm must be >="):
            optimize(lines, paper, simplify_tol_mm=-1.0)

    def test_optimize_invalid_merge_angle_raises(self):
        """Invalid merge angle should raise ValueError."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        lines = [LineString([(0, 0), (100, 0)])]
        with pytest.raises(ValueError, match="merge_angle_deg must be in"):
            optimize(lines, paper, merge_angle_deg=-1.0)
        with pytest.raises(ValueError, match="merge_angle_deg must be in"):
            optimize(lines, paper, merge_angle_deg=181.0)

    def test_optimize_negative_merge_distance_raises(self):
        """Negative merge distance should raise ValueError."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        lines = [LineString([(0, 0), (100, 0)])]
        with pytest.raises(ValueError, match="merge_dist_mm must be >="):
            optimize(lines, paper, merge_dist_mm=-0.1)


class TestOptimizeIntegration:
    """Integration-style tests for the full pipeline."""

    def test_optimize_sketch_lines_simulation(self):
        """Simulate typical sketch lines output."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)

        # Simulate many short segments from sketch lines
        # Use nearly collinear segments so they can be merged
        lines = []
        for i in range(0, 500, 20):
            # Horizontal segments with very small vertical jitter (< 1 degree)
            y = 100 + (i % 10) * 0.1
            lines.append(LineString([(i, y), (i + 20, y)]))

        result = optimize(
            lines,
            paper,
            simplify_tol_mm=0.2,
            merge_angle_deg=5.0,
            merge_dist_mm=1.0,  # Allow 1mm gap merging
        )

        # Should merge into fewer, longer lines
        assert len(result) < len(lines)
        assert len(result) >= 1

        # Total length should be preserved (approximately)
        original_length = sum(line.length for line in lines)
        result_length = sum(line.length for line in result)
        # Allow small difference due to simplification
        assert abs(result_length - original_length) / original_length < 0.05

    def test_optimize_branch_preservation(self):
        """Branching structures should be preserved (not over-merged)."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)

        # Create lines where trunk is separate from branches
        # so linemerge can join the trunk
        lines = [
            LineString([(0, 0), (100, 0)]),      # Main trunk start
            LineString([(100, 0), (200, 0)]),    # Trunk continuation
            LineString([(200, 0), (200, 100)]),  # Branch at end
            LineString([(200, 0), (200, -100)]), # Another branch at end
        ]

        result = optimize(
            lines,
            paper,
            simplify_tol_mm=0.0,
            merge_angle_deg=5.0,
            merge_dist_mm=0.1,
        )

        # Should merge trunk into one line, keep branches separate
        # Note: linemerge merges trunk, collinear join preserves branches
        assert len(result) == 3  # One long trunk + two branches
        # Find the trunk (longest)
        trunk = max(result, key=lambda line: line.length)
        coords = list(trunk.coords)
        assert coords[0] == (0.0, 0.0)
        assert coords[-1] == (200.0, 0.0)


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])
