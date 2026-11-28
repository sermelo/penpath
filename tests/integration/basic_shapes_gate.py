"""Harness for the basic-shape gate (LUC-75).

Runs the real ``penpath convert`` pipeline on each plain-text basic-shape
fixture, rendered at 400x400, and measures likeness, ink placement, tone,
machine cost and two baselines (blank page and random scribble). It also holds
the single table of enforced thresholds recorded in ``docs/TESTING.md``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import click
import numpy as np
from click.testing import CliRunner
from numpy.typing import NDArray
from PIL import Image
from sketch_lines_gate import (
    INK_CUTOFF,
    PAPER,
    PX_PER_MM,
    SEED,
    ink_mask,
    measure_plot,
    placement_crop,
    write_blank_svg,
    write_random_svg,
)

from penpath.cli.main import main
from penpath.core import (
    ImagePlacement,
    compute_machine_cost,
    get_image_placement,
    get_svg_paper_size,
    parse_svg_strokes,
    simulate_plot,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

BASIC_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "images" / "basic"
SHAPE_NAMES = (
    "black_square",
    "white_square",
    "black_disc",
    "horizontal_line",
    "checkerboard",
    "triangle",
)
RENDER_SIZE = 400
PREVIEW_WIDTH = 600
PREVIEW_PANEL = PREVIEW_WIDTH // 2


@dataclass(frozen=True, slots=True)
class ShapeMeasures:
    """All measurements collected for one drawing of one basic shape."""

    likeness: float
    ink_outside: float
    dark_coverage: float
    tone_ratio: float
    drawing_length_mm: float
    num_strokes: int
    num_lifts: int


@dataclass(frozen=True, slots=True)
class ShapeReport:
    """Measurements for a shape and its blank and random baselines."""

    shape: str
    placement: ImagePlacement
    algorithm: ShapeMeasures
    blank: ShapeMeasures
    random: ShapeMeasures


@dataclass(frozen=True, slots=True)
class ShapeThresholds:
    """Enforced floors and caps for one shape, measured with seed 42 at 400x400."""

    likeness_min: float
    ink_outside_max: float
    dark_coverage_min: float
    tone_ratio_min: float
    drawing_length_mm_max: float
    num_strokes_max: int
    num_lifts_max: int


SHAPE_THRESHOLDS: dict[str, ShapeThresholds] = {
    "black_square": ShapeThresholds(0.82, 0.10, 0.35, 2.0, 23000, 80, 80),
    "white_square": ShapeThresholds(0.14, 0.12, 0.36, 1.05, 135000, 440, 440),
    "black_disc": ShapeThresholds(0.57, 0.10, 0.36, 2.0, 60000, 200, 200),
    "horizontal_line": ShapeThresholds(0.96, 0.25, 0.30, 2.0, 3000, 12, 12),
    "checkerboard": ShapeThresholds(0.49, 0.20, 0.36, 2.0, 78000, 300, 300),
    "triangle": ShapeThresholds(0.54, 0.10, 0.36, 2.0, 67000, 220, 220),
}
NUM_STROKES_MIN = 1


@dataclass(frozen=True, slots=True)
class ThresholdViolation:
    """One enforced floor or cap that a measurement fails."""

    shape: str
    measure: str
    value: float
    bound: float
    is_floor: bool

    def __str__(self) -> str:
        symbol = ">=" if self.is_floor else "<="
        return f"{self.shape}: {self.measure} {self.value:.4f} {symbol} {self.bound:.4f}"


def _fails(value: float, bound: float, is_floor: bool) -> bool:
    return value < bound if is_floor else value > bound


def threshold_violations(shape: str, measured: ShapeMeasures) -> list[ThresholdViolation]:
    """Return every enforced threshold the measurement fails for this shape."""
    bounds = SHAPE_THRESHOLDS[shape]
    checks: tuple[tuple[str, float, float, bool], ...] = (
        ("likeness", measured.likeness, bounds.likeness_min, True),
        ("ink_outside", measured.ink_outside, bounds.ink_outside_max, False),
        ("dark_coverage", measured.dark_coverage, bounds.dark_coverage_min, True),
        ("tone_ratio", measured.tone_ratio, bounds.tone_ratio_min, True),
        (
            "drawing_length_mm",
            measured.drawing_length_mm,
            float(bounds.drawing_length_mm_max),
            False,
        ),
        ("num_strokes", float(measured.num_strokes), float(bounds.num_strokes_max), False),
        ("num_strokes", float(measured.num_strokes), float(NUM_STROKES_MIN), True),
        ("num_lifts", float(measured.num_lifts), float(bounds.num_lifts_max), False),
    )
    return [
        ThresholdViolation(shape, name, value, bound, is_floor)
        for name, value, bound, is_floor in checks
        if _fails(value, bound, is_floor)
    ]


def format_threshold_violations(violations: Sequence[ThresholdViolation]) -> str:
    """Return the violations as one line each, for assertion messages."""
    return "\n".join(str(violation) for violation in violations)


def render_fixture(pbm_path: Path, png_path: Path) -> Image.Image:
    """Render a 64x64 PBM fixture to a 400x400 PNG with nearest neighbour."""
    with Image.open(pbm_path) as opened:
        source = opened.convert("RGB")
    image = source.resize((RENDER_SIZE, RENDER_SIZE), Image.Resampling.NEAREST)
    image.save(png_path)
    return image


def shape_masks(
    plot: Image.Image,
    original: Image.Image,
    placement: tuple[float, float, float, float],
) -> tuple[NDArray[np.bool_], NDArray[np.bool_]]:
    """Return the plot's ink pixels and the original's dark pixels in its crop."""
    crop = placement_crop(plot.size, placement)
    ink = ink_mask(plot, crop)
    crop_size = (crop[2] - crop[0], crop[3] - crop[1])
    original_crop = original.resize(crop_size, Image.Resampling.LANCZOS)
    dark = np.asarray(original_crop.convert("L")) < INK_CUTOFF
    return ink, dark


def placement_metrics(ink: NDArray[np.bool_], dark: NDArray[np.bool_]) -> tuple[float, float]:
    """Return the share of ink outside the dark region and the dark region's coverage.

    A drawing with no ink reports all ink outside (1.0) and no coverage (0.0).
    """
    total_ink = int(ink.sum())
    if total_ink == 0:
        return 1.0, 0.0
    inside = int(ink[dark].sum())
    return 1.0 - inside / total_ink, inside / int(dark.sum())


def measure_svg(
    original: Image.Image,
    svg_path: Path,
    paper_size: tuple[float, float],
    placement: tuple[float, float, float, float],
) -> ShapeMeasures:
    """Measure one SVG drawing against the original shape image."""
    strokes = parse_svg_strokes(svg_path)
    plot = simulate_plot(
        strokes,
        paper_size[0],
        paper_size[1],
        dpi_px_per_mm=PX_PER_MM,
    )
    measured = measure_plot(plot, original, placement)
    ink, dark = shape_masks(plot, original, placement)
    ink_outside, dark_coverage = placement_metrics(ink, dark)
    cost = compute_machine_cost(parse_svg_strokes(svg_path, include_pen_up=True))["total"]
    return ShapeMeasures(
        likeness=measured.ssim,
        ink_outside=ink_outside,
        dark_coverage=dark_coverage,
        tone_ratio=measured.tone_ratio,
        drawing_length_mm=float(cost["drawing_length_mm"]),
        num_strokes=int(cost["num_strokes"]),
        num_lifts=int(cost["num_lifts"]),
    )


def measure_shape(shape: str, work_dir: Path, seed: int = SEED) -> ShapeReport:
    """Run the real pipeline on one basic shape and measure it with two baselines."""
    work_dir.mkdir(parents=True, exist_ok=True)
    png_path = work_dir / "shape.png"
    original = render_fixture(BASIC_DIR / f"{shape}.pbm", png_path)
    svg_path = work_dir / "plot.svg"
    result = CliRunner().invoke(
        main,
        [
            "convert",
            # Gates measure the algorithm itself; the ink coverage cap is tested separately.
            "--max-coverage",
            "1",
            str(png_path),
            "-o",
            str(svg_path),
            "--pfm-setting",
            f"seed={seed}",
        ],
        env={"XDG_CONFIG_HOME": str(work_dir / "config")},
    )
    if result.exit_code != 0:
        raise RuntimeError(f"penpath convert failed for {shape}: {result.output}")

    placement = get_image_placement(svg_path, original.size)
    paper_size = get_svg_paper_size(svg_path) or (PAPER.width_mm, PAPER.height_mm)
    placement_tuple = (placement.x, placement.y, placement.width, placement.height)
    algorithm = measure_svg(original, svg_path, paper_size, placement_tuple)

    blank_svg = work_dir / "blank.svg"
    write_blank_svg(blank_svg, PAPER, placement_tuple)
    blank = measure_svg(original, blank_svg, paper_size, placement_tuple)

    random_svg = work_dir / "random.svg"
    write_random_svg(random_svg, original.size, placement_tuple, algorithm.num_strokes, seed)
    random_drawing = measure_svg(original, random_svg, paper_size, placement_tuple)

    return ShapeReport(
        shape=shape,
        placement=placement,
        algorithm=algorithm,
        blank=blank,
        random=random_drawing,
    )


def measure_all(work_dir: Path, seed: int = SEED) -> list[ShapeReport]:
    """Measure every basic shape, writing intermediate files under work_dir."""
    return [measure_shape(name, work_dir / name, seed) for name in SHAPE_NAMES]


def make_preview(
    original: Image.Image,
    plot: Image.Image,
    placement: tuple[float, float, float, float],
) -> Image.Image:
    """Return a greyscale side-by-side image: the source left, the plot right."""
    crop = placement_crop(plot.size, placement)
    panel_size = (PREVIEW_PANEL, PREVIEW_PANEL)
    left = original.convert("L").resize(panel_size, Image.Resampling.LANCZOS)
    right = plot.convert("L").crop(crop).resize(panel_size, Image.Resampling.LANCZOS)
    preview = Image.new("L", (PREVIEW_WIDTH, PREVIEW_PANEL), "white")
    preview.paste(left, (0, 0))
    preview.paste(right, (PREVIEW_PANEL, 0))
    return preview


def write_previews(work_dir: Path, output_dir: Path) -> list[Path]:
    """Write one 600 px greyscale preview per shape from a ``measure_all`` work dir."""
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for shape in SHAPE_NAMES:
        shape_dir = work_dir / shape
        with Image.open(shape_dir / "shape.png") as opened:
            original = opened.convert("RGB")
        svg_path = shape_dir / "plot.svg"
        placement = get_image_placement(svg_path, original.size)
        paper_size = get_svg_paper_size(svg_path) or (PAPER.width_mm, PAPER.height_mm)
        placement_tuple = (placement.x, placement.y, placement.width, placement.height)
        plot = simulate_plot(
            parse_svg_strokes(svg_path),
            paper_size[0],
            paper_size[1],
            dpi_px_per_mm=PX_PER_MM,
        )
        path = output_dir / f"{shape}.png"
        make_preview(original, plot, placement_tuple).save(path)
        paths.append(path)
    return paths


def format_measurement_table(reports: Sequence[ShapeReport]) -> str:
    """Return a plain-text table of all measurements."""
    header = (
        f"{'shape':<17} {'mode':<10} {'likeness':>8} {'outside':>8} {'coverage':>8} "
        f"{'tone':>9} {'length mm':>11} {'strokes':>8} {'lifts':>6}"
    )
    rows = [
        "Basic shapes gate: default settings, fixed seed "
        f"{SEED}, 64x64 fixtures rendered to {RENDER_SIZE}x{RENDER_SIZE}",
        header,
        "-" * len(header),
    ]
    for report in reports:
        for mode, measured in (
            ("algorithm", report.algorithm),
            ("blank", report.blank),
            ("random", report.random),
        ):
            rows.append(
                f"{report.shape:<17} {mode:<10} {measured.likeness:>8.4f} "
                f"{measured.ink_outside:>8.3f} {measured.dark_coverage:>8.3f} "
                f"{measured.tone_ratio:>9.2f} {measured.drawing_length_mm:>11.1f} "
                f"{measured.num_strokes:>8d} {measured.num_lifts:>6d}"
            )
    return "\n".join(rows)


def print_measurement_table(reports: Sequence[ShapeReport]) -> None:
    """Print the measurement table to stdout without pytest capture noise."""
    click.echo(format_measurement_table(reports))


def finite_values(measured: ShapeMeasures) -> tuple[float, ...]:
    """Return every measurement as a float, for finiteness checks."""
    return (
        measured.likeness,
        measured.ink_outside,
        measured.dark_coverage,
        measured.tone_ratio,
        measured.drawing_length_mm,
        float(measured.num_strokes),
        float(measured.num_lifts),
    )


def all_finite(measured: ShapeMeasures) -> bool:
    """Report whether every measurement is a finite number."""
    return all(math.isfinite(value) for value in finite_values(measured))


__all__ = [
    "BASIC_DIR",
    "NUM_STROKES_MIN",
    "PREVIEW_PANEL",
    "PREVIEW_WIDTH",
    "RENDER_SIZE",
    "SEED",
    "SHAPE_NAMES",
    "SHAPE_THRESHOLDS",
    "ShapeMeasures",
    "ShapeReport",
    "ShapeThresholds",
    "ThresholdViolation",
    "all_finite",
    "finite_values",
    "format_measurement_table",
    "format_threshold_violations",
    "make_preview",
    "measure_all",
    "measure_shape",
    "measure_svg",
    "placement_metrics",
    "print_measurement_table",
    "render_fixture",
    "shape_masks",
    "threshold_violations",
    "write_previews",
]
