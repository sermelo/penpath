"""Generate the synthetic white page with a lighting gradient and a dark line.

Run with ``uv run python tests/fixtures/images/background/generate_gradient_page.py``.
The image is written beside this script and is reproducible pixel for pixel.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

OUTPUT_DIR = Path(__file__).resolve().parent
SIZE = 256
BRIGHTEST = 255
DARKEST = 217
LINE_X0, LINE_X1 = 120, 123
LINE_VALUE = 32


def make_gradient_page() -> Image.Image:
    """Return a 256x256 white page dimmed by 15% with one thin dark line."""
    ramp = np.rint(np.linspace(BRIGHTEST, DARKEST, SIZE)).astype(np.uint8)
    array = np.broadcast_to(ramp[:, None, None], (SIZE, SIZE, 3)).copy()
    array[:, LINE_X0:LINE_X1] = LINE_VALUE
    return Image.fromarray(array)


def main() -> None:
    """Write the reproducible lighting-gradient fixture."""
    make_gradient_page().save(OUTPUT_DIR / "gradient_on_white.png", optimize=True)


if __name__ == "__main__":
    main()
