"""Configuration loading for penpath."""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PenConfig:
    """Configuration for a pen preset."""

    name: str
    width: float
    color: str = "black"
    opacity: float = 1.0


@dataclass
class PaperConfig:
    """Configuration for a paper preset."""

    name: str
    width: float
    height: float
    margin: float = 0.0


def _default_pens() -> dict[str, PenConfig]:
    return {
        "fine": PenConfig(name="fine", width=0.3, color="black"),
        "medium": PenConfig(name="medium", width=0.5, color="black"),
        "bold": PenConfig(name="bold", width=0.8, color="black"),
    }


def _default_papers() -> dict[str, PaperConfig]:
    return {
        "a4": PaperConfig(name="a4", width=210.0, height=297.0, margin=10.0),
        "a3": PaperConfig(name="a3", width=297.0, height=420.0, margin=10.0),
        "letter": PaperConfig(name="letter", width=215.9, height=279.4, margin=10.0),
    }


@dataclass
class Config:
    """Main configuration for penpath."""

    pens: dict[str, PenConfig] = field(default_factory=_default_pens)
    papers: dict[str, PaperConfig] = field(default_factory=_default_papers)
    default_pen: str = "fine"
    default_paper: str = "a4"
    output_dir: str = "output"

    def get_pen(self, name: str | None = None) -> PenConfig:
        """Get a pen config by name, or the default."""
        pen_name = name or self.default_pen
        if pen_name not in self.pens:
            raise ValueError(f"Pen '{pen_name}' not found in configuration")
        return self.pens[pen_name]

    def get_paper(self, name: str | None = None) -> PaperConfig:
        """Get a paper config by name, or the default."""
        paper_name = name or self.default_paper
        if paper_name not in self.papers:
            raise ValueError(f"Paper '{paper_name}' not found in configuration")
        return self.papers[paper_name]


DEFAULT_CONFIG = Config()


def get_config_path() -> Path:
    """Get the path to the user config file."""
    config_home = os.environ.get("XDG_CONFIG_HOME")
    if config_home:
        return Path(config_home) / "penpath" / "config.toml"
    return Path.home() / ".config" / "penpath" / "config.toml"


def load_config(config_path: Path | None = None) -> Config:
    """Load configuration from a TOML file, falling back to defaults."""
    if config_path is None:
        config_path = get_config_path()

    if not config_path.exists():
        return DEFAULT_CONFIG

    try:
        with config_path.open("rb") as f:
            data = tomllib.load(f)
    except Exception as e:
        raise RuntimeError(f"Failed to parse config file {config_path}: {e}") from e

    return _merge_config(DEFAULT_CONFIG, data)


def _merge_config(default: Config, data: dict[str, Any]) -> Config:
    """Merge user config with defaults."""
    pens = default.pens.copy()
    if "pens" in data:
        for name, pen_data in data["pens"].items():
            pens[name] = PenConfig(
                name=name,
                width=pen_data.get("width", 0.5),
                color=pen_data.get("color", "black"),
                opacity=pen_data.get("opacity", 1.0),
            )

    papers = default.papers.copy()
    if "papers" in data:
        for name, paper_data in data["papers"].items():
            papers[name] = PaperConfig(
                name=name,
                width=paper_data.get("width", 210.0),
                height=paper_data.get("height", 297.0),
                margin=paper_data.get("margin", 0.0),
            )

    return Config(
        pens=pens,
        papers=papers,
        default_pen=data.get("default_pen", default.default_pen),
        default_paper=data.get("default_paper", default.default_paper),
        output_dir=data.get("output_dir", default.output_dir),
    )


def save_config(config: Config, config_path: Path | None = None) -> None:
    """Save configuration to a TOML file."""
    if config_path is None:
        config_path = get_config_path()

    config_path.parent.mkdir(parents=True, exist_ok=True)

    import tomli_w

    data = {
        "default_pen": config.default_pen,
        "default_paper": config.default_paper,
        "output_dir": config.output_dir,
        "pens": {
            name: {"width": pen.width, "color": pen.color, "opacity": pen.opacity}
            for name, pen in config.pens.items()
        },
        "papers": {
            name: {"width": paper.width, "height": paper.height, "margin": paper.margin}
            for name, paper in config.papers.items()
        },
    }

    with config_path.open("wb") as f:
        tomli_w.dump(data, f)
