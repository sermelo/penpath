"""End-to-end tests: the G-code preview plots the reviewed SVG."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner
from PIL import Image, ImageChops

from penpath.cli.main import main
from penpath.presets.palettes import STABILO_88

DPI = 5
COLORS = {pen.name: pen.color for pen in STABILO_88.pens}


@pytest.fixture
def drawing(tmp_path: Path) -> Path:
    path = tmp_path / "card.svg"
    path.write_text(
        f"""<svg xmlns="http://www.w3.org/2000/svg"
  xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
  width="210mm" height="297mm" viewBox="0 0 210 297">
<g inkscape:groupmode="layer" inkscape:label="stabilo_88_yellow" id="layer1"
  fill="none" stroke="{COLORS["stabilo_88_yellow"]}" stroke-width="0.4">
<polyline points="10,10 20,10 20,20"/><polyline points="30,30 40,30"/></g>
<g inkscape:groupmode="layer" inkscape:label="stabilo_88_red" id="layer2"
  fill="none" stroke="{COLORS["stabilo_88_red"]}" stroke-width="0.4">
<polyline points="50,50 60,50"/><polyline points="70,70 80,70"/></g></svg>""",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _preview(runner: CliRunner, source: Path, output: Path, *extra: str) -> Image.Image:
    result = runner.invoke(
        main, ["preview", str(source), "-o", str(output), "--dpi", str(DPI), *extra]
    )
    assert result.exit_code == 0, result.output
    with Image.open(output) as image:
        return image.copy()


@pytest.mark.parametrize("extra", [(), ("--layer", "stabilo_88_red")])
def test_gcode_png_equals_svg_png(
    runner: CliRunner, drawing: Path, tmp_path: Path, extra: tuple[str, ...]
) -> None:
    """Plotting the G-code reproduces the reviewed drawing at the same scale."""
    gcode = drawing.with_suffix(".gcode")
    result = runner.invoke(main, ["gcode", str(drawing), "--profile", "generic", "-o", str(gcode)])
    assert result.exit_code == 0, result.output

    svg_image = _preview(runner, drawing, tmp_path / "svg.png", *extra)
    gcode_image = _preview(runner, gcode, tmp_path / "gcode.png", *extra)

    assert gcode_image.size == svg_image.size
    assert ImageChops.difference(svg_image, gcode_image).getbbox() is None


def test_preview_help_says_arcs_are_unsupported(runner: CliRunner) -> None:
    result = runner.invoke(main, ["preview", "--help"])

    assert result.exit_code == 0
    assert "arcs (g2/g3)" in result.output.lower()
    assert "not supported" in result.output.lower()
    assert ".gcode" in result.output


def test_preview_rejects_arcs_with_clean_error(runner: CliRunner, tmp_path: Path) -> None:
    gcode = tmp_path / "arcs.gcode"
    gcode.write_text(
        "; penpath gcode profile=generic z_up=5.000 z_down=0.000\nG2 X10.000 Y10.000\n",
        encoding="utf-8",
    )
    output = tmp_path / "arcs.png"

    result = runner.invoke(main, ["preview", str(gcode), "-o", str(output)])

    assert result.exit_code == 1
    assert "arcs (G2) are not supported" in result.output
    assert "Traceback" not in result.output
    assert not output.exists()
