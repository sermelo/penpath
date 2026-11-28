"""Tests for Spiral Sawtooth registration, presets and settings coercion."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from PIL import Image

from penpath.cli.commands.convert import _resolve_pfm
from penpath.cli.main import main
from penpath.core.drawing.pfm_spiral import SpiralSettings, spiral_strokes
from penpath.core.drawing.registry import get_pfm, list_pfms
from penpath.core.image.pipeline import FilterPipeline
from penpath.core.models import ImageRef, Paper, Pen, Project, SpiralPFM
from penpath.core.project import load_yaml, save_yaml
from penpath.presets.pfms import (
    PFM_PRESET_TYPES,
    PFM_PRESETS,
    SPIRAL_PRESETS,
    get_pfm_preset_by_id,
    list_pfm_preset_ids,
    list_presets_for_pfm,
)


class TestSpiralRegistration:
    """Spiral Sawtooth is a first-class registered PFM."""

    def test_registry_contains_spiral_sawtooth(self) -> None:
        assert "spiral_sawtooth" in list_pfms()
        fn, model = get_pfm("spiral_sawtooth")
        assert fn is spiral_strokes
        assert model is SpiralSettings

    def test_typed_wrapper_uses_the_registered_model(self) -> None:
        pfm = SpiralPFM(settings=SpiralSettings(ring_spacing=5.0, seed=42))
        assert pfm.pfm_type == "spiral_sawtooth"
        assert pfm.to_typed_settings() == pfm.settings

    def test_info_lists_spiral_with_its_qualified_presets(self) -> None:
        result = CliRunner().invoke(main, ["info", "pfms", "--format", "json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        row = next(p for p in data["available_pfms"] if p["name"] == "spiral_sawtooth")
        assert row["settings_model"] == "SpiralSettings"
        assert row["preset_ids"] == [
            "spiral_sawtooth:bold",
            "spiral_sawtooth:fine",
            "spiral_sawtooth:parabolic",
        ]
        assert set(row["preset_ids"]) <= set(data["preset_ids"])


class TestSpiralPresets:
    """Qualified ids resolve to the right PFM and settings model."""

    def test_legacy_presets_are_unchanged(self) -> None:
        assert len(PFM_PRESETS) == 8
        assert PFM_PRESETS["fine"].line_density == 0.8
        assert get_pfm_preset_by_id("fine") == ("sketch_lines", PFM_PRESETS["fine"])

    @pytest.mark.parametrize("preset_id", sorted(SPIRAL_PRESETS))
    def test_every_preset_resolves_to_its_model(self, preset_id: str) -> None:
        qualified_id = f"spiral_sawtooth:{preset_id}"
        pfm_type, settings = get_pfm_preset_by_id(qualified_id)
        assert pfm_type == "spiral_sawtooth"
        assert isinstance(settings, SpiralSettings)
        assert settings == SPIRAL_PRESETS[preset_id]
        assert PFM_PRESET_TYPES[qualified_id] == "spiral_sawtooth"
        assert qualified_id in list_pfm_preset_ids()
        assert qualified_id in list_presets_for_pfm("spiral_sawtooth")

    def test_presets_are_independent_copies(self) -> None:
        _, settings = get_pfm_preset_by_id("spiral_sawtooth:fine")
        settings.ring_spacing = 999.0
        assert SPIRAL_PRESETS["fine"].ring_spacing == 5.0

    def test_parabolic_preset_uses_the_parabolic_branch(self) -> None:
        assert SPIRAL_PRESETS["parabolic"].spiral_type == "parabolic"

    def test_bare_parabolic_is_rejected_with_the_qualified_id(self) -> None:
        with pytest.raises(ValueError, match="spiral_sawtooth:parabolic"):
            get_pfm_preset_by_id("parabolic")


class TestSpiralProjectFile:
    """SpiralPFM survives a YAML round trip."""

    def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        img_path = tmp_path / "input.png"
        img_path.write_bytes(b"fake png")
        original = Project(
            image=ImageRef(path=img_path, filters=FilterPipeline(), dpi=300),
            paper=Paper(name="a4", width_mm=210.0, height_mm=297.0),
            pen=Pen(name="fine", width_mm=0.3),
            pfm=SpiralPFM(
                settings=SpiralSettings(
                    spiral_type="parabolic",
                    centre_x=0.25,
                    ring_spacing=4.0,
                    connected_lines=False,
                    seed=42,
                )
            ),
            output_path=tmp_path / "output.svg",
        )
        path = tmp_path / "spiral.yaml"
        save_yaml(original, path)

        assert "pfm_type: spiral_sawtooth" in path.read_text()
        loaded = load_yaml(path)
        assert isinstance(loaded.pfm, SpiralPFM)
        assert loaded.pfm.settings == original.pfm.settings
        assert loaded.pfm.to_typed_settings() == original.pfm.settings
        assert loaded.pfm.settings.spiral_type == "parabolic"
        assert loaded.pfm.settings.seed == 42


class TestSpiralSettingOverrides:
    """`-s` coerces each field through SpiralSettings and names bad input."""

    @pytest.mark.parametrize(
        ("key", "value", "expected"),
        [
            ("spiral_type", "parabolic", "parabolic"),
            ("centre_x", "0.25", 0.25),
            ("ring_spacing", "4.5", 4.5),
            ("min_velocity", "40", 40.0),
            ("connected_lines", "false", False),
            ("ignore_white", "true", True),
            ("seed", "42", 42),
        ],
    )
    def test_coerces_value(self, key: str, value: str, expected: object) -> None:
        pfm = _resolve_pfm("spiral_sawtooth", {key: value})
        assert isinstance(pfm, SpiralPFM)
        assert getattr(pfm.settings, key) == expected

    def test_preset_plus_override(self) -> None:
        pfm = _resolve_pfm("spiral_sawtooth:fine", {"ring_spacing": "9"})
        assert isinstance(pfm, SpiralPFM)
        assert pfm.settings.ring_spacing == 9.0
        assert pfm.settings.amplitude == SPIRAL_PRESETS["fine"].amplitude

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("not_a_setting", "1"),
            ("spiral_type", "elliptic"),
            ("centre_x", "2"),
            ("connected_lines", "maybe"),
        ],
    )
    def test_invalid_setting_exits_two_naming_the_key(
        self, tmp_path: Path, key: str, value: str
    ) -> None:
        image = tmp_path / "input.png"
        Image.new("RGB", (40, 40), "white").save(image)
        result = CliRunner().invoke(
            main,
            [
                "convert",
                str(image),
                "-o",
                str(tmp_path / "out.svg"),
                "--pfm",
                "spiral_sawtooth",
                "-s",
                f"{key}={value}",
                "--no-vpype",
            ],
        )
        assert result.exit_code == 2
        assert key in result.output
