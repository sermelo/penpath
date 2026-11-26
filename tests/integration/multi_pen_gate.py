"""Per-layer gate evidence for multi-pen output (LUC-50 part 6).

The LUC-47 gate measures one drawing against one reference image. A palette
drawing has several pens, each responsible for a colour region, so the union
of all pens is checked against the whole photo with the unchanged LUC-47
floors, and each pen is checked against its own region with region-relative
measures. Strokes are recoloured black for both checks so the ink threshold
applies to every pen regardless of its physical colour.
"""

from __future__ import annotations

import random
import xml.etree.ElementTree as ET
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
    make_ideal_plot,
    measure_plot,
    placement_crop,
    write_blank_svg,
)

from penpath.cli.main import main
from penpath.core import (
    compute_likeness,
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
GRID_CELLS = 4

UNION_FLOORS = {
    "SSIM": 0.18,
    "covered width": 0.60,
    "covered height": 0.60,
    "bbox area": 0.40,
    "ink per 4x4 cell": 0.0003,
    "tone ratio": 2.0,
}

DEFAULT_REGION_FLOORS = {
    "recall": 0.30,
    "precision": 0.50,
    "extent width": 0.60,
    "extent height": 0.60,
    "bbox area": 0.40,
    "cell recall": 0.75,
}

REGION_FLOOR_OVERRIDES: dict[str, dict[str, float]] = {
    "stabilo_88_light_blue": {"precision": 0.05},
    "stabilo_88_brown": {
        "extent height": 0.30,
        "bbox area": 0.30,
        "cell recall": 0.40,
    },
    "stabilo_88_black": {"recall": 0.55, "precision": 0.60},
}

ENFORCED_FLOORS = tuple(DEFAULT_REGION_FLOORS)
UNION_ENFORCED_FLOORS = tuple(UNION_FLOORS)

KNOWN_UNION_FAILURES = {"tone ratio": 1.6074}


@dataclass(frozen=True, slots=True)
class RegionMeasures:
    """Region-relative measurements of one drawing against one pen region."""

    region_pixels: int
    ssim: float
    recall: float
    precision: float
    extent_width: float
    extent_height: float
    bbox_area: float
    cell_recall: float


@dataclass(frozen=True, slots=True)
class PenLayerReport:
    """Measurements for one used pen layer and its three baselines."""

    pen_name: str
    color: str
    layer_id: str
    stroke_count: int
    algorithm: RegionMeasures
    blank: RegionMeasures
    random: RegionMeasures
    ideal: RegionMeasures


@dataclass(frozen=True, slots=True)
class MultiPenGateReport:
    """The union and per-layer measurements of one palette conversion."""

    reference: str
    palette: str
    placement: tuple[float, float, float, float]
    paper_size: tuple[float, float]
    union: PlotMeasures
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
            "--background-method",
            "global",
            "--pfm-setting",
            f"seed={seed}",
            "--quiet",
        ],
        env={"XDG_CONFIG_HOME": str(work_dir / "config")},
    )
    if result.exit_code != 0:
        raise RuntimeError(f"penpath convert --palette failed: {result.output}")
    return svg_path


def blacken(strokes: Sequence[PenStroke]) -> list[PenStroke]:
    """Recolour a set of already-selected strokes black for the ink threshold."""
    return [
        PenStroke(
            polyline=stroke.polyline,
            width_mm=stroke.width_mm,
            color="#000000",
            pen_up=stroke.pen_up,
        )
        for stroke in strokes
    ]


def _simulate(
    strokes: Sequence[PenStroke],
    paper_size: tuple[float, float],
) -> tuple[list[tuple[float, float]], Image.Image]:
    points = [point for stroke in strokes for point in stroke.polyline]
    plot = simulate_plot(list(strokes), paper_size[0], paper_size[1], dpi_px_per_mm=PX_PER_MM)
    return points, plot


