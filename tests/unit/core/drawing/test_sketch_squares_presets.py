"""Tests for Sketch Squares registration and built-in presets."""

from __future__ import annotations

import pytest

from penpath.core.drawing.pfm_sketch_squares import SketchSquaresSettings, sketch_squares
from penpath.core.drawing.registry import get_pfm, list_pfms
from penpath.core.models import SketchSquaresPFM
from penpath.presets.pfms import (
    PFM_PRESETS,
    PFM_PRESET_TYPES,
    SKETCH_SQUARES_PRESETS,
    get_pfm_preset,
    get_pfm_preset_by_id,
    list_pfm_preset_ids,
    list_pfm_presets,
)


class TestSketchSquaresRegistration:
    """Sketch Squares is a first-class registered PFM."""

    def test_registry_contains_sketch_squares(self) -> None:
        assert "sketch_squares" in list_pfms()
        fn, model = get_pfm("sketch_squares")
        assert fn is sketch_squares
        assert model is SketchSquaresSettings

    def test_typed_wrapper_uses_the_registered_settings(self) -> None:
        pfm = SketchSquaresPFM(settings=SketchSquaresSettings(grid_angle=12.5, seed=42))
        assert pfm.pfm_type == "sketch_squares"
        assert pfm.to_typed_settings() == pfm.settings


class TestSketchSquaresPresets:
    """Qualified ids resolve to the right PFM and settings model."""

    def test_legacy_presets_are_unchanged(self) -> None:
        assert len(PFM_PRESETS) == 8
        assert set(PFM_PRESETS) <= set(list_pfm_presets())
        fine = get_pfm_preset("fine")
        assert fine.line_density == 0.8
        assert fine.search_angle_step == 5.0

    def test_qualified_ids_list_all_presets(self) -> None:
        ids = list_pfm_preset_ids()
        assert ids == sorted(ids)
        assert all(":" in preset_id for preset_id in ids)
        assert set(PFM_PRESET_TYPES) == set(ids)
        for preset_id, pfm_type in PFM_PRESET_TYPES.items():
            assert pfm_type == preset_id.split(":", 1)[0]

    @pytest.mark.parametrize("preset_id", sorted(SKETCH_SQUARES_PRESETS))
    def test_every_square_preset_resolves_to_its_model(self, preset_id: str) -> None:
        qualified_id = f"sketch_squares:{preset_id}"
        pfm_type, settings = get_pfm_preset_by_id(qualified_id)
        assert pfm_type == "sketch_squares"
        assert isinstance(settings, SketchSquaresSettings)
        assert settings == SKETCH_SQUARES_PRESETS[preset_id]

    def test_legacy_fine_id_resolves_to_sketch_lines(self) -> None:
        pfm_type, settings = get_pfm_preset_by_id("sketch_lines:fine")
        assert pfm_type == "sketch_lines"
        assert settings == get_pfm_preset("fine")

    def test_preset_lookup_returns_a_copy(self) -> None:
        pfm_type, settings = get_pfm_preset_by_id("sketch_squares:coarse")
        assert pfm_type == "sketch_squares"
        assert isinstance(settings, SketchSquaresSettings)
        settings.grid_angle = 123.0
        assert SKETCH_SQUARES_PRESETS["coarse"].grid_angle == 45.0

    def test_bare_square_preset_names_a_qualified_id(self) -> None:
        with pytest.raises(ValueError, match="did you mean 'sketch_squares:coarse'"):
            get_pfm_preset_by_id("coarse")

    def test_bare_fine_suggests_both_qualified_ids(self) -> None:
        with pytest.raises(ValueError) as excinfo:
            get_pfm_preset_by_id("fine")
        assert "sketch_lines:fine" in str(excinfo.value)
        assert "sketch_squares:fine" in str(excinfo.value)

    def test_unknown_pfm_is_reported(self) -> None:
        with pytest.raises(ValueError, match="Unknown PFM: 'nope'"):
            get_pfm_preset_by_id("nope:coarse")

    def test_unknown_preset_of_known_pfm_is_reported(self) -> None:
        with pytest.raises(ValueError, match="Unknown PFM preset 'sketch_squares:bogus'"):
            get_pfm_preset_by_id("sketch_squares:bogus")

    def test_unknown_bare_name_is_reported(self) -> None:
        with pytest.raises(ValueError, match="Unknown PFM preset 'bogus'"):
            get_pfm_preset_by_id("bogus")
