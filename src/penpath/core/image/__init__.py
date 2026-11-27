"""Image loading and filtering for penpath."""

from penpath.core.image.background import (
    DEFAULT_BACKGROUND_THRESHOLD,
    BackgroundResult,
    background_mask,
    detect_paper_color,
    mask_background,
    remove_background,
)
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
from penpath.core.image.saturation import adapt_saturation, boost_saturation
from penpath.core.image.separate import (
    PaletteMatch,
    PalettePenShare,
    palette_match,
    separate_palette,
)

__all__ = [
    "DEFAULT_BACKGROUND_THRESHOLD",
    "MAX_WORKING_LONGEST_PX",
    "MIN_WORKING_LONGEST_PX",
    "BackgroundResult",
    "DitherMethod",
    "FilterPipeline",
    "FilterStep",
    "GrayscaleMethod",
    "ImageLoadError",
    "PaletteMatch",
    "PalettePenShare",
    "UnsupportedFormatError",
    "WorkingResolution",
    "adapt_saturation",
    "apply_working_resolution",
    "auto_equalize",
    "background_mask",
    "boost_saturation",
    "box_blur",
    "brightness",
    "contrast",
    "detect_paper_color",
    "gamma",
    "gaussian_blur",
    "get_filter",
    "grayscale",
    "invert",
    "list_filters",
    "load_image",
    "mask_background",
    "palette_match",
    "plan_working_resolution",
    "posterize",
    "remove_background",
    "separate_palette",
    "threshold",
]
