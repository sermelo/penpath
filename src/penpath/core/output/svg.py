"""SVG export in millimetres with one Inkscape layer per pen."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import svgwrite  # type: ignore[import-untyped]
from PIL import ImageColor
from shapely import LineString

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from penpath.core.image.resolution import WorkingResolution
    from penpath.core.models import Paper, Pen


MM_PER_INCH = 25.4
SVG_DPI = 96

PENPATH_NAMESPACE = "http://penpath.org/ns/penpath"
ET.register_namespace("penpath", PENPATH_NAMESPACE)

_PENPATH_METADATA_RE = re.compile(
    r"<metadata\b[^>]*>\s*<(?:\w+:)?image-placement\b[^>]*/>\s*</metadata>",
    re.DOTALL,
)


class ImagePlacement(NamedTuple):
    """Rectangle occupied by the source image on the SVG page, in millimetres.

    Attributes
    ----------
    x : float
        Left edge of the image in paper millimetres.
    y : float
        Top edge of the image in paper millimetres.
    width : float
        Image width in millimetres.
    height : float
        Image height in millimetres.
    """

    x: float
    y: float
    width: float
    height: float


def _as_placement(
    placement: ImagePlacement | tuple[float, float, float, float],
) -> ImagePlacement:
    """Normalise a placement argument to an ImagePlacement."""
    return ImagePlacement(*placement)


def _format_mm(value: float) -> str:
    """Format a millimetre value without redundant trailing zeros."""
    return f"{value:g}"


def _stroke_hex(pen: Pen) -> str:
    """Return the pen colour as a #RRGGBB stroke, whatever its source format."""
    try:
        rgb = ImageColor.getrgb(pen.color)
    except ValueError as e:
        raise ValueError(f"Pen colour {pen.color!r} is not a recognised colour") from e
    return "#{:02X}{:02X}{:02X}".format(*rgb[:3])


def fit_image_placement(
    image_size_px: tuple[int, int],
    area_width_mm: float,
    area_height_mm: float,
    image_dpi: int = 300,
    offset_x_mm: float = 0.0,
    offset_y_mm: float = 0.0,
) -> ImagePlacement:
    """Fit an image into an area, preserving aspect ratio and centering it.

    The result is independent of ``image_dpi``: the DPI only fixes the
    relationship between pixels and millimetres before the image is scaled
    to fit the area.

    Parameters
    ----------
    image_size_px : tuple[int, int]
        Source image size as (width, height) in pixels.
    area_width_mm : float
        Width of the area to fit the image into, in millimetres.
    area_height_mm : float
        Height of the area to fit the image into, in millimetres.
    image_dpi : int, optional
        DPI of the source image. Defaults to 300.
    offset_x_mm : float, optional
        Left edge of the area in paper millimetres. Defaults to 0.
    offset_y_mm : float, optional
        Top edge of the area in paper millimetres. Defaults to 0.

    Returns
    -------
    ImagePlacement
        Placement of the fitted image in paper millimetres.
    """
    image_width_px, image_height_px = image_size_px
    if image_width_px <= 0 or image_height_px <= 0:
        raise ValueError("Image size must have positive width and height")
    if area_width_mm <= 0 or area_height_mm <= 0:
        raise ValueError("Placement area must have positive width and height")
    if image_dpi <= 0:
        raise ValueError("Image DPI must be positive")

    image_width_mm = image_width_px * MM_PER_INCH / image_dpi
    image_height_mm = image_height_px * MM_PER_INCH / image_dpi
    scale = min(area_width_mm / image_width_mm, area_height_mm / image_height_mm)

    width_mm = image_width_mm * scale
    height_mm = image_height_mm * scale

    return ImagePlacement(
        x=offset_x_mm + (area_width_mm - width_mm) / 2,
        y=offset_y_mm + (area_height_mm - height_mm) / 2,
        width=width_mm,
        height=height_mm,
    )


def _scale_geometries_to_placement(
    geometries: Iterable[LineString],
    placement: ImagePlacement,
    image_size_px: tuple[int, int],
) -> list[LineString]:
    """Map image pixel coordinates onto the placed image rectangle, in millimetres."""
    image_width_px, image_height_px = image_size_px
    if image_width_px <= 0 or image_height_px <= 0:
        raise ValueError("Image size must have positive width and height")

    scale_x = placement.width / image_width_px
    scale_y = placement.height / image_height_px

    transformed: list[LineString] = []
    for line in geometries:
        if line.is_empty:
            continue
        coords = list(line.coords)
        if len(coords) < 2:
            continue
        new_coords = [(placement.x + x * scale_x, placement.y + y * scale_y) for x, y in coords]
        transformed.append(LineString(new_coords))
    return transformed


def _resolution_metadata(resolution: WorkingResolution | None) -> dict[str, str]:
    """Return the image/source size attributes describing a working resolution."""
    if resolution is None:
        return {}
    image_width, image_height = resolution.target_size_px
    source_width, source_height = resolution.source_size_px
    return {
        "image-width": str(image_width),
        "image-height": str(image_height),
        "source-width": str(source_width),
        "source-height": str(source_height),
    }


