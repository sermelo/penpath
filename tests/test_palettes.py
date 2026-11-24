"""Tests for the built-in Stabilo 88 palette."""

from __future__ import annotations

import pytest

from penpath.presets import get_palette, list_palettes
from penpath.presets.palettes import STABILO_88_COLORS, STABILO_88_WIDTH_MM

EXPECTED_PENS = [
    ("stabilo_88_yellow", "#F7E300"),
    ("stabilo_88_cyan", "#00B5B0"),
    ("stabilo_88_light_blue", "#8CCFE8"),
    ("stabilo_88_blue", "#1B4C9E"),
    ("stabilo_88_light_green", "#A9D18E"),
    ("stabilo_88_purple", "#6C3B9E"),
    ("stabilo_88_pink", "#F2A0BE"),
    ("stabilo_88_brown", "#7A4B23"),
    ("stabilo_88_orange", "#F4741F"),
    ("stabilo_88_black", "#000000"),
    ("stabilo_88_red", "#E4002B"),
    ("stabilo_88_green", "#00963E"),
]


def test_list_palettes_includes_stabilo_88() -> None:
    assert "stabilo_88" in list_palettes()


def test_get_palette_unknown_name_raises() -> None:
    with pytest.raises(ValueError, match="Unknown palette"):
        get_palette("no_such_palette")


def test_stabilo_88_has_twelve_pens_in_drawing_order() -> None:
    palette = get_palette("stabilo_88")
    assert palette.name == "stabilo_88"
    assert len(palette.pens) == 12
    assert [(pen.name, pen.color) for pen in palette.pens] == EXPECTED_PENS
    assert all(pen.width_mm == STABILO_88_WIDTH_MM == 0.4 for pen in palette.pens)


def test_stabilo_88_colors_table_is_the_single_source() -> None:
    assert list(STABILO_88_COLORS.items()) == [
        (name.removeprefix("stabilo_88_"), color) for name, color in EXPECTED_PENS
    ]
