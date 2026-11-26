"""Machine profiles: the validated model, the YAML loader and actionable errors.

Every machine value penpath uses lives in a profile YAML file, never in code.
Built-ins are read from ``penpath.presets.profiles`` with ``importlib.resources``;
the user file at ``$XDG_CONFIG_HOME/penpath/profiles.yaml`` (or
``~/.config/penpath/profiles.yaml``) maps names to profiles and overrides a
built-in of the same name.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Annotated, Final, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

PROFILE_FILE_VERSION: Final[Literal[1]] = 1
BUILTIN_PROFILES_PACKAGE = "penpath.presets.profiles"
USER_PROFILES_FILENAME = "profiles.yaml"

_MmPositive = Annotated[float, Field(gt=0.0)]
_MmNonNegative = Annotated[float, Field(ge=0.0)]
_MarginValue = (
    _MmNonNegative | tuple[_MmNonNegative, _MmNonNegative, _MmNonNegative, _MmNonNegative]
)


class ProfileError(Exception):
    """Base class for machine profile errors."""


class ProfileFileError(ProfileError):
    """Raised when a profile file is missing, unreadable or has the wrong shape."""


class ProfileParseError(ProfileError):
    """Raised when a profile file is not valid YAML."""


class InvalidProfileError(ProfileError):
    """Raised when a profile value does not match the profile schema."""


class UnknownProfileError(ProfileError):
    """Raised when a requested profile name is not available."""


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
    margin_mm: _MarginValue = 0.0
    """Safety margin from the drawable edge, in millimetres.

    A single non-negative number is used on all four sides. A list or tuple of
    exactly four non-negative numbers sets ``[top, right, bottom, left]``: in
    pen space ``top`` is the back (maximum Y), ``right`` the maximum X,
    ``bottom`` the front (minimum Y) and ``left`` the minimum X. The raw value
    is kept for display and serialization; use ``margins_mm`` for the normalized
    four floats in ``(top, right, bottom, left)`` order.
    """
    page: PageProfile = Field(default_factory=PageProfile)
    invert_y: bool = True

    @property
    def margins_mm(self) -> tuple[float, float, float, float]:
        """Return the four margins in ``(top, right, bottom, left)`` pen-space order."""
        if isinstance(self.margin_mm, tuple):
            return self.margin_mm
        return (self.margin_mm, self.margin_mm, self.margin_mm, self.margin_mm)

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
        if self.ramp_mm and self.z_touch is not None and self.z_touch <= self.z_down:
            raise ValueError("pen.z_touch must be above pen.z_down when pen.ramp_mm is set")
        if (
            self.ramp_mm
            and self.z_hover is not None
            and self.z_touch is not None
            and self.z_hover < self.z_touch
        ):
            raise ValueError("pen.z_hover must not be below pen.z_touch when ramping")
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


def with_margin_mm(profile: MachineProfile, margin_mm: float | Sequence[float]) -> MachineProfile:
    """Return a validated copy of ``profile`` with its bed margin overridden.

    Parameters
    ----------
    profile : MachineProfile
        Validated profile to copy; it is left unchanged.
    margin_mm : float | Sequence[float]
        One non-negative number for all four sides, or four numbers in
        ``[top, right, bottom, left]`` pen-space order.

    Returns
    -------
    MachineProfile
        The copy, revalidated so an invalid margin raises pydantic's error
        naming ``bed.margin_mm``.

    Raises
    ------
    pydantic.ValidationError
        The margin is negative, not numeric or has the wrong number of sides.
    """
    bed = profile.bed.model_dump()
    bed["margin_mm"] = margin_mm
    data = profile.model_dump()
    data["bed"] = bed
    return MachineProfile.model_validate(data)


def get_user_profiles_path() -> Path:
    """Return the user profiles file, honouring ``XDG_CONFIG_HOME``."""
    config_home = os.environ.get("XDG_CONFIG_HOME")
    if config_home:
        return Path(config_home) / "penpath" / USER_PROFILES_FILENAME
    return Path.home() / ".config" / "penpath" / USER_PROFILES_FILENAME


def _builtin_profiles() -> dict[str, Traversable]:
    """Map built-in profile names to their packaged YAML files."""
    package = resources.files(BUILTIN_PROFILES_PACKAGE)
    return {
        entry.name.removesuffix(".yaml"): entry
        for entry in package.iterdir()
        if entry.name.endswith(".yaml")
    }


def _read_yaml(source: Path | Traversable) -> object:
    """Read and parse a YAML file, with an error that names file, line and reason."""
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        reason = exc.strerror or str(exc)
        raise ProfileFileError(f"Cannot read profile file {source}: {reason}") from exc

    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        if mark is None:
            mark = getattr(exc, "context_mark", None)
        line = f" at line {mark.line + 1}" if mark is not None else ""
        reason = getattr(exc, "problem", None) or str(exc).splitlines()[0]
        raise ProfileParseError(f"Invalid YAML in {source}{line}: {reason}") from exc


def _validation_error(source: Path | Traversable, exc: ValidationError) -> str:
    """Format pydantic errors so each message names the offending key."""
    details = []
    for error in exc.errors():
        key = ".".join(str(part) for part in error["loc"]) or "profile"
        details.append(f"{key}: {error['msg']}")
    return f"Invalid profile in {source}: " + "; ".join(details)


def _load_user_profiles(path: Path) -> dict[str, object]:
    """Read the user mapping of profile names to raw profiles."""
    if not path.exists():
        return {}
    data = _read_yaml(path)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ProfileFileError(
            f"Profile file {path} must be a mapping of names to profiles, "
            "for example 'my_machine:' followed by an indented profile"
        )
    if any(key in data for key in ("bed", "feed", "pen", "gcode", "pen_change", "version")):
        raise ProfileFileError(
            f"Profile file {path} must be a mapping of names to profiles; "
            "put your profile under a name, for example 'my_machine:'"
        )
    return data


def _validate_profile(
    raw: object,
    name: str,
    source: Path | Traversable,
) -> MachineProfile:
    """Validate a raw profile, filling in its name and version when omitted."""
    if not isinstance(raw, dict):
        raise ProfileFileError(f"Profile {name!r} in {source} must be a YAML mapping")

    data = dict(raw)
    if "name" in data and data["name"] != name:
        raise InvalidProfileError(
            f"Invalid profile in {source}: name: expected {name!r}, got {data['name']!r}"
        )
    data.setdefault("name", name)
    data.setdefault("version", PROFILE_FILE_VERSION)

    try:
        return MachineProfile.model_validate(data)
    except ValidationError as exc:
        raise InvalidProfileError(_validation_error(source, exc)) from exc


def list_profiles(profiles_path: Path | None = None) -> list[str]:
    """Return the sorted names of all available built-in and user profiles.

    A user profile with a built-in's name appears once, because it overrides the
    built-in.
    """
    path = profiles_path if profiles_path is not None else get_user_profiles_path()
    user_names = {key for key in _load_user_profiles(path) if isinstance(key, str)}
    return sorted(set(_builtin_profiles()) | user_names)


def list_profile_sources(profiles_path: Path | None = None) -> dict[str, str]:
    """Map each available profile name to its source, ``"built-in"`` or ``"user"``.

    A user profile overrides a built-in of the same name and is reported as
    ``"user"``, matching what :func:`load_profile` would load.
    """
    path = profiles_path if profiles_path is not None else get_user_profiles_path()
    user_names = {key for key in _load_user_profiles(path) if isinstance(key, str)}
    sources = dict.fromkeys(_builtin_profiles(), "built-in")
    sources.update((name, "user") for name in user_names)
    return dict(sorted(sources.items()))


def load_profile(name: str, profiles_path: Path | None = None) -> MachineProfile:
    """Load and validate a built-in or user machine profile.

    Parameters
    ----------
    name : str
        Profile name. A user profile of this name wins over a built-in.
    profiles_path : Path | None
        Explicit user profiles file. Defaults to the XDG config location.

    Returns
    -------
    MachineProfile
        The validated profile.

    Raises
    ------
    ProfileFileError
        The file is missing, unreadable, empty or has the wrong shape.
    ProfileParseError
        The file is not valid YAML; the error names the file, line and reason.
    InvalidProfileError
        A value is invalid; the error names each offending key.
    UnknownProfileError
        The name is not a built-in or a user profile; available names are listed.
    """
    path = profiles_path if profiles_path is not None else get_user_profiles_path()
    user_profiles = _load_user_profiles(path)
    if name in user_profiles:
        return _validate_profile(user_profiles[name], name, path)

    builtin = _builtin_profiles().get(name)
    if builtin is not None:
        return _validate_profile(_read_yaml(builtin), name, builtin)

    available = ", ".join(list_profiles(path))
    raise UnknownProfileError(f"Unknown profile {name!r}. Available: {available}")


__all__ = [
    "PROFILE_FILE_VERSION",
    "BedProfile",
    "FeedProfile",
    "GcodeProfile",
    "InvalidProfileError",
    "MachineProfile",
    "PageProfile",
    "PenChangeProfile",
    "PenChangeStep",
    "PenProfile",
    "ProfileError",
    "ProfileFileError",
    "ProfileParseError",
    "UnknownProfileError",
    "get_user_profiles_path",
    "list_profile_sources",
    "list_profiles",
    "load_profile",
    "with_margin_mm",
]
