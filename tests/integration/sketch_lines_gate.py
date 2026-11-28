"""Measurement harness for the Sketch Lines likeness gate (LUC-47).

Runs the same image → SVG → strokes → simulation path as ``penpath convert``
and ``penpath evaluate``, then measures SSIM, coverage, ink spread and tone.
The gate thresholds themselves are recorded in ``docs/TESTING.md``; this
module only produces the numbers they are justified from.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING

import click
import numpy as np
from click.testing import CliRunner
from numpy.typing import NDArray
from PIL import Image, ImageFilter
from scipy.stats import spearmanr
from shapely import LineString

from penpath.cli.main import main
from penpath.core import (
    ImagePlacement,
    compute_likeness,
    get_image_placement,
    get_svg_paper_size,
    parse_svg_strokes,
    simulate_plot,
)
from penpath.core.models import Paper, Pen
from penpath.core.output.svg import export_svg

if TYPE_CHECKING:
    from collections.abc import Sequence

REFERENCE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "images" / "reference"
REFERENCE_NAMES = ("circle.png", "gradient.png", "sphere.png", "face.jpg", "photo.jpg")
SEED = 42
PX_PER_MM = 96 / 25.4
GRID_CELLS = 4
READABILITY_CELLS = 8
DARK_TILE_DARKNESS = 0.6
DARK_TILE_TEXTURE = 20.0
RANK_MIN = 0.75
DARK_TILE_INK_MIN = 0.20
DARK_TILE_INK_MAX = 0.92
DARK_DECILE_QUANTILE = 0.10
DARK_DECILE_INK_MAX = 0.85
WHITE_THRESHOLD = 0.92
WHITE_SAMPLE_STEP_MM = 0.1
BORDER_EXCLUSION_MM = 1.0
_WHITE = 255.0
INK_CUTOFF = 128
PAPER = Paper(name="a4", width_mm=210.0, height_mm=297.0, margin_mm=10.0)
PEN = Pen(name="fine", width_mm=0.3, color="#000000")


@dataclass(frozen=True, slots=True)
class PlotMeasures:
    """All measurements collected for one drawing of one reference image."""

    ssim: float
    coverage_width: float
    coverage_height: float
    coverage_area: float
    ink_spread_min: float
    ink_spread_max: float
    tone_dark_density: float
    tone_light_density: float
    tone_ratio: float
    rank_correlation: float
    dark_textured_ink_max: float
    dark_textured_tiles: int
    darkest_decile_ink: float


@dataclass(frozen=True, slots=True)
class GateReport:
    """Measurements for an image and its blank, random and ideal baselines."""

    reference: str
    svg_path: Path
    placement: ImagePlacement
    paper_size: tuple[float, float]
    stroke_count: int
    algorithm: PlotMeasures
    blank: PlotMeasures
    random: PlotMeasures
    ideal: PlotMeasures
    white_ink_share: float


def white_ink_share(
    svg_path: Path,
    original: Image.Image,
    placement: tuple[float, float, float, float],
) -> float:
    """Return the share of simulated stroke length drawn on near-white source pixels.

    Stroke polylines are sampled every ``WHITE_SAMPLE_STEP_MM`` millimetres and
    mapped from page millimetres to source pixels through ``placement``. Samples
    within ``BORDER_EXCLUSION_MM`` of the placement rectangle are skipped, so
    the measure concerns ink inside the image rather than its edge.
    """
    x_mm, y_mm, width_mm, height_mm = placement
    gray = np.asarray(original.convert("L"), dtype=np.float64)
    source_h, source_w = gray.shape
    sampled = 0
    on_white = 0
    for stroke in parse_svg_strokes(svg_path):
        for (x0, y0), (x1, y1) in pairwise(stroke.polyline):
            length = math.hypot(x1 - x0, y1 - y0)
            steps = max(1, math.ceil(length / WHITE_SAMPLE_STEP_MM))
            for index in range(steps + 1):
                x = x0 + (x1 - x0) * index / steps
                y = y0 + (y1 - y0) * index / steps
                if not (
                    x_mm + BORDER_EXCLUSION_MM < x < x_mm + width_mm - BORDER_EXCLUSION_MM
                    and y_mm + BORDER_EXCLUSION_MM < y < y_mm + height_mm - BORDER_EXCLUSION_MM
                ):
                    continue
                sx = min(source_w - 1, max(0, int((x - x_mm) / width_mm * source_w)))
                sy = min(source_h - 1, max(0, int((y - y_mm) / height_mm * source_h)))
                sampled += 1
                if gray[sy, sx] / _WHITE > WHITE_THRESHOLD:
                    on_white += 1
    return on_white / sampled if sampled else 0.0


def placement_crop(
    image_size: tuple[int, int],
    placement: tuple[float, float, float, float],
    px_per_mm: float = PX_PER_MM,
) -> tuple[int, int, int, int]:
    """Return the pixel crop of a placement, with compute_likeness's rounding."""
    x_mm, y_mm, width_mm, height_mm = placement
    image_width, image_height = image_size
    left = round(x_mm * px_per_mm)
    top = round(y_mm * px_per_mm)
    width = round(width_mm * px_per_mm)
    height = round(height_mm * px_per_mm)
    left = max(0, min(left, image_width - 1))
    top = max(0, min(top, image_height - 1))
    width = max(1, min(width, image_width - left))
    height = max(1, min(height, image_height - top))
    return left, top, left + width, top + height


