"""Unit tests for line simplification (RDP)."""

from __future__ import annotations

import math

import pytest
from shapely import LineString

from penpath.core.geometry.simplify import (
    mm_to_pixels,
    pixels_to_mm,
    simplify,
    simplify_line,
)


class TestMmToPixels:
    """Tests for mm_to_pixels conversion."""

    def test_mm_to_pixels_standard_dpi(self):
        """Test conversion at standard 300 DPI."""
        assert mm_to_pixels(25.4, 300) == 300.0  # 1 inch = 25.4mm = 300px at 300 DPI

    def test_mm_to_pixels_zero(self):
        """Test zero millimetres returns zero pixels."""
        assert mm_to_pixels(0.0, 300) == 0.0

    def test_mm_to_pixels_fractional(self):
        """Test fractional millimetres."""
        result = mm_to_pixels(1.0, 300)
        expected = 300 / 25.4
        assert abs(result - expected) < 1e-10

    def test_mm_to_pixels_different_dpi(self):
        """Test conversion at different DPI values."""
        assert mm_to_pixels(25.4, 600) == 600.0
        assert mm_to_pixels(25.4, 72) == 72.0


class TestPixelsToMm:
    """Tests for pixels_to_mm conversion."""

    def test_pixels_to_mm_standard_dpi(self):
        """Test conversion at standard 300 DPI."""
        assert pixels_to_mm(300, 300) == 25.4

    def test_pixels_to_mm_zero(self):
        """Test zero pixels returns zero millimetres."""
        assert pixels_to_mm(0, 300) == 0.0

    def test_round_trip(self):
        """Test mm -> pixels -> mm round trip."""
        original_mm = 10.5
        dpi = 300
        px = mm_to_pixels(original_mm, dpi)
        back_mm = pixels_to_mm(px, dpi)
        assert abs(back_mm - original_mm) < 1e-10


class TestSimplifyLine:
    """Tests for simplify_line function."""

    def test_simplify_line_zero_tolerance_returns_original(self):
        """Zero tolerance should return the original line unchanged."""
        line = LineString([(0, 0), (10, 5), (20, 0), (30, 5), (40, 0)])
        result = simplify_line(line, tolerance_mm=0.0, paper_dpi=300)
        assert list(result.coords) == list(line.coords)

    def test_simplify_line_straight_line_preserved(self):
        """Straight line should be preserved regardless of tolerance."""
        line = LineString([(0, 0), (100, 0), (200, 0), (300, 0)])
        result = simplify_line(line, tolerance_mm=10.0, paper_dpi=300)
        # Should reduce to just endpoints
        coords = list(result.coords)
        assert len(coords) == 2
        assert coords[0] == (0.0, 0.0)
        assert coords[-1] == (300.0, 0.0)

    def test_simplify_line_high_tolerance_reduces_points(self):
        """High tolerance should significantly reduce point count."""
        # Create a wiggly line
        coords = [(i * 10, 10 * (i % 2)) for i in range(20)]
        line = LineString(coords)
        result = simplify_line(line, tolerance_mm=5.0, paper_dpi=300)
        assert len(result.coords) < len(coords)

    def test_simplify_line_preserves_topology(self):
        """Simplification should preserve topology (no self-intersections)."""
        # Create a line that loops near itself
        coords = [(0, 0), (50, 0), (50, 50), (0, 50), (0, 10), (10, 10)]
        line = LineString(coords)
        result = simplify_line(line, tolerance_mm=1.0, paper_dpi=300)
        assert result.is_valid
        assert not result.is_empty

    def test_simplify_line_keeps_a_closed_ring_intact(self):
        """A stipple circle must stay round instead of becoming a diamond."""
        points = [
            (5.0 + 3.0 * math.cos(2 * math.pi * i / 12), 5.0 + 3.0 * math.sin(2 * math.pi * i / 12))
            for i in range(12)
        ]
        ring = LineString([*points, points[0]])

        result = simplify_line(ring, tolerance_mm=0.1, paper_dpi=300)

        assert list(result.coords) == list(ring.coords)

    def test_simplify_line_large_ring_still_simplifies(self):
        """Only small dot rings are protected; large contours still simplify."""
        points = [
            (
                100.0 + 100.0 * math.cos(2 * math.pi * i / 48),
                100.0 + 100.0 * math.sin(2 * math.pi * i / 48),
            )
            for i in range(48)
        ]
        ring = LineString([*points, points[0]])

        result = simplify_line(ring, tolerance_mm=0.1, paper_dpi=300)

        assert len(result.coords) < len(ring.coords)

    def test_simplify_line_empty_line(self):
        """Empty line should return empty line."""
        line = LineString()
        result = simplify_line(line, tolerance_mm=1.0, paper_dpi=300)
        assert result.is_empty

    def test_simplify_line_single_point(self):
        """Line with single point should be handled gracefully (shapely requires 2+ points)."""
        # Shapely LineString requires at least 2 points, so we test with a minimal line
        line = LineString([(100, 100), (100.1, 100.1)])
        result = simplify_line(line, tolerance_mm=1.0, paper_dpi=300)
        assert result.is_valid

    def test_simplify_line_two_points(self):
        """Line with two points should be preserved."""
        line = LineString([(0, 0), (100, 100)])
        result = simplify_line(line, tolerance_mm=10.0, paper_dpi=300)
        assert list(result.coords) == [(0.0, 0.0), (100.0, 100.0)]

    def test_simplify_line_collapses_to_point(self):
        """Very high tolerance on short line may collapse to point."""
        line = LineString([(0, 0), (1, 0), (2, 0)])
        result = simplify_line(line, tolerance_mm=100.0, paper_dpi=300)
        # Should return a minimal line with endpoints
        assert result.is_valid
        if result.geom_type == "LineString":
            coords = list(result.coords)
            assert len(coords) >= 2


