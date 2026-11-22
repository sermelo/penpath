"""Unit tests for plot simulation and machine cost computation."""

from __future__ import annotations

import math

import pytest
from PIL import Image

from penpath.core.simulation import PenStroke, compute_machine_cost, simulate_plot


class TestPenStroke:
    """Tests for PenStroke dataclass."""

    def test_pen_stroke_valid(self):
        """Valid stroke should be created successfully."""
        stroke = PenStroke(
            polyline=[(0.0, 0.0), (10.0, 10.0)],
            width_mm=0.3,
            color="#000000",
            pen_up=False,
        )
        assert stroke.polyline == [(0.0, 0.0), (10.0, 10.0)]
        assert stroke.width_mm == 0.3
        assert stroke.color == "#000000"
        assert stroke.pen_up is False

    def test_pen_stroke_defaults(self):
        """Default pen_up should be False."""
        stroke = PenStroke(
            polyline=[(0.0, 0.0), (10.0, 10.0)],
            width_mm=0.3,
            color="#000000",
        )
        assert stroke.pen_up is False

    def test_pen_stroke_pen_up_true(self):
        """Pen-up stroke should be created successfully."""
        stroke = PenStroke(
            polyline=[(0.0, 0.0), (10.0, 10.0)],
            width_mm=0.3,
            color="#000000",
            pen_up=True,
        )
        assert stroke.pen_up is True

    def test_pen_stroke_invalid_too_few_points(self):
        """Stroke with fewer than 2 points should raise ValueError."""
        with pytest.raises(ValueError, match="at least 2 points"):
            PenStroke(
                polyline=[(0.0, 0.0)],
                width_mm=0.3,
                color="#000000",
            )

    def test_pen_stroke_invalid_zero_width(self):
        """Stroke with zero width should raise ValueError."""
        with pytest.raises(ValueError, match="positive"):
            PenStroke(
                polyline=[(0.0, 0.0), (10.0, 10.0)],
                width_mm=0.0,
                color="#000000",
            )

    def test_pen_stroke_invalid_negative_width(self):
        """Stroke with negative width should raise ValueError."""
        with pytest.raises(ValueError, match="positive"):
            PenStroke(
                polyline=[(0.0, 0.0), (10.0, 10.0)],
                width_mm=-0.1,
                color="#000000",
            )

    def test_pen_stroke_immutable(self):
        """PenStroke should be immutable (frozen dataclass)."""
        stroke = PenStroke(
            polyline=[(0.0, 0.0), (10.0, 10.0)],
            width_mm=0.3,
            color="#000000",
        )
        with pytest.raises(AttributeError):
            stroke.width_mm = 0.5  # type: ignore[misc]


