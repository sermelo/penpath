"""Interpret the G-code subset penpath emits as strokes for previewing."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from penpath.core.output.gcode import page_origin_mm
from penpath.core.profiles import MachineProfile
from penpath.core.simulation import PenStroke

type PenStyle = tuple[str, float]

HEADER_RE: Final = re.compile(r"penpath\s+gcode\s*(.*)", re.IGNORECASE)
FIELD_RE: Final = re.compile(r"([a-z_]+)=(\S+)", re.IGNORECASE)
LAYER_RE: Final = re.compile(r"\blayer\b.*\bpen=(.+)$", re.IGNORECASE)
COORDINATE_RE: Final = re.compile(r"^([XYZ])([-+]?(?:\d*\.\d+|\d+\.?))", re.IGNORECASE)
PAGE_RE: Final = re.compile(
    r"^([-+]?(?:\d*\.\d+|\d+\.?))\s*x\s*([-+]?(?:\d*\.\d+|\d+\.?))$", re.IGNORECASE
)
DEFAULT_PEN_STYLE: Final[PenStyle] = ("#000000", 0.3)
Z_EPSILON_MM: Final = 1e-6


class GcodePreviewError(ValueError):
    """Raised when G-code cannot be interpreted as a pen plot."""


@dataclass(frozen=True, slots=True)
class GcodeHeader:
    """Profile name and Z heights a penpath header declares."""

    profile: str | None = None
    page: tuple[float, float] | None = None
    z_up: float | None = None
    z_touch: float | None = None
    z_down: float | None = None


@dataclass(frozen=True, slots=True)
class _Move:
    x: float | None = None
    y: float | None = None
    z: float | None = None
    pen: str | None = None


def _number(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def _page_size(text: str) -> tuple[float, float] | None:
    match = PAGE_RE.match(text)
    if match is None:
        return None
    width = _number(match.group(1))
    height = _number(match.group(2))
    if width is None or height is None or width <= 0.0 or height <= 0.0:
        return None
    return (width, height)


def parse_gcode_header(text: str) -> GcodeHeader:
    """Return the penpath header fields, empty when the file has no header."""
    for line in text.splitlines():
        if not line.lstrip().startswith(";"):
            continue
        match = HEADER_RE.search(line)
        if match is None:
            continue
        fields = {key.lower(): value for key, value in FIELD_RE.findall(match.group(1))}
        return GcodeHeader(
            profile=fields.get("profile"),
            page=_page_size(fields["page"]) if "page" in fields else None,
            z_up=_number(fields["z_up"]) if "z_up" in fields else None,
            z_touch=_number(fields["z_touch"]) if "z_touch" in fields else None,
            z_down=_number(fields["z_down"]) if "z_down" in fields else None,
        )
    return GcodeHeader()


def _moves(text: str) -> list[_Move]:
    moves: list[_Move] = []
    for raw_line in text.splitlines():
        layer = LAYER_RE.search(raw_line)
        if layer is not None:
            moves.append(_Move(pen=layer.group(1).strip()))
            continue
        line = raw_line.split(";", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        command = parts[0].upper()
        if command in ("G2", "G02", "G3", "G03"):
            raise GcodePreviewError(f"arcs ({command}) are not supported by penpath preview")
        if command not in ("G0", "G1"):
            continue
        values: dict[str, float] = {}
        for token in parts[1:]:
            coordinate = COORDINATE_RE.match(token)
            if coordinate is None:
                continue
            number = _number(coordinate.group(2))
            if number is None:
                raise GcodePreviewError(f"invalid G-code coordinate {token!r}")
            values[coordinate.group(1).upper()] = number
        if values:
            moves.append(_Move(x=values.get("X"), y=values.get("Y"), z=values.get("Z")))
    return moves


def _to_page(
    point: tuple[float, float],
    page_size_mm: tuple[float, float],
    profile: MachineProfile | None,
) -> tuple[float, float]:
    offset = profile.bed.pen_offset_mm if profile is not None else (0.0, 0.0)
    origin = page_origin_mm(profile, page_size_mm) if profile is not None else (0.0, 0.0)
    x = point[0] + offset[0] - origin[0]
    y = point[1] + offset[1] - origin[1]
    if profile is None or profile.bed.invert_y:
        return (x, page_size_mm[1] - y)
    return (x, y)


def gcode_to_strokes(
    text: str,
    paper_size_mm: tuple[float, float],
    profile: MachineProfile | None = None,
    pen_styles: Mapping[str, PenStyle] | None = None,
    pen_filter: str | None = None,
) -> list[PenStroke]:
    """Turn penpath G-code into pen-down strokes in preview page millimetres.

    ``z_touch`` from the header decides when the pen is down; a header without
    it uses ``z_down`` and a foreign file uses its lowest Z. The header's ``page``
    overrides ``paper_size_mm`` so an SVG page that differs from the bed inverts
    around the same height the emitter used. ``pen_styles`` maps pen names to
    ``(color, width_mm)``; unknown pens render black at 0.3 mm. Arcs and
    malformed coordinates raise :class:`GcodePreviewError`.
    """
    header = parse_gcode_header(text)
    page_size_mm = header.page or paper_size_mm
    moves = _moves(text)
    if header.z_touch is not None:
        touch_z = header.z_touch
    elif header.z_down is not None:
        touch_z = header.z_down
    else:
        z_values = [move.z for move in moves if move.z is not None]
        touch_z = min(z_values) if z_values else 0.0

    styles = pen_styles or {}
    strokes: list[PenStroke] = []
    position = (0.0, 0.0)
    z = header.z_up if header.z_up is not None else touch_z
    pen = "black"
    points: list[tuple[float, float]] = []

    def finish() -> None:
        if len(points) >= 2 and (pen_filter is None or pen == pen_filter):
            color, width_mm = styles.get(pen, DEFAULT_PEN_STYLE)
            strokes.append(PenStroke(list(points), width_mm, color))
        points.clear()

    def draw_part(
        start: tuple[float, float], end: tuple[float, float], z_start: float, z_end: float
    ) -> None:
        """Append only the part of a move spent at or below the touch height.

        A ramped stroke carries Z on its G1 moves, so the pen crosses the paper
        inside a move: the lead-in and lead-out above ``z_touch`` are not ink.
        """
        down_start = z_start <= touch_z + Z_EPSILON_MM
        down_end = z_end <= touch_z + Z_EPSILON_MM
        if down_start and down_end:
            first, last = start, end
        elif down_start != down_end and z_start != z_end:
            ratio = min(1.0, max(0.0, (touch_z - z_start) / (z_end - z_start)))
            crossing = (
                start[0] + (end[0] - start[0]) * ratio,
                start[1] + (end[1] - start[1]) * ratio,
            )
            first, last = (start, crossing) if down_start else (crossing, end)
        else:
            return
        if math.dist(first, last) <= Z_EPSILON_MM:
            if not points:
                points.append(_to_page(first, page_size_mm, profile))
            return
        if not points:
            points.append(_to_page(first, page_size_mm, profile))
        points.append(_to_page(last, page_size_mm, profile))

    for move in moves:
        if move.pen is not None:
            finish()
            pen = move.pen
            z = header.z_up if header.z_up is not None else touch_z + 1.0
            continue
        if move.x is None and move.y is None:
            if move.z is not None:
                finish()
                z = move.z
            continue
        start = position
        position = (
            move.x if move.x is not None else position[0],
            move.y if move.y is not None else position[1],
        )
        z_end = move.z if move.z is not None else z
        draw_part(start, position, z, z_end)
        z = z_end
    finish()
    return strokes


__all__ = [
    "GcodeHeader",
    "GcodePreviewError",
    "gcode_to_strokes",
    "parse_gcode_header",
]
