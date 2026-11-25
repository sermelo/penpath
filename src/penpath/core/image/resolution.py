"""Plan and apply the working resolution used by the drawing algorithms."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from PIL import Image

if TYPE_CHECKING:
    from penpath.core.models import Paper

MIN_WORKING_LONGEST_PX = 256
MAX_WORKING_LONGEST_PX = 1024


@dataclass(frozen=True)
class WorkingResolution:
    """The resolution a drawing algorithm works on, and how to get there.

    Attributes
    ----------
    source_size_px : tuple[int, int]
        Source image size as (width, height) in pixels.
    target_size_px : tuple[int, int]
        Size of the image handed to the drawing algorithm, in pixels.
    scale : float
        Target longest side divided by source longest side. ``1.0`` means
        the source image is used unchanged.
    working_px : int
        Derived (or overridden) longest side in pixels, before the
        never-enlarge rule is applied.
    paper_side_mm : float
        Longest side of the paper the resolution was derived from.
    pen_width_mm : float
        Pen tip width the resolution was derived from.
    """

    source_size_px: tuple[int, int]
    target_size_px: tuple[int, int]
    scale: float
    working_px: int
    paper_side_mm: float
    pen_width_mm: float


def plan_working_resolution(
    image_size_px: tuple[int, int],
    paper: Paper,
    pen_width_mm: float,
    max_longest_px: int | None = None,
) -> WorkingResolution:
    """Plan the resolution at which an image should be drawn.

    One image pixel per pen width is enough: a pen cannot draw finer than its
    own tip. The derived longest side is
    ``paper_longest_side_mm / pen_width_mm``, clamped to
    ``[MIN_WORKING_LONGEST_PX, MAX_WORKING_LONGEST_PX]``. An explicit
    ``max_longest_px`` replaces the derived value and is not clamped. The
    source image is never enlarged and its aspect ratio is preserved.

    Parameters
    ----------
    image_size_px : tuple[int, int]
        Source image size as (width, height) in pixels.
    paper : Paper
        Paper the plot will be made on. Its longest side drives the rule.
    pen_width_mm : float
        Pen tip width in millimetres. Must be positive.
    max_longest_px : int | None, optional
        Explicit longest side in pixels. Overrides the derived value without
        clamping and never enlarges the source image. Default is None.

    Returns
    -------
    WorkingResolution
        The planned size, scale factor, and inputs used to derive it.

    Raises
    ------
    ValueError
        If the image size, pen width, or override is not positive.
    """
    source_width, source_height = image_size_px
    if source_width <= 0 or source_height <= 0:
        raise ValueError("Image size must have positive width and height")
    if pen_width_mm <= 0:
        raise ValueError("Pen width must be positive")
    if max_longest_px is not None and max_longest_px <= 0:
        raise ValueError("max_longest_px must be positive")

    paper_side_mm = max(paper.width_mm, paper.height_mm)
    derived_px = max(
        MIN_WORKING_LONGEST_PX,
        min(MAX_WORKING_LONGEST_PX, round(paper_side_mm / pen_width_mm)),
    )
    working_px = derived_px if max_longest_px is None else max_longest_px

    source_longest = max(source_width, source_height)
    target_longest = min(source_longest, working_px)
    scale = target_longest / source_longest

    if target_longest == source_longest:
        target_size_px = (source_width, source_height)
    elif source_width >= source_height:
        target_size_px = (target_longest, max(1, round(source_height * scale)))
    else:
        target_size_px = (max(1, round(source_width * scale)), target_longest)

    return WorkingResolution(
        source_size_px=image_size_px,
        target_size_px=target_size_px,
        scale=scale,
        working_px=working_px,
        paper_side_mm=paper_side_mm,
        pen_width_mm=pen_width_mm,
    )


def apply_working_resolution(
    image: Image.Image,
    resolution: WorkingResolution,
) -> Image.Image:
    """Resize an image to the planned working resolution with LANCZOS.

    The image mode and aspect ratio are preserved. When the source is already
    at or below the working resolution it is returned unchanged.

    Parameters
    ----------
    image : PIL.Image.Image
        Source image.
    resolution : WorkingResolution
        Plan returned by :func:`plan_working_resolution`.

    Returns
    -------
    PIL.Image.Image
        The working image, in the same mode as the source.
    """
    if resolution.target_size_px == image.size:
        return image
    return image.resize(resolution.target_size_px, Image.Resampling.LANCZOS)


__all__ = [
    "MAX_WORKING_LONGEST_PX",
    "MIN_WORKING_LONGEST_PX",
    "WorkingResolution",
    "apply_working_resolution",
    "plan_working_resolution",
]
