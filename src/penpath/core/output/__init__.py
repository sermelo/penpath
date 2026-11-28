"""Output module for SVG export and vpype integration."""

from __future__ import annotations

from penpath.core.output.gcode import (
    DEFAULT_FRAME_MARGIN_MM,
    FIT_TOLERANCE_MM,
    FRAME_OVERLAP_MM,
    FRAME_PAUSE_MESSAGE,
    FitResult,
    FrameSpec,
    GcodeError,
    GcodeLayer,
    PagePlacement,
    PlacementName,
    PointOutsideBedError,
    build_gcode,
    drawing_bounds_pen,
    fit_layers_to_drawable,
    frame_polyline,
    lead_in_mm,
    page_origin_mm,
    place_page,
    usable_area,
)
from penpath.core.output.svg import export_pen_layers, export_svg, write_penpath_svg
from penpath.core.output.vpype import optimize_with_vpype

__all__ = [
    "DEFAULT_FRAME_MARGIN_MM",
    "FIT_TOLERANCE_MM",
    "FRAME_OVERLAP_MM",
    "FRAME_PAUSE_MESSAGE",
    "FitResult",
    "FrameSpec",
    "GcodeError",
    "GcodeLayer",
    "PagePlacement",
    "PlacementName",
    "PointOutsideBedError",
    "build_gcode",
    "drawing_bounds_pen",
    "export_pen_layers",
    "export_svg",
    "fit_layers_to_drawable",
    "frame_polyline",
    "lead_in_mm",
    "optimize_with_vpype",
    "page_origin_mm",
    "place_page",
    "usable_area",
    "write_penpath_svg",
]
