"""Assert the Sketch Lines gate thresholds recorded in docs/TESTING.md.

The reference images and harness belong to part 1 (LUC-52); this module only
turns the yardstick into assertions and changes no measurement. The SSIM
floors below are the LUC-47 re-derivation: ``max(blank, random) + 0.05``,
never below ``measured - 0.05``, with ``random + 0.05`` where the drawing
cannot beat the trivial baselines. The gradient floor was re-derived after
LUC-89 changed the shipped default. The withdrawn part 1 floors (0.75, 0.80,
0.88, 0.70, 0.75) measured a raster stipple, not a pen plot, and remain in
docs/TESTING.md as the record. The five non-SSIM floors are part 1's and are
unchanged.
"""

from __future__ import annotations

from collections.abc import Callable

import click
import pytest
from PIL import Image
from sketch_lines_gate import (
    DARK_TILE_INK_MAX,
    DARK_TILE_INK_MIN,
    PX_PER_MM,
    RANK_MIN,
    REFERENCE_DIR,
    REFERENCE_NAMES,
    GateReport,
    all_finite,
    ink_mask,
    make_solid_plot,
    placement_crop,
    print_measurement_table,
    tile_readability,
)

SSIM_THRESHOLDS: dict[str, float] = {
    "circle.png": 0.53,
    "gradient.png": 0.47,
    "sphere.png": 0.79,
    "face.jpg": 0.57,
    "photo.jpg": 0.18,
}
COVERAGE_WIDTH_MIN = 0.60
COVERAGE_HEIGHT_MIN = 0.60
BBOX_AREA_MIN = 0.40
INK_CELL_MIN = 0.0003
TONE_RATIO_MIN = 2.0
READABILITY_REFERENCES = ("face.jpg", "photo.jpg")
WHITE_INK_MAX = 0.01
MEASURED_MAIN_SSIM = {"face.jpg": 0.606598, "photo.jpg": 0.533787}
SSIM_BASELINE_TOLERANCE = 1e-3


def test_gate_harness_reports_every_reference_image(
    gate_report_factory: Callable[[str], GateReport],
) -> None:
    """The harness measures every reference image once, in the published order."""
    reports = [gate_report_factory(name) for name in REFERENCE_NAMES]
    assert [report.reference for report in reports] == list(REFERENCE_NAMES)
    print_measurement_table(reports)


@pytest.mark.parametrize("reference", REFERENCE_NAMES)
def test_gate_reference_meets_published_thresholds(
    gate_report_factory: Callable[[str], GateReport], reference: str
) -> None:
    """One reference image is finite and clears every likeness floor."""
    report = gate_report_factory(reference)
    assert report.reference == reference
    assert report.stroke_count > 0
    assert report.placement.width > 0
    assert report.placement.height > 0
    assert all_finite(report.algorithm)
    assert all_finite(report.blank)
    assert all_finite(report.random)
    assert all_finite(report.ideal)

    measured = report.algorithm
    ssim_floor = SSIM_THRESHOLDS[reference]
    checks = (
        ("SSIM", measured.ssim, ssim_floor),
        ("covered width", measured.coverage_width, COVERAGE_WIDTH_MIN),
        ("covered height", measured.coverage_height, COVERAGE_HEIGHT_MIN),
        ("bbox area", measured.coverage_area, BBOX_AREA_MIN),
        ("ink per 4x4 cell", measured.ink_spread_min, INK_CELL_MIN),
        ("tone ratio", measured.tone_ratio, TONE_RATIO_MIN),
    )
    failures = [
        f"{report.reference}: {name} {value:.4f} < {floor:.4f}"
        for name, value, floor in checks
        if value < floor
    ]
    assert not failures, "Sketch Lines likeness gate not met:\n" + "\n".join(failures)


@pytest.mark.parametrize("reference", READABILITY_REFERENCES)
def test_readability_ranks_ink_and_caps_textured_dark_tiles(
    gate_report_factory: Callable[[str], GateReport], reference: str
) -> None:
    """A photo's ink follows its darkness and stays short of a solid mass."""
    report = gate_report_factory(reference)
    measured = report.algorithm
    assert measured.rank_correlation >= RANK_MIN
    assert measured.dark_textured_tiles >= 8
    assert DARK_TILE_INK_MIN <= measured.dark_textured_ink_max <= DARK_TILE_INK_MAX
    assert report.blank.rank_correlation < RANK_MIN
    assert report.random.rank_correlation < RANK_MIN


@pytest.mark.parametrize("reference", READABILITY_REFERENCES)
def test_masked_likeness_is_not_below_the_measured_main_baseline(
    gate_report_factory: Callable[[str], GateReport], reference: str
) -> None:
    """The white-pen rule must not make either photo less recognizable.

    The floors are the values measured with this same harness at seed 42 and
    ``white_threshold=1.0``, which reproduces ``main``. The tolerance covers
    small cross-platform differences in the SSIM computation.
    """
    report = gate_report_factory(reference)
    floor = MEASURED_MAIN_SSIM[reference]
    click.echo(f"{reference}: SSIM {report.algorithm.ssim:.6f}, main baseline {floor:.6f}")
    assert report.algorithm.ssim >= floor - SSIM_BASELINE_TOLERANCE


def test_face_ink_on_near_white_source_stays_below_one_percent(
    gate_report_factory: Callable[[str], GateReport],
) -> None:
    """A simulated stroke must not spend 1% of its length on near-white source."""
    report = gate_report_factory("face.jpg")
    photo = gate_report_factory("photo.jpg")
    click.echo(
        f"face.jpg: ink on source luminance > 0.92 = {report.white_ink_share:.5f}; "
        f"photo.jpg = {photo.white_ink_share:.5f}"
    )
    assert report.white_ink_share < WHITE_INK_MAX


def test_solid_black_textured_region_fails_the_readability_cap(
    gate_report_factory: Callable[[str], GateReport],
) -> None:
    """Filling the placement with black fails both the rank and the ink cap."""
    report = gate_report_factory("photo.jpg")
    placement = (
        report.placement.x,
        report.placement.y,
        report.placement.width,
        report.placement.height,
    )
    plot_size = (round(report.paper_size[0] * PX_PER_MM), round(report.paper_size[1] * PX_PER_MM))
    solid = make_solid_plot(plot_size, placement)
    crop = placement_crop(plot_size, placement)
    with Image.open(REFERENCE_DIR / "photo.jpg") as opened:
        original = opened.convert("RGB").resize(
            (crop[2] - crop[0], crop[3] - crop[1]), Image.Resampling.LANCZOS
        )
    rank, ink_max, tiles = tile_readability(ink_mask(solid, crop), original)
    assert tiles >= 1
    assert rank < RANK_MIN
    assert ink_max > DARK_TILE_INK_MAX


def test_flat_black_shape_keeps_its_dark_coverage(
    gate_report_factory: Callable[[str], GateReport],
) -> None:
    """The cap applies to textured tiles, not to a genuinely flat black disc."""
    report = gate_report_factory("circle.png")
    assert report.algorithm.rank_correlation >= RANK_MIN
    assert report.algorithm.dark_textured_ink_max <= DARK_TILE_INK_MAX
