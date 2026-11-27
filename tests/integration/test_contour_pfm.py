"""End-to-end checks for the registered Contour PFM."""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from penpath.cli.main import main
from penpath.core import list_svg_layers, parse_svg_strokes

_FIXTURES = Path(__file__).parent.parent / "fixtures"
_FACE = _FIXTURES / "images" / "reference" / "face.jpg"
_BLOCKS = _FIXTURES / "images" / "colour" / "colour_blocks.png"
_BASE = "--dpi 72 --max-resolution 96 --no-vpype --quiet"

_CASES = (
    "--pfm contour --paper 100x100 --pen 0.3",
    "--pfm contour_portrait --paper 100x100 --pen 0.3",
    "--pfm contour_silhouette --paper 100x100 --pen 0.3",
    "--pfm contour -s threshold=110 --paper 100x100 --pen 0.3",
)


def _convert(image: Path, output: Path, options: str) -> Result:
    argv = shlex.split(f"convert {image} -o {output} {_BASE} {options}")
    return CliRunner().invoke(main, argv)


@pytest.mark.parametrize("options", _CASES)
def test_contour_cli_writes_strokes(tmp_path: Path, options: str) -> None:
    output = tmp_path / "contour.svg"
    result = _convert(_FACE, output, options)
    assert result.exit_code == 0, result.output
    assert output.is_file()
    assert len(parse_svg_strokes(output)) > 0


def test_contour_presets_draw_different_levels_of_detail(tmp_path: Path) -> None:
    portrait = tmp_path / "portrait.svg"
    silhouette = tmp_path / "silhouette.svg"
    assert _convert(_FACE, portrait, "--pfm contour_portrait").exit_code == 0
    assert _convert(_FACE, silhouette, "--pfm contour_silhouette").exit_code == 0
    assert len(parse_svg_strokes(portrait)) > len(parse_svg_strokes(silhouette))


def test_contour_runs_once_per_pen_with_a_small_palette(tmp_path: Path) -> None:
    output = tmp_path / "palette.svg"
    result = _convert(
        _BLOCKS,
        output,
        "--pfm contour --palette 'red=0.3,#FF0000;blue=0.3,#0000FF' --paper 40x40",
    )
    assert result.exit_code == 0, result.output
    assert list_svg_layers(output) == [("layer1", "red"), ("layer2", "blue")]
    assert len(parse_svg_strokes(output)) > 0


def test_contour_help_and_bad_input_are_clear(tmp_path: Path) -> None:
    runner = CliRunner()
    help_result = runner.invoke(main, ["convert", "--help"])
    assert help_result.exit_code == 0
    assert "contour" in help_result.output

    bad_pfm = _convert(_FACE, tmp_path / "bad.svg", "--pfm nope")
    assert bad_pfm.exit_code == 2
    assert "Unknown PFM or preset" in bad_pfm.output
    assert "contour" in bad_pfm.output

    bad_key = _convert(_FACE, tmp_path / "bad.svg", "--pfm contour -s line_density=1")
    assert bad_key.exit_code == 2
    assert "Unknown PFM setting" in bad_key.output
