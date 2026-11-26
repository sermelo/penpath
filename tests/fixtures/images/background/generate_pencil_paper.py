"""Generate the synthetic pencil-on-pale-grey-paper fixture.

Run with ``uv run python tests/fixtures/images/background/generate_pencil_paper.py``.
The image is written beside this script and is reproducible pixel for pixel.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

OUTPUT_DIR = Path(__file__).resolve().parent
SIZE = 256
PAPER_RGB = np.array([232, 230, 223], dtype=np.float64)
PENCIL_RGB = np.array([78, 76, 73], dtype=np.float64)


def make_pencil_paper() -> Image.Image:
    """Return a 256x256 pale grey page with a small dark pencil sketch."""
    rng = np.random.default_rng(42)
    yy, xx = np.mgrid[0:SIZE, 0:SIZE]
    paper = np.empty((SIZE, SIZE, 3), dtype=np.float64)
    for channel in range(3):
        paper[:, :, channel] = PAPER_RGB[channel] + rng.integers(-2, 3, (SIZE, SIZE))

    canvas = paper.copy()

    def draw_segment(x0: float, y0: float, x1: float, y1: float, radius: float = 1.6) -> None:
        """Blend a round-capped antialiased pencil segment into the canvas."""
        dx, dy = x1 - x0, y1 - y0
        length_sq = dx * dx + dy * dy
        if length_sq == 0:
            t = np.zeros_like(xx, dtype=np.float64)
        else:
            t = np.clip(((xx - x0) * dx + (yy - y0) * dy) / length_sq, 0.0, 1.0)
        distance = np.hypot(xx - (x0 + t * dx), yy - (y0 + t * dy))
        coverage = np.clip(radius + 0.5 - distance, 0.0, 1.0)[:, :, None]
        canvas[:] = canvas * (1.0 - coverage) + PENCIL_RGB * coverage

    # A small sketch well inside the page: cross-hatched oval plus a diagonal.
    centre_x, centre_y = 128.0, 128.0
    for step in range(120):
        angle0 = 2.0 * np.pi * step / 120.0
        angle1 = 2.0 * np.pi * (step + 1) / 120.0
        x0 = centre_x + 62.0 * np.cos(angle0)
        y0 = centre_y + 48.0 * np.sin(angle0)
        x1 = centre_x + 62.0 * np.cos(angle1)
        y1 = centre_y + 48.0 * np.sin(angle1)
        draw_segment(x0, y0, x1, y1)
    for offset in range(-5, 6):
        draw_segment(82.0 + 4.0 * offset, 92.0, 174.0 + 4.0 * offset, 164.0, 1.2)
    draw_segment(74.0, 176.0, 182.0, 88.0, 1.4)

    pixels = np.clip(np.rint(canvas), 0, 255).astype(np.uint8)
    return Image.fromarray(pixels)


def main() -> None:
    """Write the reproducible pencil-on-paper fixture."""
    make_pencil_paper().save(OUTPUT_DIR / "pencil_on_pale_grey.png", optimize=True)


if __name__ == "__main__":
    main()
