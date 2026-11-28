"""Assert the hatch gate thresholds recorded in docs/TESTING.md.

The harness in ``hatch_gate.py`` runs the real ``penpath convert`` CLI on A5
paper with one 0.4 mm black pen. This module turns the measured likeness, tone
strip, spacing, cost and timing numbers into pass/fail checks. SSIM is evidence
beside the readability floors, and every acceptance line is enforced.
"""

from __future__ import annotations

from collections.abc import Callable
from itertools import pairwise
from pathlib import Path

import click
import pytest
from click.testing import CliRunner
from hatch_gate import (
    GATE_PRESET,
    GRADIENT_STRIPS,
    PEN_WIDTH_MM,
    PRESETS,
    READABILITY_REFERENCES,
    REFERENCE_DIR,
    SEED,
    SPACING_TOLERANCE_MM,
    STRIP_DARK_END_MARGIN,
    STRIP_TOLERANCE,
    HatchReport,
    all_report_values_finite,
    band_angles,
    band_spacings,
    convert_preset,
    make_flat_image,
    make_jitter_image,
    measure,
    pen_lifts,
    print_measurement_table,
)
from sketch_lines_gate import PlotMeasures

from penpath.cli.main import main as cli_main
from penpath.core import parse_svg_strokes

pytestmark = pytest.mark.slow

MAX_WALL_SECONDS = 30.0
FLOORS: dict[str, dict[str, float]] = {
    "face.jpg": {
        "ssim": 0.48,
        "coverage_width": 0.94,
        "coverage_height": 0.94,
        "coverage_area": 0.94,
        "ink_spread_min": 0.017,
        "tone_ratio": 5.0,
        "rank_correlation": 0.75,
        "dark_textured_ink_max": 0.75,
    },
    "photo.jpg": {
        "ssim": 0.54,
        "coverage_width": 0.94,
        "coverage_height": 0.94,
        "coverage_area": 0.94,
        "ink_spread_min": 0.017,
        "tone_ratio": 1.5,
        "rank_correlation": 0.86,
        "dark_textured_ink_max": 0.75,
    },
}


def floor_failures(measures: PlotMeasures, floors: dict[str, float]) -> list[str]:
    """Return the readability floors a set of measurements fails."""
    return [
        f"{name} {getattr(measures, name):.4f} < {floor:.4f}"
        for name, floor in floors.items()
        if getattr(measures, name) < floor
    ]


@pytest.fixture(scope="session")
def hatch_report_factory(
    tmp_path_factory: pytest.TempPathFactory,
) -> Callable[[str, str], HatchReport]:
    """Convert and measure each reference/preset pair at most once per session."""
    work_dir = tmp_path_factory.mktemp("hatch-gate")
    cache: dict[tuple[str, str], HatchReport] = {}

    def report_for(reference: str, preset: str) -> HatchReport:
        key = (reference, preset)
        if key not in cache:
            cache[key] = measure(REFERENCE_DIR / reference, preset, work_dir / Path(reference).stem)
        return cache[key]

    return report_for


def test_gate_measures_every_reference_and_preset(
    hatch_report_factory: Callable[[str, str], HatchReport],
) -> None:
    """The harness measures every committed image with both gate presets."""
    reports = [
        hatch_report_factory(name, preset)
        for name in ("face.jpg", "photo.jpg", "gradient.png", "sphere.png")
        for preset in PRESETS
    ]
    assert len(reports) == 8
    print_measurement_table(reports)


@pytest.mark.parametrize("reference", READABILITY_REFERENCES)
@pytest.mark.parametrize("preset", PRESETS)
def test_hatch_reading_beats_blank_and_random(
    hatch_report_factory: Callable[[str, str], HatchReport],
    reference: str,
    preset: str,
) -> None:
    """A face or photo is readable and both trivial baselines fail the floors."""
    report = hatch_report_factory(reference, preset)
    assert report.reference == reference
    assert report.preset == preset
    assert report.stroke_count > 0
    assert report.placement[2] > 0 and report.placement[3] > 0
    assert all_report_values_finite(report)
    assert not report.geometry_failures, report.geometry_failures[:5]

    floors = FLOORS[reference]
    failures = floor_failures(report.algorithm, floors)
    assert not failures, f"{reference}/{preset}: " + "; ".join(failures)
    assert floor_failures(report.blank, floors), f"{reference}: blank page passed every floor"
    assert floor_failures(report.random, floors), f"{reference}: random scribble passed every floor"
    assert report.algorithm.rank_correlation >= floors["rank_correlation"]
    assert report.blank.rank_correlation < floors["rank_correlation"]
    assert report.random.rank_correlation < floors["rank_correlation"]


