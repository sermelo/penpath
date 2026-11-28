"""End-to-end guard for the project-override seams of ``penpath convert``."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner
from PIL import Image

from penpath.cli.main import main
from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings
from penpath.core.image.pipeline import FilterPipeline
from penpath.core.models import ImageRef, Paper, Pen, Project, SketchLinesPFM
from penpath.core.project import save_yaml

INLINE_PALETTE = "red=0.4,#FF0000;blue=0.4,#0000FF"


def test_project_cli_overrides_reach_the_svg(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    image = Image.new("L", (64, 64), "white")
    image.paste("black", (16, 16, 48, 48))
    image.save(source)

    project_path = tmp_path / "project.yaml"
    save_yaml(
        Project(
            image=ImageRef(path=source, filters=FilterPipeline(), dpi=300),
            paper=Paper(name="a4", width_mm=210.0, height_mm=297.0),
            pen=Pen(name="fine", width_mm=0.3),
            pfm=SketchLinesPFM(settings=SketchLinesSettings(seed=42)),
            output_path=tmp_path / "from_project.svg",
        ),
        project_path,
    )

    output = tmp_path / "override.svg"
    result = CliRunner().invoke(
        main,
        [
            "convert",
            str(source),
            "-p",
            str(project_path),
            "-o",
            str(output),
            "--no-vpype",
            "--quiet",
            "--paper",
            "100x100,5",
            "--margin",
            "5",
            "--fit",
            "fill",
            "--pen",
            "0.6,#00FF00,fineliner",
            "-s",
            "seed=42",
        ],
        env={"XDG_CONFIG_HOME": str(tmp_path / "config")},
    )

    assert result.exit_code == 0, result.output
    assert result.stdout == ""
    svg = output.read_text()
    assert 'viewBox="0 0 100 100"' in svg
    assert 'stroke="#00FF00"' in svg
    assert 'stroke-width="0.6"' in svg
    assert not (tmp_path / "from_project.svg").exists()


def test_palette_override_on_a_project_keeps_one_layer_per_used_pen(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    image = Image.new("RGB", (64, 32), "white")
    image.paste("red", (0, 0, 32, 32))
    image.paste("blue", (32, 0, 64, 32))
    image.save(source)

    project_path = tmp_path / "project.yaml"
    save_yaml(
        Project(
            image=ImageRef(path=source, filters=FilterPipeline(), dpi=300),
            paper=Paper(name="a4", width_mm=210.0, height_mm=297.0),
            pen=Pen(name="fine", width_mm=0.3),
            pfm=SketchLinesPFM(settings=SketchLinesSettings(seed=42)),
            output_path=tmp_path / "from_project_palette.svg",
        ),
        project_path,
    )

    output = tmp_path / "palette.svg"
    result = CliRunner().invoke(
        main,
        [
            "convert",
            str(source),
            "-p",
            str(project_path),
            "-o",
            str(output),
            "--no-vpype",
            "--quiet",
            "--palette",
            INLINE_PALETTE,
            "--background-method",
            "global",
            "--saturation",
            "2.0",
            "--max-resolution",
            "48",
            "-s",
            "seed=42",
        ],
        env={"XDG_CONFIG_HOME": str(tmp_path / "config")},
    )

    assert result.exit_code == 0, result.output
    svg = output.read_text()
    assert 'inkscape:label="red"' in svg
    assert 'inkscape:label="blue"' in svg
    assert not (tmp_path / "from_project_palette.svg").exists()
