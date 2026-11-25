"""Calibration harness for the Sketch Lines ``max_fill`` setting (LUC-89).

Generates a solid dark figure, a light figure and a greyscale gradient, runs the
real ``penpath convert`` pipeline for each value in the sweep, and measures ink
density, tone ordering, machine cost and likeness. The test module turns those
numbers into assertions and records the chosen default.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import click
import numpy as np
from click.testing import CliRunner
from PIL import Image
from sketch_lines_gate import (
    PX_PER_MM,
    SEED,
    compute_likeness,
    get_image_placement,
    get_svg_paper_size,
    ink_mask,
    parse_svg_strokes,
    placement_crop,
    simulate_plot,
)

from penpath.cli.main import main
from penpath.core import compute_machine_cost

if TYPE_CHECKING:
    from collections.abc import Sequence

RENDER_SIZE = 400
SWEEP: tuple[float, ...] = (60.0, 70.0, 80.0, 90.0, 100.0)
DEFAULT_MAX_FILL = 80.0
FIGURE_NAMES: tuple[str, ...] = ("dark_figure", "light_figure", "gradient")
LIGHT_TONE = 190


@dataclass(frozen=True, slots=True)
class FillMeasures:
    """Ink densities, tone bands, machine cost and likeness for one drawing."""

    dark_ink: float
    light_ink: float
    bands: tuple[float, float, float]
    drawing_length_mm: float
    num_strokes: int
    ssim: float


@dataclass(frozen=True, slots=True)
class FillReport:
    """One figure drawn with one ``max_fill`` value."""

    figure: str
    max_fill: float
    measures: FillMeasures


def make_figures(work_dir: Path) -> dict[str, Image.Image]:
    """Generate three 400x400 calibration images and save their PNG twins."""
    work_dir.mkdir(parents=True, exist_ok=True)
    figures: dict[str, Image.Image] = {}

    dark = np.full((RENDER_SIZE, RENDER_SIZE), 255, dtype=np.uint8)
    quarter, three_quarters = RENDER_SIZE // 4, 3 * RENDER_SIZE // 4
    dark[quarter:three_quarters, quarter:three_quarters] = 0
    figures["dark_figure"] = Image.fromarray(dark)

    light = np.full((RENDER_SIZE, RENDER_SIZE), 255, dtype=np.uint8)
    yy, xx = np.ogrid[:RENDER_SIZE, :RENDER_SIZE]
    light[(xx - RENDER_SIZE / 2) ** 2 + (yy - RENDER_SIZE / 2) ** 2 <= quarter**2] = LIGHT_TONE
    figures["light_figure"] = Image.fromarray(light)

    ramp = np.linspace(0, 255, RENDER_SIZE, dtype=np.uint8)
    gradient = np.broadcast_to(ramp, (RENDER_SIZE, RENDER_SIZE)).copy()
    figures["gradient"] = Image.fromarray(gradient)

    for name, image in figures.items():
        image.convert("RGB").save(work_dir / f"{name}.png")
    return figures


def _density(mask: np.ndarray, source: np.ndarray, selector: np.ndarray) -> float:
    """Return the ink density where the resized source satisfies ``selector``."""
    return float(mask[selector(source)].mean()) if selector(source).any() else float("nan")


def measure_figure(name: str, original: Image.Image, svg_path: Path) -> FillMeasures:
    """Measure one exported SVG against the generated calibration image."""
    placement = get_image_placement(svg_path, original.size)
    paper_size = get_svg_paper_size(svg_path) or (210.0, 297.0)
    placement_tuple = (placement.x, placement.y, placement.width, placement.height)

    strokes = parse_svg_strokes(svg_path)
    plot = simulate_plot(strokes, paper_size[0], paper_size[1], dpi_px_per_mm=PX_PER_MM)
    crop = placement_crop(plot.size, placement_tuple)
    mask = ink_mask(plot, crop)
    source = np.asarray(
        original.convert("L").resize(
            (crop[2] - crop[0], crop[3] - crop[1]), Image.Resampling.LANCZOS
        )
    )

    if name == "dark_figure":
        dark_ink = _density(mask, source, lambda values: values < 10)
        light_ink = _density(mask, source, lambda values: values > 245)
        bands = (dark_ink, float("nan"), float("nan"))
    elif name == "light_figure":
        dark_ink = _density(
            mask, source, lambda values: (values > LIGHT_TONE - 10) & (values < LIGHT_TONE + 10)
        )
        light_ink = _density(mask, source, lambda values: values > 245)
        bands = (dark_ink, float("nan"), float("nan"))
    else:
        width = mask.shape[1]
        bands = tuple(
            float(mask[:, index * width // 3 : (index + 1) * width // 3].mean())
            for index in range(3)
        )
        dark_ink, light_ink = bands[0], bands[2]

    cost = compute_machine_cost(strokes)["total"]
    return FillMeasures(
        dark_ink=dark_ink,
        light_ink=light_ink,
        bands=bands,
        drawing_length_mm=float(cost["drawing_length_mm"]),
        num_strokes=len(strokes),
        ssim=compute_likeness(
            plot, original.convert("RGB"), placement_tuple, dpi_px_per_mm=PX_PER_MM
        ),
    )


def measure_sweep(work_dir: Path, sweep: Sequence[float] = SWEEP) -> list[FillReport]:
    """Convert every figure at every requested ``max_fill`` and measure it."""
    figures = make_figures(work_dir)
    reports: list[FillReport] = []
    for name in FIGURE_NAMES:
        original = figures[name]
        for max_fill in sweep:
            svg_path = work_dir / f"{name}_{max_fill:g}.svg"
            result = CliRunner().invoke(
                main,
                [
                    "convert",
                    str(work_dir / f"{name}.png"),
                    "-o",
                    str(svg_path),
                    "--pfm-setting",
                    f"seed={SEED}",
                    "--pfm-setting",
                    f"max_fill={max_fill:g}",
                ],
                env={"XDG_CONFIG_HOME": str(work_dir / "config")},
            )
            if result.exit_code != 0:
                raise RuntimeError(
                    f"penpath convert failed for {name} at max_fill={max_fill:g}: {result.output}"
                )
            reports.append(
                FillReport(name, float(max_fill), measure_figure(name, original, svg_path))
            )
    return reports


def measurement_for(reports: Sequence[FillReport], figure: str, max_fill: float) -> FillMeasures:
    """Return the measured drawing of one figure at one ``max_fill`` value."""
    for report in reports:
        if report.figure == figure and report.max_fill == max_fill:
            return report.measures
    raise AssertionError(f"no measurement for {figure} at max_fill={max_fill:g}")


def format_measurement_table(reports: Sequence[FillReport]) -> str:
    """Return a plain-text table of the whole sweep."""
    header = (
        f"{'figure':<13} {'max_fill':>9} {'dark ink':>9} {'light ink':>10} "
        f"{'band 1':>8} {'band 2':>8} {'band 3':>8} {'length mm':>10} {'strokes':>8} {'SSIM':>7}"
    )
    rows = [
        f"Max fill calibration: seed {SEED}, {RENDER_SIZE}x{RENDER_SIZE} figures, "
        "real convert/simulate path",
        header,
        "-" * len(header),
    ]
    for report in reports:
        measured = report.measures
        bands = [f"{value:8.4f}" if np.isfinite(value) else "     n/a" for value in measured.bands]
        rows.append(
            f"{report.figure:<13} {report.max_fill:9.0f} {measured.dark_ink:9.4f} "
            f"{measured.light_ink:10.4f} {bands[0]} {bands[1]} {bands[2]} "
            f"{measured.drawing_length_mm:10.1f} {measured.num_strokes:8d} {measured.ssim:7.4f}"
        )
    return "\n".join(rows)


def print_measurement_table(reports: Sequence[FillReport]) -> None:
    """Print the sweep table to stdout without pytest capture noise."""
    click.echo(format_measurement_table(reports))


__all__ = [
    "DEFAULT_MAX_FILL",
    "FIGURE_NAMES",
    "LIGHT_TONE",
    "RENDER_SIZE",
    "SWEEP",
    "FillMeasures",
    "FillReport",
    "format_measurement_table",
    "make_figures",
    "measure_figure",
    "measure_sweep",
    "measurement_for",
    "print_measurement_table",
]
