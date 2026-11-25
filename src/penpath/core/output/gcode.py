"""Turn layers of polylines and a machine profile into G-code text.

The module holds the shape of the language (G0/G1/G21/G90 syntax and the pen
up/down state machine) and no machine number: bed geometry, feeds, Z heights and
verbatim code blocks all come from the profile. The SVG page size is passed by
the caller because paper size stays in the reviewed SVG, not in the profile.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from penpath.core.profiles import MachineProfile

type Coordinate = tuple[float, float]
type Polyline = Sequence[Coordinate]
type Bounds = tuple[Coordinate, Coordinate]

COORDINATE_DECIMALS: Final = 3
SECONDS_PER_MINUTE: Final = 60


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


def _format_mm(value: float) -> str:
    """Format a millimetre value at the emitter's fixed precision."""
    return f"{value:.{COORDINATE_DECIMALS}f}"


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
    lead_in = ""
    if ramp is not None and z_touch is not None and z_hover is not None:
        lead_in = _format_mm(ramp * (z_hover - z_touch) / (z_touch - pen.z_down))
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


def _nozzle_points(
    polyline: Polyline,
    profile: MachineProfile,
    page_height_mm: float,
    origin: Coordinate,
    drawable: Bounds,
) -> list[Coordinate]:
    """Map a page polyline to nozzle coordinates, rejecting unreachable points."""
    offset_x, offset_y = profile.bed.pen_offset_mm
    margin = profile.bed.margin_mm
    (xmin, ymin), (xmax, ymax) = drawable
    result: list[Coordinate] = []
    for x_svg, y_svg in polyline:
        x_pen = origin[0] + x_svg
        y_pen = origin[1] + (page_height_mm - y_svg if profile.bed.invert_y else y_svg)
        if not (
            xmin + margin - 1e-9 <= x_pen <= xmax - margin + 1e-9
            and ymin + margin - 1e-9 <= y_pen <= ymax - margin + 1e-9
        ):
            raise PointOutsideBedError(
                f"point (x={_format_mm(x_pen)}, y={_format_mm(y_pen)}) mm is outside "
                f"the drawable area X {_format_mm(xmin + margin)}..{_format_mm(xmax - margin)}, "
                f"Y {_format_mm(ymin + margin)}..{_format_mm(ymax - margin)} mm"
            )
        result.append((x_pen - offset_x, y_pen - offset_y))
    return result


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

    Returns
    -------
    str
        The complete G-code document, with LF line endings and a trailing newline.

    Raises
    ------
    PointOutsideBedError
        A point is outside the drawable area (minus the profile margin).
    """
    used_layers = [layer for layer in layers if any(len(line) >= 2 for line in layer.polylines)]
    layer_count = len(used_layers)
    drawable = _drawable_area(profile)
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
            points = _nozzle_points(polyline, profile, page_size_mm[1], origin, drawable)
            if pen_is_down:
                lines.append(f"G0 Z{_format_mm(profile.pen.z_up)}")
                pen_is_down = False
            first_x, first_y = points[0]
            lines.append(f"G0 X{_format_mm(first_x)} Y{_format_mm(first_y)}")
            lines.append(f"G0 Z{_format_mm(profile.pen.z_down)}")
            pen_is_down = True
            feed = f" F{line_values['feed_draw']}"
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
    "GcodeError",
    "GcodeLayer",
    "PointOutsideBedError",
    "build_gcode",
    "page_origin_mm",
]