def ink_mask(
    plot: Image.Image,
    crop: tuple[int, int, int, int],
    cutoff: int = INK_CUTOFF,
) -> NDArray[np.bool_]:
    """Return the dark pixels of a simulated plot inside a placement crop."""
    greyscale = np.asarray(plot.convert("L").crop(crop))
    return greyscale < cutoff


def darkest_decile_ink(
    mask: NDArray[np.bool_],
    original_crop: Image.Image,
) -> float:
    """Return the simulated ink share over the darkest source-tone pixels.

    The darkest decile is the source crop's pixels at or below its 0.10
    luminance quantile, using the same ``<=`` rule as :func:`tone_metrics`.
    The returned value is the mean of the simulated ink mask over those
    pixels: 1.0 is a solid-filled dark mass, 0.0 leaves all of it blank.
    """
    greyscale = np.asarray(original_crop.convert("L"), dtype=np.float64)
    darkest = greyscale <= np.quantile(greyscale, DARK_DECILE_QUANTILE)
    return float(mask[darkest].mean()) if darkest.any() else 0.0


def coverage_fractions(
    points: Sequence[tuple[float, float]],
    placement: tuple[float, float, float, float],
) -> tuple[float, float, float]:
    """Return covered width, height and area fractions of the placement rectangle."""
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


def ink_spread(mask: NDArray[np.bool_]) -> tuple[float, float]:
    """Return the smallest and largest ink share across a 4x4 grid."""
    height, width = mask.shape
    total = int(mask.sum())
    if total == 0:
        return 0.0, 0.0
    shares = []
    for row in range(GRID_CELLS):
        for column in range(GRID_CELLS):
            cell = mask[
                row * height // GRID_CELLS : (row + 1) * height // GRID_CELLS,
                column * width // GRID_CELLS : (column + 1) * width // GRID_CELLS,
            ]
            shares.append(int(cell.sum()) / total)
    return min(shares), max(shares)


def tone_metrics(
    mask: NDArray[np.bool_],
    original_crop: Image.Image,
) -> tuple[float, float, float]:
    """Return ink density in the darkest and lightest quarters and their ratio."""
    greyscale = np.asarray(original_crop.convert("L"), dtype=np.float32)
    dark = greyscale <= np.quantile(greyscale, 0.25)
    light = greyscale >= np.quantile(greyscale, 0.75)
    dark_density = float(mask[dark].mean()) if dark.any() else 0.0
    light_density = float(mask[light].mean()) if light.any() else 0.0
    smoothing = 1.0 / greyscale.size
    ratio = (dark_density + smoothing) / (light_density + smoothing)
    return dark_density, light_density, float(ratio)


