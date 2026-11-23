"""End-to-end tests for pen identity in the default (vpype) SVG export."""

from __future__ import annotations

import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from click.testing import CliRunner
from PIL import Image, ImageColor

from penpath.cli.main import main
from penpath.core.svg_parse import parse_svg_strokes

INKSCAPE_ATTR = "{http://www.inkscape.org/namespaces/inkscape}"


@pytest.fixture
def reference(tmp_path: Path) -> Path:
    image = Image.new("RGB", (64, 64), "white")
    pixels = image.load()
    for index in range(64):
        pixels[index, index] = (0, 0, 0)
    path = tmp_path / "reference.png"
    image.save(path)
    return path


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _layer_attrs(svg_path: Path, label: str) -> dict[str, str]:
    """Return the attributes of the Inkscape layer with the given label."""
    root = ET.parse(svg_path).getroot()
    for element in root.iter():
        if not element.tag.endswith("g"):
            continue
        groupmode = element.get("inkscape:groupmode") or element.get(INKSCAPE_ATTR + "groupmode")
        if groupmode != "layer":
            continue
        element_label = element.get("inkscape:label") or element.get(INKSCAPE_ATTR + "label")
        if element_label == label:
            attrs = dict(element.attrib)
            if "stroke" not in attrs:
                for descendant in element.iter():
                    if descendant.get("stroke"):
                        attrs["stroke"] = descendant.get("stroke") or ""
                        break
            return attrs
    raise AssertionError(f"No SVG layer labelled {label!r}")


def _convert(runner: CliRunner, reference: Path, output: Path, *extra_args: str) -> None:
    result = runner.invoke(
        main,
        ["convert", str(reference), "-o", str(output), "-s", "seed=42", *extra_args],
    )
    assert result.exit_code == 0, result.output


class TestVpypePenIdentity:
    """The default export must describe the same pen as the direct export."""

    def test_default_convert_output_carries_pen_colour_and_label(
        self, runner: CliRunner, reference: Path, tmp_path: Path
    ) -> None:
        plot = tmp_path / "plot.svg"
        _convert(runner, reference, plot)

        layer = _layer_attrs(plot, "Pen: fine")
        assert ImageColor.getrgb(layer["stroke"]) == ImageColor.getrgb("black")
        assert b"#0000ff" not in plot.read_bytes()
        assert parse_svg_strokes(plot, layer="Pen: fine")

    def test_vpype_and_direct_exports_agree_on_pen(
        self, runner: CliRunner, reference: Path, tmp_path: Path
    ) -> None:
        vpype_plot = tmp_path / "vpype.svg"
        direct_plot = tmp_path / "direct.svg"
        _convert(runner, reference, vpype_plot, "--pen", "red_fine")
        _convert(runner, reference, direct_plot, "--pen", "red_fine", "--no-vpype")

        vpype_layer = _layer_attrs(vpype_plot, "Pen: red_fine")
        direct_layer = _layer_attrs(direct_plot, "Pen: red_fine")
        assert ImageColor.getrgb(vpype_layer["stroke"]) == (255, 0, 0)
        assert ImageColor.getrgb(vpype_layer["stroke"]) == ImageColor.getrgb(direct_layer["stroke"])

    def test_vpype_still_reads_the_export(
        self, runner: CliRunner, reference: Path, tmp_path: Path
    ) -> None:
        vpype = shutil.which("vpype")
        assert vpype is not None, "vpype must be installed for this test"
        plot = tmp_path / "plot.svg"
        _convert(runner, reference, plot)

        result = subprocess.run(
            [vpype, "read", str(plot), "stat"],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "Stats" in result.stdout
        assert "Layer 1" in result.stdout

    def test_evaluate_by_pen_label_keys_cost_by_pen_colour(
        self, runner: CliRunner, reference: Path, tmp_path: Path
    ) -> None:
        plot = tmp_path / "plot.svg"
        _convert(runner, reference, plot, "--pen", "red_fine")

        result = runner.invoke(
            main,
            ["evaluate", str(reference), str(plot), "--layer", "Pen: red_fine", "--json"],
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        per_layer = payload["machine_cost"]["per_layer"]
        assert set(per_layer) == {"#ff0000"}
        assert "#0000ff" not in per_layer

    def test_preview_renders_ink_in_the_pen_colour(
        self, runner: CliRunner, reference: Path, tmp_path: Path
    ) -> None:
        plot = tmp_path / "plot.svg"
        preview = tmp_path / "preview.png"
        _convert(runner, reference, plot, "--pen", "red_fine")

        result = runner.invoke(main, ["preview", str(plot), "-o", str(preview), "--dpi", "2"])

        assert result.exit_code == 0, result.output
        with Image.open(preview) as image:
            pixels = list(image.getdata())
        reds = [pixel for pixel in pixels if pixel[0] > 200 and pixel[1] < 60 and pixel[2] < 60]
        blues = [pixel for pixel in pixels if pixel[2] > 150 and pixel[0] < 100]
        assert reds
        assert not blues