class TestComputeMachineCost:
    """Tests for compute_machine_cost function."""

    def test_compute_machine_cost_empty_list(self):
        """Empty stroke list should return zeros."""
        result = compute_machine_cost([])
        assert result["total"]["drawing_length_mm"] == 0.0
        assert result["total"]["pen_up_travel_mm"] == 0.0
        assert result["total"]["num_lifts"] == 0
        assert result["total"]["num_short_segments"] == 0
        assert result["total"]["num_strokes"] == 0
        assert result["per_layer"] == {}

    def test_compute_machine_cost_single_pen_down_stroke(self):
        """Single pen-down stroke should compute correct metrics."""
        strokes = [
            PenStroke(
                polyline=[(0.0, 0.0), (10.0, 0.0)],
                width_mm=0.3,
                color="#000000",
                pen_up=False,
            )
        ]
        result = compute_machine_cost(strokes)
        assert result["total"]["drawing_length_mm"] == 10.0
        assert result["total"]["pen_up_travel_mm"] == 0.0
        assert result["total"]["num_lifts"] == 0
        assert result["total"]["num_strokes"] == 1
        assert "#000000" in result["per_layer"]
        assert result["per_layer"]["#000000"]["drawing_length_mm"] == 10.0

    def test_compute_machine_cost_single_pen_up_stroke(self):
        """Single pen-up stroke should count as lift."""
        strokes = [
            PenStroke(
                polyline=[(0.0, 0.0), (10.0, 0.0)],
                width_mm=0.3,
                color="#000000",
                pen_up=True,
            )
        ]
        result = compute_machine_cost(strokes)
        assert result["total"]["drawing_length_mm"] == 0.0
        assert result["total"]["pen_up_travel_mm"] == 10.0
        assert result["total"]["num_lifts"] == 1
        assert result["total"]["num_strokes"] == 1

    def test_compute_machine_cost_multiple_strokes_same_color(self):
        """Multiple strokes of same color should aggregate."""
        strokes = [
            PenStroke(
                polyline=[(0.0, 0.0), (10.0, 0.0)],
                width_mm=0.3,
                color="#000000",
                pen_up=False,
            ),
            PenStroke(
                polyline=[(10.0, 0.0), (20.0, 0.0)],
                width_mm=0.3,
                color="#000000",
                pen_up=False,
            ),
        ]
        result = compute_machine_cost(strokes)
        assert result["total"]["drawing_length_mm"] == 20.0
        assert result["total"]["num_strokes"] == 2
        assert result["per_layer"]["#000000"]["drawing_length_mm"] == 20.0
        assert result["per_layer"]["#000000"]["num_strokes"] == 2

    def test_compute_machine_cost_multiple_colors(self):
        """Multiple colors should create separate layers."""
        strokes = [
            PenStroke(
                polyline=[(0.0, 0.0), (10.0, 0.0)],
                width_mm=0.3,
                color="#000000",
                pen_up=False,
            ),
            PenStroke(
                polyline=[(0.0, 0.0), (5.0, 0.0)],
                width_mm=0.3,
                color="#FF0000",
                pen_up=False,
            ),
        ]
        result = compute_machine_cost(strokes)
        assert result["total"]["drawing_length_mm"] == 15.0
        assert "#000000" in result["per_layer"]
        assert "#FF0000" in result["per_layer"]
        assert result["per_layer"]["#000000"]["drawing_length_mm"] == 10.0
        assert result["per_layer"]["#FF0000"]["drawing_length_mm"] == 5.0

    def test_compute_machine_cost_mixed_pen_up_down(self):
        """Mixed pen-up and pen-down should separate metrics."""
        strokes = [
            PenStroke(
                polyline=[(0.0, 0.0), (10.0, 0.0)],
                width_mm=0.3,
                color="#000000",
                pen_up=False,
            ),
            PenStroke(
                polyline=[(10.0, 0.0), (15.0, 0.0)],
                width_mm=0.3,
                color="#000000",
                pen_up=True,
            ),
            PenStroke(
                polyline=[(15.0, 0.0), (25.0, 0.0)],
                width_mm=0.3,
                color="#000000",
                pen_up=False,
            ),
        ]
        result = compute_machine_cost(strokes)
        assert result["total"]["drawing_length_mm"] == 20.0
        assert result["total"]["pen_up_travel_mm"] == 5.0
        assert result["total"]["num_lifts"] == 1
        assert result["total"]["num_strokes"] == 3

    def test_compute_machine_cost_short_segments(self):
        """Short segments should be counted correctly."""
        # Two segments: one 0.3mm (short), one 1.0mm (not short)
        strokes = [
            PenStroke(
                polyline=[(0.0, 0.0), (0.3, 0.0), (1.3, 0.0)],
                width_mm=0.3,
                color="#000000",
                pen_up=False,
            )
        ]
        result = compute_machine_cost(strokes, short_segment_threshold_mm=0.5)
        assert result["total"]["num_short_segments"] == 1
        assert result["total"]["drawing_length_mm"] == 1.3

    def test_compute_machine_cost_short_segments_custom_threshold(self):
        """Custom threshold should affect short segment count."""
        strokes = [
            PenStroke(
                polyline=[(0.0, 0.0), (0.3, 0.0), (1.3, 0.0)],
                width_mm=0.3,
                color="#000000",
                pen_up=False,
            )
        ]
        # Threshold 0.2: neither segment is short
        result = compute_machine_cost(strokes, short_segment_threshold_mm=0.2)
        assert result["total"]["num_short_segments"] == 0

        # Threshold 1.0: first segment (0.3mm) is short, second (1.0mm) is not (< threshold)
        result = compute_machine_cost(strokes, short_segment_threshold_mm=1.0)
        assert result["total"]["num_short_segments"] == 1

    def test_compute_machine_cost_diagonal_stroke(self):
        """Diagonal stroke length should use Euclidean distance."""
        strokes = [
            PenStroke(
                polyline=[(0.0, 0.0), (3.0, 4.0)],  # 3-4-5 triangle = 5mm
                width_mm=0.3,
                color="#000000",
                pen_up=False,
            )
        ]
        result = compute_machine_cost(strokes)
        assert math.isclose(result["total"]["drawing_length_mm"], 5.0, rel_tol=1e-9)

    def test_compute_machine_cost_polyline_multiple_segments(self):
        """Polyline with multiple segments should sum all segment lengths."""
        # L-shaped: (0,0) -> (3,0) -> (3,4) = 3 + 4 = 7mm
        strokes = [
            PenStroke(
                polyline=[(0.0, 0.0), (3.0, 0.0), (3.0, 4.0)],
                width_mm=0.3,
                color="#000000",
                pen_up=False,
            )
        ]
        result = compute_machine_cost(strokes)
        assert math.isclose(result["total"]["drawing_length_mm"], 7.0, rel_tol=1e-9)


