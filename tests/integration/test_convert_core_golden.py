"""End-to-end guards that the refactored CLI still writes the pre-refactor SVG."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from penpath.cli.main import main

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
GOLDEN = FIXTURES / "golden" / "svg"
CIRCLE = FIXTURES / "images" / "reference" / "circle.png"
COLOUR_BLOCKS = FIXTURES / "images" / "colour" / "colour_blocks.png"
INLINE_PALETTE = "light=0.4,#87CEEB;brown=0.4,#8B4513;black=0.4,#000000"

CASES = [
    (
        "circle",
        CIRCLE,
        "luc205_circle_direct.svg",
        ("--no-vpype", "-s", "seed=42", "--max-resolution", "128"),
    ),
    (
        "palette",
        COLOUR_BLOCKS,
        "luc205_palette_direct.svg",
        (
            "--no-vpype",
            "--quiet",
            "--palette",
            INLINE_PALETTE,
            "--background-method",
            "global",
            "--saturation",
            "2.0",
            "--max-resolution",
            "96",
            "-s",
            "seed=42",
        ),
    ),
]


@pytest.mark.parametrize(("case", "source", "golden_name", "flags"), CASES)
def test_convert_matches_pre_refactor_golden(
    case: str, source: Path, golden_name: str, flags: tuple[str, ...], tmp_path: Path
) -> None:
    """The CLI writes byte-identical SVG to the output captured before the move."""
    output = tmp_path / f"{case}.svg"
    result = CliRunner().invoke(
        main,
        ["convert", str(source), "-o", str(output), *flags],
        env={"XDG_CONFIG_HOME": str(tmp_path / "config")},
    )

    assert result.exit_code == 0, result.output
    assert result.stdout == ""
    assert output.read_bytes() == (GOLDEN / golden_name).read_bytes()


def test_convert_vpype_path_matches_pre_refactor_golden(tmp_path: Path) -> None:
    """The vpype export path writes the same SVG it wrote before the move."""
    pytest.importorskip("vpype", reason="vpype not installed")
    output = tmp_path / "vpype.svg"
    result = CliRunner().invoke(
        main,
        [
            "convert",
            str(CIRCLE),
            "-o",
            str(output),
            "-s",
            "seed=42",
            "--max-resolution",
            "128",
            "--quiet",
        ],
        env={"XDG_CONFIG_HOME": str(tmp_path / "config")},
    )

    assert result.exit_code == 0, result.output
    assert output.read_bytes() == (GOLDEN / "luc205_circle_vpype.svg").read_bytes()


def test_convert_reports_stages_on_stderr_after_the_refactor(tmp_path: Path) -> None:
    """Progress still goes to stderr with the original stage names."""
    output = tmp_path / "stages.svg"
    result = CliRunner().invoke(
        main,
        [
            "convert",
            str(CIRCLE),
            "-o",
            str(output),
            "--no-vpype",
            "-s",
            "seed=42",
            "--max-resolution",
            "128",
        ],
        env={"XDG_CONFIG_HOME": str(tmp_path / "config")},
    )

    assert result.exit_code == 0, result.output
    assert result.stdout == ""
    assert "[1/6] Loading image... done in" in result.stderr
    assert "[6/6] Exporting SVG... done in" in result.stderr
    assert "Working resolution: 128x128 px" in result.stderr
