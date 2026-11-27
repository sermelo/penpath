"""Library-only contour tracing for thresholded or posterised images."""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Literal

import numpy as np
from pydantic import BaseModel, Field
from shapely import LineString
from skimage.measure import find_contours

if TYPE_CHECKING:
    from PIL import Image

TurnPolicy = Literal["black", "white", "left", "right", "minority", "majority", "random"]
_Connectivity = Literal["low", "high"]

# Each potrace-style turn policy maps to skimage's two contour knobs. "high"
# connectivity joins diagonally touching pixels of that colour; orientation
# 'high' winds counter-clockwise around the dark (high-valued) mask.
_TURN_PARAMETERS: dict[str, tuple[_Connectivity, _Connectivity]] = {
    "black": ("high", "high"),
    "white": ("low", "low"),
    "left": ("low", "high"),
    "right": ("high", "low"),
    "minority": ("high", "high"),
    "majority": ("low", "low"),
}


class ContourSettings(BaseModel):
    """Settings for potrace-style contour tracing.

    Parameters
    ----------
    threshold : int
        Base contour level on the 0 - 255 greyscale; darker pixels are traced.
    levels : int
        Number of levels (1 - 8): level 1 is ``threshold``, the others use
        ``np.linspace(threshold, 255, levels, endpoint=False)`` for lighter tones.
    turn_policy : Literal
        Ambiguous-corner side: ``black``, ``white``, ``left``, ``right``,
        ``minority`` (like black), ``majority`` (like white) or seeded
        ``random``. Maps to ``find_contours``' connectivity and orientation.
    turd_size : int
        Minimum enclosed area in square pixels (0 - 10000); smaller specks go.
    alpha_max : float
        Tangent of the smallest turn kept sharp while smoothing (0 - 1.3334).
    opticurve : bool
        Enable corner-preserving smoothing; false keeps the RDP polygon.
    smoothing : float
        Smoothing strength when enabled (0 - 1); zero is a no-op.
    simplify_tolerance : float
        RDP tolerance in pixels (0 - 10), applied before smoothing.
    seed : int | None
        Only affects ``random``; equal seeds give equal strokes, ``None`` is 0.
    """

    threshold: int = Field(default=128, ge=0, le=255)
    levels: int = Field(default=1, ge=1, le=8)
    turn_policy: TurnPolicy = "minority"
    turd_size: int = Field(default=20, ge=0, le=10000)
    alpha_max: float = Field(default=1.0, ge=0.0, le=1.3334)
    opticurve: bool = True
    smoothing: float = Field(default=0.5, ge=0.0, le=1.0)
    simplify_tolerance: float = Field(default=0.75, ge=0.0, le=10.0)
    seed: int | None = None


def _contour_levels(settings: ContourSettings) -> list[float]:
    """Return the contour levels in ascending order."""
    if settings.levels == 1:
        return [float(settings.threshold)]
    return [
        float(level)
        for level in np.linspace(settings.threshold, 255, settings.levels, endpoint=False)
    ]


def _turn_parameters(settings: ContourSettings) -> tuple[_Connectivity, _Connectivity]:
    """Map the turn policy to skimage's connectivity and orientation."""
    if settings.turn_policy == "random":
        rng = random.Random(0 if settings.seed is None else settings.seed)
        return ("high", "high") if rng.random() < 0.5 else ("low", "low")
    return _TURN_PARAMETERS[settings.turn_policy]


def _enclosed_area(coords: list[tuple[float, float]]) -> float:
    """Compute a contour's enclosed area with the shoelace formula."""
    pairs = zip(coords, coords[1:] + coords[:1], strict=True)
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in pairs)) / 2.0


