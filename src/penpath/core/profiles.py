"""Machine profile schema: the validated model that describes a machine.

Every machine value penpath uses lives in a profile file, never in code. This
module holds only the schema: no file reading and no built-in machine values.
"""

from __future__ import annotations

from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

PROFILE_FILE_VERSION: Final[Literal[1]] = 1

_MmPositive = Annotated[float, Field(gt=0.0)]
_MmNonNegative = Annotated[float, Field(ge=0.0)]


class _ProfileModel(BaseModel):
    """Base for profile sections: unknown keys are typos, so reject them."""

    model_config = ConfigDict(extra="forbid")


class PageProfile(_ProfileModel):
    """Where the paper sits on the machine bed."""

    placement: Literal["fixed", "reachable_corner"] = "fixed"
    origin_mm: tuple[float, float] = (0.0, 0.0)


class BedProfile(_ProfileModel):
    """Bed geometry and the area the pen can reach."""

    size_mm: tuple[_MmPositive, _MmPositive]
    pen_offset_mm: tuple[float, float] = (0.0, 0.0)
    nozzle_range_mm: tuple[tuple[float, float], tuple[float, float]] | None = None
    margin_mm: _MmNonNegative = 0.0
    page: PageProfile = Field(default_factory=PageProfile)
    invert_y: bool = True

    @model_validator(mode="after")
    def _check_nozzle_range(self) -> Self:
        if self.nozzle_range_mm is not None:
            x_range, y_range = self.nozzle_range_mm
            if x_range[0] >= x_range[1]:
                raise ValueError("bed.nozzle_range_mm X values must increase")
            if y_range[0] >= y_range[1]:
                raise ValueError("bed.nozzle_range_mm Y values must increase")
        return self


class FeedProfile(_ProfileModel):
    """Travel, drawing and Z feed rates in millimetres per second."""

    travel_mm_s: _MmPositive
    draw_mm_s: _MmPositive
    z_mm_s: _MmPositive | None = None

    @property
    def effective_z_mm_s(self) -> float:
        """Z feed, falling back to travel feed when the profile omits it."""
        return self.travel_mm_s if self.z_mm_s is None else self.z_mm_s


class PenProfile(_ProfileModel):
    """Pen heights, optional ramp and optional command-driven up/down."""

    z_up: float
    z_down: float
    z_touch: float | None = None
    z_hover: float | None = None
    ramp_mm: _MmNonNegative | None = None
    touch_xy_mm: tuple[float, float] | None = None
    up_code: str | None = None
    down_code: str | None = None

    @model_validator(mode="after")
    def _check_heights(self) -> Self:
        if self.z_down >= self.z_up:
            raise ValueError("pen.z_down must be lower than pen.z_up")
        if self.z_touch is not None and not self.z_down <= self.z_touch <= self.z_up:
            raise ValueError("pen.z_touch must be between pen.z_down and pen.z_up")
        if self.z_hover is not None and not self.z_down <= self.z_hover <= self.z_up:
            raise ValueError("pen.z_hover must be between pen.z_down and pen.z_up")
        if self.ramp_mm and (self.z_touch is None or self.z_hover is None):
            raise ValueError("pen.ramp_mm requires pen.z_touch and pen.z_hover")
        return self


class GcodeProfile(_ProfileModel):
    """Verbatim G-code blocks and the comment prefix."""

    comment_prefix: str = ";"
    start: str = ""
    end: str = ""
    layer_start: str = ""
    layer_end: str = ""


class PenChangeStep(_ProfileModel):
    """One ordered pen-change action, with an optional feed selection."""

    z: Literal["up", "down", "touch", "hover"] | float | None = None
    xy: Literal["touch"] | tuple[float, float] | None = None
    raw: str | None = None
    message: str | None = None
    pause: str | None = None
    feed: Literal["travel", "draw", "z"] | None = None

    @model_validator(mode="after")
    def _check_one_action(self) -> Self:
        actions = tuple(
            name
            for name in ("z", "xy", "raw", "message", "pause")
            if getattr(self, name) is not None
        )
        if len(actions) != 1:
            raise ValueError(
                "pen_change.steps entry needs exactly one of z, xy, raw, message or pause"
            )
        return self


class PenChangeProfile(_ProfileModel):
    """When to change pens and the ordered steps of one change."""

    mode: Literal["between", "each", "none"] = "none"
    steps: list[PenChangeStep] = Field(default_factory=list)


class MachineProfile(_ProfileModel):
    """A complete, validated machine profile.

    Parameters
    ----------
    version : int
        Profile format version, currently 1.
    name : str
        Profile name; the loader uses the YAML file name or user mapping key.
    description : str
        Human-readable description for ``penpath info profiles``.
    bed : BedProfile
        Bed size, pen offset, nozzle range, page placement and Y direction.
    feed : FeedProfile
        Travel, draw and Z feed rates.
    pen : PenProfile
        Pen up/down heights and the optional landing ramp.
    gcode : GcodeProfile
        Verbatim start/end and per-layer code blocks.
    pen_change : PenChangeProfile
        Pen-change mode and ordered steps.
    """

    version: Literal[1] = PROFILE_FILE_VERSION
    name: str = Field(..., min_length=1)
    description: str = ""
    bed: BedProfile
    feed: FeedProfile
    pen: PenProfile
    gcode: GcodeProfile = Field(default_factory=GcodeProfile)
    pen_change: PenChangeProfile = Field(default_factory=PenChangeProfile)


__all__ = [
    "PROFILE_FILE_VERSION",
    "BedProfile",
    "FeedProfile",
    "GcodeProfile",
    "MachineProfile",
    "PageProfile",
    "PenChangeProfile",
    "PenChangeStep",
    "PenProfile",
]
