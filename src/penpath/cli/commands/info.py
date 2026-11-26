"""Info command for penpath - show presets, capabilities, and image details."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click
from rich.console import Console
from rich.table import Table

from penpath.cli.config import load_config
from penpath.cli.palettes import resolve_palette
from penpath.core import ProfileError, list_profile_sources, load_profile
from penpath.core.drawing.registry import get_pfm, list_pfms
from penpath.core.image.load import load_image
from penpath.core.image.pipeline import list_filters
from penpath.core.image.resolution import plan_working_resolution
from penpath.core.image.separate import palette_match
from penpath.core.models import Paper
from penpath.presets.palettes import get_palette, list_palettes
from penpath.presets.papers import get_paper, list_papers
from penpath.presets.pens import get_pen, list_pens
from penpath.presets.pfms import list_pfm_presets

if TYPE_CHECKING:
    pass

console = Console()


def _output_format(data: dict[str, Any], fmt: str) -> None:
    """Output data in the specified format."""
    if fmt == "json":
        console.print_json(json.dumps(data, indent=2, default=str))
    elif fmt == "yaml":
        import yaml

        console.print(yaml.dump(data, default_flow_style=False, sort_keys=False), soft_wrap=True)
    else:  # table
        _print_table(data)


def _print_table(data: dict[str, Any]) -> None:
    """Print data as a rich table."""
    for key, value in data.items():
        if isinstance(value, list):
            table = Table(title=key.replace("_", " ").title())
            if value and isinstance(value[0], dict):
                # Add columns from first item
                for col in value[0]:
                    table.add_column(col)
                for item in value:
                    table.add_row(*[str(item.get(c, "")) for c in value[0]])
            else:
                table.add_column("Value")
                for item in value:
                    table.add_row(str(item))
            console.print(table)
        elif isinstance(value, dict):
            table = Table(title=key.replace("_", " ").title())
            table.add_column("Property")
            table.add_column("Value")
            for k, v in value.items():
                table.add_row(k, str(v))
            console.print(table)
        else:
            console.print(f"[bold]{key}:[/bold] {value}")


def _print_palette_match_table(data: dict[str, Any]) -> None:
    """Print one row per palette pen plus the unassigned share."""
    table = Table(title=f"Palette Match: {data['path']} ({data['width']}x{data['height']})")
    for column in ("Order", "Pen name", "Colour", "Pixels", "Percent"):
        table.add_column(column)
    for row in data["rows"]:
        table.add_row(
            str(row["order"]),
            row["name"],
            row["color"],
            str(row["pixels"]),
            f"{row['percent']:.1f}%",
        )
    table.add_row(
        "-",
        "(unassigned)",
        "-",
        str(data["unassigned_pixels"]),
        f"{data['unassigned_percent']:.1f}%",
    )
    console.print(table)


@click.group(name="info")
def info_group() -> None:
    """Show information about presets, capabilities, and images."""


@info_group.command(name="pens")
@click.option("--format", "fmt", type=click.Choice(["table", "json", "yaml"]), default="table")
@click.option(
    "--config", "-c", "config_path", type=click.Path(path_type=Path), help="Config file path"
)
def info_pens(fmt: str, config_path: Path | None) -> None:
    """List built-in pen presets."""
    config = load_config(config_path)

    # Built-in presets
    builtin_pens = []
    for name in list_pens():
        pen = get_pen(name)
        builtin_pens.append(
            {
                "name": name,
                "width_mm": pen.width,
                "color": pen.color,
                "opacity": pen.opacity,
                "source": "builtin",
            }
        )

    # Config presets
    config_pens = []
    for name, pen in config.pens.items():
        config_pens.append(
            {
                "name": name,
                "width_mm": pen.width,
                "color": pen.color,
                "opacity": pen.opacity,
                "source": "config",
            }
        )

    data = {"builtin_pens": builtin_pens, "config_pens": config_pens}
    _output_format(data, fmt)


@info_group.command(name="papers")
@click.option("--format", "fmt", type=click.Choice(["table", "json", "yaml"]), default="table")
@click.option(
    "--config", "-c", "config_path", type=click.Path(path_type=Path), help="Config file path"
)
def info_papers(fmt: str, config_path: Path | None) -> None:
    """List built-in paper presets."""
    config = load_config(config_path)

    # Built-in presets
    builtin_papers = []
    for name in list_papers():
        paper = get_paper(name)
        builtin_papers.append(
            {
                "name": name,
                "width_mm": paper.width,
                "height_mm": paper.height,
                "margin_mm": paper.margin,
                "source": "builtin",
            }
        )

    # Config presets
    config_papers = []
    for name, paper in config.papers.items():
        config_papers.append(
            {
                "name": name,
                "width_mm": paper.width,
                "height_mm": paper.height,
                "margin_mm": paper.margin,
                "source": "config",
            }
        )

    data = {"builtin_papers": builtin_papers, "config_papers": config_papers}
    _output_format(data, fmt)


@info_group.command(name="palettes")
@click.option("--format", "fmt", type=click.Choice(["table", "json", "yaml"]), default="table")
def info_palettes(fmt: str) -> None:
    """List built-in palettes and their pens in drawing order."""
    builtin_palettes = []
    palette_pens = []
    for name in list_palettes():
        palette = get_palette(name)
        builtin_palettes.append({"name": name, "pen_count": len(palette.pens), "source": "builtin"})
        for order, pen in enumerate(palette.pens, start=1):
            palette_pens.append(
                {
                    "palette": name,
                    "order": order,
                    "name": pen.name,
                    "width_mm": pen.width_mm,
                    "color": pen.color,
                }
            )

    data = {"builtin_palettes": builtin_palettes, "palette_pens": palette_pens}
    _output_format(data, fmt)


@info_group.command(name="palette-match")
@click.argument("image_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--palette",
    "palette_spec",
    default="stabilo_88",
    show_default=True,
    help="Built-in palette name or inline 'name=width,#hex;...'",
)
@click.option("--format", "fmt", type=click.Choice(["table", "json", "yaml"]), default="table")
def info_palette_match(image_path: Path, palette_spec: str, fmt: str) -> None:
    """Show which palette pens raw colour separation picks for an image.

    IMAGE_PATH: Image to measure before any filter, masking or drawing
    """
    palette = resolve_palette(palette_spec)
    try:
        image = load_image(image_path)
    except Exception as e:
        raise click.ClickException(f"Failed to load image: {e}") from e
    try:
        match = palette_match(image, palette.pens)
    except ValueError as e:
        raise click.ClickException(str(e)) from e

    data: dict[str, Any] = {
        "path": str(image_path),
        "palette": palette.name,
        "width": match.width,
        "height": match.height,
        "rows": [
            {
                "order": row.order,
                "name": row.name,
                "color": row.color,
                "pixels": row.pixels,
                "percent": row.percent,
            }
            for row in match.rows
        ],
        "unassigned_pixels": match.unassigned_pixels,
        "unassigned_percent": match.unassigned_percent,
    }
    if fmt == "table":
        _print_palette_match_table(data)
    else:
        _output_format(data, fmt)


@info_group.command(name="pfms")
@click.option("--format", "fmt", type=click.Choice(["table", "json", "yaml"]), default="table")
def info_pfms(fmt: str) -> None:
    """List available PFMs (Pen Follower Modules)."""
    registered = list_pfms()
    presets = list_pfm_presets()

    pfm_data = []
    for name in registered:
        _, settings_model = get_pfm(name)
        # Get default settings
        default_settings = settings_model()
        pfm_data.append(
            {
                "name": name,
                "settings_model": settings_model.__name__,
                "default_settings": default_settings.model_dump(),
                "presets": [p for p in presets if p.startswith(name) or name == "sketch_lines"],
            }
        )

    data = {"available_pfms": pfm_data, "presets": presets}
    _output_format(data, fmt)


def _format_margin_mm(margin: float | tuple[float, ...] | list[float]) -> str:
    """Format a raw profile margin as ``10`` or ``10/5/10/5``."""
    if isinstance(margin, (tuple, list)):
        return "/".join(f"{value:g}" for value in margin)
    return f"{margin:g}"


def _print_profile_table(profiles: list[dict[str, Any]]) -> None:
    """Print profile rows as a compact table with readable descriptions."""
    table = Table(title="Machine Profiles")
    table.add_column("Name", no_wrap=True)
    table.add_column("Source", no_wrap=True)
    table.add_column("Bed (mm)", no_wrap=True)
    table.add_column("Margin (mm)", no_wrap=True)
    table.add_column("Travel", no_wrap=True)
    table.add_column("Draw", no_wrap=True)
    table.add_column("Z", no_wrap=True)
    table.add_column("Description")
    for row in profiles:
        table.add_row(
            row["name"],
            row["source"],
            f"{row['bed_width_mm']:g} x {row['bed_height_mm']:g}",
            _format_margin_mm(row["margin_mm"]),
            f"{row['travel_mm_s']:g}",
            f"{row['draw_mm_s']:g}",
            f"{row['z_mm_s']:g}",
            row["description"],
        )
    Console(width=max(console.width, 120)).print(table)


@info_group.command(name="profiles")
@click.option("--format", "fmt", type=click.Choice(["table", "json", "yaml"]), default="table")
def info_profiles(fmt: str) -> None:
    """List built-in and user machine profiles with their bed, margin and feeds."""
    try:
        sources = list_profile_sources()
        profile_data = []
        for name, source in sources.items():
            profile = load_profile(name)
            margin = profile.bed.margin_mm
            profile_data.append(
                {
                    "name": name,
                    "source": source,
                    "description": profile.description,
                    "bed_width_mm": profile.bed.size_mm[0],
                    "bed_height_mm": profile.bed.size_mm[1],
                    "margin_mm": list(margin) if isinstance(margin, tuple) else margin,
                    "travel_mm_s": profile.feed.travel_mm_s,
                    "draw_mm_s": profile.feed.draw_mm_s,
                    "z_mm_s": profile.feed.effective_z_mm_s,
                }
            )
    except ProfileError as exc:
        raise click.ClickException(str(exc)) from exc

    if fmt == "table":
        _print_profile_table(profile_data)
    else:
        _output_format({"profiles": profile_data}, fmt)


@info_group.command(name="filters")
@click.option("--format", "fmt", type=click.Choice(["table", "json", "yaml"]), default="table")
def info_filters(fmt: str) -> None:
    """List available image filters with parameters."""
    filters = list_filters()

    # Define filter parameter info
    filter_info = {
        "grayscale": {
            "description": "Convert to single channel",
            "params": {"method": "luminance|lightness|average|red|green|blue (default: luminance)"},
        },
        "threshold": {
            "description": "Binarize image (2 levels)",
            "params": {
                "level": "0-255 (default: 128)",
                "dither": "none|floyd_steinberg|ordered (default: none)",
            },
        },
        "posterize": {
            "description": "Reduce to N tonal levels",
            "params": {
                "levels": "2-256 (default: 4)",
                "dither": "none|floyd_steinberg|ordered (default: none)",
            },
        },
        "gaussian_blur": {
            "description": "Gaussian blur",
            "params": {"radius": "float >= 0 (default: 2.0)"},
        },
        "box_blur": {
            "description": "Box blur",
            "params": {"radius": "int >= 0 (default: 2)"},
        },
        "contrast": {
            "description": "Adjust contrast",
            "params": {"factor": "float >= 0, 1.0 = no change (default: 1.0)"},
        },
        "brightness": {
            "description": "Adjust brightness",
            "params": {"factor": "float >= 0, 1.0 = no change (default: 1.0)"},
        },
        "gamma": {
            "description": "Gamma correction",
            "params": {"gamma": "float > 0, 1.0 = no change (default: 1.0)"},
        },
        "invert": {
            "description": "Invert colors (negative)",
            "params": {},
        },
    }

    filter_data = []
    for name in filters:
        info = filter_info.get(name, {"description": "", "params": {}})
        filter_data.append(
            {
                "name": name,
                "description": info["description"],
                "parameters": info["params"],
            }
        )

    data = {"filters": filter_data}
    _output_format(data, fmt)


@info_group.command(name="image")
@click.argument("image_path", type=click.Path(exists=True, path_type=Path))
@click.option("--format", "fmt", type=click.Choice(["table", "json", "yaml"]), default="table")
@click.option(
    "--config", "-c", "config_path", type=click.Path(path_type=Path), help="Config file path"
)
def info_image(image_path: Path, fmt: str, config_path: Path | None) -> None:
    """Show image details and the working resolution it would be drawn at."""
    try:
        image = load_image(image_path)
    except Exception as e:
        raise click.ClickException(f"Failed to load image: {e}") from e

    config = load_config(config_path)
    paper_preset = config.papers.get(config.default_paper)
    if paper_preset is not None:
        paper = Paper(
            name=paper_preset.name,
            width_mm=paper_preset.width,
            height_mm=paper_preset.height,
        )
    else:
        builtin = get_paper(config.default_paper)
        paper = Paper(name=builtin.name, width_mm=builtin.width, height_mm=builtin.height)
    pen_preset = config.pens.get(config.default_pen)
    pen_width_mm = pen_preset.width if pen_preset is not None else get_pen(config.default_pen).width
    resolution = plan_working_resolution(image.size, paper, pen_width_mm)
    working_width, working_height = resolution.target_size_px

    # Get EXIF data
    exif_data = {}
    try:
        exif = image.getexif()
        if exif:
            for tag_id, value in exif.items():
                exif_data[str(tag_id)] = str(value)
    except Exception:
        pass

    data = {
        "path": str(image_path),
        "format": image.format,
        "mode": image.mode,
        "size": {"width": image.width, "height": image.height},
        "dpi": image.info.get("dpi", (72, 72)),
        "working_resolution": {
            "width": working_width,
            "height": working_height,
            "working_px": resolution.working_px,
            "scale": round(resolution.scale, 6),
            "paper": config.default_paper,
            "pen_width_mm": pen_width_mm,
        },
        "exif": exif_data if exif_data else "No EXIF data",
    }

    _output_format(data, fmt)


@info_group.command(name="config")
@click.option("--format", "fmt", type=click.Choice(["table", "json", "yaml"]), default="table")
@click.option(
    "--config", "-c", "config_path", type=click.Path(path_type=Path), help="Config file path"
)
@click.option(
    "--project",
    "-p",
    "project_path",
    type=click.Path(exists=True, path_type=Path),
    help="Project file path",
)
def info_config(fmt: str, config_path: Path | None, project_path: Path | None) -> None:
    """Show resolved configuration (config + project + defaults)."""
    config = load_config(config_path)

    data = {
        "config_file": str(config_path) if config_path else "default",
        "default_pen": config.default_pen,
        "default_paper": config.default_paper,
        "output_dir": config.output_dir,
        "pens": {
            name: {"width": p.width, "color": p.color, "opacity": p.opacity}
            for name, p in config.pens.items()
        },
        "papers": {
            name: {"width": p.width, "height": p.height, "margin": p.margin}
            for name, p in config.papers.items()
        },
    }

    if project_path:
        try:
            from penpath.core.project import load_yaml

            project = load_yaml(project_path)
            data["project"] = {
                "input": str(project.image.path),
                "filters": project.image.filters.to_dict(),
                "paper": project.paper.model_dump(),
                "pen": project.palette[0].model_dump(),
                "pens": [pen.model_dump() for pen in project.palette],
                "pfm": project.pfm.model_dump(),
                "output": str(project.output_path),
            }
        except Exception as e:
            data["project_error"] = str(e)

    _output_format(data, fmt)


__all__ = ["info_group"]
