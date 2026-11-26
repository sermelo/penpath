"""Unit tests for the pure G-code emitter (LUC-51 parts 3 and 7, LUC-99, LUC-117)."""

from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path

import pytest

from penpath.core import (
    FIT_TOLERANCE_MM,
    GcodeError,
    GcodeLayer,
    MachineProfile,
    PagePlacement,
    PlacementName,
    PointOutsideBedError,
    build_gcode,
    fit_layers_to_drawable,
    get_svg_paper_size,
    lead_in_mm,
    load_profile,
    page_origin_mm,
    parse_svg_layers,
    place_page,
    usable_area,
)


def _profile_data() -> dict[str, object]:
    return {
        "name": "test_machine",
        "bed": {"size_mm": [100.0, 100.0]},
        "feed": {"travel_mm_s": 60.0, "draw_mm_s": 30.0},
        "pen": {"z_up": 4.0, "z_down": 1.0},
        "gcode": {"start": "G21\nG90", "end": "M2"},
    }


def _profile(**changes: object) -> MachineProfile:
    data = _profile_data()
    for key, value in changes.items():
        data[key] = value
    return MachineProfile.model_validate(data)


def _one_layer(*polylines: tuple[tuple[float, float], ...]) -> list[GcodeLayer]:
    return [GcodeLayer("ink", list(polylines))]


def test_build_gcode_emits_profile_values_and_pen_state_machine() -> None:
    profile = _profile(
        gcode={"start": "G21\nG90", "end": "M2", "layer_start": "; begin", "layer_end": "; done"}
    )
    layers = _one_layer(
        ((1.0, 2.0), (3.0, 2.0), (3.0, 4.0)),
        ((10.0, 10.0), (11.0, 10.0)),
    )

    produced = build_gcode(layers, profile, (50.0, 60.0))

    assert produced == (
        "; penpath gcode profile=test_machine page=50.000x60.000 "
        "place=origin page_origin=0.000x0.000 usable_x=0.000..100.000 usable_y=0.000..100.000 "
        "z_up=4.000 z_down=1.000\n"
        "G21\n"
        "G90\n"
        "; layer 1/1 pen=ink\n"
        "; begin\n"
        "G0 Z4.000 F3600\n"
        "G0 X1.000 Y58.000 F3600\n"
        "G0 Z1.000 F3600\n"
        "G1 X3.000 Y58.000 F1800\n"
        "G1 X3.000 Y56.000\n"
        "G0 Z4.000 F3600\n"
        "G0 X10.000 Y50.000 F3600\n"
        "G0 Z1.000 F3600\n"
        "G1 X11.000 Y50.000 F1800\n"
        "G0 Z4.000 F3600\n"
        "; done\n"
        "M2\n"
    )


def test_build_gcode_plan_moves_always_carry_a_feed() -> None:
    """No plain or ramped plan move is a bare G0 inheriting the last drawing feed."""
    layers = _one_layer(((10.0, 10.0), (20.0, 10.0)), ((30.0, 30.0), (40.0, 30.0)))
    for profile in (_profile(), _ramped_profile()):
        produced = build_gcode(layers, profile, (100.0, 100.0))
        plan_moves = [line for line in produced.splitlines() if line.startswith("G0 ")]
        assert plan_moves
        assert all(" F" in line for line in plan_moves)


def test_build_gcode_keeps_pen_up_between_layers_without_repeating_z() -> None:
    layers = [
        GcodeLayer("first", [((1.0, 1.0), (2.0, 1.0))]),
        GcodeLayer("second", [((3.0, 3.0), (4.0, 3.0))]),
    ]

    produced = build_gcode(layers, _profile(), (10.0, 10.0))

    assert produced.count("G0 Z4.000 F3600") == 3
    assert produced.count("G0 Z1.000 F3600") == 2
    assert "; layer 1/2 pen=first" in produced
    assert "; layer 2/2 pen=second" in produced
    assert produced.index("; layer 2/2") < produced.index("G0 X3.000 Y7.000 F3600")


def test_build_gcode_flips_y_into_pen_space() -> None:
    profile = _profile(bed={"size_mm": [100.0, 100.0], "page": {"origin_mm": [5.0, 7.0]}})

    produced = build_gcode(_one_layer(((1.0, 2.0), (3.0, 4.0))), profile, (50.0, 60.0))

    assert "G0 X6.000 Y65.000 F3600\n" in produced
    assert "G1 X8.000 Y63.000 F1800\n" in produced


def test_build_gcode_can_keep_svg_y_direction() -> None:
    profile = _profile(
        bed={
            "size_mm": [100.0, 100.0],
            "page": {"origin_mm": [5.0, 7.0]},
            "invert_y": False,
        }
    )

    produced = build_gcode(_one_layer(((1.0, 2.0), (3.0, 4.0))), profile, (50.0, 60.0))

    assert "G0 X6.000 Y9.000 F3600\n" in produced
    assert "G1 X8.000 Y11.000 F1800\n" in produced


