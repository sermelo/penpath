"""Saved looks for ``penpath convert --style``.

A look is a bundle of Sketch Lines settings plus, for ``outline``, an edge pass
that runs before the tone pass. The presets live in the library so a Python
caller can resolve and draw a look without going through the CLI.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel
from shapely import LineString

from penpath.core.drawing.outline import OutlineSettings, outline_strokes
from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings

if TYPE_CHECKING:
    from PIL import Image

StyleName = Literal["sketch", "hatch", "outline"]

STYLE_NAMES: tuple[StyleName, ...] = ("sketch", "hatch", "outline")


class StylePreset(BaseModel):
    """One saved look: the tone settings and an optional edge pass."""

    name: StyleName
    description: str
    sketch_lines: SketchLinesSettings
    outline: OutlineSettings | None = None


STYLE_PRESETS: dict[StyleName, StylePreset] = {
    "sketch": StylePreset(
        name="sketch",
        description="Part 1 default: tone-adaptive sketch lines with visible tone steps.",
        sketch_lines=SketchLinesSettings(),
    ),
    "hatch": StylePreset(
        name="hatch",
        description="Directional cross-hatching with clear tone steps.",
        sketch_lines=SketchLinesSettings(
            line_density=0.75,
            max_fill=78.0,
            tone_coverage=0.55,
            tone_exponent=0.5,
            texture_limit=0.85,
            min_length=5.0,
            max_length=50.0,
            angle_range=(45.0, 135.0),
            shading_enabled=True,
            shading_threshold=0.6,
            search_angle_step=10.0,
        ),
    ),
    "outline": StylePreset(
        name="outline",
        description="Clean edge strokes over a light tone pass, with minimal ink.",
        sketch_lines=SketchLinesSettings(
            line_density=0.35,
            max_fill=70.0,
            tone_coverage=0.4,
            tone_exponent=0.7,
            texture_limit=0.6,
            min_length=4.0,
            max_length=30.0,
        ),
        outline=OutlineSettings(
            blur_sigma=2.0,
            edge_sigma=2.0,
            low_threshold=0.3,
            high_threshold=0.5,
            close_radius=1,
            min_component_pixels=24,
            min_length=24.0,
            simplify_tolerance=2.0,
        ),
    ),
}


def list_styles() -> list[str]:
    """Return the style names in the order shown by ``--help``."""
    return list(STYLE_NAMES)


def get_style(name: str) -> StylePreset:
    """Return a saved look by name.

    Parameters
    ----------
    name : str
        One of ``sketch``, ``hatch`` or ``outline``.

    Returns
    -------
    StylePreset
        The look's validated settings.

    Raises
    ------
    ValueError
        If the name is not a saved look. The message lists the valid names.
    """
    if name not in STYLE_PRESETS:
        raise ValueError(f"Unknown style: '{name}'. Choose one of: {', '.join(STYLE_NAMES)}")
    return STYLE_PRESETS[name]


def draw_styled_lines(
    image: Image.Image,
    pfm_fn: Callable[..., list[LineString]],
    pfm_settings: BaseModel,
    style: str | None = None,
    pfm_kwargs: Mapping[str, object] | None = None,
) -> list[LineString]:
    """Draw one pen image, running the style's edge pass before the tone pass.

    With no style, or a look without an edge pass, this is just the PFM call, so
    the default path is unchanged. ``outline`` first appends the deterministic
    contour strokes from the image and then the light tone strokes from the PFM;
    both are returned in one list for the geometry optimizer and SVG writer.
    ``pfm_kwargs`` is forwarded only to the PFM call, so extra arguments such as
    the physical scale needed by Hatch never reach the outline pass.

    Parameters
    ----------
    image : PIL.Image.Image
        Working image for this pen, in pixels.
    pfm_fn : Callable
        Registered PFM function taking ``(image, settings)`` and, for PFMs that
        need it, extra keyword arguments.
    pfm_settings : BaseModel
        Validated PFM settings, after any ``-s`` overrides.
    style : str | None
        Saved look name, or ``None`` for the default path.
    pfm_kwargs : Mapping[str, object] | None
        Extra keyword arguments for the PFM. Defaults to none, which calls the
        PFM exactly as ``pfm_fn(image, settings)``.

    Returns
    -------
    list[LineString]
        Edge strokes followed by tone strokes, in image pixel coordinates.
    """
    preset = get_style(style) if style is not None else None
    lines: list[LineString] = []
    if preset is not None and preset.outline is not None:
        lines.extend(outline_strokes(image, preset.outline))
    lines.extend(pfm_fn(image, pfm_settings, **(pfm_kwargs or {})))
    return lines


__all__ = [
    "STYLE_NAMES",
    "STYLE_PRESETS",
    "StyleName",
    "StylePreset",
    "draw_styled_lines",
    "get_style",
    "list_styles",
]
