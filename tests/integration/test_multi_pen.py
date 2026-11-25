"""End-to-end tests for multi-pen drawing and per-layer SVG output."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import pytest
from click.testing import CliRunner
from PIL import Image
from shapely import LineString

from penpath.cli.commands import convert as convert_module
from penpath.cli.main import main

if TYPE_CHECKING:
    from collections.abc import Callable

SVG_NS = "{http://www.w3.org/2000/svg}"
INKSCAPE_NS = "{http://www.inkscape.org/namespaces/inkscape}"
PENPATH_NS = "{http://penpath.org/ns/penpath}"
PALETTE = "unused=0.4,#00FF00;red=0.4,#FF0000;blue=0.4,#0000FF;white=0.4,#FFFFFF"


class Layer(NamedTuple):
    """One Inkscape layer read back from an SVG with plain XML parsing."""

    id: str
    label: str
    strokes: set[str]
    points: list[tuple[float, float]]


@pytest.fixture
def two_region_image(tmp_path: Path) -> Path:
    """A 120x120 image: red on the left half, blue on the right half."""
    image = Image.new("RGB", (120, 120), "white")
    for y in range(120):
        for x in range(120):
            image.putpixel((x, y), (255, 0, 0) if x < 60 else (0, 0, 255))
    path = tmp_path / "two_regions.png"
    image.save(path)
    return path


@pytest.fixture
def converted_svg(two_region_image: Path, tmp_path: Path) -> Path:
    """Convert the colour image as a user would, with a fixed seed and no vpype."""
    output = tmp_path / "multi_pen.svg"
    result = CliRunner().invoke(
        main,
        [
            "convert",
            str(two_region_image),
            "-o",
            str(output),
            "--palette",
            PALETTE,
            "-s",
            "seed=42",
            "--no-vpype",
        ],
    )
    assert result.exit_code == 0, result.output
    return output


def _layers(svg_path: Path) -> list[Layer]:
    """Read the pen layers from an SVG using ElementTree only."""
    root = ET.parse(svg_path).getroot()
    groups = [g for g in root.iter(SVG_NS + "g") if g.get(INKSCAPE_NS + "groupmode") == "layer"]
    layers: list[Layer] = []
    for group in groups:
        points: list[tuple[float, float]] = []
        strokes: set[str] = set()
        for path in group.findall(SVG_NS + "path"):
            strokes.add(str(path.get("stroke")))
            tokens = path.get("d", "").replace("M", " ").replace("L", " ").split()
            points.extend(
                (float(tokens[i]), float(tokens[i + 1])) for i in range(0, len(tokens) - 1, 2)
            )
        layers.append(
            Layer(
                str(group.get("id")),
                str(group.get(INKSCAPE_NS + "label")),
                strokes,
                points,
            )
        )
    return layers


def _placement(svg_path: Path) -> tuple[float, float]:
    """Return the recorded placement's left edge and width, in millimetres."""
    metadata = ET.parse(svg_path).getroot().find(f".//{PENPATH_NS}image-placement")
    assert metadata is not None
    return float(metadata.get("x", "0")), float(metadata.get("width", "0"))


def test_convert_writes_one_layer_per_used_pen_in_drawing_order(converted_svg: Path) -> None:
    layers = _layers(converted_svg)
    assert [layer.id for layer in layers] == ["layer1", "layer2"]
    assert [layer.label for layer in layers] == ["red", "blue"]
    assert [layer.strokes for layer in layers] == [{"#FF0000"}, {"#0000FF"}]
    assert all(layer.points for layer in layers)
    root = ET.parse(converted_svg).getroot()
    assert len(root.findall(SVG_NS + "rect")) == 1  # the background is not a layer


def test_each_layer_covers_only_its_own_colour_region(converted_svg: Path) -> None:
    left, width = _placement(converted_svg)
    assert width > 0
    red, blue = _layers(converted_svg)
    red_x = [(x - left) / width for x, _ in red.points]
    blue_x = [(x - left) / width for x, _ in blue.points]
    assert red_x and blue_x
    assert max(red_x) < 0.55 and min(blue_x) > 0.45
    assert len({round(y, 3) for _, y in red.points}) > 1
    assert len({round(y, 3) for _, y in blue.points}) > 1


def test_pipeline_draws_and_optimises_each_pen_once(
    two_region_image: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_get_pfm = convert_module.get_pfm
    real_optimize = convert_module.optimize
    pfm_counts: list[int] = []
    optimize_counts: list[int] = []

    def capture_pfm(pfm_type: str) -> tuple[Callable[..., list[LineString]], object]:
        pfm_fn, settings_model = real_get_pfm(pfm_type)

        def wrapped(image: object, settings: object) -> list[LineString]:
            lines = pfm_fn(image, settings)
            pfm_counts.append(len(lines))
            return lines

        return wrapped, settings_model

    def capture_optimize(lines: object, paper: object, **kwargs: object) -> list[LineString]:
        optimize_counts.append(len(list(lines)))
        return real_optimize(lines, paper, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(convert_module, "get_pfm", capture_pfm)
    monkeypatch.setattr(convert_module, "optimize", capture_optimize)

    result = CliRunner().invoke(
        main,
        [
            "convert",
            str(two_region_image),
            "-o",
            str(tmp_path / "calls.svg"),
            "--palette",
            PALETTE,
            "-s",
            "seed=42",
            "--no-vpype",
        ],
    )
    assert result.exit_code == 0, result.output
    assert len(pfm_counts) == len(optimize_counts) == 4
    assert pfm_counts[0] == pfm_counts[3] == 0
    assert pfm_counts[1] > 0 and pfm_counts[2] > 0
