"""penpath - Turn images into pen plotter paths from Python or the command line."""

__version__ = "0.1.0"
__author__ = "Sergio Merino"
__email__ = "sergio.merino.a@gmail.com"

from penpath.cli.main import main  # ruff: ignore[unsorted-imports]
from penpath.api import convert, preview
from penpath.core import Drawing

__all__ = ["Drawing", "convert", "main", "preview"]
