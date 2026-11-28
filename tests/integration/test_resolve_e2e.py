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
