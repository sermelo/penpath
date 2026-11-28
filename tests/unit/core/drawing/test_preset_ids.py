"""Tests for canonical PFM preset ids and legacy aliases."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from penpath.presets.pfms import (
    PFM_PRESET_TYPES,
    get_pfm_preset,
    get_pfm_preset_by_id,
    list_pfm_preset_ids,
    list_pfm_preset_ids_for_pfm,
    list_pfm_presets,
)

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


class TestCanonicalPresetIds:
    """One canonical ``PFM:PRESET`` id per built-in preset."""

    @pytest.mark.parametrize(
        ("pfm", "preset", "expected"),
        [
            ("sketch_lines", "fine", "sketch_lines:fine"),
            ("contour", "contour_portrait", "contour:portrait"),
            ("contour", "contour_silhouette", "contour:silhouette"),
            ("stipple", "stipple_fine", "stipple:fine"),
            ("sketch_squares", "sketch_squares:coarse", "sketch_squares:coarse"),
        ],
    )
    def test_canonical_id_rule(self, pfm: str, preset: str, expected: str) -> None:
        assert expected in list_pfm_preset_ids_for_pfm(pfm)
        assert get_pfm_preset_by_id(expected) == get_pfm_preset_by_id(preset)

    def test_per_pfm_ids_are_sorted_and_unique(self) -> None:
        for pfm in BUILTIN_PFMS:
            ids = list_pfm_preset_ids_for_pfm(pfm)
            assert ids == sorted(set(ids))
            assert all(preset_id.startswith(f"{pfm}:") for preset_id in ids)

    def test_no_builtin_preset_is_missing(self) -> None:
        assert len(list_pfm_preset_ids()) == len(list_pfm_presets())
        assert set(list_pfm_preset_ids()) == set(PFM_PRESET_TYPES)

    def test_all_required_ids_are_listed(self) -> None:
        ids = set(list_pfm_preset_ids())
        assert ids >= {
            "sketch_lines:fine",
            "sketch_lines:default",
            "contour:portrait",
            "contour:silhouette",
            "stipple:default",
            "stipple:fine",
            "stipple:bold",
            "sketch_squares:coarse",
            "hatch:fine",
            "spiral_sawtooth:parabolic",
        }
        assert list_pfm_preset_ids() == sorted(ids)


class TestLegacyAliasResolution:
    """Canonical ids, legacy bare names and qualified ids share settings."""

    @pytest.mark.parametrize(
        ("preset_id", "legacy_name", "pfm"),
        [
            ("contour:portrait", "contour_portrait", "contour"),
            ("contour:silhouette", "contour_silhouette", "contour"),
            ("stipple:default", "stipple_default", "stipple"),
            ("stipple:fine", "stipple_fine", "stipple"),
            ("stipple:bold", "stipple_bold", "stipple"),
            ("sketch_lines:fine", "fine", "sketch_lines"),
        ],
    )
    def test_aliases_return_the_same_settings(
        self, preset_id: str, legacy_name: str, pfm: str
    ) -> None:
        canonical = get_pfm_preset_by_id(preset_id)
        legacy = get_pfm_preset_by_id(legacy_name)
        assert canonical == legacy
        assert canonical[0] == pfm
        assert isinstance(canonical[1], BaseModel)

    def test_bare_fine_matches_the_legacy_preset(self) -> None:
        pfm, settings = get_pfm_preset_by_id("fine")
        assert pfm == "sketch_lines"
        assert settings == get_pfm_preset("fine")

    def test_lookup_returns_a_fresh_copy(self) -> None:
        _, first = get_pfm_preset_by_id("stipple:fine")
        _, second = get_pfm_preset_by_id("stipple:fine")
        assert first == second
        assert first is not second

    def test_unknown_preset_of_known_pfm_still_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown PFM preset 'stipple:bogus'"):
            get_pfm_preset_by_id("stipple:bogus")

    def test_unknown_bare_name_still_suggests_a_qualified_id(self) -> None:
        with pytest.raises(ValueError, match="did you mean 'sketch_squares:coarse'"):
            get_pfm_preset_by_id("coarse")
