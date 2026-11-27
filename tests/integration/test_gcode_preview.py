"""End-to-end tests: the G-code preview plots the reviewed SVG on the bed."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import numpy as np
import pytest
import yaml
from click.testing import CliRunner
from PIL import Image, ImageChops, ImageColor

from penpath.cli.commands.preview import OUTLINE_COLOR
from penpath.cli.main import main
from penpath.core import load_profile
from penpath.presets.palettes import STABILO_88

PX_PER_MM = 5
COLORS = {pen.name: pen.color for pen in STABILO_88.pens}
OUTLINE_RGB = ImageColor.getrgb(OUTLINE_COLOR)
BED_MM = (210.0, 297.0)
PAGE_MM = (190.0, 190.0)
PAGE_TOP_PX = round((BED_MM[1] - PAGE_MM[1]) * PX_PER_MM)
RAMPED_PROFILE = Path(__file__).resolve().parents[1] / "fixtures" / "profiles" / "ramped.yaml"


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
        main, ["preview", str(source), "-o", str(output), "--px-per-mm", str(PX_PER_MM), *extra]
    )
    assert result.exit_code == 0, result.output
    with Image.open(output) as image:
        return image.copy()


def _write_gcode(runner: CliRunner, drawing: Path, output: Path, profile: str = "generic") -> None:
    result = runner.invoke(main, ["gcode", str(drawing), "--profile", profile, "-o", str(output)])
    assert result.exit_code == 0, result.output


def _without_outlines(image: Image.Image) -> Image.Image:
    pixels = np.array(image)
    pixels[np.all(pixels == OUTLINE_RGB, axis=-1)] = (255, 255, 255)
    return Image.fromarray(pixels)


def _bed_svg(
    source: Path, page: tuple[float, float], bed: tuple[float, float], offset: tuple[float, float]
) -> Path:
    """Return a bed-sized SVG with the page's ink translated onto the bed."""
    text = source.read_text(encoding="utf-8")
    text = re.sub(
        r'width="[\d.]+mm" height="[\d.]+mm" viewBox="0 0 [\d.]+ [\d.]+"',
        f'width="{bed[0]:g}mm" height="{bed[1]:g}mm" viewBox="0 0 {bed[0]:g} {bed[1]:g}"',
        text,
        count=1,
    )
    assert f'width="{bed[0]:g}mm"' in text
    assert f'viewBox="0 0 {bed[0]:g} {bed[1]:g}"' in text
    text = re.sub(
        r"(<svg[^>]*>)",
        rf'\1<g transform="translate({offset[0]:g},{offset[1]:g})">',
        text,
        count=1,
    )
    path = source.with_name(f"bed_{source.name}")
    path.write_text(text.replace("</svg>", "</g></svg>"), encoding="utf-8")
    return path


@pytest.mark.parametrize("extra", [(), ("--layer", "stabilo_88_red")])
def test_gcode_png_equals_svg_png(
    runner: CliRunner, drawing: Path, tmp_path: Path, extra: tuple[str, ...]
) -> None:
    """Plotting the G-code reproduces the reviewed drawing on the bed canvas."""
    gcode = drawing.with_suffix(".gcode")
    _write_gcode(runner, drawing, gcode)

    svg_image = _preview(runner, drawing, tmp_path / "svg.png", *extra)
    gcode_image = _preview(runner, gcode, tmp_path / "gcode.png", *extra)
    bed_svg = _bed_svg(drawing, BED_MM, BED_MM, (0.0, 0.0))
    bed_svg_image = _preview(runner, bed_svg, tmp_path / "bed_svg.png", *extra)

    assert gcode_image.size == bed_svg_image.size == svg_image.size
    assert ImageChops.difference(_without_outlines(gcode_image), bed_svg_image).getbbox() is None


def test_gcode_preview_shows_bed_and_page_outlines(runner: CliRunner, tmp_path: Path) -> None:
    """A page smaller than the bed draws both outlines at their pen-space places."""
    drawing = tmp_path / "small.svg"
    drawing.write_text(
        f"""<svg xmlns="http://www.w3.org/2000/svg"
  xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
  width="190mm" height="190mm" viewBox="0 0 190 190">
<g inkscape:groupmode="layer" inkscape:label="stabilo_88_yellow" id="layer1"
  fill="none" stroke="{COLORS["stabilo_88_yellow"]}" stroke-width="0.4">
<polyline points="10,10 20,10 20,20"/></g></svg>""",
        encoding="utf-8",
    )
    gcode = drawing.with_suffix(".gcode")
    _write_gcode(runner, drawing, gcode)

    image = _preview(runner, gcode, tmp_path / "small-gcode.png")

    assert image.size == (round(BED_MM[0] * PX_PER_MM), round(BED_MM[1] * PX_PER_MM))
    for pixel in ((0, 500), (1049, 500), (500, 0), (500, 1484)):
        assert image.getpixel(pixel) == OUTLINE_RGB, pixel
    for pixel in ((500, PAGE_TOP_PX), (950, 1000), (0, 1000)):
        assert image.getpixel(pixel) == OUTLINE_RGB, pixel
    assert image.getpixel((500, 1000)) == (255, 255, 255)


