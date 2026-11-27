"""``penpath preview`` - render a simulated plot of an SVG or G-code file."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import click
from rich.console import Console

from penpath.cli.commands._resolution import enforce_render_budget, resolve_px_per_mm
from penpath.core import (
    GcodePreviewError,
    MachineProfile,
    PenStroke,
    ProfileError,
    gcode_to_strokes,
    get_svg_paper_size,
    load_profile,
    page_origin_mm,
    parse_gcode_header,
    parse_svg_strokes,
    simulate_plot,
)
from penpath.presets.palettes import STABILO_88
from penpath.presets.pens import PEN_PRESETS

DEFAULT_PX_PER_MM = 4.0
DEFAULT_DPI = DEFAULT_PX_PER_MM * 25.4
FALLBACK_PAPER_MM = (210.0, 297.0)
TRAVEL_COLOR = "#C8C8C8"
TRAVEL_WIDTH_MM = 0.1
OUTLINE_COLOR = "#A0A0A0"
OUTLINE_WIDTH_MM = 0.2

console = Console(stderr=True)


def _paper_size_mm(svg_path: Path) -> tuple[float, float]:
    """Return the SVG page size in mm, falling back to A4 when unreadable."""
    return get_svg_paper_size(svg_path) or FALLBACK_PAPER_MM


def _pen_styles() -> dict[str, tuple[str, float]]:
    """Map built-in pen names to the colour and width used in their SVG."""
    styles = {pen.name: (pen.color, pen.width_mm) for pen in STABILO_88.pens}
    styles.update({name: (pen.color, pen.width) for name, pen in PEN_PRESETS.items()})
    return styles


def _rectangle(x0: float, y0: float, x1: float, y1: float) -> PenStroke:
    """Return a closed grey outline in bed-canvas millimetres."""
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    return PenStroke(corners, OUTLINE_WIDTH_MM, OUTLINE_COLOR)


def _page_to_bed(
    point: tuple[float, float],
    page_size_mm: tuple[float, float],
    origin_mm: tuple[float, float],
    profile: MachineProfile,
) -> tuple[float, float]:
    """Map a page point to the bed canvas, with pen-space Y growing up."""
    x, y = point
    pen_y = origin_mm[1] + (page_size_mm[1] - y if profile.bed.invert_y else y)
    return (origin_mm[0] + x, profile.bed.size_mm[1] - pen_y)


def _outlines(
    profile: MachineProfile,
    origin_mm: tuple[float, float],
    page_size_mm: tuple[float, float],
    px_per_mm: float,
) -> list[PenStroke]:
    """Return the bed and page outlines in bed-canvas millimetres."""
    bed_width, bed_height = profile.bed.size_mm
    page_width, page_height = page_size_mm
    page_top = bed_height - origin_mm[1] - page_height
    right = (round(bed_width * px_per_mm) - 1) / px_per_mm
    bottom = (round(bed_height * px_per_mm) - 1) / px_per_mm
    return [
        _rectangle(0.0, 0.0, max(0.0, right), max(0.0, bottom)),
        _rectangle(
            origin_mm[0],
            page_top,
            origin_mm[0] + page_width,
            page_top + page_height,
        ),
    ]


def _preview_gcode(
    path: Path, layer_label: str | None, include_pen_up: bool, px_per_mm: float
) -> tuple[list[PenStroke], list[PenStroke], tuple[float, float]]:
    """Read penpath G-code, undoing the emitter's page and profile transforms."""
    text = path.read_text(encoding="utf-8")
    header = parse_gcode_header(text)
    profile = None
    if header.profile:
        try:
            profile = load_profile(header.profile)
        except ProfileError:
            console.print(f"Profile {header.profile!r} not found; previewing machine coordinates.")
    paper_size_mm = header.page or (
        profile.bed.size_mm if profile is not None else FALLBACK_PAPER_MM
    )
    try:
        strokes = gcode_to_strokes(
            text, paper_size_mm, profile, _pen_styles(), layer_label, include_pen_up
        )
    except GcodePreviewError as exc:
        raise click.ClickException(f"Could not preview G-code: {exc}") from exc
    if profile is None:
        return strokes, [], paper_size_mm

    origin_mm = header.page_origin or page_origin_mm(profile, paper_size_mm)
    canvas_mm = profile.bed.size_mm
    strokes = [
        PenStroke(
            [_page_to_bed(point, paper_size_mm, origin_mm, profile) for point in stroke.polyline],
            stroke.width_mm,
            stroke.color,
            stroke.pen_up,
        )
        for stroke in strokes
    ]
    return strokes, _outlines(profile, origin_mm, paper_size_mm, px_per_mm), canvas_mm


