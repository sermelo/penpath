"""Unit tests for the thin ``penpath compare`` CLI layer."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner
from PIL import Image

from penpath.cli.commands import compare as compare_module
from penpath.cli.commands.compare import compare_cmd


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "source.png"
    Image.new("RGB", (32, 32), "white").save(path)
    return path


def _args(output: Path, *flags: str) -> list[str]:
    return ["-o", str(output), "--dpi=2", "--max-resolution=16", *flags]


def test_compare_empty_catalog_is_a_clean_error(
    runner: CliRunner, source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(compare_module, "list_sheet_entries", lambda: [])
    output = tmp_path / "sheet.png"

    result = runner.invoke(compare_cmd, [str(source), *_args(output)])

    assert result.exit_code == 1
    assert "No contact sheet entries found" in result.stderr
    assert result.stdout == ""
    assert not output.exists()


def test_compare_invalid_paper_color_is_a_usage_error(
    runner: CliRunner, source: Path, tmp_path: Path
) -> None:
    output = tmp_path / "sheet.png"
    result = runner.invoke(compare_cmd, [str(source), *_args(output, "--paper-color=notacolour")])

    assert result.exit_code == 2
    assert "--paper-color" in result.stderr
    assert "Traceback" not in result.output
    assert result.stdout == ""
    assert not output.exists()
