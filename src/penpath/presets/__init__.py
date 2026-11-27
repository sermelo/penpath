"""Presets package for penpath."""

from penpath.presets.palettes import PALETTES, get_palette, list_palettes
from penpath.presets.papers import DEFAULT_PAPER, PAPER_PRESETS, get_paper, list_papers
from penpath.presets.pens import DEFAULT_PEN, PEN_PRESETS, get_pen, list_pens
from penpath.presets.pfms import (
    DEFAULT_PFM,
    PFM_PRESETS,
    get_pfm_for_preset,
    get_pfm_preset,
    get_pfm_preset_settings,
    list_pfm_presets,
    list_presets_for_pfm,
    register_pfm_preset,
)

__all__ = [
    "DEFAULT_PAPER",
    "DEFAULT_PEN",
    "DEFAULT_PFM",
    "PALETTES",
    "PAPER_PRESETS",
    "PEN_PRESETS",
    "PFM_PRESETS",
    "get_palette",
    "get_paper",
    "get_pen",
    "get_pfm_for_preset",
    "get_pfm_preset",
    "get_pfm_preset_settings",
    "list_palettes",
    "list_papers",
    "list_pens",
    "list_pfm_presets",
    "list_presets_for_pfm",
    "register_pfm_preset",
]
