"""Core Pydantic models for penpath."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from pydantic import BaseModel, Field, SerializeAsAny, field_validator, model_validator

from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings
from penpath.core.drawing.pfm_sketch_squares import SketchSquaresSettings
from penpath.core.image.background import DEFAULT_BACKGROUND_THRESHOLD
from penpath.core.styles import StyleName

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
    pen_type : Literal["ballpoint", "fineliner", "fountain", "brush", "marker", "rollerball", "gel"]
        Physical pen type for reference. The accepted types are ballpoint, fineliner,
        fountain, brush, marker, rollerball and gel.
    """

    name: str = Field(..., min_length=1)
    width_mm: float = Field(..., gt=0.0, le=10.0)
    color: str = Field(default="#000000")
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    pen_type: Literal[
        "ballpoint", "fineliner", "fountain", "brush", "marker", "rollerball", "gel"
    ] = Field(default="rollerball")

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


class Palette(BaseModel):
    """An ordered list of pens; the order is the drawing order.

    Attributes
    ----------
    name : str
        Name of the palette, for example ``stabilo_88``.
    pens : list[Pen]
        Pens in drawing order. ``Pen.name`` is the label written for that pen.
    """

    name: str = Field(..., min_length=1)
    pens: list[Pen] = Field(..., min_length=1)


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
    dpi : int
        Output DPI for coordinate system (pixels per inch).
    """

    name: str = Field(..., min_length=1)
    width_mm: float = Field(..., gt=0.0, le=2000.0)
    height_mm: float = Field(..., gt=0.0, le=2000.0)
    margin_mm: float = Field(default=10.0, ge=0.0, le=100.0)
    background_color: str = Field(default="#FFFFFF")
    dpi: int = Field(default=300, ge=72, le=2400)

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
    auto_equalize : bool
        Stretch the working image's luminance range to 0-255 once, before
        palette separation. True by default; old project files load as true.
    background : bool | None
        Mask paper-level pixels before palette separation. ``None`` follows
        the mode: on for a palette, off for a single pen, so old project files
        keep today's single-pen output.
    background_threshold : float
        Maximum CIE Lab distance from the detected paper colour treated as no
        ink. Documented default 10.0; old project files load with it.
    background_method : {'global', 'local'}
        How paper is found: ``local`` follows a smooth per-pixel paper field so
        lighting gradients and shadows stay no-ink; ``global`` uses one detected
        colour, reproducing the original mask. Defaults to ``local``, so older
        project files without the key load with the new behaviour.
    saturation : float
        CIE Lab chroma multiplier applied to the working image before palette
        separation. 1.0 (the default) is off; old project files load as 1.0.
    palette_adapt : bool
        Choose the multiplier automatically from the image and the palette.
        False by default; an explicit ``saturation`` takes precedence.
    """

    path: Path
    filters: FilterPipeline
    dpi: int = Field(default=300, ge=72, le=2400)
    auto_equalize: bool = True
    background: bool | None = None
    background_threshold: float = Field(
        default=DEFAULT_BACKGROUND_THRESHOLD, ge=0.0, allow_inf_nan=False
    )
    background_method: Literal["global", "local"] = "local"
    saturation: float = Field(default=1.0, ge=0.0, le=3.0, allow_inf_nan=False)
    palette_adapt: bool = False

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
        """Convert to the specific PFM settings model.

        PFMs such as ``SketchLinesPFM`` keep their algorithm settings in a
        nested ``settings`` field. Use that payload when present so the
        settings the user gave reach the algorithm; flat PFM layouts pass
        their dumped fields straight through.
        """
        model_class = self.get_settings_model()
        nested = getattr(self, "settings", None)
        if isinstance(nested, model_class):
            return nested
        data = self.model_dump(exclude={"pfm_type"})
        nested = data.get("settings")
        if isinstance(nested, dict):
            return model_class(**nested)
        return model_class(**data)


class SketchLinesPFM(PFMSettings):
    """Sketch Lines PFM settings."""

    pfm_type: Literal["sketch_lines"] = "sketch_lines"
    settings: SketchLinesSettings = Field(default_factory=SketchLinesSettings)


class SketchSquaresPFM(PFMSettings):
    """Sketch Squares PFM settings."""

    pfm_type: Literal["sketch_squares"] = "sketch_squares"
    settings: SketchSquaresSettings = Field(default_factory=SketchSquaresSettings)


class _EmptyPFMSettings(BaseModel):
    pass


