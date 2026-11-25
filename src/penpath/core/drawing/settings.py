"""Scale PFM settings that are expressed in image pixels."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, cast

from annotated_types import Ge, Gt, Le, Lt
from pydantic.fields import FieldInfo

from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings

if TYPE_CHECKING:
    from pydantic import BaseModel

PIXEL_SETTING_FIELDS: tuple[str, ...] = ("min_length", "max_length", "sample_step")


def _check_pixel_fields(model: type[BaseModel]) -> None:
    """Fail loudly when the settings model no longer has the expected fields."""
    missing = [name for name in PIXEL_SETTING_FIELDS if name not in model.model_fields]
    if missing:
        raise RuntimeError(
            "Sketch Lines pixel settings missing from the settings model: "
            f"{', '.join(missing)}. Update scale_pixel_settings before drawing."
        )


def _clamp_to_bounds(value: float, field: FieldInfo) -> float:
    """Clamp a value using the numeric constraints on a settings field."""
    is_int = field.annotation is int
    for constraint in field.metadata:
        if isinstance(constraint, Ge):
            value = max(value, cast(float, constraint.ge))
        elif isinstance(constraint, Gt):
            lower = cast(float, constraint.gt)
            value = max(value, lower + 1 if is_int else math.nextafter(lower, math.inf))
        elif isinstance(constraint, Le):
            value = min(value, cast(float, constraint.le))
        elif isinstance(constraint, Lt):
            upper = cast(float, constraint.lt)
            value = min(value, upper - 1 if is_int else math.nextafter(upper, -math.inf))
    return value


def scale_pixel_settings(settings: SketchLinesSettings, factor: float) -> SketchLinesSettings:
    """Scale image-pixel settings by the same factor as the image.

    When an image is downscaled, lengths and tile sizes measured in pixels
    must shrink with it or the drawing changes in a visible way. Only the
    pixel-valued fields are touched; every other setting keeps its value.
    Each scaled value is clamped to the range the settings model allows.

    Parameters
    ----------
    settings : SketchLinesSettings
        Settings to scale. A new model is returned; this one is not mutated.
    factor : float
        Scale factor applied to the image, for example ``0.116``. Must be
        positive. ``1.0`` leaves the settings unchanged.

    Returns
    -------
    SketchLinesSettings
        Settings with the pixel-valued fields scaled and clamped.

    Raises
    ------
    ValueError
        If ``factor`` is not positive.
    RuntimeError
        If an expected pixel-valued field is missing from the settings model.
    """
    if factor <= 0:
        raise ValueError("Scale factor must be positive")

    model = type(settings)
    _check_pixel_fields(model)

    updates: dict[str, float] = {}
    for name in PIXEL_SETTING_FIELDS:
        field = model.model_fields[name]
        current = getattr(settings, name)
        updates[name] = _clamp_to_bounds(current * factor, field)

    return model.model_validate({**settings.model_dump(), **updates})


__all__ = ["PIXEL_SETTING_FIELDS", "scale_pixel_settings"]
