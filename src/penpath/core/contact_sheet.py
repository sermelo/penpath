"""Render a contact sheet of every PFM and preset on one image."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import ceil

from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel

from penpath.core.drawing.pfm_hatch import HatchSettings
from penpath.core.drawing.pfm_patch_hatch import PatchHatchSettings
from penpath.core.drawing.pfm_tsp import TSPSettings
from penpath.core.drawing.registry import get_pfm
from penpath.core.image.filters import auto_equalize, grayscale
from penpath.core.simulation import PenStroke, simulate_plot

TILE_WIDTH_MM = 60.0
_SHEET_COLOR = "#E8E8E8"
_BORDER_COLOR = "#999999"
_CAPTION_COLOR = "#333333"
_MARGIN_PX = 8
_GAP_PX = 8
_BORDER_PX = 1


@dataclass(frozen=True, slots=True)
class ContactSheetEntry:
    """One PFM and optional preset to draw on the sheet.

    Attributes
    ----------
    pfm : str
        Registered PFM name.
    preset : str | None
        Preset name or qualified ``PFM:PRESET`` id, or ``None`` for the PFM's
        own defaults.
    settings : BaseModel
        Settings passed to the PFM as a deep copy.
    """

    pfm: str
    preset: str | None
    settings: BaseModel

    @property
    def label(self) -> str:
        """Return ``pfm`` or ``pfm:preset`` as the tile caption and error key.

        A qualified preset id is already complete, so it is not prefixed again.
        """
        if self.preset is None:
            return self.pfm
        return self.preset if ":" in self.preset else f"{self.pfm}:{self.preset}"


@dataclass(frozen=True, slots=True)
class ContactSheetResult:
    """Rendered sheet and the failures found while drawing it.

    Attributes
    ----------
    image : PIL.Image.Image
        RGB contact sheet with one tile per entry.
    errors : dict[str, str]
        Error messages keyed by the label of the entry that failed.
    """

    image: Image.Image
    errors: dict[str, str]


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    width: float,
) -> str:
    """Shorten text with an ellipsis until it fits ``width``."""
    if draw.textlength(text, font=font) <= width:
        return text
    shortened = text
    while shortened and draw.textlength(f"{shortened}...", font=font) > width:
        shortened = shortened[:-1]
    return f"{shortened}..." if shortened else ""


def _caption_lines(entry: ContactSheetEntry) -> list[str]:
    """Split a label into at most two lines: the PFM, then the preset."""
    if entry.preset is None:
        return [entry.pfm]
    prefix = f"{entry.pfm}:"
    return [entry.pfm, entry.preset.removeprefix(prefix)]


def _draw_tile_frame(
    draw: ImageDraw.ImageDraw,
    x0: int,
    y0: int,
    paper_x: int,
    paper_y: int,
    paper_w: int,
    paper_h: int,
    caption_px: int,
    cell_w: int,
) -> None:
    """Draw the caption band and the grey border around a tile."""
    draw.rectangle((x0, y0, x0 + cell_w - 1, y0 + caption_px - 1), fill=_SHEET_COLOR)
    draw.rectangle(
        (
            paper_x - _BORDER_PX,
            paper_y - _BORDER_PX,
            paper_x + paper_w + _BORDER_PX - 1,
            paper_y + paper_h + _BORDER_PX - 1,
        ),
        outline=_BORDER_COLOR,
        width=_BORDER_PX,
    )


def _draw_caption(
    draw: ImageDraw.ImageDraw,
    entry: ContactSheetEntry,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    font_size: int,
    x0: int,
    y0: int,
    cell_w: int,
) -> None:
    """Draw a label in the caption band, one line for the PFM and one for the preset."""
    line_step = font_size + 2
    for index, line in enumerate(_caption_lines(entry)):
        fitted = _fit_text(draw, line, font, cell_w - 4)
        draw.text((x0 + 2, y0 + 1 + index * line_step), fitted, font=font, fill=_CAPTION_COLOR)


def render_contact_sheet(
    image: Image.Image,
    entries: Sequence[ContactSheetEntry],
    *,
    max_resolution: int = 256,
    dpi: float = 4.0,
    columns: int = 4,
    paper_color: str = "#FFFFFF",
    ink_color: str = "#000000",
    pen_width_mm: float = 0.3,
) -> ContactSheetResult:
    """Draw every entry's simulated plot on a single light-grey sheet.

    The source image is downscaled with LANCZOS so its longest side is at most
    ``max_resolution`` (it is never enlarged), then equalized and converted to
    luminance greyscale once for all entries. Entries run in ``(pfm, preset)``
    order with a deep copy of their settings. Each PFM's pixel strokes are
    mapped onto a 60 mm wide tile and simulated with ``simulate_plot``; Hatch
    also receives the tile's physical scale and the sheet's pen width. A
    failing entry becomes a labelled error tile and the rest still render.

    Parameters
    ----------
    image : PIL.Image.Image
        Source image, in any mode Pillow can convert to luminance greyscale.
    entries : Sequence[ContactSheetEntry]
        PFM/preset/settings combinations to draw, one tile each.
    max_resolution : int, optional
        Longest side of the working image in pixels. Default is 256.
    dpi : float, optional
        Pixels per millimetre for the simulated tiles and sheet. Default is 4.
    columns : int, optional
        Number of tiles per row. Default is 4.
    paper_color : str, optional
        Tile paper colour. Default is white.
    ink_color : str, optional
        Stroke and error-text colour. Default is black.
    pen_width_mm : float, optional
        Stroke width of the simulated pen in millimetres. Default is 0.3.

    Returns
    -------
    ContactSheetResult
        The RGB sheet and a mapping of failed entry labels to error messages.

    Raises
    ------
    ValueError
        If ``max_resolution``, ``dpi`` or ``columns`` is not positive, or if
        ``entries`` is empty.
    """
    if max_resolution <= 0:
        raise ValueError("max_resolution must be positive")
    if dpi <= 0:
        raise ValueError("dpi must be positive")
    if columns <= 0:
        raise ValueError("columns must be positive")
    if not entries:
        raise ValueError("entries must not be empty")

    source_width, source_height = image.size
    longest = max(source_width, source_height)
    if longest > max_resolution:
        scale = max_resolution / longest
        working = image.resize(
            (max(1, round(source_width * scale)), max(1, round(source_height * scale))),
            Image.Resampling.LANCZOS,
        )
    else:
        working = image.copy()
    working = grayscale(auto_equalize(working), method="luminance")

    ordered = sorted(entries, key=lambda entry: (entry.pfm, entry.preset or ""))
    working_width, working_height = working.size
    tile_height_mm = TILE_WIDTH_MM * working_height / working_width
    tile_w = max(1, round(TILE_WIDTH_MM * dpi))
    tile_h = max(1, round(tile_height_mm * dpi))
    font_size = max(10, round(3 * dpi))
    font = ImageFont.load_default(size=font_size)
    caption_px = max(24, round(9 * dpi))
    cell_w = tile_w + 2 * _BORDER_PX
    cell_h = caption_px + tile_h + 2 * _BORDER_PX
    rows = ceil(len(ordered) / columns)
    sheet_w = 2 * _MARGIN_PX + columns * cell_w + (columns - 1) * _GAP_PX
    sheet_h = 2 * _MARGIN_PX + rows * cell_h + (rows - 1) * _GAP_PX

    sheet = Image.new("RGB", (sheet_w, sheet_h), _SHEET_COLOR)
    draw = ImageDraw.Draw(sheet)
    mm_per_px = TILE_WIDTH_MM / working_width
    errors: dict[str, str] = {}

    for index, entry in enumerate(ordered):
        column, row = index % columns, index // columns
        x0 = _MARGIN_PX + column * (cell_w + _GAP_PX)
        y0 = _MARGIN_PX + row * (cell_h + _GAP_PX)
        paper_x, paper_y = x0 + _BORDER_PX, y0 + caption_px + _BORDER_PX
        _draw_tile_frame(draw, x0, y0, paper_x, paper_y, tile_w, tile_h, caption_px, cell_w)
        _draw_caption(draw, entry, font, font_size, x0, y0, cell_w)

        try:
            pfm_fn, _ = get_pfm(entry.pfm)
            settings = entry.settings.model_copy(deep=True)
            pfm_kwargs: dict[str, float] = {}
            if isinstance(settings, (HatchSettings, PatchHatchSettings, TSPSettings)):
                pfm_kwargs = {
                    "pixels_per_mm": working_width / TILE_WIDTH_MM,
                    "pen_width_mm": pen_width_mm,
                }
            lines = pfm_fn(working, settings, **pfm_kwargs)
            strokes = [
                PenStroke(
                    [
                        (float(point[0]) * mm_per_px, float(point[1]) * mm_per_px)
                        for point in line.coords
                    ],
                    pen_width_mm,
                    ink_color,
                )
                for line in lines
                if len(line.coords) >= 2
            ]
            tile = simulate_plot(
                strokes,
                TILE_WIDTH_MM,
                tile_height_mm,
                paper_color=paper_color,
                dpi_px_per_mm=dpi,
            )
            sheet.paste(tile, (paper_x, paper_y))
        except Exception as exc:
            message = " ".join(f"{type(exc).__name__}: {exc}".split())
            errors[entry.label] = message
            draw.rectangle(
                (paper_x, paper_y, paper_x + tile_w - 1, paper_y + tile_h - 1), fill=paper_color
            )
            draw.text(
                (paper_x + 3, paper_y + 3),
                _fit_text(draw, message, font, tile_w - 6),
                font=font,
                fill=ink_color,
            )

    return ContactSheetResult(image=sheet, errors=errors)


__all__ = [
    "TILE_WIDTH_MM",
    "ContactSheetEntry",
    "ContactSheetResult",
    "render_contact_sheet",
]