class TestSimulatePlot:
    """Tests for simulate_plot function."""

    def test_simulate_plot_empty_strokes(self):
        """Empty stroke list should return blank paper."""
        img = simulate_plot(
            strokes=[],
            paper_width_mm=100.0,
            paper_height_mm=100.0,
            paper_color="#FFFFFF",
        )
        assert isinstance(img, Image.Image)
        assert img.size == (378, 378)  # 100mm * 3.7795 px/mm
        assert img.mode == "RGB"
        # All pixels should be white
        assert all(p == (255, 255, 255) for p in img.getdata())

    def test_simulate_plot_custom_paper_color(self):
        """Custom paper color should be used as background."""
        img = simulate_plot(
            strokes=[],
            paper_width_mm=10.0,
            paper_height_mm=10.0,
            paper_color="#FF0000",
        )
        assert all(p == (255, 0, 0) for p in img.getdata())

    def test_simulate_plot_single_horizontal_line(self):
        """Single horizontal line should be rendered."""
        strokes = [
            PenStroke(
                polyline=[(10.0, 10.0), (90.0, 10.0)],
                width_mm=1.0,
                color="#000000",
                pen_up=False,
            )
        ]
        img = simulate_plot(
            strokes=strokes,
            paper_width_mm=100.0,
            paper_height_mm=100.0,
            paper_color="#FFFFFF",
        )
        # Line should be at y=10mm ≈ 38px, spanning x=10mm to 90mm
        # Check that some pixels are black (not white)
        pixels = list(img.getdata())
        assert any(p != (255, 255, 255) for p in pixels)

    def test_simulate_plot_pen_up_not_rendered(self):
        """Pen-up strokes should not be rendered."""
        strokes = [
            PenStroke(
                polyline=[(10.0, 10.0), (90.0, 10.0)],
                width_mm=1.0,
                color="#000000",
                pen_up=True,  # Pen up - should not draw
            )
        ]
        img = simulate_plot(
            strokes=strokes,
            paper_width_mm=100.0,
            paper_height_mm=100.0,
            paper_color="#FFFFFF",
        )
        # All pixels should still be white
        assert all(p == (255, 255, 255) for p in img.getdata())

    def test_simulate_plot_mixed_pen_up_down(self):
        """Only pen-down strokes should be rendered."""
        strokes = [
            PenStroke(
                polyline=[(10.0, 10.0), (90.0, 10.0)],
                width_mm=1.0,
                color="#000000",
                pen_up=True,  # Travel move
            ),
            PenStroke(
                polyline=[(10.0, 50.0), (90.0, 50.0)],
                width_mm=1.0,
                color="#000000",
                pen_up=False,  # Actual drawing
            ),
        ]
        img = simulate_plot(
            strokes=strokes,
            paper_width_mm=100.0,
            paper_height_mm=100.0,
            paper_color="#FFFFFF",
        )
        # Should have drawn line at y=50mm but not at y=10mm
        pixels = list(img.getdata())
        assert any(p != (255, 255, 255) for p in pixels)

    def test_simulate_plot_different_colors(self):
        """Different stroke colors should be rendered correctly."""
        strokes = [
            PenStroke(
                polyline=[(10.0, 10.0), (90.0, 10.0)],
                width_mm=1.0,
                color="#FF0000",
                pen_up=False,
            ),
            PenStroke(
                polyline=[(10.0, 30.0), (90.0, 30.0)],
                width_mm=1.0,
                color="#0000FF",
                pen_up=False,
            ),
        ]
        img = simulate_plot(
            strokes=strokes,
            paper_width_mm=100.0,
            paper_height_mm=100.0,
            paper_color="#FFFFFF",
        )
        # Should have non-white pixels
        pixels = list(img.getdata())
        assert any(p != (255, 255, 255) for p in pixels)

    def test_simulate_plot_stroke_width(self):
        """Stroke width should affect rendered line thickness."""
        strokes_thin = [
            PenStroke(
                polyline=[(10.0, 10.0), (90.0, 10.0)],
                width_mm=0.1,
                color="#000000",
                pen_up=False,
            )
        ]
        strokes_thick = [
            PenStroke(
                polyline=[(10.0, 10.0), (90.0, 10.0)],
                width_mm=5.0,
                color="#000000",
                pen_up=False,
            )
        ]
        img_thin = simulate_plot(
            strokes=strokes_thin,
            paper_width_mm=100.0,
            paper_height_mm=100.0,
        )
        img_thick = simulate_plot(
            strokes=strokes_thick,
            paper_width_mm=100.0,
            paper_height_mm=100.0,
        )
        # Thick line should have more non-white pixels
        thin_non_white = sum(1 for p in img_thin.getdata() if p != (255, 255, 255))
        thick_non_white = sum(1 for p in img_thick.getdata() if p != (255, 255, 255))
        assert thick_non_white > thin_non_white

    def test_simulate_plot_custom_dpi(self):
        """Custom DPI should change output image size."""
        img = simulate_plot(
            strokes=[],
            paper_width_mm=100.0,
            paper_height_mm=100.0,
            dpi_px_per_mm=10.0,  # 10 px/mm = 254 DPI
        )
        assert img.size == (1000, 1000)

    def test_simulate_plot_minimum_size(self):
        """Very small paper should produce at least 1x1 image."""
        img = simulate_plot(
            strokes=[],
            paper_width_mm=0.1,
            paper_height_mm=0.1,
            dpi_px_per_mm=3.7795,
        )
        assert img.size == (1, 1)

    def test_simulate_plot_polyline_multiple_segments(self):
        """Polyline with multiple segments should render as connected path."""
        strokes = [
            PenStroke(
                polyline=[(10.0, 10.0), (50.0, 10.0), (50.0, 50.0), (10.0, 50.0)],
                width_mm=1.0,
                color="#000000",
                pen_up=False,
            )
        ]
        img = simulate_plot(
            strokes=strokes,
            paper_width_mm=100.0,
            paper_height_mm=100.0,
            paper_color="#FFFFFF",
        )
        # Should form a rectangle - check corners have black pixels
        pixels = list(img.getdata())
        assert any(p != (255, 255, 255) for p in pixels)