@pytest.mark.parametrize("preset", PRESETS)
def test_gradient_ink_density_is_monotonic(
    hatch_report_factory: Callable[[str, str], HatchReport],
    preset: str,
) -> None:
    """Ink density falls across the black-to-white ramp within the tolerance."""
    report = hatch_report_factory("gradient.png", preset)
    strips = report.strip_ink
    assert len(strips) == GRADIENT_STRIPS
    assert all(0.0 <= value <= 1.0 for value in strips)
    rises = [
        later - earlier for earlier, later in pairwise(strips) if later - earlier > STRIP_TOLERANCE
    ]
    assert not rises, f"{preset}: strip ink density rises by more than {STRIP_TOLERANCE}: {rises}"
    assert strips[0] - strips[-1] >= STRIP_DARK_END_MARGIN, strips


@pytest.mark.parametrize("preset", PRESETS)
def test_rendered_spacing_is_never_below_pen_width(preset: str, tmp_path: Path) -> None:
    """Every band of an all-black page renders lines at least one pen width apart."""
    image = make_flat_image(tmp_path / f"black_{preset.replace(':', '_')}.png", "black")
    svg_path = tmp_path / f"black_{preset.replace(':', '_')}.svg"
    convert_preset(image, preset, svg_path)
    strokes = parse_svg_strokes(svg_path)
    assert strokes

    spacings = band_spacings(strokes, band_angles(preset))
    assert set(spacings) == set(band_angles(preset))
    for angle, spacing in spacings.items():
        assert spacing > 0.0, f"{preset}/{angle}: no second line to measure"
        assert spacing >= PEN_WIDTH_MM - SPACING_TOLERANCE_MM, f"{preset}/{angle}: {spacing:.3f} mm"


@pytest.mark.parametrize("preset", PRESETS)
def test_blank_image_produces_no_strokes(preset: str, tmp_path: Path) -> None:
    """An all-white page makes hatch emit nothing at all."""
    image = make_flat_image(tmp_path / f"white_{preset.replace(':', '_')}.png", "white")
    svg_path = tmp_path / f"white_{preset.replace(':', '_')}.svg"
    convert_preset(image, preset, svg_path)
    assert not svg_path.exists() or parse_svg_strokes(svg_path) == []


@pytest.mark.parametrize("preset", PRESETS)
def test_black_image_draws_each_band(preset: str, tmp_path: Path) -> None:
    """Every configured band draws on an all-black page."""
    image = make_flat_image(tmp_path / "black_bands.png", "black")
    svg_path = tmp_path / "black_bands.svg"
    convert_preset(image, preset, svg_path)
    strokes = parse_svg_strokes(svg_path)
    assert set(band_spacings(strokes, band_angles(preset))) == set(band_angles(preset))


def test_photo_hatch_uses_five_times_fewer_pen_lifts(
    hatch_report_factory: Callable[[str, str], HatchReport],
    tmp_path: Path,
) -> None:
    """Hatch should use at most one fifth of Sketch Lines' pen lifts.

    The comparison uses the uncapped Sketch Lines cost this gate was calibrated
    against. The per-tone cap deliberately stops the dark tone early, so its
    capped stroke count is not the baseline for an unrelated hatch cost gate.
    """
    hatch = hatch_report_factory("photo.jpg", GATE_PRESET)
    sketch_svg = tmp_path / "sketch_photo.svg"
    convert_preset(
        REFERENCE_DIR / "photo.jpg",
        "sketch_lines",
        sketch_svg,
        "-s",
        "max_tone_ink=1.0",
    )
    sketch_lifts = pen_lifts(parse_svg_strokes(sketch_svg))
    click.echo(f"Measured pen lifts on photo.jpg: hatch {hatch.lifts}, Sketch Lines {sketch_lifts}")
    assert hatch.lifts * 5 <= sketch_lifts, (
        f"hatch {hatch.lifts} lifts, Sketch Lines {sketch_lifts} lifts"
    )


def test_photo_converts_within_the_wall_time_limit(
    hatch_report_factory: Callable[[str, str], HatchReport],
) -> None:
    """The default working resolution converts a photo well under 30 s."""
    report = hatch_report_factory("photo.jpg", GATE_PRESET)
    assert report.working_size[0] == 525
    assert report.wall_seconds < MAX_WALL_SECONDS, report.wall_seconds


def test_convert_with_fixed_seed_is_byte_identical(tmp_path: Path) -> None:
    """A seeded run with jitter writes the same SVG twice."""
    image = make_jitter_image(tmp_path / "jitter.png")
    first = tmp_path / "first.svg"
    second = tmp_path / "second.svg"
    for output in (first, second):
        invocation = CliRunner().invoke(
            cli_main,
            [
                "convert",
                # Gates measure the algorithm itself; the ink coverage cap is tested separately.
                "--max-coverage",
                "1",
                str(image),
                "-o",
                str(output),
                "--pfm",
                GATE_PRESET,
                "--paper",
                "a5",
                "--pen",
                f"{PEN_WIDTH_MM}",
                "-s",
                "jitter=0.5",
                "-s",
                f"seed={SEED}",
                "--no-vpype",
                "--quiet",
            ],
            env={"XDG_CONFIG_HOME": str(tmp_path / "config")},
        )
        assert invocation.exit_code == 0, invocation.output
    assert first.read_bytes() == second.read_bytes()
