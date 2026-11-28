"""Public Python API for penpath.

``convert`` is the one entry point from an image and a few simple names or
objects to an in-memory :class:`~penpath.core.convert.Drawing`. It resolves the
same project a ``penpath convert`` run uses, runs the core pipeline and writes
the SVG only when ``output`` is given. ``penpath`` re-exports it with
``Drawing`` so library callers need no CLI import.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from pydantic import BaseModel

from penpath.core import (
    Drawing,
    FilterPipeline,
    ImageRef,
    Palette,
    Paper,
    Pen,
    PFMSettings,
    Project,
    Reporter,
    ResolutionError,
    build_filter_pipeline,
    build_project,
    draw_project,
    resolve_output_path,
    resolve_palette,
    resolve_paper,
    resolve_pen,
    resolve_pfm,
)
from penpath.core.drawing.registry import get_registry
from penpath.core.styles import StyleName
from penpath.presets.palettes import list_palettes


def _settings_values(settings: Mapping[str, object] | BaseModel | None) -> dict[str, object]:
    """Return only the setting keys the caller actually set."""
    if settings is None:
        return {}
    if isinstance(settings, PFMSettings):
        typed = settings.to_typed_settings()
        return {key: getattr(typed, key) for key in typed.model_fields_set}
    if isinstance(settings, BaseModel):
        return {key: getattr(settings, key) for key in settings.model_fields_set}
    return dict(settings)


def _pfm_spec(
    pfm: str | PFMSettings | None,
    preset: str | None,
    settings: Mapping[str, object] | BaseModel | None,
) -> str | None:
    """Combine the PFM name and the optional named preset into one id."""
    name: str | None = None
    if isinstance(pfm, str):
        name = pfm
    elif isinstance(pfm, PFMSettings):
        name = pfm.pfm_type
    elif isinstance(settings, PFMSettings):
        name = settings.pfm_type
    if preset is not None:
        return f"{name}:{preset}" if name is not None else preset
    return name


def _pfm_type_of(settings: BaseModel) -> str | None:
    """Find the registered PFM whose settings model matches a typed model."""
    registry = get_registry()
    for name in registry.list():
        _, settings_model = registry.get(name)
        if type(settings) is settings_model:
            return name
    return None


def _apply_mode_background(project: Project, *, palette: bool) -> None:
    """Apply the background default of the selected pen mode.

    ``build_project`` masks the paper with a palette and not with a single pen.
    A base project that deliberately chose the other value keeps its choice;
    otherwise the chosen mode's default applies.
    """
    previous_palette = bool(project.pens)
    if project.image.background is None or project.image.background == previous_palette:
        project.image.background = palette


def _apply_palette(project: Project, palette: Palette | list[Pen]) -> None:
    """Replace a project's single pen with an explicit palette."""
    _apply_mode_background(project, palette=True)
    pens = list(palette.pens) if isinstance(palette, Palette) else list(palette)
    project.pens = pens
    project.pen = None
    project.palette_name = (
        palette.name if isinstance(palette, Palette) and palette.name in list_palettes() else None
    )


def _apply_pen(project: Project, pen: Pen) -> None:
    """Replace a project's palette with a single pen."""
    _apply_mode_background(project, palette=False)
    project.pen = pen
    project.pens = []
    project.palette_name = None


