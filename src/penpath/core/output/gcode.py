"""Turn layers of polylines and a machine profile into G-code text.

The module holds the shape of the language (G0/G1/G21/G90 syntax and the pen
up/down state machine) and no machine number: bed geometry, feeds, Z heights and
verbatim code blocks all come from the profile. The SVG page size is passed by
the caller because paper size stays in the reviewed SVG, not in the profile.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Final, Literal

from penpath.core.profiles import MachineProfile

type Coordinate = tuple[float, float]
type Polyline = Sequence[Coordinate]
type Bounds = tuple[Coordinate, Coordinate]
type PlacementName = Literal[
    "center", "front-right", "front-left", "back-right", "back-left", "origin"
]

COORDINATE_DECIMALS: Final = 3
SECONDS_PER_MINUTE: Final = 60
FIT_TOLERANCE_MM: Final = 0.05
PLACEMENT_EPSILON_MM: Final = 1e-6
DEFAULT_FRAME_MARGIN_MM: Final = 2.0
FRAME_OVERLAP_MM: Final = 2.0
FRAME_PAUSE_MESSAGE: Final = "Frame drawn: check paper position, press knob to plot"
PLACEMENT_NAMES: Final = (
    "center",
    "front-right",
    "front-left",
    "back-right",
    "back-left",
    "origin",
)


class GcodeError(ValueError):
    """Base class for G-code emission errors."""


class PointOutsideBedError(GcodeError):
    """Raised when a point cannot be reached by the pen on this machine."""


@dataclass(frozen=True, slots=True)
class GcodeLayer:
    """One pen layer of drawn polylines, in millimetres on the SVG page.

    Parameters
    ----------
    pen : str
        Layer label, which is the pen name used in the layer comment.
    polylines : Sequence[Sequence[tuple[float, float]]]
        Points in SVG millimetres, origin top-left, Y growing down.
    """

    pen: str
    polylines: Sequence[Polyline]


@dataclass(frozen=True, slots=True)
class PagePlacement:
    """Where a page sits on the machine bed, in pen-space millimetres.

    Parameters
    ----------
    place : PlacementName
        Effective placement name: one of the five named positions relative to
        the usable area, or ``origin`` for a fixed or explicit origin.
    origin_mm : Coordinate
        Final pen-space lower-left corner of the page, after clamping.
    requested_origin_mm : Coordinate
        Lower-left corner asked for before clamping to the usable area.
    shifted : bool
        Whether clamping moved the requested origin beyond float noise.
    """

    place: PlacementName
    origin_mm: Coordinate
    requested_origin_mm: Coordinate
    shifted: bool


@dataclass(frozen=True, slots=True)
class FitResult:
    """The outcome of fitting a drawing to a machine's drawable area.

    Parameters
    ----------
    layers : Sequence[GcodeLayer]
        Fitted layers in SVG page millimetres, ready for ``build_gcode``. The
        input sequence is returned as-is when nothing changed.
    scale : float
        Uniform scale applied in pen space, never above 1.
    offset_mm : tuple[float, float]
        Pen-space translation applied after scaling, in millimetres.
    overshoot_mm : tuple[float, float]
        Per-axis distance the original drawing exceeded the usable area, in mm.
    changed : bool
        Whether the layers were transformed.
    """

    layers: Sequence[GcodeLayer]
    scale: float
    offset_mm: Coordinate
    overshoot_mm: Coordinate
    changed: bool
    frame: FrameSpec | None = None


@dataclass(frozen=True, slots=True)
class FrameSpec:
    """An optional closed rectangle plotted before the first drawing stroke.

    Parameters
    ----------
    margin_mm : float
        Distance from each page edge to the frame, in SVG page millimetres.
        ``0`` puts the frame on the page edge.
    pen : str | None
        Pen name for the frame. ``None`` means the first used layer's pen.
    pause : bool
        Whether to pause with an ``M0`` after the frame is drawn.
    polyline : Polyline | None
        Explicit frame points in SVG page millimetres. Set by the fit step when
        the frame had to move or scale with the drawing; when omitted, the points
        come from :func:`frame_polyline` and ``margin_mm``.
    """

    margin_mm: float = DEFAULT_FRAME_MARGIN_MM
    pen: str | None = None
    pause: bool = False
    polyline: Polyline | None = None

    def points(self, page_size_mm: Coordinate) -> Polyline:
        """Return the frame points for a page, using the fitted points if set."""
        if self.polyline is not None:
            return self.polyline
        return frame_polyline(page_size_mm, self.margin_mm)


def frame_polyline(
    page_size_mm: Coordinate, margin_mm: float = DEFAULT_FRAME_MARGIN_MM
) -> list[Coordinate]:
    """Return a closed frame around a page, in SVG page millimetres.

    The rectangle runs from ``(-m, -m)`` to ``(W + m, H + m)`` for a ``W x H``
    page. It starts ``FRAME_OVERLAP_MM`` along the closing left edge, reaches the
    top-left corner, goes clockwise around the page and returns to that corner,
    so the last segment inks the same 2 mm of the closing edge as the first. The
    overlap is clamped to the shorter side of the frame for very small pages.

    Parameters
    ----------
    page_size_mm : Coordinate
        SVG page width and height in millimetres.
    margin_mm : float
        Distance from the page edge, by default 2 mm; ``0`` is the page edge.

    Returns
    -------
    list[Coordinate]
        The closed polyline, with no point outside the expanded page rectangle.

    Raises
    ------
    GcodeError
        ``margin_mm`` is negative.
    """
    if margin_mm < 0:
        raise GcodeError(f"frame margin must be non-negative, got {margin_mm}")
    width, height = page_size_mm
    left, top = -margin_mm, -margin_mm
    right, bottom = width + margin_mm, height + margin_mm
    overlap = min(FRAME_OVERLAP_MM, right - left, bottom - top)
    return [
        (left, top + overlap),
        (left, top),
        (right, top),
        (right, bottom),
        (left, bottom),
        (left, top),
    ]


def _format_mm(value: float) -> str:
    """Format a millimetre value at the emitter's fixed precision."""
    return f"{value:.{COORDINATE_DECIMALS}f}"


