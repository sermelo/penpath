"""Measure the multi-pen output per layer and record any gate failures.

The SSIM and covered-width floors are asserted because every used layer clears
them. The other LUC-47 floors are reported, not silently relaxed: a palette
pen may own only a small, local colour region, so a full-placement coverage or
ink-spread floor is not necessarily meaningful for it. Failures are printed
with their numbers and recorded in docs/TESTING.md.
"""

from __future__ import annotations

import click
import pytest
from multi_pen_gate import (
    ENFORCED_FLOORS,
    MultiPenGateReport,
    black_strokes,
    gate_failures,
    measure_reference,
    print_measurement_table,
)
from sketch_lines_gate import SEED, all_finite

from penpath.core.simulation import PenStroke


@pytest.fixture(scope="module")
def multi_pen_report(tmp_path_factory: pytest.TempPathFactory) -> MultiPenGateReport:
    """Convert the reference photo once and share the measurements."""
    work_dir = tmp_path_factory.mktemp("multi-pen-gate")
    return measure_reference(work_dir / "photo", SEED)


def test_multi_pen_gate_reports_every_used_layer(
    multi_pen_report: MultiPenGateReport,
) -> None:
    """Each used palette pen has finite measures; print the evidence table."""
    assert multi_pen_report.layers
    assert multi_pen_report.reference == "photo.jpg"
    assert multi_pen_report.palette == "stabilo_88"
    for layer in multi_pen_report.layers:
        assert layer.stroke_count > 0
        assert layer.region_pixels > 0
        for measures in (layer.algorithm, layer.blank, layer.random, layer.ideal):
            assert all_finite(measures)
    print_measurement_table([multi_pen_report])
    for layer in multi_pen_report.layers:
        for name, value, floor in gate_failures(layer):
            click.echo(f"GATE FAILURE {layer.pen_name}: {name} {value:.4f} < {floor:.4f}")


def test_multi_pen_layers_meet_enforced_floors(
    multi_pen_report: MultiPenGateReport,
) -> None:
    """Every used layer clears the SSIM and covered-width floors."""
    failures = [
        f"{layer.pen_name}: {name} {value:.4f} < {floor:.4f}"
        for layer in multi_pen_report.layers
        for name, value, floor in gate_failures(layer)
        if name in ENFORCED_FLOORS
    ]
    assert not failures, "Multi-pen per-layer gate not met:\n" + "\n".join(failures)


def test_black_strokes_selects_only_one_pen_and_recolours_it() -> None:
    """The per-layer selector keeps one pen's geometry and makes its ink black."""
    red = PenStroke([(0.0, 0.0), (10.0, 10.0)], 0.4, "#FF0000")
    blue = PenStroke([(20.0, 20.0), (30.0, 30.0)], 0.4, "#0000FF")
    selected = black_strokes([red, blue], "#FF0000")
    assert len(selected) == 1
    assert selected[0].color == "#000000"
    assert selected[0].polyline == red.polyline
    assert selected[0].width_mm == red.width_mm
    assert [stroke.color for stroke in black_strokes([red, blue], "#0000FF")] == ["#000000"]
