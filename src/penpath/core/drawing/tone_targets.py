"""Tone steps of each drawing algorithm, for equalising images onto them.

:func:`pfm_tone_targets` returns the darkness values (``1 - L/255``) at which
an algorithm moves to its next tone step. Equalising an image onto these
targets (:func:`penpath.core.image.tone_levels.equalize_to_targets`) gives
every step about the same share of the image's inked pixels, so a dark or a
washed-out photo still uses every tone the algorithm can draw.

Algorithms with discrete steps report them: Hatch its band thresholds, Patch
Hatch its layer thresholds (from pen width and spacing), Engraving the
darkness at which each extra stroke joins a line, Contour its trace levels.
Continuous algorithms (Sketch Lines, Sketch Squares, Stipple, Spiral, TSP,
Squiggle) get ``CONTINUOUS_LEVELS`` even steps, i.e. plain histogram
equalisation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from penpath.core.drawing.pfm_contour import ContourSettings, _contour_levels
from penpath.core.drawing.pfm_engraving import EngravingSettings
from penpath.core.drawing.pfm_hatch import HatchSettings
from penpath.core.drawing.pfm_patch_hatch import PatchHatchSettings, layer_thresholds
from penpath.core.image.tone_levels import uniform_targets

if TYPE_CHECKING:
    from pydantic import BaseModel

CONTINUOUS_LEVELS = 8
"""Even steps used for algorithms whose tone is continuous."""


def _increasing(values: list[float]) -> tuple[float, ...]:
    """Sorted, de-duplicated values strictly inside (0, 1)."""
    return tuple(sorted({min(max(v, 1e-4), 1.0 - 1e-4) for v in values}))


def pfm_tone_targets(settings: BaseModel, pen_width_mm: float) -> tuple[float, ...]:
    """Darkness values at which the algorithm for ``settings`` changes tone step.

    Parameters
    ----------
    settings : pydantic.BaseModel
        A PFM settings model (``HatchSettings``, ``SketchLinesSettings``, ...).
    pen_width_mm : float
        Pen tip width in millimetres; Patch Hatch and Engraving steps depend
        on it.

    Returns
    -------
    tuple[float, ...]
        Strictly increasing darkness thresholds inside (0, 1).
    """
    if isinstance(settings, HatchSettings):
        return _increasing(list(settings.thresholds))
    if isinstance(settings, PatchHatchSettings):
        if settings.thresholds is not None:
            return _increasing(list(settings.thresholds))
        spacing = max(settings.spacing, pen_width_mm)
        return _increasing(
            list(layer_thresholds(len(settings.layer_angles), spacing, pen_width_mm))
        )
    if isinstance(settings, EngravingSettings):
        strokes = max(1, round(settings.line_spacing / pen_width_mm))
        capacity = strokes * settings.max_width
        span = 1.0 - settings.min_tone
        values = []
        for rank in range(strokes):
            level = (rank + 1) / capacity if capacity > 0 else 2.0
            if level <= 1.0:
                values.append(settings.min_tone + span * level ** (1.0 / settings.tone_gamma))
        return _increasing(values) or uniform_targets(CONTINUOUS_LEVELS)
    if isinstance(settings, ContourSettings):
        return _increasing([1.0 - level / 255.0 for level in _contour_levels(settings)])
    return uniform_targets(CONTINUOUS_LEVELS)


__all__ = ["CONTINUOUS_LEVELS", "pfm_tone_targets"]
