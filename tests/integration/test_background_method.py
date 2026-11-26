"""End-to-end tests for the background method on lighting gradients.

The gradient fixture is a white page dimmed linearly by 15% with one dark line.
The default local paper field follows that dimming, so only the line is ink.
The old global colour mask misses it at a lower threshold, which is the LUC-114
reproduction: pale paper becomes a light pen's scribble.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from penpath.cli.main import main
from penpath.core.svg_parse import list_svg_layers, parse_svg_strokes

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
GRADIENT = FIXTURES / "images/background/gradient_on_white.png"
LIGHT = "stabilo_88_light_blue"
DARK = "stabilo_88_black"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _convert(
    runner: CliRunner, output: Path, tmp_path: Path, *flags: str, palette: bool = True
) -> Result:
    """Run convert on the gradient fixture with a fixed seed and direct export."""
    options = ["--palette", "stabilo_88"] if palette else []
    return runner.invoke(
        main,
        [
            "convert",
            str(GRADIENT),
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
    layers = [layer_id for layer_id, name in list_svg_layers(svg) if name == label]
    return sum(len(parse_svg_strokes(svg, layer=layer_id)) for layer_id in layers)


def _project(tmp_path: Path, output: Path, method: str) -> Path:
    """Write a project file with an explicit background method."""
    project = tmp_path / "project.yaml"
    project.write_text(
        f"""version: 1
image:
  path: "{GRADIENT}"
  filters:
    steps: []
  dpi: 300
  background_method: {method}
  background_threshold: 5.0
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


class TestGradientAtTheCLI:
    """The default keeps the page clean; global reproduces the pale scribble."""

    def test_default_local_draws_only_the_line(self, runner: CliRunner, tmp_path: Path) -> None:
        output = tmp_path / "local.svg"
        result = _convert(runner, output, tmp_path)
        assert result.exit_code == 0, result.output
        assert "(local method)" in result.output
        assert _stroke_count(output, LIGHT) == 0
        assert _stroke_count(output, DARK) > 0
        assert all(
            _stroke_count(output, name) == 0 for name, _ in list_svg_layers(output) if name != DARK
        )

    def test_global_draws_the_pale_gradient_ends(self, runner: CliRunner, tmp_path: Path) -> None:
        output = tmp_path / "global.svg"
        result = _convert(
            runner, output, tmp_path, "--background-method", "global", "--background-threshold", "5"
        )
        assert result.exit_code == 0, result.output
        assert "(global method)" in result.output
        assert _stroke_count(output, LIGHT) > 0
        assert _stroke_count(output, DARK) > 0

    def test_local_still_draws_only_the_line_at_the_same_threshold(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        output = tmp_path / "local_t5.svg"
        result = _convert(runner, output, tmp_path, "--background-threshold", "5")
        assert result.exit_code == 0, result.output
        assert _stroke_count(output, LIGHT) == 0
        assert _stroke_count(output, DARK) > 0

    def test_flag_enables_masking_for_a_single_pen(self, runner: CliRunner, tmp_path: Path) -> None:
        plain = tmp_path / "plain.svg"
        masked = tmp_path / "masked.svg"
        assert _convert(runner, plain, tmp_path, palette=False).exit_code == 0
        result = _convert(runner, masked, tmp_path, "--background-method", "global", palette=False)
        assert result.exit_code == 0, result.output
        assert masked.read_bytes() != plain.read_bytes()

    def test_no_background_wins_over_the_method(self, runner: CliRunner, tmp_path: Path) -> None:
        plain = tmp_path / "plain.svg"
        overridden = tmp_path / "overridden.svg"
        assert _convert(runner, plain, tmp_path, palette=False).exit_code == 0
        result = _convert(
            runner,
            overridden,
            tmp_path,
            "--background-method",
            "local",
            "--no-background",
            palette=False,
        )
        assert result.exit_code == 0, result.output
        assert overridden.read_bytes() == plain.read_bytes()
        assert "Masking paper background" not in result.output

    @pytest.mark.parametrize("value", ["diagonal", "GLOBAL", ""])
    def test_invalid_method_is_a_usage_error(
        self, runner: CliRunner, tmp_path: Path, value: str
    ) -> None:
        result = _convert(runner, tmp_path / "bad.svg", tmp_path, "--background-method", value)
        assert result.exit_code == 2
        assert "--background-method" in result.output


class TestBackgroundMethodProjectFilesAtTheCLI:
    """The YAML key drives the mask and the CLI flag overrides it."""

    def test_project_method_drives_the_cli(self, runner: CliRunner, tmp_path: Path) -> None:
        output = tmp_path / "from_project.svg"
        project = _project(tmp_path, output, "global")
        result = runner.invoke(
            main,
            ["convert", str(GRADIENT), "-p", str(project), "-o", str(output), "--no-vpype"],
            env={"XDG_CONFIG_HOME": str(tmp_path / "config")},
        )
        assert result.exit_code == 0, result.output
        assert "(global method)" in result.output
        assert _stroke_count(output, LIGHT) > 0

    def test_cli_method_overrides_the_project(self, runner: CliRunner, tmp_path: Path) -> None:
        output = tmp_path / "overridden.svg"
        project = _project(tmp_path, output, "global")
        result = runner.invoke(
            main,
            [
                "convert",
                str(GRADIENT),
                "-p",
                str(project),
                "-o",
                str(output),
                "--background-method",
                "local",
                "--no-vpype",
            ],
            env={"XDG_CONFIG_HOME": str(tmp_path / "config")},
        )
        assert result.exit_code == 0, result.output
        assert "(local method)" in result.output
        assert _stroke_count(output, LIGHT) == 0
        assert _stroke_count(output, DARK) > 0
