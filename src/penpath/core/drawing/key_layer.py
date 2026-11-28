"""Black key layer: edge strokes drawn on top of the colour layers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from shapely import LineString

from penpath.core.drawing.outline import outline_strokes
from penpath.core.styles import STYLE_PRESETS

if TYPE_CHECKING:
    from PIL import Image


def key_layer_strokes(image: Image.Image) -> list[LineString]:
    """Trace the image's contours for a final black key layer.

    The pass reuses the already-tuned edge settings of the ``outline`` saved
    look, so the key layer follows the same contour quality as
    ``penpath convert --style outline`` with no extra tuning. Strokes come back
    in image pixel coordinates with the origin at the top-left. The tracer uses
    no randomness, so the same image always gives the same strokes in the same
    order.

    Parameters
    ----------
    image : PIL.Image.Image
        Working image in any mode (converted to greyscale for edge detection).

    Returns
    -------
    list[LineString]
        Contour strokes in image pixel coordinates. A blank or edgeless image
        returns an empty list.

    Raises
    ------
    ValueError
        If the ``outline`` saved look has no edge settings.
    """
    settings = STYLE_PRESETS["outline"].outline
    if settings is None:
        raise ValueError("The outline saved look has no edge settings")
    return outline_strokes(image, settings)


__all__ = ["key_layer_strokes"]