def lead_in_mm(profile: MachineProfile) -> float | None:
    """Return the ramp lead-in distance, or ``None`` when the profile has no ramp.

    The lead-in is the distance before a stroke's first point over which the pen
    descends from ``z_hover`` to ``z_touch`` at the same rate as the ramp from
    ``z_touch`` to ``z_down`` (D7). The profile validator guarantees touch is
    above down and hover is at or above touch whenever a ramp is declared.
    """
    pen = profile.pen
    if not pen.ramp_mm or pen.z_touch is None or pen.z_hover is None:
        return None
    return pen.ramp_mm * (pen.z_hover - pen.z_touch) / (pen.z_touch - pen.z_down)


def _drawable_area(profile: MachineProfile) -> Bounds:
    """Return the pen-space rectangle the pen can reach, clipped to the bed."""
    bed_width, bed_height = profile.bed.size_mm
    offset_x, offset_y = profile.bed.pen_offset_mm
    nozzle_range = profile.bed.nozzle_range_mm
    if nozzle_range is None:
        return (0.0, 0.0), (bed_width, bed_height)
    (xmin, xmax), (ymin, ymax) = nozzle_range
    return (
        (max(0.0, xmin + offset_x), max(0.0, ymin + offset_y)),
        (min(bed_width, xmax + offset_x), min(bed_height, ymax + offset_y)),
    )


def usable_area(profile: MachineProfile) -> Bounds:
    """Return the drawable rectangle inset by the four bed margins.

    The bounds are in pen space, with ``bed.margins_mm`` in
    ``(top, right, bottom, left)`` order: top reduces maximum Y, right reduces
    maximum X, bottom increases minimum Y and left increases minimum X. The
    unreduced rectangle stays available from :func:`_drawable_area`.
    """
    (xmin, ymin), (xmax, ymax) = _drawable_area(profile)
    top, right, bottom, left = profile.bed.margins_mm
    return ((xmin + left, ymin + bottom), (xmax - right, ymax - top))


def place_page(
    profile: MachineProfile,
    page_size_mm: Coordinate,
    *,
    place: PlacementName | None = None,
    at: Coordinate | None = None,
    fit: bool = True,
) -> PagePlacement:
    """Place a page in the profile's usable area, in pen-space millimetres.

    When neither ``place`` nor ``at`` is given, the profile's own placement is
    used verbatim, so profiles with a fixed or reachable-corner page keep the
    coordinates they had before placement was configurable. Explicit requests
    are clamped into the usable area (the drawable area minus the per-side
    ``bed.margin_mm`` values).

    Parameters
    ----------
    profile : MachineProfile
        Validated machine profile; the only source of bed and margin values.
    page_size_mm : Coordinate
        SVG page width and height in millimetres.
    place : PlacementName | None
        Effective placement name. When omitted, the profile decides: ``fixed``
        uses ``bed.page.origin_mm`` as ``origin``, and ``reachable_corner`` uses
        ``front-right``. The five named positions other than ``origin`` are
        relative to the usable area; ``origin`` puts the page lower-left at
        pen-space (0, 0) unless the profile is fixed.
    at : Coordinate | None
        Explicit pen-space page lower-left; mutually exclusive with ``place``
        and reported with the effective name ``origin``.
    fit : bool
        Clamp a page that falls outside the usable area. With ``False``, raise
        :class:`PointOutsideBedError` instead.

    Returns
    -------
    PagePlacement
        The effective name, requested origin, final origin and whether it moved.

    Raises
    ------
    GcodeError
        Both ``place`` and ``at`` were given, or ``place`` is not a known name.
    PointOutsideBedError
        ``fit=False`` and the requested page falls outside the usable area.
    """
    if place is not None and at is not None:
        raise GcodeError("pass either place=... or at=(x, y) to place a page, not both")
    if place is not None and place not in PLACEMENT_NAMES:
        raise GcodeError(
            f"Unknown page placement {place!r}; choose one of {', '.join(PLACEMENT_NAMES)}"
        )

    page_width, page_height = page_size_mm
    (x_lo, y_lo), (x_hi, y_hi) = usable_area(profile)
    if at is not None:
        effective: PlacementName = "origin"
        requested = (at[0], at[1])
    else:
        effective = (
            place
            if place is not None
            else ("origin" if profile.bed.page.placement == "fixed" else "front-right")
        )
        if effective == "origin":
            requested = (0.0, 0.0) if place is not None else profile.bed.page.origin_mm
        elif effective == "center":
            requested = (
                x_lo + (x_hi - x_lo - page_width) / 2,
                y_lo + (y_hi - y_lo - page_height) / 2,
            )
        elif effective == "front-right":
            requested = (x_hi - page_width, y_lo)
        elif effective == "front-left":
            requested = (x_lo, y_lo)
        elif effective == "back-right":
            requested = (x_hi - page_width, y_hi - page_height)
        else:
            requested = (x_lo, y_hi - page_height)

    if place is None and at is None:
        return PagePlacement(effective, requested, requested, False)

    raw_shift_x = _shortest_shift(requested[0], requested[0] + page_width, x_lo, x_hi)
    raw_shift_y = _shortest_shift(requested[1], requested[1] + page_height, y_lo, y_hi)
    shifted_x = abs(raw_shift_x) > PLACEMENT_EPSILON_MM
    shifted_y = abs(raw_shift_y) > PLACEMENT_EPSILON_MM
    shift_x = raw_shift_x if shifted_x else 0.0
    shift_y = raw_shift_y if shifted_y else 0.0
    origin = (requested[0] + shift_x, requested[1] + shift_y)
    shifted = shifted_x or shifted_y
    if not fit and shifted:
        raise PointOutsideBedError(
            f"requested page origin (x={_format_mm(requested[0])}, "
            f"y={_format_mm(requested[1])}) mm puts the page outside the usable area "
            f"X {_format_mm(x_lo)}..{_format_mm(x_hi)}, "
            f"Y {_format_mm(y_lo)}..{_format_mm(y_hi)} mm; "
            f"nearest origin is (x={_format_mm(origin[0])}, y={_format_mm(origin[1])}); "
            "use --fit (the default) or choose a different placement"
        )
    return PagePlacement(effective, origin, requested, shifted)


