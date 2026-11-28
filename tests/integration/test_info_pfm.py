"""End-to-end coverage for ``penpath info pfms`` and ``penpath info pfm NAME``."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

import pytest
import yaml
from click.testing import CliRunner

from penpath.cli.main import main
from penpath.core import field_help, get_pfm_description
from penpath.core.drawing import get_pfm, list_pfms
from penpath.presets.pfms import list_pfm_preset_ids, list_pfm_preset_ids_for_pfm


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _document(runner: CliRunner, args: list[str]) -> dict[str, Any]:
    result = runner.invoke(main, args)
    assert result.exit_code == 0, result.output
    data: dict[str, Any] = json.loads(result.stdout)
    return data


def test_info_pfms_end_to_end_table_fits_eighty_columns() -> None:
    """A user runs `python -m penpath info pfms` at a narrow terminal."""
    result = subprocess.run(
        [sys.executable, "-m", "penpath", "info", "pfms"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    output = result.stdout
    assert "Name" in output and "Description" in output and "Preset ids" in output
    for hidden in ("default_settings", "settings_model", "'", "{"):
        assert hidden not in output
    assert max(len(line) for line in output.splitlines()) <= 80
    for name in list_pfms():
        assert name in output
        assert get_pfm_description(name).split()[0] in output
        for preset_id in list_pfm_preset_ids_for_pfm(name):
            assert preset_id in output


def test_info_pfms_json_and_yaml_keep_machine_keys_with_canonical_ids(
    runner: CliRunner,
) -> None:
    data = _document(runner, ["info", "pfms", "--format", "json"])
    assert set(data) == {"available_pfms", "presets", "preset_ids"}
    assert data["presets"] == data["preset_ids"] == list_pfm_preset_ids()
    rows = {row["name"]: row for row in data["available_pfms"]}
    assert set(rows) == set(list_pfms())
    for name, row in rows.items():
        assert set(row) == {
            "name",
            "description",
            "settings_model",
            "default_settings",
            "presets",
            "preset_ids",
        }
        assert row["description"].strip()
        assert row["default_settings"]
        assert row["presets"] == row["preset_ids"] == list_pfm_preset_ids_for_pfm(name)
    assert "contour:portrait" in data["preset_ids"]
    assert "contour:silhouette" in data["preset_ids"]
    assert {"stipple:default", "stipple:fine", "stipple:bold"} <= set(data["preset_ids"])

    yaml_result = runner.invoke(main, ["info", "pfms", "--format", "yaml"])
    assert yaml_result.exit_code == 0, yaml_result.output
    assert yaml.safe_load(yaml_result.output) == data


def test_info_pfm_sketch_lines_shows_every_setting_default_and_help(
    runner: CliRunner,
) -> None:
    result = runner.invoke(main, ["info", "pfm", "sketch_lines"])
    assert result.exit_code == 0, result.output
    assert get_pfm_description("sketch_lines")[:20] in result.output
    assert "Preset ids:" in result.output
    for preset_id in list_pfm_preset_ids_for_pfm("sketch_lines"):
        assert preset_id in result.output
    for column in ("Setting", "Default", "Help"):
        assert column in result.output
    assert "default_settings" not in result.output
    assert "None" in result.output
    assert "Fraction of the luminance progress" in result.output

    data = _document(runner, ["info", "pfm", "sketch_lines", "--format", "json"])
    assert set(data) == {"name", "description", "presets", "settings"}
    assert data["name"] == "sketch_lines"
    assert data["description"] == get_pfm_description("sketch_lines")
    assert data["presets"] == list_pfm_preset_ids_for_pfm("sketch_lines")
    _, model = get_pfm("sketch_lines")
    assert [row["name"] for row in data["settings"]] == list(model.model_fields)
    assert all(row["help"] for row in data["settings"])
    seed = next(row for row in data["settings"] if row["name"] == "seed")
    assert seed["default"] is None
    assert seed["help"] == field_help(model)["seed"]


def test_info_pfm_contour_shows_its_own_settings_and_presets(runner: CliRunner) -> None:
    result = runner.invoke(main, ["info", "pfm", "contour"])
    assert result.exit_code == 0, result.output
    assert "Trace clean vector outlines" in result.output
    assert "contour:portrait" in result.output
    assert "contour:silhouette" in result.output
    for setting in ("threshold", "levels", "turn_policy", "seed"):
        assert setting in result.output

    yaml_result = runner.invoke(main, ["info", "pfm", "contour", "--format", "yaml"])
    assert yaml_result.exit_code == 0, yaml_result.output
    data: dict[str, Any] = yaml.safe_load(yaml_result.output)
    assert data["name"] == "contour"
    assert data["presets"] == ["contour:portrait", "contour:silhouette"]
    assert [row["name"] for row in data["settings"]] == list(get_pfm("contour")[1].model_fields)


def test_info_pfm_unknown_name_is_a_click_error(runner: CliRunner) -> None:
    result = runner.invoke(main, ["info", "pfm", "not_a_pfm"])
    assert result.exit_code != 0
    assert "Unknown PFM" in result.output
    for name in list_pfms():
        assert name in result.output


def test_info_help_lists_the_pfm_subcommand(runner: CliRunner) -> None:
    result = runner.invoke(main, ["info", "--help"])
    assert result.exit_code == 0, result.output
    assert "pfm" in result.output
    assert "Show a registered PFM's description" in result.output
