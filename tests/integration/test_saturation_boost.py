"""End-to-end tests for boosting muted colours before palette separation."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner, Result
from PIL import Image
from skimage.color import lab2rgb

from penpath.cli.main import main
from penpath.core.svg_parse import list_svg_layers, parse_svg_strokes

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
LANDSCAPE = FIXTURES / "images/saturation/muted_landscape.png"
GREEN = "stabilo_88_light_green"
BLUE = "stabilo_88_light_blue"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _convert(
    runner: CliRunner, output: Path, tmp_path: Path, *flags: str, palette: bool = True
) -> Result:
    """Run convert on the muted landscape with a fixed seed and direct export."""
    options = ["--palette", "stabilo_88"] if palette else []
    return runner.invoke(
        main,
        [
            "convert",
            str(LANDSCAPE),
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


def _stroke_count(svg: Path, label: str) -> int:
    """Count the strokes written for one pen layer."""
    layer_ids = [layer_id for layer_id, name in list_svg_layers(svg) if name == label]
    return sum(len(parse_svg_strokes(svg, layer=layer_id)) for layer_id in layer_ids)


class TestBoostAtTheCLI:
    """A muted landscape picks a green pen by hue; the boost still reports its factor."""

    def test_defaults_pick_green_without_reporting_a_factor(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        output = tmp_path / "default.svg"
        result = _convert(runner, output, tmp_path)
        assert result.exit_code == 0, result.output
        assert _stroke_count(output, GREEN) > 0
        assert _stroke_count(output, BLUE) == 0
        assert "Saturation factor" not in result.output

    def test_palette_adapt_uses_green_and_reports_the_factor(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        output = tmp_path / "adapt.svg"
        result = _convert(runner, output, tmp_path, "--palette-adapt")
        assert result.exit_code == 0, result.output
        assert _stroke_count(output, GREEN) > 0
        assert _stroke_count(output, BLUE) == 0
        assert "Saturation factor: 3.00 (palette-adapted)" in result.output
        assert "[3/8] Adapting saturation to palette" in result.output

    def test_manual_saturation_uses_green_and_reports_the_factor(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        output = tmp_path / "manual.svg"
        result = _convert(runner, output, tmp_path, "--saturation", "2.0")
        assert result.exit_code == 0, result.output
        assert _stroke_count(output, GREEN) > 0
        assert "Saturation factor: 2.00 (manual)" in result.output
        assert "[3/8] Boosting saturation" in result.output

    def test_explicit_saturation_wins_over_palette_adapt(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        plain = tmp_path / "plain.svg"
        output = tmp_path / "explicit.svg"
        assert _convert(runner, plain, tmp_path).exit_code == 0
        result = _convert(runner, output, tmp_path, "--palette-adapt", "--saturation", "1.0")
        assert result.exit_code == 0, result.output
        assert output.read_bytes() == plain.read_bytes()
        assert "Saturation factor" not in result.output

    def test_quiet_suppresses_the_report(self, runner: CliRunner, tmp_path: Path) -> None:
        output = tmp_path / "quiet.svg"
        result = _convert(runner, output, tmp_path, "--palette-adapt", "--quiet")
        assert result.exit_code == 0, result.output
        assert result.output == ""
        assert _stroke_count(output, GREEN) > 0

    def test_boost_lifts_below_threshold_chroma_into_the_hue_rule(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """A near-neutral green uses the Lab rule until boosting makes it chromatic."""
        chroma = 7.0
        a = chroma * np.cos(np.radians(131.0))
        b = chroma * np.sin(np.radians(131.0))
        rgb = tuple(
            int(value)
            for value in np.clip(
                np.rint(lab2rgb(np.array([[[60.0, a, b]]], dtype=np.float64))[0, 0] * 255.0),
                0,
                255,
            ).astype(np.uint8)
        )
        image = Image.new("RGB", (60, 60), "white")
        for y in range(2, 58):
            for x in range(2, 58):
                image.putpixel((x, y), rgb)
        source = tmp_path / "low_chroma.png"
        image.save(source)

        plain = tmp_path / "plain.svg"
        boosted = tmp_path / "boosted.svg"
        for output, flags in ((plain, []), (boosted, ["--saturation", "3.0"])):
            result = runner.invoke(
                main,
                [
                    "convert",
                    str(source),
                    "-o",
                    str(output),
                    "-s",
                    "seed=42",
                    "--no-vpype",
                    "--palette",
                    "stabilo_88",
                    "--no-auto-equalize",
                    *flags,
                ],
                env={"XDG_CONFIG_HOME": str(tmp_path / "config")},
            )
            assert result.exit_code == 0, result.output

        assert _stroke_count(plain, BLUE) > 0
        assert _stroke_count(plain, GREEN) == 0
        assert _stroke_count(boosted, GREEN) > 0
        assert _stroke_count(boosted, BLUE) == 0

    def test_single_pen_is_a_noop(self, runner: CliRunner, tmp_path: Path) -> None:
        plain = tmp_path / "plain.svg"
        boosted = tmp_path / "boosted.svg"
        assert _convert(runner, plain, tmp_path, palette=False).exit_code == 0
        result = _convert(
            runner, boosted, tmp_path, "--saturation", "2.0", "--palette-adapt", palette=False
        )
        assert result.exit_code == 0, result.output
        assert boosted.read_bytes() == plain.read_bytes()
        assert "Saturation factor" not in result.output

    @pytest.mark.parametrize("value", ["-0.1", "3.1", "nan", "inf"])
    def test_invalid_saturation_is_a_usage_error(
        self, runner: CliRunner, tmp_path: Path, value: str
    ) -> None:
        result = _convert(runner, tmp_path / "bad.svg", tmp_path, "--saturation", value)
        assert result.exit_code == 2
        assert "--saturation" in result.output


class TestSaturationProjectFilesAtTheCLI:
    """The project fields drive the boost, and CLI flags override them."""

    def _project(self, tmp_path: Path, output: Path, body: str) -> Path:
        project = tmp_path / "project.yaml"
        project.write_text(
            f"""version: 1