def page_origin_mm(
    profile: MachineProfile,
    page_size_mm: Coordinate,
    *,
    placement: PagePlacement | None = None,
) -> Coordinate:
    """Return the final pen-space page origin for a profile and source page size.

    An explicit ``placement`` supplies the origin the emitter used; otherwise
    it is computed from the profile with :func:`place_page`. The emitter and the
    preview both use this helper, so ``reachable_corner`` inverts with the same
    usable-area corner origin the emitter used.
    """
    if placement is not None:
        return placement.origin_mm
    return place_page(profile, page_size_mm).origin_mm


def _profile_values(profile: MachineProfile) -> dict[str, str]:
    """Return the scalars available to placeholders in verbatim code blocks."""
    pen = profile.pen
    ramp = pen.ramp_mm
    z_touch = pen.z_touch
    z_hover = pen.z_hover
    lead = lead_in_mm(profile)
    lead_in = _format_mm(lead) if lead is not None else ""
    return {
        "z_up": _format_mm(pen.z_up),
        "z_down": _format_mm(pen.z_down),
        "z_touch": _format_mm(z_touch) if z_touch is not None else "",
        "z_hover": _format_mm(z_hover) if z_hover is not None else "",
        "ramp_mm": _format_mm(ramp) if ramp is not None else "",
        "lead_in_mm": lead_in,
        "feed_travel": f"{profile.feed.travel_mm_s * SECONDS_PER_MINUTE:.0f}",
        "feed_draw": f"{profile.feed.draw_mm_s * SECONDS_PER_MINUTE:.0f}",
        "feed_z": f"{profile.feed.effective_z_mm_s * SECONDS_PER_MINUTE:.0f}",
    }


def _block(text: str, values: dict[str, str]) -> list[str]:
    """Fill placeholders in a verbatim code block and split it into lines."""
    if not text.strip():
        return []
    return [line.format_map(values) for line in text.strip("\n").splitlines()]


def _header(
    profile: MachineProfile,
    page_size_mm: Coordinate,
    placement: PagePlacement,
) -> str:
    """Build the header comment carrying page placement, usable area and Z semantics."""
    origin = placement.origin_mm
    (usable_xmin, usable_ymin), (usable_xmax, usable_ymax) = usable_area(profile)
    fields = [
        f"profile={profile.name}",
        f"page={_format_mm(page_size_mm[0])}x{_format_mm(page_size_mm[1])}",
        f"place={placement.place}",
        f"page_origin={_format_mm(origin[0])}x{_format_mm(origin[1])}",
        f"usable_x={_format_mm(usable_xmin)}..{_format_mm(usable_xmax)}",
        f"usable_y={_format_mm(usable_ymin)}..{_format_mm(usable_ymax)}",
        f"z_up={_format_mm(profile.pen.z_up)}",
    ]
    if profile.pen.z_touch is not None:
        fields.append(f"z_touch={_format_mm(profile.pen.z_touch)}")
    fields.append(f"z_down={_format_mm(profile.pen.z_down)}")
    return f"{profile.gcode.comment_prefix} penpath gcode " + " ".join(fields)