def test_build_gcode_converts_pen_coordinates_to_nozzle_coordinates() -> None:
    profile = _profile(
        bed={
            "size_mm": [220.0, 220.0],
            "pen_offset_mm": [-22.7, -28.6],
            "nozzle_range_mm": [[0.0, 220.0], [0.0, 220.0]],
        }
    )

    produced = build_gcode(_one_layer(((10.0, 20.0), (12.0, 20.0))), profile, (100.0, 200.0))

    assert "G0 X32.700 Y208.600 F3600\n" in produced
    assert "G1 X34.700 Y208.600 F1800\n" in produced


def test_build_gcode_places_page_at_reachable_corner() -> None:
    profile = _profile(
        bed={
            "size_mm": [220.0, 220.0],
            "pen_offset_mm": [-22.7, -28.6],
            "nozzle_range_mm": [[0.0, 220.0], [0.0, 220.0]],
            "page": {"placement": "reachable_corner"},
        }
    )

    produced = build_gcode(_one_layer(((10.0, 20.0), (12.0, 20.0))), profile, (100.0, 150.0))

    assert "G0 X130.000 Y158.600 F3600\n" in produced
    assert "G1 X132.000 Y158.600 F1800\n" in produced


def test_build_gcode_clips_drawable_area_to_restricted_nozzle_range() -> None:
    profile = _profile(
        bed={
            "size_mm": [200.0, 200.0],
            "pen_offset_mm": [-10.0, -10.0],
            "nozzle_range_mm": [[20.0, 120.0], [20.0, 120.0]],
        }
    )

    produced = build_gcode(_one_layer(((100.0, 100.0), (101.0, 100.0))), profile, (200.0, 200.0))

    assert "G0 X110.000 Y110.000 F3600\n" in produced
    with pytest.raises(PointOutsideBedError) as info:
        build_gcode(_one_layer(((115.0, 100.0), (116.0, 100.0))), profile, (200.0, 200.0))
    assert "X 10.000..110.000, Y 10.000..110.000" in str(info.value)


@pytest.mark.parametrize(
    ("point", "bed", "expected"),
    [
        ((101.0, 10.0), {"size_mm": [100.0, 100.0]}, "x=101.000"),
        ((10.0, -1.0), {"size_mm": [100.0, 100.0]}, "y=101.000"),
        (
            (99.0, 10.0),
            {"size_mm": [100.0, 100.0], "margin_mm": 2.0},
            "X 2.000..98.000",
        ),
    ],
)
def test_build_gcode_outside_drawable_area_names_offending_coordinates(
    point: tuple[float, float],
    bed: dict[str, object],
    expected: str,
) -> None:
    profile = _profile(bed=bed)

    with pytest.raises(PointOutsideBedError) as info:
        build_gcode(_one_layer((point, (point[0] + 1.0, point[1]))), profile, (100.0, 100.0))

    assert expected in str(info.value)
    assert "drawable area" in str(info.value)


def test_build_gcode_fills_placeholders_in_code_blocks() -> None:
    profile = _profile(
        gcode={
            "start": "; start z={z_up} f={feed_draw} zfeed={feed_z}",
            "end": "; end layer={layer_count}",
            "layer_start": "; pen={pen} {layer_index}/{layer_count}",
        }
    )

    produced = build_gcode(_one_layer(((1.0, 1.0), (2.0, 1.0))), profile, (10.0, 10.0))

    assert "; start z=4.000 f=1800 zfeed=3600\n" in produced
    assert "; pen=ink 1/1\n" in produced
    assert produced.endswith("; end layer=1\n")


def test_build_gcode_header_carries_z_touch_for_the_preview() -> None:
    profile = _profile(pen={"z_up": 12.5, "z_down": 9.0, "z_touch": 10.0})

    produced = build_gcode(_one_layer(((1.0, 1.0), (2.0, 1.0))), profile, (20.0, 20.0))

    assert produced.startswith(
        "; penpath gcode profile=test_machine page=20.000x20.000 "
        "place=origin page_origin=0.000x0.000 usable_x=0.000..100.000 usable_y=0.000..100.000 "
        "z_up=12.500 z_touch=10.000 z_down=9.000\n"
    )


def test_build_gcode_skips_layers_without_drawn_points() -> None:
    layers = [
        GcodeLayer("unused", [(), ((1.0, 1.0),)]),
        GcodeLayer("ink", [((1.0, 1.0), (2.0, 1.0))]),
    ]

    produced = build_gcode(layers, _profile(), (10.0, 10.0))

    assert "; layer 1/1 pen=ink\n" in produced
    assert "unused" not in produced


