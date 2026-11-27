"""Tests for PFM Registry."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings, sketch_lines
from penpath.core.drawing.registry import (
    PFMRegistry,
    get_pfm,
    get_registry,
    list_pfms,
    register_pfm,
)
from penpath.presets.pfms import (
    DEFAULT_PFM,
    PFM_PRESETS,
    get_pfm_preset,
    list_pfm_presets,
)


class TestPFMRegistry:
    """Tests for PFMRegistry class."""

    def test_empty_registry(self):
        """Test that a new registry is empty."""
        registry = PFMRegistry()
        assert len(registry) == 0
        assert list(registry.list()) == []
        assert "sketch_lines" not in registry

    def test_register_and_get(self):
        """Test registering and retrieving a PFM."""
        registry = PFMRegistry()

        def dummy_pfm(image, settings):
            return []

        class DummySettings(BaseModel):
            param: int = 1

        registry.register("test_pfm", dummy_pfm, DummySettings)

        assert "test_pfm" in registry
        assert len(registry) == 1
        fn, model = registry.get("test_pfm")
        assert fn is dummy_pfm
        assert model is DummySettings

    def test_register_duplicate_raises(self):
        """Test that registering duplicate name raises ValueError."""
        registry = PFMRegistry()

        def dummy_pfm(image, settings):
            return []

        class DummySettings(BaseModel):
            param: int = 1

        registry.register("test_pfm", dummy_pfm, DummySettings)

        with pytest.raises(ValueError, match="PFM already registered: test_pfm"):
            registry.register("test_pfm", dummy_pfm, DummySettings)

    def test_get_nonexistent_raises(self):
        """Test that getting nonexistent PFM raises KeyError."""
        registry = PFMRegistry()

        with pytest.raises(KeyError, match="PFM not registered: nonexistent"):
            registry.get("nonexistent")

    def test_register_empty_name_raises(self):
        """Test that registering empty name raises ValueError."""
        registry = PFMRegistry()

        def dummy_pfm(image, settings):
            return []

        class DummySettings(BaseModel):
            param: int = 1

        with pytest.raises(ValueError, match="PFM name cannot be empty"):
            registry.register("", dummy_pfm, DummySettings)

    def test_register_non_callable_raises(self):
        """Test that registering non-callable raises ValueError."""
        registry = PFMRegistry()

        class DummySettings(BaseModel):
            param: int = 1

        with pytest.raises(ValueError, match="PFM function must be callable"):
            registry.register("test", "not_a_function", DummySettings)

    def test_register_non_basemodel_raises(self):
        """Test that registering non-BaseModel settings raises ValueError."""
        registry = PFMRegistry()

        def dummy_pfm(image, settings):
            return []

        class NotABaseModel:
            pass

        with pytest.raises(
            ValueError, match="settings_model must be a Pydantic BaseModel subclass"
        ):
            registry.register("test", dummy_pfm, NotABaseModel)

    def test_list_returns_sorted(self):
        """Test that list() returns sorted names."""
        registry = PFMRegistry()

        def dummy_pfm(image, settings):
            return []

        class DummySettings(BaseModel):
            param: int = 1

        registry.register("zebra", dummy_pfm, DummySettings)
        registry.register("apple", dummy_pfm, DummySettings)
        registry.register("banana", dummy_pfm, DummySettings)

        assert registry.list() == ["apple", "banana", "zebra"]


class TestGlobalRegistry:
    """Tests for global registry functions."""

    def test_global_registry_has_sketch_lines(self):
        """Test that global registry has sketch_lines registered."""
        registry = get_registry()
        assert "sketch_lines" in registry
        fn, model = registry.get("sketch_lines")
        assert fn is sketch_lines
        assert model is SketchLinesSettings

    def test_list_pfms_includes_sketch_lines(self):
        """Test that list_pfms includes sketch_lines."""
        pfms = list_pfms()
        assert "sketch_lines" in pfms

    def test_get_pfm_returns_correct_tuple(self):
        """Test that get_pfm returns correct function and model."""
        fn, model = get_pfm("sketch_lines")
        assert fn is sketch_lines
        assert model is SketchLinesSettings

    def test_get_pfm_nonexistent_raises(self):
        """Test that get_pfm for nonexistent raises KeyError."""
        with pytest.raises(KeyError, match="PFM not registered: nonexistent"):
            get_pfm("nonexistent")

    def test_register_pfm_adds_to_global(self):
        """Test that register_pfm adds to global registry."""
        registry = get_registry()
        initial_count = len(registry)

        def dummy_pfm(image, settings):
            return []

        class DummySettings(BaseModel):
            param: int = 1

        register_pfm("test_global", dummy_pfm, DummySettings)

        try:
            assert len(get_registry()) == initial_count + 1
            assert "test_global" in get_registry()
        finally:
            get_registry()._pfms.pop("test_global")


class TestPFMRegistryIntegration:
    """Integration tests for registry with sketch_lines."""

    def test_sketch_lines_settings_model(self):
        """Test that sketch_lines settings model is SketchLinesSettings."""
        _fn, model = get_pfm("sketch_lines")
        assert model is SketchLinesSettings

    def test_can_instantiate_settings_from_registry(self):
        """Test that we can instantiate settings from registry model."""
        _, model = get_pfm("sketch_lines")
        settings = model(line_density=2.0, seed=42)
        assert settings.line_density == 2.0
        assert settings.seed == 42

    def test_settings_validation_via_registry(self):
        """Test that settings validation works through registry."""
        _, model = get_pfm("sketch_lines")

        # Valid settings
        settings = model(line_density=1.0, min_length=10.0, max_length=100.0)
        assert settings.line_density == 1.0

        # Invalid line_density
        with pytest.raises(ValidationError):
            model(line_density=0.0)

        # Invalid min_length > max_length
        with pytest.raises(ValidationError):
            model(min_length=100.0, max_length=50.0)


class TestPFMRegistryPresets:
    """Tests for PFM presets."""

    def test_presets_dict_exists(self):
        """Test that PFM_PRESETS dict exists and has expected keys."""
        assert isinstance(PFM_PRESETS, dict)
        assert len(PFM_PRESETS) > 0

    def test_default_preset_exists(self):
        """Test that 'default' preset exists."""
        assert "default" in PFM_PRESETS
        assert PFM_PRESETS["default"] is not None

    def test_fine_preset(self):
        """Test 'fine' preset settings."""
        preset = PFM_PRESETS["fine"]
        assert isinstance(preset, SketchLinesSettings)
        assert preset.line_density == 0.8
        assert preset.min_length == 5.0
        assert preset.max_length == 50.0
        assert preset.shading_enabled is True
        assert preset.squiggle_enabled is True

    def test_bold_preset(self):
        """Test 'bold' preset settings."""
        preset = PFM_PRESETS["bold"]
        assert isinstance(preset, SketchLinesSettings)
        assert preset.line_density == 1.5
        assert preset.min_length == 15.0
        assert preset.max_length == 150.0
        assert preset.squiggle_enabled is False

    def test_shaded_preset(self):
        """Test 'shaded' preset settings."""
        preset = PFM_PRESETS["shaded"]
        assert isinstance(preset, SketchLinesSettings)
        assert preset.line_density == 2.0
        assert preset.shading_enabled is True
        assert preset.search_angle_step == 3.0

    def test_squiggly_preset(self):
        """Test 'squiggly' preset settings."""
        preset = PFM_PRESETS["squiggly"]
        assert isinstance(preset, SketchLinesSettings)
        assert preset.shading_enabled is False
        assert preset.squiggle_enabled is True
        assert preset.erase_enabled is False

    def test_crosshatch_preset(self):
        """Test 'crosshatch' preset settings."""
        preset = PFM_PRESETS["crosshatch"]
        assert isinstance(preset, SketchLinesSettings)
        assert preset.angle_range == (45.0, 135.0)
        assert preset.squiggle_enabled is False

    def test_hatch_horizontal_preset(self):
        """Test 'hatch_horizontal' preset settings."""
        preset = PFM_PRESETS["hatch_horizontal"]
        assert isinstance(preset, SketchLinesSettings)
        assert preset.angle_range == (85.0, 95.0)
        assert preset.squiggle_enabled is False

    def test_hatch_vertical_preset(self):
        """Test 'hatch_vertical' preset settings."""
        preset = PFM_PRESETS["hatch_vertical"]
        assert isinstance(preset, SketchLinesSettings)
        assert preset.angle_range == (0.0, 10.0)
        assert preset.squiggle_enabled is False

    def test_get_pfm_preset_returns_correct(self):
        """Test that get_pfm_preset returns correct preset."""
        preset = get_pfm_preset("fine")
        assert preset.line_density == 0.8
        assert preset.min_length == 5.0

    def test_get_pfm_preset_nonexistent_raises(self):
        """Test that get_pfm_preset for nonexistent raises ValueError."""
        with pytest.raises(ValueError, match="Unknown PFM preset: nonexistent"):
            get_pfm_preset("nonexistent")

    def test_list_pfm_presets_returns_sorted(self):
        """Test that list_pfm_presets returns sorted list."""
        presets = list_pfm_presets()
        assert presets == sorted(presets)
        assert "default" in presets
        assert "fine" in presets
        assert "bold" in presets
        assert "shaded" in presets
        assert "squiggly" in presets
        assert "crosshatch" in presets
        assert "hatch_horizontal" in presets
        assert "hatch_vertical" in presets

    def test_default_pfm_constant(self):
        """Test DEFAULT_PFM constant."""
        assert DEFAULT_PFM == "default"
        assert DEFAULT_PFM in PFM_PRESETS

    def test_presets_are_independent(self):
        """Test that modifying one preset doesn't affect others."""
        # Pydantic models are immutable-ish, but let's verify
        fine1 = get_pfm_preset("fine")
        fine2 = get_pfm_preset("fine")
        assert fine1.line_density == fine2.line_density

        # Create modified version - use model_copy with update
        modified = fine1.model_copy(update={"line_density": 5.0})
        assert modified.line_density == 5.0
        assert fine1.line_density == 0.8  # Original unchanged


