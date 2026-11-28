"""Convert command for penpath - photo to SVG conversion."""

from __future__ import annotations

import math
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

import click
from click.core import ParameterSource
from rich.console import Console

from penpath.api import convert
from penpath.cli.config import Config, load_config
from penpath.cli.palettes import resolve_palette as _resolve_palette
from penpath.cli.progress import StageReporter
from penpath.core import resolve as _resolve
from penpath.core.image.background import DEFAULT_BACKGROUND_THRESHOLD
from penpath.core.image.load import ImageLoadError
from penpath.core.image.pipeline import FilterPipeline
from penpath.core.models import Palette, Paper, Pen, PFMSettingsUnion, Project
from penpath.core.project import ProjectLoadError, load_yaml
from penpath.core.styles import STYLE_NAMES, StyleName
from penpath.presets.palettes import list_palettes


def _click_error(error: _resolve.ResolutionError) -> click.BadParameter:
    """Render a core resolution error as a Click usage error."""
    return click.BadParameter(error.message, param_hint=error.param_hint)


def _parse_pfm_settings(settings: Iterable[str]) -> dict[str, str]:
    """Parse PFM settings like 'line_density=0.5' into a dict."""
    result = {}
    for setting in settings:
        if "=" not in setting:
            raise click.BadParameter(f"Invalid PFM setting format: {setting}. Use KEY=VALUE")
        key, value = setting.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def _build_filter_pipeline(filter_specs: list[str]) -> FilterPipeline:
    """Build a filter pipeline from filter specifications."""
    try:
        return _resolve.build_filter_pipeline(filter_specs)
    except _resolve.ResolutionError as e:
        raise _click_error(e) from e


def _resolve_pen(pen_spec: str | None, config: Config) -> Pen:
    """Resolve a pen preset or inline spec with config presets taking precedence."""
    try:
        return _resolve.resolve_pen(pen_spec, default_pen=config.default_pen, presets=config.pens)
    except _resolve.ResolutionError as e:
        raise _click_error(e) from e


def _apply_palette(project: Project, palette: Palette) -> None:
    """Put an ordered palette on a project, replacing any single pen."""
    project.pens = list(palette.pens)
    project.pen = None
    project.palette_name = palette.name if palette.name in list_palettes() else None


def _parse_margin_parts(
    parts: list[str], param_hint: str
) -> float | tuple[float, float, float, float]:
    """Parse one or four comma-separated, non-negative millimetre margins."""
    try:
        return _resolve.parse_margin_parts(parts, param_hint)
    except _resolve.ResolutionError as e:
        raise _click_error(e) from e


def _check_drawable_area(paper: Paper, param_hint: str) -> None:
    """Reject margins that leave no room to draw on the resolved paper."""
    try:
        _resolve.check_drawable_area(paper, param_hint)
    except _resolve.ResolutionError as e:
        raise _click_error(e) from e


def _resolve_paper(paper_spec: str | None, config: Config) -> Paper:
    """Resolve paper from a preset or inline spec with config presets first."""
    try:
        return _resolve.resolve_paper(
            paper_spec, default_paper=config.default_paper, presets=config.papers
        )
    except _resolve.ResolutionError as e:
        raise _click_error(e) from e


def _resolve_pfm(
    pfm_name: str | None,
    pfm_settings: dict[str, str],
    style_name: str | None = None,
    base_pfm: PFMSettingsUnion | None = None,
) -> PFMSettingsUnion:
    """Resolve a PFM name, saved look, project base and ``-s`` overrides."""
    try:
        return _resolve.resolve_pfm(pfm_name, pfm_settings, style_name, base_pfm)
    except _resolve.ResolutionError as e:
        raise _click_error(e) from e


