"""Unit tests for the pure measurement helpers of the likeness gates."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
from multi_pen_gate import (
    BLANK_OWNERSHIP,
    IDEAL_OWNERSHIP,
    MultiPenGateReport,
    Ownership,
    OwnershipReport,
    PenLayerReport,
    ownership_failures,
    ownership_metrics,
    recolor_black,
    resize_mask,
    whole_plot_failures,
)
from PIL import Image
from sketch_lines_gate import (
    INK_CUTOFF,
    PX_PER_MM,
    PlotMeasures,
    coverage_fractions,
    ink_mask,
    ink_spread,
    make_ideal_plot,
    placement_crop,
    tone_metrics,
)

from penpath.core.simulation import PenStroke


def test_placement_crop_rounds_and_clamps_like_likeness() -> None:
    """The crop used for ink measures matches compute_likeness's placement crop."""
    assert placement_crop((400, 400), (10, 20, 50, 40), px_per_mm=1.0) == (10, 20, 60, 60)
    assert placement_crop((30, 30), (20, 20, 50, 50), px_per_mm=1.0) == (20, 20, 30, 30)


def test_coverage_fractions_for_full_quarter_and_empty() -> None:
    """Coverage reports the clipped bounding box of the stroke points."""
    placement = (0.0, 0.0, 100.0, 50.0)
    assert coverage_fractions([(0, 0), (100, 50)], placement) == (1.0, 1.0, 1.0)
    assert coverage_fractions([(0, 0), (50, 25)], placement) == (0.5, 0.5, 0.25)
    assert coverage_fractions([], placement) == (0.0, 0.0, 0.0)
    assert coverage_fractions([(-10, -10), (200, 100)], placement) == (1.0, 1.0, 1.0)


def test_ink_spread_detects_a_single_corner() -> None:
    """All ink in one cell gives min 0 and max 1; uniform ink gives equal shares."""
    corner = np.zeros((16, 16), dtype=bool)
    corner[:4, :4] = True
    assert ink_spread(corner) == (0.0, 1.0)

    uniform = np.ones((16, 16), dtype=bool)
    minimum, maximum = ink_spread(uniform)
    assert minimum == maximum == 1 / 16


def test_ink_mask_uses_the_pen_cutoff() -> None:
    """Only pixels darker than halfway between pen and paper count as ink."""
    plot = Image.new("RGB", (4, 4), "white")
    plot.putpixel((0, 0), (INK_CUTOFF - 1, INK_CUTOFF - 1, INK_CUTOFF - 1))
    plot.putpixel((1, 1), (INK_CUTOFF + 1, INK_CUTOFF + 1, INK_CUTOFF + 1))
    mask = ink_mask(plot, (0, 0, 4, 4))
    assert bool(mask[0, 0])
    assert not bool(mask[1, 1])


def test_tone_metrics_favours_dark_pixels_and_stays_finite() -> None:
    """Ink in the dark quarter raises the ratio; a blank page gives 1.0."""
    original = Image.new("L", (16, 16), 255)
    for column in range(4):
        for row in range(16):
            original.putpixel((column, row), 0)
    mask = np.zeros((16, 16), dtype=bool)
    mask[:, :4] = True

    dark, light, ratio = tone_metrics(mask, original)
    assert dark == 1.0
    assert light == 0.0
    assert ratio > 1.0

    blank = np.zeros((16, 16), dtype=bool)
    assert tone_metrics(blank, original)[2] == 1.0


def test_ideal_plot_uses_only_pen_ink_levels() -> None:
    """The ideal drawing contains pure pen black and paper white pixels."""
    original = Image.new("L", (32, 32))
    for column in range(16):
        for row in range(32):
            original.putpixel((column, row), 0)
    side = 100
    placement = (0.0, 0.0, side / PX_PER_MM, side / PX_PER_MM)
    ideal = make_ideal_plot(original, (side, side), placement)

    assert ideal.size == (side, side)
    assert set(ideal.convert("L").getdata()) <= {0, 255}


