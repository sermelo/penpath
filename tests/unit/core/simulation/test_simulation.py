"""Unit tests for plot simulation and machine cost computation."""

from __future__ import annotations

import math

import pytest
from PIL import Image

from penpath.core.simulation import (
    MAX_RENDER_MEGAPIXELS,
    PenStroke,
    check_render_budget,
    compute_layer_coverage,
    compute_machine_cost,
    insert_pen_up_moves,
    render_size_px,
    simulate_plot,
)


def _stroke(color: str, y_mm: float, width_mm: float = 1.0, pen_up: bool = False) -> PenStroke:
    """A horizontal 10 mm stroke at the given height and pen width."""
    return PenStroke(
        polyline=[(0.0, y_mm), (10.0, y_mm)],
        width_mm=width_mm,
        color=color,
        pen_up=pen_up,
    )


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
        """A pen-up move counts as a lift but not as a drawn stroke."""
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
        assert result["total"]["num_strokes"] == 0

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
        assert result["total"]["num_strokes"] == 2

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


class TestRenderBudget:
    """Tests for the shared raster size and the pure pixel budget check."""

    def test_render_size_px_a5_at_100_px_per_inch(self):
        """A5 at 100/25.4 px/mm rounds to 583x827 pixels."""
        assert render_size_px(148.0, 210.0, 100 / 25.4) == (583, 827)

    def test_render_size_px_rounds_each_dimension_and_clamps_to_one(self):
        """Each dimension rounds independently, with a one-pixel floor."""
        assert render_size_px(10.6, 0.01, 1.0) == (11, 1)

    def test_check_render_budget_accepts_exact_limit(self):
        """A raster of exactly 40 MP is allowed."""
        assert MAX_RENDER_MEGAPIXELS == 40.0
        check_render_budget(1000, 40000)

    def test_check_render_budget_rejects_one_pixel_over_limit(self):
        """A single pixel over the default budget is refused."""
        with pytest.raises(ValueError, match="above the 40 MP limit"):
            check_render_budget(1001, 40000)

    def test_check_render_budget_custom_limit(self):
        """A caller may set its own budget."""
        check_render_budget(100, 100, max_megapixels=0.01)
        with pytest.raises(ValueError, match=r"above the 0\.5 MP limit"):
            check_render_budget(1000, 1000, max_megapixels=0.5)

    def test_check_render_budget_over_limit_message_names_size_and_megapixels(self):
        """The error gives the planned size, megapixels and limit."""
        with pytest.raises(
            ValueError,
            match=r"renders 7400x10500 px \(77\.7 MP\), above the 40 MP limit",
        ):
            check_render_budget(7400, 10500)


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

    def test_simulate_plot_size_matches_shared_render_size_px(self):
        """The simulator uses the same rounding as the shared size helper."""
        expected = render_size_px(100.0, 60.0, 3.3)
        img = simulate_plot([], 100.0, 60.0, dpi_px_per_mm=3.3)
        assert img.size == expected

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

    def test_simulate_plot_travel_color_none_leaves_pen_up_invisible(self):
        """The default and an explicit zero travel colour ignore pen-up strokes."""
        strokes = [
            _stroke("#000000", 2.0),
            _stroke("#000000", 8.0, pen_up=True),
        ]
        default = simulate_plot(strokes, 10.0, 10.0, dpi_px_per_mm=10.0)
        explicit = simulate_plot(strokes, 10.0, 10.0, dpi_px_per_mm=10.0, travel_width_mm=0.5)

        assert default.tobytes() == explicit.tobytes()
        assert default.getpixel((50, 80)) == (255, 255, 255)

    def test_simulate_plot_travel_style_draws_under_ink(self):
        """Travel is light and thin, and every ink pixel stays identical."""
        travel = PenStroke(
            polyline=[(1.0, 1.0), (9.0, 9.0)],
            width_mm=0.4,
            color="#000000",
            pen_up=True,
        )
        ink = PenStroke(
            polyline=[(1.0, 9.0), (9.0, 1.0)],
            width_mm=1.0,
            color="#000000",
        )
        ink_only = simulate_plot([ink], 10.0, 10.0, dpi_px_per_mm=10.0)
        with_travel = simulate_plot(
            [travel, ink],
            10.0,
            10.0,
            dpi_px_per_mm=10.0,
            travel_color="#C8C8C8",
            travel_width_mm=0.1,
        )

        ink_pixels = [
            (x, y)
            for y in range(100)
            for x in range(100)
            if ink_only.getpixel((x, y)) != (255, 255, 255)
        ]
        assert ink_pixels
        assert all(with_travel.getpixel(p) == ink_only.getpixel(p) for p in ink_pixels)
        assert with_travel.getpixel((20, 20)) == (200, 200, 200)
        assert ink_only.getpixel((20, 20)) == (255, 255, 255)

    def test_simulate_plot_travel_width_controls_line_thickness(self):
        """A wider travel style inks more pixels than the thin default."""
        travel = PenStroke(
            polyline=[(1.0, 1.0), (9.0, 1.0)],
            width_mm=0.4,
            color="#000000",
            pen_up=True,
        )
        thin = simulate_plot([travel], 10.0, 10.0, dpi_px_per_mm=10.0, travel_color="#C8C8C8")
        thick = simulate_plot(
            [travel], 10.0, 10.0, dpi_px_per_mm=10.0, travel_color="#C8C8C8", travel_width_mm=0.5
        )

        thin_ink = sum(p == (200, 200, 200) for p in thin.getdata())
        thick_ink = sum(p == (200, 200, 200) for p in thick.getdata())
        assert 0 < thin_ink < thick_ink


