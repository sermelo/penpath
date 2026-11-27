"""Built-in PFM presets for penpath."""

from __future__ import annotations

from pydantic import BaseModel

from penpath.core.contact_sheet import ContactSheetEntry
from penpath.core.drawing.pfm_contour import ContourSettings
from penpath.core.drawing.pfm_hatch import HatchSettings
from penpath.core.drawing.pfm_patch_hatch import PatchHatchSettings
from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings
from penpath.core.drawing.pfm_sketch_squares import SketchSquaresSettings
from penpath.core.drawing.pfm_spiral import SpiralSettings
from penpath.core.drawing.pfm_squiggle import SquiggleSettings
from penpath.core.drawing.pfm_stipple import StippleSettings
from penpath.core.drawing.pfm_tsp import TSPSettings
from penpath.core.drawing.registry import get_pfm, list_pfms

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

SKETCH_SQUARES_PRESETS: dict[str, SketchSquaresSettings] = {
    "coarse": SketchSquaresSettings(
        grid_angle=45.0,
        line_density=0.45,
        min_length=8.0,
        max_length=120.0,
        max_fill=80.0,
    ),
    "fine": SketchSquaresSettings(
        grid_angle=45.0,
        line_density=0.9,
        min_length=2.0,
        max_length=30.0,
        max_fill=85.0,
    ),
    "crosshatch-grid": SketchSquaresSettings(
        grid_angle=0.0,
        line_density=0.75,
        min_length=4.0,
        max_length=60.0,
        max_fill=80.0,
    ),
}

SPIRAL_PRESETS: dict[str, SpiralSettings] = {
    "fine": SpiralSettings(
        ring_spacing=5.0,
        amplitude=0.8,
        min_velocity=40.0,
        max_velocity=100.0,
    ),
    "bold": SpiralSettings(
        ring_spacing=12.0,
        amplitude=2.0,
        min_velocity=60.0,
        max_velocity=200.0,
    ),
    "parabolic": SpiralSettings(spiral_type="parabolic"),
}

HATCH_PRESETS: dict[str, HatchSettings] = {
    "default": HatchSettings(
        angles=(45.0, 135.0), thresholds=(0.25, 0.5), min_gap=0.5, join_runs=True
    ),
    "crosshatch": HatchSettings(),
    "fine": HatchSettings(spacing=0.6),
    "single": HatchSettings(
        angles=(45.0, 45.0, 45.0, 45.0),
        variable_spacing=True,
    ),
}

PATCH_HATCH_PRESETS: dict[str, PatchHatchSettings] = {
    "default": PatchHatchSettings(),
    "fine": PatchHatchSettings(spacing=0.5, patch_size=7.0, min_patch_size=3.0),
    "bold": PatchHatchSettings(spacing=1.2, patch_size=14.0, min_patch_size=6.0),
    "fast": PatchHatchSettings(join_lines=True),
}

TSP_PRESETS: dict[str, TSPSettings] = {
    "default": TSPSettings(),
    "fine": TSPSettings(point_spacing=0.55, max_points=60000),
}