def test_build_gcode_generic_profile_comes_from_the_builtin_yaml(tmp_path: Path) -> None:
    profile = load_profile("generic", profiles_path=tmp_path / "profiles.yaml")

    produced = build_gcode(
        _one_layer(((1.0, 1.0), (2.0, 1.0))),
        profile,
        (210.0, 297.0),
    )

    assert produced.startswith(
        "; penpath gcode profile=generic page=210.000x297.000 "
        "place=origin page_origin=0.000x0.000 usable_x=0.000..210.000 usable_y=0.000..297.000 "
        "z_up=5.000 z_down=0.000\n"
    )
    assert "G21\nG90\nG28\n" in produced
    assert "G0 Z5.000 F6000\nG0 X1.000 Y296.000 F6000\nG0 Z0.000 F6000\n" in produced
    assert "G1 X2.000 Y296.000 F3000\n" in produced
    assert produced.endswith("G0 Z5.000 F6000\nM2\n")


def test_build_gcode_does_not_mutate_profile_or_layers() -> None:
    profile = _profile()
    layers = _one_layer(((1.0, 1.0), (2.0, 1.0)))
    original = deepcopy(profile.model_dump())

    build_gcode(layers, profile, (10.0, 10.0))

    assert profile.model_dump() == original
    assert len(layers[0].polylines) == 1


def test_build_gcode_with_no_drawn_layers_emits_only_wrapper() -> None:
    produced = build_gcode([], _profile(), (10.0, 10.0))

    assert (
        produced == "; penpath gcode profile=test_machine page=10.000x10.000 "
        "place=origin page_origin=0.000x0.000 usable_x=0.000..100.000 usable_y=0.000..100.000 "
        "z_up=4.000 z_down=1.000\nG21\nG90\nM2\n"
    )


def _two_layers() -> list[GcodeLayer]:
    return [
        GcodeLayer("first", [((1.0, 1.0), (2.0, 1.0))]),
        GcodeLayer("second", [((3.0, 3.0), (4.0, 3.0))]),
    ]


def test_pen_change_between_skips_the_first_layer() -> None:
    profile = _profile(
        pen_change={"mode": "between", "steps": [{"message": "{pen}"}, {"pause": ""}]}
    )

    produced = build_gcode(_two_layers(), profile, (10.0, 10.0))

    assert produced.count("; pen change") == 1
    assert produced.count("M0\n") == 1
    assert produced.index("M117 second\n") < produced.index("; layer 2/2 pen=second")
    assert "; layer 1/2 pen=first\nM117" not in produced


def test_pen_change_each_pauses_before_every_used_layer() -> None:
    profile = _profile(pen_change={"mode": "each", "steps": [{"message": "{pen}"}, {"pause": ""}]})

    produced = build_gcode(_two_layers(), profile, (10.0, 10.0))

    assert produced.count("; pen change") == 2
    assert produced.count("M117") == 2
    assert produced.index("M117 first") < produced.index("; layer 1/2")
    assert produced.index("M117 second") < produced.index("; layer 2/2")


def test_pen_change_none_emits_no_block() -> None:
    profile = _profile(pen_change={"mode": "none", "steps": [{"message": "{pen}"}, {"pause": ""}]})

    produced = build_gcode(_two_layers(), profile, (10.0, 10.0))

    assert "; pen change" not in produced
    assert "M117" not in produced


def test_pen_change_skips_layers_without_drawn_points() -> None:
    layers = [
        GcodeLayer("unused", [((1.0, 1.0),)]),
        GcodeLayer("ink", [((2.0, 2.0), (3.0, 2.0))]),
        GcodeLayer("other", [((4.0, 4.0), (5.0, 4.0))]),
    ]
    profile = _profile(
        pen_change={"mode": "between", "steps": [{"message": "{pen}"}, {"pause": ""}]}
    )

    produced = build_gcode(layers, profile, (10.0, 10.0))

    assert "unused" not in produced
    assert produced.count("; pen change") == 1
    assert "; layer 1/2 pen=ink" in produced
    assert "; layer 2/2 pen=other" in produced
    assert "M117 other" in produced


def test_pen_change_and_layer_comments_fill_all_placeholders() -> None:
    profile = _profile(
        gcode={
            "layer_start": "; layer {pen} {pen_index}/{pen_count} {layer_index}/{layer_count}",
        },
        pen_change={
            "mode": "each",
            "steps": [
                {"raw": "; raw {pen} {pen_index}/{pen_count} {layer_index}/{layer_count}"},
                {
                    "message": "take {pen} ({pen_index}/{pen_count}) "
                    "layer {layer_index}/{layer_count}"
                },
                {"pause": "mount {pen}"},
            ],
        },
    )

    produced = build_gcode(_two_layers(), profile, (10.0, 10.0))

    assert "; raw first 1/2 1/2" in produced
    assert "M117 take first (1/2) layer 1/2" in produced
    assert "M0 mount first" in produced
    assert "; layer first 1/2 1/2" in produced
    assert "; raw second 2/2 2/2" in produced
    assert "M117 take second (2/2) layer 2/2" in produced
    assert "; layer second 2/2 2/2" in produced


