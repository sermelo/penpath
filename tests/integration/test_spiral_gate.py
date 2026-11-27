"""Gate for the Spiral Sawtooth readability, single-line and plot-cost claims (LUC-138).

Every built-in preset and the algorithm defaults are converted through the real
CLI on the three photo references, then parsed, simulated and scored with the
same helpers used by ``penpath evaluate``. The enforced floors and caps are
recorded in ``docs/TESTING.md``; visual acceptance needs the committed previews.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import click
import numpy as np
import pytest
from click.testing import CliRunner
from contour_gate import PlotCost, geometry_problems, plot_cost, working_image_size
from PIL import Image
from sketch_lines_gate import (
    REFERENCE_DIR,
    SEED,
    PlotMeasures,
    measure_plot,
    simulate_svg,
    write_blank_svg,
    write_random_svg,
)

from penpath.cli.main import main as cli_main
from penpath.core import (
    get_image_placement,
    get_svg_paper_size,
    parse_svg_strokes,
)
from penpath.core.drawing.pfm_spiral import SpiralSettings, spiral_strokes
from penpath.core.models import Paper
from penpath.presets.pfms import get_pfm_preset_by_id

REFERENCES = ("face.jpg", "photo.jpg", "santa.jpg")
PRESETS = (
    "spiral_sawtooth",
    "spiral_sawtooth:fine",
    "spiral_sawtooth:bold",
    "spiral_sawtooth:parabolic",
)
PAPER = Paper(name="square", width_mm=190.0, height_mm=190.0, margin_mm=0.0)
DPI = 96
MAX_RESOLUTION = 384

COVERAGE_WIDTH_MIN = 0.85
COVERAGE_HEIGHT_MIN = 0.80
BBOX_MIN = 0.70
INK_CELL_MIN = 0.0025
TONE_RATIO_MIN = 0.60
DARK_TEXTURED_INK_MIN = 0.65
MAX_LIFTS = 3
MAX_LENGTH_MM = 100000.0
MAX_TINY_SEGMENTS = 40
MAX_TINY_FRACTION = 0.02


@dataclass(frozen=True, slots=True)
class SpiralReport:
    """Readability, baselines and machine cost of one reference/preset pair."""

    reference: str
    preset: str
    raw_strokes: int
    strokes: int
    lifts: int
    algorithm: PlotMeasures
    blank: PlotMeasures
    random: PlotMeasures
    cost: PlotCost
    geometry_failures: tuple[str, ...]


def settings_for(preset: str) -> SpiralSettings:
    """Return the shipped algorithm defaults or a registered preset's settings."""
    if preset == "spiral_sawtooth":
        return SpiralSettings()
    settings = get_pfm_preset_by_id(preset)[1]
    assert isinstance(settings, SpiralSettings)
    return settings


def convert(image_path: Path, preset: str, output: Path) -> None:
    """Convert one reference with the documented CLI command for this gate."""
    result = CliRunner().invoke(
        cli_main,
        [
            "convert",
            str(image_path),
            "-o",
            str(output),
            "--pfm",
            preset,
            "-s",
            f"seed={SEED}",
            "--paper",
            "190x190,0",
            "--pen",
            "0.4,#000000,fineliner",
            "--dpi",
            str(DPI),
            "--max-resolution",
            str(MAX_RESOLUTION),
            "--quiet",
        ],
        env={"XDG_CONFIG_HOME": str(output.parent / "config")},
    )
    if result.exit_code != 0:
        raise RuntimeError(
            f"penpath convert failed for {image_path.name}/{preset}: {result.output}"
        )


def evaluate_lifts(image_path: Path, svg_path: Path) -> int:
    """Read the pen-lift count from ``penpath evaluate --json``."""
    result = CliRunner().invoke(cli_main, ["evaluate", str(image_path), str(svg_path), "--json"])
    if result.exit_code != 0:
        raise RuntimeError(f"penpath evaluate failed for {svg_path.name}: {result.output}")
    cost = json.loads(result.stdout)["machine_cost"]["total"]
    return int(cast(int, cost["num_lifts"]))