def _placement_metadata_element(
    placement: ImagePlacement,
    resolution: WorkingResolution | None = None,
) -> ET.Element:
    """Build the <penpath:image-placement> element for an SVG metadata block."""
    return ET.Element(
        f"{{{PENPATH_NAMESPACE}}}image-placement",
        {
            "x": f"{placement.x:.4f}",
            "y": f"{placement.y:.4f}",
            "width": f"{placement.width:.4f}",
            "height": f"{placement.height:.4f}",
            **_resolution_metadata(resolution),
        },
    )


def add_placement_metadata(
    svg_path: str | Path,
    placement: ImagePlacement | tuple[float, float, float, float],
    resolution: WorkingResolution | None = None,
) -> None:
    """Insert or replace penpath image-placement metadata in an existing SVG.

    This is a helper for SVGs written by other tools; penpath's own writer
    includes the metadata when it writes the file.

    Parameters
    ----------
    svg_path : str | Path
        Path to the SVG file to update in place.
    placement : ImagePlacement | tuple[float, float, float, float]
        Image rectangle in paper millimetres: (x, y, width, height).
    resolution : WorkingResolution | None, optional
        Working resolution to record as image/source size attributes. When
        omitted, the metadata keeps only the placement rectangle.
    """
    path = Path(svg_path)
    placement_value = _as_placement(placement)
    resolution_attrs = "".join(
        f' {key}="{value}"' for key, value in _resolution_metadata(resolution).items()
    )
    metadata_xml = (
        f'<metadata xmlns:penpath="{PENPATH_NAMESPACE}">'
        f"<penpath:image-placement "
        f'x="{placement_value.x:.4f}" '
        f'y="{placement_value.y:.4f}" '
        f'width="{placement_value.width:.4f}" '
        f'height="{placement_value.height:.4f}"'
        f"{resolution_attrs}/>"
        "</metadata>"
    )

    content = path.read_text(encoding="utf-8")
    content = _PENPATH_METADATA_RE.sub("", content)
    closing_tag = "</svg>"
    closing_index = content.rfind(closing_tag)
    if closing_index < 0:
        raise ValueError(f"No closing </svg> tag found in {path}")
    path.write_text(
        content[:closing_index] + metadata_xml + content[closing_index:],
        encoding="utf-8",
    )


def _scale_and_translate_geometries(
    geometries: Iterable[LineString],
    paper: Paper,
    image_dpi: int = 300,
) -> list[LineString]:
    """Scale geometries from image pixels into paper millimetres, centred on the page."""
    if not geometries:
        return []

    drawable_width_mm = paper.drawable_width_mm
    drawable_height_mm = paper.drawable_height_mm

    all_coords: list[tuple[float, ...]] = []
    for line in geometries:
        if not line.is_empty:
            all_coords.extend(line.coords)

    if not all_coords:
        return []

    min_x = min(c[0] for c in all_coords)
    max_x = max(c[0] for c in all_coords)
    min_y = min(c[1] for c in all_coords)
    max_y = max(c[1] for c in all_coords)

    geom_width_px = max_x - min_x
    geom_height_px = max_y - min_y

    if geom_width_px == 0 or geom_height_px == 0:
        return []

    geom_width_mm = geom_width_px * MM_PER_INCH / image_dpi
    geom_height_mm = geom_height_px * MM_PER_INCH / image_dpi

    scale = min(drawable_width_mm / geom_width_mm, drawable_height_mm / geom_height_mm)
    pixel_to_mm = scale * MM_PER_INCH / image_dpi

    margin_mm = paper.margin_mm
    scaled_geom_width_mm = geom_width_px * pixel_to_mm
    scaled_geom_height_mm = geom_height_px * pixel_to_mm

    translate_x = margin_mm + (drawable_width_mm - scaled_geom_width_mm) / 2 - min_x * pixel_to_mm
    translate_y = margin_mm + (drawable_height_mm - scaled_geom_height_mm) / 2 - min_y * pixel_to_mm

    transformed: list[LineString] = []
    for line in geometries:
        if line.is_empty:
            continue
        coords = list(line.coords)
        if len(coords) < 2:
            continue
        new_coords = [
            (x * pixel_to_mm + translate_x, y * pixel_to_mm + translate_y) for x, y in coords
        ]
        transformed.append(LineString(new_coords))

    return transformed


