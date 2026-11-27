"""End-to-end evidence for LUC-128's shipped Sketch Lines defaults.

Runs the two commands from the bug report and reads the rendered preview the
same way a person does, then ranks tile ink against source darkness.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner
from PIL import Image
from sketch_lines_gate import (
    DARK_TILE_INK_MAX,
    DARK_TILE_INK_MIN,
    RANK_MIN,
    ink_mask,
    tile_readability,
)

from penpath.cli.main import main
from penpath.core import get_image_placement

REFERENCE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "images" / "reference"
PREVIEW_PX_PER_MM = 10.0
PHOTOS = ("face.jpg", "photo.jpg")


@pytest.mark.parametrize("name", PHOTOS)
def test_default_convert_and_preview_show_readable_tone_steps(name: str, tmp_path: Path) -> None:
    """The default convert path renders a photo with tone-following hatch gaps."""
    svg = tmp_path / "plot.svg"
    png = tmp_path / "plot.png"
    result = CliRunner().invoke(
        main,
        [
            "convert",
            str(REFERENCE_DIR / name),
            "-o",
            str(svg),
            "--pen",
            "medium",
            "--paper",
            "180x180",
            "--no-vpype",
            "-s",
            "seed=42",
            "--quiet",
        ],
    )
    assert result.exit_code == 0, result.output
    preview = CliRunner().invoke(
        main,
        ["preview", str(svg), "-o", str(png), "--px-per-mm", str(PREVIEW_PX_PER_MM)],
    )
    assert preview.exit_code == 0, preview.output

    with Image.open(REFERENCE_DIR / name) as opened:
        original = opened.convert("RGB")
    placement = get_image_placement(svg, original.size)
    with Image.open(png) as opened:
        plot = opened.convert("RGB")
    left = round(placement.x * PREVIEW_PX_PER_MM)
    top = round(placement.y * PREVIEW_PX_PER_MM)
    right = left + round(placement.width * PREVIEW_PX_PER_MM)
    bottom = top + round(placement.height * PREVIEW_PX_PER_MM)
    crop = (left, top, min(right, plot.width), min(bottom, plot.height))
    source = original.resize((crop[2] - crop[0], crop[3] - crop[1]), Image.Resampling.LANCZOS)
    rank, ink_max, tiles = tile_readability(ink_mask(plot, crop), source)

    assert tiles >= 8
    assert rank >= RANK_MIN
    assert DARK_TILE_INK_MIN <= ink_max <= DARK_TILE_INK_MAX