def convert(
    image: str | Path,
    *,
    pfm: str | PFMSettings | None = None,
    preset: str | None = None,
    paper: str | Paper | None = None,
    palette: str | Palette | list[Pen] | None = None,
    pen: str | Pen | None = None,
    settings: Mapping[str, object] | BaseModel | None = None,
    filters: Iterable[str] | FilterPipeline | None = None,
    style: StyleName | None = None,
    dpi: int = 300,
    output: str | Path | None = None,
    project: Project | None = None,
    use_vpype: bool = True,
    vpype_path: str = "vpype",
    max_resolution_px: int | None = None,
    no_downscale: bool = False,
    reporter: Reporter | None = None,
) -> Drawing:
    """Convert an image into a drawing, optionally writing its SVG.

    Simple names and objects are resolved by the same helpers the CLI uses.
    With ``project`` given it is the base: only the arguments supplied here
    override it, which lets the CLI reuse its config- and YAML-aware project
    construction while sharing this one conversion path. Pass ``dpi``
    explicitly when a base project's DPI must be kept; otherwise the documented
    default of 300 applies.

    Parameters
    ----------
    image : str | Path
        Path to the source raster image (PNG, JPG, TIFF, BMP).
    pfm : str | PFMSettings | None, optional
        Registered PFM id (for example ``"sketch_lines"``), a qualified
        ``"NAME:PRESET"`` id, a legacy preset name, or a PFM settings model.
    preset : str | None, optional
        Named preset for the chosen PFM, for example ``"fine"``. It is
        appended to ``pfm`` as ``"pfm:preset"``; without ``pfm`` the preset
        name alone selects the PFM.
    paper : str | Paper | None, optional
        Built-in paper name or inline ``"WIDTHxHEIGHT[,MARGINS]"``, or a
        ``Paper`` object. Defaults to A4.
    palette : str | Palette | list[Pen] | None, optional
        Built-in palette name, inline ``"name=width,#hex;..."``, ``Palette`` or
        a list of ``Pen`` objects. Mutually exclusive with ``pen``.
    pen : str | Pen | None, optional
        Built-in pen preset name, inline ``"WIDTH[,COLOR[,TYPE]]"`` or a
        ``Pen`` object. Defaults to the fine pen. Mutually exclusive with
        ``palette``.
    settings : Mapping[str, object] | BaseModel | None, optional
        PFM setting overrides, either a mapping of field names to values (for
        example ``{"seed": 42}``) or a typed settings model. These override the
        PFM's defaults and any values from ``preset`` or ``style``.
    filters : Iterable[str] | FilterPipeline | None, optional
        Filter specifications such as ``"grayscale:method=luminance"``, or a
        ready-made ``FilterPipeline``. Defaults to luminance grayscale.
    style : {'sketch', 'hatch', 'outline'} | None, optional
        Saved look applied before the settings overrides.
    dpi : int, optional
        Image DPI used for the drawn size when the paper fit is ``none``.
        Defaults to 300.
    output : str | Path | None, optional
        SVG path to write. When given, the SVG is written and the drawing is
        returned; when ``None``, only the in-memory drawing is returned.
    project : Project | None, optional
        Fully resolved base project. Explicit arguments above override it.
    use_vpype : bool, optional
        Let vpype optimise each pen's geometry before writing the SVG.
        Defaults to True and falls back to direct export if vpype is missing.
    vpype_path : str, optional
        Path to the vpype executable. Defaults to ``"vpype"``.
    max_resolution_px : int | None, optional
        Longest side of the working image, overriding the derived value.
    no_downscale : bool, optional
        Keep the source pixels instead of downscaling. Defaults to False.
    reporter : Reporter | None, optional
        Progress reporter. ``None`` discards progress messages.

    Returns
    -------
    Drawing
        The pens, optimised strokes and page placement. Call
        :meth:`~penpath.core.convert.Drawing.to_svg` to write it later.

    Raises
    ------
    ResolutionError
        If a name, spec, setting value or option combination is invalid.
    ValueError
        If an object argument cannot be used in a project.
    ImageLoadError
        If the source image cannot be loaded.
    """
    if pen is not None and palette is not None:
        raise ResolutionError("pen and palette are mutually exclusive: use one or the other.")

    explicit_settings = (
        settings if settings is not None else pfm if isinstance(pfm, PFMSettings) else None
    )
    values = _settings_values(explicit_settings)
    name = _pfm_spec(pfm, preset, settings)
    if (
        name is None
        and isinstance(explicit_settings, BaseModel)
        and not isinstance(explicit_settings, PFMSettings)
    ):
        inferred = _pfm_type_of(explicit_settings)
        if inferred is not None:
            name = inferred if preset is None else f"{inferred}:{preset}"

    pipeline = filters if isinstance(filters, FilterPipeline) else None
    filter_specs = (
        None if pipeline is not None else (list(filters) if filters is not None else None)
    )
    image_path = Path(image)

    if project is None:
        resolved = build_project(
            image_path,
            pfm=name,
            paper=paper if isinstance(paper, str) else None,
            palette=palette if isinstance(palette, str) else None,
            pen=pen if isinstance(pen, str) else None,
            settings=values,
            filters=filter_specs,
            style=style,
            dpi=dpi,
            output_path=output,
        )
    else:
        resolved = project.model_copy(deep=True)
        if resolved.image.path != image_path:
            resolved.image = ImageRef.model_validate(
                {**resolved.image.model_dump(), "path": image_path}
            )
        if name is not None or values or style is not None:
            resolved.pfm = resolve_pfm(
                name,
                values,
                style,
                base_pfm=resolved.pfm if name is None and style is None else None,
            )
        if style is not None:
            resolved.style = style
        resolved.image.dpi = dpi
        if output is not None:
            resolved.output_path = resolve_output_path(image_path, output)
        if isinstance(paper, str):
            resolved.paper = resolve_paper(paper)
        if isinstance(pen, str):
            _apply_pen(resolved, resolve_pen(pen))
        elif isinstance(palette, str):
            _apply_palette(resolved, resolve_palette(palette))
        if filter_specs is not None:
            resolved.image.filters = build_filter_pipeline(filter_specs)

    if isinstance(paper, Paper):
        resolved.paper = paper
    if pipeline is not None:
        resolved.image.filters = pipeline
    if isinstance(pen, Pen):
        _apply_pen(resolved, pen)
    elif palette is not None and not isinstance(palette, str):
        _apply_palette(resolved, palette)

    drawing = draw_project(
        resolved,
        max_resolution_px=max_resolution_px,
        no_downscale=no_downscale,
        reporter=reporter,
    )
    if output is not None:
        drawing.to_svg(
            output,
            use_vpype=use_vpype,
            vpype_path=vpype_path,
            reporter=reporter,
        )
    return drawing


__all__ = ["convert"]