class TestInsertPenUpMoves:
    """The shared travel helper follows the SVG gap rule for both input formats."""

    def test_insert_pen_up_moves_uses_following_stroke_style(self):
        first = PenStroke([(0.0, 0.0), (10.0, 0.0)], 0.3, "#000000")
        second = PenStroke([(20.0, 5.0), (30.0, 5.0)], 0.4, "#FF0000")

        result = insert_pen_up_moves([first, second])

        assert [stroke.pen_up for stroke in result] == [False, True, False]
        assert result[1].polyline == [(10.0, 0.0), (20.0, 5.0)]
        assert result[1].width_mm == 0.4
        assert result[1].color == "#FF0000"

    def test_insert_pen_up_moves_skips_contiguous_and_tiny_gaps(self):
        first = PenStroke([(0.0, 0.0), (10.0, 0.0)], 0.3, "#000000")
        touching = PenStroke([(10.0, 0.0), (20.0, 0.0)], 0.3, "#000000")
        tiny_gap = PenStroke([(20.005, 0.0), (30.0, 0.0)], 0.3, "#000000")
        real_gap = PenStroke([(30.02, 0.0), (40.0, 0.0)], 0.3, "#000000")

        result = insert_pen_up_moves([first, touching, tiny_gap, real_gap])

        assert [stroke.pen_up for stroke in result] == [False, False, False, True, False]
        assert result[3].polyline == [(30.0, 0.0), (30.02, 0.0)]