def test_pen_change_z_and_xy_steps_use_profile_values_and_feeds() -> None:
    profile = _profile(
        bed={
            "size_mm": [100.0, 100.0],
            "pen_offset_mm": [-1.0, -2.0],
        },
        feed={"travel_mm_s": 100.0, "draw_mm_s": 50.0, "z_mm_s": 10.0},
        pen={"z_up": 5.0, "z_down": 0.0, "z_touch": 2.0, "z_hover": 3.0, "touch_xy_mm": [10, 20]},
        pen_change={
            "mode": "each",
            "steps": [
                {"z": "up", "feed": "z"},
                {"z": "touch"},
                {"xy": "touch", "feed": "travel"},
                {"xy": [30, 40]},
                {"z": 7.5},
            ],
        },
    )

    produced = build_gcode(_one_layer(((1.0, 1.0), (2.0, 1.0))), profile, (10.0, 10.0))

    assert "G1 Z5.000 F600\n" in produced
    assert "G0 Z2.000\n" in produced
    assert "G1 X11.000 Y22.000 F6000\n" in produced
    assert "G0 X31.000 Y42.000\n" in produced
    assert "G0 Z7.500\n" in produced


@pytest.mark.parametrize(
    ("steps", "expected"),
    [
        ([{"z": "touch"}], "pen.z_touch"),
        ([{"z": "hover"}], "pen.z_hover"),
        ([{"xy": "touch"}], "pen.touch_xy_mm"),
    ],
)
def test_pen_change_names_missing_profile_value(
    steps: list[dict[str, object]], expected: str
) -> None:
    profile = _profile(pen_change={"mode": "each", "steps": steps})

    with pytest.raises(GcodeError, match=expected):
        build_gcode(_one_layer(((1.0, 1.0), (2.0, 1.0))), profile, (10.0, 10.0))


def _ramped_profile() -> MachineProfile:
    return _profile(
        bed={
            "size_mm": [100.0, 100.0],
            "pen_offset_mm": [-2.0, -3.0],
            "nozzle_range_mm": [[0.0, 100.0], [0.0, 100.0]],
        },
        feed={"travel_mm_s": 60.0, "draw_mm_s": 30.0, "z_mm_s": 10.0},
        pen={"z_up": 5.0, "z_down": 1.0, "z_touch": 2.0, "z_hover": 3.0, "ramp_mm": 2.0},
    )


def test_lead_in_mm_uses_the_d7_formula() -> None:
    profile = _profile(
        pen={"z_up": 12.5, "z_down": 9.0, "z_touch": 10.0, "z_hover": 10.5, "ramp_mm": 1.5}
    )

    assert lead_in_mm(profile) == pytest.approx(0.75)
    assert lead_in_mm(_profile()) is None
    assert lead_in_mm(_profile(pen={"z_up": 5.0, "z_down": 0.0, "ramp_mm": 0.0})) is None
    assert lead_in_mm(_profile(pen={"z_up": 5.0, "z_down": 0.0, "z_touch": 2.0})) is None


def test_build_gcode_ramped_stroke_lands_and_lifts_while_moving() -> None:
    produced = build_gcode(
        _one_layer(((10.0, 10.0), (20.0, 10.0))), _ramped_profile(), (100.0, 100.0)
    )

    assert produced == (
        "; penpath gcode profile=test_machine page=100.000x100.000 "
        "place=origin page_origin=0.000x0.000 usable_x=0.000..98.000 usable_y=0.000..97.000 "
        "z_up=5.000 z_touch=2.000 z_down=1.000\n"
        "G21\nG90\n"
        "; layer 1/1 pen=ink\n"
        "G0 Z5.000 F600\n"
        "G0 X10.000 Y93.000 F3600\n"
        "G0 Z3.000 F600\n"
        "G1 X12.000 Y93.000 Z2.000 F1800\n"
        "G1 X14.000 Y93.000 Z1.000\n"
        "G1 X20.000 Y93.000 Z1.000\n"
        "G1 X22.000 Y93.000 Z2.000\n"
        "G1 X24.000 Y93.000 Z3.000\n"
        "G0 Z5.000 F600\n"
        "M2\n"
    )


def test_build_gcode_ramp_checks_lead_out_against_the_drawable_area() -> None:
    profile = _profile(
        pen={"z_up": 5.0, "z_down": 1.0, "z_touch": 2.0, "z_hover": 3.0, "ramp_mm": 2.0}
    )

    with pytest.raises(PointOutsideBedError) as info:
        build_gcode(_one_layer(((5.0, 5.0), (99.0, 5.0))), profile, (100.0, 100.0))

    assert "x=101.000, y=95.000" in str(info.value)
    assert "drawable area" in str(info.value)


def test_build_gcode_ramp_clamps_a_short_stroke_without_dividing_by_zero() -> None:
    produced = build_gcode(
        _one_layer(((10.0, 10.0), (12.0, 10.0))), _ramped_profile(), (100.0, 100.0)
    )

    assert produced.index("G0 Z5.000 F600") < produced.index("G1 X")
    assert produced.rstrip().endswith("G0 Z5.000 F600\nM2")


