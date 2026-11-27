"""Measurement harness for the Contour readability and plot-cost gate (LUC-146).

Runs the real ``penpath convert`` CLI for every built-in contour preset on the
three portrait/photo references, then measures how closely the plotted contour
points follow a Canny edge of the source image and what the plot costs in
strokes and millimetres. The thresholds are recorded in ``docs/TESTING.md``;
this module only produces the numbers they are justified from.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import click
import numpy as np
from click.testing import CliRunner
from numpy.typing import NDArray
from PIL import Image
from scipy.ndimage import binary_dilation
from shapely import LineString
from skimage.color import rgb2gray
from skimage.feature import canny

from penpath.cli.main import main as cli_main
from penpath.core import get_image_placement, get_svg_paper_size, parse_svg_strokes

if TYPE_CHECKING:
    from collections.abc import Sequence

    from penpath.core.simulation import PenStroke

REFERENCE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "images" / "reference"
REFERENCE_NAMES = ("face.jpg", "photo.jpg", "santa.jpg")
PRESETS = ("contour_portrait", "contour_silhouette")
DPI = 96
MAX_RESOLUTION = 512
EDGE_TOLERANCE_PX = 2
TINY_SEGMENT_MM = 0.5
PENPATH_NAMESPACE = "http://penpath.org/ns/penpath"


@dataclass(frozen=True, slots=True)
class PlotCost:
    """Stroke budget of one drawing, measured from the exported SVG."""

    strokes: int
    points: int
    length_mm: float
    tiny_segments: int
    tiny_fraction: float


@dataclass(frozen=True, slots=True)
class ContourReport:
    """Readability and cost of one reference image drawn by one contour preset."""

    reference: str
    preset: str
    placement: tuple[float, float, float, float]
    paper_size: tuple[float, float]
    stroke_count: int
    edge_alignment: float
    matched_points: int
    sampled_points: int
    coverage_width: float
    coverage_height: float
    coverage_area: float
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
    raise ValueError(f"No working image size in {svg_path.name}; cannot align contour points")


def edge_mask(image: Image.Image, tolerance_px: int = EDGE_TOLERANCE_PX) -> NDArray[np.bool_]:
    """Return Canny edges dilated by the allowed point-to-edge tolerance."""
    grey = rgb2gray(np.asarray(image.convert("RGB"), dtype=np.float64) / 255.0)
    edges = canny(grey, sigma=1.0, low_threshold=0.1, high_threshold=0.2)
    if tolerance_px <= 0:
        return edges
    diameter = 2 * tolerance_px + 1
    return binary_dilation(edges, structure=np.ones((diameter, diameter), dtype=bool))


def points_to_pixels(
    points: Sequence[tuple[float, float]],
    placement: tuple[float, float, float, float],
    image_size: tuple[int, int],
) -> set[tuple[int, int]]:
    """Map millimetre stroke points back to distinct pixels of the working image."""
    x_mm, y_mm, width_mm, height_mm = placement
    pixels: set[tuple[int, int]] = set()
    if width_mm <= 0 or height_mm <= 0:
        return pixels
    for x, y in points:
        column = round((x - x_mm) / width_mm * (image_size[0] - 1))
        row = round((y - y_mm) / height_mm * (image_size[1] - 1))
        if 0 <= column < image_size[0] and 0 <= row < image_size[1]:
            pixels.add((row, column))
    return pixels


def edge_alignment(
    points: Sequence[tuple[float, float]],
    placement: tuple[float, float, float, float],
    image_size: tuple[int, int],
    mask: NDArray[np.bool_],
) -> tuple[float, int, int]:
    """Return the share of distinct stroke pixels lying on or near a Canny edge.

    An empty drawing samples no pixels and scores zero, so this measure cannot
    reward a blank page.
    """
    pixels = points_to_pixels(points, placement, image_size)
    if not pixels:
        return 0.0, 0, 0
    matched = sum(bool(mask[row, column]) for row, column in pixels)
    return matched / len(pixels), matched, len(pixels)


def coverage_fractions(
    points: Sequence[tuple[float, float]],
    placement: tuple[float, float, float, float],
) -> tuple[float, float, float]:
    """Return covered width, height and area as fractions of the placement."""
    x_mm, y_mm, width_mm, height_mm = placement
    if not points or width_mm <= 0 or height_mm <= 0:
        return 0.0, 0.0, 0.0
    left = max(x_mm, min(point[0] for point in points))
    right = min(x_mm + width_mm, max(point[0] for point in points))
    top = max(y_mm, min(point[1] for point in points))
    bottom = min(y_mm + height_mm, max(point[1] for point in points))
    width_fraction = max(0.0, right - left) / width_mm
    height_fraction = max(0.0, bottom - top) / height_mm
    return width_fraction, height_fraction, width_fraction * height_fraction


def geometry_problems(
    strokes: Sequence[PenStroke],
    paper_size: tuple[float, float],
    tolerance_mm: float = 0.01,
) -> tuple[str, ...]:
    """Return the invalid, off-page or zero-length strokes of a drawing."""
    problems: list[str] = []
    page_width, page_height = paper_size
    for number, stroke in enumerate(strokes):
        line = LineString(stroke.polyline)
        if any(
            not (-tolerance_mm <= x <= page_width + tolerance_mm)
            or not (-tolerance_mm <= y <= page_height + tolerance_mm)
            for x, y in stroke.polyline
        ):
            problems.append(f"stroke {number} is outside the page")
        if any(
            math.hypot(end[0] - start[0], end[1] - start[1]) <= 0.0
            for start, end in zip(stroke.polyline, stroke.polyline[1:], strict=False)
        ):
            problems.append(f"stroke {number} has a zero-length segment")
        if not line.is_valid:
            problems.append(f"stroke {number} is invalid")
    return tuple(problems)


def plot_cost(strokes: Sequence[PenStroke]) -> PlotCost:
    """Count strokes, pen-down length and segments too short to plot cleanly."""
    lengths: list[float] = []
    for stroke in strokes:
        for start, end in zip(stroke.polyline, stroke.polyline[1:], strict=False):
            lengths.append(math.hypot(end[0] - start[0], end[1] - start[1]))
    tiny = sum(1 for length in lengths if length < TINY_SEGMENT_MM)
    return PlotCost(
        strokes=len(strokes),
        points=sum(len(stroke.polyline) for stroke in strokes),
        length_mm=math.fsum(lengths),
        tiny_segments=tiny,
        tiny_fraction=tiny / len(lengths) if lengths else 0.0,
    )


def convert_preset(
    image_path: Path,
    preset: str,
    output: Path,
) -> None:
    """Convert one reference with a built-in contour preset through the real CLI."""
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
            "a4",
            "--pen",
            "0.3",
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


def measure_conversion(image_path: Path, preset: str, svg_path: Path) -> ContourReport:
    """Measure an exported contour SVG against its source image."""
    with Image.open(image_path) as opened:
        original = opened.convert("RGB")
    working_size = working_image_size(svg_path)
    working = original.resize(working_size, Image.Resampling.LANCZOS)
    mask = edge_mask(working)

    placement = get_image_placement(svg_path, original.size)
    placement_tuple = (placement.x, placement.y, placement.width, placement.height)
    paper_size = get_svg_paper_size(svg_path) or (210.0, 297.0)
    strokes = parse_svg_strokes(svg_path)
    points = [point for stroke in strokes for point in stroke.polyline]
    alignment, matched, sampled = edge_alignment(points, placement_tuple, working_size, mask)
    coverage = coverage_fractions(points, placement_tuple)
    return ContourReport(
        reference=image_path.name,
        preset=preset,
        placement=placement_tuple,
        paper_size=paper_size,
        stroke_count=len(strokes),
        edge_alignment=alignment,
        matched_points=matched,
        sampled_points=sampled,
        coverage_width=coverage[0],
        coverage_height=coverage[1],
        coverage_area=coverage[2],
        cost=plot_cost(strokes),
        geometry_failures=geometry_problems(strokes, paper_size),
    )


def measure(image_path: Path, preset: str, work_dir: Path) -> ContourReport:
    """Convert one image with one preset and measure the result."""
    work_dir.mkdir(parents=True, exist_ok=True)
    svg_path = work_dir / f"{image_path.stem}_{preset}.svg"
    convert_preset(image_path, preset, svg_path)
    return measure_conversion(image_path, preset, svg_path)


def format_measurement_table(reports: Sequence[ContourReport]) -> str:
    """Return a plain-text table of every measured contour gate value."""
    header = (
        f"{'image':<11} {'preset':<20} {'strokes':>7} {'points':>7} {'length mm':>10} "
        f"{'tiny':>6} {'tiny %':>7} {'edge':>6} {'matched':>8} {'cov W':>6} "
        f"{'cov H':>6} {'bbox':>6}"
    )
    rows = [
        "Contour gate: built-in presets, A4, one 0.3 mm pen, "
        f"working image {MAX_RESOLUTION} px, Canny tolerance {EDGE_TOLERANCE_PX} px",
        header,
        "-" * len(header),
    ]
    for report in reports:
        rows.append(
            f"{report.reference:<11} {report.preset:<20} {report.cost.strokes:>7d} "
            f"{report.cost.points:>7d} {report.cost.length_mm:>10.1f} "
            f"{report.cost.tiny_segments:>6d} {report.cost.tiny_fraction:>7.3f} "
            f"{report.edge_alignment:>6.3f} "
            f"{report.matched_points:>4d}/{report.sampled_points:<3d} "
            f"{report.coverage_width:>6.3f} {report.coverage_height:>6.3f} "
            f"{report.coverage_area:>6.3f}"
        )
    return "\n".join(rows)


def print_measurement_table(reports: Sequence[ContourReport]) -> None:
    """Print the measurement table to stdout without pytest capture noise."""
    click.echo(format_measurement_table(reports))


def main() -> None:
    """Convert and measure every reference with every preset, printing the table."""
    work_dir = Path("/tmp/contour-gate")
    reports = [
        measure(REFERENCE_DIR / reference, preset, work_dir / reference)
        for reference in REFERENCE_NAMES
        for preset in PRESETS
    ]
    print_measurement_table(reports)


__all__ = [
    "DPI",
    "EDGE_TOLERANCE_PX",
    "MAX_RESOLUTION",
    "PRESETS",
    "REFERENCE_DIR",
    "REFERENCE_NAMES",
    "TINY_SEGMENT_MM",
    "ContourReport",
    "PlotCost",
    "convert_preset",
    "coverage_fractions",
    "edge_alignment",
    "edge_mask",
    "format_measurement_table",
    "geometry_problems",
    "measure",
    "measure_conversion",
    "plot_cost",
    "points_to_pixels",
    "print_measurement_table",
    "working_image_size",
]


if __name__ == "__main__":
    main()
