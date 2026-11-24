"""Unit tests for the machine profile schema (D5)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from penpath.core import (
    PROFILE_FILE_VERSION,
    BedProfile,
    FeedProfile,
    GcodeProfile,
    MachineProfile,
    PageProfile,
    PenChangeProfile,
    PenChangeStep,
    PenProfile,
)


def _minimal() -> dict[str, object]:
    return {
        "name": "test_machine",
        "bed": {"size_mm": [210.0, 297.0]},
        "feed": {"travel_mm_s": 100.0, "draw_mm_s": 50.0},
        "pen": {"z_up": 5.0, "z_down": 0.0},
    }


def _full() -> dict[str, object]:
    data = _minimal()
    data |= {
        "description": "Test machine",
        "bed": {
            "size_mm": [220.0, 220.0],
            "pen_offset_mm": [-22.7, -28.6],
            "nozzle_range_mm": [[0.0, 220.0], [0.0, 220.0]],
            "page": {"placement": "reachable_corner", "origin_mm": [1.0, 2.0]},
        },
        "feed": {"travel_mm_s": 100.0, "draw_mm_s": 25.0, "z_mm_s": 10.0},
        "pen": {
            "z_up": 12.5,
            "z_down": 9.0,
            "z_touch": 10.0,
            "z_hover": 10.5,
            "ramp_mm": 1.5,
        },
        "gcode": {"comment_prefix": ";", "start": "G21\nG90", "end": "M2"},
        "pen_change": {
            "mode": "each",
            "steps": [
                {"z": "up", "feed": "z"},
                {"xy": [190.0, 12.0], "feed": "travel"},
                {"raw": "M300 S1000 P300"},
                {"message": "Change to {pen}"},
                {"pause": ""},
            ],
        },
    }
    return data


def test_machine_profile_validates_every_d5_section() -> None:
    """A library user validates a complete profile through the public API."""
    assert PROFILE_FILE_VERSION == 1

    profile = MachineProfile.model_validate(_full())

    assert isinstance(profile.bed, BedProfile)
    assert isinstance(profile.bed.page, PageProfile)
    assert isinstance(profile.feed, FeedProfile)
    assert isinstance(profile.pen, PenProfile)
    assert isinstance(profile.gcode, GcodeProfile)
    assert isinstance(profile.pen_change, PenChangeProfile)
    assert isinstance(profile.pen_change.steps[0], PenChangeStep)
    assert (profile.version, profile.name, profile.description) == (
        1,
        "test_machine",
        "Test machine",
    )
    assert profile.bed.size_mm == (220.0, 220.0)
    assert profile.bed.nozzle_range_mm == ((0.0, 220.0), (0.0, 220.0))
    assert profile.bed.page.placement == "reachable_corner"
    assert profile.feed.effective_z_mm_s == 10.0
    assert profile.pen.ramp_mm == 1.5
    assert profile.gcode.start == "G21\nG90"
    assert profile.pen_change.mode == "each"
    assert len(profile.pen_change.steps) == 5
    assert profile.pen_change.steps[0].z == "up"
    assert profile.pen_change.steps[2].raw == "M300 S1000 P300"


def test_optional_fields_default_without_machine_values() -> None:
    """Sections omitted by a minimal profile get machine-neutral defaults."""
    profile = MachineProfile.model_validate(_minimal())

    assert profile.version == 1
    assert profile.description == ""
    assert profile.bed.pen_offset_mm == (0.0, 0.0)
    assert profile.bed.nozzle_range_mm is None
    assert profile.bed.margin_mm == 0.0
    assert profile.bed.page.placement == "fixed"
    assert profile.bed.page.origin_mm == (0.0, 0.0)
    assert profile.bed.invert_y is True
    assert profile.feed.z_mm_s is None
    assert profile.feed.effective_z_mm_s == profile.feed.travel_mm_s
    assert profile.pen.z_touch is None
    assert profile.pen.z_hover is None
    assert profile.pen.ramp_mm is None
    assert profile.pen.touch_xy_mm is None
    assert profile.pen.up_code is None
    assert profile.pen.down_code is None
    assert profile.gcode.comment_prefix == ";"
    assert profile.gcode.start == ""
    assert profile.gcode.end == ""
    assert profile.gcode.layer_start == ""
    assert profile.gcode.layer_end == ""
    assert profile.pen_change.mode == "none"
    assert profile.pen_change.steps == []


@pytest.mark.parametrize(
    ("path", "typo"),
    [
        ((), "feeed"),
        (("bed",), "size_mm_typo"),
        (("pen",), "zupp"),
        (("gcode",), "star"),
    ],
)
def test_unknown_key_is_rejected_and_named(path: tuple[str, ...], typo: str) -> None:
    data = _full()
    section = data
    for part in path:
        section = section[part]
    section[typo] = 1

    with pytest.raises(ValidationError) as info:
        MachineProfile.model_validate(data)

    assert "extra_forbidden" in str(info.value)
    assert typo in str(info.value)


@pytest.mark.parametrize(
    ("key", "height"),
    [
        ("z_down", 12.5),
        ("z_touch", 8.9),
        ("z_touch", 12.6),
        ("z_hover", 8.9),
        ("z_hover", 12.6),
    ],
)
def test_pen_heights_must_be_ordered(key: str, height: float) -> None:
    data = _full()
    data["pen"][key] = height

    with pytest.raises(ValidationError) as info:
        MachineProfile.model_validate(data)

    assert f"pen.{key}" in str(info.value)


@pytest.mark.parametrize("missing", ["z_touch", "z_hover", "both"])
def test_ramp_requires_both_touch_and_hover(missing: str) -> None:
    data = _full()
    for name in ("z_touch", "z_hover"):
        if missing in (name, "both"):
            del data["pen"][name]

    with pytest.raises(ValidationError) as info:
        MachineProfile.model_validate(data)

    assert "pen.ramp_mm" in str(info.value)


@pytest.mark.parametrize("axis", [0, 1])
def test_nozzle_range_axes_must_increase(axis: int) -> None:
    data = _full()
    data["bed"]["nozzle_range_mm"][axis] = [10.0, 10.0]

    with pytest.raises(ValidationError) as info:
        MachineProfile.model_validate(data)

    message = str(info.value)
    assert "bed.nozzle_range_mm" in message
    assert ("X" if axis == 0 else "Y") in message


@pytest.mark.parametrize(
    "step",
    [
        {"feed": "travel"},
        {"z": "up", "raw": "M300 S1000 P300"},
        {"message": "Change", "pause": "Press knob"},
    ],
)
def test_pen_change_step_needs_exactly_one_action(step: dict[str, object]) -> None:
    data = _full()
    data["pen_change"]["steps"] = [step]

    with pytest.raises(ValidationError) as info:
        MachineProfile.model_validate(data)

    assert "pen_change.steps" in str(info.value)
