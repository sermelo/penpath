"""Shared palette resolution for penpath CLI commands."""

from __future__ import annotations

import click

from penpath.core.models import Palette
from penpath.core.resolve import ResolutionError
from penpath.core.resolve import resolve_palette as _resolve_palette_core


def resolve_palette(palette_spec: str) -> Palette:
    """Resolve a built-in palette name or an inline ``name=width,#hex;...`` list."""
    try:
        return _resolve_palette_core(palette_spec)
    except ResolutionError as e:
        raise click.BadParameter(e.message, param_hint=e.param_hint) from e


__all__ = ["resolve_palette"]
