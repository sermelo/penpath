"""Output module for SVG export and vpype integration."""

from __future__ import annotations

from penpath.core.output.gcode import (
    GcodeError,
    GcodeLayer,
    PointOutsideBedError,
    build_gcode,
    lead_in_mm,
    page_origin_mm,
)
from penpath.core.output.svg import export_pen_layers, export_svg, write_penpath_svg
from penpath.core.output.vpype import optimize_with_vpype

__all__ = [
    "GcodeError",
    "GcodeLayer",
    "PointOutsideBedError",
    "build_gcode",
    "export_pen_layers",
    "export_svg",
    "lead_in_mm",
    "optimize_with_vpype",
    "page_origin_mm",
    "write_penpath_svg",
]
