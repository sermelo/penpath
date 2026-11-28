"""Measurement harness for the Sketch Squares readability and plot-cost gate (LUC-149).

Runs the real ``penpath convert`` CLI for every built-in Sketch Squares preset on
the portrait/photo references, then simulates the exported SVG as ``penpath
evaluate`` does. It records dark-region proximity recall, ink precision, stroke
extent and pen cost beside blank-page and random-line baselines. The enforced
floors are in ``tests/integration/test_sketch_squares_gate.py`` and are justified
in ``docs/TESTING.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import click
import numpy as np
from click.testing import CliRunner
from contour_gate import PlotCost, geometry_problems, plot_cost
from numpy.typing import NDArray
from PIL import Image
from scipy.ndimage import binary_dilation
from sketch_lines_gate import (
    INK_CUTOFF,
    PAPER,
    coverage_fractions,
    ink_mask,
    placement_crop,
    simulate_svg,
    write_blank_svg,
    write_random_svg,
)

from penpath.cli.main import main as cli_main
from penpath.core import get_image_placement, get_svg_paper_size, parse_svg_strokes

if TYPE_CHECKING:
    from collections.abc import Sequence

REFERENCE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "images" / "reference"
REFERENCE_NAMES = ("face.jpg", "photo.jpg", "santa.jpg")
PRESETS = ("coarse", "fine", "crosshatch-grid")
DPI = 96
MAX_RESOLUTION = 384
SEED = 42
DARK_TOLERANCE_PX = 3
PEN_WIDTH_MM = 0.3


@dataclass(frozen=True, slots=True)
class Readability:
    """How closely the plotted ink follows the dark parts of the source."""

    dark_recall: float
    ink_precision: float
    coverage_width: float
    coverage_height: float
    coverage_area: float


@dataclass(frozen=True, slots=True)
class SquaresReport:
    """Readability, baselines and cost of one image drawn by one squares preset."""

    reference: str
    preset: str
    placement: tuple[float, float, float, float]
    paper_size: tuple[float, float]
    stroke_count: int
    algorithm: Readability
    blank: Readability
    random: Readability
    cost: PlotCost
    geometry_failures: tuple[str, ...]


def dark_region_mask(
    original_crop: Image.Image,
    tolerance_px: int = DARK_TOLERANCE_PX,
) -> NDArray[np.bool_]:
    """Return the source's dark pixels dilated by the pen-placement tolerance.

    A 0.3 mm pen at the gate's 96/25.4 px/mm draws a line roughly one pixel wide;
    three simulator pixels (about 0.8 mm) allow for the grid angle and antialiasing
    while still rejecting ink in clearly light areas of the photo.
    """
    greyscale = np.asarray(original_crop.convert("L"))
    dark = greyscale < INK_CUTOFF
    diameter = 2 * tolerance_px + 1
    return binary_dilation(dark, structure=np.ones((diameter, diameter), dtype=bool))


def readability(
    plot: Image.Image,
    original: Image.Image,
    placement: tuple[float, float, float, float],
    points: Sequence[tuple[float, float]],
) -> Readability:
    """Measure ink near dark source pixels and the stroke extent of one plot."""
    crop = placement_crop(plot.size, placement)
    original_crop = original.resize(
        (crop[2] - crop[0], crop[3] - crop[1]), Image.Resampling.LANCZOS
    )
    mask = ink_mask(plot, crop)
    near_dark = dark_region_mask(original_crop)
    supported = int(np.count_nonzero(mask & near_dark))
    dark_pixels = int(np.count_nonzero(near_dark))
    ink_pixels = int(np.count_nonzero(mask))
    recall = supported / dark_pixels if dark_pixels else 0.0
    precision = supported / ink_pixels if ink_pixels else 0.0
    width, height, area = coverage_fractions(points, placement)
    return Readability(recall, precision, width, height, area)


def convert_preset(image_path: Path, preset: str, output: Path) -> None:
    """Convert one reference with a qualified Sketch Squares preset via the CLI."""
    result = CliRunner().invoke(
        cli_main,
        [
            "convert",
            # Gates measure the algorithm itself; the ink coverage cap is tested separately.
            "--max-coverage",
            "1",
            str(image_path),
            "-o",
            str(output),
            "--pfm",
            f"sketch_squares:{preset}",
            "-s",
            f"seed={SEED}",
            "--paper",
            "a4",
            "--pen",
            str(PEN_WIDTH_MM),
            "--dpi",
            str(DPI),
            "--max-resolution",
            str(MAX_RESOLUTION),
            "--no-vpype",
            "--quiet",
        ],
        env={"XDG_CONFIG_HOME": str(output.parent / "config")},
    )
    if result.exit_code != 0:
        raise RuntimeError(
            f"penpath convert failed for {image_path.name}/{preset}: {result.output}"
        )


def measure_conversion(image_path: Path, preset: str, svg_path: Path) -> SquaresReport:
    """Measure an exported Sketch Squares SVG against its source and two baselines."""
    with Image.open(image_path) as opened:
        original = opened.convert("RGB")
    placement = get_image_placement(svg_path, original.size)
    placement_tuple = (placement.x, placement.y, placement.width, placement.height)
    paper_size = get_svg_paper_size(svg_path) or (PAPER.width_mm, PAPER.height_mm)

    strokes = parse_svg_strokes(svg_path)
    algorithm_points, algorithm_plot = simulate_svg(svg_path, paper_size)
    algorithm = readability(algorithm_plot, original, placement_tuple, algorithm_points)

    work_dir = svg_path.parent
    blank_svg = work_dir / f"{svg_path.stem}_blank.svg"
    write_blank_svg(blank_svg, PAPER, placement_tuple)
    blank_points, blank_plot = simulate_svg(blank_svg, paper_size)
    blank = readability(blank_plot, original, placement_tuple, blank_points)

    random_svg = work_dir / f"{svg_path.stem}_random.svg"
    write_random_svg(random_svg, original.size, placement_tuple, len(strokes), SEED)
    random_points, random_plot = simulate_svg(random_svg, paper_size)
    random_drawing = readability(random_plot, original, placement_tuple, random_points)

    return SquaresReport(
        reference=image_path.name,
        preset=preset,
        placement=placement_tuple,
        paper_size=paper_size,
        stroke_count=len(strokes),
        algorithm=algorithm,
        blank=blank,
        random=random_drawing,
        cost=plot_cost(strokes),
        geometry_failures=geometry_problems(strokes, paper_size),
    )


def measure(image_path: Path, preset: str, work_dir: Path) -> SquaresReport:
    """Convert one image with one preset and measure the result."""
    work_dir.mkdir(parents=True, exist_ok=True)
    svg_path = work_dir / f"{image_path.stem}_{preset}.svg"
    convert_preset(image_path, preset, svg_path)
    return measure_conversion(image_path, preset, svg_path)


def format_measurement_table(reports: Sequence[SquaresReport]) -> str:
    """Return a plain-text table of every measured Sketch Squares gate value."""
    header = (
        f"{'image':<11} {'preset':<17} {'mode':<10} {'recall':>7} {'prec':>7} "
        f"{'cov W':>7} {'cov H':>7} {'bbox':>7} {'strokes':>8} {'mm':>10} "
        f"{'tiny':>6} {'tiny %':>7}"
    )
    rows = [
        "Sketch Squares gate: qualified presets, A4, one 0.3 mm pen, seed "
        f"{SEED}, working image {MAX_RESOLUTION} px, dark tolerance {DARK_TOLERANCE_PX} px",
        header,
        "-" * len(header),
    ]
    for report in reports:
        for mode, values in (
            ("algorithm", report.algorithm),
            ("blank", report.blank),
            ("random", report.random),
        ):
            cost = report.cost
            rows.append(
                f"{report.reference:<11} {report.preset:<17} {mode:<10} "
                f"{values.dark_recall:>7.3f} {values.ink_precision:>7.3f} "
                f"{values.coverage_width:>7.3f} {values.coverage_height:>7.3f} "
                f"{values.coverage_area:>7.3f} {report.stroke_count:>8d} "
                f"{cost.length_mm:>10.1f} {cost.tiny_segments:>6d} "
                f"{cost.tiny_fraction:>7.3f}"
            )
    return "\n".join(rows)


def print_measurement_table(reports: Sequence[SquaresReport]) -> None:
    """Print the measurement table to stdout without pytest capture noise."""
    click.echo(format_measurement_table(reports))


def main() -> None:
    """Convert and measure every reference with every preset, printing the table."""
    work_dir = Path("/tmp/sketch-squares-gate")
    reports = [
        measure(REFERENCE_DIR / reference, preset, work_dir / reference)
        for reference in REFERENCE_NAMES
        for preset in PRESETS
    ]
    print_measurement_table(reports)


__all__ = [
    "DARK_TOLERANCE_PX",
    "DPI",
    "MAX_RESOLUTION",
    "PEN_WIDTH_MM",
    "PRESETS",
    "REFERENCE_DIR",
    "REFERENCE_NAMES",
    "SEED",
    "Readability",
    "SquaresReport",
    "convert_preset",
    "dark_region_mask",
    "format_measurement_table",
    "measure",
    "measure_conversion",
    "print_measurement_table",
    "readability",
]


if __name__ == "__main__":
    main()