def _smooth_coords(
    coords: list[tuple[float, float]],
    closed: bool,
    settings: ContourSettings,
) -> list[tuple[float, float]]:
    """Average non-corner vertices while keeping sharp corners in place."""
    ring = coords[:-1] if closed else coords
    if len(ring) < 3:
        return coords

    corner_angle = math.atan(settings.alpha_max)
    strength = settings.smoothing
    smoothed: list[tuple[float, float]] = []
    for index, (x, y) in enumerate(ring):
        if not closed and index in (0, len(ring) - 1):
            smoothed.append((x, y))
            continue
        previous = ring[index - 1]
        following = ring[(index + 1) % len(ring)]
        incoming = (x - previous[0], y - previous[1])
        outgoing = (following[0] - x, following[1] - y)
        incoming_length = math.hypot(*incoming)
        outgoing_length = math.hypot(*outgoing)
        if incoming_length <= 0.0 or outgoing_length <= 0.0:
            smoothed.append((x, y))
            continue
        cosine = (incoming[0] * outgoing[0] + incoming[1] * outgoing[1]) / (
            incoming_length * outgoing_length
        )
        angle = math.acos(max(-1.0, min(1.0, cosine)))
        if angle >= corner_angle:
            smoothed.append((x, y))
            continue
        smoothed.append(
            (
                (1.0 - strength) * x + strength * (previous[0] + following[0]) / 2.0,
                (1.0 - strength) * y + strength * (previous[1] + following[1]) / 2.0,
            )
        )

    deduplicated = [smoothed[0]]
    for point in smoothed[1:]:
        if point != deduplicated[-1]:
            deduplicated.append(point)
    if closed and len(deduplicated) < 3:
        return coords
    if closed and deduplicated[-1] != deduplicated[0]:
        deduplicated.append(deduplicated[0])
    return deduplicated


def contour_strokes(image: Image.Image, settings: ContourSettings) -> list[LineString]:
    """Turn a thresholded or posterised image into clean contour strokes.

    For each ascending level the greyscale image is thresholded into a dark
    mask, padded with background so contours close, traced with
    ``find_contours``, shifted into image coordinates, clamped to the image
    and filtered by shoelace area. Shapely RDP simplification and optional
    corner-preserving smoothing produce the strokes; closed contours stay
    closed and empty, invalid or zero-length results are dropped. Output
    order is level order then ``find_contours`` order. It is registered as
    the ``contour`` PFM, so the CLI can select it with ``--pfm contour``.

    Parameters
    ----------
    image : PIL.Image.Image
        Input image in any mode (converted to greyscale).
    settings : ContourSettings
        Threshold, turn policy, cleaning and smoothing configuration.

    Returns
    -------
    list[LineString]
        Strokes in image pixel coordinates (origin top-left); blank light
        images return an empty list.
    """
    gray = np.asarray(image.convert("L"), dtype=np.float64)
    height, width = gray.shape
    if height == 0 or width == 0:
        return []

    fully_connected, positive_orientation = _turn_parameters(settings)
    max_x = float(width - 1)
    max_y = float(height - 1)
    strokes: list[LineString] = []

    for level in _contour_levels(settings):
        padded = np.pad(gray < level, 1, constant_values=False)
        contours = find_contours(
            padded,
            0.5,
            fully_connected=fully_connected,
            positive_orientation=positive_orientation,
        )  # type: ignore[no-untyped-call]
        for contour in contours:
            raw = [(float(column - 1), float(row - 1)) for row, column in contour]
            if len(raw) < 3 or _enclosed_area(raw) < settings.turd_size:
                continue
            coords = [(min(max(x, 0.0), max_x), min(max(y, 0.0), max_y)) for x, y in raw]
            closed = coords[0] == coords[-1]
            simplified: list[tuple[float, float]] = [
                (float(point[0]), float(point[1]))
                for point in LineString(coords)
                .simplify(settings.simplify_tolerance, preserve_topology=True)
                .coords
            ]
            if len(simplified) < 2:
                continue
            if closed and simplified[0] != simplified[-1]:
                simplified.append(simplified[0])
            if settings.opticurve and settings.smoothing > 0.0:
                simplified = _smooth_coords(simplified, closed, settings)
            stroke = LineString(simplified)
            if stroke.is_empty or not stroke.is_valid or stroke.length <= 0.0:
                continue
            strokes.append(stroke)

    return strokes


__all__ = ["ContourSettings", "contour_strokes"]
