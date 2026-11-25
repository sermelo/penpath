"""Assert the Sketch Lines gate thresholds recorded in docs/TESTING.md.

The reference images and harness belong to part 1 (LUC-52); this module only
turns the yardstick into assertions and changes no measurement. The SSIM
floors below are the LUC-47 re-derivation: ``max(blank, random) + 0.05``,
never below ``measured - 0.05``, with ``random + 0.05`` where the drawing
cannot beat the trivial baselines. The withdrawn part 1 floors (0.75, 0.80,
0.88, 0.70, 0.75) measured a raster stipple, not a pen plot, and remain in
docs/TESTING.md as the record. The five non-SSIM floors are part 1's and are
unchanged.
"""

from __future__ import annotations

import pytest
from sketch_lines_gate import (
    REFERENCE_NAMES,
    GateReport,
    all_finite,
    measure_all,
    print_measurement_table,
)

SSIM_THRESHOLDS: dict[str, float] = {
    "circle.png": 0.53,
    "gradient.png": 0.46,
    "sphere.png": 0.79,
    "face.jpg": 0.57,
    "photo.jpg": 0.18,
}
COVERAGE_WIDTH_MIN = 0.60
COVERAGE_HEIGHT_MIN = 0.60
BBOX_AREA_MIN = 0.40
INK_CELL_MIN = 0.0003
TONE_RATIO_MIN = 2.0


@pytest.fixture(scope="module")
def gate_reports(tmp_path_factory: pytest.TempPathFactory) -> list[GateReport]:
    """Run the real pipeline once for every reference image."""
    reports = measure_all(tmp_path_factory.mktemp("sketch-lines-gate"))
    print_measurement_table(reports)
    return reports


def test_gate_harness_reports_finite_measurements(gate_reports: list[GateReport]) -> None:
    """The real pipeline runs for every image and all reported numbers are finite."""
    assert [report.reference for report in gate_reports] == list(REFERENCE_NAMES)
    for report in gate_reports:
        assert report.stroke_count > 0
        assert report.placement.width > 0
        assert report.placement.height > 0
        assert all_finite(report.algorithm)
        assert all_finite(report.blank)
        assert all_finite(report.random)
        assert all_finite(report.ideal)


def test_gate_meets_published_thresholds(gate_reports: list[GateReport]) -> None:
    """Every reference image meets the likeness gate from docs/TESTING.md."""
    failures: list[str] = []
    for report in gate_reports:
        measured = report.algorithm
        ssim_floor = SSIM_THRESHOLDS[report.reference]
        checks = (
            ("SSIM", measured.ssim, ssim_floor),
            ("covered width", measured.coverage_width, COVERAGE_WIDTH_MIN),
            ("covered height", measured.coverage_height, COVERAGE_HEIGHT_MIN),
            ("bbox area", measured.coverage_area, BBOX_AREA_MIN),
            ("ink per 4x4 cell", measured.ink_spread_min, INK_CELL_MIN),
            ("tone ratio", measured.tone_ratio, TONE_RATIO_MIN),
        )
        for name, value, floor in checks:
            if value < floor:
                failures.append(f"{report.reference}: {name} {value:.4f} < {floor:.4f}")
    assert not failures, "Sketch Lines likeness gate not met:\n" + "\n".join(failures)