def _pen_change_needed(profile: MachineProfile, index: int) -> bool:
    """Return whether a pen change belongs before this used layer."""
    mode = profile.pen_change.mode
    return mode == "each" or (mode == "between" and index > 1)


def _z_height(value: str | float, profile: MachineProfile) -> float:
    """Resolve a pen-change Z step to a millimetre height from the profile."""
    pen = profile.pen
    if isinstance(value, str):
        if value == "up":
            return pen.z_up
        if value == "down":
            return pen.z_down
        if value == "touch":
            if pen.z_touch is None:
                raise GcodeError("pen_change step z=touch needs pen.z_touch in the profile")
            return pen.z_touch
        if value == "hover":
            if pen.z_hover is None:
                raise GcodeError("pen_change step z=hover needs pen.z_hover in the profile")
            return pen.z_hover
        raise GcodeError(f"Unknown pen_change Z height {value!r}")
    return value


def _xy_point(value: str | tuple[float, float], profile: MachineProfile) -> Coordinate:
    """Resolve a pen-change XY step to a point in pen space."""
    if isinstance(value, str):
        if value == "touch":
            point = profile.pen.touch_xy_mm
            if point is None:
                raise GcodeError("pen_change step xy=touch needs pen.touch_xy_mm in the profile")
            return point
        raise GcodeError(f"Unknown pen_change XY target {value!r}")
    return value


def _feed_clause(feed: str | None, values: dict[str, str]) -> str:
    """Return the feed suffix for a pen-change move, using G1 when it is set."""
    return "" if feed is None else f" F{values[f'feed_{feed}']}"


def _pen_change_lines(profile: MachineProfile, values: dict[str, str]) -> list[str]:
    """Render the ordered pen-change steps for one layer."""
    prefix = profile.gcode.comment_prefix
    lines = [f"{prefix} pen change"]
    offset_x, offset_y = profile.bed.pen_offset_mm
    for step in profile.pen_change.steps:
        if step.z is not None:
            command = "G1" if step.feed is not None else "G0"
            lines.append(
                f"{command} Z{_format_mm(_z_height(step.z, profile))}"
                f"{_feed_clause(step.feed, values)}"
            )
        elif step.xy is not None:
            x_pen, y_pen = _xy_point(step.xy, profile)
            command = "G1" if step.feed is not None else "G0"
            lines.append(
                f"{command} X{_format_mm(x_pen - offset_x)} Y{_format_mm(y_pen - offset_y)}"
                f"{_feed_clause(step.feed, values)}"
            )
        elif step.raw is not None:
            lines.extend(
                line
                for line in step.raw.format_map(values).strip("\n").splitlines()
                if line.strip()
            )
        elif step.message is not None:
            lines.append(f"M117 {step.message.format_map(values)}".rstrip())
        elif step.pause is not None:
            text = step.pause.format_map(values)
            lines.append(f"M0 {text}".rstrip() if text else "M0")
    return lines


def _check_pen_point(point: Coordinate, profile: MachineProfile, usable: Bounds) -> None:
    """Reject a pen-space point outside the profile's usable area.

    The fit tolerance absorbs float rounding at the edge; a point further out
    reports how far past each axis it lies and how the margins shaped the area.
    """
    (x_lo, y_lo), (x_hi, y_hi) = usable
    x_pen, y_pen = point
    if not (
        x_lo - FIT_TOLERANCE_MM <= x_pen <= x_hi + FIT_TOLERANCE_MM
        and y_lo - FIT_TOLERANCE_MM <= y_pen <= y_hi + FIT_TOLERANCE_MM
    ):
        x_past = max(0.0, x_lo - x_pen, x_pen - x_hi)
        y_past = max(0.0, y_lo - y_pen, y_pen - y_hi)
        top, right, bottom, left = profile.bed.margins_mm
        if len({top, right, bottom, left}) == 1:
            margin_note = f"a {_format_mm(top)} mm margin"
        else:
            margin_note = (
                f"margins top={_format_mm(top)} right={_format_mm(right)} "
                f"bottom={_format_mm(bottom)} left={_format_mm(left)} mm"
            )
        raise PointOutsideBedError(
            f"point (x={_format_mm(x_pen)}, y={_format_mm(y_pen)}) mm is outside "
            f"the usable area X {_format_mm(x_lo)}..{_format_mm(x_hi)}, "
            f"Y {_format_mm(y_lo)}..{_format_mm(y_hi)} mm "
            f"(drawable area minus {margin_note}); "
            f"overshoot x={_format_mm(x_past)} mm, y={_format_mm(y_past)} mm"
        )


def _svg_to_pen(
    point: Coordinate,
    page_height_mm: float,
    origin: Coordinate,
    profile: MachineProfile,
) -> Coordinate:
    """Map one SVG page point to pen space with the emitter's origin and Y flip."""
    x_svg, y_svg = point
    y_page = page_height_mm - y_svg if profile.bed.invert_y else y_svg
    return (origin[0] + x_svg, origin[1] + y_page)


def _pen_to_svg(
    point: Coordinate,
    page_height_mm: float,
    origin: Coordinate,
    profile: MachineProfile,
) -> Coordinate:
    """Invert :func:`_svg_to_pen` for a fitted pen-space point."""
    x_pen, y_pen = point
    y_page = y_pen - origin[1]
    if profile.bed.invert_y:
        y_page = page_height_mm - y_page
    return (x_pen - origin[0], y_page)


