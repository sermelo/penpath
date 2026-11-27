"""End-to-end tests for project-driven fit, fill and none placement (LUC-162)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner
from PIL import Image

from penpath.cli.main import main
from penpath.core.image.pipeline import FilterPipeline
from penpath.core.models import ImageRef, Paper, Pen, Project, SketchLinesPFM
from penpath.core.output.svg import fit_image_placement
from penpath.core.project import save_yaml
from penpath.core.svg_parse import get_image_placement, parse_svg_strokes

IMAGE_SIZE = (120, 120)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _make_image(path: Path) -> None:
    image = Image.new("L", IMAGE_SIZE, 255)
    pixels = image.load()
    for y in range(IMAGE_SIZE[1]):
        for x in range(IMAGE_SIZE[0]):
            pixels[x, y] = 0 if (x // 10 + y // 10) % 2 == 0 else 255
    image.save(path)


def _project(
    path: Path,
    image_path: Path,
    paper: Paper,
    output_path: Path,
    *,
    include_fit: bool = True,
) -> None:
    project = Project(
        image=ImageRef(path=image_path, filters=FilterPipeline(), dpi=300),
        paper=paper,
        pen=Pen(name="fine", width_mm=0.3),
        pfm=SketchLinesPFM(),
        output_path=output_path,
    )
    save_yaml(project, path)
    if not include_fit:
        lines = [
            line
            for line in path.read_text(encoding="utf-8").splitlines(keepends=True)
            if not line.lstrip().startswith("fit:")
        ]
        path.write_text("".join(lines), encoding="utf-8")


def _convert(
    runner: CliRunner,
    image_path: Path,
    project_path: Path,
    output_path: Path,
    *,
    no_vpype: bool,
    extra_args: list[str] | None = None,
) -> None:
    args = [
        "convert",
        str(image_path),
        "-o",
        str(output_path),
        "--project",
        str(project_path),
        "-s",
        "seed=42",
        "-s",
        "line_density=2.0",
        "--quiet",
    ]
    if no_vpype:
        args.append("--no-vpype")
    if extra_args:
        args.extend(extra_args)
    result = runner.invoke(main, args)
    assert result.exit_code == 0, result.output


def _bbox(path: Path) -> tuple[float, float, float, float]:
    points = [point for stroke in parse_svg_strokes(path) for point in stroke.polyline]
    assert points
    return (
        min(x for x, _ in points),
        min(y for _, y in points),
        max(x for x, _ in points),
        max(y for _, y in points),
    )


def test_convert_fill_crops_the_drawable_area(runner: CliRunner, tmp_path: Path) -> None:
    image_path = tmp_path / "input.png"
    _make_image(image_path)
    paper = Paper(name="landscape", width_mm=200.0, height_mm=150.0, margin_mm=10.0, fit="fill")
    project_path = tmp_path / "fill.yaml"
    output_path = tmp_path / "fill.svg"
    _project(project_path, image_path, paper, output_path)

    _convert(runner, image_path, project_path, output_path, no_vpype=True)

    expected = fit_image_placement(
        IMAGE_SIZE,
        paper.drawable_width_mm,
        paper.drawable_height_mm,
        image_dpi=300,
        offset_x_mm=10.0,
        offset_y_mm=10.0,
        mode="fill",
    )
    assert get_image_placement(output_path, IMAGE_SIZE) == pytest.approx(expected)
    assert expected.y < 10.0
    assert expected.y + expected.height > 140.0
    min_x, min_y, max_x, max_y = _bbox(output_path)
    assert 10.0 - 0.01 <= min_x <= max_x <= 190.0 + 0.01
    assert 10.0 - 0.01 <= min_y <= max_y <= 140.0 + 0.01


def test_convert_none_uses_the_dpi_size(tmp_path: Path, runner: CliRunner) -> None:
    image_path = tmp_path / "input.png"
    _make_image(image_path)
    paper = Paper(name="small", width_mm=60.0, height_mm=60.0, margin_mm=10.0, fit="none")
    project_path = tmp_path / "none.yaml"
    output_path = tmp_path / "none.svg"
    dpi_output = tmp_path / "none_72.svg"
    _project(project_path, image_path, paper, output_path)

    _convert(runner, image_path, project_path, output_path, no_vpype=True)
    _convert(
        runner,
        image_path,
        project_path,
        dpi_output,
        no_vpype=True,
        extra_args=["--dpi", "72"],
    )

    placement = get_image_placement(output_path, IMAGE_SIZE)
    assert placement.width == pytest.approx(IMAGE_SIZE[0] * 25.4 / 300)
    assert placement.height == pytest.approx(IMAGE_SIZE[1] * 25.4 / 300)
    dpi_placement = get_image_placement(dpi_output, IMAGE_SIZE)
    assert dpi_placement.width == pytest.approx(IMAGE_SIZE[0] * 25.4 / 72)
    assert dpi_placement.height == pytest.approx(IMAGE_SIZE[1] * 25.4 / 72)
    assert dpi_placement.width > paper.drawable_width_mm


def test_convert_fill_direct_and_vpype_exports_agree(runner: CliRunner, tmp_path: Path) -> None:
    pytest.importorskip("vpype")
    if shutil.which("vpype") is None:
        pytest.skip("vpype executable not found")
    image_path = tmp_path / "input.png"
    _make_image(image_path)
    paper = Paper(name="a4", width_mm=210.0, height_mm=297.0, margin_mm=10.0, fit="fill")
    project_path = tmp_path / "fill.yaml"
    direct_path = tmp_path / "direct.svg"
    vpype_path = tmp_path / "vpype.svg"
    _project(project_path, image_path, paper, direct_path)

    _convert(runner, image_path, project_path, direct_path, no_vpype=True)
    _convert(runner, image_path, project_path, vpype_path, no_vpype=False)

    assert _bbox(vpype_path) == pytest.approx(_bbox(direct_path), abs=0.2)
    for svg_path in (direct_path, vpype_path):
        min_x, min_y, max_x, max_y = _bbox(svg_path)
        assert 10.0 - 0.01 <= min_x <= max_x <= 200.0 + 0.01
        assert 10.0 - 0.01 <= min_y <= max_y <= 287.0 + 0.01


def test_convert_default_fit_is_byte_identical_to_a_project_without_fit(
    runner: CliRunner, tmp_path: Path
) -> None:
    image_path = tmp_path / "input.png"
    _make_image(image_path)
    paper = Paper(name="a4", width_mm=210.0, height_mm=297.0, margin_mm=10.0, fit="fit")
    old_project = tmp_path / "old.yaml"
    explicit_project = tmp_path / "explicit.yaml"
    old_output = tmp_path / "old.svg"
    explicit_output = tmp_path / "explicit.svg"
    _project(old_project, image_path, paper, old_output, include_fit=False)
    _project(explicit_project, image_path, paper, explicit_output)

    _convert(runner, image_path, old_project, old_output, no_vpype=True)
    _convert(runner, image_path, explicit_project, explicit_output, no_vpype=True)

    assert explicit_output.read_bytes() == old_output.read_bytes()
