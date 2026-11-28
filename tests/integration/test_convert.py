"""Integration tests for ``penpath convert`` settings and seed reproducibility."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from click.testing import CliRunner, Result
from PIL import Image
from shapely import LineString

from penpath.cli.main import main
from penpath.core import convert as convert_module
from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings
from penpath.core.drawing.registry import get_pfm
from penpath.core.image.pipeline import FilterPipeline
from penpath.core.models import ImageRef, Paper, Pen, Project, SketchLinesPFM
from penpath.core.project import save_yaml
from penpath.presets.palettes import get_palette
from penpath.presets.pfms import PFM_PRESETS

if TYPE_CHECKING:
    from pydantic import BaseModel

SVG_NS = "{http://www.w3.org/2000/svg}"
INKSCAPE_NS = "{http://www.inkscape.org/namespaces/inkscape}"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def reference_image(tmp_path: Path) -> Path:
    """A small deterministic gradient with a dark region, like a real reference."""
    image = Image.new("RGB", (200, 200), "white")
    pixels = image.load()
    for y in range(200):
        for x in range(200):
            value = int(255 * (1 - (x + y) / 400))
            if 50 < x < 150 and 50 < y < 150:
                value = int(value * 0.3)
            pixels[x, y] = (value, value, value)
    path = tmp_path / "reference.png"
    image.save(path)
    return path


def _convert(runner: CliRunner, image: Path, output: Path) -> Result:
    """Run convert as a user would, with a fixed seed and the direct SVG export."""
    return runner.invoke(
        main,
        ["convert", str(image), "-o", str(output), "-s", "seed=42", "--no-vpype"],
    )


def _convert_with_flags(runner: CliRunner, image: Path, output: Path, *flags: str) -> Result:
    """Run a silent, seeded, direct-export conversion with extra CLI flags."""
    return runner.invoke(
        main,
        [
            "convert",
            str(image),
            "-o",
            str(output),
            "-s",
            "seed=42",
            "--no-vpype",
            "--quiet",
            *flags,
        ],
    )


def _stroke_geometry(path: Path) -> list[str]:
    """Return the drawn paths of an SVG, ignoring pen name, colour and width."""
    root = ET.parse(path).getroot()
    return [el.get("d", "") for el in root.iter("{http://www.w3.org/2000/svg}path")]


@pytest.fixture
def low_contrast_image(tmp_path: Path) -> Path:
    """A washed-out image: one dark region over a narrow 60-180 grey ramp."""
    image = Image.new("L", (400, 400), "white")
    pixels = image.load()
    for y in range(400):
        for x in range(400):
            pixels[x, y] = 60 if 100 < x < 300 and 100 < y < 300 else 60 + int((x + y) / 800 * 120)
    path = tmp_path / "low_contrast.png"
    image.save(path)
    return path


@pytest.fixture
def full_range_image(tmp_path: Path) -> Path:
    """An image whose luminance already covers 0-255, with a dark square."""
    image = Image.new("L", (400, 400), "white")
    pixels = image.load()
    for y in range(400):
        for x in range(400):
            pixels[x, y] = 0 if 100 < x < 300 and 100 < y < 300 else int(255 * (x + y) / 798)
    path = tmp_path / "full_range.png"
    image.save(path)
    return path


@pytest.fixture
def wide_range_image(tmp_path: Path) -> Path:
    """An image spanning 31-255, like sphere.png, already wide enough to skip."""
    image = Image.new("L", (400, 400), "white")
    pixels = image.load()
    for y in range(400):
        for x in range(400):
            pixels[x, y] = 31 if 100 < x < 300 and 100 < y < 300 else 31 + int(224 * (x + y) / 798)
    path = tmp_path / "wide_range.png"
    image.save(path)
    return path


def _write_equalize_project(tmp_path: Path, image: Path, output: Path, enabled: bool) -> Path:
    """Write a project YAML that explicitly sets image.auto_equalize."""
    path = tmp_path / f"equalize_{str(enabled).lower()}.yaml"
    path.write_text(
        f"""version: 1