def tile_readability(
    mask: NDArray[np.bool_],
    original_crop: Image.Image,
    cells: int = READABILITY_CELLS,
) -> tuple[float, float, int]:
    """Rank tile ink against tile darkness and cap ink in textured dark tiles.

    Ink follows the source when darker tiles carry more ink; the Spearman
    rank correlation is zero for a blank or randomly scribbled page. A dark
    tile with a high source standard deviation is textured: a plot that fills
    it solid has lost the white gaps a pen needs to show the texture.
    """
    greyscale = np.asarray(original_crop.convert("L"), dtype=np.float64)
    height, width = greyscale.shape
    darknesses: list[float] = []
    textures: list[float] = []
    inks: list[float] = []
    for row in range(cells):
        for column in range(cells):
            tile = (
                slice(row * height // cells, (row + 1) * height // cells),
                slice(column * width // cells, (column + 1) * width // cells),
            )
            darknesses.append(float(np.mean((_WHITE - greyscale[tile]) / _WHITE)))
            textures.append(float(np.std(greyscale[tile])))
            inks.append(float(mask[tile].mean()))
    if np.ptp(darknesses) == 0 or np.ptp(inks) == 0:
        correlation = 0.0
    else:
        measured = float(spearmanr(darknesses, inks).statistic)
        correlation = measured if math.isfinite(measured) else 0.0
    textured_dark = [
        ink
        for darkness, texture, ink in zip(darknesses, textures, inks, strict=True)
        if darkness >= DARK_TILE_DARKNESS and texture >= DARK_TILE_TEXTURE
    ]
    return correlation, max(textured_dark, default=0.0), len(textured_dark)


def measure_plot(
    plot: Image.Image,
    original: Image.Image,
    placement: tuple[float, float, float, float],
    points: Sequence[tuple[float, float]] | None = None,
) -> PlotMeasures:
    """Measure one simulated (or ideal) plot against the original image."""
    crop = placement_crop(plot.size, placement)
    crop_width = crop[2] - crop[0]
    crop_height = crop[3] - crop[1]
    original_crop = original.resize((crop_width, crop_height), Image.Resampling.LANCZOS)
    mask = ink_mask(plot, crop)
    coverage = coverage_fractions(points, placement) if points is not None else (1.0, 1.0, 1.0)
    spread = ink_spread(mask)
    dark, light, ratio = tone_metrics(mask, original_crop)
    correlation, dark_ink_max, dark_tiles = tile_readability(mask, original_crop)
    decile_ink = darkest_decile_ink(mask, original_crop)
    ssim = compute_likeness(plot, original, placement, dpi_px_per_mm=PX_PER_MM)
    return PlotMeasures(
        ssim=ssim,
        coverage_width=coverage[0],
        coverage_height=coverage[1],
        coverage_area=coverage[2],
        ink_spread_min=spread[0],
        ink_spread_max=spread[1],
        tone_dark_density=dark,
        tone_light_density=light,
        tone_ratio=ratio,
        rank_correlation=correlation,
        dark_textured_ink_max=dark_ink_max,
        dark_textured_tiles=dark_tiles,
        darkest_decile_ink=decile_ink,
    )


def make_ideal_plot(
    original: Image.Image,
    plot_size: tuple[int, int],
    placement: tuple[float, float, float, float],
    blur_radius: float = 1.0,
) -> Image.Image:
    """Return the image tone-mapped to the simulator's two ink levels."""
    ideal = Image.new("RGB", plot_size, "white")
    crop = placement_crop(plot_size, placement)
    tone = original.convert("L").resize(
        (crop[2] - crop[0], crop[3] - crop[1]),
        Image.Resampling.LANCZOS,
    )
    if blur_radius > 0:
        tone = tone.filter(ImageFilter.GaussianBlur(blur_radius))
    ink_levels = tone.convert("1", dither=Image.Dither.FLOYDSTEINBERG).convert("L")
    ideal.paste(Image.merge("RGB", (ink_levels, ink_levels, ink_levels)), (crop[0], crop[1]))
    return ideal


def make_solid_plot(
    plot_size: tuple[int, int],
    placement: tuple[float, float, float, float],
    px_per_mm: float = PX_PER_MM,
) -> Image.Image:
    """Return a plot whose placement rectangle is one solid black mass."""
    plot = Image.new("RGB", plot_size, "white")
    left, top, right, bottom = placement_crop(plot_size, placement, px_per_mm)
    plot.paste(Image.new("RGB", (right - left, bottom - top), "black"), (left, top))
    return plot


def write_blank_svg(
    path: Path,
    paper: Paper,
    placement: tuple[float, float, float, float],
) -> None:
    """Write an SVG with the same page and placement metadata but no strokes."""
    viewbox_width = paper.width_mm * 96 / 25.4
    viewbox_height = paper.height_mm * 96 / 25.4
    x_mm, y_mm, width_mm, height_mm = placement
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:penpath="http://penpath.org/ns/penpath" '
        f'width="{paper.width_mm}mm" height="{paper.height_mm}mm" '
        f'viewBox="0 0 {viewbox_width} {viewbox_height}">'
        "<metadata><penpath:image-placement "
        f'x="{x_mm:.4f}" y="{y_mm:.4f}" width="{width_mm:.4f}" height="{height_mm:.4f}"/>'
        "</metadata></svg>",
        encoding="utf-8",
    )


def write_random_svg(
    path: Path,
    image_size: tuple[int, int],
    placement: tuple[float, float, float, float],
    stroke_count: int,
    seed: int,
) -> None:
    """Write a seeded set of random strokes with the same count inside the placement."""
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
        image_dpi=300,
        image_placement=placement,
        image_size_px=image_size,
    )