def test_ownership_metrics_cover_region_ink_and_detect_outside_ink() -> None:
    """Recall uses the region's ink pixels; outside counts plotted ink elsewhere."""
    region = np.array([[True, True, True, False], [False, False, False, False]])
    region_ink = np.array([[True, True, False, False], [False, False, False, False]])
    ink = region_ink.copy()
    assert ownership_metrics(ink, region, region_ink) == Ownership(recall=1.0, outside=0.0)

    ink_with_outside = np.array([[True, True, False, True], [False, False, False, False]])
    assert ownership_metrics(ink_with_outside, region, region_ink) == Ownership(
        recall=1.0, outside=1.0 / 3.0
    )
    assert ownership_metrics(np.zeros_like(region), region, region_ink) == Ownership(
        recall=0.0, outside=1.0
    )


def test_resize_mask_preserves_binary_classes() -> None:
    """Resampling a mask for the plot crop introduces no intermediate values."""
    mask = np.array([[True, False], [False, True]])
    resized = resize_mask(mask, (4, 4))
    assert set(np.unique(resized)) <= {False, True}
    assert bool(resized[0, 0])
    assert not bool(resized[0, 3])
    assert bool(resized[3, 3])


def test_recolor_black_keeps_geometry_and_pen_up_state() -> None:
    """Recolouring a stroke changes only its colour."""
    stroke = PenStroke([(1.0, 2.0), (3.0, 4.0)], 0.5, "#00FF00", pen_up=True)
    assert recolor_black([stroke]) == [
        PenStroke([(1.0, 2.0), (3.0, 4.0)], 0.5, "#000000", pen_up=True)
    ]


def _measures(**changes: float) -> PlotMeasures:
    values = {
        "ssim": 0.2,
        "coverage_width": 0.7,
        "coverage_height": 0.7,
        "coverage_area": 0.5,
        "ink_spread_min": 0.0004,
        "ink_spread_max": 0.1,
        "tone_dark_density": 0.1,
        "tone_light_density": 0.01,
        "tone_ratio": 1.0,
    }
    values.update(changes)
    return PlotMeasures(**values)


def _report(*ownership: Ownership) -> MultiPenGateReport:
    layers = [
        PenLayerReport(
            pen_name=f"pen-{index}",
            color="#000000",
            stroke_count=1,
            region_pixels=100,
            algorithm=_measures(),
            blank=_measures(),
            random=_measures(),
            ideal=_measures(),
            ownership=OwnershipReport(
                algorithm=measure,
                blank=BLANK_OWNERSHIP,
                random=BLANK_OWNERSHIP,
                ideal=IDEAL_OWNERSHIP,
            ),
        )
        for index, measure in enumerate(ownership)
    ]
    return MultiPenGateReport(
        reference="photo.jpg",
        palette="stabilo_88",
        placement=(0.0, 0.0, 10.0, 10.0),
        paper_size=(210.0, 297.0),
        whole_plot=_measures(),
        whole_plot_strokes=1,
        layers=layers,
    )


def test_whole_plot_failures_exclude_tone() -> None:
    """The whole-plot gate checks five structural floors, never tone."""
    report = _report()
    assert whole_plot_failures(report) == []
    report = replace(report, whole_plot=_measures(ssim=0.1))
    assert whole_plot_failures(report) == [("SSIM", 0.1, 0.18)]


def test_ownership_failures_restrict_recall_and_outside() -> None:
    """A recall miss and an outside-ink miss are reported with their floors."""
    report = _report(
        Ownership(recall=0.2, outside=0.4),
        Ownership(recall=0.9, outside=0.6),
    )
    assert ownership_failures(report) == [
        ("pen-0", "recall", 0.2, 0.45),
        ("pen-1", "outside", 0.6, 0.50),
    ]