def layer_labels(svg_path: str | Path) -> dict[str, str]:
    """Map pen names to ``layerN`` ids from the SVG's Inkscape layers."""
    root = ET.parse(Path(svg_path)).getroot()
    labels: dict[str, str] = {}
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "g":
            continue
        layer_id = element.get("id")
        groupmode = element.get("inkscape:groupmode") or element.get(
            "{http://www.inkscape.org/namespaces/inkscape}groupmode"
        )
        label = element.get("inkscape:label") or element.get(
            "{http://www.inkscape.org/namespaces/inkscape}label"
        )
        if layer_id and groupmode == "layer" and label:
            labels[label] = layer_id
    return labels


def region_mask(
    channel: Image.Image,
    plot_size: tuple[int, int],
    placement: tuple[float, float, float, float],
) -> NDArray[np.bool_]:
    """Return the pen's dark region on the page grid, thresholded on the full channel.

    The channel is the full-size separated image from ``separate_palette``. The
    threshold is applied to that whole image first; the resulting mask is then
    mapped into the recorded placement rectangle on the plot's pixel grid so it
    can be compared with the simulated ink at the same scale.
    """
    full = np.asarray(channel.convert("L")) < INK_CUTOFF
    crop = placement_crop(plot_size, placement)
    width, height = crop[2] - crop[0], crop[3] - crop[1]
    placed = Image.fromarray(full.astype(np.uint8) * 255).resize(
        (width, height), Image.Resampling.NEAREST
    )
    mask = np.zeros((plot_size[1], plot_size[0]), dtype=bool)
    mask[crop[1] : crop[3], crop[0] : crop[2]] = np.asarray(placed) >= INK_CUTOFF
    return mask


def dilate_mask(mask: NDArray[np.bool_], radius: int = 1) -> NDArray[np.bool_]:
    """Dilate a boolean mask by a square structuring element of the given radius."""
    result = mask.copy()
    for delta_y in range(-radius, radius + 1):
        for delta_x in range(-radius, radius + 1):
            if delta_y == 0 and delta_x == 0:
                continue
            shifted = np.zeros_like(mask)
            rows = slice(max(0, delta_y), mask.shape[0] + min(0, delta_y))
            columns = slice(max(0, delta_x), mask.shape[1] + min(0, delta_x))
            source_rows = slice(rows.start - delta_y, rows.stop - delta_y)
            source_columns = slice(columns.start - delta_x, columns.stop - delta_x)
            shifted[rows, columns] = mask[source_rows, source_columns]
            result |= shifted
    return result


def _bbox(mask: NDArray[np.bool_]) -> tuple[int, int, int, int] | None:
    """Return ``(top, left, bottom, right)`` of the true pixels, or None."""
    rows, columns = np.nonzero(mask)
    if rows.size == 0:
        return None
    return int(rows.min()), int(columns.min()), int(rows.max()) + 1, int(columns.max()) + 1