def simulate_svg(
    svg_path: Path,
    paper_size: tuple[float, float],
) -> tuple[list[tuple[float, float]], Image.Image]:
    """Parse an SVG and simulate it exactly as ``penpath evaluate`` does."""
    strokes = parse_svg_strokes(svg_path)
    points = [point for stroke in strokes for point in stroke.polyline]
    plot = simulate_plot(strokes, paper_size[0], paper_size[1], dpi_px_per_mm=PX_PER_MM)
    return points, plot


def measure_reference(image_path: Path, work_dir: Path, seed: int = SEED) -> GateReport:
    """Run the default pipeline on one image and measure it with three baselines."""
    work_dir.mkdir(parents=True, exist_ok=True)
    svg_path = work_dir / "plot.svg"
    result = CliRunner().invoke(
        main,
        [
            "convert",
            # Gates measure the algorithm itself; the ink coverage cap is tested separately.
            "--max-coverage",
            "1",
            str(image_path),
            "-o",
            str(svg_path),
            "--pfm-setting",
            f"seed={seed}",
        ],
        env={"XDG_CONFIG_HOME": str(work_dir / "config")},
    )
    if result.exit_code != 0:
        raise RuntimeError(f"penpath convert failed for {image_path.name}: {result.output}")
    return measure_svg(image_path, svg_path, work_dir, seed)


def measure_svg(image_path: Path, svg_path: Path, work_dir: Path, seed: int = SEED) -> GateReport:
    """Measure an already exported SVG against its image and the three baselines."""
    with Image.open(image_path) as opened:
        original = opened.convert("RGB")
    image_size = original.size

    placement = get_image_placement(svg_path, image_size)
    paper_size = get_svg_paper_size(svg_path) or (PAPER.width_mm, PAPER.height_mm)
    placement_tuple = (placement.x, placement.y, placement.width, placement.height)

    algorithm_points, algorithm_plot = simulate_svg(svg_path, paper_size)
    algorithm = measure_plot(algorithm_plot, original, placement_tuple, algorithm_points)

    blank_svg = work_dir / "blank.svg"
    write_blank_svg(blank_svg, PAPER, placement_tuple)
    blank_points, blank_plot = simulate_svg(blank_svg, paper_size)
    blank = measure_plot(blank_plot, original, placement_tuple, blank_points)

    random_svg = work_dir / "random.svg"
    stroke_count = len(parse_svg_strokes(svg_path))
    write_random_svg(random_svg, image_size, placement_tuple, stroke_count, seed)
    random_points, random_plot = simulate_svg(random_svg, paper_size)
    random_drawing = measure_plot(random_plot, original, placement_tuple, random_points)

    ideal_plot_image = make_ideal_plot(original, algorithm_plot.size, placement_tuple)
    ideal = measure_plot(ideal_plot_image, original, placement_tuple)

    return GateReport(
        reference=image_path.name,
        svg_path=svg_path,
        placement=placement,
        paper_size=paper_size,
        stroke_count=stroke_count,
        algorithm=algorithm,
        blank=blank,
        random=random_drawing,
        ideal=ideal,
        white_ink_share=white_ink_share(svg_path, original, placement_tuple),
    )


