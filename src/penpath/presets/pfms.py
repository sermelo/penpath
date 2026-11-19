"""Built-in PFM presets for penpath."""

from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings

PFM_PRESETS: dict[str, SketchLinesSettings] = {
    "fine": SketchLinesSettings(
        line_density=0.8,
        min_length=5.0,
        max_length=50.0,
        angle_range=(0.0, 360.0),
        shading_enabled=True,
        squiggle_enabled=True,
        erase_enabled=True,
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
        search_angle_step=1.0,
        sample_step=10.0,
    ),
    "default": SketchLinesSettings(),
}

DEFAULT_PFM = "default"


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


def list_pfm_presets() -> list[str]:
    """List all available PFM preset names.

    Returns
    -------
    list[str]
        Sorted list of preset names.
    """
    return sorted(PFM_PRESETS.keys())


__all__ = [
    "DEFAULT_PFM",
    "PFM_PRESETS",
    "get_pfm_preset",
    "list_pfm_presets",
]
