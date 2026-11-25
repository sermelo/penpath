"""Gate evidence for multi-pen output (LUC-50 part 5, LUC-84).

A palette plot is measured three ways: the whole drawing against the full
photo with the transferable LUC-47 structural floors (without tone), each used
layer against its own source colour channel with the LUC-47 measures, and each
used layer's ownership of its assigned region on the working image the CLI
drew on. Strokes are recoloured black for simulation so the ink threshold
applies to every pen regardless of its physical colour.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import click
import numpy as np
from click.testing import CliRunner
from numpy.typing import NDArray
from PIL import Image
from shapely import LineString
from sketch_lines_gate import (
    INK_CUTOFF,
    PX_PER_MM,
    REFERENCE_DIR,
    SEED,
    PlotMeasures,
    ink_mask,
    make_ideal_plot,
    measure_plot,
    placement_crop,
    write_blank_svg,
)

from penpath.cli.main import main
from penpath.core import (
    get_image_placement,
    get_svg_paper_size,
    parse_svg_strokes,
    separate_palette,
    simulate_plot,
)
from penpath.core.image.resolution import apply_working_resolution, plan_working_resolution
from penpath.core.models import Paper, Pen
from penpath.core.output.svg import export_svg
from penpath.core.simulation import PenStroke
from penpath.presets.palettes import get_palette

if TYPE_CHECKING:
    from collections.abc import Sequence

PALETTE_NAME = "stabilo_88"
PHOTO_NAME = "photo.jpg"
PAPER = Paper(name="a4", width_mm=210.0, height_mm=297.0, margin_mm=10.0)
INK_PEN = Pen(name="measurement", width_mm=0.4, color="#000000")
GATE_FLOORS = {
    "SSIM": 0.18,
    "covered width": 0.60,
    "covered height": 0.60,
    "bbox area": 0.40,
    "ink per 4x4 cell": 0.0003,
    "tone ratio": 2.0,
}
ENFORCED_FLOORS = ("SSIM", "covered width")
WHOLE_PLOT_FLOORS = {
    "SSIM": 0.18,
    "covered width": 0.60,
    "covered height": 0.60,
    "bbox area": 0.40,
    "ink per 4x4 cell": 0.0003,
}
OWNERSHIP_RECALL_MIN = 0.45
OWNERSHIP_OUTSIDE_MAX = 0.50


@dataclass(frozen=True, slots=True)
class Ownership:
    """Share of a pen's region ink covered, and plotted ink outside its region."""

    recall: float
    outside: float


@dataclass(frozen=True, slots=True)
class OwnershipReport:
    """Ownership of one layer and its blank, random and ideal baselines."""

    algorithm: Ownership
    blank: Ownership
    random: Ownership
    ideal: Ownership


@dataclass(frozen=True, slots=True)
class PenLayerReport:
    """Measurements for one used pen layer and its three baselines."""

    pen_name: str
    color: str
    stroke_count: int
    region_pixels: int
    algorithm: PlotMeasures
    blank: PlotMeasures
    random: PlotMeasures
    ideal: PlotMeasures
    ownership: OwnershipReport


@dataclass(frozen=True, slots=True)
class MultiPenGateReport:
    """Whole-plot and per-layer measurements of one palette conversion."""

    reference: str
    palette: str
    placement: tuple[float, float, float, float]
    paper_size: tuple[float, float]
    whole_plot: PlotMeasures
    whole_plot_strokes: int
    layers: list[PenLayerReport]


def convert_photo(work_dir: Path, seed: int = SEED) -> Path:
    """Run the real CLI on the reference photo with the built-in palette."""
    work_dir.mkdir(parents=True, exist_ok=True)
    svg_path = work_dir / "plot.svg"
    result = CliRunner().invoke(
        main,
        [
            "convert",
            str(REFERENCE_DIR / PHOTO_NAME),
            "-o",
            str(svg_path),
            "--palette",
            PALETTE_NAME,
            "--pfm-setting",
            f"seed={seed}",
            "--quiet",
        ],
        env={"XDG_CONFIG_HOME": str(work_dir / "config")},
    )
    if result.exit_code != 0:
        raise RuntimeError(f"penpath convert --palette failed: {result.output}")
    return svg_path


