"""Measurement harness for the Stipple likeness and plot-cost gate (LUC-154).

Runs the real ``penpath convert`` CLI with the Stipple PFM on the committed
reference images, then reuses the Sketch Lines gate's simulation and likeness
helpers to measure coverage, ink spread, tone and SSIM against blank and random
baselines. Machine cost is read from the exported SVG with
``compute_machine_cost``. The enforced thresholds live in ``docs/TESTING.md``;
this module only produces the numbers they are justified from.
"""

from __future__ import annotations

import itertools
import math
import random
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import click
from click.testing import CliRunner
from PIL import Image
from shapely import LineString
from sketch_lines_gate import (
    PX_PER_MM,
    REFERENCE_DIR,
    PlotMeasures,
    all_finite,
    make_ideal_plot,
    measure_plot,
    simulate_svg,
    write_blank_svg,
)

from penpath.cli.main import main as cli_main
from penpath.core import (
    compute_machine_cost,
    get_image_placement,
    get_svg_paper_size,
    parse_svg_strokes,
    simulate_plot,
)
from penpath.core.models import Paper, Pen
from penpath.core.output.svg import export_svg
from penpath.core.simulation import PenStroke, insert_pen_up_moves
from penpath.presets.pfms import get_pfm_preset_settings

if TYPE_CHECKING:
    from collections.abc import Sequence

REFERENCE_NAMES = (
    "circle.png",
    "gradient.png",
    "sphere.png",
    "face.jpg",
    "photo.jpg",
    "santa.jpg",
)
PRESETS = ("stipple_default", "stipple_fine", "stipple_bold")
GATE_PRESET = "stipple_default"
SEED = 42
PAPER_SPEC = "190x190,10"
PAPER = Paper(name="square_190", width_mm=190.0, height_mm=190.0, margin_mm=10.0)
PEN_WIDTH_MM = 0.4
PEN = Pen(name="fine", width_mm=PEN_WIDTH_MM, color="#000000")
DPI = 96
MAX_RESOLUTION = 512
PENPATH_NAMESPACE = "http://penpath.org/ns/penpath"
TINY_SEGMENT_MM = 0.5


@dataclass(frozen=True, slots=True)
class PlotCost:
    """Machine cost of one stipple drawing, measured from its exported SVG."""

    strokes: int
    points: int
    length_mm: float
    travel_mm: float
    lifts: int
    tiny_segments: int
    tiny_fraction: float
    max_strokes: int


@dataclass(frozen=True, slots=True)
class StippleReport:
    """Likeness, baselines and plot cost of one image drawn by one preset."""

    reference: str
    preset: str
    placement: tuple[float, float, float, float]
    paper_size: tuple[float, float]
    working_size: tuple[int, int]
    stroke_count: int
    algorithm: PlotMeasures
    blank: PlotMeasures
    random: PlotMeasures
    ideal: PlotMeasures
    cost: PlotCost
    geometry_failures: tuple[str, ...]


def working_image_size(svg_path: Path) -> tuple[int, int]:
    """Read the working image size recorded by ``convert`` in the SVG metadata."""
    root = ET.parse(svg_path).getroot()
    for element in root.iter():
        if element.tag != f"{{{PENPATH_NAMESPACE}}}image-placement":
            continue
        width = element.get("image-width")
        height = element.get("image-height")
        if width is None or height is None:
            break
        return int(width), int(height)
    raise ValueError(f"No working image size in {svg_path.name}; cannot measure stipple")


def write_random_svg(
    path: Path,
    image_size: tuple[int, int],
    placement: tuple[float, float, float, float],
    stroke_count: int,
    seed: int,
) -> None:
    """Write a seeded random scribble with as many dots as the real drawing."""
    if stroke_count == 0:
        write_blank_svg(path, PAPER, placement)
        return
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
        [PEN],
        path,
        image_dpi=DPI,
        image_placement=placement,
        image_size_px=image_size,
    )


