"""Extract pen strokes and image placement metadata from SVG files."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from penpath.core.output.svg import ImagePlacement, fit_image_placement
from penpath.core.simulation import PenStroke

SVG_NAMESPACE = "http://www.w3.org/2000/svg"

MM_PER_SVG_UNIT = 25.4 / 96

_NUMBER_RE = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")
_PATH_TOKEN_RE = re.compile(r"[MmLlHhVvZz]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")
_LENGTH_RE = re.compile(r"^\s*([-+]?(?:\d*\.\d+|\d+\.?))\s*(mm|cm|in|px|pt|pc)?\s*$")
_TRANSFORM_RE = re.compile(r"(matrix|translate|scale)\s*\(([^)]*)\)")
_RGB_RE = re.compile(r"rgb\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)\s*\)", re.IGNORECASE)

_UNIT_TO_MM = {
    "mm": 1.0,
    "cm": 10.0,
    "in": 25.4,
    "px": MM_PER_SVG_UNIT,
    "pt": 25.4 / 72.0,
    "pc": 25.4 / 6.0,
}

_NAMED_COLORS = {
    "black": "#000000",
    "white": "#FFFFFF",
    "red": "#FF0000",
    "green": "#008000",
    "blue": "#0000FF",
    "gray": "#808080",
    "grey": "#808080",
}

_HIDDEN_ANCESTORS = {"defs", "clippath", "mask", "pattern", "marker", "symbol"}

_Transform = tuple[float, float, float, float, float, float]
_IDENTITY_TRANSFORM: _Transform = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _local_name(tag: str) -> str:
    """Return the local part of an XML tag, ignoring its namespace."""
    return tag.rsplit("}", 1)[-1]


def _length_to_mm(value: str | None, unit_scale: float = MM_PER_SVG_UNIT) -> float | None:
    """Convert an SVG length to millimetres, or return None if unparseable."""
    if not value:
        return None
    match = _LENGTH_RE.match(value)
    if match is None:
        return None
    number = float(match.group(1))
    unit = match.group(2)
    if unit is None:
        return number * unit_scale
    return number * _UNIT_TO_MM[unit]


def _svg_unit_scale(root: ET.Element) -> float:
    """Return millimetres per SVG user unit for the document root."""
    viewbox = root.get("viewBox")
    width = root.get("width")
    if viewbox and width:
        parts = viewbox.replace(",", " ").split()
        if len(parts) == 4:
            try:
                viewbox_width = float(parts[2])
            except ValueError:
                viewbox_width = 0.0
            page_width = _length_to_mm(width)
            if viewbox_width > 0 and page_width is not None and page_width > 0:
                return page_width / viewbox_width
    return MM_PER_SVG_UNIT


def _page_size_mm(root: ET.Element) -> tuple[float, float]:
    """Return the SVG page size in millimetres."""
    unit_scale = _svg_unit_scale(root)
    width = _length_to_mm(root.get("width"), unit_scale)
    height = _length_to_mm(root.get("height"), unit_scale)
    if width is not None and height is not None and width > 0 and height > 0:
        return width, height

    viewbox = root.get("viewBox")
    if viewbox:
        parts = viewbox.replace(",", " ").split()
        if len(parts) == 4:
            page_width = float(parts[2]) * unit_scale
            page_height = float(parts[3]) * unit_scale
            if page_width > 0 and page_height > 0:
                return page_width, page_height

    raise ValueError("SVG has no readable page size (set width/height or viewBox)")


def _compose_transforms(parent: _Transform, child: _Transform) -> _Transform:
    """Compose two affine transforms as parent(child(point))."""
    pa, pb, pc, pd, pe, pf = parent
    ca, cb, cc, cd, ce, cf = child
    return (
        pa * ca + pc * cb,
        pb * ca + pd * cb,
        pa * cc + pc * cd,
        pb * cc + pd * cd,
        pa * ce + pc * cf + pe,
        pb * ce + pd * cf + pf,
    )


def _parse_transform(value: str | None) -> _Transform:
    """Parse an SVG transform list (matrix, translate, scale)."""
    result = _IDENTITY_TRANSFORM
    if not value:
        return result

    for match in _TRANSFORM_RE.finditer(value):
        numbers = [float(number) for number in _NUMBER_RE.findall(match.group(2))]
        name = match.group(1)
        if name == "matrix" and len(numbers) == 6:
            local: _Transform = (
                numbers[0],
                numbers[1],
                numbers[2],
                numbers[3],
                numbers[4],
                numbers[5],
            )
        elif name == "translate" and len(numbers) >= 1:
            tx = numbers[0]
            ty = numbers[1] if len(numbers) > 1 else 0.0
            local = (1.0, 0.0, 0.0, 1.0, tx, ty)
        elif name == "scale" and len(numbers) >= 1:
            sx = numbers[0]
            sy = numbers[1] if len(numbers) > 1 else sx
            local = (sx, 0.0, 0.0, sy, 0.0, 0.0)
        else:
            continue
        result = _compose_transforms(result, local)
    return result


def _apply_transform(transform: _Transform, x: float, y: float) -> tuple[float, float]:
    """Apply an affine transform to a point."""
    a, b, c, d, e, f = transform
    return (a * x + c * y + e, b * x + d * y + f)


def _parse_color(value: str | None, default: str = "#000000") -> str:
    """Normalise an SVG color to a hex string."""
    if not value or value == "none":
        return default
    color = value.strip()
    if color.startswith("#"):
        return color
    rgb_match = _RGB_RE.match(color)
    if rgb_match:
        return "#{:02X}{:02X}{:02X}".format(*(int(part) for part in rgb_match.groups()))
    return _NAMED_COLORS.get(color.lower(), default)


def _parse_path_subpaths(path_data: str) -> list[list[tuple[float, float]]]:
    """Parse the subset of SVG path data used for pen strokes (M, L, H, V, Z)."""
    subpaths: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    x = y = 0.0
    start_x = start_y = 0.0
    command = ""
    tokens = _PATH_TOKEN_RE.findall(path_data)
    index = 0

    while index < len(tokens):
        token = tokens[index]
        if token.isalpha():
            command = token
            index += 1
            if command in ("Z", "z"):
                if len(current) >= 2:
                    current.append((start_x, start_y))
                    subpaths.append(current)
                current = []
                x, y = start_x, start_y
                continue
        elif command == "":
            index += 1
            continue

        if command in ("M", "m"):
            if index + 1 >= len(tokens):
                break
            new_x, new_y = float(tokens[index]), float(tokens[index + 1])
            index += 2
            if command == "m":
                new_x += x
                new_y += y
            if len(current) >= 2:
                subpaths.append(current)
            current = [(new_x, new_y)]
            x, y = new_x, new_y
            start_x, start_y = new_x, new_y
            command = "L" if command == "M" else "l"
        elif command in ("L", "l"):
            if index + 1 >= len(tokens):
                break
            new_x, new_y = float(tokens[index]), float(tokens[index + 1])
            index += 2
            if command == "l":
                new_x += x
                new_y += y
            x, y = new_x, new_y
            current.append((x, y))
        elif command in ("H", "h"):
            if index >= len(tokens):
                break
            new_x = float(tokens[index])
            index += 1
            x = new_x if command == "H" else x + new_x
            current.append((x, y))
        elif command in ("V", "v"):
            if index >= len(tokens):
                break
            new_y = float(tokens[index])
            index += 1
            y = new_y if command == "V" else y + new_y
            current.append((x, y))
        else:
            break

    if len(current) >= 2:
        subpaths.append(current)
    return subpaths


def _parse_points(points: str) -> list[tuple[float, float]]:
    """Parse a polyline ``points`` attribute into coordinate pairs."""
    numbers = [float(number) for number in _NUMBER_RE.findall(points)]
    return [(numbers[i], numbers[i + 1]) for i in range(0, len(numbers) - 1, 2)]


def _inherited_style(
    element: ET.Element,
    parent_map: dict[ET.Element, ET.Element],
) -> tuple[str | None, str | None, str | None]:
    """Return the nearest inherited (stroke, stroke-width, fill) values."""
    stroke: str | None = None
    stroke_width: str | None = None
    fill: str | None = None
    current = element
    while current in parent_map:
        current = parent_map[current]
        if stroke is None:
            stroke = current.get("stroke")
        if stroke_width is None:
            stroke_width = current.get("stroke-width")
        if fill is None:
            fill = current.get("fill")
    return stroke, stroke_width, fill


def _element_transform(
    element: ET.Element,
    parent_map: dict[ET.Element, ET.Element],
) -> _Transform:
    """Compose all transforms from the SVG root down to an element."""
    ancestors: list[ET.Element] = [element]
    current = element
    while current in parent_map:
        current = parent_map[current]
        ancestors.append(current)
    transform = _IDENTITY_TRANSFORM
    for ancestor in reversed(ancestors):
        transform = _compose_transforms(transform, _parse_transform(ancestor.get("transform")))
    return transform


def _has_hidden_ancestor(
    element: ET.Element,
    parent_map: dict[ET.Element, ET.Element],
) -> bool:
    """Check whether an element lives in a non-drawable SVG container."""
    current = element
    while current in parent_map:
        current = parent_map[current]
        if _local_name(current.tag).lower() in _HIDDEN_ANCESTORS:
            return True
    return False


def parse_svg_strokes(svg_path: str | Path) -> list[PenStroke]:
    """Parse an SVG file into pen strokes with coordinates in millimetres.

    Paths, polylines and lines are extracted from the whole document, so both
    penpath SVGs and SVGs from other tools can be read. Filled shapes, hidden
    elements and content inside ``<defs>`` are ignored.

    Parameters
    ----------
    svg_path : str | Path
        Path to the SVG file.

    Returns
    -------
    list[PenStroke]
        Pen strokes in paper millimetres, with pen-up set to False.
    """
    root = ET.parse(Path(svg_path)).getroot()
    unit_scale = _svg_unit_scale(root)
    parent_map = {child: parent for parent in root.iter() for child in parent}
    strokes: list[PenStroke] = []

    for element in root.iter():
        tag = _local_name(element.tag).lower()
        if tag not in ("path", "polyline", "line"):
            continue
        if element.get("display") == "none" or element.get("visibility") == "hidden":
            continue
        if _has_hidden_ancestor(element, parent_map):
            continue

        inherited_stroke, inherited_width, inherited_fill = _inherited_style(element, parent_map)
        fill = element.get("fill", inherited_fill)
        if fill is not None and fill != "none":
            continue

        if tag == "path":
            subpaths = _parse_path_subpaths(element.get("d", ""))
        elif tag == "polyline":
            points = _parse_points(element.get("points", ""))
            subpaths = [points] if len(points) >= 2 else []
        else:
            try:
                subpaths = [
                    [
                        (float(element.get("x1", "0")), float(element.get("y1", "0"))),
                        (float(element.get("x2", "0")), float(element.get("y2", "0"))),
                    ]
                ]
            except ValueError:
                subpaths = []

        if not subpaths:
            continue

        transform = _element_transform(element, parent_map)
        stroke_color = _parse_color(element.get("stroke", inherited_stroke))
        width_value = element.get("stroke-width", inherited_width)
        width_mm = _length_to_mm(width_value, unit_scale)
        if width_mm is None or width_mm <= 0:
            width_mm = unit_scale

        for points in subpaths:
            polyline: list[tuple[float, float]] = []
            for x, y in points:
                transformed_x, transformed_y = _apply_transform(transform, x, y)
                polyline.append((transformed_x * unit_scale, transformed_y * unit_scale))
            if len(polyline) < 2:
                continue
            strokes.append(
                PenStroke(
                    polyline=polyline,
                    width_mm=width_mm,
                    color=stroke_color,
                    pen_up=False,
                )
            )

    return strokes


def _metadata_placement(root: ET.Element) -> ImagePlacement | None:
    """Read placement metadata from an SVG root, if present."""
    for element in root.iter():
        if _local_name(element.tag) != "metadata":
            continue
        for child in element:
            if _local_name(child.tag) != "image-placement":
                continue
            try:
                return ImagePlacement(
                    x=float(child.get("x", "")),
                    y=float(child.get("y", "")),
                    width=float(child.get("width", "")),
                    height=float(child.get("height", "")),
                )
            except TypeError, ValueError:
                continue

    x_attr = root.get("data-penpath-x")
    y_attr = root.get("data-penpath-y")
    width_attr = root.get("data-penpath-width")
    height_attr = root.get("data-penpath-height")
    if (
        x_attr is not None
        and y_attr is not None
        and width_attr is not None
        and height_attr is not None
    ):
        try:
            return ImagePlacement(
                x=float(x_attr),
                y=float(y_attr),
                width=float(width_attr),
                height=float(height_attr),
            )
        except ValueError:
            return None
    return None


def get_image_placement(
    svg_path: str | Path,
    original_image_size_px: tuple[int, int],
) -> ImagePlacement:
    """Return the source image rectangle on the SVG page, in millimetres.

    Placement stored as penpath metadata is used when present. For SVGs
    without metadata, the image is fitted into the SVG page keeping its
    aspect ratio and centred.

    Parameters
    ----------
    svg_path : str | Path
        Path to the SVG file.
    original_image_size_px : tuple[int, int]
        Original image size as (width, height) in pixels.

    Returns
    -------
    ImagePlacement
        Image rectangle as (x, y, width, height) in paper millimetres.
    """
    root = ET.parse(Path(svg_path)).getroot()
    placement = _metadata_placement(root)
    if placement is not None:
        return placement

    page_width_mm, page_height_mm = _page_size_mm(root)
    return fit_image_placement(original_image_size_px, page_width_mm, page_height_mm)


__all__ = [
    "ImagePlacement",
    "get_image_placement",
    "parse_svg_strokes",
]
