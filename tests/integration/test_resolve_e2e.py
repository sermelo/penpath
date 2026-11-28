"""End-to-end coverage of the core resolvers through ``penpath convert``."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner
from PIL import Image

from penpath.cli.main import main


@pytest.fixture
def sample_image(tmp_path: Path) -> Path:
    path = tmp_path / "source.png"
    image = Image.new("RGB", (48, 48), "white")
    pixels = image.load()
    for y in range(48):
        for x in range(48):
            value = 255 - int((x + y) * 2)
            pixels[x, y] = (value, value, value)
    image.paste("black", (16, 16, 32, 32))
    image.save(path)
    return path


def test_convert_resolves_inline_pen_paper_and_pfm_preset(
    sample_image: Path, tmp_path: Path
) -> None:
    output = tmp_path / "inline.svg"
    result = CliRunner().invoke(
        main,
        [
            "convert",
            str(sample_image),
            "-o",
            str(output),
            "--no-vpype",
            "--pen",
            "0.4,#FF0000,fineliner",
            "--paper",
            "190x190,20,5,20,5",
            "--pfm",
            "sketch_lines:fine",
            "-s",
            "seed=42",
        ],
    )

    assert result.exit_code == 0, result.output
    svg = output.read_text()
    assert 'viewBox="0 0 190 190"' in svg
    assert 'stroke="#FF0000"' in svg
    assert 'id="layer1"' in svg


def test_margin_override_is_applied_after_paper_resolution(
    sample_image: Path, tmp_path: Path
) -> None:
    output = tmp_path / "margin.svg"
    result = CliRunner().invoke(
        main,
        [
            "convert",
            str(sample_image),
            "-o",
            str(output),
            "--no-vpype",
            "--paper",
            "50x50,30,5,30,5",
            "--margin",
            "5",
            "-s",
            "seed=42",
        ],
    )

    assert result.exit_code == 0, result.output
    assert output.exists()


def test_convert_resolves_builtin_palette_and_registered_pfm(
    sample_image: Path, tmp_path: Path
) -> None:
    output = tmp_path / "palette.svg"
    result = CliRunner().invoke(
        main,
        [
            "convert",
            str(sample_image),
            "-o",
            str(output),
            "--no-vpype",
            "--palette",
            "red=0.4,#FF0000;blue=0.4,#0000FF",
            "--pfm",
            "sketch_squares:fine",
            "-s",
            "seed=42",
            "--max-resolution",
            "64",
        ],
    )

    assert result.exit_code == 0, result.output
    svg = output.read_text()
    assert 'inkscape:label="red"' in svg
    assert 'stroke="#FF0000"' in svg
    assert 'id="layer1"' in svg


def test_project_file_cli_overrides_use_core_resolvers(sample_image: Path, tmp_path: Path) -> None:
    project_path = tmp_path / "project.yaml"
    project_path.write_text(
        f"""version: 1
image:
  path: "{sample_image}"
  filters:
    steps: []
  dpi: 300
pen:
  name: fine
  width_mm: 0.3
paper:
  name: a4
  width_mm: 210.0
  height_mm: 297.0
pfm:
  pfm_type: sketch_squares
  settings:
    seed: 42
output_path: "{tmp_path / "from_project.svg"}"
"""
    )
    output = tmp_path / "override.svg"
    result = CliRunner().invoke(
        main,
        [
            "convert",
            str(sample_image),
            "-p",
            str(project_path),
            "-o",
            str(output),
            "--no-vpype",
            "--max-resolution",
            "48",
            "--pen",
            "0.6,#00FF00,fineliner",
            "--paper",
            "100x100",
            "--pfm",
            "sketch_lines:fine",
            "-s",
            "seed=42",
        ],
    )

    assert result.exit_code == 0, result.output
    svg = output.read_text()
    assert 'viewBox="0 0 100 100"' in svg
    assert 'stroke-width="0.6"' in svg
    assert 'stroke="#00FF00"' in svg


def test_config_presets_and_defaults_drive_convert(sample_image: Path, tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """default_pen = "custom"
default_paper = "custom"

[pens.custom]
width = 1.0
color = "blue"

[papers.custom]
width = 300.0
height = 300.0
margin = 20.0
"""
    )
    output = tmp_path / "config.svg"
    result = CliRunner().invoke(
        main,
        [
            "convert",
            str(sample_image),
            "-o",
            str(output),
            "--no-vpype",
            "--max-resolution",
            "48",
            "-c",
            str(config_path),
            "-s",
            "seed=42",
        ],
    )

    assert result.exit_code == 0, result.output
    svg = output.read_text()
    assert 'viewBox="0 0 300 300"' in svg
    assert 'stroke-width="1"' in svg
    assert 'stroke="#0000FF"' in svg