def recolor_black(strokes: Sequence[PenStroke]) -> list[PenStroke]:
    """Recolour strokes black so every pen uses the simulator's ink threshold."""
    return [
        PenStroke(
            polyline=stroke.polyline,
            width_mm=stroke.width_mm,
            color="#000000",
            pen_up=stroke.pen_up,
        )
        for stroke in strokes
    ]


def black_strokes(strokes: Sequence[PenStroke], color: str) -> list[PenStroke]:
    """Select one pen's strokes and recolour them black for the ink threshold."""
    return recolor_black([stroke for stroke in strokes if stroke.color.upper() == color.upper()])


def working_channels(
    original: Image.Image,
    pens: Sequence[Pen],
) -> dict[str, Image.Image]:
    """Derive one separated channel per pen on the CLI's working image.

    The CLI downsizes the loaded image to one pixel per pen width before it
    splits the palette. The gate must score ownership on that image: a crop of
    the source channel is in source pixels, a different coordinate space from
    the channel the drawing algorithm actually saw.
    """
    resolution = plan_working_resolution(original.size, PAPER, pens[0].width_mm)
    working = apply_working_resolution(original, resolution)
    return {pen.name: channel for pen, channel in separate_palette(working, list(pens))}


def resize_mask(mask: NDArray[np.bool_], size: tuple[int, int]) -> NDArray[np.bool_]:
    """Resample a binary mask to another coordinate space without new values."""
    image = Image.fromarray(mask.astype(np.uint8) * 255)
    return np.asarray(image.resize(size, Image.Resampling.NEAREST)) > 127


def ownership_metrics(
    ink: NDArray[np.bool_],
    region: NDArray[np.bool_],
    region_ink: NDArray[np.bool_],
) -> Ownership:
    """Return recall of the region's ink pixels and the share of ink outside it.

    A pen with no plotted ink has no visible ownership: recall is 0 and the
    outside share is 1, the same convention as the basic-shapes gate.
    """
    outside = int((ink & ~region).sum())
    plotted = int(ink.sum())
    inside_region_ink = int((ink & region_ink).sum())
    region_pixels = int(region_ink.sum())
    return Ownership(
        recall=inside_region_ink / region_pixels if region_pixels else 0.0,
        outside=outside / plotted if plotted else 1.0,
    )


BLANK_OWNERSHIP = Ownership(recall=0.0, outside=1.0)
IDEAL_OWNERSHIP = Ownership(recall=1.0, outside=0.0)


def _simulate(
    strokes: Sequence[PenStroke],
    paper_size: tuple[float, float],
) -> tuple[list[tuple[float, float]], Image.Image]:
    points = [point for stroke in strokes for point in stroke.polyline]
    plot = simulate_plot(list(strokes), paper_size[0], paper_size[1], dpi_px_per_mm=PX_PER_MM)
    return points, plot


def _write_random_svg(
    path: Path,
    image_size: tuple[int, int],
    placement: tuple[float, float, float, float],
    stroke_count: int,
    seed: int,
) -> None:
    rng = random.Random(seed)
    lines = [
        LineString(
            [
                (rng.uniform(0, image_size[0]), rng.uniform(0, image_size[1])),
                (rng.uniform(0, image_size[0]), rng.uniform(0, image_size[1])),
            ]
        )
        for _ in range(stroke_count)
    ]
    export_svg(
        lines,
        PAPER,
        [INK_PEN],
        path,
        image_dpi=300,
        image_placement=placement,
        image_size_px=image_size,
    )


