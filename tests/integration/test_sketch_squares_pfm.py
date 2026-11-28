"""End-to-end tests for the registered Sketch Squares PFM."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from click.testing import CliRunner
from PIL import Image

from penpath.cli.main import main

SVG_NS = "{http://www.w3.org/2000/svg}"
INKSCAPE_NS = "{http://www.inkscape.org/namespaces/inkscape}"
FACE = (Path(__file__).parent.parent / "fixtures/images/reference/face.jpg").resolve()


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _svg_paths(path: Path) -> list[str]:
    return [el.get("d", "") for el in ET.parse(path).getroot().iter(SVG_NS + "path")]


def _layers(path: Path) -> list[ET.Element]:
    return [
        group
        for group in ET.parse(path).getroot().iter(SVG_NS + "g")
        if group.get(INKSCAPE_NS + "groupmode") == "layer"
    ]


@pytest.fixture
def two_pen_image(tmp_path: Path) -> Path:
    """A small image with a black region and a red region, one per palette pen."""
    image = Image.new("RGB", (120, 120), "white")
    pixels = image.load()
    for y in range(120):
        for x in range(120):
            pixels[x, y] = (0, 0, 0) if x < 60 else (200, 0, 0)
    path = tmp_path / "two_pens.png"
    image.save(path)
    return path


class TestSketchSquaresCLI:
    """A user can select Sketch Squares exactly as documented."""

    def test_seeded_face_conversion_is_deterministic(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        outputs = (tmp_path / "a.svg", tmp_path / "b.svg")
        for output in outputs:
            result = runner.invoke(
                main,
                [
                    "convert",
                    str(FACE),
                    "-o",
                    str(output),
                    "--pfm",
                    "sketch_squares",
                    "-s",
                    "seed=42",
                    "--no-vpype",
                    "--quiet",
                ],
            )
            assert result.exit_code == 0, result.output

        assert outputs[0].read_bytes() == outputs[1].read_bytes()
        assert len(_svg_paths(outputs[0])) > 0

    def test_qualified_presets_draw_differently(self, runner: CliRunner, tmp_path: Path) -> None:
        outputs = {}
        for preset in ("coarse", "fine", "crosshatch-grid"):
            output = tmp_path / f"{preset}.svg"
            result = runner.invoke(
                main,
                [
                    "convert",
                    str(FACE),
                    "-o",
                    str(output),
                    "--pfm",
                    f"sketch_squares:{preset}",
                    "-s",
                    "seed=42",
                    "--max-resolution",
                    "160",
                    "--no-vpype",
                    "--quiet",
                ],
            )
            assert result.exit_code == 0, result.output
            outputs[preset] = _svg_paths(output)
            assert outputs[preset]

        assert len(set(map(tuple, outputs.values()))) == 3

    def test_bare_square_preset_is_rejected_with_a_qualified_id(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        output = tmp_path / "rejected.svg"
        result = runner.invoke(
            main,
            [
                "convert",
                str(FACE),
                "-o",
                str(output),
                "--pfm",
                "coarse",
                "--no-vpype",
            ],
        )
        assert result.exit_code == 2
        assert "sketch_squares:coarse" in result.output
        assert not output.exists()

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("bogus", "1"),
            ("grid_angle", "999"),
            ("seed", "not-an-int"),
            ("min_length", "200"),
        ],
    )
    def test_invalid_setting_is_a_usage_error_naming_the_setting(
        self, runner: CliRunner, tmp_path: Path, key: str, value: str
    ) -> None:
        output = tmp_path / "invalid.svg"
        result = runner.invoke(
            main,
            [
                "convert",
                str(FACE),
                "-o",
                str(output),
                "--pfm",
                "sketch_squares",
                "-s",
                f"{key}={value}",
                "--no-vpype",
            ],
        )
        assert result.exit_code == 2
        assert "PFM setting" in result.output
        assert key in result.output
        assert not output.exists()

    def test_palette_mode_writes_one_stroked_layer_per_used_pen(
        self, runner: CliRunner, two_pen_image: Path, tmp_path: Path
    ) -> None:
        output = tmp_path / "palette.svg"
        result = runner.invoke(
            main,
            [
                "convert",
                str(two_pen_image),
                "-o",
                str(output),
                "--pfm",
                "sketch_squares",
                "-s",
                "seed=42",
                "--palette",
                "a=0.4,#000000;b=0.4,#FF0000",
                "--max-resolution",
                "120",
                "--no-vpype",
                "--quiet",
            ],
        )
        assert result.exit_code == 0, result.output

        layers = _layers(output)
        assert len(layers) == 2
        assert [layer.get("id") for layer in layers] == ["layer1", "layer2"]
        for layer in layers:
            assert list(layer.iter(SVG_NS + "path"))

    def test_project_yaml_converts(
        self, runner: CliRunner, two_pen_image: Path, tmp_path: Path
    ) -> None:
        output = tmp_path / "from_project.svg"
        project_path = tmp_path / "project.yaml"
        project_path.write_text(
            f"""version: 1
image:
  path: "{two_pen_image}"
  filters:
    steps: []
  dpi: 300
  auto_equalize: false
paper:
  name: a4
  width_mm: 210.0
  height_mm: 297.0
pen:
  name: fine
  width_mm: 0.3
pfm:
  pfm_type: sketch_squares
  settings:
    grid_angle: 0.0
    line_density: 0.6
    seed: 42
output_path: "{output}"
"""
        )
        result = runner.invoke(
            main, ["convert", str(two_pen_image), "-p", str(project_path), "--no-vpype", "--quiet"]
        )
        assert result.exit_code == 0, result.output
        assert _svg_paths(output)


class TestInfoPFMs:
    """`penpath info pfms` lists all registered PFMs in every format."""

    def test_json_lists_registered_pfms_and_qualified_presets(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["info", "pfms", "--format", "json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        rows = {row["name"]: row for row in data["available_pfms"]}
        assert set(rows) == {
            "sketch_lines",
            "sketch_squares",
            "contour",
            "stipple",
            "spiral_sawtooth",
            "hatch",
            "patch_hatch",
            "tsp",
            "squiggle",
            "engraving",
        }
        assert rows["sketch_lines"]["settings_model"] == "SketchLinesSettings"
        assert rows["sketch_lines"]["presets"]  # legacy bare names still listed
        squares = rows["sketch_squares"]
        assert squares["settings_model"] == "SketchSquaresSettings"
        assert squares["default_settings"]["grid_angle"] == 45.0
        assert squares["preset_ids"] == [
            "sketch_squares:coarse",
            "sketch_squares:crosshatch-grid",
            "sketch_squares:fine",
        ]
        assert data["preset_ids"] == sorted(data["preset_ids"])

    def test_yaml_and_table_show_square_presets(self, runner: CliRunner) -> None:
        yaml_result = runner.invoke(main, ["info", "pfms", "--format", "yaml"])
        assert yaml_result.exit_code == 0, yaml_result.output
        assert "sketch_squares" in yaml_result.stdout
        assert "sketch_squares:crosshatch-grid" in yaml_result.stdout

        table_result = runner.invoke(main, ["info", "pfms"])
        assert table_result.exit_code == 0, table_result.output
        assert "sketch_squares" in table_result.output
        assert "crosshatch-grid" in table_result.output