def measure_region(
    plot: Image.Image,
    channel: Image.Image,
    placement: tuple[float, float, float, float],
    pen_width_mm: float,
) -> RegionMeasures:
    """Score a drawing against the pen's own colour region.

    SSIM is computed for evidence only; recall, precision, extent, bbox area
    and cell recall are the pass/fail measures.
    """
    region = region_mask(channel, plot.size, placement)
    ink = np.asarray(plot.convert("L")) < INK_CUTOFF
    radius = max(1, round(pen_width_mm / 2 * PX_PER_MM))
    tolerance = dilate_mask(region, radius)
    hits = int((ink & tolerance).sum())
    region_count = int(region.sum())
    ink_count = int(ink.sum())
    recall = hits / region_count if region_count else 0.0
    precision = hits / ink_count if ink_count else 0.0

    region_bbox = _bbox(region)
    ink_bbox = _bbox(ink)
    extent_width = extent_height = bbox_area = cell_recall = 0.0
    if region_bbox is not None and ink_bbox is not None:
        top, left, bottom, right = region_bbox
        region_width, region_height = right - left, bottom - top
        ink_top, ink_left, ink_bottom, ink_right = ink_bbox
        extent_width = (ink_right - ink_left) / region_width
        extent_height = (ink_bottom - ink_top) / region_height
        overlap_width = max(0, min(right, ink_right) - max(left, ink_left))
        overlap_height = max(0, min(bottom, ink_bottom) - max(top, ink_top))
        bbox_area = overlap_width * overlap_height / (region_width * region_height)
        occupied = inked = 0
        for row in range(GRID_CELLS):
            for column in range(GRID_CELLS):
                row_start = top + row * region_height // GRID_CELLS
                row_end = top + (row + 1) * region_height // GRID_CELLS
                column_start = left + column * region_width // GRID_CELLS
                column_end = left + (column + 1) * region_width // GRID_CELLS
                cell_region = region[row_start:row_end, column_start:column_end]
                if not cell_region.any():
                    continue
                occupied += 1
                if ink[row_start:row_end, column_start:column_end].any():
                    inked += 1
        cell_recall = inked / occupied if occupied else 0.0

    return RegionMeasures(
        region_pixels=region_count,
        ssim=compute_likeness(plot, channel, placement, dpi_px_per_mm=PX_PER_MM),
        recall=float(recall),
        precision=float(precision),
        extent_width=float(extent_width),
        extent_height=float(extent_height),
        bbox_area=float(bbox_area),
        cell_recall=float(cell_recall),
    )


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
    """Measure the union against the photo and each used pen against its region."""
    with Image.open(REFERENCE_DIR / PHOTO_NAME) as opened:
        original = opened.convert("RGB")
    image_size = original.size
    placement = get_image_placement(svg_path, image_size)
    paper_size = get_svg_paper_size(svg_path) or (PAPER.width_mm, PAPER.height_mm)
    placement_tuple = (placement.x, placement.y, placement.width, placement.height)

    union_points, union_plot = _simulate(blacken(parse_svg_strokes(svg_path)), paper_size)
    union = measure_plot(union_plot, original, placement_tuple, union_points)

    labels = layer_labels(svg_path)
    layers: list[PenLayerReport] = []
    for pen, channel in separate_palette(original, list(get_palette(PALETTE_NAME).pens)):
        layer_id = labels.get(pen.name)
        if layer_id is None:
            continue
        strokes = parse_svg_strokes(svg_path, layer=layer_id)
        if not strokes:
            continue
        _points, plot = _simulate(blacken(strokes), paper_size)
        algorithm = measure_region(plot, channel, placement_tuple, pen.width_mm)

        blank_svg = svg_path.parent / f"blank-{layer_id}.svg"
        write_blank_svg(blank_svg, PAPER, placement_tuple)
        _blank_points, blank_plot = _simulate(parse_svg_strokes(blank_svg), paper_size)
        blank = measure_region(blank_plot, channel, placement_tuple, pen.width_mm)

        random_svg = svg_path.parent / f"random-{layer_id}.svg"
        _write_random_svg(random_svg, image_size, placement_tuple, len(strokes), seed)
        _random_points, random_plot = _simulate(parse_svg_strokes(random_svg), paper_size)
        random_drawing = measure_region(random_plot, channel, placement_tuple, pen.width_mm)

        ideal_plot = make_ideal_plot(channel, plot.size, placement_tuple)
        ideal = measure_region(ideal_plot, channel, placement_tuple, pen.width_mm)

        layers.append(
            PenLayerReport(
                pen_name=pen.name,
                color=pen.color,
                layer_id=layer_id,
                stroke_count=len(strokes),
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
        union=union,
        layers=layers,
    )


def measure_reference(work_dir: Path, seed: int = SEED) -> MultiPenGateReport:
    """Convert the reference photo and measure its gate evidence."""
    return measure_svg(convert_photo(work_dir, seed), seed)


def region_floors(pen_name: str) -> dict[str, float]:
    """Return the enforced region floors for one pen."""
    floors = dict(DEFAULT_REGION_FLOORS)
    floors.update(REGION_FLOOR_OVERRIDES.get(pen_name, {}))
    return floors


def format_measurement_table(reports: Sequence[MultiPenGateReport]) -> str:
    """Return a plain-text table of the union and per-layer measurements."""
    header = (
        f"{'layer':<24} {'mode':<10} {'SSIM*':>7} {'recall':>7} {'prec':>7} {'ext W':>7} "
        f"{'ext H':>7} {'bbox':>7} {'cell':>7} {'strokes':>8}"
    )
    rows = [
        f"Multi-pen gate: {PALETTE_NAME} on {PHOTO_NAME}, seed {SEED}; "
        "SSIM is evidence, the other columns carry the per-layer gate",
        "Union against the whole photo (unchanged LUC-47 floors): SSIM, W, H, bbox, min ink, tone",
    ]
    for report in reports:
        union = report.union
        rows.append(
            f"  union {'':<18} {union.ssim:>7.4f} {union.coverage_width:>7.3f} "
            f"{union.coverage_height:>7.3f} {union.coverage_area:>7.3f} "
            f"{union.ink_spread_min:>7.4f} {union.tone_ratio:>7.2f}"
        )
        rows.append("-" * len(header))
        rows.append(header)
        rows.append("-" * len(header))
        for layer in report.layers:
            for mode, measures in (
                ("algorithm", layer.algorithm),
                ("blank", layer.blank),
                ("random", layer.random),
                ("ideal", layer.ideal),
            ):
                rows.append(
                    f"{layer.pen_name:<24} {mode:<10} {measures.ssim:>7.4f} "
                    f"{measures.recall:>7.4f} {measures.precision:>7.4f} "
                    f"{measures.extent_width:>7.3f} {measures.extent_height:>7.3f} "
                    f"{measures.bbox_area:>7.3f} {measures.cell_recall:>7.3f} "
                    f"{layer.stroke_count:>8d}"
                )
    return "\n".join(rows)


def print_measurement_table(reports: Sequence[MultiPenGateReport]) -> None:
    """Print the measurement table to stdout."""
    click.echo(format_measurement_table(reports))


def gate_failures(
    layer: PenLayerReport,
    measures: RegionMeasures | None = None,
) -> list[tuple[str, float, float]]:
    """Return (measure, value, floor) for every region floor a mode does not clear."""
    measured = measures if measures is not None else layer.algorithm
    floors = region_floors(layer.pen_name)
    values = (
        ("recall", measured.recall),
        ("precision", measured.precision),
        ("extent width", measured.extent_width),
        ("extent height", measured.extent_height),
        ("bbox area", measured.bbox_area),
        ("cell recall", measured.cell_recall),
    )
    return [(name, value, floors[name]) for name, value in values if value < floors[name]]


def union_gate_failures(measures: PlotMeasures) -> list[tuple[str, float, float]]:
    """Return (measure, value, floor) for every LUC-47 floor the union fails."""
    values = (
        ("SSIM", measures.ssim),
        ("covered width", measures.coverage_width),
        ("covered height", measures.coverage_height),
        ("bbox area", measures.coverage_area),
        ("ink per 4x4 cell", measures.ink_spread_min),
        ("tone ratio", measures.tone_ratio),
    )
    return [
        (name, value, UNION_FLOORS[name]) for name, value in values if value < UNION_FLOORS[name]
    ]


__all__ = [
    "DEFAULT_REGION_FLOORS",
    "ENFORCED_FLOORS",
    "GRID_CELLS",
    "INK_CUTOFF",
    "KNOWN_UNION_FAILURES",
    "PALETTE_NAME",
    "PHOTO_NAME",
    "REGION_FLOOR_OVERRIDES",
    "SEED",
    "UNION_ENFORCED_FLOORS",
    "UNION_FLOORS",
    "MultiPenGateReport",
    "PenLayerReport",
    "RegionMeasures",
    "blacken",
    "convert_photo",
    "dilate_mask",
    "format_measurement_table",
    "gate_failures",
    "layer_labels",
    "measure_reference",
    "measure_region",
    "measure_svg",
    "print_measurement_table",
    "region_floors",
    "region_mask",
    "union_gate_failures",
]