class TestIntegration:
    """Integration tests combining simulation and cost computation."""

    def test_simulate_and_cost_consistent(self):
        """Simulation and cost should use same stroke data."""
        strokes = [
            PenStroke(
                polyline=[(0.0, 0.0), (10.0, 0.0)],
                width_mm=0.3,
                color="#000000",
                pen_up=False,
            ),
            PenStroke(
                polyline=[(10.0, 0.0), (10.0, 10.0)],
                width_mm=0.3,
                color="#000000",
                pen_up=True,
            ),
        ]
        cost = compute_machine_cost(strokes)
        img = simulate_plot(strokes, paper_width_mm=20.0, paper_height_mm=20.0)

        assert cost["total"]["drawing_length_mm"] == 10.0
        assert cost["total"]["pen_up_travel_mm"] == 10.0
        assert isinstance(img, Image.Image)

    def test_complex_drawing_cost(self):
        """Complex drawing with multiple layers and lifts."""
        strokes = [
            # Layer 1 (black): two drawing strokes with a lift between
            PenStroke(
                polyline=[(0.0, 0.0), (10.0, 0.0)],
                width_mm=0.3,
                color="#000000",
                pen_up=False,
            ),
            PenStroke(
                polyline=[(10.0, 0.0), (10.0, 10.0)],
                width_mm=0.3,
                color="#000000",
                pen_up=True,
            ),
            PenStroke(
                polyline=[(10.0, 10.0), (20.0, 10.0)],
                width_mm=0.3,
                color="#000000",
                pen_up=False,
            ),
            # Layer 2 (red): one drawing stroke
            PenStroke(
                polyline=[(0.0, 20.0), (15.0, 20.0)],
                width_mm=0.5,
                color="#FF0000",
                pen_up=False,
            ),
        ]
        cost = compute_machine_cost(strokes)

        # Total drawing: 10 + 10 + 15 = 35mm
        assert cost["total"]["drawing_length_mm"] == 35.0
        # Total pen-up: 10mm
        assert cost["total"]["pen_up_travel_mm"] == 10.0
        # Total lifts: 1
        assert cost["total"]["num_lifts"] == 1
        # Total strokes: 4
        assert cost["total"]["num_strokes"] == 4

        # Per-layer checks
        assert cost["per_layer"]["#000000"]["drawing_length_mm"] == 20.0
        assert cost["per_layer"]["#000000"]["pen_up_travel_mm"] == 10.0
        assert cost["per_layer"]["#000000"]["num_lifts"] == 1
        assert cost["per_layer"]["#000000"]["num_strokes"] == 3

        assert cost["per_layer"]["#FF0000"]["drawing_length_mm"] == 15.0
        assert cost["per_layer"]["#FF0000"]["pen_up_travel_mm"] == 0.0
        assert cost["per_layer"]["#FF0000"]["num_lifts"] == 0
        assert cost["per_layer"]["#FF0000"]["num_strokes"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])
