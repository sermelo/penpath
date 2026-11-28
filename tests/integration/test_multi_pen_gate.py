"""Enforce the multi-pen gate: union against the photo, each pen against its region.

The union keeps the LUC-47 floors verbatim. Each used layer is measured with
region-relative recall, precision, extent, bbox area and cell recall; SSIM is
printed as evidence but is not a per-layer floor. Blank pages and random
scribbles must fail the region floors, so the gate cannot pass for every
possible drawing. The sparse layers introduced by LUC-123's hue-led separation
are pinned with their region-relative measures so the choice cannot regress.
"""

from __future__ import annotations

from pathlib import Path

import click
import numpy as np
import pytest
from multi_pen_gate import (
    DEFAULT_REGION_FLOORS,
    ENFORCED_FLOORS,
    KNOWN_UNION_FAILURES,
    UNION_ENFORCED_FLOORS,
    UNION_FLOORS,
    MultiPenGateReport,
    blacken,
    dilate_mask,
    gate_failures,
    measure_reference,
    measure_region,
    print_measurement_table,
    region_floors,
    region_mask,
    union_gate_failures,
)
from PIL import Image
from sketch_lines_gate import SEED, placement_crop

from penpath.core.simulation import PenStroke
from penpath.core.svg_parse import parse_svg_strokes


@pytest.fixture(scope="module")
def multi_pen_report(tmp_path_factory: pytest.TempPathFactory) -> MultiPenGateReport:
    """Convert the reference photo once and share the measurements."""
    work_dir = tmp_path_factory.mktemp("multi-pen-gate")
    return measure_reference(work_dir / "photo", SEED)


@pytest.mark.slow
def test_multi_pen_gate_reports_every_used_layer(
    multi_pen_report: MultiPenGateReport,
) -> None:
    """Each used palette pen has finite measures; print the evidence table."""
    assert multi_pen_report.layers
    assert multi_pen_report.reference == "photo.jpg"
    assert multi_pen_report.palette == "stabilo_88"
    print_measurement_table([multi_pen_report])
    for layer in multi_pen_report.layers:
        assert layer.stroke_count > 0
        assert layer.layer_id.startswith("layer")
        for measures in (layer.algorithm, layer.blank, layer.random, layer.ideal):
            assert measures.region_pixels > 0
            assert all(
                np.isfinite(value)
                for value in (
                    measures.ssim,
                    measures.recall,
                    measures.precision,
                    measures.extent_width,
                    measures.extent_height,
                    measures.bbox_area,
                    measures.cell_recall,
                )
            )
        for name, value, floor in gate_failures(layer, layer.algorithm):
            click.echo(f"GATE FAILURE {layer.pen_name}: {name} {value:.4f} < {floor:.4f}")


def test_layer_selection_does_not_mix_pens_that_share_a_color(tmp_path: Path) -> None:
    """Selecting by layerN keeps pens apart even when their stroke colour matches."""
    svg = tmp_path / "repeated-colour.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
        'width="100mm" height="100mm" viewBox="0 0 100 100">'
        '<g id="layer1" inkscape:groupmode="layer" inkscape:label="pen a" '
        'stroke="#FF0000" stroke-width="1">'
        '<path d="M 0 0 L 10 10" fill="none"/></g>'
        '<g id="layer2" inkscape:groupmode="layer" inkscape:label="pen b" '
        'stroke="#FF0000" stroke-width="1">'
        '<path d="M 20 20 L 30 30" fill="none"/></g>'
        "</svg>",
        encoding="utf-8",
    )
    first = parse_svg_strokes(svg, layer="layer1")
    second = parse_svg_strokes(svg, layer="layer2")
    assert len(first) == len(second) == 1
    assert first[0].polyline == [(0.0, 0.0), (10.0, 10.0)]
    assert second[0].polyline == [(20.0, 20.0), (30.0, 30.0)]