def test_build_gcode_ramp_skips_a_stroke_with_no_movement() -> None:
    produced = build_gcode(_one_layer(((1.0, 1.0), (1.0, 1.0))), _ramped_profile(), (10.0, 10.0))

    assert "G1 X" not in produced
    assert "; layer 1/1 pen=ink" in produced


def test_build_gcode_without_ramp_keeps_the_plain_stroke_with_touch_and_hover() -> None:
    profile = _profile(pen={"z_up": 5.0, "z_down": 1.0, "z_touch": 2.0, "z_hover": 3.0})

    produced = build_gcode(_one_layer(((1.0, 1.0), (2.0, 1.0))), profile, (10.0, 10.0))

    assert "G0 Z1.000 F3600\nG1 X2.000 Y9.000 F1800\n" in produced
    assert "Z3.000" not in produced


def test_fit_layers_to_drawable_inside_keeps_the_original_layers() -> None:
    layers = _one_layer(((10.0, 10.0), (20.0, 10.0)))

    fitted = fit_layers_to_drawable(layers, _profile(), (50.0, 50.0))

    assert FIT_TOLERANCE_MM == 0.05
    assert not fitted.changed
    assert fitted.layers is layers
    assert fitted.scale == 1.0
    assert fitted.offset_mm == (0.0, 0.0)
    assert fitted.overshoot_mm == (0.0, 0.0)


def test_fit_layers_to_drawable_uses_the_supplied_tolerance() -> None:
    layers = _one_layer(((99.7, 50.0), (100.3, 50.0)))
    profile = _profile()

    default_fit = fit_layers_to_drawable(layers, profile, (100.0, 100.0))
    relaxed_fit = fit_layers_to_drawable(layers, profile, (100.0, 100.0), tolerance_mm=0.5)

    assert default_fit.changed
    assert default_fit.overshoot_mm == pytest.approx((0.3, 0.0))
    assert not relaxed_fit.changed
    assert relaxed_fit.layers is layers


def test_fit_layers_to_drawable_shifts_a_page_spill_without_scaling() -> None:
    profile = _profile(bed={"size_mm": [190.0, 190.0]})
    layers = _one_layer(((190.13, 10.0), (190.13, 20.0)))

    with pytest.raises(PointOutsideBedError):
        build_gcode(layers, profile, (190.0, 190.0))

    fitted = fit_layers_to_drawable(layers, profile, (190.0, 190.0))

    assert fitted.changed
    assert fitted.scale == 1.0
    assert fitted.overshoot_mm == pytest.approx((0.13, 0.0))
    assert fitted.offset_mm == pytest.approx((-0.13, 0.0))
    assert fitted.layers[0].pen == "ink"
    assert "G0 X190.000 Y180.000 F3600\n" in build_gcode(fitted.layers, profile, (190.0, 190.0))


def test_fit_layers_to_drawable_scales_a_drawing_larger_than_the_bed() -> None:
    layers = [
        GcodeLayer("first", [((0.0, 0.0), (200.0, 0.0))]),
        GcodeLayer("second", [((100.0, 100.0), (100.0, 200.0))]),
    ]

    fitted = fit_layers_to_drawable(layers, _profile(), (200.0, 200.0))

    assert fitted.changed
    assert fitted.scale == pytest.approx(0.5)
    assert fitted.overshoot_mm == pytest.approx((100.0, 100.0))
    assert fitted.offset_mm == (0.0, 0.0)
    assert [layer.pen for layer in fitted.layers] == ["first", "second"]
    assert "G0 X0.000 Y100.000 F3600\n" in build_gcode(fitted.layers, _profile(), (200.0, 200.0))


def test_fit_layers_to_drawable_reserves_the_ramp_lead_at_the_edge() -> None:
    profile = _profile(
        pen={"z_up": 5.0, "z_down": 1.0, "z_touch": 2.0, "z_hover": 3.0, "ramp_mm": 1.0}
    )
    layers = _one_layer(((50.0, 50.0), (100.0, 50.0)))

    assert lead_in_mm(profile) == 1.0
    with pytest.raises(PointOutsideBedError):
        build_gcode(layers, profile, (100.0, 100.0))

    fitted = fit_layers_to_drawable(layers, profile, (100.0, 100.0))

    assert fitted.changed
    assert fitted.scale == 1.0
    assert fitted.overshoot_mm == pytest.approx((1.0, 0.0))
    assert fitted.offset_mm == pytest.approx((-1.0, 0.0))
    produced = build_gcode(fitted.layers, profile, (100.0, 100.0))
    assert "G1 X100.000 Y50.000 Z3.000\n" in produced


