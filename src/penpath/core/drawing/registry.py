"""PFM (Pen Follower Module) Registry for penpath.

Provides a registry system for PFM algorithms with their associated settings models.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from pydantic import BaseModel

from penpath.core.drawing.pfm_contour import ContourSettings, contour_strokes
from penpath.core.drawing.pfm_engraving import EngravingSettings, engraving_strokes
from penpath.core.drawing.pfm_hatch import HatchSettings, hatch_strokes
from penpath.core.drawing.pfm_patch_hatch import PatchHatchSettings, patch_hatch_strokes
from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings, sketch_lines
from penpath.core.drawing.pfm_sketch_squares import SketchSquaresSettings, sketch_squares
from penpath.core.drawing.pfm_spiral import SpiralSettings, spiral_strokes
from penpath.core.drawing.pfm_squiggle import SquiggleSettings, squiggle_strokes
from penpath.core.drawing.pfm_stipple import StippleSettings, stipple
from penpath.core.drawing.pfm_tsp import TSPSettings, tsp_strokes

if TYPE_CHECKING:
    from shapely import LineString


class PFMRegistry:
    """Registry for Pen Follower Modules (PFMs).

    Each PFM is registered with a name, a callable function, and a Pydantic
    settings model class for validation. An optional one-line description is
    kept separately so callers that only need the function and model keep
    receiving the original two-tuple from :meth:`get`.
    """

    def __init__(self) -> None:
        self._pfms: dict[str, tuple[Callable[..., list[LineString]], type[BaseModel]]] = {}
        self._descriptions: dict[str, str] = {}

    def register(
        self,
        name: str,
        fn: Callable[..., list[LineString]],
        settings_model: type[BaseModel],
        description: str | None = None,
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
        description : str | None
            Short one-line description for user-facing listings.
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
        if description is not None:
            self._descriptions[name] = description

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

    def get_description(self, name: str) -> str:
        """Get the one-line description of a registered PFM.

        Parameters
        ----------
        name : str
            Name of the PFM to describe.

        Returns
        -------
        str
            The registered description, or an empty string when the PFM was
            registered without one.

        Raises
        ------
        KeyError
            If the PFM is not registered.
        """
        if name not in self._pfms:
            raise KeyError(f"PFM not registered: {name}")
        return self._descriptions.get(name, "")

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
    description: str | None = None,
) -> None:
    """Register a PFM in the global registry, with an optional description."""
    _registry.register(name, fn, settings_model, description)


def get_pfm(name: str) -> tuple[Callable[..., list[LineString]], type[BaseModel]]:
    """Get a PFM from the global registry."""
    return _registry.get(name)


def get_pfm_description(name: str) -> str:
    """Get the one-line description of a PFM in the global registry."""
    return _registry.get_description(name)


def list_pfms() -> list[str]:
    """List all PFMs in the global registry."""
    return _registry.list()


register_pfm(
    "sketch_lines",
    sketch_lines,
    SketchLinesSettings,
    "Random-angle hatching that builds pen-and-ink tone from dark pixels",
)
register_pfm(
    "contour",
    contour_strokes,
    ContourSettings,
    "Trace clean vector outlines from thresholded greyscale levels",
)
register_pfm(
    "sketch_squares",
    sketch_squares,
    SketchSquaresSettings,
    "Structured grid hatching with a position-dependent angle field",
)
register_pfm(
    "stipple",
    stipple,
    StippleSettings,
    "Weighted Poisson-disk dots that shade by dot size and density",
)
register_pfm(
    "spiral_sawtooth",
    spiral_strokes,
    SpiralSettings,
    "Continuous spiral strokes for single-pass plots with no pen lifts",
)
register_pfm(
    "hatch",
    hatch_strokes,
    HatchSettings,
    "Evenly spaced pen hatching with per-tone thresholds and angles",
)
register_pfm(
    "patch_hatch",
    patch_hatch_strokes,
    PatchHatchSettings,
    "Hand-drawn cross-hatching in small patches that follow image edges",
)
register_pfm(
    "tsp",
    tsp_strokes,
    TSPSettings,
    "One continuous line through weighted dots using a TSP tour",
)
register_pfm(
    "squiggle",
    squiggle_strokes,
    SquiggleSettings,
    "Wavy rows that shade quickly with oscillating strokes",
)
register_pfm(
    "engraving",
    engraving_strokes,
    EngravingSettings,
    "Copper-plate line-width shading in straight, swirl or contour layouts",
)

__all__ = [
    "PFMRegistry",
    "get_pfm",
    "get_pfm_description",
    "get_registry",
    "list_pfms",
    "register_pfm",
]
