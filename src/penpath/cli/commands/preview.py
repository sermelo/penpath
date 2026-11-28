"""``penpath preview`` - render a simulated plot of an SVG or G-code file."""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console

from penpath.cli.commands._resolution import resolve_px_per_mm
from penpath.core import (
    DEFAULT_PX_PER_MM,
    InvalidPaperColorError,
    PreviewError,
    RenderBudgetError,
    render_preview,
)

DEFAULT_DPI = DEFAULT_PX_PER_MM * 25.4

console = Console(stderr=True)


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
    try:
        result = render_preview(
            drawing,
            output_path,
            px_per_mm=px_per_mm,
            force=force,
            paper_color=paper_color,
            layer=layer_label,
            travel=travel,
        )
    except RenderBudgetError as exc:
        raise click.ClickException(
            f"Render too large: {exc.detail}. Lower --px-per-mm (or --dpi) or pass --force."
        ) from exc
    except InvalidPaperColorError as exc:
        raise click.BadParameter(str(exc), param_hint="--paper-color") from exc
    except PreviewError as exc:
        raise click.ClickException(str(exc)) from exc
    for warning in result.warnings:
        console.print(warning)
    console.print(
        f"Preview saved to {result.path} "
        f"({result.width_px}x{result.height_px} px, {result.width_mm:g}x{result.height_mm:g} mm)"
    )


__all__ = ["preview_cmd"]
