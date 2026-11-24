"""Fast checks of the plain-text basic-shape fixtures."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "images" / "basic"
GENERATOR_PATH = FIXTURES_DIR / "generate_basic.py"
FIXTURE_NAMES = (
    "black_square.pbm",
    "white_square.pbm",
    "black_disc.pbm",
    "horizontal_line.pbm",
    "checkerboard.pbm",
    "triangle.pbm",
)
BLACK_PIXELS = {
    "black_square.pbm": 625,
    "white_square.pbm": 3471,
    "black_disc.pbm": 1568,
    "horizontal_line.pbm": 102,
    "checkerboard.pbm": 2048,
    "triangle.pbm": 1742,
}


def _load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("generate_basic", GENERATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_basic_fixtures_are_reproducible(tmp_path: Path) -> None:
    """Regenerating the fixtures into an empty directory matches the committed bytes."""
    generator = _load_generator()
    generator.write_fixtures(tmp_path)
    for name in FIXTURE_NAMES:
        assert (tmp_path / name).read_bytes() == (FIXTURES_DIR / name).read_bytes(), name


def test_basic_fixtures_are_well_formed() -> None:
    """Every fixture is a 64x64 P1 file with only 0/1 pixels and the expected ink count."""
    for name in FIXTURE_NAMES:
        lines = (FIXTURES_DIR / name).read_bytes().splitlines()
        assert lines[0] == b"P1", name
        assert lines[1] == b"64 64", name
        assert len(lines) == 66, name
        pixels = b"".join(lines[2:])
        assert len(pixels) == 64 * 64, name
        assert set(pixels) <= {ord("0"), ord("1")}, name
        assert pixels.count(b"1") == BLACK_PIXELS[name], name
