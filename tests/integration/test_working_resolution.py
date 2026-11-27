"""End-to-end tests for downscaling in ``penpath convert``."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pytest
from click.testing import CliRunner
from PIL import Image

from penpath.cli.commands import convert as convert_module
from penpath.cli.main import main
from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings
from penpath.core.drawing.registry import get_pfm
from penpath.core.image.resolution import plan_working_resolution
from penpath.core.models import Paper
from penpath.core.output.svg import fit_image_placement
from penpath.core.svg_parse import get_image_placement, get_svg_paper_size, parse_svg_strokes

if TYPE_CHECKING:
    from typing import Any

    from shapely import LineString


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def large_image(tmp_path: Path) -> Path:
    """A 200x150 image, larger than the working size used in these tests."""
    width, height = 200, 150
    y_grid, x_grid = np.mgrid[0:height, 0:width]
    tone = 255 * (1 - (x_grid + y_grid) / (width + height))
    tone = np.where(
        (x_grid > 50) & (x_grid < 150) & (y_grid > 40) & (y_grid < 110),
        tone * 0.3,
        tone,
    )
    image = Image.fromarray(np.clip(tone, 0, 255).astype(np.uint8))
    path = tmp_path / "large.png"
    image.save(path)
    return path


@pytest.fixture
def pfm_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[tuple[int, int], SketchLinesSettings]]:
    """Record the image size and settings the PFM actually receives."""
    seen: list[tuple[tuple[int, int], SketchLinesSettings]] = []
    real_get_pfm = get_pfm

    def capture(pfm_type: str) -> tuple[Any, Any]:
        pfm_fn, settings_model = real_get_pfm(pfm_type)

        def wrapped(image: object, settings: SketchLinesSettings) -> list[LineString]:
            seen.append((image.size, settings))
            return pfm_fn(image, settings)

        return wrapped, settings_model

    monkeypatch.setattr(convert_module, "get_pfm", capture)
    return seen


def _placement_attributes(svg_path: Path) -> dict[str, str]:
    root = ET.parse(svg_path).getroot()
    for element in root.iter():
        if element.tag.endswith("image-placement"):
            return dict(element.attrib)
    raise AssertionError(f"No image-placement metadata in {svg_path}")


def _convert(
    runner: CliRunner,
    image: Path,
    output: Path,
    *extra_args: str,
) -> object:
    return runner.invoke(
        main,
        [
            "convert",
            str(image),
            "-o",
            str(output),
            "--no-vpype",
            "-s",
            "seed=42",
            *extra_args,
        ],
    )


class TestWorkingResolutionReporting:
    def test_convert_reports_and_records_the_working_resolution(
        self, runner: CliRunner, large_image: Path, tmp_path: Path
    ) -> None:
        output = tmp_path / "downscaled.svg"

        result = _convert(runner, large_image, output, "--max-resolution", "64")

        assert result.exit_code == 0, result.output
        assert "Working resolution: 64x48 px (source 200x150 px, scale 0.320)" in result.output
        attrs = _placement_attributes(output)
        expected = fit_image_placement(
            (200, 150),
            area_width_mm=190.0,
            area_height_mm=277.0,
            image_dpi=300,
            offset_x_mm=10.0,
            offset_y_mm=10.0,
        )
        assert float(attrs["x"]) == pytest.approx(expected.x)
        assert float(attrs["y"]) == pytest.approx(expected.y)
        assert float(attrs["width"]) == pytest.approx(expected.width)
        assert float(attrs["height"]) == pytest.approx(expected.height)
        assert attrs["image-width"] == "64"
        assert attrs["image-height"] == "48"
        assert attrs["source-width"] == "200"
        assert attrs["source-height"] == "150"

    def test_override_below_the_minimum_is_not_clamped(
        self, runner: CliRunner, large_image: Path, tmp_path: Path
    ) -> None:
        output = tmp_path / "tiny.svg"

        result = _convert(runner, large_image, output, "--max-resolution", "32")

        assert result.exit_code == 0, result.output
        assert "Working resolution: 32x24 px" in result.output
        assert _placement_attributes(output)["image-width"] == "32"

    def test_invalid_max_resolution_is_a_usage_error(
        self, runner: CliRunner, large_image: Path, tmp_path: Path
    ) -> None:
        result = _convert(runner, large_image, tmp_path / "bad.svg", "--max-resolution", "0")

        assert result.exit_code == 2
        assert "--max-resolution" in result.output


class TestWorkingImageAndSettings:
    def test_pfm_receives_the_downscaled_image_with_working_pixel_settings(
        self,
        runner: CliRunner,
        large_image: Path,
        tmp_path: Path,
        pfm_capture: list[tuple[tuple[int, int], SketchLinesSettings]],
    ) -> None:
        result = _convert(runner, large_image, tmp_path / "scaled.svg", "--max-resolution", "64")

        assert result.exit_code == 0, result.output
        assert len(pfm_capture) == 1
        image_size, settings = pfm_capture[0]
        assert image_size == (64, 48)
        assert settings.min_length == pytest.approx(2.0)
        assert settings.max_length == pytest.approx(40.0)
        assert settings.sample_step == pytest.approx(10.0)

    def test_no_downscale_keeps_the_source_pixels(
        self,
        runner: CliRunner,
        large_image: Path,
        tmp_path: Path,
        pfm_capture: list[tuple[tuple[int, int], SketchLinesSettings]],
    ) -> None:
        output = tmp_path / "source.svg"

        result = _convert(
            runner,
            large_image,
            output,
            "--max-resolution",
            "64",
            "--no-downscale",
        )

        assert result.exit_code == 0, result.output
        assert "Working resolution: 200x150 px (source 200x150 px, scale 1.000)" in result.output
        assert len(pfm_capture) == 1
        assert pfm_capture[0][0] == (200, 150)
        assert pfm_capture[0][1].min_length == 2.0
        attrs = _placement_attributes(output)
        assert attrs["image-width"] == "200"
        assert attrs["source-width"] == "200"

    def test_placement_does_not_move_when_downscaling(
        self, runner: CliRunner, large_image: Path, tmp_path: Path
    ) -> None:
        downscaled = tmp_path / "downscaled.svg"
        source = tmp_path / "source.svg"

        result_a = _convert(runner, large_image, downscaled, "--max-resolution", "64")
        result_b = _convert(runner, large_image, source, "--no-downscale")
        assert result_a.exit_code == 0, result_a.output
        assert result_b.exit_code == 0, result_b.output

        attrs_a = _placement_attributes(downscaled)
        attrs_b = _placement_attributes(source)
        for key in ("x", "y", "width", "height"):
            assert attrs_a[key] == attrs_b[key]

    def test_vpype_export_records_the_resolution(
        self, runner: CliRunner, large_image: Path, tmp_path: Path
    ) -> None:
        output = tmp_path / "vpype.svg"

        result = runner.invoke(
            main,
            [
                "convert",
                str(large_image),
                "-o",
                str(output),
                "--max-resolution",
                "64",
                "-s",
                "seed=42",
            ],
        )

        assert result.exit_code == 0, result.output
        attrs = _placement_attributes(output)
        assert attrs["image-width"] == "64"
        assert attrs["source-width"] == "200"


class TestInfoImageResolution:
    def test_info_image_reports_the_planned_resolution(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        image_path = tmp_path / "big.png"
        Image.new("RGB", (1200, 800), "white").save(image_path)

        result = runner.invoke(main, ["info", "image", str(image_path), "--format", "json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert data["working_resolution"] == {
            "width": 990,
            "height": 660,
            "working_px": 990,
            "scale": pytest.approx(990 / 1200),
            "paper": "a4",
            "pen_width_mm": 0.3,
        }


class TestPaperSizeAndScaling:
    def test_smaller_paper_derives_a_coarser_working_resolution(self) -> None:
        large = Paper(name="large", width_mm=190.0, height_mm=107.0, margin_mm=0.0)
        small = Paper(name="small", width_mm=130.0, height_mm=73.0, margin_mm=0.0)

        wide = plan_working_resolution((200, 150), large, 0.4)
        narrow = plan_working_resolution((200, 150), small, 0.4)

        assert wide.working_px == 475
        assert narrow.working_px == 325
        assert narrow.working_px < wide.working_px

    def test_same_max_resolution_is_a_uniform_scaled_copy(
        self, runner: CliRunner, large_image: Path, tmp_path: Path
    ) -> None:
        large_svg = tmp_path / "190x107.svg"
        small_svg = tmp_path / "130x73.svg"
        common = ("--max-resolution", "64", "--pen", "0.4,#000000,fineliner")

        wide = _convert(runner, large_image, large_svg, "--paper", "190x107,0", *common)
        narrow = _convert(runner, large_image, small_svg, "--paper", "130x73,0", *common)

        assert wide.exit_code == 0, wide.output
        assert narrow.exit_code == 0, narrow.output
        assert "Working resolution: 64x48 px" in wide.output
        assert "Working resolution: 64x48 px" in narrow.output

        wide_strokes = parse_svg_strokes(large_svg)
        narrow_strokes = parse_svg_strokes(small_svg)
        assert wide_strokes
        assert len(wide_strokes) == len(narrow_strokes)

        wide_page = get_svg_paper_size(large_svg)
        narrow_page = get_svg_paper_size(small_svg)
        assert wide_page is not None and narrow_page is not None
        assert wide_page == (190.0, 107.0)
        assert narrow_page == (130.0, 73.0)

        wide_place = get_image_placement(large_svg, (200, 150))
        narrow_place = get_image_placement(small_svg, (200, 150))
        assert narrow_place.width / narrow_page[0] == pytest.approx(
            wide_place.width / wide_page[0], rel=0.02
        )
        assert narrow_place.x / narrow_page[0] == pytest.approx(
            wide_place.x / wide_page[0], rel=0.02
        )
        assert narrow_place.height / narrow_page[1] == pytest.approx(
            wide_place.height / wide_page[1], rel=0.02
        )
        assert narrow_place.y / narrow_page[1] == pytest.approx(
            wide_place.y / wide_page[1], rel=0.02
        )

        for first, second in zip(wide_strokes, narrow_strokes, strict=True):
            assert len(first.polyline) == len(second.polyline)
            for (wide_x, wide_y), (narrow_x, narrow_y) in zip(
                first.polyline, second.polyline, strict=True
            ):
                assert (narrow_x - narrow_place.x) / narrow_place.width == pytest.approx(
                    (wide_x - wide_place.x) / wide_place.width, abs=1e-3
                )
                assert (narrow_y - narrow_place.y) / narrow_place.height == pytest.approx(
                    (wide_y - wide_place.y) / wide_place.height, abs=1e-3
                )
