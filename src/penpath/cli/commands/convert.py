"""Convert command for penpath - photo to SVG conversion."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

from penpath.cli.config import Config, load_config
from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings
from penpath.core.drawing.registry import get_pfm, list_pfms
from penpath.core.geometry.pipeline import optimize
from penpath.core.image.load import ImageLoadError, load_image
from penpath.core.image.pipeline import FilterPipeline, get_filter
from penpath.core.models import ImageRef, Paper, Pen, Project, SketchLinesPFM
from penpath.core.output.svg import add_placement_metadata, export_svg, fit_image_placement
from penpath.core.output.vpype import run_vpype
from penpath.core.project import ProjectLoadError, load_yaml
from penpath.presets.papers import get_paper
from penpath.presets.pens import get_pen
from penpath.presets.pfms import DEFAULT_PFM, get_pfm_preset, list_pfm_presets

if TYPE_CHECKING:
    from shapely import LineString


console = Console(stderr=True)


def _parse_filter_spec(spec: str) -> tuple[str, dict[str, str]]:
    """Parse a filter specification string like 'threshold:levels=4,dither=floyd_steinberg'."""
    if ":" in spec:
        name, params_str = spec.split(":", 1)
        params = {}
        for param in params_str.split(","):
            if "=" in param:
                key, value = param.split("=", 1)
                params[key.strip()] = value.strip()
        return name.strip(), params
    return spec.strip(), {}


def _convert_filter_params(filter_name: str, params: dict[str, str]) -> dict[str, Any]:
    """Convert filter parameter strings to appropriate types based on filter signature."""
    from typing import get_type_hints

    filter_fn = get_filter(filter_name)
    try:
        hints = get_type_hints(filter_fn)
    except Exception:
        hints = {}

    converted: dict[str, Any] = {}
    for key, value_str in params.items():
        if key in hints:
            annotation = hints[key]
            # Handle basic types
            if annotation is int:
                converted[key] = int(value_str)
            elif annotation is float:
                converted[key] = float(value_str)
            elif annotation is bool:
                converted[key] = value_str.lower() in ("true", "1", "yes", "on")
            else:
                converted[key] = value_str
        else:
            converted[key] = value_str
    return converted


def _build_filter_pipeline(filter_specs: list[str]) -> FilterPipeline:
    """Build a filter pipeline from filter specifications."""
    pipeline = FilterPipeline()
    for spec in filter_specs:
        name, params = _parse_filter_spec(spec)
        try:
            get_filter(name)  # Validate filter exists
        except ValueError as e:
            raise click.BadParameter(str(e), param_hint="filter") from e
        converted_params = _convert_filter_params(name, params)
        pipeline.add_step(name, **converted_params)
    return pipeline


def _parse_pfm_settings(settings: Iterable[str]) -> dict[str, str]:
    """Parse PFM settings like 'line_density=0.5' into a dict."""
    result = {}
    for setting in settings:
        if "=" not in setting:
            raise click.BadParameter(f"Invalid PFM setting format: {setting}. Use KEY=VALUE")
        key, value = setting.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def _resolve_pen(pen_spec: str | None, config: Config) -> Pen:
    """Resolve pen from spec (preset name or inline 'width,color,type')."""
    if pen_spec is None:
        pen_spec = config.default_pen

    # Check if it's a preset name in config
    config_pen_names = [p.name for p in config.pens.values()]
    if pen_spec in config_pen_names:
        pen_config = config.get_pen(pen_spec)
        return Pen(
            name=pen_config.name,
            width_mm=pen_config.width,
            color=pen_config.color,
            opacity=pen_config.opacity,
            pen_type="rollerball",
        )

    # Check built-in presets
    try:
        pen_config = get_pen(pen_spec)
        return Pen(
            name=pen_config.name,
            width_mm=pen_config.width,
            color=pen_config.color,
            opacity=pen_config.opacity,
            pen_type="rollerball",
        )
    except ValueError:
        pass

    # Parse inline format: width,color,type
    parts = pen_spec.split(",")
    if len(parts) >= 2:
        try:
            width_mm = float(parts[0])
            color = parts[1]
            pen_type = parts[2] if len(parts) > 2 else "rollerball"
            return Pen(
                name=f"inline-{pen_spec.replace(',', '-')}",
                width_mm=width_mm,
                color=color,
                opacity=1.0,
                pen_type=pen_type,  # type: ignore
            )
        except (ValueError, IndexError):  # fmt: skip
            pass

    raise click.BadParameter(
        f"Unknown pen: '{pen_spec}'. Use a preset name or inline format 'width,color,type'"
    )


def _resolve_paper(paper_spec: str | None, config: Config) -> Paper:
    """Resolve paper from spec (preset name or inline 'WIDTHxHEIGHT[,margins]')."""
    if paper_spec is None:
        paper_spec = config.default_paper

    # Check config presets
    if paper_spec in [p.name for p in config.papers.values()]:
        paper_config = config.get_paper(paper_spec)
        return Paper(
            name=paper_config.name,
            width_mm=paper_config.width,
            height_mm=paper_config.height,
            margin_mm=paper_config.margin,
        )

    # Check built-in presets
    try:
        paper_config = get_paper(paper_spec)
        return Paper(
            name=paper_config.name,
            width_mm=paper_config.width,
            height_mm=paper_config.height,
            margin_mm=paper_config.margin,
        )
    except ValueError:
        pass

    # Parse inline format: WIDTHxHEIGHT[,MARGINS]
    if "x" in paper_spec:
        try:
            size_part, *margin_parts = paper_spec.split(",")
            width_str, height_str = size_part.split("x")
            width_mm = float(width_str)
            height_mm = float(height_str)

            if margin_parts:
                margins = [float(m) for m in margin_parts[0].split(",")]
                if len(margins) == 1:
                    margin_mm = margins[0]
                elif len(margins) == 4:
                    margin_mm = sum(margins) / 4  # Average for uniform margin
                else:
                    margin_mm = margins[0]
            else:
                margin_mm = 10.0

            return Paper(
                name=f"inline-{width_mm}x{height_mm}",
                width_mm=width_mm,
                height_mm=height_mm,
                margin_mm=margin_mm,
            )
        except (ValueError, IndexError):  # fmt: skip
            pass

    raise click.BadParameter(
        f"Unknown paper: '{paper_spec}'. Use a preset name or inline format "
        "'WIDTHxHEIGHT[,margins]'"
    )


def _resolve_pfm(pfm_name: str | None, pfm_settings: dict[str, str]) -> SketchLinesPFM:
    """Resolve PFM settings from name and overrides."""
    if pfm_name is None:
        pfm_name = DEFAULT_PFM

    # Check if it's a registered PFM
    if pfm_name not in list_pfms() and pfm_name not in list_pfm_presets():
        raise click.BadParameter(f"Unknown PFM: '{pfm_name}'. Available: {list_pfms()}")

    # Get base settings from preset or default
    if pfm_name in list_pfm_presets():
        base_settings = get_pfm_preset(pfm_name).model_dump()
    else:
        base_settings = SketchLinesSettings().model_dump()

    # Apply overrides
    for key, value_str in pfm_settings.items():
        if key not in base_settings:
            raise click.BadParameter(f"Unknown PFM setting: '{key}'")
        current_value = base_settings[key]
        if isinstance(current_value, bool):
            base_settings[key] = value_str.lower() in ("true", "1", "yes", "on")
        elif isinstance(current_value, int):
            base_settings[key] = int(value_str)
        elif isinstance(current_value, float):
            base_settings[key] = float(value_str)
        elif isinstance(current_value, tuple):
            parts = value_str.split(",")
            base_settings[key] = tuple(float(p) for p in parts)
        else:
            base_settings[key] = value_str

    settings_model = SketchLinesSettings(**base_settings)
    return SketchLinesPFM(settings=settings_model)


def _determine_output_path(input_path: Path, output_path: str | None) -> Path:
    """Determine output SVG path."""
    if output_path:
        path = Path(output_path)
        if path.suffix.lower() != ".svg":
            path = path.with_suffix(".svg")
        return path
    return input_path.parent / f"{input_path.stem}_plot.svg"


def _run_convert_pipeline(
    project: Project,
    use_vpype: bool,
    vpype_path: str,
    progress: Progress,
    task_id: TaskID,
) -> list[LineString]:
    """Run the full conversion pipeline and return optimized lines."""
    # Step 1: Load image
    progress.update(task_id, description="Loading image...", advance=10)
    image = load_image(project.image.path)
    image_size_px = image.size
    image_placement = fit_image_placement(
        image_size_px=image_size_px,
        area_width_mm=project.paper.drawable_width_mm,
        area_height_mm=project.paper.drawable_height_mm,
        image_dpi=project.image.dpi,
        offset_x_mm=project.paper.margin_mm,
        offset_y_mm=project.paper.margin_mm,
    )

    # Step 2: Apply filters
    progress.update(task_id, description="Applying filters...", advance=15)
    filtered_image = project.image.filters.apply(image)

    # Step 3: Run PFM (Sketch Lines)
    progress.update(task_id, description="Generating lines (PFM)...", advance=25)
    pfm_fn, _ = get_pfm(project.pfm.pfm_type)
    pfm_settings = project.pfm.to_typed_settings()
    lines = pfm_fn(filtered_image, pfm_settings)

    if not lines:
        console.print("[yellow]Warning: No lines generated[/yellow]")
        return []

    # Step 4: Optimize geometry
    progress.update(task_id, description="Optimizing geometry...", advance=20)
    optimized_lines = optimize(
        lines,
        project.paper,
        simplify_tol_mm=0.1,
        merge_angle_deg=5.0,
        merge_dist_mm=0.5,
    )

    # Step 5: Export (vpype or direct SVG)
    progress.update(task_id, description="Exporting SVG...", advance=20)
    if use_vpype:
        try:
            svg_bytes = run_vpype(
                optimized_lines,
                project.paper,
                [project.pen],
                vpype_path,
                image_placement,
                image_size_px,
            )
            project.output_path.write_bytes(svg_bytes)
            add_placement_metadata(project.output_path, image_placement)
        except FileNotFoundError:
            console.print("[yellow]vpype not found, falling back to direct SVG export[/yellow]")
            export_svg(
                optimized_lines,
                project.paper,
                [project.pen],
                project.output_path,
                project.image.dpi,
                image_placement,
                image_size_px,
            )
    else:
        export_svg(
            optimized_lines,
            project.paper,
            [project.pen],
            project.output_path,
            project.image.dpi,
            image_placement,
            image_size_px,
        )

    progress.update(task_id, description="Done!", advance=10)
    return optimized_lines


@click.command(name="convert")
@click.argument("input_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "-o", "--output", "output_path", type=click.Path(path_type=Path), help="Output SVG path"
)
@click.option(
    "--project",
    "-p",
    "project_path",
    type=click.Path(exists=True, path_type=Path),
    help="Project YAML file",
)
@click.option(
    "--filter",
    "-f",
    "filter_specs",
    multiple=True,
    help="Filter to apply (repeatable). Format: name:param=value",
)
@click.option("--no-auto-orient", is_flag=True, help="Disable EXIF auto-orientation")
@click.option("--pfm", "pfm_name", help="PFM algorithm to use (default: sketch_lines)")
@click.option(
    "--pfm-setting",
    "-s",
    "pfm_settings",
    multiple=True,
    help="PFM setting override (repeatable). Format: KEY=VALUE",
)
@click.option("--pen", "pen_spec", help="Pen preset or inline 'width,color,type'")
@click.option("--paper", "paper_spec", help="Paper preset or inline 'WIDTHxHEIGHT[,margins]'")
@click.option("--no-vpype", is_flag=True, help="Skip vpype optimization (use direct SVG export)")
@click.option("--vpype-path", default="vpype", help="Path to vpype executable")
@click.option(
    "--layer-per-pen/--single-layer",
    default=True,
    help="SVG layer structure (default: layer-per-pen)",
)
@click.option("--dpi", type=int, default=300, help="Image DPI for coordinate scaling")
@click.option(
    "--config", "-c", "config_path", type=click.Path(path_type=Path), help="Config file path"
)
@click.pass_context
def convert_cmd(
    ctx: click.Context,
    input_path: Path,
    output_path: Path | None,
    project_path: Path | None,
    filter_specs: tuple[str, ...],
    no_auto_orient: bool,
    pfm_name: str | None,
    pfm_settings: tuple[str, ...],
    pen_spec: str | None,
    paper_spec: str | None,
    no_vpype: bool,
    vpype_path: str,
    layer_per_pen: bool,
    dpi: int,
    config_path: Path | None,
) -> None:
    """Convert a raster image to a plottable SVG using the Sketch Lines algorithm.

    INPUT_PATH: Path to input image (PNG, JPG, TIFF, BMP)
    OUTPUT_PATH: Output SVG path (default: <input>_plot.svg beside input)
    """
    # Load config
    config = load_config(config_path)

    # If project file provided, load it and override with CLI flags
    if project_path:
        try:
            project = load_yaml(project_path)
        except ProjectLoadError as e:
            raise click.ClickException(f"Failed to load project: {e}") from e

        # Override with CLI flags
        if filter_specs:
            project.image.filters = _build_filter_pipeline(list(filter_specs))
        if pfm_name or pfm_settings:
            project.pfm = _resolve_pfm(pfm_name, _parse_pfm_settings(pfm_settings))
        if pen_spec:
            project.pen = _resolve_pen(pen_spec, config)
        if paper_spec:
            project.paper = _resolve_paper(paper_spec, config)
        if output_path:
            project.output_path = _determine_output_path(input_path, str(output_path))
        if dpi != 300:
            project.image.dpi = dpi
        project.image.path = input_path  # Always use CLI input path
    else:
        # Build project from CLI flags and config
        if not filter_specs:
            # Default filter pipeline: grayscale
            filter_pipeline = FilterPipeline()
            filter_pipeline.add_step("grayscale", method="luminance")
        else:
            filter_pipeline = _build_filter_pipeline(list(filter_specs))

        pen = _resolve_pen(pen_spec, config)
        paper = _resolve_paper(paper_spec, config)
        pfm = _resolve_pfm(pfm_name, _parse_pfm_settings(pfm_settings))
        output = _determine_output_path(input_path, str(output_path) if output_path else None)

        project = Project(
            image=ImageRef(path=input_path, filters=filter_pipeline, dpi=dpi),
            paper=paper,
            pen=pen,
            pfm=pfm,
            output_path=output,
        )

    # Run conversion with progress bar
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task_id = progress.add_task("Starting...", total=100)
        try:
            _run_convert_pipeline(project, not no_vpype, vpype_path, progress, task_id)
        except ImageLoadError as e:
            raise click.ClickException(f"Image load error: {e}") from e
        except Exception as e:
            raise click.ClickException(f"Conversion failed: {e}") from e

    console.print(f"[green]✓[/green] SVG saved to: {project.output_path}")


__all__ = ["convert_cmd"]
