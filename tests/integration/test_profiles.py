"""End-to-end test: a person configures a machine profile in their XDG config."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

from penpath.core import UnknownProfileError, get_user_profiles_path, list_profiles, load_profile

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_user_configures_profiles_in_xdg_dir_and_loads_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A user writes one YAML file in the config dir; penpath finds every machine."""
    config_home = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    profiles_file = get_user_profiles_path()
    assert profiles_file == config_home / "penpath" / "profiles.yaml"

    profiles_file.parent.mkdir(parents=True)
    profiles_file.write_text(
        """\
shop_plotter:
  description: The small plotter in the shop
  bed:
    size_mm: [300.0, 210.0]
    invert_y: false
  feed:
    travel_mm_s: 80.0
    draw_mm_s: 30.0
    z_mm_s: 12.0
  pen:
    z_up: 6.0
    z_down: 0.5
  pen_change:
    mode: each
    steps:
      - {message: "Mount {pen}"}
      - {pause: "Press the knob"}
generic:
  description: My own generic machine
  bed:
    size_mm: [400.0, 300.0]
  feed:
    travel_mm_s: 100.0
    draw_mm_s: 50.0
  pen:
    z_up: 5.0
    z_down: 0.0
""",
        encoding="utf-8",
    )

    assert list_profiles() == ["aquila", "generic", "shop_plotter"]

    shop = load_profile("shop_plotter")
    assert shop.bed.size_mm == (300.0, 210.0)
    assert shop.bed.invert_y is False
    assert shop.feed.effective_z_mm_s == 12.0
    assert shop.pen_change.mode == "each"
    assert shop.pen_change.steps[0].message == "Mount {pen}"

    overridden = load_profile("generic")
    assert overridden.description == "My own generic machine"
    assert overridden.bed.size_mm == (400.0, 300.0)

    with pytest.raises(UnknownProfileError, match="Available: aquila, generic, shop_plotter"):
        load_profile("missing_machine")


def _documented_example() -> tuple[str, str]:
    text = (_REPO_ROOT / "docs" / "CLI.md").read_text(encoding="utf-8")
    section = text.split("## Machine Profile Format", 1)[1].split("\n## Pen Presets", 1)[0]
    example = section.split("### Complete example", 1)[1].split("```yaml", 1)[1].split("```", 1)[0]
    data = yaml.safe_load(example)
    assert isinstance(data, dict)
    name = data["name"]
    assert isinstance(name, str)
    return name, example


def test_documented_example_profile_loads_unchanged(tmp_path: Path) -> None:
    """The complete example in docs/CLI.md passes the real loader unchanged."""
    name, example = _documented_example()
    profiles_file = tmp_path / "profiles.yaml"
    profiles_file.write_text(f"{name}:\n{textwrap.indent(example, '  ')}", encoding="utf-8")

    profile = load_profile(name, profiles_file)

    assert profile.name == name
    assert profile.description == "Example machine with a Z-lifted pen and an offset toolhead"
    assert profile.bed.size_mm == (220.0, 220.0)
    assert profile.bed.pen_offset_mm == (-22.7, -28.6)
    assert profile.bed.nozzle_range_mm == ((0.0, 220.0), (0.0, 220.0))
    assert profile.feed.effective_z_mm_s == 10.0
    assert profile.pen.ramp_mm == 1.5
    assert profile.pen_change.mode == "each"
    assert len(profile.pen_change.steps) == 5
    assert "{layer_index}" in profile.gcode.layer_start


def test_info_profiles_end_to_end_lists_builtin_and_user_machines(tmp_path: Path) -> None:
    """A user runs `python -m penpath info profiles` and reads both sources."""
    config_home = tmp_path / "xdg"
    profiles_file = config_home / "penpath" / "profiles.yaml"
    profiles_file.parent.mkdir(parents=True)
    profiles_file.write_text(
        "shop_plotter:\n"
        "  description: The small plotter in the shop\n"
        "  bed:\n    size_mm: [300.0, 210.0]\n"
        "  feed:\n    travel_mm_s: 80.0\n    draw_mm_s: 30.0\n"
        "  pen:\n    z_up: 6.0\n    z_down: 0.5\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["XDG_CONFIG_HOME"] = str(config_home)
    result = subprocess.run(
        [sys.executable, "-m", "penpath", "info", "profiles", "--format", "json"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    rows = {row["name"]: row for row in data["profiles"]}
    assert rows["generic"]["source"] == "built-in"
    assert rows["shop_plotter"]["source"] == "user"
    assert rows["shop_plotter"]["bed_width_mm"] == 300.0
    assert rows["shop_plotter"]["travel_mm_s"] == 80.0
