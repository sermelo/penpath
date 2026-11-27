"""Unit tests for the Paper.fit field and project YAML round-trip (LUC-162)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from penpath.core.image.pipeline import FilterPipeline
from penpath.core.models import ImageRef, Paper, Pen, Project, SketchLinesPFM
from penpath.core.project import load_yaml, save_yaml


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


def test_paper_fit_defaults_to_fit() -> None:
    assert Paper(name="a4", width_mm=210.0, height_mm=297.0).fit == "fit"


@pytest.mark.parametrize("fit", ["fill", "none"])
def test_project_yaml_round_trips_paper_fit(tmp_path: Path, fit: str) -> None:
    project = _project(
        Paper(name="a4", width_mm=210.0, height_mm=297.0, fit=fit),  # type: ignore[arg-type]
        tmp_path,
    )
    path = tmp_path / "project.yaml"

    save_yaml(project, path)
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["paper"]["fit"] == fit
    assert load_yaml(path).paper.fit == fit


def test_project_yaml_without_fit_loads_as_fit(tmp_path: Path) -> None:
    _project(Paper(name="a4", width_mm=210.0, height_mm=297.0), tmp_path)
    path = tmp_path / "old.yaml"
    path.write_text(
        "version: 1\n"
        "image:\n"
        f"  path: {tmp_path / 'input.png'}\n"
        "  filters:\n"
        "    steps: []\n"
        "  dpi: 300\n"
        "paper:\n"
        "  name: a4\n"
        "  width_mm: 210\n"
        "  height_mm: 297\n"
        "pen:\n"
        "  name: fine\n"
        "  width_mm: 0.3\n"
        "pfm:\n"
        "  pfm_type: sketch_lines\n"
        "output_path: output.svg\n",
        encoding="utf-8",
    )

    assert load_yaml(path).paper.fit == "fit"


def test_paper_rejects_an_unknown_fit() -> None:
    with pytest.raises(ValidationError) as info:
        Paper(name="a4", width_mm=210.0, height_mm=297.0, fit="stretch")  # type: ignore[arg-type]

    assert "fit" in str(info.value)
