"""Tests for the registry-driven PFM plumbing with a test-only fake PFM."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner
from PIL import Image
from pydantic import BaseModel, Field, ValidationError
from shapely import LineString

from penpath.cli.commands.convert import _resolve_pfm
from penpath.cli.main import main
from penpath.core.drawing import registry as registry_module
from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings, sketch_lines
from penpath.core.drawing.registry import PFMRegistry
from penpath.core.image.pipeline import FilterPipeline
from penpath.core.models import ImageRef, Paper, Pen, Project, RegisteredPFM
from penpath.core.project import load_yaml, save_yaml
from penpath.presets import pfms as pfm_presets_module
from penpath.presets.pfms import (
    PFM_PRESETS,
    get_pfm_for_preset,
    get_pfm_preset_settings,
    list_pfm_presets,
    list_presets_for_pfm,
    register_pfm_preset,
)


class FakeDotsSettings(BaseModel):
    """Settings model of the test-only fake PFM."""

    dots_per_cm: int = Field(default=3, ge=1, le=20)
    jitter: float = 0.0


def fake_dots(image: object, settings: FakeDotsSettings) -> list[LineString]:
    """Test-only PFM that draws one short line for the configured dot count."""
    return [LineString([(0.0, 0.0), (float(settings.dots_per_cm), 0.0)])]


@pytest.fixture
def fake_pfm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Register a fake PFM and one of its presets for a single test."""
    registry = PFMRegistry()
    registry.register("sketch_lines", sketch_lines, SketchLinesSettings)
    registry.register("fake_dots", fake_dots, FakeDotsSettings)
    monkeypatch.setattr(registry_module, "_registry", registry)

    monkeypatch.setattr(pfm_presets_module, "PFM_PRESETS", dict(PFM_PRESETS))
    monkeypatch.setattr(
        pfm_presets_module, "PFM_PRESET_OWNERS", dict.fromkeys(PFM_PRESETS, "sketch_lines")
    )
    monkeypatch.setattr(pfm_presets_module, "_EXTRA_PFM_PRESETS", {})
    register_pfm_preset("fake_fine", "fake_dots", FakeDotsSettings(dots_per_cm=7, jitter=0.5))


@pytest.fixture
def image(tmp_path: Path) -> Path:
    path = tmp_path / "input.png"
    Image.new("RGB", (40, 40), "white").save(path)
    return path


def _convert_args(image: Path, output: Path, *flags: str) -> list[str]:
    return ["convert", str(image), "-o", str(output), "--no-vpype", *flags]


def test_registered_pfm_validates_and_unwraps_own_settings(fake_pfm: None) -> None:
    pfm = RegisteredPFM(pfm_type="fake_dots", settings={"dots_per_cm": 7})
    assert isinstance(pfm.settings, FakeDotsSettings)
    assert pfm.settings.dots_per_cm == 7
    typed = pfm.to_typed_settings()
    assert isinstance(typed, FakeDotsSettings)
    assert typed.jitter == 0.0

    with pytest.raises(ValidationError, match="dots_per_cm"):
        RegisteredPFM(pfm_type="fake_dots", settings={"dots_per_cm": 99})


def test_project_round_trips_registered_pfm(tmp_path: Path, fake_pfm: None) -> None:
    image_path = tmp_path / "input.png"
    Image.new("RGB", (4, 4), "white").save(image_path)
    project = Project(
        image=ImageRef(path=image_path, filters=FilterPipeline()),
        paper=Paper(name="a4", width_mm=210.0, height_mm=297.0),
        pen=Pen(name="fine", width_mm=0.3),
        pfm=RegisteredPFM(pfm_type="fake_dots", settings=FakeDotsSettings(dots_per_cm=9)),
        output_path=tmp_path / "output.svg",
    )
    path = tmp_path / "project.yaml"
    save_yaml(project, path)

    loaded = load_yaml(path)
    assert isinstance(loaded.pfm, RegisteredPFM)
    assert loaded.pfm.settings.dots_per_cm == 9
    assert isinstance(loaded.pfm.to_typed_settings(), FakeDotsSettings)


