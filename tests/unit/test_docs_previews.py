"""Check that the committed LUC-176 Spiral Sawtooth previews are present and linked."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PREVIEW_DIR = _REPO_ROOT / "docs" / "images" / "luc-176"
_PREVIEWS = ("photo_circle", "santa_circle", "photo_cover", "photo_ellipse")


@pytest.mark.parametrize("name", _PREVIEWS)
def test_committed_preview_is_a_rendered_570_px_png(name: str) -> None:
    """Each preview is a small 3 px/mm render of the 190x190 mm gate paper with ink."""
    path = _PREVIEW_DIR / f"{name}.png"
    assert path.is_file(), f"missing committed preview {path}"
    with Image.open(path) as opened:
        assert opened.format == "PNG"
        assert opened.size == (570, 570)
        minimum, maximum = opened.convert("L").getextrema()
    assert minimum < 128 < maximum, f"{name}.png has no ink or no paper"


@pytest.mark.parametrize("name", _PREVIEWS)
def test_committed_preview_is_linked_from_user_docs(name: str) -> None:
    """A reader can reach each preview from the README or the testing guide."""
    target = f"docs/images/luc-176/{name}.png"
    readme = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
    testing = (_REPO_ROOT / "docs" / "TESTING.md").read_text(encoding="utf-8")
    assert target in readme or target in testing, f"{target} is not linked from the docs"
