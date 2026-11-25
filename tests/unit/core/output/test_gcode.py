"""Unit tests for the pure G-code emitter (LUC-51 part 3)."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from penpath.core import (
    GcodeLayer,
    MachineProfile,
    PointOutsideBedError,
    build_gcode,
    load_profile,
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
        "; penpath gcode profile=test_machine z_up=4.000 z_down=1.000\n"
        "G21\n"
        "G90\n"
        "; layer 1/1 pen=ink\n"
        "; begin\n"
        "G0 Z4.000\n"
        "G0 X1.000 Y58.000\n"
        "G0 Z1.000\n"
        "G1 X3.000 Y58.000 F1800\n"
        "G1 X3.000 Y56.000\n"
        "G0 Z4.000\n"
        "G0 X10.000 Y50.000\n"
        "G0 Z1.000\n"
        "G1 X11.000 Y50.000 F1800\n"
        "G0 Z4.000\n"
        "; done\n"
        "M2\n"
    )


def test_build_gcode_keeps_pen_up_between_layers_without_repeating_z() -> None:
    layers = [
        GcodeLayer("first", [((1.0, 1.0), (2.0, 1.0))]),
        GcodeLayer("second", [((3.0, 3.0), (4.0, 3.0))]),
    ]

    produced = build_gcode(layers, _profile(), (10.0, 10.0))

    assert produced.count("G0 Z4.000") == 3
    assert produced.count("G0 Z1.000") == 2
    assert "; layer 1/2 pen=first" in produced
    assert "; layer 2/2 pen=second" in produced
    assert produced.index("; layer 2/2") < produced.index("G0 X3.000 Y7.000")


def test_build_gcode_flips_y_into_pen_space() -> None:
    profile = _profile(bed={"size_mm": [100.0, 100.0], "page": {"origin_mm": [5.0, 7.0]}})

    produced = build_gcode(_one_layer(((1.0, 2.0), (3.0, 4.0))), profile, (50.0, 60.0))

    assert "G0 X6.000 Y65.000\n" in produced
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

    assert "G0 X6.000 Y9.000\n" in produced
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

    assert "G0 X32.700 Y208.600\n" in produced
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

    assert "G0 X130.000 Y158.600\n" in produced
    assert "G1 X132.000 Y158.600 F1800\n" in produced


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
        "; penpath gcode profile=test_machine z_up=12.500 z_touch=10.000 z_down=9.000\n"
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

    assert produced.startswith("; penpath gcode profile=generic z_up=5.000 z_down=0.000\n")
    assert "G21\nG90\nG28\n" in produced
    assert "G0 Z5.000\nG0 X1.000 Y296.000\nG0 Z0.000\n" in produced
    assert "G1 X2.000 Y296.000 F3000\n" in produced
    assert produced.endswith("G0 Z5.000\nM2\n")


def test_build_gcode_does_not_mutate_profile_or_layers() -> None:
    profile = _profile()
    layers = _one_layer(((1.0, 1.0), (2.0, 1.0)))
    original = deepcopy(profile.model_dump())

    build_gcode(layers, profile, (10.0, 10.0))

    assert profile.model_dump() == original
    assert len(layers[0].polylines) == 1
