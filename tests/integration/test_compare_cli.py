"""End-to-end tests for the ``penpath compare`` CLI command."""

from __future__ import annotations

from math import ceil
from pathlib import Path

import pytest
from click.testing import CliRunner, Result
from PIL import Image, ImageDraw

from penpath.cli.commands import compare as compare_module
from penpath.cli.main import main
from penpath.core.contact_sheet import ContactSheetEntry
from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings
from penpath.presets import list_sheet_entries


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def source(tmp_path: Path) -> Path:
    """A small dark-and-light image so every PFM has something to draw."""
    image = Image.new("RGB", (64, 64), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((4, 4, 28, 48), fill="black")
    draw.ellipse((32, 4, 60, 48), fill="black")
    path = tmp_path / "source.png"
    image.save(path)
    return path


def _expected_sheet_size(entry_count: int, columns: int) -> tuple[int, int]:
    """Sheet size for 64 px square tiles at dpi 2, columns 3, with gaps and margins."""
    rows = ceil(entry_count / columns)
    return 398, 16 + rows * 146 + (rows - 1) * 8


def _compare(runner: CliRunner, source: Path, output: Path, *flags: str) -> Result:
    """Run the real command on the fixture with small, fast tile settings."""
    args = ["compare", str(source), "-o", str(output)]
    return runner.invoke(main, [*args, "--dpi=2", "--max-resolution=64", "--columns=3", *flags])


def test_compare_writes_sheet_and_reports_on_stderr(
    runner: CliRunner, source: Path, tmp_path: Path
) -> None:
    output = tmp_path / "nested" / "sheet.png"
    entries = list_sheet_entries()
    result = _compare(runner, source, output)

    assert result.exit_code == 0, result.output
    assert result.stdout == ""
    assert str(output) in result.stderr
    assert " px, " in result.stderr
    assert f"{len(entries)} entries" in result.stderr
    assert "Failed entry" not in result.stderr
    with Image.open(output) as sheet:
        assert (sheet.format, sheet.mode) == ("PNG", "RGB")
        assert sheet.size == _expected_sheet_size(len(entries), 3)


def test_compare_rejects_nonpositive_options(
    runner: CliRunner, source: Path, tmp_path: Path
) -> None:
    output = tmp_path / "sheet.png"
    for option in ("--dpi=0", "--max-resolution=0", "--columns=0", "--max-resolution=-2"):
        result = _compare(runner, source, output, option)

        assert result.exit_code == 2, result.output
        assert option.partition("=")[0] in result.stderr
        assert "Traceback" not in result.output
        assert not output.exists()


def test_compare_reports_bad_image_naming_input(runner: CliRunner, tmp_path: Path) -> None:
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image")
    output = tmp_path / "sheet.png"

    result = _compare(runner, bad, output)

    assert result.exit_code == 1
    assert str(bad) in result.stderr
    assert "Could not load image" in result.stderr
    assert result.stdout == ""
    assert not output.exists()


def test_compare_failed_entry_is_reported_and_sheet_is_written(
    runner: CliRunner,
    source: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = list_sheet_entries()
    bad_entry = ContactSheetEntry("z_missing", None, SketchLinesSettings())
    monkeypatch.setattr(compare_module, "list_sheet_entries", lambda: [*original, bad_entry])
    output = tmp_path / "sheet.png"

    result = _compare(runner, source, output)

    assert result.exit_code == 0, result.output
    assert "Failed entry z_missing" in result.stderr
    assert "KeyError" in result.stderr
    assert f"{len(original) + 1} entries" in result.stderr
    assert result.stdout == ""
    with Image.open(output) as sheet:
        assert sheet.size == _expected_sheet_size(len(original) + 1, 3)
