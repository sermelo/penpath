"""End-to-end tests for selecting the registered Spiral Sawtooth PFM."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from click.testing import CliRunner
from PIL import Image

from penpath.cli.main import main
from penpath.core.drawing.pfm_spiral import SpiralSettings, spiral_strokes
from penpath.core.image.load import load_image
from penpath.core.svg_parse import parse_svg_strokes
from penpath.presets.pfms import SPIRAL_PRESETS

SVG_NS = "{http://www.w3.org/2000/svg}"
INKSCAPE_NS = "{http://www.inkscape.org/namespaces/inkscape}"
PALETTE = "unused=0.4,#00FF00;red=0.4,#FF0000;blue=0.4,#0000FF;white=0.4,#FFFFFF"
FACE = Path(__file__).resolve().parents[2] / "tests/fixtures/images/reference/face.jpg"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _layers(svg_path: Path) -> list[tuple[str, int]]:
    """Return each Inkscape layer's id and number of drawn paths."""
    root = ET.parse(svg_path).getroot()
    result: list[tuple[str, int]] = []
    for group in root.iter(SVG_NS + "g"):
        if group.get(INKSCAPE_NS + "groupmode") == "layer":
            result.append((str(group.get("id")), len(group.findall(SVG_NS + "path"))))
    return result


class TestSpiralConvert:
    """A user can convert with `--pfm spiral_sawtooth` and `-s`."""

    def test_convert_is_deterministic_and_writes_strokes(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        first = tmp_path / "first.svg"
        second = tmp_path / "second.svg"
        args = [
            "convert",
            str(FACE),
            "-o",
            str(first),
            "--pfm",
            "spiral_sawtooth",
            "-s",
            "seed=42",
            "--no-vpype",
            "--quiet",
        ]
        result = runner.invoke(main, args)
        assert result.exit_code == 0, result.output
        assert first.exists()
        args[args.index(str(first))] = str(second)
        result = runner.invoke(main, args)
        assert result.exit_code == 0, result.output
        assert first.read_bytes() == second.read_bytes()
        assert parse_svg_strokes(first)

    def test_default_pfm_emits_one_stroke_before_optimization(self) -> None:
        strokes = spiral_strokes(load_image(FACE), SpiralSettings())
        assert len(strokes) == 1

    @pytest.mark.parametrize(
        ("preset", "expected_strokes"),
        [("fine", 1), ("bold", 1), ("parabolic", 2)],
    )
    def test_qualified_preset_converts_with_expected_strokes(
        self, runner: CliRunner, tmp_path: Path, preset: str, expected_strokes: int
    ) -> None:
        strokes = spiral_strokes(load_image(FACE), SPIRAL_PRESETS[preset])
        assert len(strokes) == expected_strokes
        output = tmp_path / f"{preset}.svg"
        result = runner.invoke(
            main,
            [
                "convert",
                str(FACE),
                "-o",
                str(output),
                "--pfm",
                f"spiral_sawtooth:{preset}",
                "-s",
                "seed=42",
                "--no-vpype",
                "--quiet",
            ],
        )
        assert result.exit_code == 0, result.output
        assert parse_svg_strokes(output)

    @pytest.mark.parametrize("shape", ["ellipse", "cover"])
    def test_shape_override_converts(self, runner: CliRunner, tmp_path: Path, shape: str) -> None:
        output = tmp_path / f"{shape}.svg"
        result = runner.invoke(
            main,
            [
                "convert",
                str(FACE),
                "-o",
                str(output),
                "--pfm",
                "spiral_sawtooth",
                "-s",
                f"shape={shape}",
                "--no-vpype",
                "--quiet",
            ],
        )
        assert result.exit_code == 0, result.output
        assert parse_svg_strokes(output)

    def test_invalid_shape_is_a_usage_error(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(
            main,
            [
                "convert",
                str(FACE),
                "-o",
                str(tmp_path / "bad.svg"),
                "--pfm",
                "spiral_sawtooth",
                "-s",
                "shape=square",
                "--quiet",
            ],
        )
        assert result.exit_code == 2
        assert "shape" in result.output

    def test_info_lists_spiral_and_qualified_presets(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["info", "pfms", "--format", "json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        row = next(p for p in data["available_pfms"] if p["name"] == "spiral_sawtooth")
        assert row["preset_ids"] == [
            "spiral_sawtooth:bold",
            "spiral_sawtooth:fine",
            "spiral_sawtooth:parabolic",
        ]

    def test_palette_run_writes_one_layer_per_used_pen(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        image = Image.new("RGB", (120, 120), "white")
        for y in range(120):
            for x in range(120):
                image.putpixel((x, y), (255, 0, 0) if x < 60 else (0, 0, 255))
        source = tmp_path / "two_regions.png"
        image.save(source)
        output = tmp_path / "palette_spiral.svg"
        result = runner.invoke(
            main,
            [
                "convert",
                str(source),
                "-o",
                str(output),
                "--pfm",
                "spiral_sawtooth",
                "--palette",
                PALETTE,
                "-s",
                "seed=42",
                "-s",
                "ignore_white=true",
                "--no-vpype",
                "--quiet",
            ],
        )
        assert result.exit_code == 0, result.output
        layers = _layers(output)
        assert [layer_id for layer_id, _ in layers] == ["layer1", "layer2"]
        assert all(stroke_count > 0 for _, stroke_count in layers)
