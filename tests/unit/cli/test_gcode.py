"""Unit tests for the ``penpath gcode`` command helpers."""

from __future__ import annotations

from pathlib import Path

from penpath.cli.commands.gcode import ProfileValidationError, _estimate_plot_seconds, _layer_pen
from penpath.core import MachineProfile, PenStroke

PROFILE = MachineProfile.model_validate(
    {
        "name": "test",
        "bed": {"size_mm": [210.0, 297.0]},
        "feed": {"travel_mm_s": 100.0, "draw_mm_s": 50.0, "z_mm_s": 10.0},
        "pen": {"z_up": 5.0, "z_down": 0.0},
    }
)

TOTAL = {
    "drawing_length_mm": 30.0,
    "pen_up_travel_mm": 15.0,
    "num_lifts": 1,
    "num_short_segments": 0,
    "num_strokes": 2,
}


def test_estimate_plot_seconds_uses_draw_travel_and_z_feeds() -> None:
    # 30/50 draw + 15/100 travel + 5 Z moves over 5 mm at 10 mm/s.
    assert _estimate_plot_seconds(PROFILE, TOTAL) == 0.6 + 0.15 + 2.5


def test_estimate_plot_seconds_uses_travel_feed_and_no_z_moves_when_empty() -> None:
    profile = MachineProfile.model_validate(
        {
            "name": "test",
            "bed": {"size_mm": [210.0, 297.0]},
            "feed": {"travel_mm_s": 100.0, "draw_mm_s": 50.0},
            "pen": {"z_up": 5.0, "z_down": 0.0},
        }
    )
    empty = {
        "drawing_length_mm": 0.0,
        "pen_up_travel_mm": 0.0,
        "num_lifts": 0,
        "num_short_segments": 0,
        "num_strokes": 0,
    }
    assert _estimate_plot_seconds(profile, empty) == 0.0


def test_layer_pen_prefers_inkscape_label(tmp_path: Path) -> None:
    svg = tmp_path / "labelled.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape">'
        '<g inkscape:groupmode="layer" inkscape:label="my_pen"/></svg>',
        encoding="utf-8",
    )
    assert _layer_pen(svg, []) == "my_pen"


def test_layer_pen_falls_back_to_first_stroke_colour(tmp_path: Path) -> None:
    svg = tmp_path / "plain.svg"
    svg.write_text("<svg/>", encoding="utf-8")
    strokes = [
        PenStroke(polyline=[(0.0, 0.0), (1.0, 1.0)], width_mm=0.3, color="#FF0000"),
    ]
    assert _layer_pen(svg, strokes) == "#FF0000"


def test_profile_validation_error_exits_3() -> None:
    assert ProfileValidationError("bad profile").exit_code == 3
