"""Built-in pen palettes for penpath.

The Stabilo colours are an approximation of the Point 88 chart; the table below
is the single place to correct them. Table order is the drawing order.
"""

from penpath.core.models import Palette, Pen

STABILO_88_WIDTH_MM = 0.4

STABILO_88_COLORS: dict[str, str] = {
    "yellow": "#F7E300",
    "cyan": "#00B5B0",
    "light_blue": "#8CCFE8",
    "blue": "#1B4C9E",
    "light_green": "#A9D18E",
    "purple": "#6C3B9E",
    "pink": "#F2A0BE",
    "brown": "#7A4B23",
    "orange": "#F4741F",
    "black": "#000000",
    "red": "#E4002B",
    "green": "#00963E",
}

STABILO_88 = Palette(
    name="stabilo_88",
    pens=[
        Pen(
            name=f"stabilo_88_{colour}",
            width_mm=STABILO_88_WIDTH_MM,
            color=color,
        )
        for colour, color in STABILO_88_COLORS.items()
    ],
)

PALETTES: dict[str, Palette] = {"stabilo_88": STABILO_88}


def get_palette(name: str) -> Palette:
    """Get a built-in palette by name."""
    if name not in PALETTES:
        raise ValueError(f"Unknown palette: {name}")
    return PALETTES[name]


def list_palettes() -> list[str]:
    """List all built-in palette names."""
    return sorted(PALETTES)


__all__ = [
    "PALETTES",
    "STABILO_88",
    "STABILO_88_COLORS",
    "STABILO_88_WIDTH_MM",
    "get_palette",
    "list_palettes",
]
