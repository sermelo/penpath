"""End-to-end checks for --no-auto-orient and removed layer options (LUC-172)."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner
from PIL import Image

from penpath.cli.main import main
from penpath.core.image.pipeline import FilterPipeline
from penpath.core.models import ImageRef, Paper, Pen, Project, SketchLinesPFM
from penpath.core.project import save_yaml
from penpath.core.svg_parse import get_image_placement

IMAGE_SIZE = (120, 60)
DPI = 300
MM_PER_INCH = 25.4


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _make_rotated_image(path: Path) -> None:
    """Write a 120x60 checkerboard JPEG tagged as EXIF orientation 6."""
    image = Image.new("L", IMAGE_SIZE, 255)
    image.putdata(
        [
            0 if (x // 10 + y // 10) % 2 == 0 else 255
            for y in range(IMAGE_SIZE[1])
            for x in range(IMAGE_SIZE[0])
        ]
    )
    exif = image.getexif()
    exif[274] = 6
    image.save(path, exif=exif)


def _convert(
    runner: CliRunner, source: Path, output: Path, *flags: str, project: Path | None = None
) -> None:
    args = [
        "convert",
        str(source),
        "-o",
        str(output),
        "--fit",
        "none",
        "--no-vpype",
        "--quiet",
        "-s",
        "seed=42",
    ]
    if project is not None:
        args.extend(["--project", str(project)])
    args.extend(flags)
    result = runner.invoke(main, args, env={"XDG_CONFIG_HOME": str(output.parent / "config")})
    assert result.exit_code == 0, result.output


def test_no_auto_orient_swaps_the_drawn_size(runner: CliRunner, tmp_path: Path) -> None:
    """With --fit none the stored pixel size depends on --no-auto-orient."""
    source = tmp_path / "rotated.jpg"
    _make_rotated_image(source)
    default_output = tmp_path / "default.svg"
    raw_output = tmp_path / "raw.svg"

    _convert(runner, source, default_output)
    _convert(runner, source, raw_output, "--no-auto-orient")

    oriented = get_image_placement(default_output, (IMAGE_SIZE[1], IMAGE_SIZE[0]))
    raw = get_image_placement(raw_output, IMAGE_SIZE)
    assert oriented.width == pytest.approx(IMAGE_SIZE[1] * MM_PER_INCH / DPI)
    assert oriented.height == pytest.approx(IMAGE_SIZE[0] * MM_PER_INCH / DPI)
    assert raw.width == pytest.approx(IMAGE_SIZE[0] * MM_PER_INCH / DPI)
    assert raw.height == pytest.approx(IMAGE_SIZE[1] * MM_PER_INCH / DPI)
    assert raw_output.read_bytes() != default_output.read_bytes()


def test_project_auto_orient_false_matches_the_cli_flag(runner: CliRunner, tmp_path: Path) -> None:
    """The saved ImageRef field drives the same path as the CLI flag."""
    source = tmp_path / "rotated.jpg"
    _make_rotated_image(source)
    project_path = tmp_path / "project.yaml"
    project_output = tmp_path / "project.svg"
    save_yaml(
        Project(
            image=ImageRef(path=source, filters=FilterPipeline(), dpi=DPI, auto_orient=False),
            paper=Paper(name="a4", width_mm=210.0, height_mm=297.0, margin_mm=10.0),
            pen=Pen(name="fine", width_mm=0.3),
            pfm=SketchLinesPFM(),
            output_path=project_output,
        ),
        project_path,
    )
    assert "auto_orient: false" in project_path.read_text(encoding="utf-8")
    cli_output = tmp_path / "cli.svg"

    _convert(runner, source, project_output, project=project_path)
    _convert(runner, source, cli_output, "--no-auto-orient")

    from_project = get_image_placement(project_output, IMAGE_SIZE)
    from_cli = get_image_placement(cli_output, IMAGE_SIZE)
    assert from_project.width == pytest.approx(from_cli.width)
    assert from_project.height == pytest.approx(from_cli.height)


@pytest.mark.parametrize("flag", ["--single-layer", "--layer-per-pen"])
def test_removed_layer_options_are_rejected(runner: CliRunner, tmp_path: Path, flag: str) -> None:
    """The no-op SVG layer options are no longer accepted by convert."""
    source = tmp_path / "rotated.jpg"
    _make_rotated_image(source)
    result = runner.invoke(main, ["convert", str(source), "-o", str(tmp_path / "out.svg"), flag])
    assert result.exit_code == 2
    assert "No such option" in result.output