def write_penpath_svg(
    strokes_by_pen: Sequence[Sequence[LineString]],
    paper: Paper,
    pens: Sequence[Pen],
    output_path: str | Path,
    image_placement: ImagePlacement | tuple[float, float, float, float] | None = None,
    resolution: WorkingResolution | None = None,
) -> None:
    """Write penpath's SVG layout from geometry already in paper millimetres.

    Both export paths end here: the direct export scales its image geometry
    first, and the vpype path reads the optimised geometry back in millimetres.
    The page uses millimetres throughout; every used pen gets one Inkscape
    layer named ``layerN`` and labelled with the pen name, in drawing order.
    The background is a plain rect, not a layer.

    Parameters
    ----------
    strokes_by_pen : Sequence[Sequence[LineString]]
        One list of line geometries per pen, in pen order, in paper
        millimetres. Empty lists create no layer.
    paper : Paper
        Paper configuration (size and background colour).
    pens : Sequence[Pen]
        Pens in drawing order, one entry per item of ``strokes_by_pen``.
    output_path : str | Path
        Output SVG file path.
    image_placement : ImagePlacement | tuple, optional
        Rectangle (x, y, width, height in mm) written as placement metadata.
    resolution : WorkingResolution | None, optional
        Working resolution to record as image/source size attributes.
    """
    if not pens:
        raise ValueError("At least one pen must be provided")
    if len(strokes_by_pen) != len(pens):
        raise ValueError("strokes_by_pen must have one entry per pen")

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    width = _format_mm(paper.width_mm)
    height = _format_mm(paper.height_mm)
    dwg = svgwrite.Drawing(
        str(path),
        size=(f"{width}mm", f"{height}mm"),
        viewBox=f"0 0 {width} {height}",
        profile="full",
        debug=False,
    )
    dwg.attribs["xmlns:inkscape"] = "http://www.inkscape.org/namespaces/inkscape"

    dwg.add(
        dwg.rect(
            insert=(0, 0),
            size=(paper.width_mm, paper.height_mm),
            fill=paper.background_color,
        )
    )
    if image_placement is not None:
        dwg.set_metadata(_placement_metadata_element(_as_placement(image_placement), resolution))

    layer_number = 0
    for pen, lines in zip(pens, strokes_by_pen, strict=True):
        valid_lines = [line for line in lines if not line.is_empty and len(list(line.coords)) >= 2]
        if not valid_lines:
            continue

        layer_number += 1
        layer = dwg.g(
            id=f"layer{layer_number}",
            **{"inkscape:groupmode": "layer", "inkscape:label": pen.name},
        )
        stroke_color = _stroke_hex(pen)
        stroke_width = _format_mm(pen.width_mm)

        for line in valid_lines:
            coords = list(line.coords)
            path_element = dwg.path(
                fill="none",
                stroke=stroke_color,
                stroke_width=stroke_width,
                stroke_opacity=pen.opacity,
                stroke_linecap="round",
                stroke_linejoin="round",
            )
            path_element.push(f"M {coords[0][0]:.3f} {coords[0][1]:.3f}")
            for x, y in coords[1:]:
                path_element.push(f"L {x:.3f} {y:.3f}")
            layer.add(path_element)

        dwg.add(layer)

    dwg.save()


def export_svg(
    geometries: list[LineString],
    paper: Paper,
    pens: list[Pen],
    output_path: str | Path,
    image_dpi: int = 300,
    image_placement: ImagePlacement | tuple[float, float, float, float] | None = None,
    image_size_px: tuple[int, int] | None = None,
    resolution: WorkingResolution | None = None,
) -> None:
    """Export geometries to a penpath SVG in millimetres.

    Creates an SVG with the paper size as width/height and viewBox in
    millimetres, a background rect, and one Inkscape layer per used pen.
    Until colour separation lands, all geometries go to the first pen.

    Parameters
    ----------
    geometries : list[LineString]
        Line geometries in image pixel coordinates (at image_dpi).
    paper : Paper
        Paper configuration (size, margins, background colour).
    pens : list[Pen]
        Pens in drawing order. Only pens with geometry get a layer.
    output_path : str | Path
        Output SVG file path.
    image_dpi : int, optional
        DPI of the input image coordinates. Defaults to 300.
    image_placement : ImagePlacement | tuple, optional
        Rectangle (x, y, width, height in mm) where the source image sits.
        ``image_size_px`` must also be provided.
    image_size_px : tuple[int, int], optional
        Size of the image the geometries belong to, in pixels. Required when
        ``image_placement`` is provided.
    resolution : WorkingResolution | None, optional
        Working resolution to record as image/source size attributes. When
        omitted, the metadata keeps only the placement rectangle.
    """
    if not pens:
        raise ValueError("At least one pen must be provided")

    if not geometries:
        raise ValueError("No geometries provided")

    valid_geometries = [g for g in geometries if not g.is_empty and len(list(g.coords)) >= 2]
    if not valid_geometries:
        raise ValueError("No valid geometries (need at least 2 points per line)")

    if image_placement is not None and image_size_px is None:
        raise ValueError("image_size_px is required when image_placement is provided")

    if image_placement is not None and image_size_px is not None:
        transformed = _scale_geometries_to_placement(
            valid_geometries, _as_placement(image_placement), image_size_px
        )
    else:
        transformed = _scale_and_translate_geometries(valid_geometries, paper, image_dpi)

    write_penpath_svg(
        [transformed, *([[]] * (len(pens) - 1))],
        paper,
        pens,
        output_path,
        image_placement,
        resolution,
    )


__all__ = [
    "PENPATH_NAMESPACE",
    "ImagePlacement",
    "add_placement_metadata",
    "export_svg",
    "fit_image_placement",
    "write_penpath_svg",
]
