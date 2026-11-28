"""End-to-end coverage of the public ``preview`` API."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner
from PIL import Image

from penpath import Drawing, convert, preview
from penpath.cli.main import main

CIRCLE = Path(__file__).resolve().parents[1] / "fixtures" / "images" / "reference" / "circle.png"


def test_public_preview_renders_an_svg_path(tmp_path: Path) -> None:
    svg = tmp_path / "plot.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
        'viewBox="0 0 100 100">'
        '<path d="M 10 20 L 90 20" fill="none" stroke="#000000" stroke-width="2"/>'
        "</svg>",
        encoding="utf-8",
    )
    output = tmp_path / "preview.png"

    result = preview(svg, output, px_per_mm=3)

    assert result == output
    with Image.open(output) as image:
        assert image.size == (300, 300)
        assert image.getpixel((150, 60)) == (0, 0, 0)
        assert image.getpixel((150, 150)) == (255, 255, 255)


def test_public_preview_renders_a_converted_drawing(tmp_path: Path) -> None:
    drawing = convert(
        CIRCLE,
        pfm="sketch_lines:fine",
        settings={"seed": 42},
        use_vpype=False,
        max_resolution_px=64,
    )
    assert isinstance(drawing, Drawing)

    from_drawing = preview(drawing, tmp_path / "drawing.png", px_per_mm=4)
    svg = drawing.to_svg(tmp_path / "drawing.svg", use_vpype=False)
    from_svg = preview(svg, tmp_path / "svg.png", px_per_mm=4)

    assert from_drawing.read_bytes() == from_svg.read_bytes()
    with Image.open(from_drawing) as image:
        assert image.size == (840, 1188)
        colors = image.getcolors(maxcolors=1_000_000) or []
        assert any(color == (0, 0, 0) for _, color in colors)


def test_public_preview_and_cli_write_the_same_png(tmp_path: Path) -> None:
    svg = tmp_path / "plot.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
        'viewBox="0 0 100 100">'
        '<g xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
        'inkscape:groupmode="layer" inkscape:label="fine" stroke="#000000" '
        'stroke-width="1"><path d="M 10 10 L 90 90"/></g>'
        "</svg>",
        encoding="utf-8",
    )
    api_output = preview(svg, tmp_path / "api.png", px_per_mm=3)
    cli_output = tmp_path / "cli.png"
    result = CliRunner().invoke(
        main, ["preview", str(svg), "-o", str(cli_output), "--px-per-mm", "3"]
    )

    assert result.exit_code == 0, result.stderr
    assert api_output.read_bytes() == cli_output.read_bytes()
