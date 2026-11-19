"""Built-in paper presets for penpath."""

from penpath.cli.config import PaperConfig

PAPER_PRESETS: dict[str, PaperConfig] = {
    "a4": PaperConfig(name="a4", width=210.0, height=297.0, margin=10.0),
    "a3": PaperConfig(name="a3", width=297.0, height=420.0, margin=10.0),
    "a5": PaperConfig(name="a5", width=148.0, height=210.0, margin=10.0),
    "letter": PaperConfig(name="letter", width=215.9, height=279.4, margin=10.0),
    "legal": PaperConfig(name="legal", width=215.9, height=355.6, margin=10.0),
    "tabloid": PaperConfig(name="tabloid", width=279.4, height=431.8, margin=10.0),
    "square_200": PaperConfig(name="square_200", width=200.0, height=200.0, margin=10.0),
    "square_300": PaperConfig(name="square_300", width=300.0, height=300.0, margin=10.0),
}

DEFAULT_PAPER = "a4"


def get_paper(name: str) -> PaperConfig:
    """Get a paper preset by name."""
    if name not in PAPER_PRESETS:
        raise ValueError(f"Unknown paper preset: {name}")
    return PAPER_PRESETS[name]


def list_papers() -> list[str]:
    """List all available paper preset names."""
    return sorted(PAPER_PRESETS.keys())
