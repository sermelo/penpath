"""End-to-end tests for ``penpath gcode`` as a user runs it."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from penpath.cli.main import main

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SIMPLE_SVG = FIXTURES / "svg" / "gcode" / "simple.svg"
GENERIC_PROFILE = FIXTURES.parent.parent / "src/penpath/presets/profiles/generic.yaml"
GOLDEN = (FIXTURES / "golden" / "gcode" / "generic.gcode").read_text(encoding="utf-8")
SUMMARY_LINES = (
    "G-code summary",
    "Profile: generic",
    "Layers: 1",
    "Drawing length:",
    "Pen-up travel:",
    "Pen lifts:",
    "Estimated plot time:",
)


@pytest.fixture(autouse=True)
def isolated_profiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the real user profiles file out of these tests."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def card(tmp_path: Path) -> Path:
    target = tmp_path / "card.svg"
    shutil.copyfile(SIMPLE_SVG, target)
    return target


def _user_profile(tmp_path: Path, name: str, body: str) -> Path:
    """Write a user profiles file with one machine under ``name``."""
    path = tmp_path / "profiles.yaml"
    indented = "".join(
        f"  {line}" if line.strip() else line for line in body.splitlines(keepends=True)
    )
    path.write_text(f"{name}:\n{indented}", encoding="utf-8")
    return path


def test_gcode_writes_default_output_matching_golden(runner: CliRunner, card: Path) -> None:
    result = runner.invoke(main, ["gcode", str(card), "--profile", "generic"])

    assert result.exit_code == 0, result.stderr
    assert result.stdout == ""
    assert card.with_suffix(".gcode").read_text(encoding="utf-8") == GOLDEN
    assert "G-code saved to:" in result.stderr
    for line in SUMMARY_LINES:
        assert line in result.stderr, result.stderr


def test_gcode_writes_explicit_output(runner: CliRunner, card: Path, tmp_path: Path) -> None:
    output = tmp_path / "nested" / "card.gcode"

    result = runner.invoke(main, ["gcode", str(card), "--profile", "generic", "-o", str(output)])

    assert result.exit_code == 0, result.stderr
    assert result.stdout == ""
    assert output.read_text(encoding="utf-8") == GOLDEN
    assert str(output) in result.stderr
    assert not card.with_suffix(".gcode").exists()


def test_gcode_unknown_profile_exits_2_and_lists_profiles(runner: CliRunner, card: Path) -> None:
    result = runner.invoke(main, ["gcode", str(card), "--profile", "nope"])

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "Unknown profile" in result.stderr
    assert "Available:" in result.stderr
    assert "generic" in result.stderr
    assert not card.with_suffix(".gcode").exists()


def test_gcode_missing_profile_exits_2_and_lists_profiles(runner: CliRunner, card: Path) -> None:
    result = runner.invoke(main, ["gcode", str(card)])

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "Missing option '--profile'" in result.stderr
    assert "generic" in result.stderr


def test_gcode_missing_profiles_file_exits_3_with_fix(
    runner: CliRunner, card: Path, tmp_path: Path
) -> None:
    missing = tmp_path / "missing.yaml"

    result = runner.invoke(
        main, ["gcode", str(card), "--profile", "generic", "--profiles", str(missing)]
    )

    assert result.exit_code == 3
    assert result.stdout == ""
    assert "Cannot read profile file" in result.stderr
    assert str(missing) in result.stderr
    assert "--profiles" in result.stderr


def test_gcode_invalid_yaml_exits_3_with_file_and_line(
    runner: CliRunner, card: Path, tmp_path: Path
) -> None:
    broken = tmp_path / "broken.yaml"
    broken.write_text("generic:\n  bed: [\n", encoding="utf-8")

    result = runner.invoke(
        main, ["gcode", str(card), "--profile", "generic", "--profiles", str(broken)]
    )

    assert result.exit_code == 3
    assert result.stdout == ""
    assert "Invalid YAML" in result.stderr
    assert "broken.yaml" in result.stderr
    assert "line" in result.stderr


def test_gcode_invalid_profile_value_exits_3_naming_key(
    runner: CliRunner, card: Path, tmp_path: Path
) -> None:
    profiles = _user_profile(
        tmp_path,
        "generic",
        """version: 1
name: generic
bed:
  size_mm: [210.0, 297.0]
feed:
  travel_mm_s: -1.0
  draw_mm_s: 50.0
pen:
  z_up: 5.0
  z_down: 0.0
""",
    )

    result = runner.invoke(
        main, ["gcode", str(card), "--profile", "generic", "--profiles", str(profiles)]
    )

    assert result.exit_code == 3
    assert "feed.travel_mm_s" in result.stderr


def test_gcode_point_outside_bed_exits_3_with_coordinates(
    runner: CliRunner, card: Path, tmp_path: Path
) -> None:
    profiles = _user_profile(
        tmp_path,
        "tiny",
        """version: 1
name: tiny
bed:
  size_mm: [15.0, 15.0]
feed:
  travel_mm_s: 100.0
  draw_mm_s: 50.0
pen:
  z_up: 5.0
  z_down: 0.0
""",
    )

    result = runner.invoke(
        main, ["gcode", str(card), "--profile", "tiny", "--profiles", str(profiles)]
    )

    assert result.exit_code == 3
    assert "outside the drawable area" in result.stderr
    assert "x=10.000, y=287.000" in result.stderr


def test_gcode_dry_run_sends_only_gcode_to_stdout(runner: CliRunner, card: Path) -> None:
    result = runner.invoke(main, ["gcode", str(card), "--profile", "generic", "--dry-run"])

    assert result.exit_code == 0, result.stderr
    assert result.stdout == GOLDEN
    for line in SUMMARY_LINES:
        assert line in result.stderr, result.stderr
    assert "G-code saved to:" not in result.stderr
    assert not card.with_suffix(".gcode").exists()


def test_gcode_uses_custom_user_profile(runner: CliRunner, card: Path, tmp_path: Path) -> None:
    body = GENERIC_PROFILE.read_text(encoding="utf-8").replace("name: generic", "name: custom")
    profiles = _user_profile(tmp_path, "custom", body)

    result = runner.invoke(
        main, ["gcode", str(card), "--profile", "custom", "--profiles", str(profiles), "--dry-run"]
    )

    assert result.exit_code == 0, result.stderr
    assert result.stdout.startswith("; penpath gcode profile=custom ")
    assert "Profile: custom" in result.stderr


def test_gcode_help_lists_its_options(runner: CliRunner) -> None:
    result = runner.invoke(main, ["gcode", "--help"])

    assert result.exit_code == 0
    for option in ("--profile", "--profiles", "--dry-run", "-o, --output"):
        assert option in result.stdout
