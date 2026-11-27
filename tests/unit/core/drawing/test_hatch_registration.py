"""Tests for hatch PFM registration, presets and palette angle rotation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from PIL import Image

from penpath.cli.commands.convert import _resolve_pfm
from penpath.cli.main import main
from penpath.core.drawing.pfm_hatch import (
    PALETTE_ANGLE_STEP_DEG,
    HatchSettings,
    hatch_strokes,
    with_angle_offset,
)
from penpath.core.drawing.registry import get_pfm, list_pfms
from penpath.core.image.pipeline import FilterPipeline
from penpath.core.models import ImageRef, Paper, Pen, Project, RegisteredPFM
from penpath.core.project import load_yaml, save_yaml
from penpath.presets.pfms import (
    HATCH_PRESETS,
    get_pfm_for_preset,
    get_pfm_preset_by_id,
    list_pfm_preset_ids,
    list_presets_for_pfm,
)

_PRESET_IDS = ["hatch:crosshatch", "hatch:default", "hatch:fine", "hatch:single"]


class TestHatchRegistration:
    """Hatch is a first-class registered PFM, as contour and stipple are."""

    def test_registry_contains_hatch(self) -> None:
        assert "hatch" in list_pfms()
        fn, model = get_pfm("hatch")
        assert fn is hatch_strokes
        assert model is HatchSettings

    def test_info_pfms_lists_hatch_with_its_qualified_presets(self) -> None:
        result = CliRunner().invoke(main, ["info", "pfms", "--format", "json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        row = next(p for p in data["available_pfms"] if p["name"] == "hatch")
        assert row["settings_model"] == "HatchSettings"
        assert row["presets"] == _PRESET_IDS
        assert row["preset_ids"] == _PRESET_IDS
        assert row["default_settings"]["spacing"] == 1.0
        assert set(_PRESET_IDS) <= set(data["preset_ids"])


class TestHatchPresets:
    """The four qualified ids resolve through the shared preset helper."""

    @pytest.mark.parametrize("preset_id", _PRESET_IDS)
    def test_preset_resolves_to_its_settings(self, preset_id: str) -> None:
        pfm_type, settings = get_pfm_preset_by_id(preset_id)
        assert pfm_type == "hatch"
        assert isinstance(settings, HatchSettings)
        assert settings == HATCH_PRESETS[preset_id.partition(":")[2]]
        assert get_pfm_for_preset(preset_id) == "hatch"
        assert preset_id in list_pfm_preset_ids()
        assert preset_id in list_presets_for_pfm("hatch")

    def test_presets_are_independent_copies(self) -> None:
        _, settings = get_pfm_preset_by_id("hatch:fine")
        assert isinstance(settings, HatchSettings)
        settings.spacing = 99.0
        assert HATCH_PRESETS["fine"].spacing == 0.6

    def test_default_joins_two_directions_with_wider_gap_bridging(self) -> None:
        settings = HATCH_PRESETS["default"]
        assert settings.spacing == 1.0
        assert settings.angles == (45.0, 135.0)
        assert settings.thresholds == (0.25, 0.5)
        assert settings.min_gap == 0.5
        assert settings.join_runs is True
        assert settings.serpentine is True

    def test_crosshatch_uses_default_angles_and_thresholds(self) -> None:
        settings = HATCH_PRESETS["crosshatch"]
        assert settings == HatchSettings()
        assert len(settings.angles) == 4
        assert settings.thresholds == (0.2, 0.4, 0.6, 0.8)

    def test_fine_uses_four_directions_at_0_6_mm(self) -> None:
        settings = HATCH_PRESETS["fine"]
        assert settings.spacing == 0.6
        assert settings.angles == HatchSettings().angles
        assert settings.thresholds == HatchSettings().thresholds

    def test_single_adds_denser_lines_in_one_direction(self) -> None:
        settings = HATCH_PRESETS["single"]
        assert settings.angles == (45.0, 45.0, 45.0, 45.0)
        assert settings.thresholds == HatchSettings().thresholds
        assert settings.variable_spacing is True


class TestHatchSettingsResolution:
    """`--pfm hatch` and `-s` use the registered settings model."""

    def test_algorithm_name_uses_registered_defaults(self) -> None:
        pfm = _resolve_pfm("hatch", {})
        assert isinstance(pfm, RegisteredPFM)
        assert pfm.pfm_type == "hatch"
        assert pfm.settings == HatchSettings()

    def test_spacing_override(self) -> None:
        pfm = _resolve_pfm("hatch", {"spacing": "0.8"})
        assert isinstance(pfm, RegisteredPFM)
        assert isinstance(pfm.settings, HatchSettings)
        assert pfm.settings.spacing == 0.8
        assert pfm.settings.angles == HatchSettings().angles

    def test_preset_plus_override(self) -> None:
        pfm = _resolve_pfm("hatch:fine", {"spacing": "1.2", "variable_spacing": "yes"})
        assert isinstance(pfm, RegisteredPFM)
        assert isinstance(pfm.settings, HatchSettings)
        assert pfm.settings.spacing == 1.2
        assert pfm.settings.variable_spacing is True


class TestHatchProjectFile:
    """Hatch settings survive a YAML round trip through RegisteredPFM."""

    def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        image_path = tmp_path / "input.png"
        image_path.write_bytes(b"fake png")
        settings = HatchSettings(
            spacing=0.7,
            angles=(30.0, 60.0),
            thresholds=(0.3, 0.6),
            variable_spacing=True,
            seed=42,
        )
        original = Project(
            image=ImageRef(path=image_path, filters=FilterPipeline(), dpi=300),
            paper=Paper(name="a4", width_mm=210.0, height_mm=297.0),
            pen=Pen(name="fine", width_mm=0.3),
            pfm=RegisteredPFM(pfm_type="hatch", settings=settings),
            output_path=tmp_path / "output.svg",
        )
        path = tmp_path / "hatch.yaml"
        save_yaml(original, path)

        assert "pfm_type: hatch" in path.read_text()
        loaded = load_yaml(path)
        assert isinstance(loaded.pfm, RegisteredPFM)
        assert isinstance(loaded.pfm.settings, HatchSettings)
        assert loaded.pfm.settings == settings
        assert loaded.pfm.to_typed_settings() == settings


class TestPaletteAngleOffset:
    """The core helper rotates bands without mutating the preset."""

    def test_step_is_thirty_degrees(self) -> None:
        assert PALETTE_ANGLE_STEP_DEG == 30.0

    def test_rotates_every_angle(self) -> None:
        settings = HatchSettings()
        rotated = with_angle_offset(settings, PALETTE_ANGLE_STEP_DEG)
        assert rotated.angles == (75.0, 165.0, 30.0, 120.0)
        assert rotated.thresholds == settings.thresholds
        assert rotated.spacing == settings.spacing
        assert settings.angles == HatchSettings().angles

    def test_wraps_modulo_180(self) -> None:
        settings = HatchSettings()
        assert with_angle_offset(settings, 180.0).angles == settings.angles
        assert with_angle_offset(settings, 390.0).angles == with_angle_offset(settings, 30.0).angles

    def test_zero_offset_leaves_settings_equivalent(self) -> None:
        settings = HatchSettings(seed=42, jitter=0.5)
        rotated = with_angle_offset(settings, 0.0)
        assert rotated is not settings
        assert rotated == settings

        image = Image.new("L", (40, 40), 0)
        assert hatch_strokes(image, settings, 10.0, 0.3) == hatch_strokes(image, rotated, 10.0, 0.3)
