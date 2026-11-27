"""``penpath compare`` - render a contact sheet of every PFM and preset."""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console

from penpath.core import ImageLoadError, load_image, render_contact_sheet
from penpath.presets import list_sheet_entries

DEFAULT_DPI = 4.0
DEFAULT_MAX_RESOLUTION = 256
DEFAULT_COLUMNS = 4

console = Console(stderr=True, soft_wrap=True)


@click.command(name="compare")
@click.argument("input_path", metavar="INPUT", type=click.Path(exists=True, path_type=Path))
@click.option(
    "-o",
    "--output",
    "output_path",
    required=True,
    type=click.Path(path_type=Path),
    help="Path of the contact sheet to write (PNG).",
)
@click.option(
    "--dpi",
    type=float,
    default=DEFAULT_DPI,
    show_default=True,
    help="Resolution in pixels per millimetre for the tiles.",
)
@click.option(
    "--max-resolution",
    type=int,
    default=DEFAULT_MAX_RESOLUTION,
    show_default=True,
    help="Longest side of the working image in pixels; larger images are downscaled.",
)
@click.option(
    "--columns",
    type=int,
    default=DEFAULT_COLUMNS,
    show_default=True,
    help="Number of tiles per row.",
)
@click.option(
    "--paper-color",
    default="#FFFFFF",
    show_default=True,
    help="Tile paper colour (hex or named CSS colour).",
)
def compare_cmd(
    input_path: Path,
    output_path: Path,
    dpi: float,
    max_resolution: int,
    columns: int,
    paper_color: str,
) -> None:
    """Render one labelled tile per PFM and preset on INPUT into a contact sheet.

    The catalog holds every registered PFM's default and presets (the legacy
    ``default`` preset is a duplicate). A failing entry becomes an error tile
    reported on stderr; stdout stays empty. There is no per-tile timeout: use
    the shell's ``timeout`` and the ``--max-resolution`` / ``--dpi`` flags.
    """
    if dpi <= 0:
        raise click.BadParameter("must be greater than zero", param_hint="--dpi")
    if max_resolution <= 0:
        raise click.BadParameter("must be greater than zero", param_hint="--max-resolution")
    if columns <= 0:
        raise click.BadParameter("must be greater than zero", param_hint="--columns")

    try:
        image = load_image(input_path)
    except (ImageLoadError, OSError) as exc:
        raise click.ClickException(f"Could not load image {input_path}: {exc}") from exc

    entries = list_sheet_entries()
    if not entries:
        raise click.ClickException("No contact sheet entries found (check PFM registrations)")

    try:
        result = render_contact_sheet(
            image,
            entries,
            max_resolution=max_resolution,
            dpi=dpi,
            columns=columns,
            paper_color=paper_color,
        )
    except ValueError as exc:
        raise click.BadParameter(str(exc), param_hint="--paper-color") from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.image.save(output_path, format="PNG")

    for label, message in result.errors.items():
        console.print(f"Failed entry {label}: {message}")
    console.print(
        f"Contact sheet saved to {output_path} "
        f"({result.image.width}x{result.image.height} px, {len(entries)} entries)"
    )


__all__ = ["compare_cmd"]
