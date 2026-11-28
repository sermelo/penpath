"""Render an SVG, G-code file or :class:`~penpath.core.convert.Drawing` as an image.

This is the single rendering path shared by the public :func:`preview` call and
``penpath preview``: the same parsers, pen styles, plot simulator and render
budget apply to both.
"""

from __future__ import annotations

import math
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from penpath.core.convert import Drawing
from penpath.core.gcode_preview import (
    GcodePreviewError,
    gcode_to_strokes,
    parse_gcode_header,
)
from penpath.core.output.gcode import page_origin_mm
from penpath.core.profiles import MachineProfile, ProfileError, load_profile
from penpath.core.simulation import (
    PenStroke,
    check_render_budget,
    render_size_px,
    simulate_plot,
)
from penpath.core.svg_parse import get_svg_paper_size, parse_svg_strokes
from penpath.presets.palettes import STABILO_88
from penpath.presets.pens import PEN_PRESETS

DEFAULT_PX_PER_MM = 4.0
MM_PER_INCH = 25.4
FALLBACK_PAPER_MM = (210.0, 297.0)
DEFAULT_PAPER_COLOR = "#FFFFFF"
TRAVEL_COLOR = "#C8C8C8"
TRAVEL_WIDTH_MM = 0.1
OUTLINE_COLOR = "#A0A0A0"
OUTLINE_WIDTH_MM = 0.2
_NO_STROKES = "No pen strokes found in drawing (check --layer if used)"

type _Prepared = tuple[list[PenStroke], list[PenStroke], tuple[float, float], tuple[str, ...]]


class PreviewError(ValueError):
    """Raised when an input cannot be rendered as a preview."""


class InvalidPaperColorError(PreviewError):
    """Raised when the paper colour is not one the image renderer understands."""


class RenderBudgetError(PreviewError):
    """Raised when the raster would exceed the 40 MP budget.

    Attributes
    ----------
    detail : str
        Size, megapixels and limit, without the suggested fix. The CLI uses it
        to build its flag-aware message.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(
            f"Render too large: {detail}. Lower px_per_mm (or dpi) or pass force=True."
        )
        self.detail = detail


@dataclass(frozen=True, slots=True)
class PreviewResult:
    """The written image and the values reported by the CLI.

    Attributes
    ----------
    path : Path
        Image file written.
    width_px, height_px : int
        Size of the rendered image.
    width_mm, height_mm : float
        Paper or bed size in millimetres.
    warnings : tuple[str, ...]
        Non-fatal messages to show to a command-line caller.
    """

    path: Path
    width_px: int
    height_px: int
    width_mm: float
    height_mm: float
    warnings: tuple[str, ...] = ()


def _paper_size_mm(svg_path: Path) -> tuple[float, float]:
    """Return the SVG page size in mm, falling back to A4 when unreadable."""
    return get_svg_paper_size(svg_path) or FALLBACK_PAPER_MM


def _pen_styles() -> dict[str, tuple[str, float]]:
    """Map built-in pen names to the colour and width used in their SVG."""
    styles = {pen.name: (pen.color, pen.width_mm) for pen in STABILO_88.pens}
    styles.update({name: (pen.color, pen.width) for name, pen in PEN_PRESETS.items()})
    return styles


def _rectangle(x0: float, y0: float, x1: float, y1: float) -> PenStroke:
    """Return a closed grey outline in bed-canvas millimetres."""
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    return PenStroke(corners, OUTLINE_WIDTH_MM, OUTLINE_COLOR)


def _page_to_bed(
    point: tuple[float, float],
    page_size_mm: tuple[float, float],
    origin_mm: tuple[float, float],
    profile: MachineProfile,
) -> tuple[float, float]:
    """Map a page point to the bed canvas, with pen-space Y growing up."""
    x, y = point
    pen_y = origin_mm[1] + (page_size_mm[1] - y if profile.bed.invert_y else y)
    return (origin_mm[0] + x, profile.bed.size_mm[1] - pen_y)


def _outlines(
    profile: MachineProfile,
    origin_mm: tuple[float, float],
    page_size_mm: tuple[float, float],
    px_per_mm: float,
) -> list[PenStroke]:
    """Return the bed and page outlines in bed-canvas millimetres."""
    bed_width, bed_height = profile.bed.size_mm
    page_width, page_height = page_size_mm
    page_top = bed_height - origin_mm[1] - page_height
    right = (round(bed_width * px_per_mm) - 1) / px_per_mm
    bottom = (round(bed_height * px_per_mm) - 1) / px_per_mm
    return [
        _rectangle(0.0, 0.0, max(0.0, right), max(0.0, bottom)),
        _rectangle(
            origin_mm[0],
            page_top,
            origin_mm[0] + page_width,
            page_top + page_height,
        ),
    ]


def _preview_gcode(
    path: Path, layer_label: str | None, include_pen_up: bool, px_per_mm: float
) -> _Prepared:
    """Read penpath G-code, undoing the emitter's page and profile transforms."""
    text = path.read_text(encoding="utf-8")
    header = parse_gcode_header(text)
    profile = None
    warnings: tuple[str, ...] = ()
    if header.profile:
        try:
            profile = load_profile(header.profile)
        except ProfileError:
            warnings = (f"Profile {header.profile!r} not found; previewing machine coordinates.",)
    paper_size_mm = header.page or (
        profile.bed.size_mm if profile is not None else FALLBACK_PAPER_MM
    )
    try:
        strokes = gcode_to_strokes(
            text, paper_size_mm, profile, _pen_styles(), layer_label, include_pen_up
        )
    except GcodePreviewError as exc:
        raise PreviewError(f"Could not preview G-code: {exc}") from exc
    if profile is None:
        return strokes, [], paper_size_mm, warnings

    origin_mm = header.page_origin or page_origin_mm(profile, paper_size_mm)
    canvas_mm = profile.bed.size_mm
    strokes = [
        PenStroke(
            [_page_to_bed(point, paper_size_mm, origin_mm, profile) for point in stroke.polyline],
            stroke.width_mm,
            stroke.color,
            stroke.pen_up,
        )
        for stroke in strokes
    ]
    return strokes, _outlines(profile, origin_mm, paper_size_mm, px_per_mm), canvas_mm, warnings


