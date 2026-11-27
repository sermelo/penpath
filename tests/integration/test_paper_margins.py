"""End-to-end test that a project's per-side paper margins reach ``convert`` (LUC-161)."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner
from PIL import Image

from penpath.cli.main import main
from penpath.core.image.pipeline import FilterPipeline
from penpath.core.models import ImageRef, Paper, Pen, Project, SketchLinesPFM
from penpath.core.project import save_yaml
from penpath.core.svg_parse import get_image_placement, parse_svg_strokes


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _project(project_path: Path, image_path: Path, margin_mm: object) -> None:
    paper = Paper(name="custom", width_mm=200.0, height_mm=200.0, margin_mm=margin_mm)  # type: ignore[arg-type]
    project = Project(
        image=ImageRef(path=image_path, filters=FilterPipeline(), dpi=300),
        paper=paper,
        pen=Pen(name="fine", width_mm=0.3),
        pfm=SketchLinesPFM(),
        output_path=project_path.parent / "output.svg",
    )
    save_yaml(project, project_path)


def _convert(runner: CliRunner, project_path: Path, output: Path) -> None:
    result = runner.invoke(
        main,
        [
            "convert",
            str(project_path.parent / "input.png"),
            "-o",
            str(output),
            "--project",
            str(project_path),
            "-s",
            "seed=42",
            "--no-vpype",
            "--quiet",
        ],
    )
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize(
    ("margin_mm", "expected"),
    [
        (10.0, (10.0, 10.0, 180.0, 180.0)),
        ([10, 20, 30, 40], (40.0, 20.0, 140.0, 140.0)),
    ],
)
def test_convert_places_the_drawing_in_the_project_paper_margins(
    runner: CliRunner,
    tmp_path: Path,
    margin_mm: object,
    expected: tuple[float, float, float, float],
) -> None:
    image_path = tmp_path / "input.png"
    Image.new("L", (120, 120), 128).save(image_path)
    project_path = tmp_path / "project.yaml"
    _project(project_path, image_path, margin_mm)
    output = tmp_path / "plot.svg"

    _convert(runner, project_path, output)

    placement = get_image_placement(output, (120, 120))
    assert (placement.x, placement.y, placement.width, placement.height) == pytest.approx(expected)
    left, top, right, bottom = (
        expected[0],
        expected[1],
        expected[0] + expected[2],
        expected[1] + expected[3],
    )
    strokes = parse_svg_strokes(output)
    assert strokes
    for stroke in strokes:
        for x, y in stroke.polyline:
            assert left - 0.01 <= x <= right + 0.01
            assert top - 0.01 <= y <= bottom + 0.01
