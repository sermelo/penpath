"""Image loading and filtering for penpath."""

from penpath.core.image.filters import (
    DitherMethod,
    GrayscaleMethod,
    auto_equalize,
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
from penpath.core.image.load import ImageLoadError, UnsupportedFormatError, load_image
from penpath.core.image.pipeline import (
    FilterPipeline,
    FilterStep,
    get_filter,
    list_filters,
)
from penpath.core.image.resolution import (
    MAX_WORKING_LONGEST_PX,
    MIN_WORKING_LONGEST_PX,
    WorkingResolution,
    apply_working_resolution,
    plan_working_resolution,
)
from penpath.core.image.separate import separate_palette

__all__ = [
    "MAX_WORKING_LONGEST_PX",
    "MIN_WORKING_LONGEST_PX",
    "DitherMethod",
    "FilterPipeline",
    "FilterStep",
    "GrayscaleMethod",
    "ImageLoadError",
    "UnsupportedFormatError",
    "WorkingResolution",
    "apply_working_resolution",
    "auto_equalize",
    "box_blur",
    "brightness",
    "contrast",
    "gamma",
    "gaussian_blur",
    "get_filter",
    "grayscale",
    "invert",
    "list_filters",
    "load_image",
    "plan_working_resolution",
    "posterize",
    "separate_palette",
    "threshold",
]
