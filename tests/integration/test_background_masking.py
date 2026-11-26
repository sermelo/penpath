"""End-to-end tests for masking paper before palette separation."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner, Result
from PIL import Image
from shapely import LineString

from penpath.cli.main import main
from penpath.core.image.background import remove_background
from penpath.core.image.separate import separate_palette
from penpath.core.svg_parse import list_svg_layers, parse_svg_strokes
from penpath.presets.palettes import get_palette

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PENCIL = FIXTURES / "images/background/pencil_on_pale_grey.png"
GOLDEN = FIXTURES / "golden/svg"
PALETTE_BEFORE = GOLDEN / "pencil_palette_before_background.svg"
SINGLE_BEFORE = GOLDEN / "single_pen_before_background.svg"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _convert(
    runner: CliRunner, output: Path, tmp_path: Path, *flags: str, palette: bool = False
) -> Result:
    """Run convert on the pencil fixture with a fixed seed and direct export."""
    options = ["--palette", "stabilo_88"] if palette else []
    return runner.invoke(
        main,
        [
            "convert",
            str(PENCIL),
            "-o",
            str(output),
            "-s",
            "seed=42",
            "--no-vpype",
            *options,
            *flags,
        ],
        env={"XDG_CONFIG_HOME": str(tmp_path / "config")},
    )


def _layer_geometry(svg: Path, label: str) -> tuple[int, float, tuple[float, float, float, float]]:
    """Return stroke count, pen-down length in mm and the stroke bounding box."""
    layer_ids = [layer_id for layer_id, name in list_svg_layers(svg) if name == label]
    strokes = [
        stroke for layer_id in layer_ids for stroke in parse_svg_strokes(svg, layer=layer_id)
    ]
    points = [point for stroke in strokes for point in stroke.polyline]
    if points:
        bbox = (
            min(point[0] for point in points),
            max(point[0] for point in points),
            min(point[1] for point in points),
            max(point[1] for point in points),
        )
    else:
        bbox = (0.0, 0.0, 0.0, 0.0)
    length = sum(LineString(stroke.polyline).length for stroke in strokes)
    return len(strokes), length, bbox


class TestBackgroundAtTheCLI:
    """The default path is unchanged; masking is opt-in for a single pen."""

    def test_single_pen_default_matches_prechange_svg(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        output = tmp_path / "single.svg"
        result = _convert(runner, output, tmp_path)
        assert result.exit_code == 0, result.output
        assert output.read_bytes() == SINGLE_BEFORE.read_bytes()

    def test_no_background_matches_prechange_palette_svg(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        output = tmp_path / "before.svg"
        result = _convert(runner, output, tmp_path, "--no-background", palette=True)
        assert result.exit_code == 0, result.output
        assert output.read_bytes() == PALETTE_BEFORE.read_bytes()

    def test_palette_reports_detected_paper_and_masked_percent(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        output = tmp_path / "palette.svg"
        result = _convert(runner, output, tmp_path, palette=True)
        assert result.exit_code == 0, result.output
        assert "Paper colour: #" in result.output
        assert "masked " in result.output and "% of pixels as no ink" in result.output
        assert "[2/6] Masking paper background" in result.output

    def test_quiet_suppresses_the_report(self, runner: CliRunner, tmp_path: Path) -> None:
        output = tmp_path / "quiet.svg"
        result = _convert(runner, output, tmp_path, "--quiet", palette=True)
        assert result.exit_code == 0, result.output
        assert result.output == ""

    def test_background_flag_enables_single_pen_masking(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        plain = tmp_path / "plain.svg"
        masked = tmp_path / "masked.svg"
        assert _convert(runner, plain, tmp_path).exit_code == 0
        result = _convert(runner, masked, tmp_path, "--background")
        assert result.exit_code == 0, result.output
        assert masked.read_bytes() != plain.read_bytes()

    def test_threshold_enables_masking_and_no_background_wins(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        tuned = tmp_path / "tuned.svg"
        disabled = tmp_path / "disabled.svg"
        result = _convert(runner, tuned, tmp_path, "--background-threshold", "2")
        assert result.exit_code == 0, result.output
        assert tuned.read_bytes() != SINGLE_BEFORE.read_bytes()
        result = _convert(
            runner, disabled, tmp_path, "--background-threshold", "2", "--no-background"
        )
        assert result.exit_code == 0, result.output
        assert disabled.read_bytes() == SINGLE_BEFORE.read_bytes()

    @pytest.mark.parametrize("value", ["-1", "nan", "inf"])
    def test_invalid_threshold_is_a_usage_error(
        self, runner: CliRunner, tmp_path: Path, value: str
    ) -> None:
        result = _convert(runner, tmp_path / "bad.svg", tmp_path, "--background-threshold", value)
        assert result.exit_code == 2
        assert "--background-threshold" in result.output

    def test_project_background_fields_override_the_mode(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        off = tmp_path / "off.svg"
        on = tmp_path / "on.svg"
        project = tmp_path / "project.yaml"
        project.write_text(
            f"""version: 1
image:
  path: "{PENCIL}"
  filters:
    steps: []
  dpi: 300
  background: false
  background_threshold: 10.0
paper:
  name: a4
  width_mm: 210.0
  height_mm: 297.0
palette: stabilo_88
pfm:
  pfm_type: sketch_lines
  settings:
    seed: 42
output_path: "{off}"
"""
        )
        result = runner.invoke(
            main,
            ["convert", str(PENCIL), "-p", str(project), "--no-vpype"],
            env={"XDG_CONFIG_HOME": str(tmp_path / "config")},
        )
        assert result.exit_code == 0, result.output
        assert off.read_bytes() == PALETTE_BEFORE.read_bytes()

        project.write_text(project.read_text().replace("background: false", "background: true"))
        result = runner.invoke(
            main,
            ["convert", str(PENCIL), "-p", str(project), "-o", str(on), "--no-vpype"],
            env={"XDG_CONFIG_HOME": str(tmp_path / "config")},
        )
        assert result.exit_code == 0, result.output
        assert on.read_bytes() != PALETTE_BEFORE.read_bytes()


class TestPaletteDrawsOnlyTheDrawing:
    """The light pen can no longer cover the paper on the synthetic fixture."""

    def test_lightest_pen_layer_is_empty_and_dark_pen_stays_on_the_sketch(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        output = tmp_path / "palette.svg"
        result = _convert(runner, output, tmp_path, "--quiet", palette=True)
        assert result.exit_code == 0, result.output

        before_count, before_length, _ = _layer_geometry(PALETTE_BEFORE, "stabilo_88_light_blue")
        light_count, light_length, _ = _layer_geometry(output, "stabilo_88_light_blue")
        dark_count, dark_length, dark_bbox = _layer_geometry(output, "stabilo_88_black")
        drawing_bbox = _layer_geometry(PALETTE_BEFORE, "stabilo_88_black")[2]

        assert before_count > 0 and before_length > 8000.0
        assert light_count == 0 and light_length == 0.0
        assert dark_count > 0 and dark_length == pytest.approx(3220.6, abs=1.0)
        assert dark_bbox == pytest.approx(drawing_bbox, abs=0.1)

    def test_all_palette_channels_are_white_outside_the_sketch(self) -> None:
        masked = remove_background(Image.open(PENCIL))
        channels = separate_palette(masked, get_palette("stabilo_88").pens)
        for _, channel in channels:
            pixels = np.asarray(channel)
            assert pixels[:20, :].min() == 255
            assert pixels[-20:, :].min() == 255
