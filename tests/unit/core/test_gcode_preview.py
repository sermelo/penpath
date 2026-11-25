"""Unit tests for the G-code preview interpreter."""

from __future__ import annotations

import pytest

from penpath.core import (
    GcodeHeader,
    GcodePreviewError,
    gcode_to_strokes,
    load_profile,
    parse_gcode_header,
)

HEADER = "; penpath gcode profile=generic z_up=12.500 z_touch=10.000 z_down=9.000\n"


def test_parse_gcode_header_reads_profile_and_z_values() -> None:
    assert parse_gcode_header(HEADER + "G21\n") == GcodeHeader("generic", 12.5, 10.0, 9.0)
    assert parse_gcode_header("G21\nG0 Z5.000\n") == GcodeHeader()


def test_gcode_to_strokes_draws_at_or_below_touch_z() -> None:
    text = (
        HEADER
        + "G0 Z10.500\nG0 X10.000 Y90.000\nG1 X20.000 Y90.000\n"
        + "G0 Z10.000\nG1 X30.000 Y90.000\nG0 Z12.500\n"
    )

    strokes = gcode_to_strokes(text, (100.0, 100.0))

    assert len(strokes) == 1
    assert strokes[0].polyline == [(20.0, 10.0), (30.0, 10.0)]


def test_gcode_to_strokes_without_header_uses_lowest_z_as_down() -> None:
    text = "G0 Z5.000\nG0 X10.000 Y90.000\nG0 Z0.000\nG1 X20.000 Y90.000\nG0 Z5.000\n"

    strokes = gcode_to_strokes(text, (100.0, 100.0))

    assert len(strokes) == 1
    assert strokes[0].polyline == [(10.0, 10.0), (20.0, 10.0)]


def test_gcode_to_strokes_colours_layers_and_defaults_unknown_pen() -> None:
    text = (
        HEADER
        + "; layer 1 pen=yellow pen\nG0 Z9.000\nG0 X10.000 Y90.000\n"
        + "G1 X20.000 Y90.000\nG0 Z12.500\n"
        + "; layer 2 pen=mystery\nG0 X30.000 Y90.000\nG0 Z9.000\n"
        + "G1 X40.000 Y90.000\nG0 Z12.500\n"
    )

    strokes = gcode_to_strokes(text, (100.0, 100.0), pen_styles={"yellow pen": ("#FFFF00", 0.4)})

    assert [stroke.color for stroke in strokes] == ["#FFFF00", "#000000"]
    assert [stroke.width_mm for stroke in strokes] == [0.4, 0.3]


def test_gcode_to_strokes_reverses_generic_profile_transform() -> None:
    text = (
        "; penpath gcode profile=generic z_up=5.000 z_down=0.000\n"
        "G0 Z5.000\nG0 X10.000 Y287.000\nG0 Z0.000\n"
        "G1 X20.000 Y287.000 F3000\nG1 X20.000 Y277.000\nG0 Z5.000\n"
    )

    strokes = gcode_to_strokes(text, (210.0, 297.0), load_profile("generic"))

    assert len(strokes) == 1
    assert strokes[0].polyline == [(10.0, 10.0), (20.0, 10.0), (20.0, 20.0)]


def test_gcode_to_strokes_pen_filter_selects_one_layer() -> None:
    text = (
        HEADER
        + "; layer 1 pen=red\nG0 Z9.000\nG0 X10.000 Y90.000\n"
        + "G1 X20.000 Y90.000\nG0 Z12.500\n"
        + "; layer 2 pen=blue\nG0 X30.000 Y90.000\nG0 Z9.000\n"
        + "G1 X40.000 Y90.000\nG0 Z12.500\n"
    )

    strokes = gcode_to_strokes(text, (100.0, 100.0), pen_filter="blue")

    assert len(strokes) == 1
    assert strokes[0].polyline == [(30.0, 10.0), (40.0, 10.0)]


def test_gcode_to_strokes_rejects_arcs_with_actionable_error() -> None:
    with pytest.raises(GcodePreviewError, match=r"arcs .* not supported"):
        gcode_to_strokes(HEADER + "G2 X10.000 Y10.000\n", (100.0, 100.0))
