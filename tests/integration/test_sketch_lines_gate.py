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

import pytest
from sketch_lines_gate import (
    REFERENCE_NAMES,
    GateReport,
    all_finite,
    print_measurement_table,
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