image:
  path: "{LANDSCAPE}"
  filters:
    steps: []
  dpi: 300
  saturation: {body}
paper:
  name: a4
  width_mm: 210.0
  height_mm: 297.0
palette: stabilo_88
pfm:
  pfm_type: sketch_lines
  settings:
    seed: 42
output_path: "{output}"
"""
        )
        return project

    def test_project_saturation_is_used(self, runner: CliRunner, tmp_path: Path) -> None:
        output = tmp_path / "from_project.svg"
        project = self._project(tmp_path, output, "2.0")
        result = runner.invoke(
            main,
            ["convert", str(LANDSCAPE), "-p", str(project), "--no-vpype"],
            env={"XDG_CONFIG_HOME": str(tmp_path / "config")},
        )
        assert result.exit_code == 0, result.output
        assert _stroke_count(output, GREEN) > 0
        assert "Saturation factor: 2.00 (manual)" in result.output

    def test_project_palette_adapt_is_used(self, runner: CliRunner, tmp_path: Path) -> None:
        output = tmp_path / "adapt_project.svg"
        project = self._project(tmp_path, output, "1.0")
        project.write_text(
            project.read_text().replace("  saturation: 1.0", "  palette_adapt: true")
        )
        result = runner.invoke(
            main,
            ["convert", str(LANDSCAPE), "-p", str(project), "--no-vpype"],
            env={"XDG_CONFIG_HOME": str(tmp_path / "config")},
        )
        assert result.exit_code == 0, result.output
        assert _stroke_count(output, GREEN) > 0
        assert "Saturation factor: 3.00 (palette-adapted)" in result.output

    def test_cli_saturation_overrides_the_project(self, runner: CliRunner, tmp_path: Path) -> None:
        output = tmp_path / "overridden.svg"
        project = self._project(tmp_path, output, "2.0")
        result = runner.invoke(
            main,
            [
                "convert",
                str(LANDSCAPE),
                "-p",
                str(project),
                "--saturation",
                "1.0",
                "--no-vpype",
            ],
            env={"XDG_CONFIG_HOME": str(tmp_path / "config")},
        )
        assert result.exit_code == 0, result.output
        assert _stroke_count(output, GREEN) > 0
        assert "Saturation factor" not in result.output
