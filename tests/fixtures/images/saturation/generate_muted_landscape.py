"""Generate the synthetic muted-green landscape fixture.

Run with ``uv run python tests/fixtures/images/saturation/generate_muted_landscape.py``.
The image is written beside this script and is reproducible pixel for pixel.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

OUTPUT_DIR = Path(__file__).resolve().parent
WIDTH = 256
HEIGHT = 192
FRAME = 12
PAPER_RGB = np.array([244, 243, 238], dtype=np.float64)
SKY_RGB = np.array([235, 238, 242], dtype=np.float64)
CLOUD_RGB = np.array([255, 255, 255], dtype=np.float64)
FIELD_RGB = np.array([150, 160, 145], dtype=np.float64)
FIELD_SHADE_RGB = np.array([132, 143, 126], dtype=np.float64)
TRUNK_RGB = np.array([0, 0, 0], dtype=np.float64)


def make_muted_landscape() -> Image.Image:
    """Return a white-framed landscape whose green field is deliberately muted."""
    rng = np.random.default_rng(42)
    yy, xx = np.mgrid[0:HEIGHT, 0:WIDTH]
    canvas = np.empty((HEIGHT, WIDTH, 3), dtype=np.float64)
    canvas[:] = PAPER_RGB

    inside = (xx >= FRAME) & (xx < WIDTH - FRAME) & (yy >= FRAME) & (yy < HEIGHT - FRAME)
    horizon = 96 + 5.0 * np.sin(xx / 23.0)
    sky = inside & (yy < horizon)
    field = inside & ~sky
    shade = field & (yy > 150 + 4.0 * np.sin(xx / 17.0))
    trunk = field & (xx >= 122) & (xx <= 128) & (yy < 150)
    cloud = sky & (xx >= 40) & (xx <= 70) & (yy >= 34) & (yy <= 42)

    canvas[sky] = SKY_RGB
    canvas[field] = FIELD_RGB
    canvas[shade] = FIELD_SHADE_RGB
    canvas[trunk] = TRUNK_RGB
    canvas[cloud] = CLOUD_RGB
    noise = rng.integers(-1, 2, (HEIGHT, WIDTH, 1)).astype(np.float64)
    canvas += noise * inside[:, :, None]

    pixels = np.clip(np.rint(canvas), 0, 255).astype(np.uint8)
    return Image.fromarray(pixels)


def main() -> None:
    """Write the reproducible muted-landscape fixture."""
    make_muted_landscape().save(OUTPUT_DIR / "muted_landscape.png", optimize=True)


if __name__ == "__main__":
    main()
