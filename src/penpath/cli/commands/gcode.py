"""``penpath gcode`` - turn a reviewed SVG into machine G-code."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import cast

import click
from rich.console import Console

from penpath.core import (
    FitResult,
    GcodeError,
    MachineProfile,
    ProfileError,
    UnknownProfileError,
    build_gcode,
    compute_machine_cost,
    fit_layers_to_drawable,
    get_svg_paper_size,
    list_profiles,
    load_profile,
    parse_svg_layers,
    parse_svg_strokes,
    with_margin_mm,
)
from penpath.core.simulation import LayerMetrics

console = Console(stderr=True, soft_wrap=True)


class ProfileValidationError(click.ClickException):
    """Invalid profile file or unreachable drawing; maps to exit code 3."""

    exit_code = 3


def _available_hint(profiles_path: Path | None) -> str:
    """Return the profile names for an actionable usage error."""
    try:
        available = ", ".join(list_profiles(profiles_path))
    except ProfileError:
        return "Run 'penpath info profiles' to list the available profiles."
    return f"Available profiles: {available}"


def _estimate_plot_seconds(profile: MachineProfile, total: LayerMetrics) -> float:
    """Estimate plot time from the profile's draw, travel and Z feeds.

    Z travel is one down and one up per stroke plus a final lift, over the
    distance between ``z_up`` and ``z_down``.
    """
    draw_seconds = float(total["drawing_length_mm"]) / profile.feed.draw_mm_s
    travel_seconds = float(total["pen_up_travel_mm"]) / profile.feed.travel_mm_s
    stroke_count = int(total["num_strokes"])
    z_moves = 2 * stroke_count + 1 if stroke_count else 0
    z_distance = z_moves * abs(profile.pen.z_up - profile.pen.z_down)
    z_seconds = z_distance / profile.feed.effective_z_mm_s
    return draw_seconds + travel_seconds + z_seconds


@click.command(name="gcode")
@click.argument("drawing_svg", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--profile",
    "profile_name",
    default=None,
    help="Machine profile name (required). Run 'penpath info profiles' to list them.",
)
@click.option(
    "--margin",
    "margin_mm",
    type=click.FloatRange(min=0),
    default=None,
    help=(
        "Override the profile safety margin for this run in mm; "
        "0 is allowed but not recommended on the Aquila."
    ),
)
@click.option(
    "-o",
    "--output",
    "output_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Output .gcode path (default: <input>.gcode beside the input).",
)
@click.option(
    "--profiles",
    "profiles_path",
    type=click.Path(path_type=Path),
    default=None,
    help="User profiles YAML file (default: $XDG_CONFIG_HOME/penpath/profiles.yaml).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Write the G-code to stdout instead of a file; all messages go to stderr.",
)
@click.option(
    "--fit/--no-fit",
    default=True,
    help=(
        "Fit a drawing that exceeds the machine's drawable area (default). "
        "With --no-fit, a point outside the area is an error (exit 3)."
    ),
)
def gcode_cmd(
    drawing_svg: Path,
    profile_name: str | None,
    margin_mm: float | None,
    output_path: Path | None,
    profiles_path: Path | None,
    dry_run: bool,
    fit: bool,
) -> None:
    """Turn DRAWING_SVG into G-code for the machine named by --profile.

    Inkscape pen layers become G-code layers in document order, with one pen
    change per used layer as described by the profile. Layers with no strokes
    are skipped, so an unused pen never triggers a pause.

    Penpath does not guess the machine: --profile is required, and a missing or
    unknown name is a usage error (exit 2) that lists the available profiles.
    An unreadable or invalid profile file is a validation error (exit 3). A
    drawing outside the machine's drawable area is fitted by default, with a
    warning on stderr naming the change; --no-fit keeps it an exit-3 error.
    --margin overrides the profile's safety margin for this run before fitting
    and emission. With --dry-run, stdout holds only G-code; every message goes
    to stderr.
    """
    if profile_name is None:
        raise click.UsageError(f"Missing option '--profile'. {_available_hint(profiles_path)}")

    if profiles_path is not None and not profiles_path.is_file():
        raise ProfileValidationError(
            f"Cannot read profile file {profiles_path}: no such file. "
            "Pass an existing YAML file to --profiles, or omit it to use the default."
        )

    try:
        profile = load_profile(profile_name, profiles_path)
    except UnknownProfileError as exc:
        raise click.UsageError(str(exc)) from exc
    except ProfileError as exc:
        raise ProfileValidationError(str(exc)) from exc

    if margin_mm is not None:
        profile = with_margin_mm(profile, margin_mm)

    try:
        strokes = parse_svg_strokes(drawing_svg)
    except (ET.ParseError, OSError, ValueError) as exc:
        raise click.ClickException(f"Could not parse SVG: {exc}") from exc
    if not strokes:
        raise click.ClickException(f"No pen strokes found in {drawing_svg}")

    page_size = get_svg_paper_size(drawing_svg)
    if page_size is None:
        raise click.ClickException(
            f"Could not read the page size from {drawing_svg}; set width and height in mm"
        )

    layers = parse_svg_layers(drawing_svg)
    layer_count = sum(1 for layer in layers if any(len(line) >= 2 for line in layer.polylines))
    fit_result: FitResult | None = None
    if fit:
        try:
            fit_result = fit_layers_to_drawable(layers, profile, page_size)
        except GcodeError as exc:
            raise ProfileValidationError(str(exc)) from exc
        emit_layers = fit_result.layers
    else:
        emit_layers = layers
    try:
        text = build_gcode(emit_layers, profile, page_size)
    except GcodeError as exc:
        message = str(exc)
        if not fit:
            message += " Pass --fit (the default) or use a smaller --paper."
        raise ProfileValidationError(message) from exc

    if fit_result is not None and fit_result.changed:
        overshoot_x, overshoot_y = fit_result.overshoot_mm
        shift_x, shift_y = fit_result.offset_mm
        console.print(
            f"Warning: drawing is {max(overshoot_x, overshoot_y):.3f} mm past the "
            f"{profile.name} drawable area; fitted with scale {fit_result.scale:.3f} "
            f"and shift ({shift_x:.3f}, {shift_y:.3f}) mm"
        )

    strokes_with_travel = parse_svg_strokes(drawing_svg, include_pen_up=True)
    total = cast(LayerMetrics, compute_machine_cost(strokes_with_travel)["total"])

    if dry_run:
        click.echo(text, nl=False)
    else:
        destination = output_path if output_path is not None else drawing_svg.with_suffix(".gcode")
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(text, encoding="utf-8", newline="\n")
        except OSError as exc:
            raise click.ClickException(f"Could not write G-code to {destination}: {exc}") from exc
        console.print(f"G-code saved to: {destination}")

    console.print("G-code summary")
    console.print(f"  Profile: {profile.name}")
    console.print(f"  Layers: {layer_count}")
    console.print(f"  Drawing length: {float(total['drawing_length_mm']):.2f} mm")
    console.print(f"  Pen-up travel: {float(total['pen_up_travel_mm']):.2f} mm")
    console.print(f"  Pen lifts: {int(total['num_lifts'])}")
    console.print(f"  Estimated plot time: {_estimate_plot_seconds(profile, total):.1f} s")


__all__ = ["gcode_cmd"]