def geometry_problems(
    strokes: Sequence[PenStroke],
    paper_size: tuple[float, float],
    tolerance_mm: float = 0.01,
) -> tuple[str, ...]:
    """Return the invalid, off-page or zero-length strokes of a drawing."""
    problems: list[str] = []
    page_width, page_height = paper_size
    for number, stroke in enumerate(strokes):
        polyline = stroke.polyline
        line = LineString(polyline)
        if any(
            not (-tolerance_mm <= x <= page_width + tolerance_mm)
            or not (-tolerance_mm <= y <= page_height + tolerance_mm)
            for x, y in polyline
        ):
            problems.append(f"stroke {number} is outside the page")
        if any(
            math.hypot(end[0] - start[0], end[1] - start[1]) <= 0.0
            for start, end in itertools.pairwise(polyline)
        ):
            problems.append(f"stroke {number} has a zero-length segment")
        if not line.is_valid:
            problems.append(f"stroke {number} is invalid")
    return tuple(problems)


def plot_cost(strokes: Sequence[PenStroke], max_strokes: int) -> PlotCost:
    """Count dots, pen-down millimetres, pen-up travel and lifts from the SVG."""
    lengths = [
        math.hypot(end[0] - start[0], end[1] - start[1])
        for stroke in strokes
        for start, end in zip(stroke.polyline, stroke.polyline[1:], strict=False)
    ]
    cost = compute_machine_cost(insert_pen_up_moves(strokes))["total"]
    tiny = sum(1 for length in lengths if length < TINY_SEGMENT_MM)
    return PlotCost(
        strokes=int(cost["num_strokes"]),
        points=sum(len(stroke.polyline) for stroke in strokes),
        length_mm=float(cost["drawing_length_mm"]),
        travel_mm=float(cost["pen_up_travel_mm"]),
        lifts=int(cost["num_lifts"]),
        tiny_segments=tiny,
        tiny_fraction=tiny / len(lengths) if lengths else 0.0,
        max_strokes=max_strokes,
    )


def convert_preset(image_path: Path, preset: str, output: Path) -> None:
    """Convert one reference with a built-in stipple preset through the real CLI."""
    result = CliRunner().invoke(
        cli_main,
        [
            "convert",
            str(image_path),
            "-o",
            str(output),
            "--pfm",
            preset,
            "--paper",
            PAPER_SPEC,
            "--pen",
            f"{PEN_WIDTH_MM}",
            "--dpi",
            str(DPI),
            "--max-resolution",
            str(MAX_RESOLUTION),
            "--no-vpype",
            "--quiet",
            "-s",
            f"seed={SEED}",
        ],
        env={"XDG_CONFIG_HOME": str(output.parent / "config")},
    )
    if result.exit_code != 0:
        raise RuntimeError(
            f"penpath convert failed for {image_path.name}/{preset}: {result.output}"
        )


def measure_conversion(image_path: Path, preset: str, svg_path: Path) -> StippleReport:
    """Measure an exported stipple SVG against its image and three baselines."""
    with Image.open(image_path) as opened:
        original = opened.convert("RGB")
    image_size = original.size
    placement = get_image_placement(svg_path, image_size)
    placement_tuple = (placement.x, placement.y, placement.width, placement.height)
    paper_size = get_svg_paper_size(svg_path) or (PAPER.width_mm, PAPER.height_mm)
    working_size = working_image_size(svg_path)

    strokes = parse_svg_strokes(svg_path)
    points = [point for stroke in strokes for point in stroke.polyline]
    algorithm_plot = simulate_plot(strokes, paper_size[0], paper_size[1], dpi_px_per_mm=PX_PER_MM)
    algorithm = measure_plot(algorithm_plot, original, placement_tuple, points)

    blank_svg = svg_path.with_name(f"{svg_path.stem}_blank.svg")
    write_blank_svg(blank_svg, PAPER, placement_tuple)
    blank_points, blank_plot = simulate_svg(blank_svg, paper_size)
    blank = measure_plot(blank_plot, original, placement_tuple, blank_points)

    random_svg = svg_path.with_name(f"{svg_path.stem}_random.svg")
    write_random_svg(random_svg, image_size, placement_tuple, len(strokes), SEED)
    random_points, random_plot = simulate_svg(random_svg, paper_size)
    random_drawing = measure_plot(random_plot, original, placement_tuple, random_points)

    ideal_plot = make_ideal_plot(original, algorithm_plot.size, placement_tuple)
    ideal = measure_plot(ideal_plot, original, placement_tuple)

    settings = get_pfm_preset_settings(preset)
    return StippleReport(
        reference=image_path.name,
        preset=preset,
        placement=placement_tuple,
        paper_size=paper_size,
        working_size=working_size,
        stroke_count=len(strokes),
        algorithm=algorithm,
        blank=blank,
        random=random_drawing,
        ideal=ideal,
        cost=plot_cost(strokes, int(settings.max_strokes)),
        geometry_failures=geometry_problems(strokes, paper_size),
    )


