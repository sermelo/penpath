"""End-to-end checks that the white-source pen lift reaches the CLI."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from click.testing import CliRunner
from PIL import Image

from penpath.cli.main import main
from penpath.core import get_image_placement, parse_svg_strokes

WIDTH = 200
HEIGHT = 120
GAP = (60, 140)


def _two_blocks(tmp_path: Path) -> Path:
    image = Image.new("L", (WIDTH, HEIGHT), 255)
    for y in range(30, 90):
        for x in (*range(20, GAP[0]), *range(GAP[1], 180)):
            image.putpixel((x, y), 0)
    path = tmp_path / "two_blocks.png"
    image.save(path)
    return path


@pytest.mark.parametrize("pfm", ("sketch_lines", "sketch_squares"))
def test_convert_leaves_a_white_gap_blank(tmp_path: Path, pfm: str) -> None:
    """`convert -s white_threshold=0.9` inks no source pixels in the gap."""
    image_path = _two_blocks(tmp_path)
    svg_path = tmp_path / f"{pfm}.svg"
    result = CliRunner().invoke(
        main,
        [
            "convert",
            str(image_path),
            "-o",
            str(svg_path),
            "--pfm",
            pfm,
            "-s",
            "seed=42",
            "-s",
            "white_threshold=0.9",
            "--no-vpype",
            "--quiet",
        ],
    )
    assert result.exit_code == 0, result.output

    strokes = parse_svg_strokes(svg_path)
    assert strokes
    placement = get_image_placement(svg_path, (WIDTH, HEIGHT))
    for stroke in strokes:
        for (x0, y0), (x1, y1) in zip(stroke.polyline, stroke.polyline[1:], strict=False):
            steps = max(1, math.ceil(2 * math.hypot(x1 - x0, y1 - y0)))
            for index in range(steps + 1):
                page_x = x0 + (x1 - x0) * index / steps
                page_y = y0 + (y1 - y0) * index / steps
                px = (page_x - placement.x) / placement.width * WIDTH
                py = (page_y - placement.y) / placement.height * HEIGHT
                assert not (GAP[0] <= px < GAP[1] and 30 <= py < 90)