def test_fit_layers_to_drawable_reports_an_empty_drawable_area() -> None:
    profile = _profile(
        bed={"size_mm": [10.0, 10.0], "margin_mm": 5.0},
        pen={"z_up": 5.0, "z_down": 1.0, "z_touch": 2.0, "z_hover": 3.0, "ramp_mm": 1.0},
    )

    with pytest.raises(GcodeError, match="no drawable area left"):
        fit_layers_to_drawable(_one_layer(((9.0, 9.0), (10.0, 9.0))), profile, (10.0, 10.0))


@pytest.mark.parametrize(
    ("x", "accepted"),
    [(100.04, True), (100.06, False)],
)
def test_build_gcode_tolerates_float_rounding_at_the_drawable_edge(
    x: float, accepted: bool
) -> None:
    layers = _one_layer(((x, 10.0), (x, 20.0)))

    if accepted:
        assert "G0 X100.040 Y90.000 F3600\n" in build_gcode(layers, _profile(), (100.0, 100.0))
    else:
        with pytest.raises(PointOutsideBedError, match=r"overshoot x=0\.060 mm"):
            build_gcode(layers, _profile(), (100.0, 100.0))


def test_build_gcode_error_names_per_axis_overshoot() -> None:
    layers = _one_layer(((101.0, 105.0), (102.0, 105.0)))

    with pytest.raises(PointOutsideBedError) as info:
        build_gcode(layers, _profile(), (100.0, 100.0))

    message = str(info.value)
    assert "point (x=101.000, y=-5.000) mm" in message
    assert (
        "usable area X 0.000..100.000, Y 0.000..100.000 mm "
        "(drawable area minus a 0.000 mm margin)" in message
    )
    assert "overshoot x=1.000 mm, y=5.000 mm" in message


def test_fit_then_build_gcode_from_aquila_page_with_a_spill(tmp_path: Path) -> None:
    drawing = tmp_path / "card.svg"
    drawing.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
        'width="170mm" height="170mm" viewBox="0 0 170 170">'
        '<g inkscape:groupmode="layer" inkscape:label="ink">'
        '<polyline points="10,10 170.13,10 170.13,20"/>'
        "</g></svg>",
        encoding="utf-8",
    )
    profile = load_profile("aquila", profiles_path=tmp_path / "profiles.yaml")
    layers = parse_svg_layers(drawing)
    page_size = get_svg_paper_size(drawing)
    assert page_size is not None

    with pytest.raises(PointOutsideBedError):
        build_gcode(layers, profile, page_size)

    fitted = fit_layers_to_drawable(layers, profile, page_size)
    produced = build_gcode(fitted.layers, profile, page_size)

    assert fitted.changed
    assert fitted.scale == 1.0
    assert fitted.layers[0].pen == "ink"
    assert produced.startswith("; penpath gcode profile=aquila page=170.000x170.000 ")


FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"
SIMPLE_SVG = FIXTURES / "svg" / "gcode" / "simple.svg"
AQUILA_SVG = FIXTURES / "svg" / "gcode" / "aquila_card.svg"
RAMPED_PROFILES = FIXTURES / "profiles" / "ramped.yaml"
AQUILA_PAGE = (130.0, 73.0)
NAMED_ORIGINS: tuple[tuple[PlacementName, tuple[float, float], bool], ...] = (
    ("center", (33.65, 59.2), False),
    ("front-right", (57.3, 10.0), False),
    ("front-left", (10.0, 10.0), False),
    ("back-right", (57.3, 108.4), False),
    ("back-left", (10.0, 108.4), False),
    ("origin", (10.0, 10.0), True),
)


def _aquila(tmp_path: Path) -> MachineProfile:
    return load_profile("aquila", profiles_path=tmp_path / "profiles.yaml")


def _pen_points(text: str, profile: MachineProfile) -> list[tuple[float, float]]:
    """Stroke XY moves only, converted from nozzle space back to pen space."""
    offset_x, offset_y = profile.bed.pen_offset_mm
    points: list[tuple[float, float]] = []
    in_layer = False
    for line in text.splitlines():
        if line.startswith("; layer "):
            in_layer = True
            continue
        if not in_layer:
            continue
        match = re.match(r"^G[01] X(-?\d+\.\d+) Y(-?\d+\.\d+)", line)
        if match is None:
            if line.startswith("G1 Z") or line.startswith("M"):
                in_layer = False
            continue
        points.append((float(match.group(1)) + offset_x, float(match.group(2)) + offset_y))
    return points


@pytest.mark.parametrize(("place", "expected", "shifted"), NAMED_ORIGINS)
def test_place_page_named_placements_use_the_aquila_usable_area(
    place: PlacementName,
    expected: tuple[float, float],
    shifted: bool,
    tmp_path: Path,
) -> None:
    placement = place_page(_aquila(tmp_path), AQUILA_PAGE, place=place)

    assert placement.place == place
    assert placement.origin_mm == pytest.approx(expected)
    assert placement.requested_origin_mm == pytest.approx(
        (0.0, 0.0) if place == "origin" else expected
    )
    assert placement.shifted is shifted