def measure_svg(svg_path: Path, seed: int = SEED) -> MultiPenGateReport:
    """Measure the whole palette plot and every used layer of a palette SVG."""
    with Image.open(REFERENCE_DIR / PHOTO_NAME) as opened:
        original = opened.convert("RGB")
    image_size = original.size
    placement = get_image_placement(svg_path, image_size)
    paper_size = get_svg_paper_size(svg_path) or (PAPER.width_mm, PAPER.height_mm)
    placement_tuple = (placement.x, placement.y, placement.width, placement.height)
    strokes = parse_svg_strokes(svg_path)
    pens = list(get_palette(PALETTE_NAME).pens)
    channels = {pen.name: channel for pen, channel in separate_palette(original, pens)}
    working_channels_by_pen = working_channels(original, pens)

    all_points, all_plot = _simulate(recolor_black(strokes), paper_size)
    whole_plot = measure_plot(all_plot, original, placement_tuple, all_points)
    crop = placement_crop(all_plot.size, placement_tuple)
    crop_size = (crop[2] - crop[0], crop[3] - crop[1])

    layers: list[PenLayerReport] = []
    for pen in pens:
        pen_strokes = black_strokes(strokes, pen.color)
        if not pen_strokes:
            continue
        channel = channels[pen.name]
        points, plot = _simulate(pen_strokes, paper_size)
        algorithm = measure_plot(plot, channel, placement_tuple, points)

        blank_svg = svg_path.parent / f"blank-{pen.name}.svg"
        write_blank_svg(blank_svg, PAPER, placement_tuple)
        blank_points, blank_plot = _simulate(parse_svg_strokes(blank_svg), paper_size)
        blank = measure_plot(blank_plot, channel, placement_tuple, blank_points)

        random_svg = svg_path.parent / f"random-{pen.name}.svg"
        _write_random_svg(random_svg, image_size, placement_tuple, len(pen_strokes), seed)
        random_points, random_plot = _simulate(parse_svg_strokes(random_svg), paper_size)
        random_drawing = measure_plot(random_plot, channel, placement_tuple, random_points)

        ideal_plot = make_ideal_plot(channel, plot.size, placement_tuple)
        ideal = measure_plot(ideal_plot, channel, placement_tuple)

        working_channel = working_channels_by_pen[pen.name]
        assigned = np.asarray(working_channel) < 255
        region_ink = np.asarray(working_channel) < INK_CUTOFF
        assigned_crop = resize_mask(assigned, crop_size)
        region_ink_crop = resize_mask(region_ink, crop_size)
        ownership = OwnershipReport(
            algorithm=ownership_metrics(ink_mask(plot, crop), assigned_crop, region_ink_crop),
            blank=BLANK_OWNERSHIP,
            random=ownership_metrics(ink_mask(random_plot, crop), assigned_crop, region_ink_crop),
            ideal=IDEAL_OWNERSHIP,
        )

        layers.append(
            PenLayerReport(
                pen_name=pen.name,
                color=pen.color,
                stroke_count=len(pen_strokes),
                region_pixels=int(assigned.sum()),
                algorithm=algorithm,
                blank=blank,
                random=random_drawing,
                ideal=ideal,
                ownership=ownership,
            )
        )

    return MultiPenGateReport(
        reference=PHOTO_NAME,
        palette=PALETTE_NAME,
        placement=placement_tuple,
        paper_size=paper_size,
        whole_plot=whole_plot,
        whole_plot_strokes=len(strokes),
        layers=layers,
    )


def measure_reference(work_dir: Path, seed: int = SEED) -> MultiPenGateReport:
    """Convert the reference photo and measure its whole-plot and per-layer evidence."""
    return measure_svg(convert_photo(work_dir, seed), seed)


def format_measurement_table(reports: Sequence[MultiPenGateReport]) -> str:
    """Return a plain-text table of the whole-plot and per-layer measurements."""
    likeness_header = (
        f"{'layer':<24} {'mode':<10} {'SSIM':>7} {'cov W':>7} {'cov H':>7} {'bbox':>7} "
        f"{'ink min':>8} {'ink max':>8} {'tone':>7} {'strokes':>8}"
    )
    ownership_header = f"{'layer':<24} {'mode':<10} {'region px':>10} {'recall':>8} {'outside':>8}"
    rows = [f"Multi-pen gate: {PALETTE_NAME} on {PHOTO_NAME}, seed {SEED}"]
    for report in reports:
        whole = report.whole_plot
        rows.extend(
            [
                "Whole plot (all layers, black, vs full photo):",
                f"  SSIM {whole.ssim:.4f}  cov W {whole.coverage_width:.3f}  "
                f"cov H {whole.coverage_height:.3f}  bbox {whole.coverage_area:.3f}  "
                f"ink min {whole.ink_spread_min:.4f}  tone {whole.tone_ratio:.2f} "
                f"(report only)  strokes {report.whole_plot_strokes:d}",
                "",
                "Per-layer likeness vs each pen's own source channel:",
                likeness_header,
                "-" * len(likeness_header),
            ]
        )
        for layer in report.layers:
            for mode, measures in (
                ("algorithm", layer.algorithm),
                ("blank", layer.blank),
                ("random", layer.random),
                ("ideal", layer.ideal),
            ):
                rows.append(
                    f"{layer.pen_name:<24} {mode:<10} {measures.ssim:>7.4f} "
                    f"{measures.coverage_width:>7.3f} {measures.coverage_height:>7.3f} "
                    f"{measures.coverage_area:>7.3f} {measures.ink_spread_min:>8.4f} "
                    f"{measures.ink_spread_max:>8.4f} {measures.tone_ratio:>7.2f} "
                    f"{layer.stroke_count:>8d}"
                )
        rows.extend(
            [
                "",
                "Ownership vs each pen's assigned region on the working image:",
                ownership_header,
                "-" * len(ownership_header),
            ]
        )
        for layer in report.layers:
            for mode, measures in (
                ("algorithm", layer.ownership.algorithm),
                ("blank", layer.ownership.blank),
                ("random", layer.ownership.random),
                ("ideal", layer.ownership.ideal),
            ):
                rows.append(
                    f"{layer.pen_name:<24} {mode:<10} {layer.region_pixels:>10d} "
                    f"{measures.recall:>8.4f} {measures.outside:>8.4f}"
                )
    return "\n".join(rows)


