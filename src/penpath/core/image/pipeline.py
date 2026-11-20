"""Filter pipeline for composing and applying image filters in sequence."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from penpath.core.image.filters import (
    box_blur,
    brightness,
    contrast,
    gamma,
    gaussian_blur,
    grayscale,
    invert,
    posterize,
    threshold,
)


class FilterStep(BaseModel):
    """A single filter step in the pipeline."""

    model_config = ConfigDict(extra="forbid")

    name: str
    kwargs: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


# Registry of available filters by name
_FILTER_REGISTRY: dict[str, Callable[..., Image.Image]] = {
    "grayscale": grayscale,
    "threshold": threshold,
    "posterize": posterize,
    "gaussian_blur": gaussian_blur,
    "box_blur": box_blur,
    "contrast": contrast,
    "brightness": brightness,
    "gamma": gamma,
    "invert": invert,
}


def get_filter(name: str) -> Callable[..., Image.Image]:
    """Get a filter function by name.

    Parameters
    ----------
    name : str
        Name of the filter (e.g., "grayscale", "threshold").

    Returns
    -------
    Callable
        The filter function.

    Raises
    ------
    ValueError
        If the filter name is not registered.
    """
    if name not in _FILTER_REGISTRY:
        raise ValueError(f"Unknown filter: {name}. Available: {list(_FILTER_REGISTRY.keys())}")
    return _FILTER_REGISTRY[name]


def list_filters() -> list[str]:
    """List all available filter names.

    Returns
    -------
    list[str]
        Sorted list of filter names.
    """
    return sorted(_FILTER_REGISTRY.keys())


class FilterPipeline(BaseModel):
    """Pipeline for composing and applying image filters in sequence.

    Each step in the pipeline has a filter name, keyword arguments, and an
    enabled flag. Only enabled steps are applied when `apply()` is called.

    Example
    -------
    >>> pipeline = FilterPipeline()
    >>> pipeline.add_step("grayscale", method="luminance")
    >>> pipeline.add_step("threshold", level=128, dither="floyd_steinberg")
    >>> result = pipeline.apply(image)
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    steps: list[FilterStep] = Field(default_factory=list)

    def add_step(self, filter_name: str, **kwargs: Any) -> int:
        """Add a filter step to the end of the pipeline.

        Parameters
        ----------
        filter_name : str
            Name of the filter (must be registered).
        **kwargs : Any
            Keyword arguments passed to the filter function.

        Returns
        -------
        int
            Index of the added step.

        Raises
        ------
        ValueError
            If the filter name is not registered.
        """
        # Validate filter exists
        get_filter(filter_name)
        step = FilterStep(name=filter_name, kwargs=kwargs, enabled=True)
        self.steps.append(step)
        return len(self.steps) - 1

    def remove_step(self, index: int) -> None:
        """Remove a filter step by index.

        Parameters
        ----------
        index : int
            Index of the step to remove.

        Raises
        ------
        IndexError
            If index is out of range.
        """
        if not 0 <= index < len(self.steps):
            raise IndexError(f"Step index {index} out of range (0-{len(self.steps) - 1})")
        self.steps.pop(index)

    def enable_step(self, index: int) -> None:
        """Enable a filter step by index.

        Parameters
        ----------
        index : int
            Index of the step to enable.

        Raises
        ------
        IndexError
            If index is out of range.
        """
        if not 0 <= index < len(self.steps):
            raise IndexError(f"Step index {index} out of range (0-{len(self.steps) - 1})")
        self.steps[index].enabled = True

    def disable_step(self, index: int) -> None:
        """Disable a filter step by index.

        Parameters
        ----------
        index : int
            Index of the step to disable.

        Raises
        ------
        IndexError
            If index is out of range.
        """
        if not 0 <= index < len(self.steps):
            raise IndexError(f"Step index {index} out of range (0-{len(self.steps) - 1})")
        self.steps[index].enabled = False

    def reorder(self, from_idx: int, to_idx: int) -> None:
        """Move a filter step from one position to another.

        Parameters
        ----------
        from_idx : int
            Current index of the step to move.
        to_idx : int
            Target index (step will be inserted at this position).

        Raises
        ------
        IndexError
            If either index is out of range.
        """
        if not 0 <= from_idx < len(self.steps):
            raise IndexError(f"From index {from_idx} out of range (0-{len(self.steps) - 1})")
        if not 0 <= to_idx < len(self.steps):
            raise IndexError(f"To index {to_idx} out of range (0-{len(self.steps) - 1})")

        step = self.steps.pop(from_idx)
        self.steps.insert(to_idx, step)

    def apply(self, image: Image.Image) -> Image.Image:
        """Apply all enabled filter steps to an image in order.

        Parameters
        ----------
        image : PIL.Image.Image
            Input image.

        Returns
        -------
        PIL.Image.Image
            Filtered image (always a copy, even if no steps are applied).
        """
        result = image
        applied_any = False
        for step in self.steps:
            if not step.enabled:
                continue
            filter_fn = get_filter(step.name)
            result = filter_fn(result, **step.kwargs)
            applied_any = True
        if not applied_any:
            return image.copy()
        return result

    def to_dict(self) -> dict[str, Any]:
        """Serialize the pipeline to a dictionary.

        Returns
        -------
        dict
            Dictionary representation with steps list.
        """
        return {
            "steps": [
                {
                    "name": step.name,
                    "kwargs": step.kwargs,
                    "enabled": step.enabled,
                }
                for step in self.steps
            ]
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FilterPipeline:
        """Create a pipeline from a dictionary.

        Parameters
        ----------
        data : dict
            Dictionary with "steps" key containing list of step dicts.

        Returns
        -------
        FilterPipeline
            Reconstructed pipeline.

        Raises
        ------
        ValueError
            If data format is invalid or filter names are unknown.
        """
        pipeline = cls()
        steps_data = data.get("steps", [])
        for step_data in steps_data:
            if not isinstance(step_data, dict):
                raise ValueError("Each step must be a dictionary")
            name = step_data.get("name")
            if not name:
                raise ValueError("Step missing 'name' field")
            kwargs = step_data.get("kwargs", {})
            enabled = step_data.get("enabled", True)
            # Validate filter exists
            get_filter(name)
            step = FilterStep(name=name, kwargs=kwargs, enabled=enabled)
            pipeline.steps.append(step)
        return pipeline

    def __len__(self) -> int:
        """Return the number of steps in the pipeline."""
        return len(self.steps)

    def __getitem__(self, index: int) -> FilterStep:
        """Get a step by index."""
        return self.steps[index]

    def __iter__(self) -> Any:
        """Iterate over steps."""
        return iter(self.steps)

    def __repr__(self) -> str:
        """Return a string representation of the pipeline."""
        parts = []
        for i, s in enumerate(self.steps):
            kwargs_str = ", ".join(f"{k}={v!r}" for k, v in s.kwargs.items())
            disabled_str = " [disabled]" if not s.enabled else ""
            parts.append(f"{i}: {s.name}({kwargs_str}){disabled_str}")
        steps_repr = ", ".join(parts)
        return f"FilterPipeline([{steps_repr}])"
