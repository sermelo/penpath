"""Unit tests for the ``penpath gcode`` command helpers."""

from __future__ import annotations

from penpath.cli.commands.gcode import ProfileValidationError, _estimate_plot_seconds
from penpath.core import MachineProfile

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


def test_profile_validation_error_exits_3() -> None:
    assert ProfileValidationError("bad profile").exit_code == 3
