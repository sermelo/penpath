"""Unit tests for saved looks and how they reach the drawing."""

from __future__ import annotations

import pytest
from PIL import Image, ImageDraw
from pydantic import BaseModel
from shapely import LineString

from penpath.core import (
    STYLE_NAMES,
    OutlineSettings,
    draw_styled_lines,
    get_style,
    list_styles,
    outline_strokes,
)
from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings

_TONE_LINE = LineString([(1.0, 1.0), (9.0, 9.0)])


def _edge_image() -> Image.Image:
    """A dark square on white, with edges the outline pass can follow."""
    image = Image.new("L", (120, 120), 255)
    ImageDraw.Draw(image).rectangle([25, 25, 95, 95], fill=0)
    return image


def _tone_pfm(image: object, settings: BaseModel) -> list[LineString]:
    """A PFM stand-in that returns one recognisable tone stroke."""
    return [_TONE_LINE]


class TestStylePresets:
    """Exactly three saved looks, each resolving to validated settings."""

    def test_names_are_exactly_sketch_hatch_outline(self) -> None:
        assert STYLE_NAMES == ("sketch", "hatch", "outline")
        assert list_styles() == ["sketch", "hatch", "outline"]

    def test_sketch_is_the_part_one_default(self) -> None:
        preset = get_style("sketch")
        assert preset.sketch_lines == SketchLinesSettings()
        assert preset.sketch_lines.model_fields_set == set()
        assert preset.outline is None

    def test_hatch_is_directional_with_tone_steps(self) -> None:
        settings = get_style("hatch").sketch_lines
        assert settings.angle_range[1] - settings.angle_range[0] >= 60
        assert settings.shading_enabled is True
        assert settings.line_density < 1.0
        assert settings.max_fill < 90.0
        assert settings.tone_coverage > 0.0
        assert get_style("hatch").outline is None

    def test_outline_has_edge_pass_before_a_light_tone_pass(self) -> None:
        preset = get_style("outline")
        assert isinstance(preset.outline, OutlineSettings)
        assert preset.sketch_lines.line_density < SketchLinesSettings().line_density
        assert preset.sketch_lines.max_fill < SketchLinesSettings().max_fill

    def test_unknown_name_lists_valid_names(self) -> None:
        with pytest.raises(ValueError, match="sketch, hatch, outline"):
            get_style("scribble")


class TestDrawStyledLines:
    """The outline pass runs first and only when the look asks for it."""

    @pytest.mark.parametrize("style", [None, "sketch", "hatch"])
    def test_without_edge_pass_only_the_pfm_draws(self, style: str | None) -> None:
        lines = draw_styled_lines(_edge_image(), _tone_pfm, SketchLinesSettings(), style)
        assert lines == [_TONE_LINE]

    def test_outline_adds_edge_strokes_before_tone(self) -> None:
        preset = get_style("outline")
        assert preset.outline is not None
        image = _edge_image()
        edges = outline_strokes(image, preset.outline)
        assert edges, "the fixture must have a detectable edge"

        lines = draw_styled_lines(image, _tone_pfm, preset.sketch_lines, "outline")
        assert len(lines) == len(edges) + 1
        assert lines[: len(edges)] == edges
        assert lines[-1] == _TONE_LINE

    def test_pfm_receives_its_settings_unchanged(self) -> None:
        seen: list[BaseModel] = []

        def capture(image: object, settings: BaseModel) -> list[LineString]:
            seen.append(settings)
            return _tone_pfm(image, settings)

        settings = get_style("hatch").sketch_lines
        draw_styled_lines(_edge_image(), capture, settings, "hatch")
        assert seen == [settings]

    def test_extra_kwargs_reach_only_the_pfm(self) -> None:
        seen: list[dict[str, object]] = []

        def capture(image: object, settings: BaseModel, **kwargs: object) -> list[LineString]:
            seen.append(kwargs)
            return _tone_pfm(image, settings)

        kwargs = {"pixels_per_mm": 10.0, "pen_width_mm": 0.3}
        lines = draw_styled_lines(_edge_image(), capture, SketchLinesSettings(), "outline", kwargs)

        assert seen == [kwargs]
        assert lines[-1] == _TONE_LINE
