"""Unit tests for registry-driven PFM resolution in ``convert``."""

from __future__ import annotations

import click
import pytest

from penpath.cli.commands.convert import _resolve_pfm
from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings
from penpath.core.drawing.pfm_sketch_squares import SketchSquaresSettings
from penpath.core.models import SketchLinesPFM, SketchSquaresPFM
from penpath.presets.pfms import PFM_PRESETS, SKETCH_SQUARES_PRESETS


class TestResolvePFM:
    """A registered PFM name, legacy preset or qualified id selects the wrapper."""

    def test_default_is_legacy_sketch_lines_default(self) -> None:
        pfm = _resolve_pfm(None, {})
        assert isinstance(pfm, SketchLinesPFM)
        assert pfm.settings == SketchLinesSettings()

    def test_bare_fine_still_means_sketch_lines(self) -> None:
        pfm = _resolve_pfm("fine", {})
        assert isinstance(pfm, SketchLinesPFM)
        assert pfm.settings == PFM_PRESETS["fine"]

    def test_qualified_legacy_preset(self) -> None:
        pfm = _resolve_pfm("sketch_lines:fine", {})
        assert isinstance(pfm, SketchLinesPFM)
        assert pfm.settings == PFM_PRESETS["fine"]

    def test_registered_pfm_name_uses_algorithm_defaults(self) -> None:
        pfm = _resolve_pfm("sketch_squares", {})
        assert isinstance(pfm, SketchSquaresPFM)
        assert pfm.settings == SketchSquaresSettings()

    @pytest.mark.parametrize("preset_id", sorted(SKETCH_SQUARES_PRESETS))
    def test_qualified_square_preset(self, preset_id: str) -> None:
        pfm = _resolve_pfm(f"sketch_squares:{preset_id}", {})
        assert isinstance(pfm, SketchSquaresPFM)
        assert pfm.settings == SKETCH_SQUARES_PRESETS[preset_id]

    def test_overrides_use_the_settings_field_types(self) -> None:
        pfm = _resolve_pfm(
            "sketch_squares",
            {
                "grid_angle": "12.5",
                "line_density": "0.4",
                "min_length": "5.0",
                "max_length": "80.0",
                "max_fill": "90.0",
                "seed": "42",
                "max_strokes": "300",
            },
        )
        assert isinstance(pfm, SketchSquaresPFM)
        assert pfm.settings == SketchSquaresSettings(
            grid_angle=12.5,
            line_density=0.4,
            min_length=5.0,
            max_length=80.0,
            max_fill=90.0,
            seed=42,
            max_strokes=300,
        )

    @pytest.mark.parametrize("pfm", ("sketch_lines", "sketch_squares"))
    def test_white_threshold_override_reaches_both_pfms(self, pfm: str) -> None:
        settings = _resolve_pfm(pfm, {"white_threshold": "0.9"}).to_typed_settings()
        assert isinstance(settings, (SketchLinesSettings, SketchSquaresSettings))
        assert settings.white_threshold == 0.9

    def test_max_tone_ink_is_a_sketch_lines_only_setting(self) -> None:
        settings = _resolve_pfm("sketch_lines", {"max_tone_ink": "0.7"}).to_typed_settings()
        assert isinstance(settings, SketchLinesSettings)
        assert settings.max_tone_ink == 0.7
        with pytest.raises(click.BadParameter):
            _resolve_pfm("sketch_squares", {"max_tone_ink": "0.7"})

    def test_boolean_and_tuple_overrides_for_sketch_lines(self) -> None:
        pfm = _resolve_pfm(
            "sketch_lines",
            {"shading_enabled": "yes", "erase_enabled": "off", "angle_range": "-80,-40"},
        )
        assert isinstance(pfm, SketchLinesPFM)
        assert pfm.settings.shading_enabled is True
        assert pfm.settings.erase_enabled is False
        assert pfm.settings.angle_range == (-80.0, -40.0)


class TestResolvePFMErrors:
    """Invalid names and settings fail with actionable usage errors."""

    @pytest.mark.parametrize(
        ("spec", "expected"),
        [
            ("coarse", "did you mean 'sketch_squares:coarse'"),
            ("nope", "Unknown PFM preset 'nope'"),
            ("nope:coarse", "Unknown PFM: 'nope'"),
            ("sketch_squares:bogus", "Unknown PFM preset 'sketch_squares:bogus'"),
        ],
    )
    def test_bad_pfm_names_name_the_fix(self, spec: str, expected: str) -> None:
        with pytest.raises(click.BadParameter) as excinfo:
            _resolve_pfm(spec, {})
        assert expected in str(excinfo.value.message)

    def test_unknown_setting_names_the_setting(self) -> None:
        with pytest.raises(click.BadParameter, match="Unknown PFM setting: 'bogus'"):
            _resolve_pfm("sketch_squares", {"bogus": "1"})

    @pytest.mark.parametrize(
        ("spec", "key", "value"),
        [
            ("sketch_squares", "grid_angle", "abc"),
            ("sketch_squares", "seed", "not-an-int"),
            ("sketch_squares", "grid_angle", "999"),
            ("sketch_lines", "shading_enabled", "maybe"),
            ("sketch_lines", "angle_range", "-80"),
            ("sketch_lines", "min_length", "100"),
        ],
    )
    def test_invalid_values_name_the_setting(self, spec: str, key: str, value: str) -> None:
        with pytest.raises(click.BadParameter) as excinfo:
            _resolve_pfm(spec, {key: value})
        assert key in str(excinfo.value.message)
