"""Unit tests for ``penpath info`` output helpers."""

from __future__ import annotations

from penpath.cli.commands.info import _format_margin_mm


def test_format_margin_mm_uniform_value_has_no_decimals() -> None:
    assert _format_margin_mm(10.0) == "10"


def test_format_margin_mm_per_side_uses_top_right_bottom_left_order() -> None:
    assert _format_margin_mm((10.0, 5.0, 10.0, 5.0)) == "10/5/10/5"
    assert _format_margin_mm([1.0, 2.0, 3.0, 4.0]) == "1/2/3/4"


def test_format_margin_mm_zero_is_visible() -> None:
    assert _format_margin_mm(0.0) == "0"
