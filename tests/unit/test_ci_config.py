"""Tests for CI configuration consistency."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _minimum_python() -> tuple[int, int]:
    pyproject = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    specifier = pyproject["project"]["requires-python"]
    match = re.match(r">=(\d+)\.(\d+)", specifier)
    assert match is not None, f"Unsupported requires-python: {specifier}"
    return int(match.group(1)), int(match.group(2))


def test_ci_python_pins_satisfy_requires_python() -> None:
    """Every setup-python pin must meet the project's minimum Python version."""
    workflow = yaml.safe_load(
        (_REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    pins = [
        step["with"]["python-version"]
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if step.get("uses", "").startswith("actions/setup-python@")
    ]
    minimum = _minimum_python()

    assert len(pins) == 6, f"Expected a Python pin in each of the 6 jobs, got {pins}"
    for pin in pins:
        major, minor = (int(part) for part in pin.split(".")[:2])
        assert (major, minor) >= minimum, f"Python {pin} is below requires-python {minimum}"
