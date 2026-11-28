"""Unit tests for shared core resolution and project building."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from penpath.cli.config import PaperConfig, PenConfig
from penpath.core.models import Palette, Project, SketchLinesPFM, SketchSquaresPFM
from penpath.core.resolve import (
    ResolutionError,
    build_project,
    check_drawable_area,
    check_pen_palette_conflict,
    parse_margin_parts,
    resolve_output_path,
    resolve_palette,
    resolve_paper,
    resolve_pen,
    resolve_pfm,
)

PEN_TYPES = ("ballpoint", "fineliner", "fountain", "brush", "marker", "rollerball", "gel")


@pytest.fixture
def image_path(tmp_path: Path) -> Path:
    """A small image that a real ``build_project`` can reference."""
    path = tmp_path / "input.png"
    image = Image.new("RGB", (32, 32), "white")
    image.paste("black", (8, 8, 24, 24))
    image.save(path)
    return path


class TestResolvePen:
    def test_builtin_preset(self) -> None:
        pen = resolve_pen("fine")
        assert (pen.name, pen.width_mm, pen.color, pen.pen_type) == (
            "fine",
            0.3,
            "black",
            "rollerball",
        )

    def test_caller_preset_wins_over_builtin_of_the_same_name(self) -> None:
        presets = {"fine": PenConfig(name="fine", width=0.9, color="#010203", opacity=0.5)}
        pen = resolve_pen("fine", presets=presets)
        assert pen.width_mm == 0.9
        assert pen.color == "#010203"
        assert pen.opacity == 0.5

    def test_default_pen_is_used_without_a_spec(self) -> None:
        assert resolve_pen(None, default_pen="bold").width_mm == 0.8
        assert resolve_pen(None).width_mm == 0.3

    @pytest.mark.parametrize("pen_type", PEN_TYPES)
    def test_inline_spec_accepts_every_pen_type(self, pen_type: str) -> None:
        pen = resolve_pen(f"0.4,#FF6600,{pen_type}")
        assert pen.width_mm == 0.4
        assert pen.color == "#FF6600"
        assert pen.pen_type == pen_type
        assert pen.name == f"0.4-#FF6600-{pen_type}"

    @pytest.mark.parametrize(
        ("spec", "field", "accepted"),
        [
            ("wide", "width_mm", "greater than 0"),
            ("11", "width_mm", "at most 10"),
            ("0.4,#GGGGGG", "color", "#RRGGBB"),
            ("0.4,#000000,bogus", "pen_type", "fineliner"),
        ],
    )
    def test_invalid_inline_spec_names_field_and_fix(
        self, spec: str, field: str, accepted: str
    ) -> None:
        with pytest.raises(ResolutionError) as excinfo:
            resolve_pen(spec)
        assert field in excinfo.value.message
        assert accepted in excinfo.value.message
        assert "Unknown pen" not in excinfo.value.message
        assert excinfo.value.param_hint == "--pen"

    def test_too_many_fields_states_the_format(self) -> None:
        with pytest.raises(ResolutionError, match=r"WIDTH\[,COLOR\[,TYPE\]\]"):
            resolve_pen("0.4,#000000,fine,extra")


class TestResolvePaperAndMargins:
    def test_builtin_paper(self) -> None:
        paper = resolve_paper("a4")
        assert (paper.name, paper.width_mm, paper.height_mm, paper.margin_mm) == (
            "a4",
            210.0,
            297.0,
            10.0,
        )

    def test_caller_preset_wins_over_builtin_of_the_same_name(self) -> None:
        presets = {"a4": PaperConfig(name="a4", width=300, height=300, margin=20)}
        paper = resolve_paper("a4", presets=presets)
        assert paper.width_mm == 300
        assert paper.margin_mm == 20

    def test_default_paper_is_used_without_a_spec(self) -> None:
        assert resolve_paper(None, default_paper="a5").height_mm == 210
        assert resolve_paper(None).name == "a4"

    def test_inline_size_keeps_four_margins_per_side(self) -> None:
        paper = resolve_paper("190x190,20,5,20,5")
        assert paper.name == "inline-190.0x190.0"
        assert paper.margins_mm == (20.0, 5.0, 20.0, 5.0)
        assert paper.drawable_origin_mm == (5.0, 20.0)

    def test_inline_size_without_margins_uses_ten_millimetres(self) -> None:
        assert resolve_paper("190x190").margin_mm == 10.0

    @pytest.mark.parametrize(
        "spec",
        ["190x190,1,2", "190x190,1,2,3,4,5", "190x190,-1", "190x190,nan", "0x190", "unknown"],
    )
    def test_invalid_paper_spec_names_the_flag(self, spec: str) -> None:
        with pytest.raises(ResolutionError) as excinfo:
            resolve_paper(spec)
        assert excinfo.value.param_hint == "--paper"

    def test_parse_margin_parts_keeps_side_order(self) -> None:
        assert parse_margin_parts(["12.5"], "--margin") == 12.5
        assert parse_margin_parts(["20", "5", "20", "5"], "--margin") == (
            20.0,
            5.0,
            20.0,
            5.0,
        )

    @pytest.mark.parametrize("parts", [["1", "2"], ["-1"], ["nan"], ["abc"]])
    def test_invalid_margins_name_the_flag(self, parts: list[str]) -> None:
        with pytest.raises(ResolutionError) as excinfo:
            parse_margin_parts(parts, "--margin")
        assert excinfo.value.param_hint == "--margin"

    def test_drawable_area_error_says_how_to_fix_it(self) -> None:
        paper = resolve_paper("50x50,30,5,30,5")
        with pytest.raises(ResolutionError) as excinfo:
            check_drawable_area(paper, "--margin")
        assert "no drawable area" in excinfo.value.message
        assert "reduce the margin or use a larger paper" in excinfo.value.message
        assert excinfo.value.param_hint == "--margin"
        check_drawable_area(resolve_paper("a4"))


class TestResolvePalette:
    def test_builtin_palette(self) -> None:
        palette = resolve_palette("stabilo_88")
        assert palette.name == "stabilo_88"
        assert len(palette.pens) == 12
        assert "stabilo_88_black" in [pen.name for pen in palette.pens]

    def test_inline_palette_keeps_user_order(self) -> None:
        palette = resolve_palette("red=0.5,#FF0000;blue=0.4,#0000FF")
        assert palette.name == "inline"
        assert [pen.name for pen in palette.pens] == ["red", "blue"]
        assert [pen.color for pen in palette.pens] == ["#FF0000", "#0000FF"]

    @pytest.mark.parametrize(
        ("spec", "expected"),
        [
            ("nonsense", "NAME=WIDTH,#HEX"),
            ("red=0.5", "NAME=WIDTH,#HEX"),
            ("red=wide,#FF0000", "could not convert string to float"),
        ],
    )
    def test_invalid_inline_palette_is_actionable(self, spec: str, expected: str) -> None:
        with pytest.raises(ResolutionError) as excinfo:
            resolve_palette(spec)
        assert "Invalid palette pen 1" in excinfo.value.message
        assert expected in excinfo.value.message
        assert excinfo.value.param_hint == "palette"


class TestResolvePFM:
    def test_default_and_legacy_preset(self) -> None:
        assert isinstance(resolve_pfm(None, {}), SketchLinesPFM)
        assert resolve_pfm("fine", {}).to_typed_settings().line_density == 0.8

    def test_registered_name_and_qualified_preset(self) -> None:
        assert isinstance(resolve_pfm("sketch_squares", {}), SketchSquaresPFM)
        assert isinstance(resolve_pfm("sketch_squares:coarse", {}), SketchSquaresPFM)

    def test_style_applies_to_default_but_not_explicit_pfm(self) -> None:
        styled = resolve_pfm(None, {}, "hatch")
        assert isinstance(styled, SketchLinesPFM)
        assert styled.settings.line_density == 0.75
        explicit = resolve_pfm("sketch_squares", {}, "hatch")
        assert isinstance(explicit, SketchSquaresPFM)

    def test_settings_use_the_models_field_types(self) -> None:
        settings = resolve_pfm(
            "sketch_lines",
            {"shading_enabled": "yes", "angle_range": "-80,-40", "seed": "42"},
        ).to_typed_settings()
        assert settings.shading_enabled is True
        assert settings.angle_range == (-80.0, -40.0)
        assert settings.seed == 42

    def test_saved_base_pfm_is_preserved_under_an_override(self) -> None:
        base = resolve_pfm("sketch_lines:fine", {})
        resolved = resolve_pfm(None, {"seed": "7"}, base_pfm=base)
        assert isinstance(resolved, SketchLinesPFM)
        assert resolved.settings.seed == 7
        assert resolved.settings.line_density == 0.8

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("coarse", "did you mean 'sketch_squares:coarse'"),
            ("nope", "Unknown PFM preset 'nope'"),
            ("nope:coarse", "Unknown PFM: 'nope'"),
            ("sketch_squares:bogus", "Unknown PFM preset 'sketch_squares:bogus'"),
        ],
    )
    def test_unknown_pfm_names_name_the_fix(self, name: str, expected: str) -> None:
        with pytest.raises(ResolutionError) as excinfo:
            resolve_pfm(name, {})
        assert expected in excinfo.value.message
        assert excinfo.value.param_hint == "--pfm"

    @pytest.mark.parametrize(
        ("name", "settings", "expected"),
        [
            ("sketch_lines", {"bogus": "1"}, "Unknown PFM setting: 'bogus'"),
            ("sketch_squares", {"grid_angle": "abc"}, "grid_angle"),
            ("sketch_lines", {"shading_enabled": "maybe"}, "shading_enabled"),
            ("sketch_lines", {"min_length": "100"}, "min_length"),
        ],
    )
    def test_invalid_settings_name_the_setting(
        self, name: str, settings: dict[str, str], expected: str
    ) -> None:
        with pytest.raises(ResolutionError) as excinfo:
            resolve_pfm(name, settings)
        assert expected in excinfo.value.message
        assert excinfo.value.param_hint == "-s/--pfm-setting"


class TestBuildProject:
    def test_defaults_match_convert(self, image_path: Path) -> None:
        project = build_project(image_path)
        assert isinstance(project, Project)
        assert project.paper.name == "a4"
        assert project.pen is not None and project.pen.name == "fine"
        assert project.pens == []
        assert project.image.filters.to_dict() == {
            "steps": [{"name": "grayscale", "kwargs": {"method": "luminance"}, "enabled": True}]
        }
        assert project.image.dpi == 300
        assert project.image.auto_equalize is True
        assert project.image.auto_orient is True
        assert project.image.background is False
        assert project.image.key_layer is None
        assert project.image.palette_adapt is False
        assert project.style is None
        assert project.output_path == image_path.parent / "input_plot.svg"
        assert isinstance(project.pfm, SketchLinesPFM)
        assert project.pfm.settings == resolve_pfm(None, {}).to_typed_settings()

    def test_palette_turns_on_background_and_palette_name(self, image_path: Path) -> None:
        project = build_project(image_path, palette="stabilo_88")
        assert project.pen is None
        assert len(project.pens) == 12
        assert project.palette_name == "stabilo_88"
        assert project.image.background is True
        assert project.image.key_layer is None

    def test_inline_palette_has_no_builtin_name(self, image_path: Path) -> None:
        project = build_project(image_path, palette="red=0.4,#FF0000")
        assert project.palette_name is None
        assert project.image.background is True

    def test_explicit_filters_replace_the_default(self, image_path: Path) -> None:
        project = build_project(image_path, filters=["threshold:level=128"])
        assert [step.name for step in project.image.filters.steps] == ["threshold"]
        assert project.image.filters.steps[0].kwargs == {"level": 128}

    def test_options_reach_the_project(self, image_path: Path) -> None:
        project = build_project(
            image_path,
            pfm="sketch_squares",
            preset="coarse",
            paper="190x190,20,5,20,5",
            pen="0.4,#FF0000,fineliner",
            settings={"seed": "42"},
            style="sketch",
            dpi=150,
            output_path="plot.svg",
            background=True,
            background_threshold=12.5,
            background_method="global",
            saturation=1.5,
            palette_adapt=True,
            key_layer=True,
            auto_orient=False,
            auto_equalize=False,
        )
        assert isinstance(project.pfm, SketchSquaresPFM)
        assert project.paper.margins_mm == (20.0, 5.0, 20.0, 5.0)
        assert project.pen is not None and project.pen.color == "#FF0000"
        assert project.image.dpi == 150
        assert project.image.background is True
        assert project.image.background_threshold == 12.5
        assert project.image.background_method == "global"
        assert project.image.saturation == 1.5
        assert project.image.palette_adapt is False
        assert project.image.key_layer is True
        assert project.image.auto_orient is False
        assert project.image.auto_equalize is False
        assert project.output_path == Path("plot.svg")

    def test_caller_presets_and_defaults_are_used(self, image_path: Path) -> None:
        project = build_project(
            image_path,
            default_pen="bold",
            default_paper="a5",
            pen_presets={"bold": PenConfig(name="bold", width=0.7, color="blue")},
            paper_presets={"a5": PaperConfig(name="a5", width=100, height=200, margin=5)},
        )
        assert project.pen is not None and project.pen.width_mm == 0.7
        assert project.paper.width_mm == 100
        assert project.paper.margin_mm == 5

    def test_background_threshold_implies_background(self, image_path: Path) -> None:
        project = build_project(image_path, background_threshold=8.0)
        assert project.image.background is True
        assert project.image.background_threshold == 8.0

    def test_palette_adapt_on_without_explicit_saturation(self, image_path: Path) -> None:
        project = build_project(image_path, palette_adapt=True)
        assert project.image.palette_adapt is True
        assert project.image.saturation == 1.0

    def test_mutual_exclusion_is_a_resolution_error(self, image_path: Path) -> None:
        with pytest.raises(ResolutionError) as excinfo:
            build_project(image_path, pen="fine", palette="stabilo_88")
        assert "mutually exclusive" in excinfo.value.message
        assert excinfo.value.param_hint is None
        check_pen_palette_conflict(None, "stabilo_88")

    def test_unknown_names_propagate_from_resolvers(self, image_path: Path) -> None:
        with pytest.raises(ResolutionError) as excinfo:
            build_project(image_path, paper="unknown")
        assert excinfo.value.param_hint == "--paper"
        with pytest.raises(ResolutionError) as excinfo:
            build_project(image_path, pfm="unknown")
        assert excinfo.value.param_hint == "--pfm"

    def test_invalid_image_path_is_a_validation_error(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError, match="Image file not found"):
            build_project(tmp_path / "missing.png")

    def test_output_path_resolution(self, image_path: Path) -> None:
        assert resolve_output_path(image_path, None) == image_path.parent / "input_plot.svg"
        assert resolve_output_path(image_path, "plot") == Path("plot.svg")
        assert resolve_output_path(image_path, "plot.svg") == Path("plot.svg")


def test_resolution_error_is_a_value_error() -> None:
    error = ResolutionError("bad value", "--pen")
    assert isinstance(error, ValueError)
    assert str(error) == "bad value"
    assert error.message == "bad value"
    assert error.param_hint == "--pen"


def test_palette_model_is_shared() -> None:
    assert isinstance(resolve_palette("stabilo_88"), Palette)
