"""End-to-end tests for the SVG layout written on both export paths."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from click.testing import CliRunner
from PIL import Image, ImageColor

from penpath.cli.main import main
from penpath.core.svg_parse import parse_svg_strokes

SVG_NS = "{http://www.w3.org/2000/svg}"
INKSCAPE_NS = "{http://www.inkscape.org/namespaces/inkscape}"


@pytest.fixture
def reference(tmp_path: Path) -> Path:
    image = Image.new("RGB", (64, 64), "white")
    pixels = image.load()
    for index in range(64):
        pixels[index, index] = (0, 0, 0)
    path = tmp_path / "reference.png"
    image.save(path)
    return path


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _layer_attrs(svg_path: Path, label: str) -> dict[str, str]:
    """Return the attributes of the Inkscape layer with the given label."""
    root = ET.parse(svg_path).getroot()
    for group in root.iter(SVG_NS + "g"):
        if group.get(INKSCAPE_NS + "groupmode") != "layer":
            continue
        if group.get(INKSCAPE_NS + "label") == label:
            attrs = dict(group.attrib)
            path = group.find(SVG_NS + "path")
            if path is not None:
                attrs.update(
                    {key: value for key, value in path.attrib.items() if key in ("stroke", "fill")}
                )
            return attrs
    raise AssertionError(f"No SVG layer labelled {label!r}")


def _convert(runner: CliRunner, reference: Path, output: Path, *extra_args: str) -> None:
    result = runner.invoke(
        main,
        ["convert", str(reference), "-o", str(output), "-s", "seed=42", *extra_args],
    )
    assert result.exit_code == 0, result.output


def _assert_penpath_layout(svg_path: Path, pen_name: str, colour: str, width: str) -> None:
    """Check the agreed millimetre layout with plain XML parsing."""
    root = ET.parse(svg_path).getroot()
    assert root.get("width") == "210mm"
    assert root.get("height") == "297mm"
    assert root.get("viewBox") == "0 0 210 297"

    assert root.findall(SVG_NS + "rect") == []

    groups = list(root.iter(SVG_NS + "g"))
    assert len(groups) == 1
    group = groups[0]
    assert group.get(INKSCAPE_NS + "groupmode") == "layer"
    assert group.get(INKSCAPE_NS + "label") == pen_name
    assert group.get("id") == "layer1"

    paths = list(group.findall(SVG_NS + "path"))
    assert paths
    for path in paths:
        assert path.get("fill") == "none"
        assert path.get("stroke") == colour
        assert path.get("stroke-width") == width


def _require_vpype() -> None:
    """Skip the acceptance test when vpype is absent or cannot run here."""
    pytest.importorskip("vpype")
    if shutil.which("vpype") is None:
        pytest.skip("vpype executable not found")
    probe = subprocess.run(
        ["vpype", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        pytest.skip(f"vpype executable unusable: {probe.stderr.strip()}")


def _vpype_bounds_mm(svg_path: Path) -> tuple[float, float, float, float]:
    """Return the bounds reported by `vpype read <svg> stat`, in millimetres."""
    result = subprocess.run(
        ["vpype", "read", str(svg_path), "stat"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    lines = [line for line in result.stdout.splitlines() if "Bounds:" in line]
    assert lines, result.stdout
    numbers = r"(?<![A-Za-z0-9_])[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
    boxes = [tuple(float(value) for value in re.findall(numbers, line)[:4]) for line in lines]
    assert all(len(box) == 4 for box in boxes), result.stdout
    mm_per_vpype_unit = 25.4 / 96
    return (
        min(box[0] for box in boxes) * mm_per_vpype_unit,
        min(box[1] for box in boxes) * mm_per_vpype_unit,
        max(box[2] for box in boxes) * mm_per_vpype_unit,
        max(box[3] for box in boxes) * mm_per_vpype_unit,
    )


def _stroke_bbox_mm(svg_path: Path) -> tuple[float, float, float, float]:
    """Return the bounding box of the parsed ink, in millimetres."""
    strokes = parse_svg_strokes(svg_path)
    assert strokes
    points = [point for stroke in strokes for point in stroke.polyline]
    return (
        min(point[0] for point in points),
        min(point[1] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
    )


class TestPenpathSvgLayout:
    """Both export paths end in a penpath-written, millimetre SVG."""

    def test_default_convert_output_carries_pen_colour_and_label(
        self, runner: CliRunner, reference: Path, tmp_path: Path
    ) -> None:
        plot = tmp_path / "plot.svg"
        _convert(runner, reference, plot)

        _assert_penpath_layout(plot, "fine", "#000000", "0.3")
        assert b"#0000ff" not in plot.read_bytes()
        assert parse_svg_strokes(plot)
        assert parse_svg_strokes(plot, layer="fine")
        assert _layer_attrs(plot, "fine")["id"] == "layer1"

    def test_direct_export_has_the_same_layout(
        self, runner: CliRunner, reference: Path, tmp_path: Path
    ) -> None:
        plot = tmp_path / "direct.svg"
        _convert(runner, reference, plot, "--pen", "red_fine", "--no-vpype")

        _assert_penpath_layout(plot, "red_fine", "#FF0000", "0.3")

    def test_vpype_and_direct_exports_agree_on_pen(
        self, runner: CliRunner, reference: Path, tmp_path: Path
    ) -> None:
        vpype_plot = tmp_path / "vpype.svg"
        direct_plot = tmp_path / "direct.svg"
        _convert(runner, reference, vpype_plot, "--pen", "red_fine")
        _convert(runner, reference, direct_plot, "--pen", "red_fine", "--no-vpype")

        vpype_layer = _layer_attrs(vpype_plot, "red_fine")
        direct_layer = _layer_attrs(direct_plot, "red_fine")
        assert ImageColor.getrgb(vpype_layer.get("stroke", "#000000")) == (255, 0, 0)
        assert ImageColor.getrgb(vpype_layer.get("stroke", "#000000")) == ImageColor.getrgb(
            direct_layer.get("stroke", "#000000")
        )

    def test_layer_ids_are_numeric_even_when_labels_contain_digits(
        self, runner: CliRunner, reference: Path, tmp_path: Path
    ) -> None:
        """The G-code step maps numeric ids, not vpype's digits in labels."""
        plot = tmp_path / "palette.svg"
        _convert(runner, reference, plot, "--palette", "stabilo_88")

        root = ET.parse(plot).getroot()
        group = next(root.iter(SVG_NS + "g"))
        assert group.get(INKSCAPE_NS + "label") == "stabilo_88_black"
        assert group.get("id") == "layer1"

    def test_evaluate_by_pen_label_keys_cost_by_pen_colour(
        self, runner: CliRunner, reference: Path, tmp_path: Path
    ) -> None:
        plot = tmp_path / "plot.svg"
        _convert(runner, reference, plot, "--pen", "red_fine")

        result = runner.invoke(
            main,
            ["evaluate", str(reference), str(plot), "--layer", "red_fine", "--json"],
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        per_layer = payload["machine_cost"]["per_layer"]
        assert set(per_layer) == {"#FF0000"}
        assert "#0000ff" not in per_layer

    def test_preview_renders_ink_in_the_pen_colour(
        self, runner: CliRunner, reference: Path, tmp_path: Path
    ) -> None:
        plot = tmp_path / "plot.svg"
        preview = tmp_path / "preview.png"
        _convert(runner, reference, plot, "--pen", "red_fine")

        result = runner.invoke(main, ["preview", str(plot), "-o", str(preview), "--dpi", "2"])

        assert result.exit_code == 0, result.output
        with Image.open(preview) as image:
            pixels = list(image.getdata())
        reds = [pixel for pixel in pixels if pixel[0] > 200 and pixel[1] < 60 and pixel[2] < 60]
        blues = [pixel for pixel in pixels if pixel[2] > 150 and pixel[0] < 100]
        assert reds
        assert not blues

    def test_evaluate_likeness_is_stable_between_export_paths(
        self, runner: CliRunner, reference: Path, tmp_path: Path
    ) -> None:
        """The millimetre viewBox keeps the same score on both paths."""
        vpype_plot = tmp_path / "vpype.svg"
        direct_plot = tmp_path / "direct.svg"
        _convert(runner, reference, vpype_plot)
        _convert(runner, reference, direct_plot, "--no-vpype")

        scores: dict[str, float] = {}
        for name, plot in (("vpype", vpype_plot), ("direct", direct_plot)):
            result = runner.invoke(main, ["evaluate", str(reference), str(plot), "--json"])
            assert result.exit_code == 0, result.output
            scores[name] = json.loads(result.stdout)["likeness"]

        assert scores["vpype"] == pytest.approx(scores["direct"], abs=0.05)


class TestVpypeReadBounds:
    """`vpype read` sees the drawing, never the page-sized background."""

    @pytest.mark.parametrize(
        "extra_args",
        [[], ["--palette", "stabilo_88"]],
        ids=["single-pen", "palette"],
    )
    def test_vpype_read_bounds_match_ink_not_page(
        self,
        extra_args: list[str],
        runner: CliRunner,
        reference: Path,
        tmp_path: Path,
    ) -> None:
        _require_vpype()
        plot = tmp_path / "plot.svg"
        _convert(runner, reference, plot, *extra_args)

        assert ET.parse(plot).getroot().findall(SVG_NS + "rect") == []
        ink_bbox = _stroke_bbox_mm(plot)
        assert _vpype_bounds_mm(plot) == pytest.approx(ink_bbox, abs=0.5)
