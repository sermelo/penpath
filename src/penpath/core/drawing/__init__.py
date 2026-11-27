"""Drawing module for penpath - PFM implementations."""

from penpath.core.drawing.key_layer import key_layer_strokes
from penpath.core.drawing.outline import OutlineSettings, outline_strokes
from penpath.core.drawing.pfm_contour import ContourSettings, contour_strokes
from penpath.core.drawing.pfm_hatch import (
    PALETTE_ANGLE_STEP_DEG,
    HatchSettings,
    hatch_strokes,
    with_angle_offset,
)
from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings, sketch_lines
from penpath.core.drawing.pfm_spiral import SpiralSettings, spiral_strokes
from penpath.core.drawing.pfm_stipple import StippleSettings, stipple
from penpath.core.drawing.registry import (
    PFMRegistry,
    get_pfm,
    get_registry,
    list_pfms,
    register_pfm,
)
from penpath.core.drawing.settings import PIXEL_SETTING_FIELDS, scale_pixel_settings

__all__ = [
    "PALETTE_ANGLE_STEP_DEG",
    "PIXEL_SETTING_FIELDS",
    "ContourSettings",
    "HatchSettings",
    "OutlineSettings",
    "PFMRegistry",
    "SketchLinesSettings",
    "SpiralSettings",
    "StippleSettings",
    "contour_strokes",
    "get_pfm",
    "get_registry",
    "hatch_strokes",
    "key_layer_strokes",
    "list_pfms",
    "outline_strokes",
    "register_pfm",
    "scale_pixel_settings",
    "sketch_lines",
    "spiral_strokes",
    "stipple",
    "with_angle_offset",
]
