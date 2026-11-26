"""Unit tests for pen resolution in the convert command."""

from __future__ import annotations

import click
import pytest

from penpath.cli.commands.convert import _resolve_pen
from penpath.cli.config import Config, PenConfig

PEN_TYPES = ("ballpoint", "fineliner", "fountain", "brush", "marker", "rollerball", "gel")


class TestResolvePenInline:
    """The inline form is WIDTH[,COLOR[,TYPE]], validated by the Pen model."""

    def test_bare_width_is_black_rollerball(self) -> None:
        pen = _resolve_pen("0.4", Config())
        assert pen.width_mm == 0.4
        assert pen.color == "#000000"
        assert pen.pen_type == "rollerball"
        assert pen.name == "0.4"

    def test_hex_color(self) -> None:
        pen = _resolve_pen("0.4,#FF6600", Config())
        assert pen.width_mm == 0.4
        assert pen.color == "#FF6600"
        assert pen.pen_type == "rollerball"

    def test_named_color(self) -> None:
        pen = _resolve_pen("0.5,red", Config())
        assert pen.color == "red"
        assert pen.width_mm == 0.5

    @pytest.mark.parametrize("pen_type", PEN_TYPES)
    def test_every_valid_type_is_accepted(self, pen_type: str) -> None:
        pen = _resolve_pen(f"0.4,#000000,{pen_type}", Config())
        assert pen.pen_type == pen_type
        assert pen.name == f"0.4-#000000-{pen_type}"

    @pytest.mark.parametrize(
        ("spec", "field", "accepted"),
        [
            ("wide", "width_mm", "greater than 0"),
            ("0", "width_mm", "greater than 0"),
            ("11", "width_mm", "at most 10"),
            ("0.4,#GGGGGG", "color", "#RRGGBB"),
            (
                "0.4,#000000,bogus",
                "pen_type",
                "fineliner",
            ),
        ],
    )
    def test_invalid_field_names_field_and_accepted_values(
        self, spec: str, field: str, accepted: str
    ) -> None:
        with pytest.raises(click.BadParameter) as excinfo:
            _resolve_pen(spec, Config())
        message = str(excinfo.value.message)
        assert field in message
        assert accepted in message
        assert "Unknown pen" not in message

    def test_too_many_fields_names_the_expected_format(self) -> None:
        with pytest.raises(click.BadParameter, match="WIDTH\\[,COLOR\\[,TYPE\\]\\]"):
            _resolve_pen("0.4,#000000,fine,extra", Config())

    def test_from_config_default(self) -> None:
        config = Config(default_pen="bold")
        assert _resolve_pen(None, config).width_mm == 0.8


class TestResolvePenPresets:
    """Preset lookup stays first, before inline parsing."""

    def test_builtin_preset(self) -> None:
        pen = _resolve_pen("fine", Config())
        assert pen.name == "fine"
        assert pen.width_mm == 0.3
        assert pen.color == "black"
        assert pen.pen_type == "rollerball"

    def test_config_preset_wins_over_builtin_of_the_same_name(self) -> None:
        config = Config(
            pens={"fine": PenConfig(name="fine", width=0.9, color="#010203")},
            default_pen="fine",
        )
        pen = _resolve_pen("fine", config)
        assert pen.width_mm == 0.9
        assert pen.color == "#010203"