class TestSimplify:
    """Tests for simplify function (iterable version)."""

    def test_simplify_empty_list(self):
        """Empty list should return empty list."""
        result = simplify([], tolerance_mm=1.0, paper_dpi=300)
        assert result == []

    def test_simplify_multiple_lines(self):
        """Should simplify multiple lines independently."""
        lines = [
            LineString([(0, 0), (10, 5), (20, 0)]),
            LineString([(0, 100), (10, 105), (20, 100)]),
        ]
        result = simplify(lines, tolerance_mm=2.0, paper_dpi=300)
        assert len(result) == 2
        for r in result:
            assert r.is_valid

    def test_simplify_preserves_order(self):
        """Output order should match input order."""
        lines = [
            LineString([(0, 0), (10, 0)]),
            LineString([(100, 100), (110, 100)]),
            LineString([(200, 200), (210, 200)]),
        ]
        result = simplify(lines, tolerance_mm=0.0, paper_dpi=300)
        for orig, simp in zip(lines, result, strict=False):
            assert list(orig.coords) == list(simp.coords)

    def test_simplify_zero_tolerance_identity(self):
        """Zero tolerance should be identity for all lines."""
        lines = [
            LineString([(0, 0), (10, 5), (20, 0)]),
            LineString([(0, 100), (10, 105), (20, 100), (30, 105)]),
        ]
        result = simplify(lines, tolerance_mm=0.0, paper_dpi=300)
        for orig, simp in zip(lines, result, strict=False):
            assert list(orig.coords) == list(simp.coords)

    def test_simplify_custom_dpi(self):
        """Should respect custom DPI parameter."""
        line = LineString([(0, 0), (10, 5), (20, 0)])
        result_300 = simplify([line], tolerance_mm=1.0, paper_dpi=300)
        result_600 = simplify([line], tolerance_mm=1.0, paper_dpi=600)
        # Higher DPI = more pixels per mm = tighter tolerance in pixels = less simplification
        # So 600 DPI should preserve more points
        assert len(result_600[0].coords) >= len(result_300[0].coords)


class TestSimplifyErrorHandling:
    """Tests for error handling in simplify functions."""

    def test_simplify_negative_tolerance_raises(self):
        """Negative tolerance should raise ValueError."""
        line = LineString([(0, 0), (10, 0)])
        with pytest.raises(ValueError, match="tolerance_mm must be >="):
            simplify_line(line, tolerance_mm=-1.0, paper_dpi=300)

    def test_simplify_zero_dpi_raises(self):
        """Zero DPI should raise ValueError."""
        line = LineString([(0, 0), (10, 0)])
        with pytest.raises(ValueError, match="paper_dpi must be > 0"):
            simplify_line(line, tolerance_mm=1.0, paper_dpi=0)

    def test_simplify_negative_dpi_raises(self):
        """Negative DPI should raise ValueError."""
        line = LineString([(0, 0), (10, 0)])
        with pytest.raises(ValueError, match="paper_dpi must be > 0"):
            simplify_line(line, tolerance_mm=1.0, paper_dpi=-300)


class TestSimplifyRealWorld:
    """Tests with more realistic scenarios."""

    def test_simplify_preserves_endpoints(self):
        """Endpoints of lines should always be preserved."""
        line = LineString([(0, 0), (50, 25), (100, 0), (150, 25), (200, 0)])
        result = simplify_line(line, tolerance_mm=5.0, paper_dpi=300)
        coords = list(result.coords)
        assert coords[0] == (0.0, 0.0)
        assert coords[-1] == (200.0, 0.0)

    def test_simplify_horizontal_line(self):
        """Horizontal line should simplify to endpoints."""
        line = LineString([(0, 100), (50, 100), (100, 100), (150, 100), (200, 100)])
        result = simplify_line(line, tolerance_mm=1.0, paper_dpi=300)
        coords = list(result.coords)
        assert len(coords) == 2
        assert coords[0] == (0.0, 100.0)
        assert coords[-1] == (200.0, 100.0)

    def test_simplify_vertical_line(self):
        """Vertical line should simplify to endpoints."""
        line = LineString([(100, 0), (100, 50), (100, 100), (100, 150), (100, 200)])
        result = simplify_line(line, tolerance_mm=1.0, paper_dpi=300)
        coords = list(result.coords)
        assert len(coords) == 2
        assert coords[0] == (100.0, 0.0)
        assert coords[-1] == (100.0, 200.0)

    def test_simplify_diagonal_line(self):
        """Diagonal line should simplify to endpoints."""
        line = LineString([(0, 0), (50, 50), (100, 100), (150, 150), (200, 200)])
        result = simplify_line(line, tolerance_mm=1.0, paper_dpi=300)
        coords = list(result.coords)
        assert len(coords) == 2
        assert coords[0] == (0.0, 0.0)
        assert coords[-1] == (200.0, 200.0)


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])
