"""Resolve preset names, inline specs and project defaults in one place.

The CLI and library callers share these helpers: they turn names such as
``fine``, ``a4``, ``stabilo_88`` or ``sketch_lines:fine`` into validated
``penpath.core`` models, and assemble a ``Project`` with the same defaults as
``penpath convert``. CLI-only policy (config files, project YAML overrides and
Click error rendering) stays outside this module.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from types import NoneType, UnionType
from typing import Any, Literal, Protocol, Union, get_args, get_origin, get_type_hints

from pydantic import ValidationError

from penpath.core.drawing.registry import get_pfm, list_pfms
from penpath.core.image.background import DEFAULT_BACKGROUND_THRESHOLD
from penpath.core.image.pipeline import FilterPipeline, get_filter
from penpath.core.models import (
    ImageRef,
    Palette,
    Paper,
    Pen,
    PFMSettingsUnion,
    Project,
    make_pfm_settings,
)
from penpath.core.styles import StyleName, get_style
from penpath.presets.palettes import get_palette, list_palettes
from penpath.presets.papers import get_paper as get_builtin_paper
from penpath.presets.pens import get_pen as get_builtin_pen
from penpath.presets.pfms import (
    DEFAULT_PFM,
    get_pfm_for_preset,
    get_pfm_preset_by_id,
    get_pfm_preset_settings,
    list_pfm_presets,
)

_PEN_FORMAT = "WIDTH[,COLOR[,TYPE]]"
_MARGIN_FORMAT = "one margin in mm or four in top,right,bottom,left order"
_PEN_FIELD_HINTS: dict[str, str] = {
    "width_mm": "a width in millimetres greater than 0 and at most 10",
    "color": "a #RRGGBB hex colour or a named CSS colour",
    "pen_type": (
        "one of "
        + ", ".join(str(item) for item in get_args(Pen.model_fields["pen_type"].annotation))
    ),
}


class ResolutionError(ValueError):
    """An invalid name, spec or option combination during resolution.

    ``param_hint`` names the CLI option that caused it; the CLI uses it when
    rendering the error. Library callers can use ``message`` directly.
    """

    def __init__(self, message: str, param_hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.param_hint = param_hint


class PenPreset(Protocol):
    """The preset fields pen resolution needs, supplied by a config or caller."""

    name: str
    width: float
    color: str
    opacity: float


class PaperPreset(Protocol):
    """The preset fields paper resolution needs, supplied by a config or caller."""

    name: str
    width: float
    height: float
    margin: float


def resolve_pen(
    pen_spec: str | None,
    *,
    default_pen: str | None = None,
    presets: Mapping[str, PenPreset] | None = None,
) -> Pen:
    """Resolve a preset name or inline ``WIDTH[,COLOR[,TYPE]]`` to a ``Pen``.

    Caller presets win over built-ins, and both win over inline parsing. The
    three inline fields are validated by ``Pen`` so an invalid field names that
    field and what it accepts instead of reporting an unknown pen.
    """
    spec = pen_spec if pen_spec is not None else default_pen or "fine"
    configured = presets or {}
    if spec in configured:
        preset = configured[spec]
        return Pen(
            name=preset.name,
            width_mm=preset.width,
            color=preset.color,
            opacity=preset.opacity,
            pen_type="rollerball",
        )

    try:
        preset = get_builtin_pen(spec)
        return Pen(
            name=preset.name,
            width_mm=preset.width,
            color=preset.color,
            opacity=preset.opacity,
            pen_type="rollerball",
        )
    except ValueError:
        pass

    parts = [part.strip() for part in spec.split(",")]
    if not 1 <= len(parts) <= 3:
        raise ResolutionError(
            f"expected inline format '{_PEN_FORMAT}': at most three comma-separated "
            f"fields, got {len(parts)}",
            "--pen",
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
        value = values.get(field, spec)
        hint = _PEN_FIELD_HINTS.get(field, f"a preset name or inline '{_PEN_FORMAT}'")
        raise ResolutionError(
            f"invalid {field} '{value}': {error['msg']}. Accepted: {hint}", "--pen"
        ) from e


def resolve_palette(palette_spec: str) -> Palette:
    """Resolve a built-in palette name or an inline ``name=width,#hex;...`` list."""
    if palette_spec in list_palettes():
        return get_palette(palette_spec)

    pens: list[Pen] = []
    for index, entry in enumerate(palette_spec.split(";"), start=1):
        if "=" not in entry:
            raise ResolutionError(
                f"Invalid palette pen {index}: '{entry}'. Use NAME=WIDTH,#HEX", "palette"
            )
        name, value = entry.split("=", 1)
        parts = value.split(",")
        if len(parts) != 2:
            raise ResolutionError(
                f"Invalid palette pen {index}: '{entry}'. Use NAME=WIDTH,#HEX", "palette"
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
            raise ResolutionError(f"Invalid palette pen {index}: '{entry}'. {e}", "palette") from e

    return Palette(name="inline", pens=pens)


def parse_margin_parts(
    parts: Sequence[str], param_hint: str = "--margin"
) -> float | tuple[float, float, float, float]:
    """Parse one or four comma-separated, non-negative millimetre margins."""
    try:
        values = [float(part.strip()) for part in parts]
    except ValueError as e:
        raise ResolutionError(
            f"margins must be numbers in millimetres; expected {_MARGIN_FORMAT}", param_hint
        ) from e

    if len(values) == 1:
        margin: float | tuple[float, float, float, float] = values[0]
    elif len(values) == 4:
        margin = (values[0], values[1], values[2], values[3])
    else:
        raise ResolutionError(f"expected {_MARGIN_FORMAT}, got {len(values)} values", param_hint)

    for value in (margin,) if isinstance(margin, float) else margin:
        if not math.isfinite(value) or value < 0:
            raise ResolutionError(
                "margins must be finite and non-negative in millimetres", param_hint
            )
    return margin


def check_drawable_area(paper: Paper, param_hint: str = "paper") -> None:
    """Reject margins that leave no room to draw on the resolved paper."""
    if paper.drawable_width_mm <= 0 or paper.drawable_height_mm <= 0:
        sides = "/".join(f"{value:g}" for value in paper.margins_mm)
        raise ResolutionError(
            f"margins {sides} (top/right/bottom/left) leave no drawable area on "
            f"{paper.width_mm:g}x{paper.height_mm:g} mm paper; "
            "reduce the margin or use a larger paper",
            param_hint,
        )


def resolve_paper(
    paper_spec: str | None,
    *,
    default_paper: str | None = None,
    presets: Mapping[str, PaperPreset] | None = None,
) -> Paper:
    """Resolve paper from a preset or inline ``WIDTHxHEIGHT[,MARGINS]``."""
    spec = paper_spec if paper_spec is not None else default_paper or "a4"
    configured = presets or {}
    if spec in configured:
        preset = configured[spec]
        return Paper(
            name=preset.name,
            width_mm=preset.width,
            height_mm=preset.height,
            margin_mm=preset.margin,
        )

    try:
        preset = get_builtin_paper(spec)
        return Paper(
            name=preset.name,
            width_mm=preset.width,
            height_mm=preset.height,
            margin_mm=preset.margin,
        )
    except ValueError:
        pass

    if "x" in spec:
        parts = [part.strip() for part in spec.split(",")]
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
                raise ResolutionError(
                    "inline size must be two positive numbers in millimetres", "--paper"
                )
            margin_mm: float | tuple[float, float, float, float] = (
                10.0 if len(parts) == 1 else parse_margin_parts(parts[1:], "--paper")
            )
            return Paper(
                name=f"inline-{width_mm}x{height_mm}",
                width_mm=width_mm,
                height_mm=height_mm,
                margin_mm=margin_mm,
            )

    raise ResolutionError(
        f"Unknown paper: '{spec}'. Use a preset name or inline format 'WIDTHxHEIGHT[,MARGINS]'",
        "--paper",
    )


def _coerce_setting_value(annotation: object, value_str: object, key: str) -> object:
    """Convert a CLI string using the settings model's field type.

    Library callers may pass already-typed values; those go straight to model
    validation instead of being parsed as ``KEY=VALUE`` strings.
    """
    if not isinstance(value_str, str):
        return value_str

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


def resolve_pfm(
    pfm_name: str | None,
    pfm_settings: Mapping[str, object],
    style_name: str | None = None,
    base_pfm: PFMSettingsUnion | None = None,
) -> PFMSettingsUnion:
    """Resolve a registered id, legacy preset, saved look and setting overrides.

    An explicit non-default PFM picks the algorithm or preset; otherwise a
    style picks the settings bundle, and settings win on top of either. With a
    base PFM and no explicit choice, the saved settings are preserved so an
    override does not discard the rest of a project's saved look.
    """
    if base_pfm is not None and pfm_name is None and style_name is None:
        pfm_type = base_pfm.pfm_type
        base_model = base_pfm.to_typed_settings()
    else:
        name = pfm_name if pfm_name is not None else DEFAULT_PFM

        if ":" in name:
            try:
                pfm_type, base_model = get_pfm_preset_by_id(name)
            except ValueError as e:
                raise ResolutionError(str(e), "--pfm") from e
        elif name in list_pfm_presets():
            pfm_type = get_pfm_for_preset(name)
            base_model = get_pfm_preset_settings(name)
        elif name in list_pfms():
            pfm_type = name
            _, settings_model = get_pfm(pfm_type)
            base_model = settings_model()
        else:
            try:
                get_pfm_preset_by_id(name)
            except ValueError as e:
                raise ResolutionError(f"Unknown PFM or preset: {e}", "--pfm") from e
            raise ResolutionError(f"Unknown PFM: '{name}'", "--pfm")

        # "default" is not a non-default PFM, so a style still applies to it.
        if style_name is not None and name == DEFAULT_PFM:
            base_model = get_style(style_name).sketch_lines
            pfm_type = "sketch_lines"

    # Keep only the fields the preset, style or caller actually set so the
    # drawing can tell an explicit value from a model default.
    explicit_keys = set(base_model.model_fields_set) | set(pfm_settings)

    _, settings_model = get_pfm(pfm_type)
    values = base_model.model_dump()
    for key, value_str in pfm_settings.items():
        if key not in settings_model.model_fields:
            raise ResolutionError(
                f"Unknown PFM setting: '{key}' for {pfm_type}", "-s/--pfm-setting"
            )
        annotation = settings_model.model_fields[key].annotation
        try:
            values[key] = _coerce_setting_value(annotation, value_str, key)
        except ValueError as e:
            raise ResolutionError(
                f"Invalid value '{value_str}' for PFM setting '{key}': {e}",
                "-s/--pfm-setting",
            ) from e

    try:
        settings = settings_model(
            **{key: value for key, value in values.items() if key in explicit_keys}
        )
    except ValidationError as e:
        error = e.errors()[0]
        key = str(error["loc"][0]) if error.get("loc") else "pfm"
        raise ResolutionError(
            f"Invalid value for PFM setting '{key}': {error['msg']}", "-s/--pfm-setting"
        ) from e
    return make_pfm_settings(pfm_type, settings)


def _parse_filter_spec(spec: str) -> tuple[str, dict[str, str]]:
    """Parse a filter specification like ``threshold:levels=4``."""
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
    """Convert filter parameter strings to the types in the filter signature."""
    filter_fn = get_filter(filter_name)
    try:
        hints = get_type_hints(filter_fn)
    except Exception:
        hints = {}

    converted: dict[str, Any] = {}
    for key, value_str in params.items():
        if key in hints:
            annotation = hints[key]
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


def build_filter_pipeline(filter_specs: Iterable[str]) -> FilterPipeline:
    """Build a filter pipeline from ``name:param=value`` specifications."""
    pipeline = FilterPipeline()
    for spec in filter_specs:
        name, params = _parse_filter_spec(spec)
        try:
            get_filter(name)
        except ValueError as e:
            raise ResolutionError(str(e), "filter") from e
        pipeline.add_step(name, **_convert_filter_params(name, params))
    return pipeline


def resolve_output_path(image_path: Path, output_path: str | Path | None) -> Path:
    """Determine the SVG path, defaulting to ``<input>_plot.svg`` beside the image."""
    if output_path:
        path = Path(output_path)
        if path.suffix.lower() != ".svg":
            path = path.with_suffix(".svg")
        return path
    return image_path.parent / f"{image_path.stem}_plot.svg"


def check_pen_palette_conflict(pen_spec: str | None, palette_spec: str | None) -> None:
    """Reject a run that asks for both a single pen and a palette."""
    if pen_spec is not None and palette_spec is not None:
        raise ResolutionError(
            "Options --pen and --palette are mutually exclusive: use one or the other."
        )


def build_project(
    image_path: str | Path,
    *,
    pfm: str | None = None,
    preset: str | None = None,
    paper: str | None = None,
    palette: str | None = None,
    pen: str | None = None,
    settings: Mapping[str, object] | None = None,
    filters: Iterable[str] | None = None,
    style: StyleName | None = None,
    dpi: int = 300,
    output_path: str | Path | None = None,
    background: bool | None = None,
    background_threshold: float | None = None,
    background_method: Literal["global", "local"] | None = None,
    saturation: float | None = None,
    palette_adapt: bool = False,
    key_layer: bool | None = None,
    auto_orient: bool = True,
    auto_equalize: bool = True,
    default_pen: str | None = None,
    default_paper: str | None = None,
    pen_presets: Mapping[str, PenPreset] | None = None,
    paper_presets: Mapping[str, PaperPreset] | None = None,
) -> Project:
    """Assemble a ``Project`` with the defaults of ``penpath convert``.

    With no filters the project uses grayscale (luminance). Background masking
    defaults to on with a palette and off for one pen; a key layer defaults to
    on with a palette and off for one pen via ``ImageRef.key_layer=None``.
    ``background_method`` and ``saturation`` are ``None`` when not explicitly
    chosen, which keeps the documented defaults without forcing the background
    or suppressing ``palette_adapt``. Config-owned presets can be supplied by
    the caller; resolution itself has no config-file knowledge.
    """
    check_pen_palette_conflict(pen, palette)
    path = Path(image_path)

    filter_pipeline = (
        build_filter_pipeline(filters) if filters is not None else _default_filter_pipeline()
    )
    resolved_paper = resolve_paper(paper, default_paper=default_paper, presets=paper_presets)

    if palette is not None:
        resolved_palette = resolve_palette(palette)
        selected_pens = list(resolved_palette.pens)
        selected_pen = None
        palette_name = resolved_palette.name if resolved_palette.name in list_palettes() else None
    else:
        selected_pen = resolve_pen(pen, default_pen=default_pen, presets=pen_presets)
        selected_pens = []
        palette_name = None

    pfm_name = pfm
    if preset is not None:
        pfm_name = f"{pfm}:{preset}" if pfm is not None else preset
    resolved_pfm = resolve_pfm(pfm_name, settings or {}, style)

    if background is not None:
        resolved_background = background
    elif palette is not None:
        resolved_background = True
    else:
        resolved_background = background_threshold is not None or background_method is not None

    return Project(
        image=ImageRef(
            path=path,
            filters=filter_pipeline,
            dpi=dpi,
            auto_orient=auto_orient,
            auto_equalize=auto_equalize,
            background=resolved_background,
            background_threshold=(
                DEFAULT_BACKGROUND_THRESHOLD
                if background_threshold is None
                else background_threshold
            ),
            background_method=background_method or "local",
            saturation=saturation if saturation is not None else 1.0,
            palette_adapt=palette_adapt and saturation is None,
            key_layer=key_layer,
        ),
        paper=resolved_paper,
        pen=selected_pen,
        pens=selected_pens,
        palette_name=palette_name,
        pfm=resolved_pfm,
        style=style,
        output_path=resolve_output_path(path, output_path),
    )


def _default_filter_pipeline() -> FilterPipeline:
    """Return the grayscale pipeline used when ``convert`` gets no filters."""
    pipeline = FilterPipeline()
    pipeline.add_step("grayscale", method="luminance")
    return pipeline


__all__ = [
    "PaperPreset",
    "PenPreset",
    "ResolutionError",
    "build_filter_pipeline",
    "build_project",
    "check_drawable_area",
    "check_pen_palette_conflict",
    "parse_margin_parts",
    "resolve_output_path",
    "resolve_palette",
    "resolve_paper",
    "resolve_pen",
    "resolve_pfm",
]
