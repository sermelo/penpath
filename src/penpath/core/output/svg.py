"""Direct SVG export fallback using svgwrite."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import svgwrite  # type: ignore[import-untyped]
from shapely import LineString

if TYPE_CHECKING:
    from collections.abc import Iterable

    from penpath.core.models import Paper, Pen


MM_PER_INCH = 25.4
SVG_DPI = 96


def _mm_to_svg_units(mm: float) -> float:
    """Convert millimetres to SVG user units (1/96 inch)."""
    return mm * SVG_DPI / MM_PER_INCH


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
        margin_svg_x
        + (drawable_width_svg - scaled_geom_width_svg) / 2
        - min_x * pixel_to_svg
    )
    translate_y = (
        margin_svg_y
        + (drawable_height_svg - scaled_geom_height_svg) / 2
        - min_y * pixel_to_svg
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
            (x * pixel_to_svg + translate_x, y * pixel_to_svg + translate_y)
            for x, y in coords
        ]
        transformed.append(LineString(new_coords))

    return transformed


def export_svg(
    geometries: list[LineString],
    paper: Paper,
    pens: list[Pen],
    output_path: str | Path,
    image_dpi: int = 300,
) -> None:
    """Export geometries to SVG using svgwrite.

    Creates an SVG with:
    - ViewBox from paper size at 96 DPI (standard SVG)
    - Background layer with paper color
    - One layer per pen with inkscape:groupmode="layer"
    - Stroke width from pen width_mm, stroke color from pen color

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
    """
    if not pens:
        raise ValueError("At least one pen must be provided")

    if not geometries:
        raise ValueError("No geometries provided")

    valid_geometries = [g for g in geometries if not g.is_empty and len(list(g.coords)) >= 2]
    if not valid_geometries:
        raise ValueError("No valid geometries (need at least 2 points per line)")

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

    # Transform geometries to paper coordinates
    transformed_geometries = _scale_and_translate_geometries(valid_geometries, paper, image_dpi)

    # Create one layer per pen
    for i, pen in enumerate(pens):
        layer_id = f"pen-{pen.name}"
        layer_label = f"Pen: {pen.name}"

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


__all__ = ["export_svg"]
