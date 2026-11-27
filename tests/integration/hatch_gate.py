"""Measurement harness for the Hatch likeness, readability and cost gate (LUC-167).

Runs the same image → SVG → strokes → simulation path as ``penpath convert``
and ``penpath evaluate`` on A5 paper with one 0.4 mm black pen. It reuses the
Sketch Lines gate's simulation and likeness helpers and the Stipple gate's
geometry and cost helpers without changing either gate. The enforced floors
live in ``docs/TESTING.md``; this module only produces the numbers.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, cast

import click
from click.testing import CliRunner
from PIL import Image, ImageDraw
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
from stipple_gate import geometry_problems, plot_cost, working_image_size, write_random_svg

from penpath.cli.main import main as cli_main
from penpath.core import (
    compute_machine_cost,
    get_image_placement,
    get_svg_paper_size,
    parse_svg_strokes,
    simulate_plot,
)
from penpath.core.models import Paper
from penpath.core.simulation import insert_pen_up_moves

if TYPE_CHECKING:
    from collections.abc import Sequence

    from penpath.core.simulation import PenStroke

REFERENCE_NAMES = ("face.jpg", "photo.jpg", "gradient.png", "sphere.png")
READABILITY_REFERENCES = ("face.jpg", "photo.jpg")
PRESETS = ("hatch:default", "hatch:crosshatch")
GATE_PRESET = "hatch:default"
SEED = 42
PAPER_SPEC = "a5"
PAPER = Paper(name="a5", width_mm=148.0, height_mm=210.0, margin_mm=10.0)
PEN_WIDTH_MM = 0.4
GRADIENT_STRIPS = 8
STRIP_TOLERANCE = 0.01
STRIP_DARK_END_MARGIN = 0.5
SPACING_TOLERANCE_MM = 0.01
SPACING_CLUSTER_MM = 0.15
SYNTHETIC_SIZE = 200
TINY_SEGMENT_MM = 0.5


@dataclass(frozen=True, slots=True)
class HatchReport:
    """Likeness, baselines, tone strips and machine cost of one hatch drawing."""

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
    lifts: int
    length_mm: float
    travel_mm: float
    tiny_segments: int
    strip_ink: tuple[float, ...]
    geometry_failures: tuple[str, ...]
    wall_seconds: float


def convert_preset(
    image_path: Path,
    preset: str,
    output: Path,
    *extra: str,
) -> float:
    """Convert one image with a hatch preset through the real CLI; return seconds."""
    start = time.monotonic()
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
            "-s",
            f"seed={SEED}",
            "--no-vpype",
            "--quiet",
            *extra,
        ],
        env={"XDG_CONFIG_HOME": str(output.parent / "config")},
    )
    elapsed = time.monotonic() - start
    if result.exit_code != 0:
        raise RuntimeError(
            f"penpath convert failed for {image_path.name}/{preset}: {result.output}"
        )
    return elapsed


def make_flat_image(path: Path, color: str, size: int = SYNTHETIC_SIZE) -> Path:
    """Write a flat black or white PNG of a predictable pixel size."""
    image = Image.new("RGB", (size, size), color)
    image.save(path)
    return path


def make_jitter_image(path: Path, size: int = 64) -> Path:
    """Write a small dark-and-light image with texture for the seed check."""
    image = Image.new("RGB", (size, size), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((3, 3, size // 2, size - 4), fill="black")
    draw.ellipse((size // 2, 3, size - 4, size - 4), fill="#333333")
    image.save(path)
    return path


def pen_lifts(strokes: Sequence[PenStroke]) -> int:
    """Count pen-up transitions between the strokes of one exported drawing."""
    cost = compute_machine_cost(insert_pen_up_moves(strokes))["total"]
    return int(cast(float, cost["num_lifts"]))


def strip_ink_densities(
    strokes: Sequence[PenStroke],
    paper_size: tuple[float, float],
    placement: tuple[float, float, float, float],
    count: int = GRADIENT_STRIPS,
) -> tuple[float, ...]:
    """Return the simulated ink share of equally wide vertical strips."""
    plot = simulate_plot(strokes, paper_size[0], paper_size[1], dpi_px_per_mm=PX_PER_MM)
    x_mm, y_mm, width_mm, height_mm = placement
    left = round(x_mm * PX_PER_MM)
    top = round(y_mm * PX_PER_MM)
    width = round(width_mm * PX_PER_MM)
    height = round(height_mm * PX_PER_MM)
    import numpy as np

    greyscale = np.asarray(plot.convert("L").crop((left, top, left + width, top + height)))
    return tuple(
        float((greyscale[:, index * width // count : (index + 1) * width // count] < 128).mean())
        for index in range(count)
    )


def band_angles(preset: str) -> tuple[float, ...]:
    """Return the band angles of a gate preset, as used by its settings."""
    from penpath.core.drawing.pfm_hatch import HatchSettings
    from penpath.presets.pfms import get_pfm_preset_settings

    settings = get_pfm_preset_settings(preset)
    if not isinstance(settings, HatchSettings):
        raise ValueError(f"{preset} is not a hatch preset")
    return settings.angles


def band_spacings(
    strokes: Sequence[PenStroke],
    angles: Sequence[float],
) -> dict[float, float]:
    """Return the smallest perpendicular gap between parallel strokes of each band."""
    offsets: dict[float, list[float]] = {round(angle, 6): [] for angle in angles}
    for stroke in strokes:
        first, last = stroke.polyline[0], stroke.polyline[-1]
        dx, dy = last[0] - first[0], last[1] - first[1]
        angle = math.degrees(math.atan2(dy, dx)) % 180.0
        band = min(offsets, key=lambda candidate: abs(candidate - angle))
        if abs(band - angle) > 1.5:
            continue
        theta = math.radians(band)
        midpoint = ((first[0] + last[0]) / 2.0, (first[1] + last[1]) / 2.0)
        offsets[band].append(-math.sin(theta) * midpoint[0] + math.cos(theta) * midpoint[1])
    spacings: dict[float, float] = {}
    for band, values in offsets.items():
        ordered = sorted(values)
        distinct: list[float] = []
        for offset in ordered:
            if not distinct or offset - distinct[-1] > SPACING_CLUSTER_MM:
                distinct.append(offset)
        spacings[band] = min(
            (later - earlier for earlier, later in pairwise(distinct)),
            default=0.0,
        )
    return spacings


def measure_conversion(
    image_path: Path,
    preset: str,
    svg_path: Path,
    wall_seconds: float,
) -> HatchReport:
    """Measure a converted hatch SVG against its image and three baselines."""
    with Image.open(image_path) as opened:
        original = opened.convert("RGB")
    placement = get_image_placement(svg_path, original.size)
    placement_tuple = (placement.x, placement.y, placement.width, placement.height)
    paper_size = get_svg_paper_size(svg_path) or (PAPER.width_mm, PAPER.height_mm)

    strokes = parse_svg_strokes(svg_path)
    points = [point for stroke in strokes for point in stroke.polyline]
    algorithm_plot = simulate_plot(strokes, paper_size[0], paper_size[1], dpi_px_per_mm=PX_PER_MM)
    algorithm = measure_plot(algorithm_plot, original, placement_tuple, points)

    blank_svg = svg_path.with_name(f"{svg_path.stem}_blank.svg")
    write_blank_svg(blank_svg, PAPER, placement_tuple)
    blank_points, blank_plot = simulate_svg(blank_svg, paper_size)
    blank = measure_plot(blank_plot, original, placement_tuple, blank_points)

    random_svg = svg_path.with_name(f"{svg_path.stem}_random.svg")
    write_random_svg(random_svg, original.size, placement_tuple, len(strokes), SEED)
    random_points, random_plot = simulate_svg(random_svg, paper_size)
    random_drawing = measure_plot(random_plot, original, placement_tuple, random_points)

    ideal = measure_plot(
        make_ideal_plot(original, algorithm_plot.size, placement_tuple), original, placement_tuple
    )

    cost = plot_cost(strokes, len(strokes))
    return HatchReport(
        reference=image_path.name,
        preset=preset,
        placement=placement_tuple,
        paper_size=paper_size,
        working_size=working_image_size(svg_path),
        stroke_count=len(strokes),
        algorithm=algorithm,
        blank=blank,
        random=random_drawing,
        ideal=ideal,
        lifts=cost.lifts,
        length_mm=cost.length_mm,
        travel_mm=cost.travel_mm,
        tiny_segments=cost.tiny_segments,
        strip_ink=strip_ink_densities(strokes, paper_size, placement_tuple),
        geometry_failures=geometry_problems(strokes, paper_size),
        wall_seconds=wall_seconds,
    )


def measure(image_path: Path, preset: str, work_dir: Path) -> HatchReport:
    """Convert one image with one preset and measure the result."""
    work_dir.mkdir(parents=True, exist_ok=True)
    svg_path = work_dir / f"{image_path.stem}_{preset.replace(':', '_')}.svg"
    elapsed = convert_preset(image_path, preset, svg_path)
    return measure_conversion(image_path, preset, svg_path, elapsed)


def measure_all(
    work_dir: Path,
    references: Sequence[str] = REFERENCE_NAMES,
    presets: Sequence[str] = PRESETS,
) -> list[HatchReport]:
    """Convert and measure every requested image/preset pair."""
    return [
        measure(REFERENCE_DIR / name, preset, work_dir / Path(name).stem / preset.replace(":", "_"))
        for name in references
        for preset in presets
    ]


def _triple(measures: Sequence[PlotMeasures], name: str, decimals: int) -> str:
    """Format one measure for the algorithm, blank and random rows."""
    return "/".join(f"{getattr(item, name):.{decimals}f}" for item in measures)


def format_measurement_table(reports: Sequence[HatchReport]) -> str:
    """Return a plain-text table of every measured hatch gate value."""
    header = (
        f"{'image':<13} {'preset':<15} {'SSIM a/b/r':>24} {'W':>6} {'H':>6} {'bbox':>6} "
        f"{'ink min':>8} {'tone':>7} {'rank':>7} {'darkInk':>8} {'strokes':>8} "
        f"{'lifts':>7} {'mm':>9} {'tiny':>5} {'wall s':>7}"
    )
    rows = [
        f"Hatch gate: seed 42, A5 paper, 0.4 mm black pen, --no-vpype, {PX_PER_MM:.3f} px/mm",
        "SSIM is algorithm / blank / random; other columns are the algorithm's values.",
        header,
        "-" * len(header),
    ]
    for report in reports:
        algorithm = report.algorithm
        rows.append(
            f"{report.reference:<13} {report.preset:<15} "
            f"{_triple((algorithm, report.blank, report.random), 'ssim', 4):>24} "
            f"{algorithm.coverage_width:>6.3f} {algorithm.coverage_height:>6.3f} "
            f"{algorithm.coverage_area:>6.3f} {algorithm.ink_spread_min:>8.4f} "
            f"{algorithm.tone_ratio:>7.2f} {algorithm.rank_correlation:>7.3f} "
            f"{algorithm.dark_textured_ink_max:>8.3f} {report.stroke_count:>8d} "
            f"{report.lifts:>7d} {report.length_mm:>9.1f} {report.tiny_segments:>5d} "
            f"{report.wall_seconds:>7.2f}"
        )
    return "\n".join(rows)


def print_measurement_table(reports: Sequence[HatchReport]) -> None:
    """Print the measurement table to stdout without pytest capture noise."""
    click.echo(format_measurement_table(reports))


def all_report_values_finite(report: HatchReport) -> bool:
    """Report whether every likeness measurement in a report is finite."""
    return all(
        all_finite(measures)
        for measures in (report.algorithm, report.blank, report.random, report.ideal)
    )


def main() -> None:
    """Convert and measure every reference/preset pair, printing the table."""
    print_measurement_table(measure_all(Path("/tmp/hatch-gate")))


__all__ = [
    "GATE_PRESET",
    "GRADIENT_STRIPS",
    "PAPER",
    "PAPER_SPEC",
    "PEN_WIDTH_MM",
    "PRESETS",
    "PX_PER_MM",
    "READABILITY_REFERENCES",
    "REFERENCE_DIR",
    "REFERENCE_NAMES",
    "SEED",
    "SPACING_CLUSTER_MM",
    "SPACING_TOLERANCE_MM",
    "STRIP_DARK_END_MARGIN",
    "STRIP_TOLERANCE",
    "SYNTHETIC_SIZE",
    "TINY_SEGMENT_MM",
    "HatchReport",
    "all_report_values_finite",
    "band_angles",
    "band_spacings",
    "convert_preset",
    "format_measurement_table",
    "make_flat_image",
    "make_jitter_image",
    "measure",
    "measure_all",
    "measure_conversion",
    "pen_lifts",
    "print_measurement_table",
    "strip_ink_densities",
]

if __name__ == "__main__":
    main()
