"""Direct SVG export fallback using svgwrite."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import svgwrite  # type: ignore[import-untyped]
from shapely import LineString

if TYPE_CHECKING:
    from collections.abc import Iterable

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


def _mm_to_svg_units(mm: float) -> float:
    """Convert millimetres to SVG user units (1/96 inch)."""
    return mm * SVG_DPI / MM_PER_INCH


def _as_placement(
    placement: ImagePlacement | tuple[float, float, float, float],
) -> ImagePlacement:
    """Normalise a placement argument to an ImagePlacement."""
    return ImagePlacement(*placement)


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
    """Map image pixel coordinates onto the placed image rectangle."""
    image_width_px, image_height_px = image_size_px
    if image_width_px <= 0 or image_height_px <= 0:
        raise ValueError("Image size must have positive width and height")

    scale_x = placement.width / image_width_px
    scale_y = placement.height / image_height_px
    mm_to_units = SVG_DPI / MM_PER_INCH

    transformed: list[LineString] = []
    for line in geometries:
        if line.is_empty:
            continue
        coords = list(line.coords)
        if len(coords) < 2:
            continue
        new_coords = [
            (
                (placement.x + x * scale_x) * mm_to_units,
                (placement.y + y * scale_y) * mm_to_units,
            )
            for x, y in coords
        ]
        transformed.append(LineString(new_coords))
    return transformed


def _pen_layer_label(pen: Pen) -> str:
    """Return the Inkscape layer label penpath uses for a pen."""
    return f"Pen: {pen.name}"


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

    This is used for SVGs written by external tools such as vpype, where the
    export function is not under penpath's control. The rest of the SVG is
    left untouched so other tools keep reading it unchanged.

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
    """Scale geometries from image coordinates (pixels at image_dpi)
    to paper coordinates (SVG units).

    The geometries are scaled to fit within the paper's drawable area (with margins),
    centered on the page.

    Parameters
    ----------
    geometries : Iterable[LineString]
        Input line geometries in image pixel coordinates.
    paper : Paper
        Paper configuration with size, margins, and DPI.
    image_dpi : int, optional
        DPI of the source image coordinates. Defaults to 300.

    Returns
    -------
    list[LineString]
        Transformed geometries in SVG user units (1/96 inch), positioned on the page.
    """
    if not geometries:
        return []

    # Paper drawable area in mm
    drawable_width_mm = paper.drawable_width_mm
    drawable_height_mm = paper.drawable_height_mm

    # Convert drawable area to SVG units
    drawable_width_svg = _mm_to_svg_units(drawable_width_mm)
    drawable_height_svg = _mm_to_svg_units(drawable_height_mm)

    # Find bounds of all geometries in image pixels
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

    # Convert geometry bounds to mm at image_dpi
    geom_width_mm = geom_width_px * MM_PER_INCH / image_dpi
    geom_height_mm = geom_height_px * MM_PER_INCH / image_dpi

    # Calculate scale to fit in drawable area
    scale_x = drawable_width_mm / geom_width_mm
    scale_y = drawable_height_mm / geom_height_mm
    scale = min(scale_x, scale_y)

    # Scale factor from image pixels to SVG units
    # 1 image pixel = (scale * MM_PER_INCH / image_dpi) mm = (scale * SVG_DPI / image_dpi) SVG units
    pixel_to_svg = scale * SVG_DPI / image_dpi

    # Calculate translation to center on paper
    # Paper origin (0,0) in SVG is top-left with margins
    margin_svg_x = _mm_to_svg_units(paper.margin_mm)
    margin_svg_y = _mm_to_svg_units(paper.margin_mm)

    # Center the scaled geometry in the drawable area
    scaled_geom_width_svg = geom_width_px * pixel_to_svg
    scaled_geom_height_svg = geom_height_px * pixel_to_svg

    translate_x = (
        margin_svg_x + (drawable_width_svg - scaled_geom_width_svg) / 2 - min_x * pixel_to_svg
    )
    translate_y = (
        margin_svg_y + (drawable_height_svg - scaled_geom_height_svg) / 2 - min_y * pixel_to_svg
    )

    # Transform all geometries
    transformed = []
    for line in geometries:
        if line.is_empty:
            continue
        coords = list(line.coords)
        if len(coords) < 2:
            continue
        new_coords = [
            (x * pixel_to_svg + translate_x, y * pixel_to_svg + translate_y) for x, y in coords
        ]
        transformed.append(LineString(new_coords))

    return transformed


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
    """Export geometries to SVG using svgwrite.

    Creates an SVG with:
    - ViewBox from paper size at 96 DPI (standard SVG)
    - Background layer with paper color
    - One layer per pen with inkscape:groupmode="layer"
    - Stroke width from pen width_mm, stroke color from pen color
    - Optional image-placement metadata describing where the source image sits

    Parameters
    ----------
    geometries : list[LineString]
        Line geometries in image pixel coordinates (at image_dpi).
    paper : Paper
        Paper configuration (size, margins, background color, DPI).
    pens : list[Pen]
        Pen configurations. Each pen gets its own layer.
        In MVP, all geometries go to the first pen's layer.
    output_path : str | Path
        Output SVG file path.
    image_dpi : int, optional
        DPI of the input image coordinates. Defaults to 300.
    image_placement : ImagePlacement | tuple, optional
        Rectangle (x, y, width, height in mm) where the source image was
        placed. When given, geometries are mapped into this rectangle and
        the rectangle is written as SVG metadata. ``image_size_px`` must
        also be provided.
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

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Paper size in SVG units (96 DPI)
    svg_width = _mm_to_svg_units(paper.width_mm)
    svg_height = _mm_to_svg_units(paper.height_mm)

    # Create SVG drawing
    dwg = svgwrite.Drawing(
        str(output_path),
        size=(f"{paper.width_mm}mm", f"{paper.height_mm}mm"),
        viewBox=f"0 0 {svg_width} {svg_height}",
        profile="full",
        debug=False,
    )

    # Add Inkscape namespace for layer support
    dwg.attribs["xmlns:inkscape"] = "http://www.inkscape.org/namespaces/inkscape"

    # Background layer
    bg_attrs = {"inkscape:groupmode": "layer", "inkscape:label": "Background"}
    bg_layer = dwg.g(id="background", **bg_attrs)
    bg_rect = dwg.rect(
        insert=(0, 0),
        size=(svg_width, svg_height),
        fill=paper.background_color,
    )
    bg_layer.add(bg_rect)
    dwg.add(bg_layer)

    # Transform geometries to paper coordinates. When the image placement is
    # known, image pixels map directly onto that rectangle so the metadata
    # describes exactly where the drawing sits on the page.
    if image_placement is not None and image_size_px is not None:
        placement_value = _as_placement(image_placement)
        transformed_geometries = _scale_geometries_to_placement(
            valid_geometries, placement_value, image_size_px
        )
        dwg.set_metadata(_placement_metadata_element(placement_value, resolution))
    else:
        transformed_geometries = _scale_and_translate_geometries(valid_geometries, paper, image_dpi)

    # Create one layer per pen
    for i, pen in enumerate(pens):
        layer_id = f"pen-{pen.name}"
        layer_label = _pen_layer_label(pen)

        pen_layer = dwg.g(
            id=layer_id,
            **{"inkscape:groupmode": "layer", "inkscape:label": layer_label},
        )

        # Only first pen gets geometries (MVP: single pen)
        layer_geometries = transformed_geometries if i == 0 else []

        # Stroke properties
        stroke_width_svg = _mm_to_svg_units(pen.width_mm)
        stroke_color = pen.color
        stroke_opacity = pen.opacity

        for line in layer_geometries:
            coords = list(line.coords)
            if len(coords) < 2:
                continue

            path = dwg.path(
                fill="none",
                stroke=stroke_color,
                stroke_width=stroke_width_svg,
                stroke_opacity=stroke_opacity,
                stroke_linecap="round",
                stroke_linejoin="round",
            )

            # Build path data
            path.push(f"M {coords[0][0]:.3f} {coords[0][1]:.3f}")
            for x, y in coords[1:]:
                path.push(f"L {x:.3f} {y:.3f}")

            pen_layer.add(path)

        dwg.add(pen_layer)

    # Save SVG
    dwg.save()


__all__ = [
    "PENPATH_NAMESPACE",
    "ImagePlacement",
    "add_placement_metadata",
    "export_svg",
    "fit_image_placement",
]
