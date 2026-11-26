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
from typing import Final

from penpath.core.profiles import MachineProfile

type Coordinate = tuple[float, float]
type Polyline = Sequence[Coordinate]
type Bounds = tuple[Coordinate, Coordinate]

COORDINATE_DECIMALS: Final = 3
SECONDS_PER_MINUTE: Final = 60
FIT_TOLERANCE_MM: Final = 0.05


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
        Per-axis distance the original drawing exceeded the drawable area, in mm.
    changed : bool
        Whether the layers were transformed.
    """

    layers: Sequence[GcodeLayer]
    scale: float
    offset_mm: Coordinate
    overshoot_mm: Coordinate
    changed: bool


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


def _page_origin(
    profile: MachineProfile,
    page_size_mm: Coordinate,
    drawable: Bounds,
) -> Coordinate:
    """Return the pen-space origin of the page's lower-left corner."""
    page = profile.bed.page
    if page.placement == "fixed":
        return page.origin_mm
    return (drawable[1][0] - page_size_mm[0], drawable[0][1])


def page_origin_mm(
    profile: MachineProfile,
    page_size_mm: Coordinate,
) -> Coordinate:
    """Return the pen-space page origin for a profile and source page size.

    Both the emitter and the preview use this helper, so ``reachable_corner``
    placement inverts with the same drawable-corner origin the emitter used.
    """
    return _page_origin(profile, page_size_mm, _drawable_area(profile))


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


