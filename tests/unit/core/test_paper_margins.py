"""Unit tests for per-side paper margins (LUC-161 part 1)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from shapely import LineString

from penpath.core.image.pipeline import FilterPipeline
from penpath.core.models import ImageRef, Paper, Pen, Project, SketchLinesPFM
from penpath.core.output.svg import export_svg
from penpath.core.project import load_yaml, save_yaml


def test_paper_scalar_margin_keeps_the_original_drawable_geometry() -> None:
    paper = Paper(name="a4", width_mm=210.0, height_mm=297.0, margin_mm=10.0)

    assert paper.margin_mm == 10.0
    assert paper.margins_mm == (10.0, 10.0, 10.0, 10.0)
    assert paper.drawable_origin_mm == (10.0, 10.0)
    assert paper.drawable_width_mm == 190.0
    assert paper.drawable_height_mm == 277.0


def test_paper_four_margins_inset_each_side_by_its_own_value() -> None:
    paper = Paper(name="custom", width_mm=200.0, height_mm=300.0, margin_mm=[5, 10, 15, 20])

    assert paper.margin_mm == (5.0, 10.0, 15.0, 20.0)
    assert paper.margins_mm == (5.0, 10.0, 15.0, 20.0)
    assert paper.drawable_origin_mm == (20.0, 5.0)
    assert paper.drawable_width_mm == 170.0
    assert paper.drawable_height_mm == 280.0


@pytest.mark.parametrize(
    "margin_mm",
    [-1.0, [1.0, -2.0, 3.0, 4.0], [1.0, 2.0, 3.0], [1.0, 2.0, 3.0, 4.0, 5.0], ["x", 2, 3, 4]],
)
def test_paper_rejects_negative_or_wrong_length_margins(margin_mm: object) -> None:
    with pytest.raises(ValidationError) as info:
        Paper(name="bad", width_mm=100.0, height_mm=100.0, margin_mm=margin_mm)  # type: ignore[arg-type]

    assert "margin_mm" in str(info.value)


def test_export_svg_centres_geometry_in_the_per_side_drawable_area(tmp_path: Path) -> None:
    paper = Paper(name="custom", width_mm=200.0, height_mm=200.0, margin_mm=[10, 20, 30, 40])
    output = tmp_path / "per-side.svg"

    export_svg([LineString([(0, 0), (100, 100)])], paper, [Pen(name="p", width_mm=0.3)], output)

    content = output.read_text(encoding="utf-8")
    assert 'd="M 40.000 20.000 L 180.000 160.000"' in content


def test_export_svg_scalar_and_equivalent_four_margins_are_identical(tmp_path: Path) -> None:
    lines = [LineString([(0, 0), (100, 100)])]
    pen = Pen(name="p", width_mm=0.3)
    scalar = tmp_path / "scalar.svg"
    per_side = tmp_path / "per-side.svg"

    export_svg(
        lines,
        Paper(name="p", width_mm=200.0, height_mm=200.0, margin_mm=10.0),
        [pen],
        scalar,
    )
    export_svg(
        lines,
        Paper(name="p", width_mm=200.0, height_mm=200.0, margin_mm=[10, 10, 10, 10]),
        [pen],
        per_side,
    )

    assert per_side.read_bytes() == scalar.read_bytes()


def _project(paper: Paper, tmp_path: Path) -> Project:
    image_path = tmp_path / "input.png"
    image_path.write_bytes(b"fake png")
    return Project(
        image=ImageRef(path=image_path, filters=FilterPipeline(), dpi=300),
        paper=paper,
        pen=Pen(name="fine", width_mm=0.3),
        pfm=SketchLinesPFM(),
        output_path=tmp_path / "output.svg",
    )


@pytest.mark.parametrize(
    ("margin_mm", "expected"),
    [
        (10.0, 10.0),
        ([5, 10, 15, 20], (5.0, 10.0, 15.0, 20.0)),
    ],
)
def test_project_yaml_round_trips_scalar_and_four_margins(
    tmp_path: Path, margin_mm: object, expected: float | tuple[float, float, float, float]
) -> None:
    project = _project(
        Paper(name="custom", width_mm=200.0, height_mm=300.0, margin_mm=margin_mm),  # type: ignore[arg-type]
        tmp_path,
    )
    path = tmp_path / "project.yaml"

    save_yaml(project, path)
    loaded = load_yaml(path)

    assert loaded.paper.margin_mm == expected
    assert loaded.paper.drawable_origin_mm == project.paper.drawable_origin_mm
    assert loaded.paper.drawable_width_mm == project.paper.drawable_width_mm
    assert loaded.paper.drawable_height_mm == project.paper.drawable_height_mm


def test_project_yaml_loads_old_scalar_margin(tmp_path: Path) -> None:
    project = _project(Paper(name="custom", width_mm=200.0, height_mm=300.0), tmp_path)
    path = tmp_path / "old.yaml"
    path.write_text(
        "version: 1\n"
        "image:\n"
        f"  path: {project.image.path}\n"
        "  dpi: 300\n"
        "  filters:\n"
        "    steps: []\n"
        "paper:\n"
        "  name: a4\n"
        "  width_mm: 210\n"
        "  height_mm: 297\n"
        "  margin_mm: 10\n"
        "pen:\n"
        "  name: fine\n"
        "  width_mm: 0.3\n"
        "pfm:\n"
        "  pfm_type: sketch_lines\n"
        "output_path: output.svg\n",
        encoding="utf-8",
    )

    loaded = load_yaml(path)

    assert loaded.paper.margin_mm == 10.0
    assert loaded.paper.drawable_width_mm == 190.0
    assert loaded.paper.drawable_height_mm == 277.0
