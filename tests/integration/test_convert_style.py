"""End-to-end tests for ``penpath convert --style``."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from click.testing import CliRunner, Result
from PIL import Image, ImageDraw
from shapely import LineString

from penpath.cli.main import main
from penpath.core import convert as convert_module
from penpath.core import get_style
from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings
from penpath.core.image.pipeline import FilterPipeline
from penpath.core.models import ImageRef, Paper, Pen, Project, SketchLinesPFM
from penpath.core.project import save_yaml
from penpath.presets.pfms import PFM_PRESETS


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def image(tmp_path: Path) -> Path:
    """A small deterministic photo-like image with a dark subject."""
    result = tmp_path / "scene.jpg"
    canvas = Image.new("RGB", (200, 200), "white")
    pixels = canvas.load()
    for y in range(200):
        for x in range(200):
            value = int(255 * (1 - (x + y) / 420))
            pixels[x, y] = (value, value, value)
    ImageDraw.Draw(canvas).ellipse([60, 60, 140, 140], fill=(20, 20, 20))
    canvas.save(result, quality=95)
    return result


def _convert(runner: CliRunner, image: Path, output: Path, *flags: str, seed: str = "42") -> Result:
    """Run convert as a user would, with a fixed seed and direct SVG export."""
    return runner.invoke(
        main,
        [
            "convert",
            str(image),
            "-o",
            str(output),
            "-s",
            f"seed={seed}",
            "--no-vpype",
            "--quiet",
            *flags,
        ],
    )


def _capture_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> list[SketchLinesSettings]:
    """Replace the PFM so style settings reach a spy instead of the algorithm."""
    seen: list[SketchLinesSettings] = []
    real_get_pfm = convert_module.get_pfm

    def capture(pfm_type: str) -> tuple[Callable[..., list[LineString]], type]:
        _, model = real_get_pfm(pfm_type)

        def stub(image: object, settings: SketchLinesSettings) -> list[LineString]:
            seen.append(settings)
            return [LineString([(0.0, 0.0), (5.0, 5.0)])]

        return stub, model

    monkeypatch.setattr(convert_module, "get_pfm", capture)
    return seen


def _paths(path: Path) -> int:
    """Count drawn paths in an SVG."""
    return path.read_text(encoding="utf-8").count("<path")


class TestStyleCli:
    """The CLI accepts exactly the three saved looks."""

    def test_help_lists_all_styles(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["convert", "--help"])
        assert result.exit_code == 0
        assert "--style" in result.output
        for name in ("sketch", "hatch", "outline"):
            assert name in result.output

    def test_unknown_style_exits_2_and_lists_valid_names(
        self, runner: CliRunner, image: Path, tmp_path: Path
    ) -> None:
        output = tmp_path / "bad.svg"
        result = _convert(runner, image, output, "--style", "scribble")
        assert result.exit_code == 2
        for name in ("sketch", "hatch", "outline"):
            assert name in result.output
        assert not output.exists()

    @pytest.mark.parametrize("style", ["sketch", "hatch", "outline"])
    def test_each_style_resolves_its_settings(
        self,
        runner: CliRunner,
        image: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        style: str,
    ) -> None:
        seen = _capture_settings(monkeypatch)
        result = _convert(runner, image, tmp_path / f"{style}.svg", "--style", style)
        assert result.exit_code == 0, result.output
        assert len(seen) == 1
        expected = get_style(style).sketch_lines
        for key in expected.model_fields_set:
            assert getattr(seen[0], key) == getattr(expected, key)
            assert key in seen[0].model_fields_set

    def test_s_override_wins_over_style_value(
        self,
        runner: CliRunner,
        image: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        seen = _capture_settings(monkeypatch)
        result = _convert(
            runner,
            image,
            tmp_path / "override.svg",
            "--style",
            "hatch",
            "-s",
            "angle_range=10,20",
        )
        assert result.exit_code == 0, result.output
        assert seen[0].angle_range == (10.0, 20.0)
        assert seen[0].line_density == get_style("hatch").sketch_lines.line_density

    def test_explicit_non_default_pfm_wins_over_style_settings(
        self,
        runner: CliRunner,
        image: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        seen = _capture_settings(monkeypatch)
        result = _convert(
            runner,
            image,
            tmp_path / "pfm.svg",
            "--style",
            "hatch",
            "--pfm",
            "fine",
        )
        assert result.exit_code == 0, result.output
        assert seen[0].line_density == PFM_PRESETS["fine"].line_density
        assert seen[0].angle_range == PFM_PRESETS["fine"].angle_range

    def test_default_pfm_does_not_override_the_style(
        self,
        runner: CliRunner,
        image: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        seen = _capture_settings(monkeypatch)
        result = _convert(
            runner,
            image,
            tmp_path / "default_pfm.svg",
            "--style",
            "hatch",
            "--pfm",
            "default",
        )
        assert result.exit_code == 0, result.output
        assert seen[0].angle_range == get_style("hatch").sketch_lines.angle_range


class TestDefaultPath:
    """Without --style the drawing is still the part 1 default."""

    def test_no_style_uses_the_part_one_default_settings(
        self,
        runner: CliRunner,
        image: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """With no style the PFM gets the shipped defaults and no extra keys."""
        seen = _capture_settings(monkeypatch)
        result = _convert(runner, image, tmp_path / "plain.svg")
        assert result.exit_code == 0, result.output
        assert len(seen) == 1
        assert seen[0].model_dump(exclude={"seed"}) == (
            SketchLinesSettings().model_dump(exclude={"seed"})
        )
        assert seen[0].model_fields_set == {"seed"}

    def test_no_style_and_sketch_are_byte_identical(
        self, runner: CliRunner, image: Path, tmp_path: Path
    ) -> None:
        plain = tmp_path / "plain.svg"
        sketch = tmp_path / "sketch.svg"
        assert _convert(runner, image, plain).exit_code == 0
        assert _convert(runner, image, sketch, "--style", "sketch").exit_code == 0
        assert plain.read_bytes() == sketch.read_bytes()


class TestOutlinePipeline:
    """The outline style really emits edges and tone, on both pen paths."""

    def test_outline_strokes_are_added_to_the_tone_pass(
        self, runner: CliRunner, image: Path, tmp_path: Path
    ) -> None:
        output = tmp_path / "outline.svg"
        tone_only = tmp_path / "tone.svg"
        result = _convert(runner, image, output, "--style", "outline")
        assert result.exit_code == 0, result.output

        settings = get_style("outline").sketch_lines
        flags: list[str] = []
        for key in settings.model_fields_set:
            value = getattr(settings, key)
            if isinstance(value, tuple):
                value = ",".join(str(item) for item in value)
            flags.extend(["-s", f"{key}={value}"])
        tone_result = _convert(runner, image, tone_only, *flags)
        assert tone_result.exit_code == 0, tone_result.output
        assert _paths(output) > _paths(tone_only)

    def test_palette_path_keeps_working(
        self, runner: CliRunner, image: Path, tmp_path: Path
    ) -> None:
        output = tmp_path / "palette.svg"
        result = _convert(runner, image, output, "--style", "outline", "--palette", "stabilo_88")
        assert result.exit_code == 0, result.output
        assert output.exists()
        assert _paths(output) > 0


class TestStyleInProjectFiles:
    """``style:`` round-trips and CLI flags still win over the saved look."""

    def _project(self, image: Path, output: Path, style: str) -> Path:
        path = output.with_suffix(".yaml")
        save_yaml(
            Project(
                image=ImageRef(path=image, filters=FilterPipeline(), dpi=300),
                paper=Paper(name="a4", width_mm=210.0, height_mm=297.0),
                pen=Pen(name="fine", width_mm=0.3),
                pfm=SketchLinesPFM(settings=SketchLinesSettings(seed=42)),
                style=style,
                output_path=output,
            ),
            path,
        )
        return path

    def test_style_from_project_runs_the_outline_pass(
        self, runner: CliRunner, image: Path, tmp_path: Path
    ) -> None:
        outline_out = tmp_path / "outline.svg"
        sketch_out = tmp_path / "sketch.svg"
        outline_project = self._project(image, outline_out, "outline")
        sketch_project = self._project(image, sketch_out, "sketch")

        result_outline = runner.invoke(
            main,
            ["convert", str(image), "-p", str(outline_project), "--no-vpype", "--quiet"],
        )
        result_sketch = runner.invoke(
            main,
            ["convert", str(image), "-p", str(sketch_project), "--no-vpype", "--quiet"],
        )
        assert result_outline.exit_code == 0, result_outline.output
        assert result_sketch.exit_code == 0, result_sketch.output
        assert _paths(outline_out) > _paths(sketch_out)

    def test_cli_style_overrides_project_style(
        self, runner: CliRunner, image: Path, tmp_path: Path
    ) -> None:
        override_out = tmp_path / "override.svg"
        saved_out = tmp_path / "saved_outline.svg"
        override_project = self._project(image, override_out, "outline")
        saved_project = self._project(image, saved_out, "outline")

        result_override = _convert(
            runner, image, override_out, "-p", str(override_project), "--style", "sketch"
        )
        result_saved = runner.invoke(
            main,
            ["convert", str(image), "-p", str(saved_project), "--no-vpype", "--quiet"],
        )
        assert result_override.exit_code == 0, result_override.output
        assert result_saved.exit_code == 0, result_saved.output
        assert _paths(override_out) < _paths(saved_out)

    def test_s_overrides_saved_pfm_settings(
        self,
        runner: CliRunner,
        image: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        seen = _capture_settings(monkeypatch)
        output = tmp_path / "saved_override.svg"
        project = self._project(image, output, "hatch")
        result = runner.invoke(
            main,
            [
                "convert",
                str(image),
                "-p",
                str(project),
                "-s",
                "angle_range=15,25",
                "--no-vpype",
                "--quiet",
            ],
        )
        assert result.exit_code == 0, result.output
        assert seen[0].angle_range == (15.0, 25.0)
        assert seen[0].seed == 42