def _pen_points(
    polyline: Polyline,
    profile: MachineProfile,
    page_height_mm: float,
    origin: Coordinate,
    usable: Bounds,
) -> list[Coordinate]:
    """Map a page polyline to checked pen-space points."""
    result: list[Coordinate] = []
    for point in polyline:
        pen_point = _svg_to_pen(point, page_height_mm, origin, profile)
        _check_pen_point(pen_point, profile, usable)
        result.append(pen_point)
    return result


def _nozzle(point: Coordinate, profile: MachineProfile) -> Coordinate:
    """Convert one checked pen-space point to nozzle/machine space."""
    offset_x, offset_y = profile.bed.pen_offset_mm
    return (point[0] - offset_x, point[1] - offset_y)


def _is_tap(points: list[Coordinate]) -> bool:
    """Return whether a polyline stays at one point, so the pen only taps it."""
    return bool(points) and all(math.dist(point, points[0]) <= 1e-6 for point in points[1:])


def _ramped_path(
    points: list[Coordinate],
    profile: MachineProfile,
) -> list[tuple[Coordinate, float]]:
    """Return ``(pen point, Z)`` triples of one stroke's ramped landing and lift.

    Ported from the Aquila reference's ``ramped`` helper: a lead-in before the
    first point and a lead-out after the last, with Z falling linearly from
    ``z_hover`` to ``z_down`` over ``lead_in + ramp_mm`` and rising the same way
    at the end. Marks where Z reaches ``z_down`` are inserted so every emitted
    G1 interpolates a straight, correctly timed descent.
    """
    lead = lead_in_mm(profile)
    ramp = profile.pen.ramp_mm
    hover = profile.pen.z_hover
    if lead is None or ramp is None or hover is None:
        raise GcodeError("ramped landing needs pen.ramp_mm, pen.z_touch and pen.z_hover")
    down = profile.pen.z_down
    clean = [
        point
        for index, point in enumerate(points)
        if index == 0 or math.dist(point, points[index - 1]) > 1e-6
    ]
    if len(clean) < 2:
        return []

    def unit(a: Coordinate, b: Coordinate) -> Coordinate:
        distance = math.dist(a, b)
        return ((b[0] - a[0]) / distance, (b[1] - a[1]) / distance)

    u0 = unit(clean[0], clean[1])
    u1 = unit(clean[-2], clean[-1])
    path: list[Coordinate] = [
        (clean[0][0] - u0[0] * lead, clean[0][1] - u0[1] * lead),
        *clean,
        (clean[-1][0] + u1[0] * lead, clean[-1][1] + u1[1] * lead),
    ]
    cumulative = [0.0]
    for a, b in pairwise(path):
        cumulative.append(cumulative[-1] + math.dist(a, b))
    total = cumulative[-1]
    ramp_distance = min(lead + ramp, total / 2)

    def z_at(distance: float) -> float:
        fall = min(1.0, distance / ramp_distance, (total - distance) / ramp_distance)
        return hover - (hover - down) * fall

    result: list[tuple[Coordinate, float]] = []
    for index, (a, b) in enumerate(pairwise(path)):
        result.append((a, z_at(cumulative[index])))
        for mark in sorted({ramp_distance, total - ramp_distance}):
            if cumulative[index] < mark < cumulative[index + 1]:
                ratio = (mark - cumulative[index]) / (cumulative[index + 1] - cumulative[index])
                result.append(
                    (
                        (a[0] + (b[0] - a[0]) * ratio, a[1] + (b[1] - a[1]) * ratio),
                        z_at(mark),
                    )
                )
    result.append((path[-1], z_at(total)))
    return result


