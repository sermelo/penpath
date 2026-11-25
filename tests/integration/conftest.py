"""Shared fixtures for integration tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from sketch_lines_gate import REFERENCE_DIR, GateReport, measure_reference


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
