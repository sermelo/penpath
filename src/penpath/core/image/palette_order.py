"""Order palette pens for drawing by the lightness of their ink.

The palette a user supplies decides which pen inks each pixel; it does not
decide in which order those pens visit the paper. Light ink is laid down first
and dark ink over it, so a dark pen is never overwritten by a light one. A pen
whose sRGB relative luminance is at most ``0.02`` counts as near-black and
always draws last, whatever order the palette gave it.
"""

from __future__ import annotations

from PIL import ImageColor

from penpath.core.models import Pen

_NEAR_BLACK_LUMINANCE = 0.02


def _relative_luminance(color: str) -> float:
    """Return the WCAG relative luminance of a CSS colour, in [0, 1]."""
    try:
        rgb = ImageColor.getrgb(color)
    except ValueError as exc:
        raise ValueError(f"Cannot parse pen colour {color!r}") from exc
    linear: list[float] = []
    for channel in rgb[:3]:
        value = channel / 255.0
        linear.append(value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4)
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def is_near_black_pen(pen: Pen) -> bool:
    """Return whether a pen's ink counts as near-black for drawing order.

    Parameters
    ----------
    pen : Pen
        Pen whose colour is tested.

    Returns
    -------
    bool
        True when the pen's sRGB relative luminance is at most 0.02.

    Raises
    ------
    ValueError
        If the pen colour cannot be parsed as a CSS colour.
    """
    return _relative_luminance(pen.color) <= _NEAR_BLACK_LUMINANCE


def order_pens_for_drawing(pens: list[Pen]) -> list[Pen]:
    """Order pens from light to dark ink, with near-black pens last.

    Parameters
    ----------
    pens : list[Pen]
        Pens in palette order. The list is not modified.

    Returns
    -------
    list[Pen]
        The same pens in drawing order. Pens of equal luminance keep their
        input order, as do several near-black pens.

    Raises
    ------
    ValueError
        If a pen colour cannot be parsed as a CSS colour.
    """
    luminances = [(pen, _relative_luminance(pen.color)) for pen in pens]
    drawing = sorted(
        ((pen, value) for pen, value in luminances if value > _NEAR_BLACK_LUMINANCE),
        key=lambda item: -item[1],
    )
    near_black = [(pen, value) for pen, value in luminances if value <= _NEAR_BLACK_LUMINANCE]
    return [pen for pen, _ in drawing] + [pen for pen, _ in near_black]


__all__ = ["is_near_black_pen", "order_pens_for_drawing"]
