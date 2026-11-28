"""Tests that checked-in Python-version declarations agree with requires-python."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
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
    tokens = shlex.split(command)
    index = tokens.index("pytest") + 1
    targets: list[str] = []
    skip_next = False
    for token in tokens[index:]:
        if skip_next:
            skip_next = False
        elif token == "-m":
            skip_next = True
        elif not token.startswith("-"):
            targets.append(token)
    return targets


def _needs(job: dict[str, object]) -> set[str]:
    needs = job.get("needs", [])
    if isinstance(needs, str):
        return {needs}
    return {str(entry) for entry in needs}


def _pytest_ini() -> dict[str, object]:
    pyproject = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    options = pyproject["tool"]["pytest"]["ini_options"]
    assert isinstance(options, dict)
    return options


def test_pytest_default_excludes_slow_and_registers_the_marker() -> None:
    """A bare pytest run is fast; --strict-markers knows the slow marker."""
    options = _pytest_ini()
    assert "-m 'not slow'" in str(options["addopts"])
    markers = options["markers"]
    assert isinstance(markers, list)
    assert any(str(marker).startswith("slow:") for marker in markers)


def test_pytest_marker_filters_override_the_default() -> None:
    """Both explicit -m expressions replace, not add to, the default filter."""

    def collected(expression: str) -> str:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "-m",
                expression,
                "tests/unit/test_ci_config.py",
                "tests/integration/test_sketch_lines_gate.py",
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    slow = collected("slow")
    assert "<Module test_sketch_lines_gate.py>" in slow
    assert "<Module test_ci_config.py>" not in slow

    everything = collected("slow or not slow")
    assert "<Module test_sketch_lines_gate.py>" in everything
    assert "<Module test_ci_config.py>" in everything


def test_ci_splits_likeness_gate_from_rest_of_integration() -> None:
    """The gate and the rest of integration run in separate parallel jobs."""
    jobs = _ci_jobs()
    gate = jobs["integration-gate"]
    rest = jobs["integration-rest"]

    gate_command = _run_command(gate, "Run fast gate helper checks")
    assert _pytest_targets(gate_command) == ["tests/integration/test_gate_measures.py"]
    assert "-m 'not slow'" in gate_command

    rest_command = _run_command(rest, "Run integration tests")
    assert _pytest_targets(rest_command) == ["tests/integration"]
    assert "-m 'not slow'" in rest_command
    assert "--ignore=tests/integration/test_sketch_lines_gate.py" in rest_command
    assert "--ignore=tests/integration/test_gate_measures.py" in rest_command

    assert "integration-gate" not in _needs(rest)
    assert "integration-rest" not in _needs(gate)

    unit_command = _run_command(jobs["test"], "Run unit tests with coverage")
    assert "tests/unit" in unit_command
    assert "-m 'not slow'" in unit_command


def test_required_ci_job_names_are_unchanged() -> None:
    """Slow gates add a job; the five required checks keep their names."""
    names = {str(job["name"]) for job in _ci_jobs().values()}
    assert {
        "Lint & Format",
        "Type Check (mypy)",
        "Unit Tests",
        "Integration Tests",
        "Build Wheel",
    } <= names


def test_slow_quality_gates_run_only_on_main_push() -> None:
    """The main-only job selects slow tests; PR jobs select none of them."""
    jobs = _ci_jobs()
    slow = jobs["slow-gates"]

    assert slow["name"] == "Quality Gates (Slow)"
    assert slow["if"] == "github.event_name == 'push' && github.ref == 'refs/heads/main'"
    command = _run_command(slow, "Run slow quality gates")
    assert "-m 'slow'" in command
    assert "-m 'not slow'" not in command

    for name in ("test", "integration-gate", "integration-rest"):
        commands = [str(step["run"]) for step in jobs[name]["steps"] if "run" in step]
        assert all("-m 'slow'" not in command for command in commands), name


def _nightly_workflow() -> dict[str, object]:
    workflow = yaml.safe_load((_WORKFLOWS_DIR / "nightly.yml").read_text(encoding="utf-8"))
    assert isinstance(workflow, dict)
    return workflow


def _nightly_job() -> dict[str, object]:
    jobs = _nightly_workflow()["jobs"]
    assert isinstance(jobs, dict)
    assert len(jobs) == 1
    job = next(iter(jobs.values()))
    assert isinstance(job, dict)
    return job


def test_nightly_runs_on_schedule_and_by_hand_only() -> None:
    """A timer and workflow_dispatch start it; a pull request never does."""
    triggers = _nightly_workflow()[True]
    assert isinstance(triggers, dict)
    assert "schedule" in triggers
    assert "workflow_dispatch" in triggers
    assert "pull_request" not in triggers
    assert "push" not in triggers


def _nightly_script() -> Path:
    return _REPO_ROOT / "scripts" / "nightly.sh"


def _nightly_script_text() -> str:
    return _nightly_script().read_text(encoding="utf-8")


def test_nightly_workflow_calls_the_shared_runner() -> None:
    """The workflow delegates its workload to the script a user runs locally."""
    commands = [str(step["run"]) for step in _nightly_job()["steps"] if "run" in step]
    assert any("bash scripts/nightly.sh" in command for command in commands)
    for fragment in ("uv sync", "uv pip install", "/usr/bin/time", "uv run pytest"):
        assert not any(fragment in command for command in commands), fragment


def test_nightly_script_runs_full_unit_and_integration_suite() -> None:
    """One shared runner covers both test directories, including slow gates."""
    script = _nightly_script_text()
    assert "uv run pytest tests/unit tests/integration -vs -m 'slow or not slow'" in script
    assert "-m 'not slow'" not in script


def test_nightly_script_times_one_photo_conversion() -> None:
    """The shared runner records a wall-clock time for a real photo convert."""
    script = _nightly_script_text()
    assert "-f 'penpath convert wall time: %e s'" in script
    assert "--pfm-setting seed=42" in script
    assert "tests/fixtures/images/reference/photo.jpg" in script
    assert "-o /tmp/nightly-photo.svg" in script


def test_nightly_script_syncs_dev_and_vpype_extras() -> None:
    """The shared runner installs the same extras and test tools as the workflow."""
    script = _nightly_script_text()
    assert "uv sync --python 3.14 --extra dev --extra vpype" in script
    assert "uv pip install pytest pytest-cov" in script
    assert os.access(_nightly_script(), os.X_OK)


def test_nightly_command_is_documented() -> None:
    """The exact command a user runs appears in the README and testing guide."""
    for name in ("README.md", "docs/TESTING.md"):
        text = (_REPO_ROOT / name).read_text(encoding="utf-8")
        assert "bash scripts/nightly.sh" in text, name
