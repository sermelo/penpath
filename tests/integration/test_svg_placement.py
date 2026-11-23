"""Integration tests for SVG placement metadata end to end."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner
from PIL import Image
from shapely import LineString

from penpath.cli.main import main
from penpath.core.models import Paper, Pen
from penpath.core.output.svg import export_svg, fit_image_placement
from penpath.core.svg_parse import get_image_placement, parse_svg_strokes


def _make_test_image(path: Path) -> tuple[int, int]:
    """Create a small image with enough contrast to produce sketch lines."""
    image = Image.new("RGB", (100, 100), "white")
    pixels = image.load()
    for y in range(100):
        for x in range(100):
            value = 0 if (x // 10 + y // 10) % 2 == 0 else 255
            pixels[x, y] = (value, value, value)
    image.save(path)
    return image.size


def _stroke_bbox(path: Path) -> tuple[float, float, float, float]:
    """Bounding box (min_x, min_y, max_x, max_y) of drawn ink, in mm."""
    strokes = parse_svg_strokes(path)
    assert strokes
    points = [point for stroke in strokes for point in stroke.polyline]
    return (
        min(point[0] for point in points),
        min(point[1] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
    )


class TestSvgPlacementIntegration:
    def test_convert_writes_placement_metadata_and_parser_reads_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Running `penpath convert` produces an SVG with usable metadata."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        image_path = tmp_path / "input.png"
        image_size = _make_test_image(image_path)
        output_path = tmp_path / "plot.svg"

        result = CliRunner().invoke(
            main,
            [
                "convert",
                str(image_path),
                "-o",
                str(output_path),
                "--no-vpype",
                "--pfm-setting",
                "line_density=2.0",
                "--pfm-setting",
                "seed=42",
            ],
        )

        assert result.exit_code == 0, result.output
        assert output_path.exists()

        placement = get_image_placement(output_path, image_size)
        paper = Paper(name="A4", width_mm=210, height_mm=297)
        expected = fit_image_placement(
            image_size,
            paper.drawable_width_mm,
            paper.drawable_height_mm,
            offset_x_mm=paper.margin_mm,
            offset_y_mm=paper.margin_mm,
        )
        assert placement == pytest.approx(expected, abs=0.1)

        strokes = parse_svg_strokes(output_path)
        assert strokes
        assert all(stroke.pen_up is False for stroke in strokes)
        assert all(stroke.width_mm > 0 for stroke in strokes)
        assert all(
            placement.x - 0.1 <= point[0] <= placement.x + placement.width + 0.1
            and placement.y - 0.1 <= point[1] <= placement.y + placement.height + 0.1
            for stroke in strokes
            for point in stroke.polyline
        )

    def test_vpype_reads_svg_with_placement_metadata(self, tmp_path: Path) -> None:
        """vpype still reads an SVG that carries penpath placement metadata."""
        pytest.importorskip("vpype")
        vpype_path = shutil.which("vpype")
        if vpype_path is None:
            pytest.skip("vpype executable not found")

        svg_path = tmp_path / "placed.svg"
        export_svg(
            [LineString([(0, 0), (100, 50)])],
            Paper(name="square", width_mm=100, height_mm=100),
            [Pen(name="fine", width_mm=0.3)],
            svg_path,
            image_size_px=(100, 50),
            image_placement=fit_image_placement((100, 50), 100, 100),
        )

        result = subprocess.run(
            [vpype_path, "read", str(svg_path), "stat"],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "Stats" in result.stdout

    def test_vpype_reads_svg_with_injected_metadata(self, tmp_path: Path) -> None:
        """Metadata added to vpype's own output does not break vpype."""
        pytest.importorskip("vpype")
        vpype_path = shutil.which("vpype")
        if vpype_path is None:
            pytest.skip("vpype executable not found")

        from penpath.core.output.svg import add_placement_metadata
        from penpath.core.output.vpype import run_vpype

        svg_path = tmp_path / "vpype_placed.svg"
        svg_path.write_bytes(
            run_vpype(
                [LineString([(0, 0), (100, 50)])],
                Paper(name="square", width_mm=100, height_mm=100),
                [Pen(name="fine", width_mm=0.3)],
                vpype_path,
            )
        )
        add_placement_metadata(svg_path, (5.0, 5.0, 90.0, 45.0))

        assert get_image_placement(svg_path, (100, 50)) == pytest.approx((5.0, 5.0, 90.0, 45.0))

        result = subprocess.run(
            [vpype_path, "read", str(svg_path), "stat"],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "Stats" in result.stdout

    def test_convert_with_vpype_writes_placement_metadata(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The default vpype export also carries readable placement metadata."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        image_path = tmp_path / "input.png"
        image_size = _make_test_image(image_path)
        output_path = tmp_path / "vpype_plot.svg"

        result = CliRunner().invoke(
            main,
            [
                "convert",
                str(image_path),
                "-o",
                str(output_path),
                "--pfm-setting",
                "line_density=2.0",
                "--pfm-setting",
                "seed=42",
            ],
        )

        assert result.exit_code == 0, result.output
        assert "image-placement" in output_path.read_text()
        placement = get_image_placement(output_path, image_size)
        paper = Paper(name="A4", width_mm=210, height_mm=297)
        expected = fit_image_placement(
            image_size,
            paper.drawable_width_mm,
            paper.drawable_height_mm,
            offset_x_mm=paper.margin_mm,
            offset_y_mm=paper.margin_mm,
        )
        assert placement == pytest.approx(expected, abs=0.1)
        assert parse_svg_strokes(output_path)

    def test_vpype_export_geometry_inside_metadata_rectangle(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The default vpype export draws inside the rectangle it reports."""
        pytest.importorskip("vpype")
        if shutil.which("vpype") is None:
            pytest.skip("vpype executable not found")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        image_path = tmp_path / "input.png"
        image_size = _make_test_image(image_path)
        output_path = tmp_path / "vpype_plot.svg"

        result = CliRunner().invoke(
            main,
            [
                "convert",
                str(image_path),
                "-o",
                str(output_path),
                "--pfm-setting",
                "line_density=2.0",
                "--pfm-setting",
                "seed=42",
            ],
        )

        assert result.exit_code == 0, result.output
        placement = get_image_placement(output_path, image_size)
        min_x, min_y, max_x, max_y = _stroke_bbox(output_path)
        assert placement.x - 0.1 <= min_x
        assert placement.y - 0.1 <= min_y
        assert max_x <= placement.x + placement.width + 0.1
        assert max_y <= placement.y + placement.height + 0.1

    def test_direct_and_vpype_exports_agree_on_placement(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Both export paths put the same drawing in the same paper rectangle."""
        pytest.importorskip("vpype")
        if shutil.which("vpype") is None:
            pytest.skip("vpype executable not found")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        image_path = tmp_path / "input.png"
        _make_test_image(image_path)
        vpype_path = tmp_path / "vpype_plot.svg"
        direct_path = tmp_path / "direct_plot.svg"
        settings = [
            "--pfm-setting",
            "line_density=2.0",
            "--pfm-setting",
            "seed=42",
        ]

        vpype_result = CliRunner().invoke(
            main,
            ["convert", str(image_path), "-o", str(vpype_path), *settings],
        )
        direct_result = CliRunner().invoke(
            main,
            ["convert", str(image_path), "-o", str(direct_path), "--no-vpype", *settings],
        )

        assert vpype_result.exit_code == 0, vpype_result.output
        assert direct_result.exit_code == 0, direct_result.output
        assert _stroke_bbox(vpype_path) == pytest.approx(_stroke_bbox(direct_path), abs=0.2)

    def test_evaluate_likeness_agrees_between_direct_and_vpype_exports(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The crop used by evaluate no longer favours one export path."""
        pytest.importorskip("vpype")
        if shutil.which("vpype") is None:
            pytest.skip("vpype executable not found")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        image_path = tmp_path / "input.png"
        _make_test_image(image_path)
        vpype_path = tmp_path / "vpype_plot.svg"
        direct_path = tmp_path / "direct_plot.svg"
        settings = ["--pfm-setting", "line_density=2.0", "--pfm-setting", "seed=42"]
        runner = CliRunner()

        for output, extra in ((vpype_path, []), (direct_path, ["--no-vpype"])):
            result = runner.invoke(
                main, ["convert", str(image_path), "-o", str(output), *settings, *extra]
            )
            assert result.exit_code == 0, result.output

        likeness: dict[str, float] = {}
        for name, output in (("vpype", vpype_path), ("direct", direct_path)):
            result = runner.invoke(main, ["evaluate", str(image_path), str(output), "--json"])
            assert result.exit_code == 0, result.output
            likeness[name] = json.loads(result.stdout)["likeness"]

        assert likeness["vpype"] == pytest.approx(likeness["direct"], abs=0.05)
