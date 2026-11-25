"""End-to-end test: a colour image file split into per-pen images before filters."""

from pathlib import Path

import numpy as np
from PIL import Image

from penpath.core import FilterPipeline, load_image, separate_palette
from penpath.core.models import Pen


def test_separate_palette_split_before_filters(tmp_path: Path) -> None:
    image = Image.new("RGB", (24, 24), "white")
    for y in range(2, 10):
        for x in range(2, 10):
            image.putpixel((x, y), (255, 0, 0))
    for y in range(14, 22):
        for x in range(14, 22):
            image.putpixel((x, y), (0, 0, 255))
    image_path = tmp_path / "colours.png"
    image.save(image_path)

    pens = [
        Pen(name="red", width_mm=0.4, color="#FF0000"),
        Pen(name="blue", width_mm=0.4, color="#0000FF"),
        Pen(name="white", width_mm=0.4, color="#FFFFFF"),
    ]
    pipeline = FilterPipeline()
    pipeline.add_step("grayscale")
    pipeline.add_step("threshold", level=128, dither="none")

    loaded = load_image(image_path)
    filtered = [(pen, pipeline.apply(layer)) for pen, layer in separate_palette(loaded, pens)]

    assert [pen.name for pen, _ in filtered] == ["red", "blue", "white"]
    red_layer = np.asarray(filtered[0][1])
    blue_layer = np.asarray(filtered[1][1])
    white_layer = np.asarray(filtered[2][1])

    assert np.all(red_layer[2:10, 2:10] == 0)
    assert np.all(red_layer[14:22, 14:22] == 255)
    assert np.all(blue_layer[14:22, 14:22] == 0)
    assert np.all(blue_layer[2:10, 2:10] == 255)
    assert np.all(white_layer == 255)
