"""Convert command for penpath - photo to SVG conversion."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
from types import NoneType, UnionType
from typing import Any, Literal, Union, get_args, get_origin

import click
from click.core import ParameterSource
from pydantic import ValidationError
from rich.console import Console
from shapely import LineString

from penpath.cli.config import Config, load_config
from penpath.cli.palettes import resolve_palette as _resolve_palette
from penpath.cli.progress import StageReporter
from penpath.core.drawing.pfm_hatch import (
    PALETTE_ANGLE_STEP_DEG,
    HatchSettings,
    with_angle_offset,
)
from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings
from penpath.core.drawing.registry import get_pfm, list_pfms
from penpath.core.geometry.pipeline import optimize
from penpath.core.image.background import DEFAULT_BACKGROUND_THRESHOLD, mask_background
from penpath.core.image.filters import auto_equalize
from penpath.core.image.load import ImageLoadError, load_image
from penpath.core.image.palette_order import order_pens_for_drawing
from penpath.core.image.pipeline import FilterPipeline, get_filter
from penpath.core.image.resolution import apply_working_resolution, plan_working_resolution
from penpath.core.image.saturation import NO_BOOST_FACTOR, adapt_saturation, boost_saturation
from penpath.core.image.separate import separate_palette
from penpath.core.models import (
    ImageRef,
    Palette,
    Paper,
    Pen,
    PFMSettingsUnion,
    Project,
    make_pfm_settings,
)
from penpath.core.output.svg import (
    ImagePlacement,
    export_pen_layers,
    fit_image_placement,
    write_penpath_svg,
)
from penpath.core.output.vpype import optimize_with_vpype
from penpath.core.project import ProjectLoadError, load_yaml
from penpath.core.styles import STYLE_NAMES, StyleName, draw_styled_lines, get_style
from penpath.presets.palettes import list_palettes
from penpath.presets.papers import get_paper
from penpath.presets.pens import get_pen
from penpath.presets.pfms import (
    DEFAULT_PFM,
    get_pfm_for_preset,
    get_pfm_preset_by_id,
    get_pfm_preset_settings,
    list_pfm_presets,
)

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


def _apply_palette(project: Project, palette: Palette) -> None:
    """Put an ordered palette on a project, replacing any single pen."""
    project.pens = list(palette.pens)
    project.pen = None
    project.palette_name = palette.name if palette.name in list_palettes() else None


_MARGIN_FORMAT = "one margin in mm or four in top,right,bottom,left order"


def _parse_margin_parts(
    parts: list[str], param_hint: str
) -> float | tuple[float, float, float, float]:
    """Parse one or four comma-separated, non-negative millimetre margins."""
    try:
        values = [float(part.strip()) for part in parts]
    except ValueError as e:
        raise click.BadParameter(
            f"margins must be numbers in millimetres; expected {_MARGIN_FORMAT}",
            param_hint=param_hint,
        ) from e

    if len(values) == 1:
        margin: float | tuple[float, float, float, float] = values[0]
    elif len(values) == 4:
        margin = (values[0], values[1], values[2], values[3])
    else:
        raise click.BadParameter(
            f"expected {_MARGIN_FORMAT}, got {len(values)} values", param_hint=param_hint
        )

    for value in (margin,) if isinstance(margin, float) else margin:
        if not math.isfinite(value) or value < 0:
            raise click.BadParameter(
                "margins must be finite and non-negative in millimetres", param_hint=param_hint
            )
    return margin


def _check_drawable_area(paper: Paper, param_hint: str) -> None:
    """Reject margins that leave no room to draw on the resolved paper."""
    if paper.drawable_width_mm <= 0 or paper.drawable_height_mm <= 0:
        sides = "/".join(f"{value:g}" for value in paper.margins_mm)
        raise click.BadParameter(
            f"margins {sides} (top/right/bottom/left) leave no drawable area on "
            f"{paper.width_mm:g}x{paper.height_mm:g} mm paper; "
            "reduce the margin or use a larger paper",
            param_hint=param_hint,
        )


def _resolve_paper(paper_spec: str | None, config: Config) -> Paper:
    """Resolve paper from a preset or inline 'WIDTHxHEIGHT[,MARGINS]'."""
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
        parts = [part.strip() for part in paper_spec.split(",")]
        try:
            width_str, height_str = parts[0].split("x", 1)
            width_mm = float(width_str)
            height_mm = float(height_str)
        except ValueError:
            pass
        else:
            if not (
                math.isfinite(width_mm)
                and math.isfinite(height_mm)
                and width_mm > 0
                and height_mm > 0
            ):
                raise click.BadParameter(
                    "inline size must be two positive numbers in millimetres", param_hint="--paper"
                )
            margin_mm: float | tuple[float, float, float, float] = (
                10.0 if len(parts) == 1 else _parse_margin_parts(parts[1:], "--paper")
            )
            return Paper(
                name=f"inline-{width_mm}x{height_mm}",
                width_mm=width_mm,
                height_mm=height_mm,
                margin_mm=margin_mm,
            )

    raise click.BadParameter(
        f"Unknown paper: '{paper_spec}'. Use a preset name or inline format "
        "'WIDTHxHEIGHT[,MARGINS]'"
    )


def _coerce_setting_value(annotation: object, value_str: str, key: str) -> object:
    """Convert a ``KEY=VALUE`` string using the settings model's field type."""
    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        args = [arg for arg in get_args(annotation) if arg is not NoneType]
        if len(args) == 1:
            return _coerce_setting_value(args[0], value_str, key)
        return value_str

    if annotation is bool:
        lowered = value_str.strip().lower()
        if lowered in ("true", "1", "yes", "on"):
            return True
        if lowered in ("false", "0", "no", "off"):
            return False
        raise ValueError("expected true, 1, yes, on, false, 0, no or off")

    if annotation is int:
        return int(value_str)

    if annotation is float:
        return float(value_str)

    if origin is tuple:
        tuple_args = get_args(annotation)
        parts = value_str.split(",")
        if tuple_args and tuple_args[-1] is Ellipsis:
            return tuple(_coerce_setting_value(tuple_args[0], part.strip(), key) for part in parts)
        if tuple_args and len(tuple_args) != len(parts):
            raise ValueError(f"expected {len(tuple_args)} comma-separated values")
        return tuple(
            _coerce_setting_value(arg, part.strip(), key)
            for arg, part in zip(tuple_args, parts, strict=True)
        )

    return value_str