def _from_svg(path: Path, layer: str | None, travel: bool) -> _Prepared:
    """Parse an SVG into strokes and its paper size."""
    try:
        strokes = parse_svg_strokes(path, layer=layer, include_pen_up=travel)
    except (ET.ParseError, OSError, ValueError) as exc:
        raise PreviewError(f"Could not parse SVG: {exc}") from exc
    return strokes, [], _paper_size_mm(path), ()


def _prepare(
    source: Drawing | str | Path,
    layer: str | None,
    travel: bool,
    px_per_mm: float,
) -> _Prepared:
    """Return ink strokes, outlines, canvas size and warnings for a source."""
    if isinstance(source, Drawing):
        # A Drawing's strokes are in working-image pixels; its SVG export already
        # maps them to paper millimetres and pen layers. Use a temporary SVG so
        # Drawing and file inputs share exactly one parser path.
        if not any(source.strokes_by_pen):
            raise PreviewError(_NO_STROKES)
        with tempfile.TemporaryDirectory(prefix="penpath-preview-") as temp_dir:
            svg_path = Path(temp_dir) / "drawing.svg"
            source.to_svg(svg_path, use_vpype=False)
            return _from_svg(svg_path, layer, travel)
    path = Path(source)
    if path.suffix.lower() == ".gcode":
        try:
            return _preview_gcode(path, layer, travel, px_per_mm)
        except OSError as exc:
            raise PreviewError(f"Could not read G-code: {exc}") from exc
    return _from_svg(path, layer, travel)


def _resolve_px_per_mm(dpi: float | None, px_per_mm: float) -> float:
    """Turn a real DPI or a pixels-per-millimetre value into one resolution."""
    if dpi is not None:
        if not math.isfinite(dpi) or dpi <= 0:
            raise PreviewError("dpi must be a finite number greater than zero")
        return dpi / MM_PER_INCH
    if not math.isfinite(px_per_mm) or px_per_mm <= 0:
        raise PreviewError("px_per_mm must be a finite number greater than zero")
    return px_per_mm


