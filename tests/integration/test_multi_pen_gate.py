"""Assert the multi-pen gate recorded in docs/TESTING.md.

The whole palette plot must clear the five transferable LUC-47 structural
floors (tone excluded). Each used pen must also own its assigned region on the
working image. Brown's recall miss is the one documented failure, tracked for
LUC-85: the test pins it with its measured value so it cannot drift silently.
The per-layer LUC-47 measures remain report-only, as in LUC-73.
"""

from __future__ import annotations

import click
import pytest
from multi_pen_gate import (
    BLANK_OWNERSHIP,
    ENFORCED_FLOORS,
    IDEAL_OWNERSHIP,
    MultiPenGateReport,
    black_strokes,
    gate_failures,
    measure_reference,
    ownership_failures,
    print_measurement_table,
    whole_plot_failures,
)
from sketch_lines_gate import SEED, all_finite

from penpath.core.simulation import PenStroke

KNOWN_OWNERSHIP_FAILURES = {("stabilo_88_brown", "recall")}


@pytest.fixture(scope="module")
def multi_pen_report(tmp_path_factory: pytest.TempPathFactory) -> MultiPenGateReport:
    """Convert the reference photo once and share the measurements."""
    work_dir = tmp_path_factory.mktemp("multi-pen-gate")
    return measure_reference(work_dir / "photo", SEED)


def test_multi_pen_gate_reports_every_used_layer(
    multi_pen_report: MultiPenGateReport,
) -> None:
    """Each used palette pen has finite measures; print the evidence tables."""
    assert multi_pen_report.layers
    assert multi_pen_report.reference == "photo.jpg"
    assert multi_pen_report.palette == "stabilo_88"
    for layer in multi_pen_report.layers:
        assert layer.stroke_count > 0
        assert layer.region_pixels > 0
        for measures in (layer.algorithm, layer.blank, layer.random, layer.ideal):
            assert all_finite(measures)
        for measures in (
            layer.ownership.algorithm,
            layer.ownership.blank,
            layer.ownership.random,
            layer.ownership.ideal,
        ):
            assert 0.0 <= measures.recall <= 1.0
            assert 0.0 <= measures.outside <= 1.0
    print_measurement_table([multi_pen_report])
    for name, value, floor in whole_plot_failures(multi_pen_report):
        click.echo(f"WHOLE PLOT FAILURE: {name} {value:.4f} < {floor:.4f}")
    for layer in multi_pen_report.layers:
        for name, value, floor in gate_failures(layer):
            click.echo(f"REPORT-ONLY LAYER MISS {layer.pen_name}: {name} {value:.4f} < {floor:.4f}")
    for pen, name, value, floor in ownership_failures(multi_pen_report):
        click.echo(f"OWNERSHIP FAILURE {pen}: {name} {value:.4f} vs {floor:.4f}")


def test_multi_pen_whole_plot_meets_structural_floors(
    multi_pen_report: MultiPenGateReport,
) -> None:
    """All layers together clear the five transferable LUC-47 floors."""
    assert multi_pen_report.whole_plot_strokes > 0
    assert all_finite(multi_pen_report.whole_plot)
    failures = whole_plot_failures(multi_pen_report)
    assert not failures, "Multi-pen whole-plot gate not met:\n" + "\n".join(
        f"{name} {value:.4f} < {floor:.4f}" for name, value, floor in failures
    )


def test_multi_pen_ownership_failures_are_only_the_documented_brown_miss(
    multi_pen_report: MultiPenGateReport,
) -> None:
    """Every pen owns its region except brown, whose recall miss is tracked."""
    failures = ownership_failures(multi_pen_report)
    actual = {(pen, name) for pen, name, _, _ in failures}
    assert actual == KNOWN_OWNERSHIP_FAILURES, "Multi-pen ownership gate changed:\n" + "\n".join(
        f"{pen}: {name} {value:.4f} vs {floor:.4f}" for pen, name, value, floor in failures
    )
    layers = {layer.pen_name: layer for layer in multi_pen_report.layers}
    brown = layers["stabilo_88_brown"].ownership.algorithm
    assert brown.recall == pytest.approx(0.2287, abs=0.01)
    assert brown.outside == pytest.approx(0.4356, abs=0.01)
    assert {layer.pen_name: layer.region_pixels for layer in multi_pen_report.layers} == {
        "stabilo_88_light_blue": 188847,
        "stabilo_88_brown": 4550,
        "stabilo_88_black": 167350,
    }
    for layer in multi_pen_report.layers:
        assert layer.ownership.blank == BLANK_OWNERSHIP
        assert layer.ownership.ideal == IDEAL_OWNERSHIP
        assert 0.0 <= layer.ownership.random.recall <= 1.0
        assert 0.0 <= layer.ownership.random.outside <= 1.0


def test_multi_pen_layers_meet_enforced_report_only_floors(
    multi_pen_report: MultiPenGateReport,
) -> None:
    """Every used layer clears the SSIM and covered-width reporting floors."""
    failures = [
        f"{layer.pen_name}: {name} {value:.4f} < {floor:.4f}"
        for layer in multi_pen_report.layers
        for name, value, floor in gate_failures(layer)
        if name in ENFORCED_FLOORS
    ]
    assert not failures, "Multi-pen per-layer SSIM/width gate not met:\n" + "\n".join(failures)


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
