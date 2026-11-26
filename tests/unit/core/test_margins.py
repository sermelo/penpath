"""Unit tests for per-side bed margins and the usable area (LUC-119 part 1)."""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from pydantic import ValidationError

from penpath.core import (
    GcodeLayer,
    MachineProfile,
    PointOutsideBedError,
    build_gcode,
    fit_layers_to_drawable,
    gcode_to_strokes,
    page_origin_mm,
    parse_gcode_header,
    usable_area,
    with_margin_mm,
)


def _profile(
    margin_mm: float | Sequence[float] | None = None,
    page: dict[str, str] | None = None,
    invert_y: bool | None = None,
) -> MachineProfile:
    bed: dict[str, object] = {"size_mm": [100.0, 100.0]}
    if margin_mm is not None:
        bed["margin_mm"] = margin_mm
    if page is not None:
        bed["page"] = page
    if invert_y is not None:
        bed["invert_y"] = invert_y
    data: dict[str, object] = {
        "name": "asymmetric",
        "bed": bed,
        "feed": {"travel_mm_s": 60.0, "draw_mm_s": 30.0},
        "pen": {"z_up": 5.0, "z_down": 1.0},
    }
    return MachineProfile.model_validate(data)


def _one_layer(*polylines: tuple[tuple[float, float], ...]) -> list[GcodeLayer]:
    return [GcodeLayer("ink", list(polylines))]


def test_bed_profile_margins_mm_scalar_expands_to_all_sides() -> None:
    profile = _profile(2.5)

    assert profile.bed.margin_mm == 2.5
    assert profile.bed.margins_mm == (2.5, 2.5, 2.5, 2.5)


def test_bed_profile_margins_mm_four_values_keep_pen_space_order() -> None:
    profile = _profile([1.0, 2.0, 3.0, 4.0])

    assert profile.bed.margin_mm == (1.0, 2.0, 3.0, 4.0)
    assert profile.bed.margins_mm == (1.0, 2.0, 3.0, 4.0)


@pytest.mark.parametrize(
    "margin_mm",
    [-1.0, [1.0, -2.0, 3.0, 4.0], [1.0, 2.0, 3.0], [1.0, 2.0, 3.0, 4.0, 5.0], ["x", 2, 3, 4]],
)
def test_bed_profile_margins_mm_rejects_invalid_values(margin_mm: object) -> None:
    with pytest.raises(ValidationError) as info:
        _profile(margin_mm)

    assert "bed.margin_mm" in str(info.value)


def test_with_margin_mm_returns_validated_copy_and_keeps_the_original() -> None:
    profile = _profile()

    override = with_margin_mm(profile, [1.0, 2.0, 3.0, 4.0])

    assert override is not profile
    assert override.bed.margins_mm == (1.0, 2.0, 3.0, 4.0)
    assert profile.bed.margins_mm == (0.0, 0.0, 0.0, 0.0)
    assert with_margin_mm(profile, 2.0).bed.margins_mm == (2.0, 2.0, 2.0, 2.0)


def test_with_margin_mm_rejects_an_invalid_margin() -> None:
    with pytest.raises(ValidationError) as info:
        with_margin_mm(_profile(), [1.0, 2.0])

    assert "bed.margin_mm" in str(info.value)


def test_usable_area_insets_each_side_by_its_own_margin() -> None:
    profile = _profile([1.0, 2.0, 3.0, 4.0])

    assert usable_area(profile) == ((4.0, 3.0), (98.0, 99.0))


def test_page_origin_mm_places_page_at_the_usable_front_right_corner() -> None:
    profile = _profile([1.0, 2.0, 3.0, 4.0], page={"placement": "reachable_corner"})

    assert page_origin_mm(profile, (80.0, 50.0)) == (18.0, 3.0)


def test_fit_layers_to_drawable_measures_overshoot_against_the_usable_area() -> None:
    profile = _profile([1.0, 2.0, 3.0, 4.0], invert_y=False)

    fitted = fit_layers_to_drawable(
        _one_layer(((3.0, 50.0), (90.0, 50.0))), profile, (100.0, 100.0)
    )

    assert fitted.changed
    assert fitted.overshoot_mm == (1.0, 0.0)
    assert fitted.offset_mm == (1.0, 0.0)
    assert fitted.layers[0].polylines[0][0] == (4.0, 50.0)


def test_build_gcode_names_the_asymmetric_usable_area_on_failure() -> None:
    profile = _profile([1.0, 2.0, 3.0, 4.0], invert_y=False)

    with pytest.raises(PointOutsideBedError) as info:
        build_gcode(_one_layer(((3.5, 50.0), (90.0, 50.0))), profile, (100.0, 100.0))

    assert str(info.value) == (
        "point (x=3.500, y=50.000) mm is outside the usable area "
        "X 4.000..98.000, Y 3.000..99.000 mm "
        "(drawable area minus margins top=1.000 right=2.000 bottom=3.000 left=4.000 mm); "
        "overshoot x=0.500 mm, y=0.000 mm"
    )


def test_build_gcode_header_reports_usable_area_and_page_origin() -> None:
    profile = _profile([1.0, 2.0, 3.0, 4.0], page={"placement": "reachable_corner"})

    produced = build_gcode(_one_layer(((80.0, 10.0), (90.0, 10.0))), profile, (100.0, 100.0))

    assert produced.startswith(
        "; penpath gcode profile=asymmetric page=100.000x100.000 "
        "page_origin=-2.000,3.000 usable_x=4.000..98.000 usable_y=3.000..99.000 "
        "z_up=5.000 z_down=1.000\n"
    )
    header = parse_gcode_header(produced)
    assert header.page_origin == (-2.0, 3.0)
    assert header.usable_x == (4.0, 98.0)
    assert header.usable_y == (3.0, 99.0)


def test_gcode_to_strokes_uses_header_page_origin_for_a_margin_override() -> None:
    baseline = _profile(page={"placement": "reachable_corner"}, invert_y=False)
    overridden = with_margin_mm(baseline, [1.0, 2.0, 3.0, 4.0])
    layers = _one_layer(((10.0, 10.0), (20.0, 10.0)))

    produced = build_gcode(layers, overridden, (100.0, 100.0))
    strokes = gcode_to_strokes(produced, (100.0, 100.0), baseline)

    assert parse_gcode_header(produced).page_origin == (-2.0, 3.0)
    assert strokes[0].polyline == [(10.0, 10.0), (20.0, 10.0)]
