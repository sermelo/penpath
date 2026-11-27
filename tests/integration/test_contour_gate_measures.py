"""Unit tests for the pure measurement helpers of the Contour gate."""

from __future__ import annotations

import numpy as np
from contour_gate import (
    TINY_SEGMENT_MM,
    coverage_fractions,
    edge_alignment,
    edge_mask,
    geometry_problems,
    plot_cost,
    points_to_pixels,
)
from PIL import Image

from penpath.core.simulation import PenStroke

_PLACEMENT = (10.0, 20.0, 100.0, 50.0)


def _stroke(points: list[tuple[float, float]]) -> PenStroke:
    return PenStroke(polyline=points, width_mm=0.3, color="#000000")


def test_edge_alignment_rejects_a_blank_page() -> None:
    """No points means no edge support, so an empty drawing scores zero."""
    mask = np.ones((8, 8), dtype=bool)
    assert edge_alignment([], _PLACEMENT, (8, 8), mask) == (0.0, 0, 0)


def test_edge_alignment_scores_points_on_a_source_edge() -> None:
    """The split image's edge matches its contour; the far side does not."""
    image = Image.new("RGB", (8, 8), "white")
    for row in range(8):
        for column in range(4):
            image.putpixel((column, row), (0, 0, 0))
    mask = edge_mask(image)

    on_edge = [(x, 45.0) for x in (59.0, 60.0, 61.0)]
    assert edge_alignment(on_edge, _PLACEMENT, (8, 8), mask) == (1.0, 2, 2)
    assert edge_alignment([(11.0, 45.0)], _PLACEMENT, (8, 8), mask) == (0.0, 0, 1)


def test_points_to_pixels_maps_the_placement_and_discards_outliers() -> None:
    """A point's millimetre position maps into the working image's pixels."""
    pixels = points_to_pixels(
        [(10.0, 20.0), (110.0, 70.0), (200.0, 20.0)],
        _PLACEMENT,
        (101, 51),
    )
    assert pixels == {(0, 0), (50, 100)}


def test_coverage_fractions_measure_the_stroke_extent() -> None:
    """A line spans the width but no height; an empty drawing spans nothing."""
    assert coverage_fractions([(10.0, 45.0), (110.0, 45.0)], _PLACEMENT) == (1.0, 0.0, 0.0)
    assert coverage_fractions([], _PLACEMENT) == (0.0, 0.0, 0.0)


def test_plot_cost_counts_segments_length_and_tiny_share() -> None:
    """Cost is measured per segment, including the count below 0.5 mm."""
    strokes = [
        _stroke([(0.0, 0.0), (3.0, 4.0), (3.0, 5.0)]),
        _stroke([(10.0, 10.0), (10.0 + TINY_SEGMENT_MM / 2, 10.0)]),
    ]
    cost = plot_cost(strokes)
    assert cost.strokes == 2
    assert cost.points == 5
    assert cost.length_mm == 5.0 + 1.0 + TINY_SEGMENT_MM / 2
    assert cost.tiny_segments == 1
    assert cost.tiny_fraction == 1 / 3


def test_geometry_problems_flags_off_page_and_zero_length_strokes() -> None:
    """Invalid geometry is named instead of silently counted as ink."""
    assert geometry_problems([_stroke([(0.0, 0.0), (1.0, 1.0)])], (10.0, 10.0)) == ()
    problems = geometry_problems(
        [_stroke([(0.0, 0.0), (11.0, 0.0)]), _stroke([(1.0, 1.0), (1.0, 1.0)])],
        (10.0, 10.0),
    )
    assert any("outside the page" in problem for problem in problems)
    assert any("zero-length" in problem for problem in problems)
