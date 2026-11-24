"""Assert the Sketch Lines gate thresholds published in docs/TESTING.md.

The reference images, harness and thresholds belong to part 1 (LUC-52). This
module only turns the published yardstick into assertions; it changes no
measurement and no threshold.
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
    "circle.png": 0.75,
    "gradient.png": 0.80,
    "sphere.png": 0.88,
    "face.jpg": 0.70,
    "photo.jpg": 0.75,
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
    """Every reference image meets the part 1 likeness gate from docs/TESTING.md."""
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
