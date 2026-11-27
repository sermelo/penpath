"""End-to-end tests for hatch PFM selection, physical scale and contact sheets."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from click.testing import CliRunner, Result
from PIL import Image, ImageDraw
from shapely import LineString

from penpath.cli.main import main
from penpath.core import contact_sheet
from penpath.core.contact_sheet import (
    TILE_WIDTH_MM,
    ContactSheetEntry,
    render_contact_sheet,
)
from penpath.core.drawing import registry as registry_module
from penpath.core.drawing.pfm_hatch import HatchSettings, hatch_strokes
from penpath.presets import list_sheet_entries


@pytest.fixture
def source(tmp_path: Path) -> Path:
    """A small dark-and-light image so hatch has something to draw."""
    image = Image.new("RGB", (64, 64), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((4, 4, 28, 48), fill="black")
    draw.ellipse((32, 4, 60, 48), fill="black")
    path = tmp_path / "source.png"
    image.save(path)
    return path


def _convert(source: Path, output: Path, *flags: str) -> Result:
    """Convert with a predictable pixel size so the scale assertion is exact."""
    return CliRunner().invoke(
        main,
        [
            "convert",
            str(source),
            "-o",
            str(output),
            "--no-vpype",
            "--fit",
            "none",
            *flags,
        ],
    )


def _capture_hatch(
    seen: list[tuple[HatchSettings, dict[str, float]]],
) -> Callable[..., list[LineString]]:
    """Replace the registered hatch function with one that records its kwargs."""

    def capture(image: Image.Image, settings: HatchSettings, **kwargs: float) -> list[LineString]:
        seen.append((settings, kwargs))
        return hatch_strokes(image, settings, **kwargs)

    return capture


def test_convert_hatch_writes_svg_with_physical_scale(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[HatchSettings, dict[str, float]]] = []
    monkeypatch.setitem(
        registry_module.get_registry()._pfms,
        "hatch",
        (_capture_hatch(seen), HatchSettings),
    )
    output = tmp_path / "hatch.svg"

    result = _convert(source, output, "--pfm", "hatch")

    assert result.exit_code == 0, result.output
    assert output.exists()
    assert "<svg" in output.read_text()
    assert len(seen) == 1
    settings, kwargs = seen[0]
    assert isinstance(settings, HatchSettings)
    assert kwargs["pixels_per_mm"] == pytest.approx(300.0 / 25.4)
    assert kwargs["pen_width_mm"] == 0.3


def test_convert_hatch_palette_rotates_angles_per_pen(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[HatchSettings, dict[str, float]]] = []
    monkeypatch.setitem(
        registry_module.get_registry()._pfms,
        "hatch",
        (_capture_hatch(seen), HatchSettings),
    )
    output = tmp_path / "palette.svg"

    result = _convert(
        source,
        output,
        "--pfm",
        "hatch:single",
        "--no-background",
        "--palette",
        "red=0.4,#FF0000;blue=0.4,#0000FF",
    )

    assert result.exit_code == 0, result.output
    assert output.exists()
    assert len(seen) == 2
    assert seen[0][0].angles == (45.0, 45.0, 45.0, 45.0)
    assert seen[1][0].angles == (75.0, 75.0, 75.0, 75.0)
    assert [kwargs["pen_width_mm"] for _, kwargs in seen] == [0.4, 0.4]


@pytest.mark.parametrize(
    "pfm_id", ["hatch", "hatch:default", "hatch:crosshatch", "hatch:fine", "hatch:single"]
)
def test_convert_each_hatch_preset_writes_svg(source: Path, tmp_path: Path, pfm_id: str) -> None:
    output = tmp_path / f"{pfm_id.replace(':', '_')}.svg"

    result = _convert(source, output, "--pfm", pfm_id)

    assert result.exit_code == 0, result.output
    assert output.exists()
    assert "<svg" in output.read_text()


def test_compare_includes_hatch_tiles_without_errors(source: Path, tmp_path: Path) -> None:
    output = tmp_path / "sheet.png"
    entries = list_sheet_entries()

    result = CliRunner().invoke(
        main,
        [
            "compare",
            str(source),
            "-o",
            str(output),
            "--dpi=2",
            "--max-resolution=64",
            "--columns=3",
        ],
    )

    assert result.exit_code == 0, result.output
    assert result.stdout == ""
    assert "Failed entry" not in result.stderr
    assert f"{len(entries)} entries" in result.stderr
    assert output.exists()
    labels = {entry.label for entry in entries}
    assert {"hatch", "hatch:crosshatch", "hatch:fine", "hatch:single"} <= labels
    assert "hatch:default" not in labels
    assert "hatch:hatch:fine" not in labels
    assert ContactSheetEntry("hatch", "hatch:fine", HatchSettings()).label == "hatch:fine"


def test_contact_sheet_passes_tile_scale_to_hatch(
    source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[HatchSettings, dict[str, float]]] = []
    monkeypatch.setattr(
        contact_sheet, "get_pfm", lambda _name: (_capture_hatch(seen), HatchSettings)
    )
    entry = ContactSheetEntry("hatch", None, HatchSettings())
    image = Image.open(source).convert("RGB")

    result = render_contact_sheet(image, [entry], max_resolution=64, dpi=2)

    assert result.errors == {}
    assert len(seen) == 1
    settings, kwargs = seen[0]
    assert isinstance(settings, HatchSettings)
    assert kwargs["pixels_per_mm"] == pytest.approx(64 / TILE_WIDTH_MM)
    assert kwargs["pen_width_mm"] == 0.3