def _determine_output_path(input_path: Path, output_path: str | None) -> Path:
    """Determine output SVG path."""
    return _resolve.resolve_output_path(input_path, output_path)


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
@click.option(
    "--max-coverage",
    "max_coverage_opt",
    type=click.FloatRange(0.0, 1.0, min_open=True),
    default=None,
    help=(
        "Largest share of the paper ink may cover where the image is black, measured "
        "with the pen width (default: 0.8; 1 turns the cap off)"
    ),
)
@click.option(
    "--auto-levels-clip",
    "auto_levels_clip_opt",
    type=click.FloatRange(0.0, 10.0),
    default=None,
    help=(
        "Percent of pixels ignored at each end when auto equalize measures the range "
        "(default: 0; 0.5 ignores a few extreme pixels so flat photos get stretched)"
    ),
)
@click.option(
    "--equalize-levels/--no-equalize-levels",
    "equalize_levels_flag",
    default=None,
    help=(
        "Equalise the image onto the drawing algorithm's own tone steps, so every "
        "step gets the same share of inked pixels (default: off)"
    ),
)
@click.option(
    "--background/--no-background",
    "background_flag",
    default=None,
    help="Mask paper pixels as no ink (default: on with --palette, off for a single pen)",
)
@click.option(
    "--background-threshold",
    "background_threshold",
    type=float,
    default=None,
    help=(
        "Max CIE Lab distance from the paper colour to mask "
        f"(default: {DEFAULT_BACKGROUND_THRESHOLD:g}; implies --background)"
    ),
)
@click.option(
    "--background-method",
    "background_method",
    type=click.Choice(["global", "local"]),
    default="local",
    show_default=True,
    help=(
        "How to find paper: local follows lighting gradients, "
        "global uses one detected colour; implies --background"
    ),
)
@click.option(
    "--saturation",
    "saturation",
    type=float,
    default=1.0,
    show_default=True,
    help="CIE Lab chroma multiplier for palette mode (0-3; 1.0 is off)",
)
@click.option(
    "--palette-adapt",
    is_flag=True,
    help="Choose the chroma multiplier from the image and palette; --saturation wins",
)
@click.option(
    "--style",
    "style_name",
    type=click.Choice(STYLE_NAMES),
    help="Saved look: sketch (the default), hatch or outline. -s overrides its values",
)
@click.option(
    "--pfm",
    "pfm_name",
    help=(
        "Registered PFM algorithm, legacy preset or qualified PFM:PRESET id "
        "(default: sketch_lines). Run 'penpath info pfms' to list them."
    ),
)
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
@click.option(
    "--key-layer/--no-key-layer",
    "key_layer_flag",
    default=None,
    help="Trace a final black edge layer (default: on with --palette, off for a single pen)",
)
@click.option(
    "--paper",
    "paper_spec",
    help="Paper preset or inline 'WIDTHxHEIGHT[,MARGINS]' (one margin or top,right,bottom,left)",
)
@click.option(
    "--margin",
    "margin_spec",
    help=(
        "Override the paper margin in mm for this run: one value for all sides or four "
        "in top,right,bottom,left order (e.g. 10 or 20,5,20,5)"
    ),
)
@click.option(
    "--fit",
    "fit_mode",
    type=click.Choice(["fit", "fill", "none"]),
    default=None,
    help=(
        "Image placement: fit (default, contain in the drawable area), fill (cover and crop), "
        "or none (use the --dpi pixel size). --dpi sets the drawn size only with --fit none"
    ),
)
@click.option("--no-vpype", is_flag=True, help="Skip vpype optimization (use direct SVG export)")
@click.option("--vpype-path", default="vpype", help="Path to vpype executable")
@click.option(
    "--dpi",
    type=int,
    default=300,
    help=(
        "Image DPI; sets the drawn size only with --fit none, because fit and fill "
        "scale the image to the paper"
    ),
)
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
    equalize_levels_flag: bool | None,
    auto_levels_clip_opt: float | None,
    max_coverage_opt: float | None,
    background_flag: bool | None,
    background_threshold: float | None,
    background_method: Literal["global", "local"],
    saturation: float,
    palette_adapt: bool,
    style_name: StyleName | None,
    pfm_name: str | None,
    pfm_settings: tuple[str, ...],
    pen_spec: str | None,
    palette_spec: str | None,
    key_layer_flag: bool | None,
    paper_spec: str | None,
    margin_spec: str | None,
    fit_mode: Literal["fit", "fill", "none"] | None,
    no_vpype: bool,
    vpype_path: str,
    dpi: int,
    max_resolution_px: int | None,
    no_downscale: bool,
    quiet: bool,
    config_path: Path | None,
) -> None:
    """Convert a raster image to a plottable SVG with the selected PFM.

    INPUT_PATH: Path to input image (PNG, JPG, TIFF, BMP)
    OUTPUT_PATH: Output SVG path (default: <input>_plot.svg beside input)
    """
    if max_resolution_px is not None and max_resolution_px <= 0:
        raise click.BadParameter(
            "must be a positive number of pixels", param_hint="--max-resolution"
        )

    if background_threshold is not None and (
        not math.isfinite(background_threshold) or background_threshold < 0
    ):
        raise click.BadParameter(
            "must be a finite, non-negative Lab distance", param_hint="--background-threshold"
        )

    explicit_background_method = (
        ctx.get_parameter_source("background_method") is ParameterSource.COMMANDLINE
    )
    explicit_saturation = ctx.get_parameter_source("saturation") is ParameterSource.COMMANDLINE
    if not math.isfinite(saturation) or not 0.0 <= saturation <= 3.0:
        raise click.BadParameter("must be a finite number in [0, 3]", param_hint="--saturation")

    try:
        _resolve.check_pen_palette_conflict(pen_spec, palette_spec)
    except _resolve.ResolutionError as e:
        raise click.UsageError(e.message) from e

    margins = (
        _parse_margin_parts(margin_spec.split(","), "--margin") if margin_spec is not None else None
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
        if style_name is not None:
            project.style = style_name
        if pfm_name or pfm_settings or style_name:
            parsed_settings = _parse_pfm_settings(pfm_settings)
            project.pfm = _resolve_pfm(
                pfm_name,
                parsed_settings,
                style_name,
                base_pfm=project.pfm if not (pfm_name or style_name) else None,
            )
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
        if no_auto_orient:
            project.image.auto_orient = False
        if auto_equalize_flag is not None:
            project.image.auto_equalize = auto_equalize_flag
        if equalize_levels_flag is not None:
            project.image.equalize_levels = equalize_levels_flag
        if auto_levels_clip_opt is not None:
            project.image.auto_levels_clip = auto_levels_clip_opt
        if max_coverage_opt is not None:
            project.image.max_coverage = max_coverage_opt
        if background_flag is not None:
            project.image.background = background_flag
        if key_layer_flag is not None:
            project.image.key_layer = key_layer_flag
        if background_threshold is not None:
            project.image.background_threshold = background_threshold
            if background_flag is None:
                project.image.background = True
        if explicit_background_method:
            project.image.background_method = background_method
            if background_flag is None:
                project.image.background = True
        if explicit_saturation:
            project.image.saturation = saturation
            project.image.palette_adapt = False
        elif palette_adapt:
            project.image.palette_adapt = True
            project.image.saturation = 1.0
        project.image.path = input_path  # Always use CLI input path
    else:
        try:
            project = _resolve.build_project(
                input_path,
                pfm=pfm_name,
                paper=paper_spec,
                palette=palette_spec,
                pen=pen_spec,
                settings=_parse_pfm_settings(pfm_settings),
                filters=list(filter_specs) if filter_specs else None,
                style=style_name,
                dpi=dpi,
                output_path=resolved_output,
                background=background_flag,
                background_threshold=background_threshold,
                background_method=background_method if explicit_background_method else None,
                saturation=saturation if explicit_saturation else None,
                palette_adapt=palette_adapt,
                key_layer=key_layer_flag,
                auto_orient=not no_auto_orient,
                auto_equalize=True if auto_equalize_flag is None else auto_equalize_flag,
                equalize_levels=bool(equalize_levels_flag),
                auto_levels_clip=auto_levels_clip_opt or 0.0,
                max_coverage=0.8 if max_coverage_opt is None else max_coverage_opt,
                default_pen=config.default_pen,
                default_paper=config.default_paper,
                pen_presets=config.pens,
                paper_presets=config.papers,
            )
        except _resolve.ResolutionError as e:
            raise _click_error(e) from e

    if margins is not None:
        project.paper.margin_mm = margins
    if fit_mode is not None:
        project.paper.fit = fit_mode
    margin_hint = "--margin" if margins is not None else "--paper" if paper_spec else "paper"
    _check_drawable_area(project.paper, margin_hint)

    # Report to stderr so stdout stays clean for pipelines and agents. The
    # console is created here so its terminal detection sees the current stderr.
    reporter = StageReporter(Console(stderr=True), quiet=quiet)
    try:
        with reporter:
            convert(
                input_path,
                project=project,
                dpi=project.image.dpi,
                output=project.output_path,
                use_vpype=not no_vpype,
                vpype_path=vpype_path,
                max_resolution_px=max_resolution_px,
                no_downscale=no_downscale,
                reporter=reporter,
            )
    except ImageLoadError as e:
        raise click.ClickException(f"Image load error: {e}") from e
    except Exception as e:
        raise click.ClickException(f"Conversion failed: {e}") from e

    reporter.summary()
    reporter.message(f"[green]✓[/green] SVG saved to: {project.output_path}")


__all__ = ["convert_cmd"]
