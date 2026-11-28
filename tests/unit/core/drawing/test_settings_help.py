"""Tests for field help parsed from settings-model docstrings."""

from __future__ import annotations

from pydantic import BaseModel

from penpath.core.drawing.registry import get_pfm
from penpath.core.drawing.settings_help import field_help

BUILTIN_PFMS = (
    "sketch_lines",
    "contour",
    "sketch_squares",
    "stipple",
    "spiral_sawtooth",
    "hatch",
    "patch_hatch",
    "tsp",
    "squiggle",
    "engraving",
)


class TestFieldHelp:
    """Every built-in settings model documents all of its fields."""

    def test_every_registered_model_field_has_nonempty_help(self) -> None:
        for pfm_name in BUILTIN_PFMS:
            _, model = get_pfm(pfm_name)
            help_by_name = field_help(model)
            for field_name in model.model_fields:
                text = help_by_name.get(field_name, "")
                assert text.strip(), f"{model.__name__}.{field_name} has no help"
                assert "\n" not in text, f"{model.__name__}.{field_name} help is not joined"

    def test_multiline_description_is_joined_with_spaces(self) -> None:
        _, model = get_pfm("sketch_lines")
        text = field_help(model)["line_density"]
        assert text.startswith("Fraction of the luminance progress")
        assert "Higher = more ink." in text
        assert "\n" not in text

    def test_undocumented_field_does_not_raise(self) -> None:
        class PartlyDocumented(BaseModel):
            """Settings with one documented field.

            Parameters
            ----------
            known : int
                A documented field with a longer
                description over two lines.
            """

            known: int = 1
            unknown: int = 2

        help_by_name = field_help(PartlyDocumented)
        assert (
            help_by_name["known"] == "A documented field with a longer description over two lines."
        )
        assert "unknown" not in help_by_name

    def test_model_without_parameters_section_returns_empty(self) -> None:
        class Undocumented(BaseModel):
            """A model with no numpydoc Parameters section."""

            value: int = 1

        assert field_help(Undocumented) == {}
