"""End-to-end coverage of the public API and the CLI sharing one conversion path."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from penpath import Drawing, convert
from penpath.cli.main import main
from penpath.core.svg_parse import parse_svg_strokes

CIRCLE = Path(__file__).resolve().parents[1] / "fixtures" / "images" / "reference" / "circle.png"


def test_api_writes_svg_that_parses_back_into_strokes(tmp_path: Path) -> None:
    """A real conversion writes an SVG whose strokes can be read back."""
    output = tmp_path / "circle.svg"
    drawing = convert(
        CIRCLE,
        pfm="sketch_lines:fine",
        settings={"seed": 42},
        paper="a4",
        use_vpype=False,
        max_resolution_px=64,
        output=output,
    )

    assert isinstance(drawing, Drawing)
    strokes = parse_svg_strokes(output)
    assert len(strokes) == sum(len(lines) for lines in drawing.strokes_by_pen)
    assert all(len(stroke.polyline) >= 2 for stroke in strokes)
    assert output.exists()


def test_api_output_matches_drawing_to_svg(tmp_path: Path) -> None:
    """Writing through ``output=`` is the same export as ``Drawing.to_svg``."""
    first = tmp_path / "on_convert.svg"
    second = tmp_path / "explicit.svg"
    drawing = convert(
        CIRCLE,
        settings={"seed": 42},
        use_vpype=False,
        max_resolution_px=64,
        output=first,
    )

    assert drawing.to_svg(second, use_vpype=False) == second
    assert second.read_bytes() == first.read_bytes()


def test_cli_and_api_produce_the_same_svg(tmp_path: Path) -> None:
    """The CLI now goes through the public convert facade."""
    cli_output = tmp_path / "cli.svg"
    result = CliRunner().invoke(
        main,
        [
            "convert",
            str(CIRCLE),
            "-o",
            str(cli_output),
            "--no-vpype",
            "--pfm",
            "sketch_lines:fine",
            "-s",
            "seed=42",
            "--max-resolution",
            "64",
        ],
    )

    assert result.exit_code == 0, result.output
    api_output = tmp_path / "api.svg"
    convert(
        CIRCLE,
        pfm="sketch_lines:fine",
        settings={"seed": 42},
        output=api_output,
        use_vpype=False,
        max_resolution_px=64,
    )

    assert api_output.read_bytes() == cli_output.read_bytes()
