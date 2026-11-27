"""Built-in PFM presets for penpath."""

from pydantic import BaseModel

from penpath.core.drawing.pfm_contour import ContourSettings
from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings
from penpath.core.drawing.registry import get_pfm

PFM_PRESETS: dict[str, SketchLinesSettings] = {
    "fine": SketchLinesSettings(
        line_density=0.8,
        min_length=5.0,
        max_length=50.0,
        angle_range=(0.0, 360.0),
        shading_enabled=True,
        squiggle_enabled=True,
        erase_enabled=True,
        max_fill=80.0,
        tone_coverage=1.0,
        tone_exponent=1.0,
        texture_limit=0.0,
        search_angle_step=5.0,
        sample_step=8.0,
    ),
    "bold": SketchLinesSettings(
        line_density=1.5,
        min_length=15.0,
        max_length=150.0,
        angle_range=(0.0, 360.0),
        shading_enabled=True,
        squiggle_enabled=False,
        erase_enabled=True,
        max_fill=80.0,
        tone_coverage=1.0,
        tone_exponent=1.0,
        texture_limit=0.0,
        search_angle_step=10.0,
        sample_step=15.0,
    ),
    "shaded": SketchLinesSettings(
        line_density=2.0,
        min_length=8.0,
        max_length=80.0,
        angle_range=(0.0, 360.0),
        shading_enabled=True,
        squiggle_enabled=True,
        erase_enabled=True,
        max_fill=80.0,
        tone_coverage=1.0,
        tone_exponent=1.0,
        texture_limit=0.0,
        search_angle_step=3.0,
        sample_step=5.0,
    ),
    "squiggly": SketchLinesSettings(
        line_density=1.2,
        min_length=10.0,
        max_length=100.0,
        angle_range=(0.0, 360.0),
        shading_enabled=False,
        squiggle_enabled=True,
        erase_enabled=False,
        max_fill=80.0,
        tone_coverage=1.0,
        tone_exponent=1.0,
        texture_limit=0.0,
        search_angle_step=5.0,
        sample_step=10.0,
    ),
    "crosshatch": SketchLinesSettings(
        line_density=1.0,
        min_length=20.0,
        max_length=200.0,
        angle_range=(45.0, 135.0),  # 45° to 135° (crosshatch angles)
        shading_enabled=True,
        squiggle_enabled=False,
        erase_enabled=True,
        max_fill=80.0,
        tone_coverage=1.0,
        tone_exponent=1.0,
        texture_limit=0.0,
        search_angle_step=2.0,
        sample_step=10.0,
    ),
    "hatch_horizontal": SketchLinesSettings(
        line_density=1.0,
        min_length=30.0,
        max_length=300.0,
        angle_range=(85.0, 95.0),  # Near horizontal
        shading_enabled=True,
        squiggle_enabled=False,
        erase_enabled=True,
        max_fill=80.0,
        tone_coverage=1.0,
        tone_exponent=1.0,
        texture_limit=0.0,
        search_angle_step=1.0,
        sample_step=10.0,
    ),
    "hatch_vertical": SketchLinesSettings(
        line_density=1.0,
        min_length=30.0,
        max_length=300.0,
        angle_range=(0.0, 10.0),  # Near vertical (or 170-190)
        shading_enabled=True,
        squiggle_enabled=False,
        erase_enabled=True,
        max_fill=80.0,
        tone_coverage=1.0,
        tone_exponent=1.0,
        texture_limit=0.0,
        search_angle_step=1.0,
        sample_step=10.0,
    ),
    "default": SketchLinesSettings(),
}

DEFAULT_PFM = "default"

PFM_PRESET_OWNERS: dict[str, str] = dict.fromkeys(PFM_PRESETS, "sketch_lines")
_EXTRA_PFM_PRESETS: dict[str, tuple[str, BaseModel]] = {}


def register_pfm_preset(name: str, pfm_type: str, settings: BaseModel) -> None:
    """Register a preset for a PFM other than the built-in sketch_lines one."""
    if name in PFM_PRESETS or name in _EXTRA_PFM_PRESETS:
        raise ValueError(f"PFM preset already registered: {name}")
    try:
        _, settings_model = get_pfm(pfm_type)
    except KeyError as e:
        raise ValueError(f"Unknown PFM: {pfm_type}") from e
    _EXTRA_PFM_PRESETS[name] = (pfm_type, settings_model.model_validate(settings.model_dump()))


register_pfm_preset(
    "contour_portrait",
    "contour",
    ContourSettings(
        threshold=110,
        levels=4,
        turn_policy="minority",
        turd_size=30,
        alpha_max=0.7,
        opticurve=True,
        smoothing=0.65,
        simplify_tolerance=0.6,
    ),
)
register_pfm_preset(
    "contour_silhouette",
    "contour",
    ContourSettings(
        threshold=140,
        levels=1,
        turn_policy="majority",
        turd_size=100,
        alpha_max=1.2,
        opticurve=True,
        smoothing=0.35,
        simplify_tolerance=1.5,
    ),
)


def get_pfm_preset(name: str) -> SketchLinesSettings:
    """Get a PFM preset by name.

    Parameters
    ----------
    name : str
        Name of the preset (e.g., "fine", "bold", "shaded", "squiggly").

    Returns
    -------
    SketchLinesSettings
        The preset settings.

    Raises
    ------
    ValueError
        If the preset name is not found.
    """
    if name not in PFM_PRESETS:
        raise ValueError(f"Unknown PFM preset: {name}")
    return PFM_PRESETS[name]


def get_pfm_preset_settings(name: str) -> BaseModel:
    """Get a preset's settings, from any registered PFM."""
    if name in PFM_PRESETS:
        return PFM_PRESETS[name]
    if name in _EXTRA_PFM_PRESETS:
        return _EXTRA_PFM_PRESETS[name][1]
    raise ValueError(f"Unknown PFM preset: {name}")


def get_pfm_for_preset(name: str) -> str:
    """Get the PFM a preset belongs to."""
    if name in PFM_PRESET_OWNERS:
        return PFM_PRESET_OWNERS[name]
    if name in _EXTRA_PFM_PRESETS:
        return _EXTRA_PFM_PRESETS[name][0]
    raise ValueError(f"Unknown PFM preset: {name}")


def list_presets_for_pfm(pfm_type: str) -> list[str]:
    """List the preset names belonging to one PFM."""
    builtin = [name for name, owner in PFM_PRESET_OWNERS.items() if owner == pfm_type]
    extra = [name for name, (owner, _) in _EXTRA_PFM_PRESETS.items() if owner == pfm_type]
    return sorted(builtin + extra)


def list_pfm_presets() -> list[str]:
    """List all available PFM preset names.

    Returns
    -------
    list[str]
        Sorted list of preset names.
    """
    return sorted(set(PFM_PRESETS) | set(_EXTRA_PFM_PRESETS))


__all__ = [
    "DEFAULT_PFM",
    "PFM_PRESETS",
    "PFM_PRESET_OWNERS",
    "get_pfm_for_preset",
    "get_pfm_preset",
    "get_pfm_preset_settings",
    "list_pfm_presets",
    "list_presets_for_pfm",
    "register_pfm_preset",
]
