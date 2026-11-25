"""``penpath preview`` - render a simulated plot of an SVG or G-code file."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import click
from rich.console import Console

from penpath.core import (
    GcodePreviewError,
    PenStroke,
    ProfileError,
    gcode_to_strokes,
    get_svg_paper_size,
    load_profile,
    parse_gcode_header,
    parse_svg_strokes,
    simulate_plot,
)
from penpath.presets.palettes import STABILO_88
from penpath.presets.pens import PEN_PRESETS

DEFAULT_PX_PER_MM = 10.0
FALLBACK_PAPER_MM = (210.0, 297.0)

console = Console(stderr=True)


def _paper_size_mm(svg_path: Path) -> tuple[float, float]:
    """Return the SVG page size in mm, falling back to A4 when unreadable."""
    return get_svg_paper_size(svg_path) or FALLBACK_PAPER_MM


def _pen_styles() -> dict[str, tuple[str, float]]:
    """Map built-in pen names to the colour and width used in their SVG."""
    styles = {pen.name: (pen.color, pen.width_mm) for pen in STABILO_88.pens}
    styles.update({name: (pen.color, pen.width) for name, pen in PEN_PRESETS.items()})
    return styles


def _preview_gcode(
    path: Path, layer_label: str | None
) -> tuple[list[PenStroke], tuple[float, float]]:
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
        strokes = gcode_to_strokes(text, paper_size_mm, profile, _pen_styles(), layer_label)
    except GcodePreviewError as exc:
        raise click.ClickException(f"Could not preview G-code: {exc}") from exc
    return strokes, paper_size_mm


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
    "px_per_mm",
    type=float,
    default=DEFAULT_PX_PER_MM,
    show_default=True,
    help="Resolution in pixels per millimetre.",
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
    help="Only preview this pen layer (layer label or id). Default: all layers.",
)
def preview_cmd(
    drawing: Path,
    output_path: Path,
    px_per_mm: float,
    paper_color: str,
    layer_label: str | None,
) -> None:
    """Render a simulated plot of DRAWING to an image.

    DRAWING is an SVG or a .gcode file; arcs (G2/G3) are not supported and
    other G-code dialects are out of scope. Strokes are drawn with the core plot
    simulator at the requested resolution. All messages go to stderr, so stdout
    stays usable in a pipeline.
    """
    if px_per_mm <= 0:
        raise click.BadParameter("must be greater than zero", param_hint="--dpi")

    if drawing.suffix.lower() == ".gcode":
        try:
            strokes, (width_mm, height_mm) = _preview_gcode(drawing, layer_label)
        except OSError as exc:
            raise click.ClickException(f"Could not read G-code: {exc}") from exc
    else:
        try:
            strokes = parse_svg_strokes(drawing, layer=layer_label)
        except (ET.ParseError, OSError, ValueError) as exc:
            raise click.ClickException(f"Could not parse SVG: {exc}") from exc
        width_mm, height_mm = _paper_size_mm(drawing)
    if not strokes:
        raise click.ClickException("No pen strokes found in drawing (check --layer if used)")

    try:
        image = simulate_plot(
            strokes,
            paper_width_mm=width_mm,
            paper_height_mm=height_mm,
            paper_color=paper_color,
            dpi_px_per_mm=px_per_mm,
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