def test_gcode_preview_ink_matches_svg_in_page_region(runner: CliRunner, tmp_path: Path) -> None:
    """The page region matches the SVG once the outline colour is ignored."""
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
    _write_gcode(runner, drawing, gcode)

    svg_image = _preview(runner, drawing, tmp_path / "small-svg.png")
    gcode_image = _preview(runner, gcode, tmp_path / "small-gcode.png")
    page_region = _without_outlines(gcode_image).crop(
        (0, PAGE_TOP_PX, round(PAGE_MM[0] * PX_PER_MM), round(BED_MM[1] * PX_PER_MM))
    )

    assert page_region.size == svg_image.size == (950, 950)
    assert ImageChops.difference(page_region, svg_image).getbbox() is None


def test_ramped_gcode_png_equals_svg_png(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ramped plot inks only the original stroke, not its lead-in or lead-out."""
    config_home = tmp_path / "xdg"
    profiles_dir = config_home / "penpath"
    profiles_dir.mkdir(parents=True)
    shutil.copyfile(RAMPED_PROFILE, profiles_dir / "profiles.yaml")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    drawing = tmp_path / "ramp.svg"
    drawing.write_text(
        f"""<svg xmlns="http://www.w3.org/2000/svg"
  xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
  width="100mm" height="100mm" viewBox="0 0 100 100">
<g inkscape:groupmode="layer" inkscape:label="stabilo_88_yellow" id="layer1"
  fill="none" stroke="{COLORS["stabilo_88_yellow"]}" stroke-width="0.4">
<polyline points="10,10 40,10 40,40"/>
<polyline points="60,60 80,60"/></g></svg>""",
        encoding="utf-8",
    )
    gcode = drawing.with_suffix(".gcode")
    _write_gcode(runner, drawing, gcode, "ramped")

    svg_image = _preview(runner, drawing, tmp_path / "svg.png")
    gcode_image = _preview(runner, gcode, tmp_path / "gcode.png")
    bed_svg = _bed_svg(drawing, (100.0, 100.0), BED_MM, (0.0, BED_MM[1] - 100.0))
    bed_svg_image = _preview(runner, bed_svg, tmp_path / "bed_svg.png")

    assert gcode_image.size == (210 * PX_PER_MM, 297 * PX_PER_MM)
    assert svg_image.size == (100 * PX_PER_MM, 100 * PX_PER_MM)
    assert ImageChops.difference(_without_outlines(gcode_image), bed_svg_image).getbbox() is None


def test_gcode_preview_flips_ink_when_profile_does_not_invert_y(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bed canvas follows `bed.invert_y` when it places page strokes."""
    config_home = tmp_path / "xdg"
    profiles_dir = config_home / "penpath"
    profiles_dir.mkdir(parents=True)
    profile = load_profile("generic").model_dump()
    profile["name"] = "no_invert"
    profile["bed"]["invert_y"] = False
    (profiles_dir / "profiles.yaml").write_text(
        yaml.safe_dump({"no_invert": profile}), encoding="utf-8"
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    drawing = tmp_path / "flat.svg"
    drawing.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
        'viewBox="0 0 100 100">'
        '<path d="M 10 10 L 50 10" fill="none" stroke="#000000" stroke-width="1"/></svg>',
        encoding="utf-8",
    )
    gcode = drawing.with_suffix(".gcode")
    _write_gcode(runner, drawing, gcode, "no_invert")

    image = _preview(runner, gcode, tmp_path / "no_invert.png")

    assert image.getpixel((100, round(287 * PX_PER_MM))) == (0, 0, 0)
    assert image.getpixel((100, round(10 * PX_PER_MM))) == (255, 255, 255)


def test_gcode_preview_layer_keeps_both_outlines(
    runner: CliRunner, drawing: Path, tmp_path: Path
) -> None:
    """`--layer` hides other pens' ink but never the bed or page outline."""
    gcode = drawing.with_suffix(".gcode")
    _write_gcode(runner, drawing, gcode)

    image = _preview(runner, gcode, tmp_path / "red.png", "--layer", "stabilo_88_red")

    colors = set(image.getdata())
    assert OUTLINE_RGB in colors
    assert ImageColor.getrgb(COLORS["stabilo_88_red"]) in colors
    assert ImageColor.getrgb(COLORS["stabilo_88_yellow"]) not in colors


def test_preview_travel_changes_gcode_png_and_keeps_ink(runner: CliRunner, tmp_path: Path) -> None:
    """The G-code preview can draw light pen-up travel under unchanged ink."""
    drawing = tmp_path / "travel.svg"
    drawing.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
        'viewBox="0 0 100 100">'
        '<path d="M 10 10 L 90 10" fill="none" stroke="#000000" stroke-width="1"/>'
        '<path d="M 10 40 L 90 40" fill="none" stroke="#000000" stroke-width="1"/></svg>',
        encoding="utf-8",
    )
    gcode = drawing.with_suffix(".gcode")
    _write_gcode(runner, drawing, gcode)

    ink = _preview(runner, gcode, tmp_path / "ink.png")
    travel = _preview(runner, gcode, tmp_path / "travel.png", "--travel")
    no_travel = _preview(runner, gcode, tmp_path / "no-travel.png", "--no-travel")
    ink_pixels = [
        (x, y)
        for y in range(ink.height)
        for x in range(ink.width)
        if ink.getpixel((x, y)) != (255, 255, 255)
    ]

    assert ink.tobytes() == no_travel.tobytes()
    assert ink.tobytes() != travel.tobytes()
    assert ink_pixels
    assert all(travel.getpixel(pixel) == ink.getpixel(pixel) for pixel in ink_pixels)
    assert any(pixel == (200, 200, 200) for pixel in travel.getdata())