def measure_all(work_dir: Path, seed: int = SEED) -> list[GateReport]:
    """Measure every reference image, writing intermediate SVGs under work_dir."""
    return [
        measure_reference(REFERENCE_DIR / name, work_dir / Path(name).stem, seed)
        for name in REFERENCE_NAMES
    ]


def format_measurement_table(reports: Sequence[GateReport]) -> str:
    """Return a plain-text table of all measurements."""
    header = (
        f"{'image':<13} {'mode':<10} {'SSIM':>7} {'cov W':>7} {'cov H':>7} {'bbox':>7} "
        f"{'ink min':>8} {'ink max':>8} {'tone':>7} {'rank':>7} "
        f"{'darkInk':>8} {'decInk':>7} {'tiles':>5} {'white%':>7} {'strokes':>8}"
    )
    rows = [
        "Sketch Lines likeness gate: default settings, fixed seed "
        f"{SEED}, recorded placement rectangles",
        header,
        "-" * len(header),
    ]
    for report in reports:
        for mode, measures in (
            ("algorithm", report.algorithm),
            ("blank", report.blank),
            ("random", report.random),
            ("ideal", report.ideal),
        ):
            rows.append(
                f"{report.reference:<13} {mode:<10} {measures.ssim:>7.4f} "
                f"{measures.coverage_width:>7.3f} {measures.coverage_height:>7.3f} "
                f"{measures.coverage_area:>7.3f} {measures.ink_spread_min:>8.4f} "
                f"{measures.ink_spread_max:>8.4f} {measures.tone_ratio:>7.2f} "
                f"{measures.rank_correlation:>7.3f} {measures.dark_textured_ink_max:>8.3f} "
                f"{measures.darkest_decile_ink:>7.3f} "
                f"{measures.dark_textured_tiles:>5d} {report.white_ink_share * 100:>6.3f} "
                f"{report.stroke_count:>8d}"
            )
    return "\n".join(rows)


def print_measurement_table(reports: Sequence[GateReport]) -> None:
    """Print the measurement table to stdout without pytest capture noise."""
    click.echo(format_measurement_table(reports))


def finite_values(measures: PlotMeasures) -> tuple[float, ...]:
    """Return every measurement as a float, for finiteness checks."""
    return (
        measures.ssim,
        measures.coverage_width,
        measures.coverage_height,
        measures.coverage_area,
        measures.ink_spread_min,
        measures.ink_spread_max,
        measures.tone_dark_density,
        measures.tone_light_density,
        measures.tone_ratio,
        measures.rank_correlation,
        measures.dark_textured_ink_max,
        measures.darkest_decile_ink,
    )


def all_finite(measures: PlotMeasures) -> bool:
    """Report whether every measurement is a finite number."""
    return all(math.isfinite(value) for value in finite_values(measures))


__all__ = [
    "BORDER_EXCLUSION_MM",
    "DARK_DECILE_INK_MAX",
    "DARK_DECILE_QUANTILE",
    "DARK_TILE_DARKNESS",
    "DARK_TILE_INK_MAX",
    "DARK_TILE_INK_MIN",
    "DARK_TILE_TEXTURE",
    "GRID_CELLS",
    "INK_CUTOFF",
    "PX_PER_MM",
    "RANK_MIN",
    "READABILITY_CELLS",
    "REFERENCE_DIR",
    "REFERENCE_NAMES",
    "SEED",
    "WHITE_SAMPLE_STEP_MM",
    "WHITE_THRESHOLD",
    "GateReport",
    "PlotMeasures",
    "all_finite",
    "coverage_fractions",
    "darkest_decile_ink",
    "format_measurement_table",
    "ink_mask",
    "ink_spread",
    "make_ideal_plot",
    "make_solid_plot",
    "measure_all",
    "measure_plot",
    "measure_reference",
    "measure_svg",
    "placement_crop",
    "print_measurement_table",
    "simulate_svg",
    "tile_readability",
    "tone_metrics",
    "white_ink_share",
    "write_blank_svg",
    "write_random_svg",
]
