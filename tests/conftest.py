"""Pytest configuration for penpath tests."""

import os
import sys
from pathlib import Path

import pytest

src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help="Regenerate golden files instead of comparing against them",
    )


@pytest.fixture
def update_golden(pytestconfig: pytest.Config) -> bool:
    """Whether this run was explicitly asked to regenerate golden files."""
    return bool(
        pytestconfig.getoption("--update-golden")
        or os.environ.get("PENPATH_UPDATE_GOLDEN", "") not in ("", "0", "false")
    )
