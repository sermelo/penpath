"""Unit tests for the built-in Aquila profile against sergio's reference script.

Source: sermelo/penpath, branch aquila-gcode-reference,
``reference/aquila_gcode/aquila_plot.py``. The numbers and verbatim blocks below
are the reference constants and ``Plot.start``/``Plot.pen``/``Plot.end`` bodies;
they live in the profile, never in penpath's code. The 10 mm safety margin is
penpath's own addition.
"""

from __future__ import annotations

import re

import pytest

from penpath.core import (
    FIT_TOLERANCE_MM,
    GcodeLayer,
    PointOutsideBedError,
    build_gcode,
    fit_layers_to_drawable,
    lead_in_mm,
    load_profile,
    page_origin_mm,
    usable_area,
)

PEN = "stabilo_88_black"


def _gcode_lines() -> list[str]:
    """Emit one short stroke through the real built-in profile."""
    layer = GcodeLayer(PEN, [[(10.0, 10.0), (40.0, 10.0)]])
    return build_gcode([layer], load_profile("aquila"), (170.0, 170.0)).splitlines()


def test_aquila_profile_numbers_match_reference() -> None:
    """Machine values come from the reference, plus penpath's safety margin."""
    profile = load_profile("aquila")
    assert profile.name == "aquila"
    assert profile.bed.size_mm == (220.0, 220.0)
    assert profile.bed.pen_offset_mm == (-22.7, -28.6)
    assert profile.bed.nozzle_range_mm == ((0.0, 220.0), (0.0, 220.0))
    assert profile.bed.margin_mm == 10.0
    assert profile.bed.margins_mm == (10.0, 10.0, 10.0, 10.0)
    assert usable_area(profile) == ((10.0, 10.0), (187.3, 181.4))
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
    assert page_origin_mm(profile, (170.0, 170.0)) == pytest.approx((17.3, 10.0))
    assert page_origin_mm(profile, (130.0, 73.0)) == pytest.approx((57.3, 10.0))
    assert profile.pen_change.mode == "each"


def test_aquila_start_block_matches_reference() -> None:
    """The header and start sequence are the reference's Plot.start body."""
    assert _gcode_lines()[:19] == [
        "; penpath gcode profile=aquila page=170.000x170.000 "
        "place=front-right page_origin=17.300x10.000 "
        "usable_x=10.000..187.300 usable_y=10.000..181.400 "
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
        "M0 Pen 1: stabilo_88_black. Fit pen, touch paper, tighten clamp, press knob",
        "M300 S1500 P200",
        "M117 Plotting stabilo_88_black",
        "G1 Z12.500 F600",
        "; layer 1/1 pen=stabilo_88_black",
    ]


def test_aquila_travel_and_z_moves_carry_reference_feeds() -> None:
    """Plan travels run at F6000 and Z lifts at F600, as the reference emits them."""
    plan_moves = [line for line in _gcode_lines() if line.startswith("G0 ")]
    assert plan_moves
    assert all(" F" in line for line in plan_moves)
    assert [line for line in plan_moves if line.startswith("G0 X")] == ["G0 X49.250 Y198.600 F6000"]
    assert [line for line in plan_moves if line.startswith("G0 Z")] == [
        "G0 Z12.500 F600",
        "G0 Z10.500 F600",
        "G0 Z12.500 F600",
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
    text = build_gcode(layers, load_profile("aquila"), (170.0, 170.0))
    commands = {line.split(" ", 1)[0] for line in text.splitlines()}

    assert text.count("; pen change") == 3
    assert sum(line.startswith("M0") for line in text.splitlines()) == 3
    assert "M25" not in commands


def _drawing_nozzle_points(gcode: str) -> list[tuple[float, float]]:
    """Return nozzle XY moves of the strokes only, excluding the pen-change block."""
    lines = gcode.splitlines()
    start = next(index for index, line in enumerate(lines) if line.startswith("; layer "))
    end = next(index for index, line in enumerate(lines[start:], start) if "Z80.000" in line)
    points: list[tuple[float, float]] = []
    for line in lines[start:end]:
        if not line.startswith(("G0 ", "G1 ")) or "X" not in line:
            continue
        values = {key: float(value) for key, value in re.findall(r"([XY])(-?\d+\.\d+)", line)}
        points.append((values["X"], values["Y"]))
    return points


def test_aquila_fit_keeps_every_drawn_point_inside_the_usable_area() -> None:
    """Fitting leaves the ramp lead-in/out and every drawn point reachable."""
    profile = load_profile("aquila")
    layers = [GcodeLayer(PEN, [[(170.0, 170.0), (170.0, 10.0)]])]
    fitted = fit_layers_to_drawable(layers, profile, (170.0, 170.0))
    assert fitted.changed

    produced = build_gcode(fitted.layers, profile, (170.0, 170.0))
    points = _drawing_nozzle_points(produced)
    assert len(points) >= 4
    (x_lo, y_lo), (x_hi, y_hi) = usable_area(profile)
    offset_x, offset_y = profile.bed.pen_offset_mm
    for nozzle_x, nozzle_y in points:
        pen_x, pen_y = nozzle_x + offset_x, nozzle_y + offset_y
        assert x_lo - FIT_TOLERANCE_MM <= pen_x <= x_hi + FIT_TOLERANCE_MM
        assert y_lo - FIT_TOLERANCE_MM <= pen_y <= y_hi + FIT_TOLERANCE_MM


def test_aquila_direct_build_rejects_a_stroke_on_the_usable_edge() -> None:
    """A stroke on the edge needs fitting first: its ramp lead-in leaves the area."""
    with pytest.raises(PointOutsideBedError, match="outside the usable area"):
        build_gcode(
            [GcodeLayer(PEN, [[(170.0, 170.0), (170.0, 100.0)]])],
            load_profile("aquila"),
            (170.0, 170.0),
        )