class TestRegistryImports:
    """Tests that all expected exports are available."""

    def test_drawing_exports(self):
        """Test that drawing module exports all expected names."""
        from penpath.core.drawing import (
            SketchLinesSettings,
            get_pfm,
            get_registry,
            list_pfms,
            pfm_sketch_lines,
            register_pfm,
            sketch_lines,
        )

        # Just verify they're importable
        assert SketchLinesSettings is not None
        assert sketch_lines is not None
        assert pfm_sketch_lines is not None
        assert get_registry is not None
        assert register_pfm is not None
        assert get_pfm is not None
        assert list_pfms is not None

    def test_presets_exports(self):
        """Test that presets module exports all expected names."""
        from penpath.presets import (
            DEFAULT_PAPER,
            DEFAULT_PEN,
            DEFAULT_PFM,
            PAPER_PRESETS,
            PEN_PRESETS,
            PFM_PRESETS,
            get_paper,
            get_pen,
            get_pfm_preset,
            list_papers,
            list_pens,
            list_pfm_presets,
        )

        # Just verify they're importable
        assert DEFAULT_PFM is not None
        assert DEFAULT_PEN is not None
        assert DEFAULT_PAPER is not None
        assert PFM_PRESETS is not None
        assert PEN_PRESETS is not None
        assert PAPER_PRESETS is not None
        assert get_pen is not None
        assert get_paper is not None
        assert get_pfm_preset is not None
        assert list_pens is not None
        assert list_papers is not None
        assert list_pfm_presets is not None


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])