def _framed_gcode(tmp_path: Path, runner: CliRunner, *extra: str) -> Path:
    """Write G-code for a 160 mm centred card with a frame."""
    drawing = tmp_path / "framed.svg"
    drawing.write_text(
        f"""<svg xmlns="http://www.w3.org/2000/svg"
  xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
  width="160mm" height="160mm" viewBox="0 0 160 160">
<g inkscape:groupmode="layer" inkscape:label="stabilo_88_black" id="layer1"
  fill="none" stroke="{COLORS["stabilo_88_black"]}" stroke-width="0.3">
<polyline points="20,20 140,20 140,140 20,140 20,20"/></g></svg>""",
        encoding="utf-8",
    )
    gcode = drawing.with_suffix(".gcode")
    result = runner.invoke(
        main,
        [
            "gcode",
            str(drawing),
            "--profile",
            "aquila",
            "--place",
            "center",
            "--frame",
            *extra,
            "-o",
            str(gcode),
        ],
    )
    assert result.exit_code == 0, result.output
    return gcode


def test_gcode_preview_shows_the_frame_as_ink(runner: CliRunner, tmp_path: Path) -> None:
    """The frame is plotted ink, outside the page outline, not another grey guide."""
    gcode = _framed_gcode(tmp_path, runner)
    image = _preview(runner, gcode, tmp_path / "frame.png")

    assert image.size == (round(220 * PX_PER_MM), round(220 * PX_PER_MM))
    assert image.getpixel((83, 500)) == (0, 0, 0)
    assert image.getpixel((95, 500)) == (255, 255, 255)
    assert image.getpixel((round(18.65 * PX_PER_MM), 500)) == OUTLINE_RGB


def test_gcode_preview_layer_can_show_only_the_frame(runner: CliRunner, tmp_path: Path) -> None:
    """A frame pen is its own layer for `--layer` even when it differs from the ink."""
    gcode = _framed_gcode(tmp_path, runner, "--frame-pen", "stabilo_88_red")
    image = _preview(runner, gcode, tmp_path / "frame-layer.png", "--layer", "stabilo_88_red")
    colors = set(image.getdata())

    assert ImageColor.getrgb(COLORS["stabilo_88_red"]) in colors
    assert (0, 0, 0) not in colors
    assert OUTLINE_RGB in colors


def test_preview_help_says_arcs_are_unsupported(runner: CliRunner) -> None:
    result = runner.invoke(main, ["preview", "--help"])

    assert result.exit_code == 0
    assert "arcs (g2/g3)" in result.output.lower()
    assert "not supported" in result.output.lower()
    assert ".gcode" in result.output
    assert "bed and page outline" in result.output.lower()


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
    """A header naming a profile that is not installed renders in machine space."""
    gcode = tmp_path / "foreign.gcode"
    gcode.write_text(
        "; penpath gcode profile=no_such_machine z_up=5.000 z_down=0.000\n"
        "G0 Z5.000\nG0 X10.000 Y287.000\nG0 Z0.000\nG1 X20.000 Y287.000\nG0 Z5.000\n",
        encoding="utf-8",
    )
    output = tmp_path / "foreign.png"

    result = runner.invoke(
        main, ["preview", str(gcode), "-o", str(output), "--px-per-mm", str(PX_PER_MM)]
    )

    assert result.exit_code == 0, result.output
    assert "no_such_machine" in result.output
    assert "not found" in result.output
    assert "Traceback" not in result.output
    with Image.open(output) as image:
        assert image.size == (210 * PX_PER_MM, 297 * PX_PER_MM)
        assert OUTLINE_RGB not in set(image.getdata())


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
