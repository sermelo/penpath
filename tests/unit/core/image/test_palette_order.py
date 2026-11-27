"""Tests for drawing-order sorting of palette pens."""

from __future__ import annotations

import pytest

from penpath.core import order_pens_for_drawing
from penpath.core.models import Pen
from penpath.presets.palettes import get_palette


def _pen(name: str, color: str) -> Pen:
    return Pen(name=name, width_mm=0.4, color=color)


def test_order_pens_for_drawing_sorts_unsorted_pens_light_to_dark() -> None:
    pens = [
        _pen("blue", "#0000FF"),
        _pen("yellow", "#FFFF00"),
        _pen("red", "#FF0000"),
        _pen("white", "#FFFFFF"),
    ]
    assert [pen.name for pen in order_pens_for_drawing(pens)] == [
        "white",
        "yellow",
        "red",
        "blue",
    ]
    assert [pen.name for pen in pens] == ["blue", "yellow", "red", "white"]


def test_order_pens_for_drawing_keeps_a_supplied_black_pen_last() -> None:
    pens = [_pen("black", "#000000"), _pen("white", "#FFFFFF"), _pen("red", "#FF0000")]
    assert [pen.name for pen in order_pens_for_drawing(pens)] == ["white", "red", "black"]


def test_order_pens_for_drawing_treats_near_black_as_black() -> None:
    pens = [_pen("near_black", "#202020"), _pen("dark", "#606060"), _pen("light", "#E0E0E0")]
    assert [pen.name for pen in order_pens_for_drawing(pens)] == ["light", "dark", "near_black"]


def test_order_pens_for_drawing_equal_luminance_keeps_input_order() -> None:
    pens = [
        _pen("first", "#808080"),
        _pen("light", "#FFFFFF"),
        _pen("second", "gray"),
        _pen("dark", "#000000"),
    ]
    assert [pen.name for pen in order_pens_for_drawing(pens)] == [
        "light",
        "first",
        "second",
        "dark",
    ]


def test_order_pens_for_drawing_invalid_colour_raises() -> None:
    pens = [_pen("white", "#FFFFFF"), _pen("bad", "notacolour")]
    with pytest.raises(ValueError, match="Cannot parse pen colour 'notacolour'"):
        order_pens_for_drawing(pens)


def test_order_pens_for_drawing_stabilo_palette_is_light_to_dark_with_black_last() -> None:
    pens = list(get_palette("stabilo_88").pens)
    ordered = order_pens_for_drawing(pens)
    assert ordered[-1].name == "stabilo_88_black"
    assert [pen.name for pen in ordered] != [pen.name for pen in pens]
    assert sorted(pen.name for pen in ordered) == sorted(pen.name for pen in pens)
