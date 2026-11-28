"""Split an image's darkness into a fixed number of equalised tone levels.

Every drawing algorithm can only draw a few distinct tones (Hatch has one
band per angle, cross-hatching has paper, one family, two families, ...).
Equalising the image into exactly that many levels spreads its pixels evenly
over the tones the algorithm can draw: the thresholds are the image's own
darkness quantiles, so each level gets about the same share of the inked
pixels, whatever the photo's exposure or contrast.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray

if TYPE_CHECKING:
    from PIL import Image

_PAPER = 1.0 / 255.0


def equalized_thresholds(darkness: NDArray[np.float64], levels: int) -> tuple[float, ...]:
    """Darkness thresholds that split the inked pixels into ``levels`` equal shares.

    Pixels whose darkness is at most 1/255 (paper white) are ignored when the
    quantiles are measured, so a large white margin does not push every
    threshold down. Threshold ``k`` (1-based) is the ``k / levels`` quantile
    of the inked darkness; level 0 (below the first threshold) also holds the
    paper. Thresholds are strictly increasing; ties from a flat image are
    nudged apart by 1e-6.

    Parameters
    ----------
    darkness : numpy.ndarray
        Darkness map ``1 - L/255``, values 0 - 1.
    levels : int
        Number of tone levels (>= 2).

    Returns
    -------
    tuple[float, ...]
        ``levels - 1`` increasing thresholds; evenly spaced ones when the
        image has no ink.

    Raises
    ------
    ValueError
        If ``levels`` is below 2.
    """
    if levels < 2:
        raise ValueError("levels must be at least 2")
    inked = darkness[darkness > _PAPER]
    if inked.size == 0:
        return tuple(k / levels for k in range(1, levels))
    quantiles = np.quantile(inked, [k / levels for k in range(1, levels)])
    thresholds: list[float] = []
    for value in quantiles.tolist():
        if thresholds and value <= thresholds[-1]:
            value = thresholds[-1] + 1e-6
        thresholds.append(float(value))
    return tuple(thresholds)


def quantize_levels(
    darkness: NDArray[np.float64], thresholds: tuple[float, ...]
) -> NDArray[np.int64]:
    """Level index (0 = lightest) of every pixel for the given thresholds."""
    return np.digitize(darkness, np.asarray(thresholds, dtype=np.float64)).astype(np.int64)


def equalize_to_targets(
    darkness: NDArray[np.float64], targets: tuple[float, ...]
) -> NDArray[np.float64]:
    """Remap darkness so the image's own quantiles land on ``targets``.

    ``targets`` are the darkness values at which a drawing algorithm moves
    to its next tone step (strictly increasing, inside (0, 1)). With
    ``n = len(targets) + 1`` steps, the ``k / n`` quantile of the inked
    pixels (darkness above 1/255) is mapped to ``targets[k - 1]``, with
    paper staying 0 and full black staying 1, linearly in between. Each tone
    step of the algorithm then gets about the same share of the inked pixels.

    Parameters
    ----------
    darkness : numpy.ndarray
        Darkness map ``1 - L/255``, values 0 - 1.
    targets : tuple[float, ...]
        Increasing darkness thresholds of the algorithm's tone steps.

    Returns
    -------
    numpy.ndarray
        The remapped darkness map, values 0 - 1.
    """
    if not targets:
        return darkness.copy()
    sources = equalized_thresholds(darkness, len(targets) + 1)
    xs = [0.0, *sources, 1.0]
    ys = [0.0, *(min(max(t, 1e-6), 1.0 - 1e-6) for t in targets), 1.0]
    for index in range(1, len(xs)):
        if xs[index] <= xs[index - 1]:
            xs[index] = xs[index - 1] + 1e-9
    return np.clip(np.interp(darkness, xs, ys), 0.0, 1.0)


def apply_tone_levels(image: Image.Image, targets: tuple[float, ...]) -> Image.Image:
    """Return a greyscale copy of ``image`` equalised onto ``targets``.

    See :func:`equalize_to_targets`. The result is mode ``L``.
    """
    from PIL import Image as PILImage

    gray = image.convert("L") if image.mode != "L" else image
    darkness = 1.0 - np.asarray(gray, dtype=np.float64) / 255.0
    mapped = equalize_to_targets(darkness, targets)
    return PILImage.fromarray(np.rint((1.0 - mapped) * 255.0).astype(np.uint8))


def uniform_targets(levels: int) -> tuple[float, ...]:
    """Evenly spaced targets ``k / levels``: plain histogram equalisation."""
    if levels < 2:
        raise ValueError("levels must be at least 2")
    return tuple(k / levels for k in range(1, levels))


__all__ = [
    "apply_tone_levels",
    "equalize_to_targets",
    "equalized_thresholds",
    "quantize_levels",
    "uniform_targets",
]
