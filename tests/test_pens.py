"""Tests for penpath.presets.pens module."""

import pytest

from penpath.cli.config import PenConfig
from penpath.presets.pens import (
    DEFAULT_PEN,
    PEN_PRESETS,
    get_pen,
    list_pens,
)


class TestPensPresets:
    def test_default_pen_exists(self) -> None:
        assert DEFAULT_PEN in PEN_PRESETS

    def test_pen_presets_structure(self) -> None:
        for name, pen in PEN_PRESETS.items():
            assert isinstance(pen, PenConfig)
            assert pen.name == name
            assert pen.width > 0
            assert pen.color
            assert 0 < pen.opacity <= 1.0

    def test_expected_pens_present(self) -> None:
        expected = {
            "fine",
            "medium",
            "bold",
            "extra_fine",
            "brush",
            "red_fine",
            "blue_fine",
            "green_fine",
        }
        assert expected.issubset(set(PEN_PRESETS.keys()))


class TestGetPen:
    def test_get_existing_pen(self) -> None:
        pen = get_pen("fine")
        assert pen.name == "fine"
        assert pen.width == 0.3

    def test_get_colored_pen(self) -> None:
        pen = get_pen("red_fine")
        assert pen.name == "red_fine"
        assert pen.color == "red"

    def test_get_unknown_pen_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown pen preset: unknown"):
            get_pen("unknown")


class TestListPens:
    def test_list_pens_sorted(self) -> None:
        pens = list_pens()
        assert pens == sorted(pens)
        assert "fine" in pens
        assert "medium" in pens
