"""Gate for the Spiral Sawtooth readability, single-line and plot-cost claims (LUC-138, LUC-203).

Every built-in preset and the algorithm defaults are converted through the real
CLI on the three photo references, then parsed, simulated and scored with the
same helpers used by ``penpath evaluate``. Coverage and ink/tone readability
floors are asserted on ``shape="cover"`` and ``shape="ellipse"`` (which reach the
page edges); the new default ``shape="circle"`` is asserted for roundness and
cost instead, because round rings deliberately leave the corners empty. The
enforced floors and caps are recorded in ``docs/TESTING.md``; visual acceptance
needs the committed previews.
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
from shapely import LineString
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

pytestmark = pytest.mark.slow

REFERENCES = ("face.jpg", "photo.jpg", "santa.jpg")
PRESETS = (
    "spiral_sawtooth",
    "spiral_sawtooth:fine",
    "spiral_sawtooth:bold",
    "spiral_sawtooth:parabolic",
)
SHAPES = ("circle", "ellipse", "cover")
DEFAULT_PRESET = "spiral_sawtooth"
SHAPE_CASES = tuple((preset, "circle") for preset in PRESETS) + tuple(
    (DEFAULT_PRESET, shape) for shape in SHAPES if shape != "circle"
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
MAX_TINY_SEGMENTS = 0
MAX_TINY_FRACTION = 0.0


@dataclass(frozen=True, slots=True)
class SpiralReport:
    """Readability, baselines and machine cost of one reference/preset/shape pair."""

    reference: str
    preset: str
    shape: str
    raw_strokes: int
    strokes: int
    lifts: int
    radial_reach_delta: float
    algorithm: PlotMeasures
    blank: PlotMeasures
    random: PlotMeasures
    cost: PlotCost
    geometry_failures: tuple[str, ...]


def settings_for(preset: str, shape: str) -> SpiralSettings:
    """Return a preset's settings, or the defaults, with the given shape."""
    if preset == DEFAULT_PRESET:
        settings = SpiralSettings()
    else:
        settings = cast(SpiralSettings, get_pfm_preset_by_id(preset)[1])
        assert isinstance(settings, SpiralSettings)
    return settings.model_copy(update={"shape": shape})


def convert(image_path: Path, preset: str, output: Path, shape: str = "circle") -> None:
    """Convert one reference with the documented CLI command for this gate."""
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
            preset,
            "-s",
            f"seed={SEED}",
            "-s",
            f"shape={shape}",
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
            f"penpath convert failed for {image_path.name}/{preset}/{shape}: {result.output}"
        )


def evaluate_lifts(image_path: Path, svg_path: Path) -> int:
    """Read the pen-lift count from ``penpath evaluate --json``."""
    result = CliRunner().invoke(cli_main, ["evaluate", str(image_path), str(svg_path), "--json"])
    if result.exit_code != 0:
        raise RuntimeError(f"penpath evaluate failed for {svg_path.name}: {result.output}")
    cost = json.loads(result.stdout)["machine_cost"]["total"]
    return int(cast(int, cost["num_lifts"]))


def _radial_reach_delta(strokes: list[LineString], image: Image.Image) -> float:
    """Return how far the horizontal and vertical reaches differ, in pixels."""
    points = [point for stroke in strokes for point in stroke.coords]
    if not points:
        return float("inf")
    centre_x, centre_y = (image.width - 1) / 2, (image.height - 1) / 2
    horizontal = max(abs(x - centre_x) for x, _ in points)
    vertical = max(abs(y - centre_y) for _, y in points)
    return abs(horizontal - vertical)