def _header(profile: MachineProfile, page_size_mm: Coordinate) -> str:
    """Build the header comment carrying the page size and Z semantics."""
    fields = [
        f"profile={profile.name}",
        f"page={_format_mm(page_size_mm[0])}x{_format_mm(page_size_mm[1])}",
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


def _check_pen_point(point: Coordinate, profile: MachineProfile, drawable: Bounds) -> None:
    """Reject a pen-space point outside the drawable area minus the bed margin.

    The fit tolerance absorbs float rounding at the edge; a point further out
    reports how far past each axis it lies.
    """
    margin = profile.bed.margin_mm
    (xmin, ymin), (xmax, ymax) = drawable
    x_pen, y_pen = point
    x_lo, x_hi = xmin + margin, xmax - margin
    y_lo, y_hi = ymin + margin, ymax - margin
    if not (
        x_lo - FIT_TOLERANCE_MM <= x_pen <= x_hi + FIT_TOLERANCE_MM
        and y_lo - FIT_TOLERANCE_MM <= y_pen <= y_hi + FIT_TOLERANCE_MM
    ):
        x_past = max(0.0, x_lo - x_pen, x_pen - x_hi)
        y_past = max(0.0, y_lo - y_pen, y_pen - y_hi)
        raise PointOutsideBedError(
            f"point (x={_format_mm(x_pen)}, y={_format_mm(y_pen)}) mm is outside "
            f"the drawable area X {_format_mm(x_lo)}..{_format_mm(x_hi)}, "
            f"Y {_format_mm(y_lo)}..{_format_mm(y_hi)} mm; "
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
    drawable: Bounds,
) -> list[Coordinate]:
    """Map a page polyline to checked pen-space points."""
    result: list[Coordinate] = []
    for point in polyline:
        pen_point = _svg_to_pen(point, page_height_mm, origin, profile)
        _check_pen_point(pen_point, profile, drawable)
        result.append(pen_point)
    return result


def _nozzle(point: Coordinate, profile: MachineProfile) -> Coordinate:
    """Convert one checked pen-space point to nozzle/machine space."""
    offset_x, offset_y = profile.bed.pen_offset_mm
    return (point[0] - offset_x, point[1] - offset_y)


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


def _shortest_shift(low: float, high: float, target_low: float, target_high: float) -> float:
    """Return the smallest translation placing an interval inside its target."""
    if low < target_low:
        return target_low - low
    if high > target_high:
        return target_high - high
    return 0.0


def fit_layers_to_drawable(
    layers: Sequence[GcodeLayer],
    profile: MachineProfile,
    page_size_mm: Coordinate,
    tolerance_mm: float = FIT_TOLERANCE_MM,
) -> FitResult:
    """Fit a drawing into the profile's drawable area without distorting it.

    Page points are mapped to pen space exactly as :func:`build_gcode` maps
    them, then confined to the drawable area minus ``bed.margin_mm`` and minus
    the ramp's lead-in on every side, so a ramped stroke's lead-in and lead-out
    stay reachable too. A drawing already inside that area (within
    ``tolerance_mm``) is returned untouched. Otherwise it is shifted the
    shortest way that fits, or uniformly scaled down and shifted when it is
    larger than the available area. Scaling happens in pen space: the profile's
    lead distance itself is never scaled.

    Parameters
    ----------
    layers : Sequence[GcodeLayer]
        Layers of polylines in SVG page millimetres, in drawing order.
    profile : MachineProfile
        Validated machine profile; the only source of machine values.
    page_size_mm : tuple[float, float]
        SVG page width and height in millimetres, used for the Y flip and page origin.
    tolerance_mm : float
        Slop allowed at the drawable boundary, by default ``FIT_TOLERANCE_MM``.

    Returns
    -------
    FitResult
        The fitted layers, the pen-space transform and the overshoot found.

    Raises
    ------
    GcodeError
        The profile has no drawable area left after the margin and ramp lead-in.
    """
    drawable = _drawable_area(profile)
    origin = page_origin_mm(profile, page_size_mm)
    page_height = page_size_mm[1]
    inset = profile.bed.margin_mm + (lead_in_mm(profile) or 0.0)
    (xmin, ymin), (xmax, ymax) = drawable
    x_lo, x_hi = xmin + inset, xmax - inset
    y_lo, y_hi = ymin + inset, ymax - inset
    unchanged = FitResult(layers, 1.0, (0.0, 0.0), (0.0, 0.0), False)

    pen_points = [
        _svg_to_pen(point, page_height, origin, profile)
        for layer in layers
        for polyline in layer.polylines
        if len(polyline) >= 2
        for point in polyline
    ]
    if not pen_points:
        return unchanged
    min_x = min(point[0] for point in pen_points)
    max_x = max(point[0] for point in pen_points)
    min_y = min(point[1] for point in pen_points)
    max_y = max(point[1] for point in pen_points)
    overshoot = (
        max(0.0, x_lo - min_x, max_x - x_hi),
        max(0.0, y_lo - min_y, max_y - y_hi),
    )
    if overshoot[0] <= tolerance_mm and overshoot[1] <= tolerance_mm:
        return unchanged

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

    def fitted(point: Coordinate) -> Coordinate:
        pen_point = _svg_to_pen(point, page_height, origin, profile)
        pen = (scale * pen_point[0] + offset[0], scale * pen_point[1] + offset[1])
        return _pen_to_svg(pen, page_height, origin, profile)

    fitted_layers = [
        GcodeLayer(
            layer.pen,
            [tuple(fitted(point) for point in polyline) for polyline in layer.polylines],
        )
        for layer in layers
    ]
    return FitResult(fitted_layers, scale, offset, overshoot, True)


def build_gcode(
    layers: Sequence[GcodeLayer],
    profile: MachineProfile,
    page_size_mm: Coordinate,
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
        SVG page width and height in millimetres, used for the Y flip and for
        ``reachable_corner`` placement. Paper size comes from the reviewed SVG.

    A profile with ``ramp_mm`` uses the ramped landing of D7: each stroke gains
    a lead-in before its first point and a lead-out after its last, and Z falls
    linearly from ``z_hover`` to ``z_down`` over ``lead_in_mm + ramp_mm`` and
    rises the same way, so the pen lands and lifts while moving. Profiles
    without a ramp keep the plain travel/down/draw/up stroke.

    Returns
    -------
    str
        The complete G-code document, with LF line endings and a trailing newline.

    Raises
    ------
    PointOutsideBedError
        A point is more than ``FIT_TOLERANCE_MM`` outside the drawable area
        (minus the profile margin); the error names the point, the limits and
        the per-axis overshoot.
    """
    used_layers = [layer for layer in layers if any(len(line) >= 2 for line in layer.polylines)]
    layer_count = len(used_layers)
    drawable = _drawable_area(profile)
    lead = lead_in_mm(profile)
    origin = page_origin_mm(profile, page_size_mm)
    line_values = _profile_values(profile)
    common_values = line_values | {
        "pen": "",
        "pen_index": "0",
        "layer_index": "0",
        "pen_count": str(layer_count),
        "layer_count": str(layer_count),
    }
    prefix = profile.gcode.comment_prefix

    lines = [_header(profile, page_size_mm)]
    lines.extend(_block(profile.gcode.start, common_values))
    pen_is_down = True
    for index, layer in enumerate(used_layers, start=1):
        values = common_values | {
            "pen": layer.pen,
            "pen_index": str(index),
            "layer_index": str(index),
        }
        if _pen_change_needed(profile, index):
            lines.extend(_pen_change_lines(profile, values))
        lines.append(f"{prefix} layer {index}/{layer_count} pen={layer.pen}")
        lines.extend(_block(profile.gcode.layer_start, values))
        for polyline in layer.polylines:
            if len(polyline) < 2:
                continue
            pen_points = _pen_points(polyline, profile, page_size_mm[1], origin, drawable)
            if pen_is_down:
                lines.append(f"G0 Z{_format_mm(profile.pen.z_up)}")
                pen_is_down = False
            feed = f" F{line_values['feed_draw']}"
            if lead is not None:
                ramp_path = _ramped_path(pen_points, profile)
                if not ramp_path:
                    continue
                for point, _ in ramp_path:
                    _check_pen_point(point, profile, drawable)
                first, first_z = ramp_path[0]
                first_x, first_y = _nozzle(first, profile)
                lines.append(f"G0 X{_format_mm(first_x)} Y{_format_mm(first_y)}")
                lines.append(f"G0 Z{_format_mm(first_z)}")
                for point_index, (point, z) in enumerate(ramp_path[1:]):
                    x, y = _nozzle(point, profile)
                    suffix = feed if point_index == 0 else ""
                    lines.append(f"G1 X{_format_mm(x)} Y{_format_mm(y)} Z{_format_mm(z)}{suffix}")
                lines.append(f"G0 Z{_format_mm(profile.pen.z_up)}")
            else:
                points = [_nozzle(point, profile) for point in pen_points]
                first_x, first_y = points[0]
                lines.append(f"G0 X{_format_mm(first_x)} Y{_format_mm(first_y)}")
                lines.append(f"G0 Z{_format_mm(profile.pen.z_down)}")
                pen_is_down = True
                for point_index, point in enumerate(points[1:]):
                    suffix = feed if point_index == 0 else ""
                    lines.append(f"G1 X{_format_mm(point[0])} Y{_format_mm(point[1])}{suffix}")
        if pen_is_down:
            lines.append(f"G0 Z{_format_mm(profile.pen.z_up)}")
            pen_is_down = False
        lines.extend(_block(profile.gcode.layer_end, values))
    lines.extend(_block(profile.gcode.end, common_values))
    return "\n".join(lines) + "\n"


__all__ = [
    "FIT_TOLERANCE_MM",
    "FitResult",
    "GcodeError",
    "GcodeLayer",
    "PointOutsideBedError",
    "build_gcode",
    "fit_layers_to_drawable",
    "lead_in_mm",
    "page_origin_mm",
]