class TestComputeLayerCoverage:
    """Tests for per-layer ink coverage."""

    def test_full_page_stroke_is_near_100_percent(self):
        """Horizontal lines spaced by the pen width fill the whole page."""
        strokes = [_stroke("#000000", y + 0.5, width_mm=1.1) for y in range(10)]
        result = compute_layer_coverage(strokes, 10, 10, dpi_px_per_mm=10)
        assert result.per_layer["#000000"] == pytest.approx(100.0, abs=0.5)
        assert result.total == pytest.approx(100.0, abs=0.5)

    def test_short_line_is_near_zero(self):
        """A short line on a large page inks almost none of it."""
        stroke = PenStroke(polyline=[(10.0, 10.0), (11.0, 10.0)], width_mm=0.3, color="#000000")
        result = compute_layer_coverage([stroke], 100, 100, dpi_px_per_mm=10)
        assert result.per_layer["#000000"] < 0.1
        assert result.total < 0.1

    def test_pen_width_affects_coverage(self):
        """A thicker pen inks more of the page for the same line."""
        thin = compute_layer_coverage([_stroke("#000000", 5.0, 0.5)], 10, 10, dpi_px_per_mm=10)
        thick = compute_layer_coverage([_stroke("#000000", 5.0, 3.0)], 10, 10, dpi_px_per_mm=10)
        assert thick.total > thin.total

    def test_two_layers_report_their_own_values(self):
        """Each colour gets its own percentage, keyed by stroke colour."""
        strokes = [
            _stroke("#000000", 5.0, width_mm=2.0),
            PenStroke(polyline=[(0.0, 9.0), (2.0, 9.0)], width_mm=1.0, color="#FF0000"),
        ]
        result = compute_layer_coverage(strokes, 10, 10, dpi_px_per_mm=10)
        assert set(result.per_layer) == {"#000000", "#FF0000"}
        assert result.per_layer["#000000"] > result.per_layer["#FF0000"]

    def test_values_are_bounded(self):
        """Overlapping strokes and off-page coordinates stay within 0-100."""
        strokes = [
            _stroke("#000000", 5.0, width_mm=50.0),
            _stroke("#FF0000", 5.0, width_mm=50.0),
            PenStroke(polyline=[(-100.0, 5.0), (200.0, 5.0)], width_mm=20.0, color="#00FF00"),
        ]
        result = compute_layer_coverage(strokes, 10, 10, dpi_px_per_mm=10)
        assert result.per_layer
        assert all(0.0 <= value <= 100.0 for value in result.per_layer.values())
        assert 0.0 <= result.total <= 100.0

    def test_empty_page_does_not_divide_by_zero(self):
        """No strokes on a zero-sized page reports zero without an error."""
        result = compute_layer_coverage([], 0, 0, dpi_px_per_mm=10)
        assert result.per_layer == {}
        assert result.total == 0.0

    def test_pen_up_strokes_do_not_add_ink(self):
        """Travel moves are not ink."""
        result = compute_layer_coverage([_stroke("#000000", 5.0, 1.1, pen_up=True)], 10, 10, 10)
        assert result.per_layer == {}
        assert result.total == 0.0

    def test_total_is_union_not_sum_of_overlapping_layers(self):
        """Two layers over the same pixels report their own values but one total."""
        strokes = [_stroke("#000000", 5.0, 1.1), _stroke("#FF0000", 5.0, 1.1)]
        result = compute_layer_coverage(strokes, 10, 10, dpi_px_per_mm=10)
        assert result.per_layer["#000000"] > 10.0
        assert result.per_layer["#FF0000"] > 10.0
        assert result.total == pytest.approx(max(result.per_layer.values()))


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
        # Total drawn strokes: 3 (the pen-up move is not a stroke)
        assert cost["total"]["num_strokes"] == 3

        # Per-layer checks
        assert cost["per_layer"]["#000000"]["drawing_length_mm"] == 20.0
        assert cost["per_layer"]["#000000"]["pen_up_travel_mm"] == 10.0
        assert cost["per_layer"]["#000000"]["num_lifts"] == 1
        assert cost["per_layer"]["#000000"]["num_strokes"] == 2

        assert cost["per_layer"]["#FF0000"]["drawing_length_mm"] == 15.0
        assert cost["per_layer"]["#FF0000"]["pen_up_travel_mm"] == 0.0
        assert cost["per_layer"]["#FF0000"]["num_lifts"] == 0
        assert cost["per_layer"]["#FF0000"]["num_strokes"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])