image:
  path: "{image}"
  filters:
    steps: []
  dpi: 300
  auto_equalize: {str(enabled).lower()}
paper:
  name: a4
  width_mm: 210.0
  height_mm: 297.0
pen:
  name: fine
  width_mm: 0.3
pfm:
  pfm_type: sketch_lines
  settings:
    seed: 42
output_path: "{output}"
"""
    )
    return path


class TestConvertSeed:
    """The seed given on the command line must reach the drawing algorithm."""

    def test_cli_seed_reaches_pfm(
        self,
        runner: CliRunner,
        reference_image: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        seen: list[SketchLinesSettings] = []
        real_get_pfm = get_pfm

        def capture_pfm(pfm_type: str) -> tuple[Callable[..., list[LineString]], type[BaseModel]]:
            pfm_fn, settings_model = real_get_pfm(pfm_type)

            def wrapped(image: object, settings: SketchLinesSettings) -> list[LineString]:
                seen.append(settings)
                return pfm_fn(image, settings)

            return wrapped, settings_model

        monkeypatch.setattr(convert_module, "get_pfm", capture_pfm)
        result = _convert(runner, reference_image, tmp_path / "seeded.svg")
        assert result.exit_code == 0, result.output
        assert len(seen) == 1
        assert seen[0].seed == 42

    def test_seed_determinism(
        self, runner: CliRunner, reference_image: Path, tmp_path: Path
    ) -> None:
        """Two runs with the same seed give the same SVG and the same scores."""
        first = tmp_path / "a.svg"
        second = tmp_path / "b.svg"

        result_a = _convert(runner, reference_image, first)
        result_b = _convert(runner, reference_image, second)
        assert result_a.exit_code == 0, result_a.output
        assert result_b.exit_code == 0, result_b.output

        assert first.exists() and second.exists()
        assert first.read_bytes() == second.read_bytes()

        eval_a = runner.invoke(main, ["evaluate", str(reference_image), str(first), "--json"])
        eval_b = runner.invoke(main, ["evaluate", str(reference_image), str(second), "--json"])
        assert eval_a.exit_code == 0, eval_a.output
        assert eval_b.exit_code == 0, eval_b.output
        assert json.loads(eval_a.stdout) == json.loads(eval_b.stdout)

    def test_seed_from_project_file_is_deterministic(
        self, runner: CliRunner, reference_image: Path, tmp_path: Path
    ) -> None:
        """The seed stored in a project YAML reaches the algorithm too."""
        outputs = (tmp_path / "proj_a.svg", tmp_path / "proj_b.svg")
        for output in outputs:
            project_path = tmp_path / f"{output.stem}.yaml"
            save_yaml(
                Project(
                    image=ImageRef(path=reference_image, filters=FilterPipeline(), dpi=300),
                    paper=Paper(name="a4", width_mm=210.0, height_mm=297.0),
                    pen=Pen(name="fine", width_mm=0.3),
                    pfm=SketchLinesPFM(settings=SketchLinesSettings(seed=42)),
                    output_path=output,
                ),
                project_path,
            )
            result = runner.invoke(
                main,
                ["convert", str(reference_image), "-p", str(project_path), "--no-vpype"],
            )
            assert result.exit_code == 0, result.output

        assert outputs[0].read_bytes() == outputs[1].read_bytes()


class TestConvertSettings:
    """Every Sketch Lines setting must be reachable as `convert -s KEY=VALUE`."""

    ALL_SETTINGS: tuple[tuple[str, str, object], ...] = (
        ("line_density", "1.25", 1.25),
        ("max_fill", "90.0", 90.0),
        ("white_threshold", "0.9", 0.9),
        ("tone_coverage", "0.4", 0.4),
        ("tone_exponent", "0.7", 0.7),
        ("texture_limit", "0.6", 0.6),
        ("max_tone_ink", "0.7", 0.7),
        ("min_length", "3.0", 3.0),
        ("max_length", "60.0", 60.0),
        ("angle_range", "-80,-40", (-80.0, -40.0)),
        ("shading_enabled", "true", True),
        ("squiggle_enabled", "yes", True),
        ("erase_enabled", "false", False),
        ("seed", "42", 42),
        ("search_angle_step", "9.0", 9.0),
        ("sample_step", "7.0", 7.0),
        ("erase_min", "40.0", 40.0),
        ("erase_max", "90.0", 90.0),
        ("tone", "0.25", 0.25),
        ("erase_radius_min", "0.0", 0.0),
        ("erase_radius_max", "2.0", 2.0),
        ("squiggle_max_deviation", "0.5", 0.5),
        ("squiggle_min_length", "10", 10),
        ("squiggle_max_length", "200", 200),
        ("shading_threshold", "0.25", 0.25),
        ("max_strokes", "25", 25),
    )

    def _capture_settings(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> list[SketchLinesSettings]:
        """Replace the PFM with a stub so only settings propagation is tested."""
        seen: list[SketchLinesSettings] = []
        real_get_pfm = get_pfm

        def capture_pfm(pfm_type: str) -> tuple[Callable[..., list[LineString]], type[BaseModel]]:
            _, settings_model = real_get_pfm(pfm_type)

            def stub(image: object, settings: SketchLinesSettings) -> list[LineString]:
                seen.append(settings)
                return [LineString([(0.0, 0.0), (10.0, 10.0)])]

            return stub, settings_model

        monkeypatch.setattr(convert_module, "get_pfm", capture_pfm)
        return seen

    def test_setting_table_covers_every_model_field(self) -> None:
        """A new setting must be added to this table and to docs/CLI.md."""
        covered = {key for key, _, _ in self.ALL_SETTINGS}
        assert covered == set(SketchLinesSettings.model_fields)

    @pytest.mark.parametrize(("key", "value", "expected"), ALL_SETTINGS)
    def test_cli_setting_reaches_algorithm(
        self,
        runner: CliRunner,
        reference_image: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        key: str,
        value: str,
        expected: object,
    ) -> None:
        seen = self._capture_settings(monkeypatch)
        result = runner.invoke(
            main,
            [
                "convert",
                str(reference_image),
                "-o",
                str(tmp_path / "settings.svg"),
                "--no-vpype",
                "-s",
                f"{key}={value}",
            ],
        )
        assert result.exit_code == 0, result.output
        assert len(seen) == 1
        assert getattr(seen[0], key) == expected

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("bogus", "1"),
            ("angle_range", "abc"),
            ("line_density", "99"),
            ("min_length", "100"),
        ],
    )
    def test_invalid_setting_is_an_actionable_usage_error(
        self,
        runner: CliRunner,
        reference_image: Path,
        tmp_path: Path,
        key: str,
        value: str,
    ) -> None:
        result = runner.invoke(
            main,
            [
                "convert",
                str(reference_image),
                "-o",
                str(tmp_path / "invalid.svg"),
                "--no-vpype",
                "-s",
                f"{key}={value}",
            ],
        )
        assert result.exit_code == 2
        assert "PFM setting" in result.output
        assert key in result.output

    def test_preset_name_and_override_reach_algorithm(
        self,
        runner: CliRunner,
        reference_image: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """`--pfm <preset>` loads the preset and `-s` overrides one of its keys."""
        seen = self._capture_settings(monkeypatch)
        result = runner.invoke(
            main,
            [
                "convert",
                str(reference_image),
                "-o",
                str(tmp_path / "preset.svg"),
                "--no-vpype",
                "--pfm",
                "fine",
                "-s",
                "seed=42",
            ],
        )
        assert result.exit_code == 0, result.output
        assert len(seen) == 1
        preset = PFM_PRESETS["fine"]
        assert seen[0].seed == 42
        assert seen[0].line_density == preset.line_density
        assert seen[0].search_angle_step == preset.search_angle_step

    def test_setting_changes_the_drawn_geometry(
        self, runner: CliRunner, reference_image: Path, tmp_path: Path
    ) -> None:
        """End to end: a `-s` override changes the SVG a user gets, with a fixed seed."""
        plain = tmp_path / "plain.svg"
        dense = tmp_path / "dense.svg"
        plain_result = runner.invoke(
            main,
            ["convert", str(reference_image), "-o", str(plain), "--no-vpype", "-s", "seed=42"],
        )
        dense_result = runner.invoke(
            main,
            [
                "convert",
                str(reference_image),
                "-o",
                str(dense),
                "--no-vpype",
                "-s",
                "seed=42",
                "-s",
                "line_density=2.0",
                "-s",
                "min_length=6.0",
                "-s",
                "max_length=60.0",
            ],
        )
        assert plain_result.exit_code == 0, plain_result.output
        assert dense_result.exit_code == 0, dense_result.output
        assert _stroke_geometry(plain) != _stroke_geometry(dense)


class TestConvertPenForms:
    """Every documented --pen form resolves when a user runs convert."""

    @pytest.mark.parametrize(
        ("spec", "expected_color", "expected_width"),
        [
            ("0.4", "#000000", "0.4"),
            ("0.4,#FF6600", "#FF6600", "0.4"),
            ("0.4,#000000,fineliner", "#000000", "0.4"),
            ("fine", "#000000", "0.3"),
        ],
    )
    def test_preset_and_inline_forms_reach_the_svg(
        self,
        runner: CliRunner,
        reference_image: Path,
        tmp_path: Path,
        spec: str,
        expected_color: str,
        expected_width: str,
    ) -> None:
        output = tmp_path / "pen.svg"
        result = _convert_with_flags(runner, reference_image, output, "--pen", spec)
        assert result.exit_code == 0, result.output

        paths = list(ET.parse(output).getroot().iter(SVG_NS + "path"))
        assert paths
        assert {path.get("stroke") for path in paths} == {expected_color}
        assert {path.get("stroke-width") for path in paths} == {expected_width}

    def test_unknown_type_names_the_field_and_accepted_values(
        self, runner: CliRunner, reference_image: Path, tmp_path: Path
    ) -> None:
        output = tmp_path / "bad_type.svg"
        result = _convert_with_flags(runner, reference_image, output, "--pen", "0.4,#000000,bogus")
        assert result.exit_code == 2
        assert "pen_type" in result.output
        assert "fineliner" in result.output
        assert "Unknown pen" not in result.output
        assert not output.exists()


class TestConvertAutoEqualize:
    """Auto levels are on by default and can be turned off per run or project."""

    def test_default_differs_from_no_auto_equalize_on_low_contrast(
        self, runner: CliRunner, low_contrast_image: Path, tmp_path: Path
    ) -> None:
        """End to end: normalization changes the drawing of a washed-out image."""
        default = tmp_path / "default.svg"
        disabled = tmp_path / "disabled.svg"
        result_on = _convert_with_flags(runner, low_contrast_image, default)
        result_off = _convert_with_flags(runner, low_contrast_image, disabled, "--no-auto-equalize")
        assert result_on.exit_code == 0, result_on.output
        assert result_off.exit_code == 0, result_off.output
        assert _stroke_geometry(default) != _stroke_geometry(disabled)

    def test_no_project_default_matches_explicit_auto_equalize(
        self, runner: CliRunner, low_contrast_image: Path, tmp_path: Path
    ) -> None:
        """With no project, leaving the flag out is the same as passing it."""
        default = tmp_path / "default.svg"
        explicit = tmp_path / "explicit.svg"
        result_default = _convert_with_flags(runner, low_contrast_image, default)
        result_explicit = _convert_with_flags(
            runner, low_contrast_image, explicit, "--auto-equalize"
        )
        assert result_default.exit_code == 0, result_default.output
        assert result_explicit.exit_code == 0, result_explicit.output
        assert default.read_bytes() == explicit.read_bytes()

    def test_full_range_image_is_byte_identical(
        self, runner: CliRunner, full_range_image: Path, tmp_path: Path
    ) -> None:
        """A full-range image is a no-op, so the flag cannot change its SVG."""
        enabled = tmp_path / "enabled.svg"
        disabled = tmp_path / "disabled.svg"
        result_on = _convert_with_flags(runner, full_range_image, enabled)
        result_off = _convert_with_flags(runner, full_range_image, disabled, "--no-auto-equalize")
        assert result_on.exit_code == 0, result_on.output
        assert result_off.exit_code == 0, result_off.output
        assert enabled.read_bytes() == disabled.read_bytes()

    def test_wide_range_image_is_byte_identical(
        self, runner: CliRunner, wide_range_image: Path, tmp_path: Path
    ) -> None:
        """A 31-255 image is a no-op, so the flag cannot change its SVG."""
        enabled = tmp_path / "enabled.svg"
        disabled = tmp_path / "disabled.svg"
        result_on = _convert_with_flags(runner, wide_range_image, enabled)
        result_off = _convert_with_flags(runner, wide_range_image, disabled, "--no-auto-equalize")
        assert result_on.exit_code == 0, result_on.output
        assert result_off.exit_code == 0, result_off.output
        assert enabled.read_bytes() == disabled.read_bytes()

    def test_project_yaml_false_is_respected(
        self, runner: CliRunner, low_contrast_image: Path, tmp_path: Path
    ) -> None:
        """A saved `auto_equalize: false` keeps the original tones."""
        output_off = tmp_path / "project_off.svg"
        output_on = tmp_path / "project_on.svg"
        project_off = _write_equalize_project(
            tmp_path, low_contrast_image, output_off, enabled=False
        )
        project_on = _write_equalize_project(tmp_path, low_contrast_image, output_on, enabled=True)
        result_off = runner.invoke(
            main,
            ["convert", str(low_contrast_image), "-p", str(project_off), "--no-vpype", "--quiet"],
        )
        result_on = runner.invoke(
            main,
            ["convert", str(low_contrast_image), "-p", str(project_on), "--no-vpype", "--quiet"],
        )
        assert result_off.exit_code == 0, result_off.output
        assert result_on.exit_code == 0, result_on.output
        assert output_off.exists() and output_on.exists()
        assert _stroke_geometry(output_off) != _stroke_geometry(output_on)

    def test_cli_flag_overrides_project_yaml(
        self, runner: CliRunner, low_contrast_image: Path, tmp_path: Path
    ) -> None:
        """`--auto-equalize` wins over a project that disabled the feature."""
        output_off = tmp_path / "yaml_off.svg"
        output_override = tmp_path / "override.svg"
        output_on = tmp_path / "yaml_on.svg"
        project_off = _write_equalize_project(
            tmp_path, low_contrast_image, output_off, enabled=False
        )
        project_on = _write_equalize_project(tmp_path, low_contrast_image, output_on, enabled=True)
        result_off = runner.invoke(
            main,
            ["convert", str(low_contrast_image), "-p", str(project_off), "--no-vpype", "--quiet"],
        )
        result_override = runner.invoke(
            main,
            [
                "convert",
                str(low_contrast_image),
                "-p",
                str(project_off),
                "--auto-equalize",
                "-o",
                str(output_override),
                "--no-vpype",
                "--quiet",
            ],
        )
        result_on = runner.invoke(
            main,
            ["convert", str(low_contrast_image), "-p", str(project_on), "--no-vpype", "--quiet"],
        )
        assert result_off.exit_code == 0, result_off.output
        assert result_override.exit_code == 0, result_override.output
        assert result_on.exit_code == 0, result_on.output
        assert _stroke_geometry(output_off) != _stroke_geometry(output_override)
        assert output_override.read_bytes() == output_on.read_bytes()

    def test_help_documents_both_flags(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["convert", "--help"])
        assert result.exit_code == 0, result.output
        assert "--auto-equalize" in result.output
        assert "--no-auto-equalize" in result.output


class TestConvertPalette:
    """A palette splits the image and produces one layer per used pen."""

    def test_project_palette_key_produces_pen_layers(
        self, runner: CliRunner, reference_image: Path, tmp_path: Path
    ) -> None:
        output = tmp_path / "from_palette.svg"
        project_path = tmp_path / "project.yaml"
        project_path.write_text(
            f"""version: 1