def test_region_mask_thresholds_the_full_channel_at_an_offset_placement() -> None:
    """A small dark area stays small when the full channel maps into the placement."""
    plot_size = (40, 40)
    placement = (5.0, 5.0, 10.0, 10.0)
    channel = Image.new("L", (20, 20), 255)
    for row in range(2, 4):
        for column in range(2, 4):
            channel.putpixel((column, row), 0)
    crop = placement_crop(plot_size, placement)
    region = region_mask(channel, plot_size, placement)
    rows, columns = np.nonzero(region)
    assert crop == (19, 19, 40, 40)
    assert int(region.sum()) == 4
    assert (
        int(rows.min()),
        int(columns.min()),
        int(rows.max()) + 1,
        int(columns.max()) + 1,
    ) == (21, 21, 23, 23)
    assert not region[: crop[1]].any() and not region[crop[3] :].any()
    assert not region[:, : crop[0]].any() and not region[:, crop[2] :].any()


def test_region_measures_reward_ink_inside_the_region_and_punish_stray_ink() -> None:
    """Recall and precision are a pair: a blank fails recall, a scribble precision."""
    placement = (0.0, 0.0, 20.0, 20.0)
    plot_size = (20, 20)
    channel = Image.new("L", plot_size, 255)
    for row in range(5, 15):
        for column in range(5, 15):
            channel.putpixel((column, row), 0)
    assert placement_crop(plot_size, placement) == (0, 0, 20, 20)

    blank = Image.new("RGB", plot_size, "white")
    blank_measures = measure_region(blank, channel, placement, 0.4)
    assert blank_measures.recall == 0.0

    inside = Image.new("RGB", plot_size, "white")
    for row in range(5, 15):
        for column in range(5, 15):
            inside.putpixel((column, row), (0, 0, 0))
    inside_measures = measure_region(inside, channel, placement, 0.4)
    assert inside_measures.recall == pytest.approx(1.0)
    assert inside_measures.precision == pytest.approx(1.0)
    assert inside_measures.cell_recall == pytest.approx(1.0)

    stray = Image.new("RGB", plot_size, "white")
    for row in range(0, 3):
        for column in range(0, 20):
            stray.putpixel((column, row), (0, 0, 0))
    stray_measures = measure_region(stray, channel, placement, 0.4)
    assert stray_measures.precision == 0.0


def test_dilate_mask_extends_the_region_by_half_a_pen_width() -> None:
    """A one-pixel dilation makes the tolerance three pixels across."""
    mask = np.zeros((7, 7), dtype=bool)
    mask[3, 3] = True
    dilated = dilate_mask(mask, radius=1)
    assert int(dilated.sum()) == 9
    assert bool(dilated[2, 2]) and bool(dilated[4, 4])


@pytest.mark.slow
def test_enforced_region_floors_are_all_asserted(multi_pen_report: MultiPenGateReport) -> None:
    """Every region measure in the report has an enforced floor."""
    assert set(ENFORCED_FLOORS) == set(DEFAULT_REGION_FLOORS)
    for layer in multi_pen_report.layers:
        assert set(region_floors(layer.pen_name)) == set(ENFORCED_FLOORS)
        assert all(value > 0 for value in region_floors(layer.pen_name).values())


@pytest.mark.slow
def test_used_layers_meet_region_floors(multi_pen_report: MultiPenGateReport) -> None:
    """The drawing of every used pen clears all enforced region floors."""
    failures = [
        f"{layer.pen_name}: {name} {value:.4f} < {floor:.4f}"
        for layer in multi_pen_report.layers
        for name, value, floor in gate_failures(layer)
    ]
    assert not failures, "Multi-pen per-layer gate not met:\n" + "\n".join(failures)


