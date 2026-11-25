"""Per-layer gate evidence for multi-pen output (LUC-50 part 5).

The LUC-47 gate measures one drawing against one reference image. A palette
drawing has several pens, each responsible for a different colour region, so
the same measures are taken once per used layer: the pen's separated colour
channel is the reference, and only that layer's strokes are simulated. Strokes
are recoloured black for the simulation so the gate's ink threshold applies to
every pen regardless of its physical colour.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import click
import numpy as np
from click.testing import CliRunner
from PIL import Image
from shapely import LineString
from sketch_lines_gate import (
    INK_CUTOFF,
    PX_PER_MM,
    REFERENCE_DIR,
    SEED,
    PlotMeasures,
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


@dataclass(frozen=True, slots=True)
class MultiPenGateReport:
    """The per-layer measurements of one palette conversion."""

    reference: str
    palette: str
    placement: tuple[float, float, float, float]
    paper_size: tuple[float, float]
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


def black_strokes(strokes: Sequence[PenStroke], color: str) -> list[PenStroke]:
    """Select one pen's strokes and recolour them black for the ink threshold."""
    return [
        PenStroke(
            polyline=stroke.polyline,
            width_mm=stroke.width_mm,
            color="#000000",
            pen_up=stroke.pen_up,
        )
        for stroke in strokes
        if stroke.color.upper() == color.upper()
    ]


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
    """Measure every used pen layer of a palette SVG against its own channel."""
    with Image.open(REFERENCE_DIR / PHOTO_NAME) as opened:
        original = opened.convert("RGB")
    image_size = original.size
    placement = get_image_placement(svg_path, image_size)
    paper_size = get_svg_paper_size(svg_path) or (PAPER.width_mm, PAPER.height_mm)
    placement_tuple = (placement.x, placement.y, placement.width, placement.height)
    strokes = parse_svg_strokes(svg_path)
    pens = list(get_palette(PALETTE_NAME).pens)
    channels = separate_palette(original, pens)

    layers: list[PenLayerReport] = []
    for pen, channel in channels:
        pen_strokes = black_strokes(strokes, pen.color)
        if not pen_strokes:
            continue
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
        crop = placement_crop(plot.size, placement_tuple)
        region = np.asarray(channel.convert("L").crop(crop)) < INK_CUTOFF

        layers.append(
            PenLayerReport(
                pen_name=pen.name,
                color=pen.color,
                stroke_count=len(pen_strokes),
                region_pixels=int(region.sum()),
                algorithm=algorithm,
                blank=blank,
                random=random_drawing,
                ideal=ideal,
            )
        )

    return MultiPenGateReport(
        reference=PHOTO_NAME,
        palette=PALETTE_NAME,
        placement=placement_tuple,
        paper_size=paper_size,
        layers=layers,
    )


def measure_reference(work_dir: Path, seed: int = SEED) -> MultiPenGateReport:
    """Convert the reference photo and measure its per-layer gate evidence."""
    return measure_svg(convert_photo(work_dir, seed), seed)


def format_measurement_table(reports: Sequence[MultiPenGateReport]) -> str:
    """Return a plain-text table of the per-layer measurements."""
    header = (
        f"{'layer':<24} {'mode':<10} {'SSIM':>7} {'cov W':>7} {'cov H':>7} {'bbox':>7} "
        f"{'ink min':>8} {'ink max':>8} {'tone':>7} {'strokes':>8}"
    )
    rows = [
        f"Per-layer gate: {PALETTE_NAME} on {PHOTO_NAME}, seed {SEED}, "
        "each layer scored against its own colour channel",
        header,
        "-" * len(header),
    ]
    for report in reports:
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
    return "\n".join(rows)


def print_measurement_table(reports: Sequence[MultiPenGateReport]) -> None:
    """Print the per-layer measurement table to stdout."""
    click.echo(format_measurement_table(reports))


def gate_failures(layer: PenLayerReport) -> list[tuple[str, float, float]]:
    """Return (measure, value, floor) for every floor the layer does not clear."""
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


__all__ = [
    "ENFORCED_FLOORS",
    "GATE_FLOORS",
    "INK_CUTOFF",
    "PALETTE_NAME",
    "PHOTO_NAME",
    "SEED",
    "MultiPenGateReport",
    "PenLayerReport",
    "black_strokes",
    "convert_photo",
    "format_measurement_table",
    "gate_failures",
    "measure_reference",
    "measure_svg",
    "print_measurement_table",
]