def _emit_stroke(
    polyline: Polyline,
    profile: MachineProfile,
    page_height_mm: float,
    origin: Coordinate,
    usable: Bounds,
    line_values: dict[str, str],
    feed_travel: str,
    feed_z: str,
    pen_is_down: bool,
) -> tuple[list[str], bool]:
    """Emit one stroke exactly as both frame and drawing strokes are plotted.

    A zero-length polyline is a tap: travel to its point, lower to ``z_touch``
    when the profile has one (otherwise ``z_down``), then raise again, with no
    G1 and no ramp lead-in or lead-out.
    """
    lines: list[str] = []
    pen_points = _pen_points(polyline, profile, page_height_mm, origin, usable)
    if pen_is_down:
        lines.append(f"G0 Z{_format_mm(profile.pen.z_up)}{feed_z}")
        pen_is_down = False
    if _is_tap(pen_points):
        x, y = _nozzle(pen_points[0], profile)
        touch = profile.pen.z_touch if profile.pen.z_touch is not None else profile.pen.z_down
        lines.append(f"G0 X{_format_mm(x)} Y{_format_mm(y)}{feed_travel}")
        lines.append(f"G0 Z{_format_mm(touch)}{feed_z}")
        lines.append(f"G0 Z{_format_mm(profile.pen.z_up)}{feed_z}")
        return lines, pen_is_down
    feed = f" F{line_values['feed_draw']}"
    lead = lead_in_mm(profile)
    if lead is not None:
        ramp_path = _ramped_path(pen_points, profile)
        if not ramp_path:
            return lines, pen_is_down
        for point, _ in ramp_path:
            _check_pen_point(point, profile, usable)
        first, first_z = ramp_path[0]
        first_x, first_y = _nozzle(first, profile)
        lines.append(f"G0 X{_format_mm(first_x)} Y{_format_mm(first_y)}{feed_travel}")
        lines.append(f"G0 Z{_format_mm(first_z)}{feed_z}")
        for point_index, (point, z) in enumerate(ramp_path[1:]):
            x, y = _nozzle(point, profile)
            suffix = feed if point_index == 0 else ""
            lines.append(f"G1 X{_format_mm(x)} Y{_format_mm(y)} Z{_format_mm(z)}{suffix}")
        lines.append(f"G0 Z{_format_mm(profile.pen.z_up)}{feed_z}")
    else:
        points = [_nozzle(point, profile) for point in pen_points]
        first_x, first_y = points[0]
        lines.append(f"G0 X{_format_mm(first_x)} Y{_format_mm(first_y)}{feed_travel}")
        lines.append(f"G0 Z{_format_mm(profile.pen.z_down)}{feed_z}")
        pen_is_down = True
        for point_index, point in enumerate(points[1:]):
            suffix = feed if point_index == 0 else ""
            lines.append(f"G1 X{_format_mm(point[0])} Y{_format_mm(point[1])}{suffix}")
    return lines, pen_is_down


def _shortest_shift(low: float, high: float, target_low: float, target_high: float) -> float:
    """Return the smallest translation placing an interval inside its target."""
    if low < target_low:
        return target_low - low
    if high > target_high:
        return target_high - high
    return 0.0


def _fit_pen_points(
    layers: Sequence[GcodeLayer],
    frame_points: Sequence[Coordinate],
    profile: MachineProfile,
    page_height: float,
    origin: Coordinate,
) -> list[Coordinate]:
    """Map the frame and every drawable stroke point to pen space."""
    points = [_svg_to_pen(point, page_height, origin, profile) for point in frame_points]
    points.extend(
        _svg_to_pen(point, page_height, origin, profile)
        for layer in layers
        for polyline in layer.polylines
        if len(polyline) >= 2
        for point in polyline
    )
    return points


def _fit_bounds(points: Sequence[Coordinate]) -> Bounds:
    """Return the lower and upper corners of a set of pen-space points."""
    return (
        (min(point[0] for point in points), min(point[1] for point in points)),
        (max(point[0] for point in points), max(point[1] for point in points)),
    )


def _fit_transform(
    bounds: Bounds,
    area: Bounds,
    tolerance_mm: float,
    profile: MachineProfile,
) -> tuple[float, Coordinate, Coordinate] | None:
    """Return the scale, offset and overshoot when a drawing needs fitting."""
    (min_x, min_y), (max_x, max_y) = bounds
    (x_lo, y_lo), (x_hi, y_hi) = area
    overshoot = (
        max(0.0, x_lo - min_x, max_x - x_hi),
        max(0.0, y_lo - min_y, max_y - y_hi),
    )
    if overshoot[0] <= tolerance_mm and overshoot[1] <= tolerance_mm:
        return None
    width, height = x_hi - x_lo, y_hi - y_lo
    if width <= 0.0 or height <= 0.0:
        raise GcodeError(
            f"Profile {profile.name!r} has no drawable area left after bed.margin_mm "
            "and the ramp lead-in; use a larger drawable area"
        )
    drawing_width, drawing_height = max_x - min_x, max_y - min_y
    scale = min(
        1.0,
        width / drawing_width if drawing_width > 0.0 else 1.0,
        height / drawing_height if drawing_height > 0.0 else 1.0,
    )
    offset = (
        _shortest_shift(scale * min_x, scale * max_x, x_lo, x_hi),
        _shortest_shift(scale * min_y, scale * max_y, y_lo, y_hi),
    )
    return scale, offset, overshoot


def _fit_point(
    point: Coordinate,
    scale: float,
    offset: Coordinate,
    page_height: float,
    origin: Coordinate,
    profile: MachineProfile,
) -> Coordinate:
    """Apply a pen-space fit transform to one SVG page point."""
    pen_point = _svg_to_pen(point, page_height, origin, profile)
    pen = (scale * pen_point[0] + offset[0], scale * pen_point[1] + offset[1])
    return _pen_to_svg(pen, page_height, origin, profile)


def _fit_layers(
    layers: Sequence[GcodeLayer],
    scale: float,
    offset: Coordinate,
    page_height: float,
    origin: Coordinate,
    profile: MachineProfile,
) -> list[GcodeLayer]:
    """Apply a pen-space fit transform to every point of every layer."""
    return [
        GcodeLayer(
            layer.pen,
            [
                tuple(
                    _fit_point(point, scale, offset, page_height, origin, profile)
                    for point in polyline
                )
                for polyline in layer.polylines
            ],
        )
        for layer in layers
    ]


