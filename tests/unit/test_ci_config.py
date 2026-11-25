"""Tests that checked-in Python-version declarations agree with requires-python."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOWS_DIR = _REPO_ROOT / ".github" / "workflows"
_PYTHON_CLASSIFIER = re.compile(r"^Programming Language :: Python :: (\d+)\.(\d+)$")


def _minimum_python() -> tuple[int, int]:
    pyproject = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    specifier = pyproject["project"]["requires-python"]
    match = re.match(r">=(\d+)\.(\d+)", specifier)
    assert match is not None, f"Unsupported requires-python: {specifier}"
    return int(match.group(1)), int(match.group(2))


def _version(value: str) -> tuple[int, int]:
    match = re.match(r"(\d+)\.(\d+)", value)
    assert match is not None, f"Unsupported Python version: {value}"
    return int(match.group(1)), int(match.group(2))


def _setup_python_pins() -> dict[str, list[str]]:
    pins: dict[str, list[str]] = {}
    for path in sorted(_WORKFLOWS_DIR.glob("*.y*ml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        pins[path.name] = [
            step["with"]["python-version"]
            for job in workflow["jobs"].values()
            for step in job["steps"]
            if step.get("uses", "").startswith("actions/setup-python@")
        ]
    return pins


def test_ci_python_pins_satisfy_requires_python() -> None:
    """Every setup-python pin in ci.yml must meet the project's minimum Python version."""
    pins = _setup_python_pins()["ci.yml"]
    minimum = _minimum_python()

    assert pins, "No setup-python pins found in ci.yml"
    for pin in pins:
        assert _version(pin) >= minimum, f"Python {pin} is below requires-python {minimum}"


def test_all_workflow_python_pins_satisfy_requires_python() -> None:
    """Every setup-python pin in any workflow must meet requires-python."""
    pins_by_workflow = _setup_python_pins()
    minimum = _minimum_python()

    assert pins_by_workflow, f"No workflows found in {_WORKFLOWS_DIR}"
    assert any(pins_by_workflow.values()), "No workflow declares a setup-python pin"
    for workflow, pins in pins_by_workflow.items():
        for pin in pins:
            assert _version(pin) >= minimum, (
                f"Python {pin} in {workflow} is below requires-python {minimum}"
            )


def test_python_classifiers_satisfy_requires_python() -> None:
    """Advertised Python classifiers must not claim versions below requires-python."""
    pyproject = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    classifiers = pyproject["project"]["classifiers"]
    python_classifiers = [
        classifier for classifier in classifiers if _PYTHON_CLASSIFIER.match(classifier)
    ]
    minimum = _minimum_python()

    assert python_classifiers, "No Programming Language :: Python :: X.Y classifier found"
    for classifier in python_classifiers:
        match = _PYTHON_CLASSIFIER.match(classifier)
        assert match is not None
        version = int(match.group(1)), int(match.group(2))
        assert version >= minimum, f"Classifier {classifier!r} is below requires-python {minimum}"


def _ci_jobs() -> dict[str, dict[str, object]]:
    workflow = yaml.safe_load((_WORKFLOWS_DIR / "ci.yml").read_text(encoding="utf-8"))
    return workflow["jobs"]


def _run_command(job: dict[str, object], step_name: str) -> str:
    for step in job["steps"]:
        if step.get("name") == step_name:
            return str(step["run"])
    raise AssertionError(f"No {step_name!r} step found in job")


def _pytest_targets(command: str) -> list[str]:
    tokens = command.split()
    return [token for token in tokens[tokens.index("pytest") + 1 :] if not token.startswith("-")]


def _needs(job: dict[str, object]) -> set[str]:
    needs = job.get("needs", [])
    if isinstance(needs, str):
        return {needs}
    return {str(entry) for entry in needs}


def test_ci_splits_likeness_gate_from_rest_of_integration() -> None:
    """The gate and the rest of integration run in separate parallel jobs."""
    jobs = _ci_jobs()
    gate = jobs["integration-gate"]
    rest = jobs["integration-rest"]

    assert _pytest_targets(_run_command(gate, "Run likeness gate")) == [
        "tests/integration/test_sketch_lines_gate.py",
        "tests/integration/test_gate_measures.py",
    ]

    rest_command = _run_command(rest, "Run integration tests")
    assert _pytest_targets(rest_command) == ["tests/integration"]
    assert "--ignore=tests/integration/test_sketch_lines_gate.py" in rest_command
    assert "--ignore=tests/integration/test_gate_measures.py" in rest_command

    assert "integration-gate" not in _needs(rest)
    assert "integration-rest" not in _needs(gate)

    assert "tests/unit" in _run_command(jobs["test"], "Run unit tests with coverage")
