"""End-to-end test: a person configures a machine profile in their XDG config."""

from __future__ import annotations

from pathlib import Path

import pytest

from penpath.core import UnknownProfileError, get_user_profiles_path, list_profiles, load_profile


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

    assert list_profiles() == ["generic", "shop_plotter"]

    shop = load_profile("shop_plotter")
    assert shop.bed.size_mm == (300.0, 210.0)
    assert shop.bed.invert_y is False
    assert shop.feed.effective_z_mm_s == 12.0
    assert shop.pen_change.mode == "each"
    assert shop.pen_change.steps[0].message == "Mount {pen}"

    overridden = load_profile("generic")
    assert overridden.description == "My own generic machine"
    assert overridden.bed.size_mm == (400.0, 300.0)

    with pytest.raises(UnknownProfileError, match="Available: generic, shop_plotter"):
        load_profile("missing_machine")
