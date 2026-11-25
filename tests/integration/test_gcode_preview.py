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


def test_gcode_png_equals_svg_png_when_page_differs_from_bed(
    runner: CliRunner, tmp_path: Path
) -> None:
    """The header page makes the preview invert Y around the page, not the bed."""
    drawing = tmp_path / "small.svg"
    drawing.write_text(
        f"""<svg xmlns="http://www.w3.org/2000/svg"
  xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
  width="190mm" height="190mm" viewBox="0 0 190 190">
<g inkscape:groupmode="layer" inkscape:label="stabilo_88_yellow" id="layer1"
  fill="none" stroke="{COLORS["stabilo_88_yellow"]}" stroke-width="0.4">
<polyline points="10,10 20,10 20,20"/><polyline points="30,30 40,30"/></g></svg>""",
        encoding="utf-8",
    )
    gcode = drawing.with_suffix(".gcode")
    result = runner.invoke(main, ["gcode", str(drawing), "--profile", "generic", "-o", str(gcode)])
    assert result.exit_code == 0, result.output

    svg_image = _preview(runner, drawing, tmp_path / "small-svg.png")
    gcode_image = _preview(runner, gcode, tmp_path / "small-gcode.png")

    assert gcode_image.size == svg_image.size == (190 * DPI, 190 * DPI)
    assert ImageChops.difference(svg_image, gcode_image).getbbox() is None


def test_preview_help_says_arcs_are_unsupported(runner: CliRunner) -> None:
    result = runner.invoke(main, ["preview", "--help"])

    assert result.exit_code == 0
    assert "arcs (g2/g3)" in result.output.lower()
    assert "not supported" in result.output.lower()
    assert ".gcode" in result.output


@pytest.mark.parametrize("command", ["G2", "G02", "G3", "G03"])
def test_preview_rejects_arcs_with_clean_error(
    runner: CliRunner, tmp_path: Path, command: str
) -> None:
    gcode = tmp_path / "arcs.gcode"
    gcode.write_text(
        f"; penpath gcode profile=generic z_up=5.000 z_down=0.000\n{command} X10.000 Y10.000\n",
        encoding="utf-8",
    )
    output = tmp_path / "arcs.png"

    result = runner.invoke(main, ["preview", str(gcode), "-o", str(output)])

    assert result.exit_code == 1
    assert f"arcs ({command}) are not supported" in result.output
    assert "Traceback" not in result.output
    assert not output.exists()


def test_preview_unknown_profile_falls_back_to_a4(runner: CliRunner, tmp_path: Path) -> None:
    """A header naming a profile that is not installed still renders in machine space."""
    gcode = tmp_path / "foreign.gcode"
    gcode.write_text(
        "; penpath gcode profile=no_such_machine z_up=5.000 z_down=0.000\n"
        "G0 Z5.000\nG0 X10.000 Y287.000\nG0 Z0.000\nG1 X20.000 Y287.000\nG0 Z5.000\n",
        encoding="utf-8",
    )
    output = tmp_path / "foreign.png"

    result = runner.invoke(main, ["preview", str(gcode), "-o", str(output), "--dpi", str(DPI)])

    assert result.exit_code == 0, result.output
    assert "no_such_machine" in result.output
    assert "not found" in result.output
    assert "Traceback" not in result.output
    with Image.open(output) as image:
        assert image.size == (210 * DPI, 297 * DPI)


def test_preview_gcode_without_strokes_is_clean_error(runner: CliRunner, tmp_path: Path) -> None:
    gcode = tmp_path / "empty.gcode"
    gcode.write_text(
        "; penpath gcode profile=generic z_up=5.000 z_down=0.000\nG21\nG90\n",
        encoding="utf-8",
    )
    output = tmp_path / "empty.png"

    result = runner.invoke(main, ["preview", str(gcode), "-o", str(output)])

    assert result.exit_code == 1
    assert "No pen strokes found" in result.output
    assert "Traceback" not in result.output
    assert not output.exists()
