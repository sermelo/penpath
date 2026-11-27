"""PFM (Pen Follower Module) Registry for penpath.

Provides a registry system for PFM algorithms with their associated settings models.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from pydantic import BaseModel

from penpath.core.drawing.pfm_contour import ContourSettings, contour_strokes
from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings, sketch_lines
from penpath.core.drawing.pfm_sketch_squares import SketchSquaresSettings, sketch_squares

if TYPE_CHECKING:
    from shapely import LineString


class PFMRegistry:
    """Registry for Pen Follower Modules (PFMs).

    Each PFM is registered with a name, a callable function, and a Pydantic
    settings model class for validation.
    """

    def __init__(self) -> None:
        self._pfms: dict[str, tuple[Callable[..., list[LineString]], type[BaseModel]]] = {}

    def register(
        self,
        name: str,
        fn: Callable[..., list[LineString]],
        settings_model: type[BaseModel],
    ) -> None:
        """Register a PFM algorithm.

        Parameters
        ----------
        name : str
            Unique identifier for the PFM (e.g., "sketch_lines").
        fn : Callable
            Function that takes (image, settings) and returns list[LineString].
        settings_model : type[BaseModel]
            Pydantic model class for validating PFM settings.
        """
        if not name:
            raise ValueError("PFM name cannot be empty")
        if name in self._pfms:
            raise ValueError(f"PFM already registered: {name}")
        if not callable(fn):
            raise ValueError("PFM function must be callable")
        if not issubclass(settings_model, BaseModel):
            raise ValueError("settings_model must be a Pydantic BaseModel subclass")

        self._pfms[name] = (fn, settings_model)

    def get(self, name: str) -> tuple[Callable[..., list[LineString]], type[BaseModel]]:
        """Get a registered PFM by name.

        Parameters
        ----------
        name : str
            Name of the PFM to retrieve.

        Returns
        -------
        tuple[Callable, type[BaseModel]]
            The PFM function and its settings model class.

        Raises
        ------
        KeyError
            If the PFM is not registered.
        """
        if name not in self._pfms:
            raise KeyError(f"PFM not registered: {name}")
        return self._pfms[name]

    def list(self) -> list[str]:
        """List all registered PFM names.

        Returns
        -------
        list[str]
            Sorted list of registered PFM names.
        """
        return sorted(self._pfms.keys())

    def __contains__(self, name: str) -> bool:
        """Check if a PFM is registered."""
        return name in self._pfms

    def __len__(self) -> int:
        """Return the number of registered PFMs."""
        return len(self._pfms)


# Global registry instance
_registry = PFMRegistry()


def get_registry() -> PFMRegistry:
    """Get the global PFM registry instance."""
    return _registry


def register_pfm(
    name: str,
    fn: Callable[..., list[LineString]],
    settings_model: type[BaseModel],
) -> None:
    """Register a PFM in the global registry."""
    _registry.register(name, fn, settings_model)


def get_pfm(name: str) -> tuple[Callable[..., list[LineString]], type[BaseModel]]:
    """Get a PFM from the global registry."""
    return _registry.get(name)


def list_pfms() -> list[str]:
    """List all PFMs in the global registry."""
    return _registry.list()


register_pfm("sketch_lines", sketch_lines, SketchLinesSettings)
register_pfm("contour", contour_strokes, ContourSettings)
register_pfm("sketch_squares", sketch_squares, SketchSquaresSettings)

__all__ = [
    "PFMRegistry",
    "get_pfm",
    "get_registry",
    "list_pfms",
    "register_pfm",
]
