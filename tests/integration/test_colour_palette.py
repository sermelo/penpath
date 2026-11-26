"""Acceptance test for many-pen colour separation on the committed colour set."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from click.testing import CliRunner
from PIL import Image

from penpath.cli.main import main
from penpath.core import separate_palette
from penpath.presets.palettes import get_palette

COLOUR_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "images" / "colour"
PALETTE_NAME = "stabilo_88"
SEED = 42
SHARE_FLOOR_PERCENT = 2.0
SVG_NS = "{http://www.w3.org/2000/svg}"
INKSCAPE_NS = "{http://www.inkscape.org/namespaces/inkscape}"
REQUIRED_BLOCK_PENS = {
    "stabilo_88_red",
    "stabilo_88_green",
    "stabilo_88_yellow",
    "stabilo_88_blue",
    "stabilo_88_black",
}
REQUIRED_TREE_PENS = {
    "stabilo_88_red",
    "stabilo_88_yellow",
    "stabilo_88_black",
    "stabilo_88_green",
    "stabilo_88_light_green",
}


def _convert(image_name: str, tmp_path: Path) -> Path:
    """Convert a committed colour fixture as a user would, with no vpype."""
    source = COLOUR_DIR / image_name
    output = tmp_path / f"{source.stem}.svg"
    result = CliRunner().invoke(
        main,
        [
            "convert",
            str(source),
            "-o",
            str(output),
            "--palette",
            PALETTE_NAME,
            "--background-method",
            "global",
            "-s",
            f"seed={SEED}",
            "--no-vpype",
            "--quiet",
        ],
        env={"XDG_CONFIG_HOME": str(tmp_path / "config")},
    )
    assert result.exit_code == 0, result.output
    return output


def _used_pens(svg_path: Path) -> set[str]:
    """Return the labels of SVG layers that hold at least one drawn path."""
    root = ET.parse(svg_path).getroot()
    used: set[str] = set()
    for group in root.iter(SVG_NS + "g"):
        if group.get(INKSCAPE_NS + "groupmode") != "layer":
            continue
        if any(path.get("d") for path in group.findall(SVG_NS + "path")):
            label = group.get(INKSCAPE_NS + "label")
            if label:
                used.add(label)
    return used


def _pen_shares(image: Image.Image) -> dict[str, float]:
    """Return each pen's percentage of image pixels from ``separate_palette``."""
    total = image.width * image.height
    shares: dict[str, float] = {}
    for pen, channel in separate_palette(image, list(get_palette(PALETTE_NAME).pens)):
        pixels = int(np.count_nonzero(np.asarray(channel) < 255))
        shares[pen.name] = 100.0 * pixels / total
    return shares


def test_generate_colour_blocks_is_deterministic() -> None:
    """The committed PNG matches a fresh deterministic regeneration."""
    import importlib.util
    from types import ModuleType

    generator_path = COLOUR_DIR / "generate_colour.py"
    spec = importlib.util.spec_from_file_location("generate_colour", generator_path)
    assert spec is not None and spec.loader is not None
    generator = ModuleType("generate_colour")
    generator.__file__ = str(generator_path)
    spec.loader.exec_module(generator)
    fresh = generator.make_colour_blocks()
    with Image.open(COLOUR_DIR / "colour_blocks.png") as committed:
        assert np.array_equal(np.asarray(fresh), np.asarray(committed.convert("RGB")))
    assert np.array_equal(np.asarray(fresh), np.asarray(generator.make_colour_blocks()))


def test_colour_blocks_draw_at_least_six_pens(tmp_path: Path) -> None:
    """The synthetic blocks produce at least six used pens in the SVG."""
    used = _used_pens(_convert("colour_blocks.png", tmp_path))
    assert len(used) >= 6, f"only {len(used)} used pens: {sorted(used)}"
    assert used >= REQUIRED_BLOCK_PENS
    assert {"stabilo_88_purple", "stabilo_88_orange"} & used


def test_christmas_tree_meets_two_percent_share_and_layer_floor(tmp_path: Path) -> None:
    """Every required tree colour is both assigned and drawn above 2%."""
    with Image.open(COLOUR_DIR / "christmas_tree.jpg") as opened:
        shares = _pen_shares(opened.convert("RGB"))
    green = shares["stabilo_88_green"] + shares["stabilo_88_light_green"]
    measured = {
        "red": shares["stabilo_88_red"],
        "yellow": shares["stabilo_88_yellow"],
        "black": shares["stabilo_88_black"],
        "green + light_green": green,
    }
    for name, percent in measured.items():
        assert percent > SHARE_FLOOR_PERCENT, (
            f"{name} share {percent:.2f}% <= {SHARE_FLOOR_PERCENT:.1f}%; all shares: {shares}"
        )
    used = _used_pens(_convert("christmas_tree.jpg", tmp_path))
    assert used >= REQUIRED_TREE_PENS, f"missing tree layers: {sorted(REQUIRED_TREE_PENS - used)}"