def measure(reference: str, preset: str, shape: str, work_dir: Path) -> SpiralReport:
    """Convert, simulate and measure one reference/preset/shape pair."""
    work_dir.mkdir(parents=True, exist_ok=True)
    image_path = REFERENCE_DIR / reference
    svg_path = work_dir / f"{Path(reference).stem}_{preset.replace(':', '_')}_{shape}.svg"
    convert(image_path, preset, svg_path, shape)
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
    raw = spiral_strokes(working, settings_for(preset, shape))
    return SpiralReport(
        reference=reference,
        preset=preset,
        shape=shape,
        raw_strokes=len(raw),
        strokes=len(strokes),
        lifts=evaluate_lifts(image_path, svg_path),
        radial_reach_delta=_radial_reach_delta(raw, working),
        algorithm=algorithm,
        blank=blank,
        random=random,
        cost=plot_cost(strokes),
        geometry_failures=geometry_problems(strokes, paper_size),
    )


def format_table(reports: list[SpiralReport]) -> str:
    """Return the measured numbers as a plain-text table."""
    header = (
        f"{'image':<11} {'preset':<22} {'shape':<8} {'raw':>3} {'svg':>3} {'lift':>4} "
        f"{'reachΔ':>7} {'rank':>6} {'darkInk':>8} {'cov W':>6} {'cov H':>6} "
        f"{'bbox':>6} {'ink min':>8} {'tone':>8} {'strokes':>7} {'mm':>10} "
        f"{'tiny':>5} {'tiny %':>7} {'SSIM':>6}"
    )
    rows = [
        "Spiral gate: 190x190 mm, one 0.4 mm pen, seed 42, working image 384 px",
        header,
        "-" * len(header),
    ]
    for report in reports:
        m, cost = report.algorithm, report.cost
        rows.append(
            f"{report.reference:<11} {report.preset:<22} {report.shape:<8} "
            f"{report.raw_strokes:>3d} {report.strokes:>3d} {report.lifts:>4d} "
            f"{report.radial_reach_delta:>7.2f} "
            f"{m.rank_correlation:>6.3f} {m.dark_textured_ink_max:>8.3f} {m.coverage_width:>6.3f} "
            f"{m.coverage_height:>6.3f} {m.coverage_area:>6.3f} {m.ink_spread_min:>8.4f} "
            f"{m.tone_ratio:>8.2f} {cost.strokes:>7d} {cost.length_mm:>10.1f} "
            f"{cost.tiny_segments:>5d} {cost.tiny_fraction:>7.3f} {m.ssim:>6.3f}"
        )
    return "\n".join(rows)


@pytest.fixture(scope="session")
def spiral_report_factory(
    tmp_path_factory: pytest.TempPathFactory,
) -> Callable[[str, str, str], SpiralReport]:
    """Convert and measure each reference/preset/shape at most once per session."""
    work_dir = tmp_path_factory.mktemp("spiral-gate")
    cache: dict[tuple[str, str, str], SpiralReport] = {}

    def report_for(reference: str, preset: str, shape: str) -> SpiralReport:
        key = (reference, preset, shape)
        if key not in cache:
            cache[key] = measure(reference, preset, shape, work_dir / reference)
        return cache[key]

    return report_for


def test_measures_every_case_with_every_shape(
    spiral_report_factory: Callable[[str, str, str], SpiralReport],
) -> None:
    """Print all measurements for the recorded evidence table."""
    reports = [
        spiral_report_factory(reference, preset, shape)
        for reference in REFERENCES
        for preset, shape in SHAPE_CASES
    ]
    click.echo(format_table(reports))
    assert len(reports) == len(REFERENCES) * len(SHAPE_CASES)


def test_default_santa_is_one_continuous_line(
    spiral_report_factory: Callable[[str, str, str], SpiralReport],
) -> None:
    """The default archimedean circle stroke stays a single line before and after export."""
    report = spiral_report_factory("santa.jpg", DEFAULT_PRESET, "circle")
    assert report.raw_strokes == 1
    assert report.strokes == 1
    assert report.lifts == 0
    assert report.cost.length_mm > 0


def test_default_circle_is_round(
    spiral_report_factory: Callable[[str, str, str], SpiralReport],
) -> None:
    """Default round rings reach equally far horizontally and vertically."""
    defaults = SpiralSettings()
    tooth_reach = defaults.ring_spacing / 2.0 * defaults.amplitude
    for reference in REFERENCES:
        report = spiral_report_factory(reference, DEFAULT_PRESET, "circle")
        assert report.radial_reach_delta <= tooth_reach, (
            reference,
            report.radial_reach_delta,
            tooth_reach,
        )


