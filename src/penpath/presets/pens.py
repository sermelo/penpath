"""Built-in pen presets for penpath."""

from penpath.cli.config import PenConfig

PEN_PRESETS: dict[str, PenConfig] = {
    "fine": PenConfig(name="fine", width=0.3, color="black"),
    "medium": PenConfig(name="medium", width=0.5, color="black"),
    "bold": PenConfig(name="bold", width=0.8, color="black"),
    "extra_fine": PenConfig(name="extra_fine", width=0.2, color="black"),
    "brush": PenConfig(name="brush", width=1.0, color="black"),
    "red_fine": PenConfig(name="red_fine", width=0.3, color="red"),
    "blue_fine": PenConfig(name="blue_fine", width=0.3, color="blue"),
    "green_fine": PenConfig(name="green_fine", width=0.3, color="green"),
}

DEFAULT_PEN = "fine"


def get_pen(name: str) -> PenConfig:
    """Get a pen preset by name."""
    if name not in PEN_PRESETS:
        raise ValueError(f"Unknown pen preset: {name}")
    return PEN_PRESETS[name]


def list_pens() -> list[str]:
    """List all available pen preset names."""
    return sorted(PEN_PRESETS.keys())
