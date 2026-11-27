"""Tests for the core contact-sheet renderer and preset catalog."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from penpath.core import contact_sheet
from penpath.core.contact_sheet import (
    TILE_WIDTH_MM,
    ContactSheetEntry,
    render_contact_sheet,
)
from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings
from penpath.core.drawing.registry import get_registry, list_pfms
from penpath.presets import list_sheet_entries
from penpath.presets.pfms import list_presets_for_pfm

_BUILTIN_PFMS = {"contour", "sketch_lines", "sketch_squares", "stipple"}


@pytest.fixture(autouse=True)
def _builtin_pfm_registry() -> Iterator[None]:
    """Ignore PFMs other tests register globally, then restore them afterwards."""
    registry = get_registry()
    original = dict(registry._pfms)
    for name in list(registry._pfms):
        if name not in _BUILTIN_PFMS:
            del registry._pfms[name]
    yield
    registry._pfms.clear()
    registry._pfms.update(original)


def _dark_light_image() -> Image.Image:
    """Small image with a solid square and a filled circle."""
    image = Image.new("RGB", (80, 40), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((5, 5, 35, 35), fill="black")
    draw.ellipse((45, 5, 75, 35), fill="black")
    return image


def _tile_height_px(image: Image.Image, max_resolution: int, dpi: float) -> int:
    """Expected simulated paper height in pixels for an image's aspect."""
    width, height = image.size
    scale = min(1.0, max_resolution / max(width, height))
    working_width, working_height = round(width * scale), round(height * scale)
    return round(TILE_WIDTH_MM * working_height / working_width * dpi)


def _dark_pixels_in_tile(
    sheet: Image.Image,
    index: int,
    columns: int,
    tile_height_px: int,
) -> int:
    """Count ink-coloured pixels inside one paper area, excluding caption and border."""
    cell_w, cell_h = 122, 26 + tile_height_px
    x = 8 + (index % columns) * (cell_w + 8)
    y = 8 + (index // columns) * (cell_h + 8)
    paper = sheet.crop((x + 1, y + 25, x + 121, y + 25 + tile_height_px))
    return int(np.count_nonzero(np.asarray(paper.convert("L")) < 128))


def test_list_sheet_entries_covers_every_pfm_and_preset() -> None:
    entries = list_sheet_entries()
    assert len(entries) == 19
    assert {entry.pfm for entry in entries} == set(list_pfms())

    assert "default" in list_presets_for_pfm("sketch_lines")
    for pfm in list_pfms():
        expected = {pfm}
        expected.update(
            f"{pfm}:{preset}" for preset in list_presets_for_pfm(pfm) if preset != "default"
        )
        assert {entry.label for entry in entries if entry.pfm == pfm} == expected
    assert all(entry.preset != "default" for entry in entries)


def test_list_sheet_entries_labels_and_fresh_settings() -> None:
    first, second = list_sheet_entries(), list_sheet_entries()
    assert [entry.label for entry in first] == [entry.label for entry in second]
    assert len({entry.label for entry in first}) == len(first)

    assert ContactSheetEntry("sketch_lines", None, SketchLinesSettings()).label == "sketch_lines"
    assert (
        ContactSheetEntry("sketch_lines", "fine", SketchLinesSettings()).label
        == "sketch_lines:fine"
    )

    sketch = next(entry for entry in first if entry.label == "sketch_lines")
    other = next(entry for entry in second if entry.label == "sketch_lines")
    assert sketch.settings is not other.settings
    sketch.settings.line_density = 5.0
    assert other.settings.line_density != 5.0


def test_render_contact_sheet_dimensions_follow_columns() -> None:
    image = Image.new("RGB", (40, 20), "white")
    entries = list_sheet_entries()[:3]

    result = render_contact_sheet(image, entries, max_resolution=64, dpi=2, columns=2)

    assert result.errors == {}
    assert result.image.mode == "RGB"
    assert result.image.size == (268, 196)


def test_render_contact_sheet_every_tile_has_ink() -> None:
    image = _dark_light_image()
    entries = [entry for entry in list_sheet_entries() if entry.preset is None]
    assert len(entries) == len(list_pfms())

    result = render_contact_sheet(image, entries, max_resolution=64, dpi=2, columns=2)

    assert result.errors == {}
    tile_height = _tile_height_px(image, 64, 2)
    for index, entry in enumerate(sorted(entries, key=lambda e: (e.pfm, e.preset or ""))):
        ink = _dark_pixels_in_tile(result.image, index, 2, tile_height)
        assert ink > 0, f"{entry.label} produced no ink"


def test_render_contact_sheet_unknown_pfm_error_tile_and_other_tiles_render() -> None:
    image = _dark_light_image()
    good = next(entry for entry in list_sheet_entries() if entry.pfm == "contour")
    bad_z = ContactSheetEntry("z_missing", None, SketchLinesSettings())
    bad_a = ContactSheetEntry("a_missing", "fine", SketchLinesSettings())

    result = render_contact_sheet(image, [bad_z, good, bad_a], max_resolution=64, dpi=2, columns=3)

    assert list(result.errors) == ["a_missing:fine", "z_missing"]
    assert all("KeyError" in message for message in result.errors.values())
    tile_height = _tile_height_px(image, 64, 2)
    assert _dark_pixels_in_tile(result.image, 1, 3, tile_height) > 0
    assert _dark_pixels_in_tile(result.image, 2, 3, tile_height) > 0
    assert _dark_pixels_in_tile(result.image, 0, 3, tile_height) > 0


def test_render_contact_sheet_passes_deep_copy_to_pfm(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[SketchLinesSettings] = []

    def fake_pfm(_image: Image.Image, settings: SketchLinesSettings) -> list:
        seen.append(settings)
        settings.angle_range = (0.0, 10.0)
        return []

    monkeypatch.setattr(contact_sheet, "get_pfm", lambda _name: (fake_pfm, SketchLinesSettings))
    settings = SketchLinesSettings()
    result = render_contact_sheet(
        _dark_light_image(),
        [ContactSheetEntry("fake", None, settings)],
        max_resolution=64,
        dpi=2,
    )

    assert result.errors == {}
    assert seen[0] is not settings
    assert settings.angle_range == (-72.0, -52.0)


@pytest.mark.parametrize(
    ("invalid", "message"),
    [
        ({"max_resolution": 0}, "max_resolution must be positive"),
        ({"max_resolution": -1}, "max_resolution must be positive"),
        ({"dpi": 0}, "dpi must be positive"),
        ({"columns": 0}, "columns must be positive"),
        ({"entries": []}, "entries must not be empty"),
    ],
)
def test_render_contact_sheet_rejects_invalid_inputs(invalid: dict, message: str) -> None:
    image = _dark_light_image()
    entry = ContactSheetEntry("contour", None, SketchLinesSettings())
    kwargs = {"entries": [entry], **invalid}

    with pytest.raises(ValueError, match=message):
        render_contact_sheet(image, **kwargs)


def test_render_contact_sheet_from_catalog_on_reference_image() -> None:
    image = Image.open(Path("tests/fixtures/images/reference/gradient.png")).convert("RGB")
    entries = list_sheet_entries()[:6]

    result = render_contact_sheet(image, entries, max_resolution=64, dpi=2, columns=3)

    assert result.errors == {}
    assert result.image.size == (398, 238)
    tile_height = _tile_height_px(image, 64, 2)
    for index in range(len(entries)):
        assert _dark_pixels_in_tile(result.image, index, 3, tile_height) > 0
