"""Generate the synthetic images in the Sketch Lines reference set.

Run from anywhere with ``uv run python tests/fixtures/images/reference/generate_synthetic.py``.
The images are written beside this script and are reproducible pixel for pixel.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

OUTPUT_DIR = Path(__file__).resolve().parent
SIZE = 400
RADIUS = 150.0


def make_circle() -> Image.Image:
    """Return a 400x400 black disc centred on white."""
    yy, xx = np.ogrid[:SIZE, :SIZE]
    centre = (SIZE - 1) / 2
    inside = (xx - centre) ** 2 + (yy - centre) ** 2 <= RADIUS**2
    arr = np.full((SIZE, SIZE), 255, dtype=np.uint8)
    arr[inside] = 0
    return Image.fromarray(arr).convert("RGB")


def make_gradient() -> Image.Image:
    """Return a 600x400 horizontal ramp from black on the left to white on the right."""
    width, height = 600, 400
    ramp = np.linspace(0, 255, width, dtype=np.uint8)
    arr = np.broadcast_to(ramp, (height, width)).copy()
    return Image.fromarray(arr).convert("RGB")


def make_sphere() -> Image.Image:
    """Return a 400x400 shaded sphere with its light source at the upper left."""
    yy, xx = np.ogrid[:SIZE, :SIZE]
    centre = (SIZE - 1) / 2
    dx = (xx - centre) / RADIUS
    dy = (yy - centre) / RADIUS
    radius_sq = dx**2 + dy**2
    on_sphere = radius_sq <= 1.0
    nz = np.sqrt(np.clip(1.0 - radius_sq, 0.0, 1.0))
    light = np.array([-1.0, -1.0, 1.4])
    light /= np.linalg.norm(light)
    diffuse = np.clip(dx * light[0] + dy * light[1] + nz * light[2], 0.0, 1.0)
    shade = 0.12 + 0.88 * diffuse**1.2
    arr = np.full((SIZE, SIZE), 255.0)
    arr[on_sphere] = np.clip(shade[on_sphere] * 255.0, 0.0, 255.0)
    return Image.fromarray(np.rint(arr).astype(np.uint8)).convert("RGB")


def main() -> None:
    """Write all three synthetic reference images."""
    for name, factory in (
        ("circle.png", make_circle),
        ("gradient.png", make_gradient),
        ("sphere.png", make_sphere),
    ):
        factory().save(OUTPUT_DIR / name, optimize=True)


if __name__ == "__main__":
    main()
