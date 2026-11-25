"""End-to-end tests for ``penpath convert`` progress and ``--quiet``."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from penpath.cli.main import main

IMAGE = Path(__file__).parent.parent / "fixtures" / "images" / "reference" / "circle.png"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _args(image: Path, output: Path, *extra: str) -> list[str]:
    return [
        "convert",
        str(image),
        "-o",
        str(output),
        "--no-vpype",
        "--max-resolution",
        "32",
        "-s",
        "seed=42",
        *extra,
    ]


def test_stage_lines_and_summary_go_to_stderr_with_empty_stdout(
    runner: CliRunner, tmp_path: Path
) -> None:
    output = tmp_path / "progress.svg"

    result = runner.invoke(main, _args(IMAGE, output))

    assert result.exit_code == 0, result.stderr
    assert result.stdout == ""
    stderr = result.stderr
    for line in (
        "[1/6] Loading image... done in",
        "Working resolution: 32x32 px (source 400x400 px, scale 0.080)",
        "[2/6] Downscaling image... done in",
        "[3/6] Applying filters... done in",
        "[4/6] Generating lines (PFM)... done in",
        "[5/6] Optimizing geometry... done in",
        "[6/6] Exporting SVG... done in",
        "Done in ",
        "SVG saved to:",
    ):
        assert line in stderr, stderr
    assert output.exists()


@pytest.mark.parametrize("flag", ["--quiet", "-q"])
def test_quiet_writes_nothing_but_still_writes_the_svg(
    runner: CliRunner, tmp_path: Path, flag: str
) -> None:
    output = tmp_path / "quiet.svg"

    result = runner.invoke(main, _args(IMAGE, output, flag))

    assert result.exit_code == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""
    assert output.exists()


def test_downscale_stage_is_skipped_when_no_downscaling_happens(
    runner: CliRunner, tmp_path: Path
) -> None:
    output = tmp_path / "source.svg"

    result = runner.invoke(main, _args(IMAGE, output, "--no-downscale"))

    assert result.exit_code == 0, result.stderr
    assert "Downscaling image" not in result.stderr
    assert "[1/5] Loading image" in result.stderr
    assert "[5/5] Exporting SVG" in result.stderr


def test_failure_reports_error_on_stderr_and_exits_1_even_when_quiet(
    runner: CliRunner, tmp_path: Path
) -> None:
    bad_image = tmp_path / "broken.png"
    bad_image.write_text("not an image", encoding="utf-8")

    result = runner.invoke(
        main,
        [
            "convert",
            str(bad_image),
            "-o",
            str(tmp_path / "never.svg"),
            "--no-vpype",
            "--quiet",
        ],
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Image load error" in result.stderr