def test_place_page_center_of_a_130_by_73_page(tmp_path: Path) -> None:
    placement = place_page(_aquila(tmp_path), AQUILA_PAGE, place="center")

    assert placement.origin_mm == pytest.approx((33.65, 59.2))


def test_place_page_without_place_follows_the_profile(tmp_path: Path) -> None:
    aquila = place_page(_aquila(tmp_path), AQUILA_PAGE)
    generic = place_page(
        load_profile("generic", profiles_path=tmp_path / "profiles.yaml"), AQUILA_PAGE
    )
    ramped = place_page(load_profile("ramped", profiles_path=RAMPED_PROFILES), AQUILA_PAGE)

    assert aquila.place == "front-right"
    assert aquila.origin_mm == pytest.approx((57.3, 10.0))
    assert not aquila.shifted
    for placement in (generic, ramped):
        assert placement.place == "origin"
        assert placement.origin_mm == (0.0, 0.0)
        assert not placement.shifted


def test_place_page_fixed_profile_uses_its_configured_origin() -> None:
    profile = _profile(bed={"size_mm": [100.0, 100.0], "page": {"origin_mm": [5.0, 7.0]}})

    placement = place_page(profile, (50.0, 60.0))

    assert placement.place == "origin"
    assert placement.origin_mm == (5.0, 7.0)
    assert not placement.shifted


def test_place_page_at_sets_a_pen_space_origin(tmp_path: Path) -> None:
    placement = place_page(_aquila(tmp_path), AQUILA_PAGE, at=(15.0, 20.0))

    assert placement.place == "origin"
    assert placement.requested_origin_mm == (15.0, 20.0)
    assert placement.origin_mm == (15.0, 20.0)
    assert not placement.shifted


def test_place_page_at_outside_shifts_to_the_nearest_origin(tmp_path: Path) -> None:
    placement = place_page(_aquila(tmp_path), AQUILA_PAGE, at=(250.0, 200.0))

    assert placement.place == "origin"
    assert placement.requested_origin_mm == (250.0, 200.0)
    assert placement.origin_mm == pytest.approx((57.3, 108.4))
    assert placement.shifted


def test_place_page_fit_false_names_the_requested_origin_and_usable_limits(
    tmp_path: Path,
) -> None:
    with pytest.raises(PointOutsideBedError) as info:
        place_page(_aquila(tmp_path), AQUILA_PAGE, at=(250.0, 200.0), fit=False)

    message = str(info.value)
    assert "requested page origin (x=250.000, y=200.000) mm" in message
    assert "usable area X 10.000..187.300, Y 10.000..181.400 mm" in message
    assert "nearest origin is (x=57.300, y=108.400)" in message
    assert "--fit" in message
    assert "different placement" in message


def test_place_page_rejects_place_and_at_together(tmp_path: Path) -> None:
    with pytest.raises(GcodeError, match=r"either place=.* or at="):
        place_page(_aquila(tmp_path), AQUILA_PAGE, place="center", at=(1.0, 2.0))


def test_place_page_rejects_an_unknown_placement(tmp_path: Path) -> None:
    with pytest.raises(GcodeError, match="Unknown page placement 'middle'"):
        place_page(_aquila(tmp_path), AQUILA_PAGE, place="middle")  # type: ignore[arg-type]


def test_place_page_clamps_a_page_larger_than_the_usable_area(tmp_path: Path) -> None:
    placement = place_page(_aquila(tmp_path), (300.0, 300.0), place="center")

    assert placement.origin_mm == (10.0, 10.0)
    assert placement.shifted


def test_place_page_named_positions_respect_the_bed_margin() -> None:
    profile = _profile(bed={"size_mm": [100.0, 100.0], "margin_mm": 5.0})

    placement = place_page(profile, (50.0, 50.0), place="front-right")

    assert placement.origin_mm == (45.0, 5.0)
    assert not placement.shifted


def test_place_page_named_positions_respect_per_side_margins() -> None:
    profile = _profile(bed={"size_mm": [100.0, 100.0], "margin_mm": [2.0, 3.0, 4.0, 5.0]})

    placement = place_page(profile, (50.0, 50.0), place="front-right")

    assert placement.origin_mm == (47.0, 4.0)
    assert not placement.shifted


def test_page_origin_mm_accepts_an_explicit_placement(tmp_path: Path) -> None:
    profile = _aquila(tmp_path)
    placement = place_page(profile, AQUILA_PAGE, place="center")

    assert page_origin_mm(profile, AQUILA_PAGE) == pytest.approx((57.3, 10.0))
    assert page_origin_mm(profile, AQUILA_PAGE, placement=placement) == pytest.approx((33.65, 59.2))
    assert page_origin_mm(profile, AQUILA_PAGE, placement=placement) is placement.origin_mm