def _render(
    drawing_or_svg: Drawing | str | Path,
    output: str | Path,
    dpi: float | None,
    px_per_mm: float,
    force: bool,
    paper_color: str,
    layer: str | None,
    travel: bool,
) -> PreviewResult:
    """Run the shared renderer and return the result with CLI-facing numbers."""
    resolution = _resolve_px_per_mm(dpi, px_per_mm)
    strokes, outlines, (width_mm, height_mm), warnings = _prepare(
        drawing_or_svg, layer, travel, resolution
    )
    if not strokes:
        raise PreviewError(_NO_STROKES)
    width_px, height_px = render_size_px(width_mm, height_mm, resolution)
    if not force:
        try:
            check_render_budget(width_px, height_px)
        except ValueError as exc:
            raise RenderBudgetError(str(exc)) from exc
    try:
        image = simulate_plot(
            [*outlines, *strokes],
            paper_width_mm=width_mm,
            paper_height_mm=height_mm,
            paper_color=paper_color,
            dpi_px_per_mm=resolution,
            travel_color=TRAVEL_COLOR if travel else None,
            travel_width_mm=TRAVEL_WIDTH_MM,
        )
    except ValueError as exc:
        raise InvalidPaperColorError(str(exc)) from exc
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    return PreviewResult(
        path=output_path,
        width_px=image.width,
        height_px=image.height,
        width_mm=width_mm,
        height_mm=height_mm,
        warnings=warnings,
    )


def render_preview(
    drawing_or_svg: Drawing | str | Path,
    output: str | Path,
    *,
    dpi: float | None = None,
    px_per_mm: float = DEFAULT_PX_PER_MM,
    force: bool = False,
    paper_color: str = DEFAULT_PAPER_COLOR,
    layer: str | None = None,
    travel: bool = False,
) -> PreviewResult:
    """Render a preview and return its path together with the reported sizes.

    This is the form the CLI uses to print its message; library callers should
    use :func:`preview`, which returns just the output path.
    """
    return _render(drawing_or_svg, output, dpi, px_per_mm, force, paper_color, layer, travel)


def preview(
    drawing_or_svg: Drawing | str | Path,
    output: str | Path,
    *,
    dpi: float | None = None,
    px_per_mm: float = DEFAULT_PX_PER_MM,
    force: bool = False,
    paper_color: str = DEFAULT_PAPER_COLOR,
    layer: str | None = None,
    travel: bool = False,
) -> Path:
    """Render a simulated plot to an image file.

    Parameters
    ----------
    drawing_or_svg : Drawing | str | Path
        A :class:`~penpath.core.convert.Drawing`, an SVG path, or a ``.gcode``
        file written by ``penpath gcode``. A Drawing is exported to a temporary
        SVG so the same parser, layers and paper size apply as for a file.
    output : str | Path
        Path of the image to write, normally a PNG. Parents are created.
    dpi : float | None, optional
        Real dots per inch, converted with ``/25.4``. When given, it takes
        precedence over ``px_per_mm``.
    px_per_mm : float, optional
        Pixels per millimetre. Defaults to 4.0, the same as ``penpath preview``.
    force : bool, optional
        Render even if the raster exceeds the 40 MP budget. Defaults to False.
    paper_color : str, optional
        Paper background colour, as hex or a named CSS colour.
    layer : str | None, optional
        Only render this pen layer. Defaults to all layers. G-code bed and
        page outlines stay visible.
    travel : bool, optional
        Draw pen-up travel moves as thin light lines under the ink. Defaults
        to False.

    Returns
    -------
    Path
        The written image path.

    Raises
    ------
    PreviewError
        If the source cannot be parsed, has no ink, or the resolution is bad.
    RenderBudgetError
        If the raster exceeds the 40 MP budget and ``force`` is False.
    InvalidPaperColorError
        If ``paper_color`` is not a colour the renderer understands.
    """
    return _render(drawing_or_svg, output, dpi, px_per_mm, force, paper_color, layer, travel).path


__all__ = [
    "DEFAULT_PX_PER_MM",
    "InvalidPaperColorError",
    "PreviewError",
    "PreviewResult",
    "RenderBudgetError",
    "preview",
    "render_preview",
]
