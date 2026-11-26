"""Convert command for penpath - photo to SVG conversion."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
from typing import Any, cast, get_args

import click
from pydantic import ValidationError
from rich.console import Console
from shapely import LineString

from penpath.cli.config import Config, load_config
from penpath.cli.progress import StageReporter
from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings
from penpath.core.drawing.registry import get_pfm, list_pfms
from penpath.core.geometry.pipeline import optimize
from penpath.core.image.filters import auto_equalize
from penpath.core.image.load import ImageLoadError, load_image
from penpath.core.image.pipeline import FilterPipeline, get_filter
from penpath.core.image.resolution import apply_working_resolution, plan_working_resolution
from penpath.core.image.separate import separate_palette
from penpath.core.models import ImageRef, Palette, Paper, Pen, Project, SketchLinesPFM
from penpath.core.output.svg import export_pen_layers, fit_image_placement, write_penpath_svg
from penpath.core.output.vpype import optimize_with_vpype
from penpath.core.project import ProjectLoadError, load_yaml
from penpath.presets.palettes import get_palette, list_palettes
from penpath.presets.papers import get_paper
from penpath.presets.pens import get_pen
from penpath.presets.pfms import DEFAULT_PFM, get_pfm_preset, list_pfm_presets

_VALID_PEN_TYPES: tuple[str, ...] = tuple(
    str(item) for item in get_args(Pen.model_fields["pen_type"].annotation)
)
_PEN_FIELD_HINTS: dict[str, str] = {
    "width_mm": "a width in millimetres greater than 0 and at most 10",
    "color": "a #RRGGBB hex colour or a named CSS colour",
    "pen_type": f"one of {', '.join(_VALID_PEN_TYPES)}",
}
_PEN_FORMAT = "WIDTH[,COLOR[,TYPE]]"


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
    """Resolve a preset name or inline 'WIDTH[,COLOR[,TYPE]]' to a Pen.

    Preset names win over inline parsing. The three inline fields are validated by
    ``Pen``; an invalid field becomes a BadParameter naming that field and what it
    accepts instead of a generic "Unknown pen".
    """
    if pen_spec is None:
        pen_spec = config.default_pen

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

    parts = [part.strip() for part in pen_spec.split(",")]
    if not 1 <= len(parts) <= 3:
        raise click.BadParameter(
            f"expected inline format '{_PEN_FORMAT}': at most three comma-separated "
            f"fields, got {len(parts)}",
            param_hint="--pen",
        )

    values: dict[str, object] = {
        "name": "-".join(parts),
        "width_mm": parts[0],
        "color": parts[1] if len(parts) > 1 else "#000000",
        "pen_type": parts[2] if len(parts) > 2 else "rollerball",
    }
    try:
        return Pen.model_validate(values)
    except ValidationError as e:
        error = e.errors()[0]
        field = str(error["loc"][0]) if error.get("loc") else "pen"
        value = values.get(field, pen_spec)
        hint = _PEN_FIELD_HINTS.get(field, f"a preset name or inline '{_PEN_FORMAT}'")
        raise click.BadParameter(
            f"invalid {field} '{value}': {error['msg']}. Accepted: {hint}",
            param_hint="--pen",
        ) from e


def _resolve_palette(palette_spec: str) -> Palette:
    """Resolve a built-in palette name or an inline 'name=width,#hex;...' list."""
    if palette_spec in list_palettes():
        return get_palette(palette_spec)

    pens: list[Pen] = []
    for index, entry in enumerate(palette_spec.split(";"), start=1):
        if "=" not in entry:
            raise click.BadParameter(
                f"Invalid palette pen {index}: '{entry}'. Use NAME=WIDTH,#HEX",
                param_hint="palette",
            )
        name, value = entry.split("=", 1)
        parts = value.split(",")
        if len(parts) != 2:
            raise click.BadParameter(
                f"Invalid palette pen {index}: '{entry}'. Use NAME=WIDTH,#HEX",
                param_hint="palette",
            )
        try:
            pens.append(
                Pen(
                    name=name.strip(),
                    width_mm=float(parts[0].strip()),
                    color=parts[1].strip(),
                )
            )
        except (ValidationError, ValueError) as e:
            raise click.BadParameter(
                f"Invalid palette pen {index}: '{entry}'. {e}",
                param_hint="palette",
            ) from e

    return Palette(name="inline", pens=pens)


def _apply_palette(project: Project, palette: Palette) -> None:
    """Put an ordered palette on a project, replacing any single pen."""
    project.pens = list(palette.pens)
    project.pen = None
    project.palette_name = palette.name if palette.name in list_palettes() else None


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
        try:
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
        except (TypeError, ValueError) as e:
            raise click.BadParameter(
                f"Invalid value '{value_str}' for PFM setting '{key}': {e}",
                param_hint="-s/--pfm-setting",
            ) from e

    try:
        settings_model = SketchLinesSettings(**base_settings)
    except ValidationError as e:
        error = e.errors()[0]
        key = str(error["loc"][0]) if error.get("loc") else "pfm"
        raise click.BadParameter(
            f"Invalid value for PFM setting '{key}': {error['msg']}",
            param_hint="-s/--pfm-setting",
        ) from e
    return SketchLinesPFM(settings=settings_model)


def _determine_output_path(input_path: Path, output_path: str | None) -> Path:
    """Determine output SVG path."""
    if output_path:
        path = Path(output_path)
        if path.suffix.lower() != ".svg":
            path = path.with_suffix(".svg")
        return path
    return input_path.parent / f"{input_path.stem}_plot.svg"


def _resolve_output_path(
    input_path: Path, positional: Path | None, option: Path | None
) -> Path | None:
    """Resolve the output path from the positional argument and -o/--output."""
    if positional is None and option is None:
        return None

    positional_path = (
        _determine_output_path(input_path, str(positional)) if positional is not None else None
    )
    option_path = _determine_output_path(input_path, str(option)) if option is not None else None

    if positional_path is not None and option_path is not None and positional_path != option_path:
        raise click.UsageError(
            f"Conflicting output paths: '{positional_path}' (OUTPUT_PATH) and "
            f"'{option_path}' (-o/--output). Give only one."
        )

    return positional_path if positional_path is not None else option_path


def _run_convert_pipeline(
    project: Project,
    use_vpype: bool,
    vpype_path: str,
    reporter: StageReporter,
    max_resolution_px: int | None = None,
    no_downscale: bool = False,
) -> list[list[LineString]]:
    """Draw every pen and return its optimized lines, in pen order."""
    pens = project.palette

    # Step 1: Load image and plan the working resolution. Placement is derived
    # from the source size so the drawing rectangle does not move when the
    # working image is downscaled.
    reporter.start("Loading image")
    image = load_image(project.image.path)
    source_size_px = image.size
    image_placement = fit_image_placement(
        image_size_px=source_size_px,
        area_width_mm=project.paper.drawable_width_mm,
        area_height_mm=project.paper.drawable_height_mm,
        image_dpi=project.image.dpi,
        offset_x_mm=project.paper.margin_mm,
        offset_y_mm=project.paper.margin_mm,
    )
    resolution = plan_working_resolution(
        source_size_px,
        project.paper,
        pens[0].width_mm,
        max_longest_px=max_resolution_px,
    )
    if no_downscale:
        resolution = replace(resolution, target_size_px=source_size_px, scale=1.0)
    downscaling = resolution.target_size_px != source_size_px
    reporter.set_total_stages(5 + int(downscaling))
    reporter.finish()

    working_width, working_height = resolution.target_size_px
    reporter.message(
        f"Working resolution: {working_width}x{working_height} px "
        f"(source {source_size_px[0]}x{source_size_px[1]} px, scale {resolution.scale:.3f})"
    )

    # Step 2: Downscale to the working resolution, only when it changes the image.
    if downscaling:
        reporter.start("Downscaling image")
    working_image = apply_working_resolution(image, resolution)
    if downscaling:
        reporter.finish()
    working_size_px = working_image.size

    # Auto levels run once on the whole working image, before separation, so
    # every palette channel shares one luminance range and explicit -f filters
    # keep their current meaning.
    if project.image.auto_equalize:
        working_image = auto_equalize(working_image)

    # Step 3: Split before filtering, so the default grayscale filter cannot
    # throw away the colour needed to choose a pen.
    reporter.start("Applying filters")
    pen_images = separate_palette(working_image, pens)
    filtered_by_pen = [project.image.filters.apply(image) for _, image in pen_images]
    reporter.finish()

    # Step 4: Run the PFM once per pen, with settings in working-image pixels.
    reporter.start("Generating lines (PFM)")
    pfm_fn, _ = get_pfm(project.pfm.pfm_type)
    pfm_settings = cast(SketchLinesSettings, project.pfm.to_typed_settings())
    lines_by_pen = [pfm_fn(image, pfm_settings) for image in filtered_by_pen]
    reporter.finish()

    if not any(lines_by_pen):
        reporter.message("Warning: No lines generated", style="yellow")
        return [[] for _ in pens]

    # Step 5: Optimize geometry per pen; never merge or sort across pens.
    reporter.start("Optimizing geometry")
    strokes_by_pen = [
        optimize(
            lines,
            project.paper,
            simplify_tol_mm=0.1,
            merge_angle_deg=5.0,
            merge_dist_mm=0.5,
        )
        for lines in lines_by_pen
    ]
    reporter.finish()

    # Step 6: Export. vpype optimises geometry one pen at a time; penpath writes
    # the SVG on both paths so the millimetre layout is identical.
    reporter.start("Exporting SVG")
    if use_vpype:
        try:
            strokes_mm_by_pen = optimize_with_vpype(
                strokes_by_pen,
                project.paper,
                pens,
                vpype_path,
                image_placement,
                working_size_px,
            )
            write_penpath_svg(
                [
                    [LineString(stroke.polyline) for stroke in strokes]
                    for strokes in strokes_mm_by_pen
                ],
                project.paper,
                pens,
                project.output_path,
                image_placement,
                resolution,
            )
        except FileNotFoundError:
            reporter.message(
                "vpype not found, falling back to direct SVG export "
                '(install it with: pip install "penpath[vpype]")',
                style="yellow",
                markup=False,
            )
            export_pen_layers(
                strokes_by_pen,
                project.paper,
                pens,
                project.output_path,
                image_placement,
                working_size_px,
                resolution,
            )
    else:
        export_pen_layers(
            strokes_by_pen,
            project.paper,
            pens,
            project.output_path,
            image_placement,
            working_size_px,
            resolution,
        )

    reporter.finish()
    return strokes_by_pen


@click.command(name="convert")
@click.argument("input_path", type=click.Path(exists=True, path_type=Path))
@click.argument("output_path", required=False, type=click.Path(path_type=Path))
@click.option(
    "-o", "--output", "output_option", type=click.Path(path_type=Path), help="Output SVG path"
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
@click.option(
    "--auto-equalize/--no-auto-equalize",
    "auto_equalize_flag",
    default=None,
    help="Normalize tonal range before drawing (default: on; use --no-auto-equalize to keep tones)",
)
@click.option("--pfm", "pfm_name", help="PFM algorithm or built-in preset (default: sketch_lines)")
@click.option(
    "--pfm-setting",
    "-s",
    "pfm_settings",
    multiple=True,
    help="PFM setting override (repeatable). Format: KEY=VALUE",
)
@click.option(
    "--pen",
    "pen_spec",
    help=(
        "Pen preset or inline 'WIDTH[,COLOR[,TYPE]]' (default: fine). "
        "Colour: #RRGGBB or named CSS colour. "
        "Types: ballpoint, fineliner, fountain, brush, marker, rollerball, gel"
    ),
)
@click.option(
    "--palette",
    "palette_spec",
    help=(
        "Built-in palette name or inline 'name=width,#hex;...': "
        "split by colour, one layer per used pen"
    ),
)
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
    "--max-resolution",
    "max_resolution_px",
    type=int,
    default=None,
    help="Longest side of the working image in pixels (overrides the derived value)",
)
@click.option(
    "--no-downscale",
    is_flag=True,
    help="Keep the source pixels (do not downscale before drawing)",
)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    help="Suppress progress and other non-error output on stderr",
)
@click.option(
    "--config", "-c", "config_path", type=click.Path(path_type=Path), help="Config file path"
)
@click.pass_context
def convert_cmd(
    ctx: click.Context,
    input_path: Path,
    output_path: Path | None,
    output_option: Path | None,
    project_path: Path | None,
    filter_specs: tuple[str, ...],
    no_auto_orient: bool,
    auto_equalize_flag: bool | None,
    pfm_name: str | None,
    pfm_settings: tuple[str, ...],
    pen_spec: str | None,
    palette_spec: str | None,
    paper_spec: str | None,
    no_vpype: bool,
    vpype_path: str,
    layer_per_pen: bool,
    dpi: int,
    max_resolution_px: int | None,
    no_downscale: bool,
    quiet: bool,
    config_path: Path | None,
) -> None:
    """Convert a raster image to a plottable SVG using the Sketch Lines algorithm.

    INPUT_PATH: Path to input image (PNG, JPG, TIFF, BMP)
    OUTPUT_PATH: Output SVG path (default: <input>_plot.svg beside input)
    """
    if max_resolution_px is not None and max_resolution_px <= 0:
        raise click.BadParameter(
            "must be a positive number of pixels", param_hint="--max-resolution"
        )

    if pen_spec is not None and palette_spec is not None:
        raise click.UsageError(
            "Options --pen and --palette are mutually exclusive: use one or the other."
        )

    resolved_output = _resolve_output_path(input_path, output_path, output_option)

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
        if palette_spec:
            _apply_palette(project, _resolve_palette(palette_spec))
        if paper_spec:
            project.paper = _resolve_paper(paper_spec, config)
        if resolved_output:
            project.output_path = resolved_output
        if dpi != 300:
            project.image.dpi = dpi
        if auto_equalize_flag is not None:
            project.image.auto_equalize = auto_equalize_flag
        project.image.path = input_path  # Always use CLI input path
    else:
        # Build project from CLI flags and config
        if not filter_specs:
            # Default filter pipeline: grayscale
            filter_pipeline = FilterPipeline()
            filter_pipeline.add_step("grayscale", method="luminance")
        else:
            filter_pipeline = _build_filter_pipeline(list(filter_specs))

        if palette_spec:
            palette = _resolve_palette(palette_spec)
            pen = None
            pens = palette.pens
            palette_name = palette.name if palette.name in list_palettes() else None
        else:
            pen = _resolve_pen(pen_spec, config)
            pens = []
            palette_name = None

        paper = _resolve_paper(paper_spec, config)
        pfm = _resolve_pfm(pfm_name, _parse_pfm_settings(pfm_settings))
        output = _determine_output_path(
            input_path, str(resolved_output) if resolved_output else None
        )

        project = Project(
            image=ImageRef(
                path=input_path,
                filters=filter_pipeline,
                dpi=dpi,
                auto_equalize=True if auto_equalize_flag is None else auto_equalize_flag,
            ),
            paper=paper,
            pen=pen,
            pens=pens,
            palette_name=palette_name,
            pfm=pfm,
            output_path=output,
        )

    # Report to stderr so stdout stays clean for pipelines and agents. The
    # console is created here so its terminal detection sees the current stderr.
    reporter = StageReporter(Console(stderr=True), quiet=quiet)
    try:
        with reporter:
            _run_convert_pipeline(
                project,
                not no_vpype,
                vpype_path,
                reporter,
                max_resolution_px=max_resolution_px,
                no_downscale=no_downscale,
            )
    except ImageLoadError as e:
        raise click.ClickException(f"Image load error: {e}") from e
    except Exception as e:
        raise click.ClickException(f"Conversion failed: {e}") from e

    reporter.summary()
    reporter.message(f"[green]✓[/green] SVG saved to: {project.output_path}")


__all__ = ["convert_cmd"]
