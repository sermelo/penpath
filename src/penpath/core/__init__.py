"""Core penpath functionality."""

from penpath.core.geometry import (
    DEFAULT_PAPER_DPI,
    merge_lines,
    mm_to_pixels,
    pixels_to_mm,
    simplify,
    simplify_line,
)
from penpath.core.image import (
    DitherMethod,
    FilterPipeline,
    FilterStep,
    GrayscaleMethod,
    ImageLoadError,
    UnsupportedFormatError,
    box_blur,
    brightness,
    contrast,
    gamma,
    gaussian_blur,
    get_filter,
    grayscale,
    invert,
    list_filters,
    load_image,
    posterize,
    threshold,
)
from penpath.core.models import (
    ImageRef,
    Paper,
    Pen,
    PFMSettings,
    PFMSettingsUnion,
    Project,
    SketchLinesPFM,
)
from penpath.core.project import (
    PROJECT_FILE_VERSION,
    ProjectLoadError,
    ProjectSaveError,
    load_yaml,
    save_yaml,
)
from penpath.core.simulation import (
    PenStroke,
    compute_machine_cost,
    simulate_plot,
)

# Rebuild Pydantic models that have forward references
# FilterPipeline is imported above, so ImageRef can now be fully resolved
ImageRef.model_rebuild()
Project.model_rebuild()

__all__ = [
    "DEFAULT_PAPER_DPI",
    "PROJECT_FILE_VERSION",
    "DitherMethod",
    "FilterPipeline",
    "FilterStep",
    "GrayscaleMethod",
    "ImageLoadError",
    "ImageRef",
    "PFMSettings",
    "PFMSettingsUnion",
    "Paper",
    "Pen",
    "PenStroke",
    "Project",
    "ProjectLoadError",
    "ProjectSaveError",
    "SketchLinesPFM",
    "UnsupportedFormatError",
    "box_blur",
    "brightness",
    "compute_machine_cost",
    "contrast",
    "gamma",
    "gaussian_blur",
    "get_filter",
    "grayscale",
    "invert",
    "list_filters",
    "load_image",
    "load_yaml",
    "merge_lines",
    "mm_to_pixels",
    "pixels_to_mm",
    "posterize",
    "save_yaml",
    "simplify",
    "simplify_line",
    "simulate_plot",
    "threshold",
]
