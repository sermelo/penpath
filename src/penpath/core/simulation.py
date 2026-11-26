"""Plot simulation and machine cost computation.

This module provides core functions for simulating a pen plot, computing
machine costs (pen-up travel, lifts, short segments), and measuring the share
of the paper inked by each layer from a list of pen strokes.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image, ImageDraw

if TYPE_CHECKING:
    from collections.abc import Sequence


# Type aliases for machine cost metrics
type LayerMetrics = dict[str, float | int]
type MachineCostResult = dict[str, dict[str, LayerMetrics] | LayerMetrics]


@dataclass(frozen=True, slots=True)
class CoverageResult:
    """Ink coverage as percentages of the whole paper area.

    Attributes
    ----------
    per_layer : dict[str, float]
        Percentage of the paper inked by each layer, keyed by stroke colour.
    total : float
        Percentage of the paper inked by at least one layer (the union).
    """

    per_layer: dict[str, float]
    total: float


@dataclass(frozen=True, slots=True)
class PenStroke:
    """A single pen stroke with geometry and styling.

    Attributes
    ----------
    polyline : list[tuple[float, float]]
        Sequence of (x, y) points in millimetres. Must have at least 2 points.
    width_mm : float
        Pen stroke width in millimetres.
    color : str
        Stroke color as hex string (e.g., "#000000") or named CSS color.
    pen_up : bool
        True if this stroke is a pen-up travel move (not drawn).
    """

    polyline: list[tuple[float, float]]
    width_mm: float
    color: str
    pen_up: bool = False

    def __post_init__(self) -> None:
        """Validate stroke after initialization."""
        if len(self.polyline) < 2:
            raise ValueError("PenStroke polyline must have at least 2 points")
        if self.width_mm <= 0:
            raise ValueError("PenStroke width_mm must be positive")


def _polyline_length(polyline: Sequence[tuple[float, float]]) -> float:
    """Calculate total length of a polyline in millimetres."""
    if len(polyline) < 2:
        return 0.0
    total = 0.0
    for i in range(len(polyline) - 1):
        x1, y1 = polyline[i]
        x2, y2 = polyline[i + 1]
        total += hypot(x2 - x1, y2 - y1)
    return total


def _count_short_segments(polyline: Sequence[tuple[float, float]], threshold_mm: float) -> int:
    """Count segments shorter than threshold."""
    if len(polyline) < 2:
        return 0
    count = 0
    for i in range(len(polyline) - 1):
        x1, y1 = polyline[i]
        x2, y2 = polyline[i + 1]
        if hypot(x2 - x1, y2 - y1) < threshold_mm:
            count += 1
    return count


def compute_machine_cost(
    strokes: Sequence[PenStroke],
    short_segment_threshold_mm: float = 0.5,
) -> MachineCostResult:
    """Compute machine cost metrics for a list of pen strokes.

    Parameters
    ----------
    strokes : Sequence[PenStroke]
        List of pen strokes to analyze.
    short_segment_threshold_mm : float, optional
        Segment length below which a segment is considered "short".
        Default is 0.5 mm.

    Returns
    -------
    MachineCostResult
        Dictionary with per-layer (by color) and total metrics:
        - drawing_length_mm: total length of pen-down strokes
        - pen_up_travel_mm: total length of pen-up moves
        - num_lifts: number of pen-up transitions
        - num_short_segments: number of segments shorter than threshold
        - num_strokes: number of pen-down strokes (pen-up moves are not strokes)

    Notes
    -----
    Layers are grouped by stroke color. Each color gets its own entry
    in the "per_layer" dict, plus a "total" entry with summed metrics.
    """
    per_layer: dict[str, LayerMetrics] = {}
    total: LayerMetrics = {
        "drawing_length_mm": 0.0,
        "pen_up_travel_mm": 0.0,
        "num_lifts": 0,
        "num_short_segments": 0,
        "num_strokes": 0,
    }

    for stroke in strokes:
        layer_key = stroke.color
        if layer_key not in per_layer:
            per_layer[layer_key] = {
                "drawing_length_mm": 0.0,
                "pen_up_travel_mm": 0.0,
                "num_lifts": 0,
                "num_short_segments": 0,
                "num_strokes": 0,
            }

        length = _polyline_length(stroke.polyline)
        short_segs = _count_short_segments(stroke.polyline, short_segment_threshold_mm)

        if stroke.pen_up:
            per_layer[layer_key]["pen_up_travel_mm"] += length
            total["pen_up_travel_mm"] += length
            per_layer[layer_key]["num_lifts"] += 1
            total["num_lifts"] += 1
        else:
            per_layer[layer_key]["drawing_length_mm"] += length
            total["drawing_length_mm"] += length
            per_layer[layer_key]["num_strokes"] += 1
            total["num_strokes"] += 1

        per_layer[layer_key]["num_short_segments"] += short_segs
        total["num_short_segments"] += short_segs

    return {"per_layer": per_layer, "total": total}


def compute_layer_coverage(
    strokes: Sequence[PenStroke],
    paper_width_mm: float,
    paper_height_mm: float,
    dpi_px_per_mm: float = 96 / 25.4,
) -> CoverageResult:
    """Rasterise each layer and report the share of the paper it inks.

    Parameters
    ----------
    strokes : Sequence[PenStroke]
        Strokes to rasterise. Only pen-down strokes add ink.
    paper_width_mm : float
        Paper width in millimetres.
    paper_height_mm : float
        Paper height in millimetres.
    dpi_px_per_mm : float, optional
        Rasterisation resolution in pixels per millimetre. Default is 96 DPI.

    Returns
    -------
    CoverageResult
        Percentage of the full paper inked by each layer (keyed by stroke
        colour) and the union percentage inked by any layer.

    Notes
    -----
    Layers are grouped by stroke colour, as in ``compute_machine_cost``. Each
    layer is drawn on its own image at the same resolution and pen width as
    ``simulate_plot``, then inked pixels are counted against the whole page,
    not the image placement. Per-layer percentages may overlap, so they do not
    add up to the total; pen-up travel moves never add ink.
    """
    width_px = max(1, round(paper_width_mm * dpi_px_per_mm))
    height_px = max(1, round(paper_height_mm * dpi_px_per_mm))
    area_px = width_px * height_px

    by_layer: dict[str, list[PenStroke]] = {}
    for stroke in strokes:
        if not stroke.pen_up:
            by_layer.setdefault(stroke.color, []).append(stroke)

    union = np.zeros((height_px, width_px), dtype=bool)
    per_layer: dict[str, float] = {}
    for color, layer_strokes in by_layer.items():
        mask = Image.new("L", (width_px, height_px), 0)
        draw = ImageDraw.Draw(mask)
        for stroke in layer_strokes:
            coords_px = [(x * dpi_px_per_mm, y * dpi_px_per_mm) for x, y in stroke.polyline]
            stroke_width_px = max(1, round(stroke.width_mm * dpi_px_per_mm))
            draw.line(coords_px, fill=255, width=stroke_width_px, joint="curve")
        ink = np.asarray(mask) > 0
        per_layer[color] = 100.0 * float(np.count_nonzero(ink)) / area_px
        union |= ink

    total = 100.0 * float(np.count_nonzero(union)) / area_px
    return CoverageResult(per_layer=per_layer, total=total)


def simulate_plot(
    strokes: Sequence[PenStroke],
    paper_width_mm: float,
    paper_height_mm: float,
    paper_color: str = "#FFFFFF",
    dpi_px_per_mm: float = 96 / 25.4,
) -> Image.Image:
    """Simulate a pen plot by rendering strokes to a PIL Image.

    Parameters
    ----------
    strokes : Sequence[PenStroke]
        List of pen strokes to render. Only pen-down strokes are drawn.
    paper_width_mm : float
        Paper width in millimetres.
    paper_height_mm : float
        Paper height in millimetres.
    paper_color : str, optional
        Background color as hex string or named CSS color. Default "#FFFFFF".
    dpi_px_per_mm : float, optional
        Pixels per millimetre for the output image.
        Default is 96 DPI = 96/25.4 ≈ 3.7795 px/mm.

    Returns
    -------
    PIL.Image.Image
        Simulated plot as a PIL Image in RGB mode.

    Notes
    -----
    - Pen-up strokes are not rendered (they represent travel moves).
    - Stroke width is converted from mm to pixels using dpi_px_per_mm.
    - Coordinates are in mm with (0, 0) at top-left of paper.
    """
    width_px = max(1, round(paper_width_mm * dpi_px_per_mm))
    height_px = max(1, round(paper_height_mm * dpi_px_per_mm))

    # Create image with paper background
    img = Image.new("RGB", (width_px, height_px), paper_color)
    draw = ImageDraw.Draw(img)

    for stroke in strokes:
        if stroke.pen_up:
            continue  # Skip pen-up travel moves

        if len(stroke.polyline) < 2:
            continue

        # Convert polyline from mm to pixels
        coords_px = [(x * dpi_px_per_mm, y * dpi_px_per_mm) for x, y in stroke.polyline]

        # Convert stroke width from mm to pixels (PIL requires integer width)
        stroke_width_px = max(1, round(stroke.width_mm * dpi_px_per_mm))

        # Draw the polyline as connected line segments
        draw.line(
            coords_px,
            fill=stroke.color,
            width=stroke_width_px,
            joint="curve",
        )

    return img


__all__ = [
    "CoverageResult",
    "PenStroke",
    "compute_layer_coverage",
    "compute_machine_cost",
    "simulate_plot",
]
