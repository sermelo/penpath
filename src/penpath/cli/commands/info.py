"""Info command for penpath - show presets, capabilities, and image details."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click
from pydantic.fields import FieldInfo
from rich.console import Console
from rich.table import Table
from rich.text import Text

from penpath.cli.config import load_config
from penpath.cli.palettes import resolve_palette
from penpath.core import (
    ProfileError,
    field_help,
    get_pfm_description,
    list_profile_sources,
    load_profile,
)
from penpath.core.drawing.registry import get_pfm, list_pfms
from penpath.core.image.load import load_image
from penpath.core.image.palette_order import order_pens_for_drawing
from penpath.core.image.pipeline import list_filters
from penpath.core.image.resolution import plan_working_resolution
from penpath.core.image.separate import palette_match
from penpath.core.models import Paper
from penpath.presets.palettes import get_palette, list_palettes
from penpath.presets.papers import get_paper, list_papers
from penpath.presets.pens import get_pen, list_pens
from penpath.presets.pfms import list_pfm_preset_ids, list_pfm_preset_ids_for_pfm

if TYPE_CHECKING:
    pass

console = Console()
PFM_TABLE_WIDTH = 80


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
        for order, pen in enumerate(order_pens_for_drawing(palette.pens), start=1):
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


def _fold_cell(text: str, width: int) -> str:
    """Fold text on word boundaries so a cell never breaks a preset id."""
    return "\n".join(
        textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False)
    )


def _print_pfms_table(rows: list[dict[str, Any]]) -> None:
    """Print one compact row per PFM: name, description and canonical preset ids."""
    name_width = max((len(row["name"]) for row in rows), default=4)
    preset_width = max((len(pid) + 1 for row in rows for pid in row["preset_ids"]), default=10)
    description_width = max(PFM_TABLE_WIDTH - name_width - preset_width - 10, 10)
    table = Table(title="Pen Follower Modules", width=PFM_TABLE_WIDTH)
    table.add_column("Name", width=name_width, no_wrap=True)
    table.add_column("Description", width=description_width, overflow="fold")
    table.add_column("Preset ids", width=preset_width, overflow="fold")
    for row in rows:
        table.add_row(
            Text(row["name"]),
            Text(_fold_cell(row["description"], description_width)),
            Text(_fold_cell(", ".join(row["preset_ids"]), preset_width)),
        )
    Console(width=PFM_TABLE_WIDTH).print(table)


@info_group.command(name="pfms")
@click.option("--format", "fmt", type=click.Choice(["table", "json", "yaml"]), default="table")
def info_pfms(fmt: str) -> None:
    """List registered PFMs with a description and their canonical preset ids."""
    preset_ids = list_pfm_preset_ids()
    pfm_data = []
    for name in list_pfms():
        _, settings_model = get_pfm(name)
        own_preset_ids = list_pfm_preset_ids_for_pfm(name)
        pfm_data.append(
            {
                "name": name,
                "description": get_pfm_description(name),
                "settings_model": settings_model.__name__,
                "default_settings": settings_model().model_dump(mode="json"),
                "presets": own_preset_ids,
                "preset_ids": own_preset_ids,
            }
        )

    all_preset_ids = sorted({pid for row in pfm_data for pid in row["preset_ids"]})
    data = {"available_pfms": pfm_data, "presets": all_preset_ids, "preset_ids": preset_ids}
    if fmt == "table":
        _print_pfms_table(pfm_data)
    else:
        _output_format(data, fmt)


def _setting_default(field: FieldInfo) -> Any:
    """Return a setting's default, or ``-`` for a required field."""
    if field.is_required():
        return "-"
    return field.default


def _print_pfm_table(data: dict[str, Any]) -> None:
    """Print a PFM's description, preset ids and settings above a detail table."""
    table_console = Console(width=PFM_TABLE_WIDTH)
    table_console.print(f"{data['name']}: {data['description']}", markup=False)
    table_console.print(f"Preset ids: {', '.join(data['presets'])}", markup=False)
    table = Table(title=f"Settings: {data['name']}", width=PFM_TABLE_WIDTH)
    table.add_column("Setting", no_wrap=True)
    table.add_column("Default", no_wrap=True)
    table.add_column("Help", overflow="fold")
    for setting in data["settings"]:
        table.add_row(
            Text(setting["name"]),
            Text(str(setting["default"])),
            Text(setting["help"]),
        )
    table_console.print(table)


@info_group.command(name="pfm")
@click.argument("name")
@click.option("--format", "fmt", type=click.Choice(["table", "json", "yaml"]), default="table")
def info_pfm(name: str, fmt: str) -> None:
    """Show a registered PFM's description, preset ids and settings.

    NAME is a registered PFM name such as sketch_lines, not a preset id. Run
    'penpath info pfms' to list the available names.
    """
    available = list_pfms()
    if name not in available:
        raise click.ClickException(f"Unknown PFM: '{name}'. Available PFMs: {', '.join(available)}")

    _, settings_model = get_pfm(name)
    help_by_name = field_help(settings_model)
    settings = [
        {
            "name": field_name,
            "default": _setting_default(field),
            "help": help_by_name.get(field_name, ""),
        }
        for field_name, field in settings_model.model_fields.items()
    ]
    data: dict[str, Any] = {
        "name": name,
        "description": get_pfm_description(name),
        "presets": list_pfm_preset_ids_for_pfm(name),
        "settings": settings,
    }
    if fmt == "table":
        _print_pfm_table(data)
    else:
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
        "equalize": {
            "description": "Global histogram equalisation of the luminance",
            "params": {},
        },
        "clahe": {
            "description": "Local contrast equalisation (CLAHE) of the luminance",
            "params": {
                "clip_limit": "float in (0, 1], higher = stronger (default: 0.01)",
                "tiles": "int 2-64, regions across the longest side (default: 8)",
            },
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
