"""Sketch Squares PFM (Pen Follower Module) implementation.

Port of ``PFMSketchSquaresBasic`` and its ``AbstractSketchPFM`` base from
DrawingBotV3 (v1.6.25-stable-free). Each ray replaces the Sketch Lines random
angle with the reference's position-dependent angle field, which bends the
strokes into a curved grid. As with the Sketch Lines port, the ported logic
follows DrawingBotV3's GPL-3.0 licence handling (see the repository LICENSE).
"""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field
from shapely import LineString

from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings, _run_sketch_engine

if TYPE_CHECKING:
    from PIL import Image


class SketchSquaresSettings(BaseModel):
    """Settings for the Sketch Squares PFM algorithm.

    Parameters
    ----------
    grid_angle : float
        Reference "Start Angle" in degrees (-360 - 360), added to the
        position-dependent angle field from ``PFMSketchSquaresBasic``.
    line_density : float
        Overall ink density multiplier (0.01 - 10.0). Higher = more ink, with
        the same luminance-progress stop rule as Sketch Lines.
    min_length : float
        Minimum segment length in image pixels (1 - 1000). Reference default 2.
    max_length : float
        Maximum segment length in image pixels (1 - 5000). Reference default 40.
    max_fill : float
        Maximum ink coverage as a percentage (1 - 100). Any source tone darker
        than ``255 * (1 - max_fill / 100)`` is treated as black, as in Sketch
        Lines.
    seed : int | None
        Random seed for segment lengths and darkest-pixel sampling. None = non-
        deterministic.
    max_strokes : int | None
        Hard cap on strokes. When None a generous cap is derived from the image
        size and line density, as in Sketch Lines.
    """

    grid_angle: float = Field(default=45.0, ge=-360.0, le=360.0)
    line_density: float = Field(default=0.75, ge=0.01, le=10.0)
    min_length: float = Field(default=2.0, ge=1.0, le=1000.0)
    max_length: float = Field(default=40.0, ge=1.0, le=5000.0)
    max_fill: float = Field(default=80.0, ge=1.0, le=100.0)
    seed: int | None = None
    max_strokes: int | None = Field(default=None, ge=1)

    def model_post_init(self, __context: object) -> None:
        if self.min_length > self.max_length:
            raise ValueError("min_length must be <= max_length")


def sketch_squares(image: Image.Image, settings: SketchSquaresSettings) -> list[LineString]:
    """Generate grid-hatched strokes from an image using the Sketch Squares PFM.

    The engine is the same darkest-pixel, ray-search, erase and luminance-stop
    engine Sketch Lines uses. Only the angle provider differs: at each segment
    it applies the reference rule from ``PFMSketchSquaresBasic`` to the current
    pixel, so successive strokes follow a slowly rotating grid. Strokes are
    returned in image pixel coordinates (origin top-left), always inside the
    image, and never have zero length.

    Parameters
    ----------
    image : PIL.Image.Image
        Input image (any mode, converted to grayscale).
    settings : SketchSquaresSettings
        Algorithm configuration.

    Returns
    -------
    list[LineString]
        Strokes in image pixel coordinates.
    """
    engine_settings = SketchLinesSettings(
        line_density=settings.line_density,
        max_fill=settings.max_fill,
        min_length=settings.min_length,
        max_length=settings.max_length,
        seed=settings.seed,
        max_strokes=settings.max_strokes,
    )

    def angle_provider(_rng: random.Random, x: int, y: int, _step: int) -> float:
        return settings.grid_angle + math.degrees(
            math.sin(math.radians(x / 9.0)) + math.cos(math.radians(y / 9.0) + 26.0)
        )

    return _run_sketch_engine(
        image,
        engine_settings,
        angle_provider,
        shading_enabled=False,
        squiggle_enabled=False,
        shading_threshold=0.5,
    )


__all__ = ["SketchSquaresSettings", "sketch_squares"]
