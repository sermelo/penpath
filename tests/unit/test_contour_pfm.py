"""Unit tests for Contour PFM registration, settings, presets and project files."""

from __future__ import annotations

import json
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from penpath.cli.commands.convert import _resolve_pfm
from penpath.cli.main import main
from penpath.core.drawing.pfm_contour import ContourSettings
from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings
from penpath.core.drawing.registry import get_pfm, list_pfms
from penpath.core.image.pipeline import FilterPipeline
from penpath.core.models import (
    ImageRef,
    Paper,
    Pen,
    Project,
    RegisteredPFM,
    SketchLinesPFM,
    make_pfm_settings,
)
from penpath.core.project import load_yaml, save_yaml
from penpath.presets.pfms import (
    get_pfm_for_preset,
    get_pfm_preset_settings,
    list_presets_for_pfm,
)


def _overrides(spec: str) -> dict[str, str]:
    return dict(item.split("=", 1) for item in spec.split())


def test_registry_and_preset_owners() -> None:
    fn, model = get_pfm("contour")
    assert "contour" in list_pfms()
    assert fn.__name__ == "contour_strokes"
    assert model is ContourSettings
    assert set(list_presets_for_pfm("contour")) == {"contour_portrait", "contour_silhouette"}
    assert get_pfm_for_preset("contour_portrait") == "contour"
    assert isinstance(get_pfm_preset_settings("contour_silhouette"), ContourSettings)


@pytest.mark.parametrize(
    ("name", "spec"),
    [
        (None, ""),
        ("contour", ""),
        ("contour_portrait", ""),
        ("contour_silhouette", ""),
        ("contour_portrait", "threshold=200"),
    ],
)
def test_resolve_pfm_returns_the_matching_pfm(name: str | None, spec: str) -> None:
    pfm = _resolve_pfm(name, _overrides(spec))
    assert isinstance(pfm, SketchLinesPFM if name is None else RegisteredPFM)
    if name is not None:
        assert pfm.pfm_type == "contour"
    assert isinstance(
        pfm.to_typed_settings(), SketchLinesSettings if name is None else ContourSettings
    )


def test_resolve_pfm_applies_typed_overrides() -> None:
    pfm = _resolve_pfm(
        "contour",
        _overrides("threshold=110 alpha_max=0.4 opticurve=false seed=7 turn_policy=white"),
    )
    settings = pfm.to_typed_settings()
    assert isinstance(settings, ContourSettings)
    assert (
        settings.threshold,
        settings.alpha_max,
        settings.opticurve,
        settings.seed,
        settings.turn_policy,
    ) == (110, 0.4, False, 7, "white")


def test_resolve_pfm_rejects_bad_inputs() -> None:
    for name, spec in (
        ("unknown", ""),
        ("contour", "line_density=1"),
        ("contour", "threshold=abc"),
        ("contour", "threshold=999"),
    ):
        with pytest.raises(click.BadParameter):
            _resolve_pfm(name, _overrides(spec))


def test_contour_project_yaml_round_trip(tmp_path: Path) -> None:
    pfm = make_pfm_settings("contour", ContourSettings(threshold=110, levels=4))
    assert isinstance(pfm, RegisteredPFM)
    assert pfm.pfm_type == "contour"
    assert pfm.to_typed_settings().threshold == 110
    image = tmp_path / "input.png"
    image.write_bytes(b"fake png")
    project = Project(
        image=ImageRef(path=image, filters=FilterPipeline()),
        paper=Paper(name="a4", width_mm=210.0, height_mm=297.0),
        pen=Pen(name="fine", width_mm=0.3),
        pfm=pfm,
        output_path=tmp_path / "out.svg",
    )
    path = tmp_path / "contour.yaml"
    save_yaml(project, path)
    assert "pfm_type: contour" in path.read_text(encoding="utf-8")
    loaded = load_yaml(path)
    assert isinstance(loaded.pfm, RegisteredPFM)
    assert loaded.pfm.pfm_type == "contour"
    assert loaded.pfm.to_typed_settings().levels == 4


def test_info_pfms_json_groups_presets_by_pfm() -> None:
    result = CliRunner().invoke(main, ["info", "pfms", "--format", "json"])
    assert result.exit_code == 0, result.output
    rows = {row["name"]: row for row in json.loads(result.output)["available_pfms"]}
    assert rows["contour"]["presets"] == sorted(list_presets_for_pfm("contour"))
    assert not any(name.startswith("contour") for name in rows["sketch_lines"]["presets"])
