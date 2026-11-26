"""Generate the synthetic colour-block fixture.

Run with ``uv run python tests/fixtures/images/colour/generate_colour.py``.
The image is written beside this script and is reproducible pixel for pixel.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

OUTPUT_DIR = Path(__file__).resolve().parent
WIDTH = 826
HEIGHT = 422
BLOCK = 190
GAP = 12
MARGIN = 15
PAPER_RGB = (255, 255, 255)
BLOCK_COLORS: tuple[tuple[str, tuple[int, int, int]], ...] = (
    ("red", (228, 0, 43)),
    ("green", (0, 150, 62)),
    ("yellow", (247, 227, 0)),
    ("orange", (244, 116, 31)),
    ("blue", (27, 76, 158)),
    ("purple", (108, 59, 158)),
    ("black", (0, 0, 0)),
)


def make_colour_blocks() -> Image.Image:
    """Return a 4x2 grid of colour blocks on white with white gaps."""
    pixels = np.full((HEIGHT, WIDTH, 3), PAPER_RGB, dtype=np.uint8)
    for index, (_name, color) in enumerate(BLOCK_COLORS):
        row, column = divmod(index, 4)
        top = MARGIN + row * (BLOCK + GAP)
        left = MARGIN + column * (BLOCK + GAP)
        pixels[top : top + BLOCK, left : left + BLOCK] = color
    return Image.fromarray(pixels)


def main() -> None:
    """Write the reproducible colour-block fixture."""
    make_colour_blocks().save(OUTPUT_DIR / "colour_blocks.png", optimize=True)


if __name__ == "__main__":
    main()