@pytest.mark.slow
def test_sparse_layer_choices_are_pinned_after_luc123(
    multi_pen_report: MultiPenGateReport,
) -> None:
    """Hue-led separation hands the sky, horizon and corner to blue, green and purple.

    Brown and light blue no longer own pixels, so neither draws a layer. The
    three new sparse layers are pinned here with their stroke counts and
    region-relative measures so a silent change of pen cannot pass the gate.
    """
    layers = {layer.pen_name: layer for layer in multi_pen_report.layers}
    assert "stabilo_88_brown" not in layers
    assert "stabilo_88_light_blue" not in layers

    pins = {
        "stabilo_88_blue": (61, 1.3531, 0.2199, 1.001, 1.002, 0.997, 0.857),
        "stabilo_88_light_green": (21, 0.8244, 0.9641, 1.003, 0.538, 0.538, 0.545),
        "stabilo_88_purple": (10, 0.6464, 0.5536, 0.697, 0.191, 0.133, 0.333),
    }
    for pen_name, (strokes, recall, precision, ext_w, ext_h, bbox, cell) in pins.items():
        layer = layers[pen_name]
        measured = layer.algorithm
        assert layer.stroke_count == strokes
        assert measured.recall == pytest.approx(recall, abs=0.02)
        assert measured.precision == pytest.approx(precision, abs=0.02)
        assert measured.extent_width == pytest.approx(ext_w, abs=0.02)
        assert measured.extent_height == pytest.approx(ext_h, abs=0.02)
        assert measured.bbox_area == pytest.approx(bbox, abs=0.02)
        assert measured.cell_recall == pytest.approx(cell, abs=0.02)


@pytest.mark.slow
def test_ideal_baseline_clears_every_enforced_floor(
    multi_pen_report: MultiPenGateReport,
) -> None:
    """A floor must never sit above what its own pen's channel can reach."""
    failures = [
        f"{layer.pen_name}: {name} {value:.4f} < {floor:.4f}"
        for layer in multi_pen_report.layers
        for name, value, floor in gate_failures(layer, layer.ideal)
    ]
    assert not failures, "Floors above a pen's ideal baseline:\n" + "\n".join(failures)


@pytest.mark.slow
def test_blank_page_fails_region_floors(multi_pen_report: MultiPenGateReport) -> None:
    """A blank layer fails recall and precision for every pen."""
    for layer in multi_pen_report.layers:
        failures = gate_failures(layer, layer.blank)
        failing = {name for name, _, _ in failures}
        assert "recall" in failing, layer.pen_name
        assert "precision" in failing, layer.pen_name


@pytest.mark.slow
def test_random_scribble_fails_region_floors(multi_pen_report: MultiPenGateReport) -> None:
    """A random scribble fails at least one region floor for every pen."""
    for layer in multi_pen_report.layers:
        failures = gate_failures(layer, layer.random)
        assert failures, f"{layer.pen_name} passes every region floor"
        failing = {name for name, _, _ in failures}
        assert failing & {"recall", "precision"}, layer.pen_name


@pytest.mark.slow
def test_union_keeps_the_luc47_floors(multi_pen_report: MultiPenGateReport) -> None:
    """The union is checked with the shipped floors, with any failure pinned.

    LUC-123's hue-led separation clears every LUC-47 floor, including tone, so
    no failure is recorded. A new failure fails this test rather than being
    silently accepted or lowering a floor.
    """
    failures = union_gate_failures(multi_pen_report.union)
    assert set(UNION_ENFORCED_FLOORS) == set(UNION_FLOORS)
    unexpected = [
        (name, value, floor) for name, value, floor in failures if name not in KNOWN_UNION_FAILURES
    ]
    assert not unexpected, "New union regression:\n" + "\n".join(
        f"{name} {value:.4f} < {floor:.4f}" for name, value, floor in unexpected
    )
    for name, value, floor in failures:
        assert value == pytest.approx(KNOWN_UNION_FAILURES[name], abs=0.05)
        click.echo(f"RECORDED UNION FAILURE {name}: {value:.4f} < {floor:.4f}")


def test_blacken_keeps_geometry_but_makes_every_stroke_black() -> None:
    """Recolouring a selected layer changes only the ink colour."""
    strokes = [PenStroke([(0.0, 0.0), (10.0, 10.0)], 0.4, "#FF0000")]
    result = blacken(strokes)
    assert len(result) == 1
    assert result[0].color == "#000000"
    assert result[0].polyline == strokes[0].polyline
    assert result[0].width_mm == strokes[0].width_mm