def measure(reference: str, preset: str, work_dir: Path) -> SpiralReport:
    """Convert, simulate and measure one reference/preset pair."""
    work_dir.mkdir(parents=True, exist_ok=True)
    image_path = REFERENCE_DIR / reference
    svg_path = work_dir / f"{Path(reference).stem}_{preset.replace(':', '_')}.svg"
    convert(image_path, preset, svg_path)
    with Image.open(image_path) as opened:
        original = opened.convert("RGB")
    placement = get_image_placement(svg_path, original.size)
    placement_tuple = (placement.x, placement.y, placement.width, placement.height)
    paper_size = get_svg_paper_size(svg_path) or (PAPER.width_mm, PAPER.height_mm)
    strokes = parse_svg_strokes(svg_path)
    points, plot = simulate_svg(svg_path, paper_size)
    algorithm = measure_plot(plot, original, placement_tuple, points)

    blank_svg = work_dir / f"{svg_path.stem}_blank.svg"
    write_blank_svg(blank_svg, PAPER, placement_tuple)
    blank_points, blank_plot = simulate_svg(blank_svg, paper_size)
    blank = measure_plot(blank_plot, original, placement_tuple, blank_points)

    random_svg = work_dir / f"{svg_path.stem}_random.svg"
    write_random_svg(random_svg, original.size, placement_tuple, len(strokes), SEED)
    random_points, random_plot = simulate_svg(random_svg, paper_size)
    random = measure_plot(random_plot, original, placement_tuple, random_points)

    working = original.resize(working_image_size(svg_path), Image.Resampling.LANCZOS)
    raw_strokes = len(spiral_strokes(working, settings_for(preset)))
    return SpiralReport(
        reference=reference,
        preset=preset,
        raw_strokes=raw_strokes,
        strokes=len(strokes),
        lifts=evaluate_lifts(image_path, svg_path),
        algorithm=algorithm,
        blank=blank,
        random=random,
        cost=plot_cost(strokes),
        geometry_failures=geometry_problems(strokes, paper_size),
    )


def format_table(reports: list[SpiralReport]) -> str:
    """Return the measured numbers as a plain-text table."""
    header = (
        f"{'image':<11} {'preset':<22} {'raw':>3} {'svg':>3} {'lift':>4} {'rank':>6} "
        f"{'darkInk':>8} {'cov W':>6} {'cov H':>6} {'bbox':>6} {'ink min':>8} "
        f"{'tone':>8} {'strokes':>7} {'mm':>10} {'tiny':>5} {'tiny %':>7} {'SSIM':>6}"
    )
    rows = [
        "Spiral gate: 190x190 mm, one 0.4 mm pen, seed 42, working image 384 px",
        header,
        "-" * len(header),
    ]
    for report in reports:
        m, cost = report.algorithm, report.cost
        rows.append(
            f"{report.reference:<11} {report.preset:<22} {report.raw_strokes:>3d} "
            f"{report.strokes:>3d} {report.lifts:>4d} {m.rank_correlation:>6.3f} "
            f"{m.dark_textured_ink_max:>8.3f} {m.coverage_width:>6.3f} "
            f"{m.coverage_height:>6.3f} {m.coverage_area:>6.3f} "
            f"{m.ink_spread_min:>8.4f} {m.tone_ratio:>8.2f} {cost.strokes:>7d} "
            f"{cost.length_mm:>10.1f} {cost.tiny_segments:>5d} "
            f"{cost.tiny_fraction:>7.3f} {m.ssim:>6.3f}"
        )
    return "\n".join(rows)


@pytest.fixture(scope="session")
def spiral_report_factory(
    tmp_path_factory: pytest.TempPathFactory,
) -> Callable[[str, str], SpiralReport]:
    """Convert and measure each reference/preset pair at most once per session."""
    work_dir = tmp_path_factory.mktemp("spiral-gate")
    cache: dict[tuple[str, str], SpiralReport] = {}

    def report_for(reference: str, preset: str) -> SpiralReport:
        key = (reference, preset)
        if key not in cache:
            cache[key] = measure(reference, preset, work_dir / reference)
        return cache[key]

    return report_for


