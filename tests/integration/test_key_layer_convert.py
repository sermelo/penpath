"""End-to-end checks for the final black key edge layer."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from click.testing import CliRunner

from penpath.cli.main import main
from penpath.core import parse_svg_strokes

COLOUR_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "images" / "colour"
TREE = COLOUR_DIR / "christmas_tree.jpg"
PALETTE = "stabilo_88"
SVG_NS = "{http://www.w3.org/2000/svg}"
INKSCAPE_NS = "{http://www.inkscape.org/namespaces/inkscape}"


@dataclass(frozen=True, slots=True)
class LayerInfo:
    """One used SVG layer and the strokes it holds."""

    label: str
    stroke_count: int
    total_length_mm: float
    longest_mm: float
    color: str


def _length_mm(polyline: tuple[tuple[float, float], ...]) -> float:
    return sum(
        math.hypot(second[0] - first[0], second[1] - first[1])
        for first, second in pairwise(polyline)
    )


def _layers(svg_path: Path) -> list[LayerInfo]:
    """Return used layers in document order, with their stroke measurements."""
    root = ET.parse(svg_path).getroot()
    layers: list[LayerInfo] = []
    for group in root.iter(SVG_NS + "g"):
        if group.get(INKSCAPE_NS + "groupmode") != "layer":
            continue
        layer_id = group.get("id")
        if layer_id is None:
            continue
        strokes = parse_svg_strokes(svg_path, layer=layer_id)
        if not strokes:
            continue
        lengths = [_length_mm(stroke.polyline) for stroke in strokes]
        layers.append(
            LayerInfo(
                label=str(group.get(INKSCAPE_NS + "label")),
                stroke_count=len(strokes),
                total_length_mm=sum(lengths),
                longest_mm=max(lengths),
                color=strokes[0].color,
            )
        )
    return layers


def _convert(source: Path, output: Path, tmp_path: Path, *flags: str) -> Path:
    """Convert an image as a user would, with the direct SVG export."""
    result = CliRunner().invoke(
        main,
        [
            "convert",
            str(source),
            "-o",
            str(output),
            "--no-vpype",
            "--quiet",
            *flags,
        ],
        env={"XDG_CONFIG_HOME": str(tmp_path / "config")},
    )
    assert result.exit_code == 0, result.output
    return output


def _palette_flags() -> tuple[str, ...]:
    return ("--palette", PALETTE, "--background-method", "global", "-s", "seed=42")


def test_palette_default_has_black_key_layer_last_with_long_edges(tmp_path: Path) -> None:
    """The default palette run adds contour strokes to the final black layer."""
    layers = _layers(_convert(TREE, tmp_path / "key.svg", tmp_path, *_palette_flags()))
    assert len(layers) >= 3
    assert layers[-1].label == "stabilo_88_black"
    assert layers[-1].longest_mm >= 30.0


def test_no_key_layer_removes_extra_edge_strokes(tmp_path: Path) -> None:
    """Disabling the key pass leaves the palette's own black strokes only."""
    with_key = _layers(_convert(TREE, tmp_path / "key.svg", tmp_path, *_palette_flags()))[-1]
    without = _layers(
        _convert(TREE, tmp_path / "nokey.svg", tmp_path, *_palette_flags(), "--no-key-layer")
    )[-1]
    assert without.label == "stabilo_88_black"
    assert with_key.stroke_count > without.stroke_count
    assert with_key.total_length_mm > without.total_length_mm


def test_single_pen_defaults_to_no_key_layer(tmp_path: Path) -> None:
    """A single pen keeps the old one-layer output unless asked for a key."""
    layers = _layers(_convert(TREE, tmp_path / "single.svg", tmp_path))
    assert len(layers) == 1
    assert layers[0].label == "fine"


def test_single_pen_key_layer_adds_black_layer_last(tmp_path: Path) -> None:
    """An explicit --key-layer on a single pen appends a distinct black layer."""
    layers = _layers(_convert(TREE, tmp_path / "singlekey.svg", tmp_path, "--key-layer"))
    assert len(layers) == 2
    assert layers[0].label == "fine"
    assert layers[-1].label == "key"
    assert layers[-1].color.lower() == "#000000"
    assert layers[-1].stroke_count > 0


def test_convert_help_lists_key_layer_option() -> None:
    """Both sides of the tri-state flag appear in convert --help."""
    result = CliRunner().invoke(main, ["convert", "--help"])
    assert result.exit_code == 0, result.output
    assert "--key-layer" in result.output
    assert "--no-key-layer" in result.output