@click.command(name="preview")
@click.argument("drawing", type=click.Path(exists=True, path_type=Path))
@click.option(
    "-o",
    "--output",
    "output_path",
    required=True,
    type=click.Path(path_type=Path),
    help="Path of the preview image to write (PNG).",
)
@click.option(
    "--dpi",
    "dpi",
    type=float,
    default=None,
    help=f"Resolution in dots per inch (converted with /25.4). Default: {DEFAULT_DPI:g} DPI "
    f"({DEFAULT_PX_PER_MM:g} px/mm).",
)
@click.option(
    "--px-per-mm",
    "px_per_mm_option",
    type=float,
    default=None,
    help=f"Resolution in pixels per millimetre. Default: {DEFAULT_PX_PER_MM:g}. "
    "Mutually exclusive with --dpi.",
)
@click.option(
    "--force",
    is_flag=True,
    help="Render even if the image exceeds 40 MP (bypasses only the pixel budget).",
)
@click.option(
    "--paper-color",
    default="#FFFFFF",
    show_default=True,
    help="Paper background colour (hex or named CSS colour).",
)
@click.option(
    "--layer",
    "layer_label",
    default=None,
    help=(
        "Only preview this pen layer (layer label or id). Default: all layers. "
        "G-code bed and page outlines stay visible."
    ),
)
@click.option(
    "--travel/--no-travel",
    default=False,
    show_default=True,
    help="Draw pen-up travel moves as thin light lines.",
)
def preview_cmd(
    drawing: Path,
    output_path: Path,
    dpi: float | None,
    px_per_mm_option: float | None,
    force: bool,
    paper_color: str,
    layer_label: str | None,
    travel: bool,
) -> None:
    """Render a simulated plot of DRAWING to an image.

    DRAWING is an SVG or a .gcode file; arcs (G2/G3) are not supported and
    other G-code dialects are out of scope. Strokes are drawn with the core plot
    simulator at the requested resolution. ``--dpi`` is real dots per inch and
    ``--px-per-mm`` is pixels per millimetre; they are mutually exclusive, and
    the default is 4 px/mm (about 101 DPI). A raster over 40 MP is refused
    before allocation unless ``--force`` is given. For G-code naming a known
    profile the canvas is the machine bed, with a thin grey bed and page outline
    under the ink; the header's page_origin places the page. ``--layer`` filters
    the ink only, leaving both outlines visible. ``--travel`` also draws pen-up
    moves as thin light lines under the ink; the default stays ink-only. All
    messages go to stderr, so stdout stays usable in a pipeline.
    """
    px_per_mm = resolve_px_per_mm(dpi, px_per_mm_option, DEFAULT_PX_PER_MM)

    outlines: list[PenStroke] = []
    if drawing.suffix.lower() == ".gcode":
        try:
            strokes, outlines, (width_mm, height_mm) = _preview_gcode(
                drawing, layer_label, travel, px_per_mm
            )
        except OSError as exc:
            raise click.ClickException(f"Could not read G-code: {exc}") from exc
    else:
        try:
            strokes = parse_svg_strokes(drawing, layer=layer_label, include_pen_up=travel)
        except (ET.ParseError, OSError, ValueError) as exc:
            raise click.ClickException(f"Could not parse SVG: {exc}") from exc
        width_mm, height_mm = _paper_size_mm(drawing)
    if not strokes:
        raise click.ClickException("No pen strokes found in drawing (check --layer if used)")

    enforce_render_budget(width_mm, height_mm, px_per_mm, force=force)
    try:
        image = simulate_plot(
            [*outlines, *strokes],
            paper_width_mm=width_mm,
            paper_height_mm=height_mm,
            paper_color=paper_color,
            dpi_px_per_mm=px_per_mm,
            travel_color=TRAVEL_COLOR if travel else None,
            travel_width_mm=TRAVEL_WIDTH_MM,
        )
    except ValueError as exc:
        raise click.BadParameter(str(exc), param_hint="--paper-color") from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    console.print(
        f"Preview saved to {output_path} "
        f"({image.width}x{image.height} px, {width_mm:g}x{height_mm:g} mm)"
    )


__all__ = ["preview_cmd"]
