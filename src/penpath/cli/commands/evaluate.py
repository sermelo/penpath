"""``penpath evaluate`` - score likeness and machine cost of a pen plot."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import cast

import click
from PIL import Image, UnidentifiedImageError
from rich.console import Console
from rich.table import Table

from penpath.cli.commands._resolution import enforce_render_budget, resolve_px_per_mm
from penpath.core import (
    compute_edge_likeness,
    compute_layer_coverage,
    compute_likeness,
    compute_machine_cost,
    compute_masked_likeness,
    get_image_placement,
    get_layer_pen_names,
    get_svg_paper_size,
    parse_svg_strokes,
    simulate_plot,
)
from penpath.core.simulation import LayerMetrics, MachineCostResult

DEFAULT_DPI = 96.0
DEFAULT_PX_PER_MM = DEFAULT_DPI / 25.4
FALLBACK_PAPER_MM = (210.0, 297.0)

console = Console(stderr=True)


def _pen_name(metrics: LayerMetrics, layer: str) -> str:
    """Return the pen name added to a per-layer machine-cost row."""
    return cast(str, cast(dict[str, object], metrics).get("pen", layer))


def _cost_table(cost: MachineCostResult) -> Table:
    """Build the human-readable machine cost table."""
    table = Table(title="Machine Cost", show_header=True, header_style="bold", padding=(0, 0))
    table.add_column("Layer", style="cyan")
    table.add_column("Pen", style="cyan", overflow="fold")
    table.add_column("Draw mm", justify="right")
    table.add_column("Travel mm", justify="right")
    table.add_column("Lifts", justify="right")
    table.add_column("Short", justify="right")
    table.add_column("Strokes", justify="right")
    table.add_column("Ink %", justify="right")

    per_layer = cast(dict[str, LayerMetrics], cost["per_layer"])
    for layer, metrics in per_layer.items():
        table.add_row(
            layer,
            _pen_name(metrics, layer),
            f"{metrics['drawing_length_mm']:.2f}",
            f"{metrics['pen_up_travel_mm']:.2f}",
            str(metrics["num_lifts"]),
            str(metrics["num_short_segments"]),
            str(metrics["num_strokes"]),
            f"{metrics['ink_coverage_pct']:.1f}",
        )

    total = cast(LayerMetrics, cost["total"])
    table.add_row(
        "TOTAL",
        "",
        f"{total['drawing_length_mm']:.2f}",
        f"{total['pen_up_travel_mm']:.2f}",
        str(total["num_lifts"]),
        str(total["num_short_segments"]),
        str(total["num_strokes"]),
        f"{total['ink_coverage_pct']:.1f}",
        style="bold",
    )
    return table


@click.command(name="evaluate")
@click.argument("image", type=click.Path(exists=True, path_type=Path))
@click.argument("drawing_svg", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Print only JSON on stdout (for scripts and agents).",
)
@click.option(
    "--dpi",
    "dpi",
    type=float,
    default=None,
    help="Resolution in dots per inch (converted with /25.4). "
    f"Default: {DEFAULT_DPI:g} DPI ({DEFAULT_PX_PER_MM:g} px/mm).",
)
@click.option(
    "--px-per-mm",
    "px_per_mm_option",
    type=float,
    default=None,
    help="Resolution in pixels per millimetre (shared by simulation and likeness). "
    f"Default: {DEFAULT_PX_PER_MM:g}. Mutually exclusive with --dpi.",
)
@click.option(
    "--force",
    is_flag=True,
    help="Evaluate even if the simulation exceeds 40 MP (bypasses only the pixel budget).",
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
    help="Only evaluate this pen layer (layer label or id). Default: all layers.",
)
@click.option(
    "--coverage-warn",
    "coverage_warn_pct",
    type=click.FloatRange(min=0),
    default=50.0,
    show_default=True,
    metavar="PCT",
    help="Warn on stderr when a layer covers more than this percentage of the page "
    "(0 disables the warning; must be >= 0).",
)
def evaluate_cmd(
    image: Path,
    drawing_svg: Path,
    as_json: bool,
    dpi: float | None,
    px_per_mm_option: float | None,
    force: bool,
    paper_color: str,
    layer_label: str | None,
    coverage_warn_pct: float,
) -> None:
    """Evaluate DRAWING_SVG against the original IMAGE.

    ``--dpi`` is real dots per inch and ``--px-per-mm`` is pixels per
    millimetre; they are mutually exclusive, and the default is 96 DPI
    (96/25.4 px/mm). A simulation over 40 MP is refused before allocation
    unless ``--force`` is given. The SVG is simulated at the chosen resolution,
    cropped to the recorded image placement, and scored with greyscale SSIM over
    the whole page, greyscale SSIM over the source image's ink only, and edge
    SSIM. Whole-page greyscale SSIM misses pale ink on a near-blank page and
    rewards agreeing
    with mostly-white paper; ink-only SSIM averages the same SSIM map over the
    source ink pixels instead. Edge SSIM compares Sobel edge maps and penalises
    spurious structure. Machine cost, ink coverage and the pen name from the
    SVG layer are reported per pen layer and in total; a layer covering most of
    the page warns on stderr. With --json, only a JSON object is written to
    stdout.
    """
    px_per_mm = resolve_px_per_mm(dpi, px_per_mm_option, DEFAULT_PX_PER_MM)

    try:
        with Image.open(image) as opened:
            original_size = opened.size
            original = opened.convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise click.ClickException(f"Could not read image: {exc}") from exc

    try:
        strokes = parse_svg_strokes(drawing_svg, layer=layer_label, include_pen_up=True)
    except (ET.ParseError, OSError, ValueError) as exc:
        raise click.ClickException(f"Could not parse SVG: {exc}") from exc
    if not strokes:
        raise click.ClickException("No pen strokes found in SVG")

    try:
        pen_names = get_layer_pen_names(drawing_svg)
    except (ET.ParseError, OSError, ValueError) as exc:
        raise click.ClickException(f"Could not parse SVG pen names: {exc}") from exc

    try:
        placement = get_image_placement(drawing_svg, original_size)
    except (ET.ParseError, OSError, ValueError) as exc:
        raise click.ClickException(f"Could not read image placement: {exc}") from exc

    width_mm, height_mm = get_svg_paper_size(drawing_svg) or FALLBACK_PAPER_MM
    enforce_render_budget(width_mm, height_mm, px_per_mm, force=force)
    try:
        simulated = simulate_plot(
            strokes,
            paper_width_mm=width_mm,
            paper_height_mm=height_mm,
            paper_color=paper_color,
            dpi_px_per_mm=px_per_mm,
        )
    except ValueError as exc:
        raise click.BadParameter(str(exc), param_hint="--paper-color") from exc
    placement_rect = (placement.x, placement.y, placement.width, placement.height)
    likeness = compute_likeness(
        simulated,
        original,
        placement_rect,
        dpi_px_per_mm=px_per_mm,
    )
    masked_likeness = compute_masked_likeness(
        simulated,
        original,
        placement_rect,
        dpi_px_per_mm=px_per_mm,
    )
    edge_likeness = compute_edge_likeness(
        simulated,
        original,
        placement_rect,
        dpi_px_per_mm=px_per_mm,
    )
    cost = compute_machine_cost(strokes)
    coverage = compute_layer_coverage(strokes, width_mm, height_mm, dpi_px_per_mm=px_per_mm)
    per_layer_cost = cast(dict[str, LayerMetrics], cost["per_layer"])
    for layer, metrics in per_layer_cost.items():
        metrics["ink_coverage_pct"] = coverage.per_layer.get(layer, 0.0)
        cast(dict[str, object], metrics)["pen"] = pen_names.get(layer, layer)
    total_cost = cast(LayerMetrics, cost["total"])
    total_cost["ink_coverage_pct"] = coverage.total

    if coverage_warn_pct > 0:
        for layer, percentage in coverage.per_layer.items():
            if percentage > coverage_warn_pct:
                console.print(
                    f"Warning: layer {layer} covers {percentage:.1f}% of the page "
                    f"(above --coverage-warn {coverage_warn_pct:g}%). "
                    "Check --background-threshold / --saturation: pale areas may be "
                    "filling the page."
                )

    if as_json:
        click.echo(
            json.dumps(
                {
                    "likeness": likeness,
                    "masked_likeness": masked_likeness,
                    "edge_likeness": edge_likeness,
                    "machine_cost": cost,
                },
                indent=2,
            )
        )
        return

    console.print(f"Evaluation: {drawing_svg.name} vs {image.name}")
    console.print()
    table = Table(title="Likeness", show_header=True, header_style="bold")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")
    table.add_row("SSIM (whole page)", f"{likeness:.4f}")
    table.add_row("SSIM (ink only)", f"{masked_likeness:.4f}")
    table.add_row("Edge SSIM", f"{edge_likeness:.4f}")
    console.print(table)
    console.print()
    console.print(_cost_table(cost))


__all__ = ["evaluate_cmd"]
