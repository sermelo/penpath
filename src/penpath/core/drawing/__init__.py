"""Drawing module for penpath - PFM implementations."""

from penpath.core.drawing.key_layer import key_layer_strokes
from penpath.core.drawing.outline import OutlineSettings, outline_strokes
from penpath.core.drawing.pfm_contour import ContourSettings, contour_strokes
from penpath.core.drawing.pfm_engraving import EngravingSettings, engraving_strokes
from penpath.core.drawing.pfm_hatch import (
    PALETTE_ANGLE_STEP_DEG,
    HatchSettings,
    hatch_strokes,
    with_angle_offset,
)
from penpath.core.drawing.pfm_patch_hatch import (
    PatchHatchSettings,
    patch_hatch_strokes,
    with_layer_angle_offset,
)
from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings, sketch_lines
from penpath.core.drawing.pfm_spiral import SpiralSettings, spiral_strokes
from penpath.core.drawing.pfm_squiggle import SquiggleSettings, squiggle_strokes
from penpath.core.drawing.pfm_stipple import StippleSettings, stipple
from penpath.core.drawing.pfm_tsp import TSPSettings, tsp_strokes
from penpath.core.drawing.registry import (
    PFMRegistry,
    get_pfm,
    get_pfm_description,
    get_registry,
    list_pfms,
    register_pfm,
)
from penpath.core.drawing.settings import PIXEL_SETTING_FIELDS, scale_pixel_settings
from penpath.core.drawing.settings_help import field_help

__all__ = [
    "PALETTE_ANGLE_STEP_DEG",
    "PIXEL_SETTING_FIELDS",
    "ContourSettings",
    "EngravingSettings",
    "HatchSettings",
    "OutlineSettings",
    "PFMRegistry",
    "PatchHatchSettings",
    "SketchLinesSettings",
    "SpiralSettings",
    "SquiggleSettings",
    "StippleSettings",
    "TSPSettings",
    "contour_strokes",
    "engraving_strokes",
    "field_help",
    "get_pfm",
    "get_pfm_description",
    "get_registry",
    "hatch_strokes",
    "key_layer_strokes",
    "list_pfms",
    "outline_strokes",
    "patch_hatch_strokes",
    "register_pfm",
    "scale_pixel_settings",
    "sketch_lines",
    "spiral_strokes",
    "squiggle_strokes",
    "stipple",
    "tsp_strokes",
    "with_angle_offset",
    "with_layer_angle_offset",
]