def _resolve_pfm(
    pfm_name: str | None,
    pfm_settings: dict[str, str],
    style_name: str | None = None,
    base_pfm: PFMSettingsUnion | None = None,
) -> PFMSettingsUnion:
    """Resolve a registered id, legacy preset, saved look and ``-s`` overrides.

    An explicit non-default ``--pfm`` picks the algorithm or preset. Otherwise a
    ``--style`` picks the settings bundle, and ``-s KEY=VALUE`` wins on top of
    either. With ``--project`` and only ``-s``, the file's saved PFM settings are
    the base so an override does not discard the rest of the saved look.
    """
    if base_pfm is not None and pfm_name is None and style_name is None:
        pfm_type = base_pfm.pfm_type
        base_model = base_pfm.to_typed_settings()
    else:
        if pfm_name is None:
            pfm_name = DEFAULT_PFM

        if ":" in pfm_name:
            try:
                pfm_type, base_model = get_pfm_preset_by_id(pfm_name)
            except ValueError as e:
                raise click.BadParameter(str(e), param_hint="--pfm") from e
        elif pfm_name in list_pfm_presets():
            pfm_type = get_pfm_for_preset(pfm_name)
            base_model = get_pfm_preset_settings(pfm_name)
        elif pfm_name in list_pfms():
            pfm_type = pfm_name
            _, settings_model = get_pfm(pfm_type)
            base_model = settings_model()
        else:
            try:
                get_pfm_preset_by_id(pfm_name)
            except ValueError as e:
                raise click.BadParameter(f"Unknown PFM or preset: {e}", param_hint="--pfm") from e
            raise click.BadParameter(f"Unknown PFM: '{pfm_name}'", param_hint="--pfm")

        # "default" is not a non-default --pfm, so a style still applies to it.
        if style_name is not None and pfm_name == DEFAULT_PFM:
            base_model = get_style(style_name).sketch_lines
            pfm_type = "sketch_lines"

    # Keep the fields the preset, style or caller actually set so the drawing
    # can tell an explicit value from a model default (flat images keep the
    # calibrated legacy max_fill/line_density; see the tone rule in pfm_sketch_lines).
    explicit_keys = set(base_model.model_fields_set) | set(pfm_settings)

    _, settings_model = get_pfm(pfm_type)
    values = base_model.model_dump()
    for key, value_str in pfm_settings.items():
        if key not in settings_model.model_fields:
            raise click.BadParameter(
                f"Unknown PFM setting: '{key}' for {pfm_type}",
                param_hint="-s/--pfm-setting",
            )
        annotation = settings_model.model_fields[key].annotation
        try:
            values[key] = _coerce_setting_value(annotation, value_str, key)
        except ValueError as e:
            raise click.BadParameter(
                f"Invalid value '{value_str}' for PFM setting '{key}': {e}",
                param_hint="-s/--pfm-setting",
            ) from e

    try:
        settings = settings_model(
            **{key: value for key, value in values.items() if key in explicit_keys}
        )
    except ValidationError as e:
        error = e.errors()[0]
        key = str(error["loc"][0]) if error.get("loc") else "pfm"
        raise click.BadParameter(
            f"Invalid value for PFM setting '{key}': {error['msg']}",
            param_hint="-s/--pfm-setting",
        ) from e
    return make_pfm_settings(pfm_type, settings)


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
    use_palette = len(pens) > 1
    use_background = (
        project.image.background if project.image.background is not None else use_palette
    )
    saturation_active = use_palette and (
        project.image.saturation != NO_BOOST_FACTOR or project.image.palette_adapt
    )

    # Step 1: Load image and plan the working resolution. Placement is derived
    # from the source size so the drawing rectangle does not move when the
    # working image is downscaled.
    reporter.start("Loading image")
    image = load_image(project.image.path)
    source_size_px = image.size
    origin_x_mm, origin_y_mm = project.paper.drawable_origin_mm
    fit_mode = project.paper.fit
    image_placement = fit_image_placement(
        image_size_px=source_size_px,
        area_width_mm=project.paper.drawable_width_mm,
        area_height_mm=project.paper.drawable_height_mm,
        image_dpi=project.image.dpi,
        offset_x_mm=origin_x_mm,
        offset_y_mm=origin_y_mm,
        mode=fit_mode,
    )
    clip_rect = (
        ImagePlacement(
            origin_x_mm,
            origin_y_mm,
            project.paper.drawable_width_mm,
            project.paper.drawable_height_mm,
        )
        if fit_mode == "fill"
        else None
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
    reporter.set_total_stages(5 + int(downscaling) + int(use_background) + int(saturation_active))
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

    if use_background:
        reporter.start("Masking paper background")
        masked = mask_background(
            working_image,
            threshold=project.image.background_threshold,
            method=project.image.background_method,
        )
        working_image = masked.image
        reporter.finish()
        reporter.message(
            f"Paper colour: {masked.paper_color} ({project.image.background_method} method); "
            f"masked {masked.masked_percent:.1f}% of pixels as no ink"
        )

    # Chroma boost runs on the masked working image. A single pen has no colour
    # decision to make, so both paths are silent no-ops there.
    if saturation_active:
        if project.image.saturation != NO_BOOST_FACTOR:
            factor = project.image.saturation
            reporter.start("Boosting saturation")
            working_image = boost_saturation(working_image, factor)
            reporter.finish()
            mode = "manual"
        else:
            reporter.start("Adapting saturation to palette")
            factor = adapt_saturation(working_image, pens)
            reporter.finish()
            if factor != NO_BOOST_FACTOR:
                working_image = boost_saturation(working_image, factor)
            mode = "palette-adapted"
        reporter.message(f"Saturation factor: {factor:.2f} ({mode})")

    # Step 3: Split before filtering, so the default grayscale filter cannot
    # throw away the colour needed to choose a pen.
    reporter.start("Applying filters")
    pen_images = separate_palette(working_image, pens)
    filtered_by_pen = [project.image.filters.apply(image) for _, image in pen_images]
    reporter.finish()

    # Step 4: Run the PFM once per pen, with settings in working-image pixels.
    reporter.start("Generating lines (PFM)")
    pfm_fn, _ = get_pfm(project.pfm.pfm_type)
    pfm_settings = project.pfm.to_typed_settings()
    if use_palette and isinstance(pfm_settings, SketchLinesSettings):
        legacy = {
            "max_fill": 80.0,
            "line_density": 0.75,
            "tone_coverage": 1.0,
            "tone_exponent": 1.0,
            "texture_limit": 0.0,
        }
        updates = {
            key: value for key, value in legacy.items() if key not in pfm_settings.model_fields_set
        }
        if updates:
            pfm_settings = pfm_settings.model_copy(update=updates)
    # Hatch needs the physical scale, which the serialisable settings do not
    # carry. A palette rotates the angle set per pen so colour layers do not
    # sit exactly on top of one another; a single pen keeps the original angles.
    pixels_per_mm = working_width / image_placement.width
    lines_by_pen: list[list[LineString]] = []
    for index, image in enumerate(filtered_by_pen):
        pen_settings = pfm_settings
        pfm_kwargs: dict[str, object] = {}
        if isinstance(pen_settings, HatchSettings):
            if use_palette:
                pen_settings = with_angle_offset(pen_settings, index * PALETTE_ANGLE_STEP_DEG)
            pfm_kwargs = {
                "pixels_per_mm": pixels_per_mm,
                "pen_width_mm": pens[index].width_mm,
            }
        lines_by_pen.append(
            draw_styled_lines(image, pfm_fn, pen_settings, project.style, pfm_kwargs)
        )
    reporter.finish()

    drawing_pens = order_pens_for_drawing(pens)
    position_by_id = {id(pen): index for index, pen in enumerate(pens)}
    lines_by_pen = [lines_by_pen[position_by_id[id(pen)]] for pen in drawing_pens]
    pens = drawing_pens

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
                clip_rect,
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
                fit_mode,
                clip_rect,
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
                fit_mode,
                clip_rect,
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
            fit_mode,
            clip_rect,
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
    "--layer-per-pen/--single-layer",
    default=True,
    help="SVG layer structure (default: layer-per-pen)",
)
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
    paper_spec: str | None,
    margin_spec: str | None,
    fit_mode: Literal["fit", "fill", "none"] | None,
    no_vpype: bool,
    vpype_path: str,
    layer_per_pen: bool,
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

    if pen_spec is not None and palette_spec is not None:
        raise click.UsageError(
            "Options --pen and --palette are mutually exclusive: use one or the other."
        )

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
        if auto_equalize_flag is not None:
            project.image.auto_equalize = auto_equalize_flag
        if background_flag is not None:
            project.image.background = background_flag
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
        pfm = _resolve_pfm(pfm_name, _parse_pfm_settings(pfm_settings), style_name)
        output = _determine_output_path(
            input_path, str(resolved_output) if resolved_output else None
        )
        if background_flag is not None:
            background = background_flag
        elif palette_spec:
            background = True
        else:
            background = background_threshold is not None or explicit_background_method

        project = Project(
            image=ImageRef(
                path=input_path,
                filters=filter_pipeline,
                dpi=dpi,
                auto_equalize=True if auto_equalize_flag is None else auto_equalize_flag,
                background=background,
                background_threshold=(
                    DEFAULT_BACKGROUND_THRESHOLD
                    if background_threshold is None
                    else background_threshold
                ),
                background_method=background_method,
                saturation=saturation,
                palette_adapt=palette_adapt and not explicit_saturation,
            ),
            paper=paper,
            pen=pen,
            pens=pens,
            palette_name=palette_name,
            pfm=pfm,
            style=style_name,
            output_path=output,
        )

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
