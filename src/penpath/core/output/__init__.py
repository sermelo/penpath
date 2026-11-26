"""Output module for SVG export and vpype integration."""

from __future__ import annotations

from penpath.core.output.gcode import (
    FIT_TOLERANCE_MM,
    FitResult,
    GcodeError,
    GcodeLayer,
    PointOutsideBedError,
    build_gcode,
    fit_layers_to_drawable,
    lead_in_mm,
    page_origin_mm,
    usable_area,
)
from penpath.core.output.svg import export_pen_layers, export_svg, write_penpath_svg
from penpath.core.output.vpype import optimize_with_vpype

__all__ = [
    "FIT_TOLERANCE_MM",
    "FitResult",
    "GcodeError",
    "GcodeLayer",
    "PointOutsideBedError",
    "build_gcode",
    "export_pen_layers",
    "export_svg",
    "fit_layers_to_drawable",
    "lead_in_mm",
    "optimize_with_vpype",
    "page_origin_mm",
    "usable_area",
    "write_penpath_svg",
]
