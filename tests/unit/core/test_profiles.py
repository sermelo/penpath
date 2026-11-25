"""Unit tests for the machine profile loader, user file and actionable errors."""

from __future__ import annotations

from pathlib import Path

import pytest

from penpath.core.profiles import (
    InvalidProfileError,
    ProfileFileError,
    ProfileParseError,
    UnknownProfileError,
    get_user_profiles_path,
    list_profile_sources,
    list_profiles,
    load_profile,
)

_MINIMAL_PROFILE = """\
  bed:
    size_mm: [210.0, 297.0]
  feed:
    travel_mm_s: 100.0
    draw_mm_s: 50.0
  pen:
    z_up: 5.0
    z_down: 0.0
"""

_BARE_PROFILE = """\
bed:
  size_mm: [210.0, 297.0]
feed:
  travel_mm_s: 100.0
  draw_mm_s: 50.0
pen:
  z_up: 5.0
  z_down: 0.0
"""


def _write_profiles(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_load_profile_builtin_generic_returns_validated_profile(tmp_path: Path) -> None:
    """The built-in generic profile loads with the D5 sections filled in."""
    profile = load_profile("generic", profiles_path=tmp_path / "no-profiles.yaml")

    assert profile.name == "generic"
    assert profile.version == 1
    assert profile.bed.size_mm == (210.0, 297.0)
    assert profile.bed.pen_offset_mm == (0.0, 0.0)
    assert profile.bed.nozzle_range_mm is None
    assert profile.bed.margin_mm == 0.0
    assert profile.feed.travel_mm_s == 100.0
    assert profile.feed.draw_mm_s == 50.0
    assert profile.feed.effective_z_mm_s == 100.0
    assert profile.pen.z_up == 5.0
    assert profile.pen.z_down == 0.0
    assert profile.pen.ramp_mm is None
    assert profile.gcode.comment_prefix == ";"
    assert "G21" in profile.gcode.start
    assert "M2" in profile.gcode.end
    assert profile.pen_change.mode == "between"


def test_load_profile_user_file_overrides_builtin(tmp_path: Path) -> None:
    """A user profile named like a built-in wins over the packaged YAML."""
    path = _write_profiles(
        tmp_path / "profiles.yaml",
        "generic:\n"
        "  description: My overridden machine\n"
        "  bed:\n"
        "    size_mm: [300.0, 200.0]\n"
        "  feed:\n"
        "    travel_mm_s: 120.0\n"
        "    draw_mm_s: 40.0\n"
        "  pen:\n"
        "    z_up: 7.0\n"
        "    z_down: 1.0\n",
    )

    profile = load_profile("generic", profiles_path=path)

    assert profile.name == "generic"
    assert profile.description == "My overridden machine"
    assert profile.bed.size_mm == (300.0, 200.0)
    assert profile.feed.travel_mm_s == 120.0
    assert profile.pen.z_up == 7.0
    assert list_profiles(path) == ["generic"]


def test_load_profile_user_file_can_hold_several_machines(tmp_path: Path) -> None:
    """One user YAML file maps several names to profiles."""
    path = _write_profiles(
        tmp_path / "profiles.yaml",
        "generic:\n" + _MINIMAL_PROFILE + "shop_plotter:\n" + _MINIMAL_PROFILE,
    )

    assert load_profile("shop_plotter", profiles_path=path).name == "shop_plotter"
    assert list_profiles(path) == ["generic", "shop_plotter"]


def test_load_profile_unknown_name_lists_available(tmp_path: Path) -> None:
    """An unknown name reports what to use instead."""
    path = _write_profiles(
        tmp_path / "profiles.yaml",
        "shop_plotter:\n" + _MINIMAL_PROFILE,
    )

    with pytest.raises(UnknownProfileError) as info:
        load_profile("aqula", profiles_path=path)

    message = str(info.value)
    assert "Unknown profile 'aqula'" in message
    assert "Available: generic, shop_plotter" in message


def test_load_profile_broken_yaml_names_file_line_and_reason(tmp_path: Path) -> None:
    """Malformed YAML points at the file, the line and the parser's reason."""
    path = _write_profiles(
        tmp_path / "profiles.yaml",
        "generic:\n  bed:\n    size_mm: [210, 297\n  feed:\n    travel_mm_s: 1\n",
    )

    with pytest.raises(ProfileParseError) as info:
        load_profile("generic", profiles_path=path)

    message = str(info.value)
    assert str(path) in message
    assert "line 4" in message
    assert "expected ',' or ']'" in message


def test_load_profile_invalid_value_names_key(tmp_path: Path) -> None:
    """A bad value names the key to fix, not just the profile."""
    path = _write_profiles(
        tmp_path / "profiles.yaml",
        "generic:\n"
        "  bed:\n"
        "    size_mm: [210.0, 297.0]\n"
        "  feed:\n"
        "    travel_mm_s: -1\n"
        "    draw_mm_s: 50.0\n"
        "  pen:\n"
        "    z_up: 5.0\n"
        "    z_down: 0.0\n",
    )

    with pytest.raises(InvalidProfileError) as info:
        load_profile("generic", profiles_path=path)

    message = str(info.value)
    assert str(path) in message
    assert "feed.travel_mm_s" in message
    assert "greater than 0" in message


def test_load_profile_unknown_key_names_key(tmp_path: Path) -> None:
    """A typo in a key is rejected and named, since extra keys are not machine data."""
    path = _write_profiles(
        tmp_path / "profiles.yaml",
        "generic:\n" + _MINIMAL_PROFILE + "  feeed:\n    travel_mm_s: 1\n",
    )

    with pytest.raises(InvalidProfileError, match="feeed"):
        load_profile("generic", profiles_path=path)


def test_load_profile_single_profile_not_in_mapping_says_how_to_fix(tmp_path: Path) -> None:
    """A bare profile is rejected with the mapping shape to use."""
    path = _write_profiles(tmp_path / "profiles.yaml", _BARE_PROFILE)

    with pytest.raises(ProfileFileError, match="names to profiles"):
        load_profile("generic", profiles_path=path)


def test_get_user_profiles_path_honours_xdg_config_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """XDG_CONFIG_HOME overrides the default config directory."""
    config_home = tmp_path / "xdg-config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))

    assert get_user_profiles_path() == config_home / "penpath" / "profiles.yaml"


def test_get_user_profiles_path_uses_default_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without XDG_CONFIG_HOME the path is ~/.config/penpath/profiles.yaml."""
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    assert get_user_profiles_path() == tmp_path / ".config" / "penpath" / "profiles.yaml"


def test_list_profiles_defaults_to_user_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """list_profiles() finds user machines in the default file without a path."""
    config_home = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    profiles_file = get_user_profiles_path()
    _write_profiles(profiles_file, "shop_plotter:\n" + _MINIMAL_PROFILE)

    assert list_profiles() == ["generic", "shop_plotter"]


def test_load_profile_defaults_to_user_file_and_overrides_builtin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """load_profile(name) reads the default file; a user machine wins over a built-in."""
    config_home = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    profiles_file = get_user_profiles_path()
    _write_profiles(
        profiles_file,
        "generic:\n  description: My own generic machine\n" + _MINIMAL_PROFILE,
    )

    profile = load_profile("generic")
    assert profile.description == "My own generic machine"


def test_list_profile_sources_marks_builtin_and_user_names(tmp_path: Path) -> None:
    """Each profile is reported once, with the source that load_profile would use."""
    path = _write_profiles(
        tmp_path / "profiles.yaml",
        "generic:\n  description: Mine\n" + _MINIMAL_PROFILE + "shop_plotter:\n" + _MINIMAL_PROFILE,
    )

    assert list_profile_sources(path) == {
        "generic": "user",
        "shop_plotter": "user",
    }


def test_list_profile_sources_without_user_file_marks_builtin(tmp_path: Path) -> None:
    """A missing user file still lists built-ins as built-in."""
    assert list_profile_sources(tmp_path / "no-profiles.yaml") == {"generic": "built-in"}