image:
  path: "{reference_image}"
  filters:
    steps: []
  dpi: 300
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
        result = runner.invoke(
            main,
            ["convert", str(reference_image), "-p", str(project_path), "--no-vpype"],
        )
        assert result.exit_code == 0, result.output

        layers = [
            group
            for group in ET.parse(output).getroot().iter(SVG_NS + "g")
            if group.get(INKSCAPE_NS + "groupmode") == "layer"
        ]
        assert layers
        names = {pen.name for pen in get_palette("stabilo_88").pens}
        assert [layer.get("id") for layer in layers] == [
            f"layer{index}" for index in range(1, len(layers) + 1)
        ]
        assert {layer.get(INKSCAPE_NS + "label") for layer in layers} <= names

    def test_palette_draws_different_strokes_than_a_single_pen(
        self, runner: CliRunner, reference_image: Path, tmp_path: Path
    ) -> None:
        """With a fixed seed, separation changes which pixels each pen draws."""
        plain = tmp_path / "plain.svg"
        palette = tmp_path / "palette.svg"
        plain_result = _convert(runner, reference_image, plain)
        palette_result = runner.invoke(
            main,
            [
                "convert",
                str(reference_image),
                "-o",
                str(palette),
                "-s",
                "seed=42",
                "--no-vpype",
                "--palette",
                "stabilo_88",
            ],
        )
        assert plain_result.exit_code == 0, plain_result.output
        assert palette_result.exit_code == 0, palette_result.output
        assert _stroke_geometry(plain) != _stroke_geometry(palette)

    def test_project_pens_list_uses_the_first_pen_and_a_key_layer(
        self, runner: CliRunner, reference_image: Path, tmp_path: Path
    ) -> None:
        output = tmp_path / "from_pens.svg"
        project_path = tmp_path / "pens.yaml"
        project_path.write_text(
            f"""version: 1
image:
  path: "{reference_image}"
  filters:
    steps: []
  dpi: 300
paper:
  name: a4
  width_mm: 210.0
  height_mm: 297.0
pens:
  - name: first
    width_mm: 0.5
    color: "#FF0000"
  - name: second
    width_mm: 0.4
    color: "#0000FF"
pfm:
  pfm_type: sketch_lines
  settings:
    seed: 42
output_path: "{output}"
"""
        )
        result = runner.invoke(
            main,
            ["convert", str(reference_image), "-p", str(project_path), "--no-vpype"],
        )
        assert result.exit_code == 0, result.output
        svg = output.read_text()
        assert 'inkscape:label="first"' in svg
        assert 'stroke="#FF0000"' in svg
        assert "second" not in svg
        assert 'inkscape:label="key"' in svg
        assert svg.count('inkscape:groupmode="layer"') == 2  # first pen + key layer

    def test_project_pen_and_palette_is_a_clear_error(
        self, runner: CliRunner, reference_image: Path, tmp_path: Path
    ) -> None:
        output = tmp_path / "conflict.svg"
        project_path = tmp_path / "conflict.yaml"
        project_path.write_text(
            f"""version: 1
image:
  path: "{reference_image}"
  filters:
    steps: []
  dpi: 300
paper:
  name: a4
  width_mm: 210.0
  height_mm: 297.0
pen:
  name: fine
  width_mm: 0.3
palette: stabilo_88
pfm:
  pfm_type: sketch_lines
  settings:
    seed: 42
output_path: "{output}"
"""
        )
        result = runner.invoke(
            main,
            ["convert", str(reference_image), "-p", str(project_path), "--no-vpype"],
        )
        assert result.exit_code == 1
        assert "mutually exclusive" in result.output
        assert not output.exists()
