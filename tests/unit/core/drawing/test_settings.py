"""Unit tests for scaling pixel-valued Sketch Lines settings."""

from __future__ import annotations

import pytest

from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings
from penpath.core.drawing.settings import PIXEL_SETTING_FIELDS, scale_pixel_settings


def test_expected_pixel_fields_exist_in_the_model() -> None:
    """A renamed field must fail here instead of silently skipping the scaling."""
    for name in PIXEL_SETTING_FIELDS:
        assert name in SketchLinesSettings.model_fields


def test_missing_pixel_field_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(SketchLinesSettings.model_fields, "min_length")

    with pytest.raises(RuntimeError, match="min_length"):
        scale_pixel_settings(SketchLinesSettings(), 0.5)


def test_pixel_fields_are_scaled_by_the_factor() -> None:
    scaled = scale_pixel_settings(SketchLinesSettings(), 0.5)

    assert scaled.min_length == pytest.approx(1.0)
    assert scaled.max_length == pytest.approx(20.0)
    assert scaled.sample_step == pytest.approx(5.0)


def test_scaled_values_are_clamped_to_lower_bounds() -> None:
    scaled = scale_pixel_settings(SketchLinesSettings(), 0.01)

    assert scaled.min_length == 1.0
    assert scaled.max_length == 1.0
    assert scaled.sample_step == 1.0


def test_scaled_values_are_clamped_to_upper_bounds() -> None:
    scaled = scale_pixel_settings(SketchLinesSettings(), 1000.0)

    assert scaled.min_length == 1000.0
    assert scaled.max_length == 5000.0
    assert scaled.sample_step == 100.0


def test_non_pixel_settings_are_unchanged() -> None:
    original = SketchLinesSettings(
        line_density=0.4,
        seed=42,
        erase_enabled=False,
        angle_range=(-10.0, 10.0),
    )

    scaled = scale_pixel_settings(original, 0.5)

    assert scaled.line_density == 0.4
    assert scaled.seed == 42
    assert scaled.erase_enabled is False
    assert scaled.angle_range == (-10.0, 10.0)


def test_factor_one_preserves_all_values() -> None:
    original = SketchLinesSettings()

    assert scale_pixel_settings(original, 1.0).model_dump() == original.model_dump()


def test_input_settings_are_not_mutated() -> None:
    original = SketchLinesSettings()

    scale_pixel_settings(original, 0.5)

    assert original.min_length == 2.0
    assert original.max_length == 40.0
    assert original.sample_step == 10.0


def test_non_positive_factor_is_rejected() -> None:
    with pytest.raises(ValueError, match="positive"):
        scale_pixel_settings(SketchLinesSettings(), 0.0)
