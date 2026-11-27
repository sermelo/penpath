"""Shared fixtures for integration tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from contour_gate import ContourReport, measure
from sketch_lines_gate import REFERENCE_DIR, GateReport, measure_reference
from sketch_squares_gate import SquaresReport
from sketch_squares_gate import measure as measure_squares


@pytest.fixture(scope="session")
def gate_report_factory(
    tmp_path_factory: pytest.TempPathFactory,
) -> Callable[[str], GateReport]:
    """Convert and measure each reference image at most once per test session.

    Tests that only measure a finished SVG share the conversion instead of
    running ``penpath convert`` again. Tests that check the conversion itself
    must invoke the CLI directly so they still see a fresh conversion.
    """
    work_dir = tmp_path_factory.mktemp("sketch-lines-gate")
    cache: dict[str, GateReport] = {}

    def report_for(reference: str) -> GateReport:
        if reference not in cache:
            cache[reference] = measure_reference(
                REFERENCE_DIR / reference, work_dir / Path(reference).stem
            )
        return cache[reference]

    return report_for


@pytest.fixture(scope="session")
def contour_report_factory(
    tmp_path_factory: pytest.TempPathFactory,
) -> Callable[[str, str], ContourReport]:
    """Convert and measure each reference/preset pair at most once per session."""
    work_dir = tmp_path_factory.mktemp("contour-gate")
    cache: dict[tuple[str, str], ContourReport] = {}

    def report_for(reference: str, preset: str) -> ContourReport:
        key = (reference, preset)
        if key not in cache:
            cache[key] = measure(REFERENCE_DIR / reference, preset, work_dir / reference)
        return cache[key]

    return report_for


@pytest.fixture(scope="session")
def squares_report_factory(
    tmp_path_factory: pytest.TempPathFactory,
) -> Callable[[str, str], SquaresReport]:
    """Convert and measure each reference/preset pair at most once per session."""
    work_dir = tmp_path_factory.mktemp("sketch-squares-gate")
    cache: dict[tuple[str, str], SquaresReport] = {}

    def report_for(reference: str, preset: str) -> SquaresReport:
        key = (reference, preset)
        if key not in cache:
            cache[key] = measure_squares(REFERENCE_DIR / reference, preset, work_dir / reference)
        return cache[key]

    return report_for