def test_cover_reaches_the_page_corners(
    spiral_report_factory: Callable[[str, str, str], SpiralReport],
) -> None:
    """Circular rings out to the farthest corner meet the coverage floors everywhere."""
    for reference in REFERENCES:
        report = spiral_report_factory(reference, DEFAULT_PRESET, "cover")
        m = report.algorithm
        failures = []
        for name, value, floor in (
            ("cov W", m.coverage_width, COVERAGE_WIDTH_MIN),
            ("cov H", m.coverage_height, COVERAGE_HEIGHT_MIN),
            ("bbox", m.coverage_area, BBOX_MIN),
        ):
            if value < floor:
                failures.append(f"{name} {value:.4f} < {floor}")
        assert not failures, f"{reference}/cover: " + "; ".join(failures)


def test_every_shape_is_valid_and_cheap(
    spiral_report_factory: Callable[[str, str, str], SpiralReport],
) -> None:
    """Every shape and preset stays on the page, follows dark tiles and is cheap to plot."""
    for reference in REFERENCES:
        for preset, shape in SHAPE_CASES:
            report = spiral_report_factory(reference, preset, shape)
            assert not report.geometry_failures, report.geometry_failures[:5]
            assert report.strokes > 0
            assert report.strokes <= MAX_LIFTS, f"{reference}/{preset}/{shape}: strokes"
            assert report.lifts <= MAX_LIFTS, f"{reference}/{preset}/{shape}: lifts"
            m, cost = report.algorithm, report.cost
            failures: list[str] = []
            if m.dark_textured_ink_max < DARK_TEXTURED_INK_MIN:
                failures.append(f"dark tile ink {m.dark_textured_ink_max:.4f}")
            if cost.length_mm > MAX_LENGTH_MM:
                failures.append(f"length {cost.length_mm:.1f} > {MAX_LENGTH_MM}")
            if cost.tiny_segments > MAX_TINY_SEGMENTS:
                failures.append(f"tiny segments {cost.tiny_segments}")
            if cost.tiny_fraction > MAX_TINY_FRACTION:
                failures.append(f"tiny share {cost.tiny_fraction:.3f}")
            assert not failures, f"{reference}/{preset}/{shape}: " + "; ".join(failures)


def test_edge_reaching_shapes_meet_ink_and_tone_floors(
    spiral_report_factory: Callable[[str, str, str], SpiralReport],
) -> None:
    """Ellipse and cover keep the per-cell ink and tone floors; circle omits corners by design."""
    for reference in REFERENCES:
        for shape in ("ellipse", "cover"):
            report = spiral_report_factory(reference, DEFAULT_PRESET, shape)
            m = report.algorithm
            failures: list[str] = []
            for name, value, floor in (
                ("ink per cell", m.ink_spread_min, INK_CELL_MIN),
                ("tone ratio", m.tone_ratio, TONE_RATIO_MIN),
            ):
                if value < floor:
                    failures.append(f"{name} {value:.4f} < {floor}")
            assert not failures, f"{reference}/{shape}: " + "; ".join(failures)


def test_blank_and_random_fail_readability(
    spiral_report_factory: Callable[[str, str, str], SpiralReport],
) -> None:
    """A blank page and a random scribble cannot pass the readability floors."""
    for reference in REFERENCES:
        for preset, shape in SHAPE_CASES:
            report = spiral_report_factory(reference, preset, shape)
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
            cli_main,
            ["preview", str(svg_path), "-o", str(png_path), "--px-per-mm", "3"],
        )
        assert previewed.exit_code == 0, previewed.output
        with Image.open(png_path) as opened:
            greyscale = opened.convert("L")
            assert greyscale.size == (570, 570)
            pixels = np.asarray(greyscale)
        assert pixels.min() < 128 < pixels.max()
        images.append(pixels.tobytes())
    assert len(set(images)) == len(PRESETS)
