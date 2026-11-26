"""Shared palette resolution for penpath CLI commands."""

from __future__ import annotations

import click
from pydantic import ValidationError

from penpath.core.models import Palette, Pen
from penpath.presets.palettes import get_palette, list_palettes


def resolve_palette(palette_spec: str) -> Palette:
    """Resolve a built-in palette name or an inline 'name=width,#hex;...' list."""
    if palette_spec in list_palettes():
        return get_palette(palette_spec)

    pens: list[Pen] = []
    for index, entry in enumerate(palette_spec.split(";"), start=1):
        if "=" not in entry:
            raise click.BadParameter(
                f"Invalid palette pen {index}: '{entry}'. Use NAME=WIDTH,#HEX",
                param_hint="palette",
            )
        name, value = entry.split("=", 1)
        parts = value.split(",")
        if len(parts) != 2:
            raise click.BadParameter(
                f"Invalid palette pen {index}: '{entry}'. Use NAME=WIDTH,#HEX",
                param_hint="palette",
            )
        try:
            pens.append(
                Pen(
                    name=name.strip(),
                    width_mm=float(parts[0].strip()),
                    color=parts[1].strip(),
                )
            )
        except (ValidationError, ValueError) as e:
            raise click.BadParameter(
                f"Invalid palette pen {index}: '{entry}'. {e}",
                param_hint="palette",
            ) from e

    return Palette(name="inline", pens=pens)


__all__ = ["resolve_palette"]
