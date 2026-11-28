"""Tests for PFM descriptions in the registry."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from penpath.core.drawing.registry import (
    PFMRegistry,
    get_pfm,
    get_pfm_description,
    get_registry,
    list_pfms,
    register_pfm,
)

BUILTIN_PFMS = {
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
}


class DummySettings(BaseModel):
    param: int = 1


def _dummy_pfm(image: object, settings: DummySettings) -> list[object]:
    return []


class TestPFMDescriptions:
    """Every built-in PFM has a short description for listings."""

    def test_every_builtin_pfm_has_a_nonempty_description(self) -> None:
        assert set(list_pfms()) >= BUILTIN_PFMS
        for name in sorted(BUILTIN_PFMS):
            description = get_pfm_description(name)
            assert description.strip(), f"{name} has no description"
            assert "\n" not in description, f"{name} description is not one line"

    def test_get_pfm_description_unknown_raises_keyerror(self) -> None:
        with pytest.raises(KeyError, match="PFM not registered: nonexistent"):
            get_pfm_description("nonexistent")

    def test_get_pfm_still_returns_the_original_two_tuple(self) -> None:
        fn, model = get_pfm("sketch_lines")
        assert callable(fn)
        assert model.__name__ == "SketchLinesSettings"
        assert len(get_pfm("sketch_lines")) == 2


class TestDescriptionRegistration:
    """The optional description argument is stored without changing get()."""

    def test_register_stores_optional_description(self) -> None:
        registry = PFMRegistry()
        registry.register("described", _dummy_pfm, DummySettings, "A described PFM")
        assert registry.get_description("described") == "A described PFM"
        assert len(registry.get("described")) == 2

    def test_register_without_description_returns_empty_string(self) -> None:
        registry = PFMRegistry()
        registry.register("plain", _dummy_pfm, DummySettings)
        assert registry.get_description("plain") == ""

    def test_get_description_unknown_raises_keyerror(self) -> None:
        registry = PFMRegistry()
        with pytest.raises(KeyError, match="PFM not registered: missing"):
            registry.get_description("missing")

    def test_global_register_pfm_accepts_description(self) -> None:
        registry = get_registry()
        register_pfm("described_global", _dummy_pfm, DummySettings, "Global description")
        try:
            assert get_pfm_description("described_global") == "Global description"
            assert len(get_pfm("described_global")) == 2
        finally:
            registry._pfms.pop("described_global")
            registry._descriptions.pop("described_global")