def fit_layers_to_drawable(
    layers: Sequence[GcodeLayer],
    profile: MachineProfile,
    page_size_mm: Coordinate,
    tolerance_mm: float = FIT_TOLERANCE_MM,
    placement: PagePlacement | None = None,
    frame: FrameSpec | None = None,
) -> FitResult:
    """Fit a drawing into the profile's usable area without distorting it.

    Page points are mapped to pen space exactly as :func:`build_gcode` maps
    them, then confined to the usable area (the drawable area minus the four
    per-side ``bed.margin_mm`` values) and minus the ramp's lead-in on every
    side, so a ramped stroke's lead-in and lead-out stay reachable too. A
    drawing already inside that area (within ``tolerance_mm``) is returned
    untouched. Otherwise it is shifted the shortest way that fits, or uniformly
    scaled down and shifted when it is larger than the available area. Scaling
    happens in pen space: the profile's lead distance itself is never scaled.

    Parameters
    ----------
    layers : Sequence[GcodeLayer]
        Layers of polylines in SVG page millimetres, in drawing order.
    profile : MachineProfile
        Validated machine profile; the only source of machine values.
    page_size_mm : tuple[float, float]
        SVG page width and height in millimetres, used for the Y flip and page origin.
    tolerance_mm : float
        Slop allowed at the usable-area boundary, by default ``FIT_TOLERANCE_MM``.
    placement : PagePlacement | None
        Page placement to map through. Computed from the profile when omitted.
    frame : FrameSpec | None
        Optional frame to include in the reachable-area check. When the fit
        changes the drawing, the returned ``FitResult.frame`` carries the same
        transform applied to the frame points, so emitter and fit agree.

    Returns
    -------
    FitResult
        The fitted layers, the pen-space transform, the overshoot found and the
        frame to emit (unchanged or fitted).

    Raises
    ------
    GcodeError
        The profile has no usable area left after the margins and ramp lead-in.
    """
    (xmin, ymin), (xmax, ymax) = usable_area(profile)
    final_placement = placement if placement is not None else place_page(profile, page_size_mm)
    origin = final_placement.origin_mm
    page_height = page_size_mm[1]
    lead = lead_in_mm(profile) or 0.0
    area = ((xmin + lead, ymin + lead), (xmax - lead, ymax - lead))
    unchanged = FitResult(layers, 1.0, (0.0, 0.0), (0.0, 0.0), False, frame)

    frame_points = list(frame.points(page_size_mm)) if frame is not None else []
    pen_points = _fit_pen_points(layers, frame_points, profile, page_height, origin)
    if not pen_points:
        return unchanged
    transform = _fit_transform(_fit_bounds(pen_points), area, tolerance_mm, profile)
    if transform is None:
        return unchanged
    scale, offset, overshoot = transform
    fitted_frame = (
        FrameSpec(
            frame.margin_mm,
            frame.pen,
            frame.pause,
            [
                _fit_point(point, scale, offset, page_height, origin, profile)
                for point in frame_points
            ],
        )
        if frame is not None
        else None
    )
    return FitResult(
        _fit_layers(layers, scale, offset, page_height, origin, profile),
        scale,
        offset,
        overshoot,
        True,
        fitted_frame,
    )


def drawing_bounds_pen(
    layers: Sequence[GcodeLayer],
    profile: MachineProfile,
    page_size_mm: Coordinate,
    placement: PagePlacement | None = None,
) -> Bounds:
    """Return the pen-space bounds of the drawing's emitted strokes.

    Points go through the emitter's own page-to-pen mapping, so the bounds
    describe the geometry that :func:`build_gcode` receives after fitting.
    Only polylines with at least two points count, matching the strokes the
    emitter draws; a separate frame is not included.

    Parameters
    ----------
    layers : Sequence[GcodeLayer]
        Layers of polylines in SVG page millimetres, in drawing order.
    profile : MachineProfile
        Validated machine profile; the only source of bed and placement values.
    page_size_mm : Coordinate
        SVG page width and height in millimetres, used for the Y flip.
    placement : PagePlacement | None
        Page placement the emitter used. Computed from the profile when omitted.

    Returns
    -------
    Bounds
        ``((min_x, min_y), (max_x, max_y))`` in pen-space millimetres.

    Raises
    ------
    GcodeError
        The drawing has no polyline with two or more points to bound.
    """
    final_placement = placement if placement is not None else place_page(profile, page_size_mm)
    origin = final_placement.origin_mm
    page_height = page_size_mm[1]
    points = [
        _svg_to_pen(point, page_height, origin, profile)
        for layer in layers
        for polyline in layer.polylines
        if len(polyline) >= 2
        for point in polyline
    ]
    if not points:
        raise GcodeError("drawing has no drawn points to bound")
    return (
        (min(point[0] for point in points), min(point[1] for point in points)),
        (max(point[0] for point in points), max(point[1] for point in points)),
    )