def measure(image_path: Path, preset: str, work_dir: Path) -> StippleReport:
    """Convert one image with one preset and measure the result."""
    work_dir.mkdir(parents=True, exist_ok=True)
    svg_path = work_dir / f"{image_path.stem}_{preset}.svg"
    convert_preset(image_path, preset, svg_path)
    return measure_conversion(image_path, preset, svg_path)


def measure_all(
    work_dir: Path, reference_names: Sequence[str] = REFERENCE_NAMES
) -> list[StippleReport]:
    """Convert and measure every reference with the gate preset."""
    return [
        measure(REFERENCE_DIR / name, GATE_PRESET, work_dir / Path(name).stem)
        for name in reference_names
    ]


def _triple(measures: Sequence[PlotMeasures], name: str, decimals: int) -> str:
    """Format one measure for the algorithm, blank and random rows."""
    return "/".join(f"{getattr(item, name):.{decimals}f}" for item in measures)


def format_measurement_table(reports: Sequence[StippleReport]) -> str:
    """Return a plain-text table of every measured stipple gate value."""
    header = (
        f"{'image':<13} {'SSIM':>6} {'SSIM a/b/r':>24} {'W a/b/r':>20} "
        f"{'H a/b/r':>20} {'bbox a/b/r':>20} {'ink min a/b/r':>24} "
        f"{'tone a/b/r':>22} {'strokes':>8} {'len mm':>9} {'travel':>9} {'lifts':>7}"
    )
    rows = [
        "Stipple gate: default preset, seed 42, 190x190 mm paper, 0.4 mm pen, "
        f"{PX_PER_MM:.3f} px/mm",
        "Ratios are algorithm / blank / random; SSIM is evidence, not a floor.",
        header,
        "-" * len(header),
    ]
    for report in reports:
        algorithm = report.algorithm
        rows.append(
            f"{report.reference:<13} {algorithm.ssim:>6.4f} "
            f"{_triple((algorithm, report.blank, report.random), 'ssim', 4):>24} "
            f"{_triple((algorithm, report.blank, report.random), 'coverage_width', 3):>20} "
            f"{_triple((algorithm, report.blank, report.random), 'coverage_height', 3):>20} "
            f"{_triple((algorithm, report.blank, report.random), 'coverage_area', 3):>20} "
            f"{_triple((algorithm, report.blank, report.random), 'ink_spread_min', 4):>24} "
            f"{_triple((algorithm, report.blank, report.random), 'tone_ratio', 2):>22} "
            f"{report.stroke_count:>8d} {report.cost.length_mm:>9.1f} "
            f"{report.cost.travel_mm:>9.1f} {report.cost.lifts:>7d}"
        )
    return "\n".join(rows)


def print_measurement_table(reports: Sequence[StippleReport]) -> None:
    """Print the measurement table to stdout without pytest capture noise."""
    click.echo(format_measurement_table(reports))


def all_report_values_finite(report: StippleReport) -> bool:
    """Report whether every likeness measurement in a report is finite."""
    return all(
        all_finite(measures)
        for measures in (report.algorithm, report.blank, report.random, report.ideal)
    )


def main() -> None:
    """Convert and measure every reference with the gate preset, printing the table."""
    print_measurement_table(measure_all(Path("/tmp/stipple-gate")))


__all__ = [
    "DPI",
    "GATE_PRESET",
    "MAX_RESOLUTION",
    "PAPER",
    "PAPER_SPEC",
    "PEN",
    "PEN_WIDTH_MM",
    "PRESETS",
    "PX_PER_MM",
    "REFERENCE_DIR",
    "REFERENCE_NAMES",
    "SEED",
    "PlotCost",
    "StippleReport",
    "all_report_values_finite",
    "convert_preset",
    "format_measurement_table",
    "geometry_problems",
    "measure",
    "measure_all",
    "measure_conversion",
    "plot_cost",
    "print_measurement_table",
    "working_image_size",
    "write_random_svg",
]


if __name__ == "__main__":
    main()