class RegisteredPFM(PFMSettings):
    """PFM wrapper whose settings validate against the registered PFM model."""

    pfm_type: str = Field(..., min_length=1)
    settings: SerializeAsAny[BaseModel] = Field(default_factory=_EmptyPFMSettings)

    @model_validator(mode="before")
    @classmethod
    def validate_registered_settings(cls, data: object) -> object:
        """Validate the nested settings with this PFM's registered model."""
        if not isinstance(data, dict):
            return data
        pfm_type = data.get("pfm_type")
        if not isinstance(pfm_type, str):
            return data

        from penpath.core.drawing.registry import get_pfm

        try:
            _, settings_model = get_pfm(pfm_type)
        except KeyError as e:
            raise ValueError(f"Unknown PFM: {pfm_type}") from e
        raw_settings = data.get("settings", {})
        if isinstance(raw_settings, BaseModel):
            raw_settings = raw_settings.model_dump()
        validated = dict(data)
        validated["settings"] = settings_model.model_validate(raw_settings)
        return validated


_PFM_WRAPPERS: dict[str, type[PFMSettings]] = {
    "sketch_lines": SketchLinesPFM,
    "sketch_squares": SketchSquaresPFM,
}


def make_pfm_settings(pfm_type: str, settings: BaseModel) -> PFMSettingsUnion:
    """Build the typed project PFM wrapper for a registered PFM and its settings."""
    from penpath.core.drawing.registry import get_pfm

    _, settings_model = get_pfm(pfm_type)
    validated = (
        settings
        if isinstance(settings, settings_model)
        else settings_model.model_validate(settings.model_dump())
    )
    wrapper_cls = _PFM_WRAPPERS.get(pfm_type, RegisteredPFM)
    wrapper = wrapper_cls.model_validate({"pfm_type": pfm_type, "settings": validated})
    return cast("PFMSettingsUnion", wrapper)


PFMSettingsUnion = SketchLinesPFM | SketchSquaresPFM | RegisteredPFM


class Project(BaseModel):
    """Complete project configuration for penpath.

    Attributes
    ----------
    image : ImageRef
        Input image reference with filters and DPI.
    paper : Paper
        Paper configuration.
    pen : Pen | None
        Single pen for old-style projects; mutually exclusive with ``pens``.
    pens : list[Pen]
        Pens in drawing order; mutually exclusive with ``pen``.
    palette_name : str | None
        Name of the built-in palette ``pens`` came from, when there is one.
        Excluded from dumps; the project file writes it as ``palette:``.
    pfm : PFMSettingsUnion
        Pen Follower Module settings (discriminated union). The saved look's
        values are resolved into these settings; explicit CLI overrides win.
    style : StyleName | None
        Saved look that selected the settings, if any. ``outline`` also runs
        the edge pass; ``None`` keeps the default path.
    output_path : Path
        Output SVG file path.
    """

    image: ImageRef
    paper: Paper
    pen: Pen | None = None
    pens: list[Pen] = Field(default_factory=list)
    palette_name: str | None = Field(default=None, exclude=True)
    pfm: PFMSettingsUnion
    style: StyleName | None = None
    output_path: Path

    @field_validator("output_path")
    @classmethod
    def validate_output_path(cls, v: Path) -> Path:
        """Ensure output path has .svg extension."""
        if v.suffix.lower() != ".svg":
            raise ValueError("Output path must have .svg extension")
        return v

    @model_validator(mode="after")
    def validate_pen_selection(self) -> Project:
        """Require exactly one of a single pen or an ordered pen list."""
        if self.pen is not None and self.pens:
            raise ValueError("Project cannot set both 'pen' and 'pens': use one")
        if self.pen is None and not self.pens:
            raise ValueError("Project requires either 'pen' or 'pens'")
        return self

    @property
    def palette(self) -> list[Pen]:
        """Effective pens in drawing order, falling back to the single pen."""
        if self.pens:
            return list(self.pens)
        if self.pen is None:
            raise ValueError("Project has no pens")
        return [self.pen]

    def model_dump_for_vpype(self) -> dict[str, Any]:
        """Dump project as a dict suitable for vpype pipeline construction."""
        pen = self.palette[0]
        return {
            "page_size": self.paper.to_vpype_page_size(),
            "layer_name": pen.to_vpype_layer_name(),
            "pen_width_mm": pen.width_mm,
            "pen_color": pen.color,
            "pen_opacity": pen.opacity,
        }


__all__ = [
    "ImageRef",
    "PFMSettings",
    "PFMSettingsUnion",
    "Palette",
    "Paper",
    "Pen",
    "Project",
    "RegisteredPFM",
    "SketchLinesPFM",
    "SketchSquaresPFM",
    "make_pfm_settings",
]
