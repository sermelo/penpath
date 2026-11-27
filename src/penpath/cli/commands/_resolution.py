"""Shared resolution flags and render budget for preview and evaluate."""

from __future__ import annotations

import math

import click

from penpath.core import check_render_budget, render_size_px

MM_PER_INCH = 25.4


def resolve_px_per_mm(dpi: float | None, px_per_mm: float | None, default: float) -> float:
    """Resolve the mutually exclusive resolution flags to pixels per millimetre.

    Parameters
    ----------
    dpi : float | None
        Resolution in real dots per inch, or ``None`` when not given.
    px_per_mm : float | None
        Resolution in pixels per millimetre, or ``None`` when not given.
    default : float
        Pixels per millimetre to use when neither flag is given.

    Returns
    -------
    float
        The resolution in pixels per millimetre.

    Raises
    ------
    click.UsageError
        If both flags are given.
    click.BadParameter
        If a given value is not finite and greater than zero.
    """
    if dpi is not None and px_per_mm is not None:
        raise click.UsageError("--dpi and --px-per-mm are mutually exclusive; pass only one.")
    for value, flag in ((dpi, "--dpi"), (px_per_mm, "--px-per-mm")):
        if value is not None and (not math.isfinite(value) or value <= 0):
            raise click.BadParameter("must be a finite number greater than zero", param_hint=flag)
    if dpi is not None:
        return dpi / MM_PER_INCH
    if px_per_mm is not None:
        return px_per_mm
    return default


def enforce_render_budget(
    width_mm: float, height_mm: float, px_per_mm: float, *, force: bool
) -> None:
    """Refuse an oversized raster before the caller allocates it.

    Parameters
    ----------
    width_mm : float
        Paper or canvas width in millimetres.
    height_mm : float
        Paper or canvas height in millimetres.
    px_per_mm : float
        Resolved rasterisation resolution in pixels per millimetre.
    force : bool
        When true, skip the budget check. Value checks happen before this call.

    Raises
    ------
    click.ClickException
        If the raster exceeds the core 40 MP budget and ``force`` is false.
    """
    if force:
        return
    width_px, height_px = render_size_px(width_mm, height_mm, px_per_mm)
    try:
        check_render_budget(width_px, height_px)
    except ValueError as exc:
        raise click.ClickException(
            f"Render too large: {exc}. Lower --px-per-mm (or --dpi) or pass --force."
        ) from exc


__all__ = ["MM_PER_INCH", "enforce_render_budget", "resolve_px_per_mm"]