def test_build_gcode_header_records_placement_and_page_origin(tmp_path: Path) -> None:
    profile = _aquila(tmp_path)
    placement = place_page(profile, AQUILA_PAGE, place="center")

    produced = build_gcode(
        _one_layer(((15.0, 20.0), (25.0, 20.0))), profile, AQUILA_PAGE, placement
    )

    assert produced.startswith(
        "; penpath gcode profile=aquila page=130.000x73.000 place=center "
        "page_origin=33.650x59.200 usable_x=10.000..187.300 usable_y=10.000..181.400 "
        "z_up=12.500 z_touch=10.000 z_down=9.000\n"
    )


def test_build_gcode_header_uses_the_profile_placement_by_default(tmp_path: Path) -> None:
    produced = build_gcode([], _aquila(tmp_path), AQUILA_PAGE)

    assert produced.startswith(
        "; penpath gcode profile=aquila page=130.000x73.000 "
        "place=front-right page_origin=57.300x10.000 "
    )


def test_build_gcode_maps_strokes_through_an_explicit_placement() -> None:
    profile = _profile(bed={"size_mm": [100.0, 100.0]})
    placement = place_page(profile, (50.0, 50.0), place="center")

    produced = build_gcode(
        _one_layer(((10.0, 10.0), (20.0, 10.0))), profile, (50.0, 50.0), placement
    )

    assert placement.origin_mm == (25.0, 25.0)
    assert "G0 X35.000 Y65.000 F3600\n" in produced
    assert "G1 X45.000 Y65.000 F1800\n" in produced


def test_fit_layers_to_drawable_uses_an_explicit_placement() -> None:
    profile = _profile(
        bed={"size_mm": [200.0, 200.0], "nozzle_range_mm": [[10.0, 190.0], [10.0, 190.0]]}
    )
    page = (100.0, 100.0)
    placement = place_page(profile, page, place="center")

    fitted = fit_layers_to_drawable(
        _one_layer(((195.0, 5.0), (195.0, 15.0))), profile, page, placement=placement
    )
    produced = build_gcode(fitted.layers, profile, page, placement)

    assert placement.origin_mm == (50.0, 50.0)
    assert fitted.changed
    assert fitted.offset_mm == pytest.approx((-55.0, 0.0))
    assert "G0 X190.000 Y145.000 F3600\n" in produced
    assert "G1 X190.000 Y135.000 F1800\n" in produced


@pytest.mark.parametrize("place", [name for name, _, _ in NAMED_ORIGINS])
def test_build_gcode_keeps_strokes_inside_the_aquila_usable_area_for_every_placement(
    place: PlacementName,
    tmp_path: Path,
) -> None:
    profile = _aquila(tmp_path)
    placement = place_page(profile, AQUILA_PAGE, place=place)

    produced = build_gcode(
        _one_layer(((50.0, 30.0), (60.0, 30.0))), profile, AQUILA_PAGE, placement
    )
    points = _pen_points(produced, profile)
    (x_lo, y_lo), (x_hi, y_hi) = usable_area(profile)

    assert points
    assert all(x_lo - FIT_TOLERANCE_MM <= x <= x_hi + FIT_TOLERANCE_MM for x, _ in points)
    assert all(y_lo - FIT_TOLERANCE_MM <= y <= y_hi + FIT_TOLERANCE_MM for _, y in points)


def test_generic_and_ramped_output_keeps_the_origin_placement(tmp_path: Path) -> None:
    page = get_svg_paper_size(SIMPLE_SVG)
    assert page is not None
    layers = parse_svg_layers(SIMPLE_SVG)

    for profile in (
        load_profile("generic", profiles_path=tmp_path / "profiles.yaml"),
        load_profile("ramped", profiles_path=RAMPED_PROFILES),
    ):
        produced = build_gcode(layers, profile, page)
        assert "place=origin page_origin=0.000x0.000" in produced

    generic = build_gcode(
        layers, load_profile("generic", profiles_path=tmp_path / "profiles.yaml"), page
    )
    assert "G0 X10.000 Y287.000 F6000\n" in generic


def test_end_to_end_placement_flow_from_an_svg_file(tmp_path: Path) -> None:
    profile = _aquila(tmp_path)
    page = get_svg_paper_size(AQUILA_SVG)
    assert page == (170.0, 170.0)
    placement = place_page(profile, page, place="center")
    fitted = fit_layers_to_drawable(
        parse_svg_layers(AQUILA_SVG), profile, page, placement=placement
    )

    produced = build_gcode(fitted.layers, profile, page, placement)
    points = _pen_points(produced, profile)
    (x_lo, y_lo), (x_hi, y_hi) = usable_area(profile)

    assert isinstance(placement, PagePlacement)
    assert placement.origin_mm == pytest.approx((13.65, 10.7))
    assert "place=center page_origin=13.650x10.700" in produced
    assert points
    assert all(x_lo - FIT_TOLERANCE_MM <= x <= x_hi + FIT_TOLERANCE_MM for x, _ in points)
    assert all(y_lo - FIT_TOLERANCE_MM <= y <= y_hi + FIT_TOLERANCE_MM for _, y in points)
