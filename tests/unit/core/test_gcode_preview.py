"""Unit tests for the G-code preview interpreter."""

from __future__ import annotations

import pytest

from penpath.core import (
    BedProfile,
    FeedProfile,
    GcodeHeader,
    GcodeLayer,
    GcodePreviewError,
    MachineProfile,
    PageProfile,
    PenProfile,
    build_gcode,
    gcode_to_strokes,
    load_profile,
    page_origin_mm,
    parse_gcode_header,
)

HEADER = "; penpath gcode profile=generic z_up=12.500 z_touch=10.000 z_down=9.000\n"


def _reachable_corner_profile() -> MachineProfile:
    return MachineProfile(
        name="test_reachable",
        bed=BedProfile(
            size_mm=(210.0, 297.0),
            pen_offset_mm=(5.0, 7.0),
            nozzle_range_mm=((10.0, 200.0), (20.0, 280.0)),
            page=PageProfile(placement="reachable_corner"),
            invert_y=True,
        ),
        feed=FeedProfile(travel_mm_s=100.0, draw_mm_s=50.0),
        pen=PenProfile(z_up=5.0, z_down=0.0),
    )


def test_parse_gcode_header_reads_profile_and_z_values() -> None:
    assert parse_gcode_header(HEADER + "G21\n") == GcodeHeader(
        profile="generic", z_up=12.5, z_touch=10.0, z_down=9.0
    )
    assert parse_gcode_header("G21\nG0 Z5.000\n") == GcodeHeader()


def test_parse_gcode_header_reads_page_size() -> None:
    header = parse_gcode_header(
        "; penpath gcode profile=generic page=190.000x190.000 z_up=5.000 z_down=0.000\n"
    )
    assert header.page == (190.0, 190.0)
    assert parse_gcode_header("; penpath gcode profile=generic page=bad z_up=5.000\n").page is None


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


def test_build_gcode_header_carries_source_page_size() -> None:
    text = build_gcode(
        [GcodeLayer("black", [[(10.0, 10.0), (20.0, 10.0)]])],
        load_profile("generic"),
        (190.0, 190.0),
    )

    assert text.startswith("; penpath gcode profile=generic page=190.000x190.000 ")


def test_gcode_to_strokes_round_trips_page_smaller_than_bed() -> None:
    page = (190.0, 190.0)
    points = [(10.0, 10.0), (20.0, 10.0), (20.0, 20.0)]
    text = build_gcode([GcodeLayer("black", [points])], load_profile("generic"), page)

    strokes = gcode_to_strokes(text, (210.0, 297.0), load_profile("generic"))

    assert len(strokes) == 1
    assert strokes[0].polyline == points


def test_page_origin_mm_uses_drawable_corner_for_reachable_corner() -> None:
    assert page_origin_mm(_reachable_corner_profile(), (190.0, 190.0)) == (15.0, 27.0)


def test_gcode_to_strokes_round_trips_reachable_corner() -> None:
    profile = _reachable_corner_profile()
    page = (190.0, 190.0)
    points = [(10.0, 10.0), (20.0, 10.0), (20.0, 20.0)]
    text = build_gcode([GcodeLayer("black", [points])], profile, page)

    strokes = gcode_to_strokes(text, (210.0, 297.0), profile)

    assert len(strokes) == 1
    assert strokes[0].polyline == points


def _ramped_profile() -> MachineProfile:
    return MachineProfile(
        name="ramped",
        bed=BedProfile(
            size_mm=(100.0, 100.0),
            pen_offset_mm=(-2.0, -3.0),
            nozzle_range_mm=((0.0, 100.0), (0.0, 100.0)),
        ),
        feed=FeedProfile(travel_mm_s=60.0, draw_mm_s=30.0, z_mm_s=10.0),
        pen=PenProfile(z_up=5.0, z_down=1.0, z_touch=2.0, z_hover=3.0, ramp_mm=2.0),
    )


def test_gcode_to_strokes_ignores_the_ramp_lead_in_and_lead_out() -> None:
    profile = _ramped_profile()
    points = [(10.0, 10.0), (20.0, 10.0), (20.0, 20.0)]
    text = build_gcode([GcodeLayer("black", [points])], profile, (100.0, 100.0))

    strokes = gcode_to_strokes(text, (100.0, 100.0), profile)

    assert len(strokes) == 1
    assert strokes[0].polyline == [
        (10.0, 10.0),
        (12.0, 10.0),
        (20.0, 10.0),
        (20.0, 18.0),
        (20.0, 20.0),
    ]
    assert strokes[0].polyline[0] == points[0]
    assert strokes[0].polyline[-1] == points[-1]


def test_gcode_to_strokes_clips_z_interpolated_moves_at_touch_height() -> None:
    text = (
        HEADER
        + "G0 Z12.500\nG0 X10.000 Y90.000\n"
        + "G1 X20.000 Y90.000 Z9.000\nG1 X30.000 Y90.000 Z9.000\n"
        + "G1 X40.000 Y90.000 Z12.500\nG0 Z12.500\n"
    )

    strokes = gcode_to_strokes(text, (100.0, 100.0))

    assert len(strokes) == 1
    assert strokes[0].polyline[0] == pytest.approx((17.1428571429, 10.0))
    assert strokes[0].polyline[1:3] == [(20.0, 10.0), (30.0, 10.0)]
    assert strokes[0].polyline[-1] == pytest.approx((32.8571428571, 10.0))