def print_measurement_table(reports: Sequence[MultiPenGateReport]) -> None:
    """Print the whole-plot and per-layer measurement tables to stdout."""
    click.echo(format_measurement_table(reports))


def gate_failures(layer: PenLayerReport) -> list[tuple[str, float, float]]:
    """Return (measure, value, floor) for every report-only LUC-47 floor missed."""
    measured = layer.algorithm
    values = (
        ("SSIM", measured.ssim),
        ("covered width", measured.coverage_width),
        ("covered height", measured.coverage_height),
        ("bbox area", measured.coverage_area),
        ("ink per 4x4 cell", measured.ink_spread_min),
        ("tone ratio", measured.tone_ratio),
    )
    return [(name, value, GATE_FLOORS[name]) for name, value in values if value < GATE_FLOORS[name]]


def whole_plot_failures(report: MultiPenGateReport) -> list[tuple[str, float, float]]:
    """Return (measure, value, floor) for every structural floor the plot misses."""
    measured = report.whole_plot
    values = (
        ("SSIM", measured.ssim),
        ("covered width", measured.coverage_width),
        ("covered height", measured.coverage_height),
        ("bbox area", measured.coverage_area),
        ("ink per 4x4 cell", measured.ink_spread_min),
    )
    return [
        (name, value, WHOLE_PLOT_FLOORS[name])
        for name, value in values
        if value < WHOLE_PLOT_FLOORS[name]
    ]


def ownership_failures(report: MultiPenGateReport) -> list[tuple[str, str, float, float]]:
    """Return (pen, measure, value, floor) for every ownership floor missed."""
    failures: list[tuple[str, str, float, float]] = []
    for layer in report.layers:
        measured = layer.ownership.algorithm
        if measured.recall < OWNERSHIP_RECALL_MIN:
            failures.append((layer.pen_name, "recall", measured.recall, OWNERSHIP_RECALL_MIN))
        if measured.outside > OWNERSHIP_OUTSIDE_MAX:
            failures.append((layer.pen_name, "outside", measured.outside, OWNERSHIP_OUTSIDE_MAX))
    return failures


__all__ = [
    "BLANK_OWNERSHIP",
    "ENFORCED_FLOORS",
    "GATE_FLOORS",
    "IDEAL_OWNERSHIP",
    "INK_CUTOFF",
    "OWNERSHIP_OUTSIDE_MAX",
    "OWNERSHIP_RECALL_MIN",
    "PALETTE_NAME",
    "PHOTO_NAME",
    "SEED",
    "WHOLE_PLOT_FLOORS",
    "MultiPenGateReport",
    "Ownership",
    "OwnershipReport",
    "PenLayerReport",
    "black_strokes",
    "convert_photo",
    "format_measurement_table",
    "gate_failures",
    "measure_reference",
    "measure_svg",
    "ownership_failures",
    "ownership_metrics",
    "print_measurement_table",
    "recolor_black",
    "resize_mask",
    "whole_plot_failures",
    "working_channels",
]