def test_presets_record_their_owning_pfm(fake_pfm: None) -> None:
    assert get_pfm_for_preset("default") == "sketch_lines"
    assert list_presets_for_pfm("sketch_lines") == sorted(PFM_PRESETS)
    assert isinstance(get_pfm_preset_settings("fine"), SketchLinesSettings)

    assert get_pfm_for_preset("fake_fine") == "fake_dots"
    assert list_presets_for_pfm("fake_dots") == ["fake_fine"]
    assert "fake_fine" in list_pfm_presets()
    assert isinstance(get_pfm_preset_settings("fake_fine"), FakeDotsSettings)


def test_resolve_pfm_uses_named_pfms_own_model(fake_pfm: None) -> None:
    pfm = _resolve_pfm("fake_dots", {"jitter": "1.5"})
    assert isinstance(pfm, RegisteredPFM)
    assert pfm.pfm_type == "fake_dots"
    assert pfm.settings.dots_per_cm == 3
    assert pfm.settings.jitter == 1.5


def test_resolve_pfm_preset_selects_its_pfm_and_overrides(fake_pfm: None) -> None:
    pfm = _resolve_pfm("fake_fine", {"dots_per_cm": "12"})
    assert isinstance(pfm, RegisteredPFM)
    assert pfm.pfm_type == "fake_dots"
    assert pfm.settings.dots_per_cm == 12
    assert pfm.settings.jitter == 0.5


def test_convert_selects_and_overrides_fake_pfm(
    image: Path,
    tmp_path: Path,
    fake_pfm: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[FakeDotsSettings] = []

    def capture(pfm_image: object, settings: FakeDotsSettings) -> list[LineString]:
        seen.append(settings)
        return fake_dots(pfm_image, settings)

    monkeypatch.setitem(
        registry_module.get_registry()._pfms, "fake_dots", (capture, FakeDotsSettings)
    )
    output = tmp_path / "dots.svg"
    result = CliRunner().invoke(
        main, _convert_args(image, output, "--pfm", "fake_fine", "-s", "dots_per_cm=12")
    )
    assert result.exit_code == 0, result.output
    assert len(seen) == 1
    assert isinstance(seen[0], FakeDotsSettings)
    assert seen[0].dots_per_cm == 12
    assert seen[0].jitter == 0.5
    assert output.exists()


@pytest.mark.parametrize(
    ("setting", "expected_in_output"),
    [("bogus=1", "bogus"), ("dots_per_cm=abc", "dots_per_cm"), ("dots_per_cm=99", "dots_per_cm")],
)
def test_invalid_fake_pfm_setting_exits_2_naming_setting(
    image: Path,
    tmp_path: Path,
    fake_pfm: None,
    setting: str,
    expected_in_output: str,
) -> None:
    result = CliRunner().invoke(
        main,
        _convert_args(image, tmp_path / "invalid.svg", "--pfm", "fake_dots", "-s", setting),
    )
    assert result.exit_code == 2
    assert "PFM setting" in result.output
    assert expected_in_output in result.output


def test_info_pfms_json_lists_each_pfms_own_presets(fake_pfm: None) -> None:
    result = CliRunner().invoke(main, ["info", "pfms", "--format", "json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    by_name = {row["name"]: row for row in data["available_pfms"]}
    assert set(by_name) == {"sketch_lines", "fake_dots"}
    assert by_name["sketch_lines"]["presets"] == sorted(PFM_PRESETS)
    assert by_name["fake_dots"]["presets"] == ["fake_fine"]
    assert by_name["fake_dots"]["settings_model"] == "FakeDotsSettings"
    assert by_name["fake_dots"]["default_settings"]["dots_per_cm"] == 3
    assert "fake_fine" in data["presets"]


def test_info_pfms_table_and_yaml_stay_valid(fake_pfm: None) -> None:
    table = CliRunner().invoke(main, ["info", "pfms", "--format", "table"])
    assert table.exit_code == 0, table.output
    assert "fake_dots" in table.output
    assert "fake_fine" in table.output

    yaml_result = CliRunner().invoke(main, ["info", "pfms", "--format", "yaml"])
    assert yaml_result.exit_code == 0, yaml_result.output
    data = yaml.safe_load(yaml_result.output)
    by_name = {row["name"]: row for row in data["available_pfms"]}
    assert by_name["fake_dots"]["presets"] == ["fake_fine"]
