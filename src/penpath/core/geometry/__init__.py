"""Geometry optimization module for penpath.

Provides line simplification (RDP), merging (linemerge + collinear join),
and sorting (nearest-neighbour + 2-opt).
"""

from penpath.core.geometry.merge import merge_lines
from penpath.core.geometry.merge import mm_to_pixels as merge_mm_to_pixels
from penpath.core.geometry.simplify import (
    DEFAULT_PAPER_DPI,
    mm_to_pixels,
    pixels_to_mm,
    simplify,
    simplify_line,
)

__all__ = [
    "DEFAULT_PAPER_DPI",
    "merge_lines",
    "merge_mm_to_pixels",
    "mm_to_pixels",
    "pixels_to_mm",
    "simplify",
    "simplify_line",
]
