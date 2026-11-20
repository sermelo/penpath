"""Core Pydantic models for penpath."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field, field_validator

from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings

if TYPE_CHECKING:
    from penpath.core.image.pipeline import FilterPipeline


class Pen(BaseModel):
    """Pen configuration for plotting.

    Attributes
    ----------
    name : str
        Unique identifier for the pen.
    width_mm : float
        Pen tip width in millimetres.
    color : str
        Pen color as hex string (e.g., "#000000") or named CSS color.
    opacity : float
        Pen opacity (0.0 - 1.0).
    pen_type : Literal["ballpoint", "fountain", "brush", "marker", "rollerball", "gel"]
        Physical pen type for reference.
    """

    name: str = Field(..., min_length=1)
    width_mm: float = Field(..., gt=0.0, le=10.0)
    color: str = Field(default="#000000")
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    pen_type: Literal["ballpoint", "fountain", "brush", "marker", "rollerball", "gel"] = Field(
        default="rollerball"
    )

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: str) -> str:
        """Validate color format (hex or named)."""
        v = v.strip()
        if v.startswith("#"):
            if len(v) not in (4, 7, 9):
                raise ValueError(
                    "Hex color must be 3, 6, or 8 digits (e.g., #RGB, #RRGGBB, #RRGGBBAA)"
                )
            try:
                int(v[1:], 16)
            except ValueError:
                raise ValueError("Invalid hex color format") from None
        return v

    def to_vpype_layer_name(self) -> str:
        """Generate a vpype-compatible layer name."""
        return f"pen-{self.name}"


class Paper(BaseModel):
    """Paper configuration for plotting.

    Attributes
    ----------
    name : str
        Unique identifier for the paper.
    width_mm : float
        Paper width in millimetres.
    height_mm : float
        Paper height in millimetres.
    margin_mm : float
        Margin around the drawable area in millimetres.
    background_color : str
        Paper background color as hex string or named CSS color.
    """

    name: str = Field(..., min_length=1)
    width_mm: float = Field(..., gt=0.0, le=2000.0)
    height_mm: float = Field(..., gt=0.0, le=2000.0)
    margin_mm: float = Field(default=10.0, ge=0.0, le=100.0)
    background_color: str = Field(default="#FFFFFF")

    @field_validator("background_color")
    @classmethod
    def validate_background_color(cls, v: str) -> str:
        """Validate background color format."""
        v = v.strip()
        if v.startswith("#"):
            if len(v) not in (4, 7, 9):
                raise ValueError("Hex color must be 3, 6, or 8 digits")
            try:
                int(v[1:], 16)
            except ValueError:
                raise ValueError("Invalid hex color format") from None
        return v

    @property
    def drawable_width_mm(self) -> float:
        """Width of the drawable area in millimetres."""
        return self.width_mm - 2 * self.margin_mm

    @property
    def drawable_height_mm(self) -> float:
        """Height of the drawable area in millimetres."""
        return self.height_mm - 2 * self.margin_mm

    def to_vpype_page_size(self) -> str:
        """Generate vpype page size string (e.g., '210x297mm')."""
        return f"{self.width_mm}x{self.height_mm}mm"


class ImageRef(BaseModel):
    """Reference to an input image with processing settings.

    Attributes
    ----------
    path : Path
        Path to the image file.
    filters : FilterPipeline
        Filter pipeline to apply to the image.
    dpi : int
        Target DPI for the image when converting to plot coordinates.
    """

    path: Path
    filters: FilterPipeline
    dpi: int = Field(default=300, ge=72, le=2400)

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: Path) -> Path:
        """Validate that the path exists and is a file."""
        if not v.exists():
            raise ValueError(f"Image file not found: {v}")
        if not v.is_file():
            raise ValueError(f"Path is not a file: {v}")
        return v


class PFMSettings(BaseModel):
    """Base settings for a Pen Follower Module (PFM)."""

    pfm_type: str = Field(..., min_length=1)

    def get_settings_model(self) -> type[BaseModel]:
        """Get the Pydantic model class for this PFM's settings."""
        from penpath.core.drawing.registry import get_pfm

        _, settings_model = get_pfm(self.pfm_type)
        return settings_model

    def to_typed_settings(self) -> BaseModel:
        """Convert to the specific PFM settings model."""
        model_class = self.get_settings_model()
        data = self.model_dump(exclude={"pfm_type"})
        return model_class(**data)


class SketchLinesPFM(PFMSettings):
    """Sketch Lines PFM settings."""

    pfm_type: Literal["sketch_lines"] = "sketch_lines"
    settings: SketchLinesSettings = Field(default_factory=SketchLinesSettings)


class Project(BaseModel):
    """Complete project configuration for penpath.

    Attributes
    ----------
    image : ImageRef
        Input image reference with filters and DPI.
    paper : Paper
        Paper configuration.
    pen : Pen
        Pen configuration.
    pfm : PFMSettings
        Pen Follower Module settings.
    output_path : Path
        Output SVG file path.
    """

    image: ImageRef
    paper: Paper
    pen: Pen
    pfm: PFMSettings
    output_path: Path

    @field_validator("output_path")
    @classmethod
    def validate_output_path(cls, v: Path) -> Path:
        """Ensure output path has .svg extension."""
        if v.suffix.lower() != ".svg":
            raise ValueError("Output path must have .svg extension")
        return v

    def model_dump_for_vpype(self) -> dict[str, Any]:
        """Dump project as a dict suitable for vpype pipeline construction."""
        return {
            "page_size": self.paper.to_vpype_page_size(),
            "layer_name": self.pen.to_vpype_layer_name(),
            "pen_width_mm": self.pen.width_mm,
            "pen_color": self.pen.color,
            "pen_opacity": self.pen.opacity,
        }


__all__ = [
    "ImageRef",
    "PFMSettings",
    "Paper",
    "Pen",
    "Project",
    "SketchLinesPFM",
]
