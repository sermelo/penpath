"""Print the Sketch Lines gate measurement table for the reference image set.

The thresholds are recorded in docs/TESTING.md; this test deliberately checks
only that the harness runs and produces finite numbers.
"""

from __future__ import annotations

from pathlib import Path

from sketch_lines_gate import (
    REFERENCE_NAMES,
    all_finite,
    measure_all,
    print_measurement_table,
)


def test_gate_harness_reports_finite_measurements(tmp_path: Path) -> None:
    """The real pipeline runs for every image and all reported numbers are finite."""
    reports = measure_all(tmp_path)
    print_measurement_table(reports)

    assert [report.reference for report in reports] == list(REFERENCE_NAMES)
    for report in reports:
        assert report.stroke_count > 0
        assert report.placement.width > 0
        assert report.placement.height > 0
        assert all_finite(report.algorithm)
        assert all_finite(report.blank)
        assert all_finite(report.random)
        assert all_finite(report.ideal)