def test_measures_every_reference_with_every_preset(
    spiral_report_factory: Callable[[str, str], SpiralReport],
) -> None:
    """Print all measurements for the recorded evidence table."""
    reports = [
        spiral_report_factory(reference, preset) for reference in REFERENCES for preset in PRESETS
    ]
    click.echo(format_table(reports))
    assert len(reports) == len(REFERENCES) * len(PRESETS)


def test_default_santa_is_one_continuous_line(
    spiral_report_factory: Callable[[str, str], SpiralReport],
) -> None:
    """The default archimedean stroke stays a single line before and after export."""
    report = spiral_report_factory("santa.jpg", "spiral_sawtooth")
    assert report.raw_strokes == 1
    assert report.strokes == 1
    assert report.lifts == 0
    assert report.cost.length_mm > 0


@pytest.mark.parametrize("reference", REFERENCES)
@pytest.mark.parametrize("preset", PRESETS)
def test_preset_is_valid_readable_and_cheap(
    spiral_report_factory: Callable[[str, str], SpiralReport],
    reference: str,
    preset: str,
) -> None:
    """Every preset draws a real, dark-following, low-cost plot on every reference."""
    report = spiral_report_factory(reference, preset)
    assert not report.geometry_failures, report.geometry_failures[:5]
    assert report.strokes > 0
    assert report.strokes <= MAX_LIFTS, f"{reference}/{preset}: {report.strokes} strokes"
    assert report.lifts <= MAX_LIFTS, f"{reference}/{preset}: {report.lifts} lifts"

    m = report.algorithm
    failures: list[str] = []
    for name, value, floor in (
        ("cov W", m.coverage_width, COVERAGE_WIDTH_MIN),
        ("cov H", m.coverage_height, COVERAGE_HEIGHT_MIN),
        ("bbox", m.coverage_area, BBOX_MIN),
        ("ink per cell", m.ink_spread_min, INK_CELL_MIN),
        ("tone ratio", m.tone_ratio, TONE_RATIO_MIN),
        ("dark tile ink", m.dark_textured_ink_max, DARK_TEXTURED_INK_MIN),
    ):
        if value < floor:
            failures.append(f"{name} {value:.4f} < {floor}")
    cost = report.cost
    if cost.length_mm > MAX_LENGTH_MM:
        failures.append(f"length {cost.length_mm:.1f} > {MAX_LENGTH_MM}")
    if cost.tiny_segments > MAX_TINY_SEGMENTS:
        failures.append(f"tiny segments {cost.tiny_segments} > {MAX_TINY_SEGMENTS}")
    if cost.tiny_fraction > MAX_TINY_FRACTION:
        failures.append(f"tiny share {cost.tiny_fraction:.3f} > {MAX_TINY_FRACTION}")
    assert not failures, f"{reference}/{preset}: " + "; ".join(failures)


def test_blank_and_random_fail_readability(
    spiral_report_factory: Callable[[str, str], SpiralReport],
) -> None:
    """A blank page and a random scribble cannot pass the readability floors."""
    for reference in REFERENCES:
        for preset in PRESETS:
            report = spiral_report_factory(reference, preset)
            for baseline in (report.blank, report.random):
                assert baseline.coverage_area < BBOX_MIN
                assert baseline.ink_spread_min < INK_CELL_MIN
                assert baseline.dark_textured_ink_max < DARK_TEXTURED_INK_MIN


def test_user_can_convert_and_preview_every_preset(tmp_path: Path) -> None:
    """The documented convert-plus-preview commands write four distinct PNGs."""
    images: list[bytes] = []
    for preset in PRESETS:
        name = preset.replace(":", "_")
        svg_path = tmp_path / f"santa_{name}.svg"
        png_path = tmp_path / f"santa_{name}.png"
        convert(REFERENCE_DIR / "santa.jpg", preset, svg_path)
        previewed = CliRunner().invoke(
            cli_main, ["preview", str(svg_path), "-o", str(png_path), "--dpi", "3"]
        )
        assert previewed.exit_code == 0, previewed.output
        with Image.open(png_path) as opened:
            greyscale = opened.convert("L")
            assert greyscale.size == (570, 570)
            pixels = np.asarray(greyscale)
        assert pixels.min() < 128 < pixels.max()
        images.append(pixels.tobytes())
    assert len(set(images)) == len(PRESETS)