SQUIGGLE_PRESETS: dict[str, SquiggleSettings] = {
    "default": SquiggleSettings(),
    "fine": SquiggleSettings(line_spacing=1.2, max_frequency=2.5),
    "diagonal": SquiggleSettings(angle=45.0),
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
register_pfm_preset("stipple_default", "stipple", StippleSettings())
register_pfm_preset("stipple_fine", "stipple", StippleSettings(min_radius=0.5, max_radius=1.5))
register_pfm_preset("stipple_bold", "stipple", StippleSettings(min_radius=1.5, max_radius=5.0))

for _preset_name, _preset_settings in SKETCH_SQUARES_PRESETS.items():
    register_pfm_preset(f"sketch_squares:{_preset_name}", "sketch_squares", _preset_settings)

for _spiral_name, _spiral_settings in SPIRAL_PRESETS.items():
    register_pfm_preset(f"spiral_sawtooth:{_spiral_name}", "spiral_sawtooth", _spiral_settings)

for _hatch_name, _hatch_settings in HATCH_PRESETS.items():
    register_pfm_preset(f"hatch:{_hatch_name}", "hatch", _hatch_settings)

for _squiggle_name, _squiggle_settings in SQUIGGLE_PRESETS.items():
    register_pfm_preset(f"squiggle:{_squiggle_name}", "squiggle", _squiggle_settings)

for _tsp_name, _tsp_settings in TSP_PRESETS.items():
    register_pfm_preset(f"tsp:{_tsp_name}", "tsp", _tsp_settings)

for _patch_name, _patch_settings in PATCH_HATCH_PRESETS.items():
    register_pfm_preset(f"patch_hatch:{_patch_name}", "patch_hatch", _patch_settings)

PFM_PRESET_TYPES: dict[str, str] = {
    **{f"sketch_lines:{name}": "sketch_lines" for name in PFM_PRESETS},
    **{name: owner for name, (owner, _) in _EXTRA_PFM_PRESETS.items() if ":" in name},
}


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


def list_sheet_entries() -> list[ContactSheetEntry]:
    """Build the default entry and every preset entry for each registered PFM.

    A preset named ``default`` or qualified ``PFM:default`` is skipped: the
    PFM's own default entry already draws those settings. Each entry gets
    fresh settings so callers can change one without affecting another.

    Returns
    -------
    list[ContactSheetEntry]
        Entries in PFM order, defaults before that PFM's sorted presets.
    """
    entries: list[ContactSheetEntry] = []
    for pfm in list_pfms():
        _, model = get_pfm(pfm)
        entries.append(ContactSheetEntry(pfm=pfm, preset=None, settings=model()))
        for preset in list_presets_for_pfm(pfm):
            if preset == "default" or preset.endswith(":default"):
                continue
            settings = get_pfm_preset_settings(preset).model_copy(deep=True)
            entries.append(ContactSheetEntry(pfm=pfm, preset=preset, settings=settings))
    return entries


def list_pfm_presets() -> list[str]:
    """List all available PFM preset names.

    Returns
    -------
    list[str]
        Sorted list of preset names.
    """
    return sorted(set(PFM_PRESETS) | set(_EXTRA_PFM_PRESETS))


def list_pfm_preset_ids() -> list[str]:
    """List all built-in presets as qualified ``PFM:PRESET`` ids.

    Returns
    -------
    list[str]
        Sorted list of qualified preset ids.
    """
    return sorted(
        {f"sketch_lines:{name}" for name in PFM_PRESETS}
        | {pid for pid in _EXTRA_PFM_PRESETS if ":" in pid}
    )


def get_pfm_preset_by_id(preset_id: str) -> tuple[str, BaseModel]:
    """Resolve a qualified ``PFM:PRESET`` id to its PFM type and settings.

    Parameters
    ----------
    preset_id : str
        Qualified preset id, for example ``sketch_squares:fine``.

    Returns
    -------
    tuple[str, BaseModel]
        The registered PFM name and a fresh copy of the preset settings.

    Raises
    ------
    ValueError
        If the id is unknown, names an unregistered PFM or omits the PFM prefix.
    """
    if ":" not in preset_id:
        bare_matches = [pid for pid in list_pfm_preset_ids() if pid.partition(":")[2] == preset_id]
        if bare_matches:
            suggestions = " or ".join(f"'{pid}'" for pid in bare_matches)
            raise ValueError(f"Unknown PFM preset '{preset_id}'; did you mean {suggestions}?")
        raise ValueError(
            f"Unknown PFM preset '{preset_id}'. Use a qualified 'PFM:PRESET' id "
            f"or a registered PFM name: {list_pfms()}"
        )

    pfm_name, _, preset_name = preset_id.partition(":")
    if pfm_name not in list_pfms():
        raise ValueError(f"Unknown PFM: '{pfm_name}'. Available: {list_pfms()}")
    if pfm_name == "sketch_lines" and preset_name in PFM_PRESETS:
        return pfm_name, get_pfm_preset(preset_name).model_copy(deep=True)
    if preset_id in _EXTRA_PFM_PRESETS and _EXTRA_PFM_PRESETS[preset_id][0] == pfm_name:
        return pfm_name, get_pfm_preset_settings(preset_id).model_copy(deep=True)

    available = [pid for pid in list_pfm_preset_ids() if pid.startswith(f"{pfm_name}:")]
    raise ValueError(f"Unknown PFM preset '{preset_id}'. Available for {pfm_name}: {available}")


__all__ = [
    "DEFAULT_PFM",
    "HATCH_PRESETS",
    "PATCH_HATCH_PRESETS",
    "PFM_PRESETS",
    "PFM_PRESET_OWNERS",
    "PFM_PRESET_TYPES",
    "SKETCH_SQUARES_PRESETS",
    "SPIRAL_PRESETS",
    "SQUIGGLE_PRESETS",
    "TSP_PRESETS",
    "get_pfm_for_preset",
    "get_pfm_preset",
    "get_pfm_preset_by_id",
    "get_pfm_preset_settings",
    "list_pfm_preset_ids",
    "list_pfm_presets",
    "list_presets_for_pfm",
    "list_sheet_entries",
    "register_pfm_preset",
]
