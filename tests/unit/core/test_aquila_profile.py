"""Unit tests for the built-in Aquila profile against sergio's reference script.

Source: sermelo/penpath, branch aquila-gcode-reference,
``reference/aquila_gcode/aquila_plot.py``. The numbers and verbatim blocks below
are the reference constants and ``Plot.start``/``Plot.pen``/``Plot.end`` bodies;
they live in the profile, never in penpath's code.
"""

from __future__ import annotations

from penpath.core import GcodeLayer, build_gcode, lead_in_mm, load_profile, page_origin_mm

PEN = "stabilo_88_black"


def _gcode_lines() -> list[str]:
    """Emit one short stroke through the real built-in profile."""
    layer = GcodeLayer(PEN, [[(10.0, 10.0), (40.0, 10.0)]])
    return build_gcode([layer], load_profile("aquila"), (190.0, 190.0)).splitlines()


def test_aquila_profile_numbers_match_reference() -> None:
    """Every machine value comes from the reference constants."""
    profile = load_profile("aquila")
    assert profile.name == "aquila"
    assert profile.bed.size_mm == (220.0, 220.0)
    assert profile.bed.pen_offset_mm == (-22.7, -28.6)
    assert profile.bed.nozzle_range_mm == ((0.0, 220.0), (0.0, 220.0))
    assert profile.bed.margin_mm == 0.0
    assert profile.bed.page.placement == "reachable_corner"
    assert profile.bed.invert_y is True
    assert (profile.feed.travel_mm_s, profile.feed.draw_mm_s, profile.feed.z_mm_s) == (
        100.0,
        25.0,
        10.0,
    )
    assert profile.pen.z_up == 12.5
    assert profile.pen.z_hover == 10.5
    assert profile.pen.z_touch == 10.0
    assert profile.pen.z_down == 9.0
    assert profile.pen.ramp_mm == 1.5
    assert profile.pen.touch_xy_mm == (190.0, 12.0)
    assert lead_in_mm(profile) == 0.75
    assert page_origin_mm(profile, (190.0, 190.0)) == (197.3 - 190.0, 0.0)
    assert profile.pen_change.mode == "each"


def test_aquila_start_block_matches_reference() -> None:
    """The header and start sequence are the reference's Plot.start body."""
    assert _gcode_lines()[:19] == [
        "; penpath gcode profile=aquila page=190.000x190.000 "
        "z_up=12.500 z_touch=10.000 z_down=9.000",
        "; BEFORE STARTING: paper held down, pen OUT of the clamp. Never home with a pen in.",
        "; touch Z 10.0, pen down Z 9.0, up Z 12.5, offset (-22.7, -28.6)",
        "G21",
        "G90",
        "M104 S0",
        "M140 S0",
        "M107",
        "M84 S0 ; no stepper timeout during the pauses",
        "M201 X500 Y500 Z100",
        "M203 X500 Y500 Z10",
        "M204 P500 T500",
        "M205 X8.00 Y8.00 Z0.40",
        "M300 S1000 P300",
        "M117 Pen OUT? Homing in 10s",
        "G4 S10",
        "G28",
        "M420 S1 Z0 ; saved CR Touch mesh, no fade",
        "G1 Z12.500 F600",
    ]


def test_aquila_pen_change_matches_reference() -> None:
    """The first pen change is the reference's Plot.pen body, with filled names."""
    lines = _gcode_lines()
    assert lines[20:31] == [
        "; ---- pen 1: stabilo_88_black ----",
        "G1 Z12.500 F600",
        "G1 X212.700 Y40.600 F6000",
        "G1 Z10.000 F600",
        "M300 S1000 P300",
        "M117 Pen 1: stabilo_88_black, touch, knob",
        "M0 Pen 1: stabilo_88_black. Touch paper, tighten, press knob",
        "M300 S1500 P200",
        "M117 Plotting stabilo_88_black",
        "G1 Z12.500 F600",
        "; layer 1/1 pen=stabilo_88_black",
    ]


def test_aquila_end_block_parks_and_has_no_m2() -> None:
    """The reference parks the head and disables the steppers; it has no M2."""
    lines = _gcode_lines()
    assert lines[-8:] == [
        "G1 Z80.000 F600",
        "G1 X0.000 Y220.000 F6000 ; head left, bed forward: paper free to take out",
        "M300 S1500 P150",
        "G4 P200",
        "M300 S1500 P150",
        "M84 S120 ; stepper timeout back to the usual 120 s",
        "M84",
        "M117 Plot done",
    ]
    assert "M2" not in {line.split(" ", 1)[0] for line in lines}


def test_aquila_three_pens_pause_three_times_without_m25() -> None:
    """Each used pen gets one pen-change block and one M0; this firmware never uses M25."""
    layers = [
        GcodeLayer(f"pen{index}", [[(10.0, index * 10.0), (40.0, index * 10.0)]])
        for index in (1, 2, 3)
    ]
    text = build_gcode(layers, load_profile("aquila"), (190.0, 190.0))
    commands = {line.split(" ", 1)[0] for line in text.splitlines()}

    assert text.count("; pen change") == 3
    assert sum(line.startswith("M0") for line in text.splitlines()) == 3
    assert "M25" not in commands
