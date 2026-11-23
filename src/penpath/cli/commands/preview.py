"""``penpath preview`` - render a simulated plot of an SVG to an image."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import click
from rich.console import Console

from penpath.core import get_svg_paper_size, parse_svg_strokes, simulate_plot

DEFAULT_PX_PER_MM = 10.0
FALLBACK_PAPER_MM = (210.0, 297.0)

console = Console(stderr=True)


def _paper_size_mm(svg_path: Path) -> tuple[float, float]:
    """Return the SVG page size in mm, falling back to A4 when unreadable."""
    return get_svg_paper_size(svg_path) or FALLBACK_PAPER_MM


@click.command(name="preview")
@click.argument("drawing_svg", type=click.Path(exists=True, path_type=Path))
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
    drawing_svg: Path,
    output_path: Path,
    px_per_mm: float,
    paper_color: str,
    layer_label: str | None,
) -> None:
    """Render a simulated plot of DRAWING_SVG to an image.

    DRAWING_SVG is read with the penpath SVG parser; its strokes are drawn with
    the core plot simulator at the requested resolution. All messages go to
    stderr so stdout stays usable in a pipeline.
    """
    if px_per_mm <= 0:
        raise click.BadParameter("must be greater than zero", param_hint="--dpi")

    try:
        strokes = parse_svg_strokes(drawing_svg, layer=layer_label)
    except (ET.ParseError, OSError, ValueError) as exc:
        raise click.ClickException(f"Could not parse SVG: {exc}") from exc
    if not strokes:
        raise click.ClickException("No pen strokes found in SVG (check --layer if used)")

    width_mm, height_mm = _paper_size_mm(drawing_svg)
    image = simulate_plot(
        strokes,
        paper_width_mm=width_mm,
        paper_height_mm=height_mm,
        paper_color=paper_color,
        dpi_px_per_mm=px_per_mm,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    console.print(
        f"Preview saved to {output_path} "
        f"({image.width}x{image.height} px, {width_mm:g}x{height_mm:g} mm)"
    )


__all__ = ["preview_cmd"]