def build_gcode(
    layers: Sequence[GcodeLayer],
    profile: MachineProfile,
    page_size_mm: Coordinate,
    placement: PagePlacement | None = None,
    *,
    frame: FrameSpec | None = None,
) -> str:
    """Build G-code text from one or more pen layers and a machine profile.

    Parameters
    ----------
    layers : Sequence[GcodeLayer]
        Layers of polylines in SVG page millimetres, in drawing order. Empty
        polylines and layers without drawn points are skipped, so an unused pen
        never triggers a pen change. Each used layer gets one pen-change block
        according to ``pen_change.mode``.
    profile : MachineProfile
        Validated machine profile; the only source of machine values.
    page_size_mm : tuple[float, float]
        SVG page width and height in millimetres, used for the Y flip. Paper
        size comes from the reviewed SVG.
    placement : PagePlacement | None
        Page placement to map through and record in the header. Computed from
        the profile with :func:`place_page` when omitted.
    frame : FrameSpec | None
        Optional frame plotted before the first drawing stroke. With no frame,
        the output is exactly the same as before this option existed. The frame
        uses the first used layer's pen unless ``FrameSpec.pen`` names another;
        a different pen follows the profile's pen-change rule (a change before
        the frame and again before layer 1 in ``each`` mode, none in ``between``
        or ``none``). The frame and every drawing stroke share the same ramp and
        Z path. ``FRAME_PAUSE_MESSAGE`` is emitted after it when requested.

    A profile with ``ramp_mm`` uses the ramped landing of D7: each stroke gains
    a lead-in before its first point and a lead-out after its last, and Z falls
    linearly from ``z_hover`` to ``z_down`` over ``lead_in_mm + ramp_mm`` and
    rises the same way, so the pen lands and lifts while moving. Profiles
    without a ramp keep the plain travel/down/draw/up stroke. A zero-length
    polyline is a tap instead: travel to the point, lower to ``z_touch`` when
    present else ``z_down``, raise to ``z_up``, with no G1 and no ramp.

    Returns
    -------
    str
        The complete G-code document, with LF line endings and a trailing newline.

    Raises
    ------
    PointOutsideBedError
        A point is more than ``FIT_TOLERANCE_MM`` outside the usable area
        (the drawable area minus the profile margins); the error names the
        point, the limits and the per-axis overshoot.
    """
    used_layers = [layer for layer in layers if any(len(line) >= 2 for line in layer.polylines)]
    layer_count = len(used_layers)
    usable = usable_area(profile)
    final_placement = placement if placement is not None else place_page(profile, page_size_mm)
    origin = final_placement.origin_mm
    line_values = _profile_values(profile)
    feed_travel = f" F{line_values['feed_travel']}"
    feed_z = f" F{line_values['feed_z']}"
    common_values = line_values | {
        "pen": "",
        "pen_index": "0",
        "layer_index": "0",
        "pen_count": str(layer_count),
        "layer_count": str(layer_count),
    }
    prefix = profile.gcode.comment_prefix

    lines = [_header(profile, page_size_mm, final_placement)]
    lines.extend(_block(profile.gcode.start, common_values))
    pen_is_down = True
    first_pen = used_layers[0].pen if used_layers else ""
    frame_change_emitted = False
    if frame is not None:
        frame_pen = frame.pen if frame.pen is not None else first_pen
        if frame_pen == first_pen and used_layers:
            if _pen_change_needed(profile, 1):
                lines.extend(
                    _pen_change_lines(
                        profile,
                        common_values | {"pen": first_pen, "pen_index": "1", "layer_index": "1"},
                    )
                )
                frame_change_emitted = True
        elif profile.pen_change.mode == "each":
            lines.extend(
                _pen_change_lines(
                    profile,
                    common_values | {"pen": frame_pen, "pen_index": "0", "layer_index": "0"},
                )
            )
        lines.append(f"{prefix} frame pen={frame_pen}")
        frame_lines, pen_is_down = _emit_stroke(
            frame.points(page_size_mm),
            profile,
            page_size_mm[1],
            origin,
            usable,
            line_values,
            feed_travel,
            feed_z,
            pen_is_down,
        )
        lines.extend(frame_lines)
        if frame.pause:
            lines.append(f"M0 {FRAME_PAUSE_MESSAGE}")
    for index, layer in enumerate(used_layers, start=1):
        values = common_values | {
            "pen": layer.pen,
            "pen_index": str(index),
            "layer_index": str(index),
        }
        if _pen_change_needed(profile, index) and not (index == 1 and frame_change_emitted):
            lines.extend(_pen_change_lines(profile, values))
        lines.append(f"{prefix} layer {index}/{layer_count} pen={layer.pen}")
        lines.extend(_block(profile.gcode.layer_start, values))
        for polyline in layer.polylines:
            if len(polyline) < 2:
                continue
            stroke_lines, pen_is_down = _emit_stroke(
                polyline,
                profile,
                page_size_mm[1],
                origin,
                usable,
                line_values,
                feed_travel,
                feed_z,
                pen_is_down,
            )
            lines.extend(stroke_lines)
        if pen_is_down:
            lines.append(f"G0 Z{_format_mm(profile.pen.z_up)}{feed_z}")
            pen_is_down = False
        lines.extend(_block(profile.gcode.layer_end, values))
    lines.extend(_block(profile.gcode.end, common_values))
    return "\n".join(lines) + "\n"


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
    "fit_layers_to_drawable",
    "frame_polyline",
    "lead_in_mm",
    "page_origin_mm",
    "place_page",
    "usable_area",
]
