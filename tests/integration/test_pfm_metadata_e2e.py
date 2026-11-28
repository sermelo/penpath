"""End-to-end use of the core PFM metadata API the way an info command does."""

from __future__ import annotations

from pydantic import BaseModel

from penpath.core import field_help, get_pfm_description
from penpath.core.drawing import get_pfm, list_pfms
from penpath.presets.pfms import get_pfm_preset_by_id, list_pfm_preset_ids_for_pfm

BUILTIN_PFMS = (
    "sketch_lines",
    "contour",
    "sketch_squares",
    "stipple",
    "spiral_sawtooth",
    "hatch",
    "patch_hatch",
    "tsp",
    "squiggle",
    "engraving",
)


def build_info() -> dict[str, object]:
    """Assemble the same readable listing part 2's CLI will print."""
    rows: dict[str, object] = {}
    for name in BUILTIN_PFMS:
        _, model = get_pfm(name)
        defaults = model().model_dump(mode="json")
        help_by_name = field_help(model)
        rows[name] = {
            "description": get_pfm_description(name),
            "preset_ids": list_pfm_preset_ids_for_pfm(name),
            "settings": [
                {
                    "name": field_name,
                    "default": defaults[field_name],
                    "help": help_by_name.get(field_name, ""),
                }
                for field_name in model.model_fields
            ],
        }
    return rows


def test_info_listing_is_complete_and_readable() -> None:
    assert set(BUILTIN_PFMS) <= set(list_pfms())
    info = build_info()
    assert len(info) == len(BUILTIN_PFMS)
    for _, row in info.items():
        assert isinstance(row, dict)
        assert isinstance(row["description"], str) and row["description"].strip()
        assert "\n" not in row["description"]
        assert isinstance(row["preset_ids"], list) and row["preset_ids"]
        assert all(isinstance(pid, str) and ":" in pid for pid in row["preset_ids"])
        assert isinstance(row["settings"], list)
        assert len(row["settings"]) > 0
        for setting in row["settings"]:
            assert isinstance(setting, dict)
            assert setting["help"].strip()
            assert "default" in setting


def test_every_listed_preset_id_resolves_with_help() -> None:
    for name in BUILTIN_PFMS:
        _, model = get_pfm(name)
        help_by_name = field_help(model)
        for preset_id in list_pfm_preset_ids_for_pfm(name):
            pfm, settings = get_pfm_preset_by_id(preset_id)
            assert isinstance(settings, BaseModel)
            assert pfm == name
            assert isinstance(settings.model_dump(mode="json"), dict)
            assert help_by_name
