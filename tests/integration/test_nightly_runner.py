"""End-to-end tests for the local nightly workload runner."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "nightly.sh"

_STUB_UV = """#!/usr/bin/env bash
printf '%s|%s\\n' "$PWD" "$*" >> "$PENPATH_NIGHTLY_LOG"
if [[ -n "${PENPATH_NIGHTLY_FAIL_ON:-}" && "$*" == *"$PENPATH_NIGHTLY_FAIL_ON"* ]]; then
  exit 7
fi
"""

_STUB_TIME = """#!/usr/bin/env bash
[[ "$1" == "-f" ]] || exit 9
format="$2"
shift 2
printf '%s\\n' "${format//%e/0.42}"
exec "$@"
"""


def _write_stub(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture
def stubbed_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Log uv calls and run a fake GNU time so the real script stays fast."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_stub(bin_dir / "uv", _STUB_UV)
    _write_stub(bin_dir / "time", _STUB_TIME)
    log = tmp_path / "commands.log"
    log.touch()
    monkeypatch.delenv("BASH_ENV", raising=False)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("PENPATH_NIGHTLY_LOG", str(log))
    monkeypatch.setenv("PENPATH_NIGHTLY_TIME", str(bin_dir / "time"))
    return log


def _run_runner(cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(_SCRIPT)],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def test_runner_runs_nightly_workload_in_order(stubbed_tools: Path, tmp_path: Path) -> None:
    """Invoking the script runs sync, tools, timed convert and the full suite in order."""
    result = _run_runner(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "penpath convert wall time: 0.42 s" in result.stdout
    assert stubbed_tools.read_text(encoding="utf-8").splitlines() == [
        f"{_REPO_ROOT}|sync --python 3.14 --extra dev --extra vpype",
        f"{_REPO_ROOT}|pip install pytest pytest-cov",
        (
            f"{_REPO_ROOT}|run penpath convert "
            "tests/fixtures/images/reference/photo.jpg "
            "-o /tmp/nightly-photo.svg --pfm-setting seed=42 --quiet"
        ),
        f"{_REPO_ROOT}|run pytest tests/unit tests/integration -vs -m slow or not slow",
    ]


def test_runner_stops_when_a_step_fails(
    stubbed_tools: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed step stops the runner before the conversion or test suite."""
    monkeypatch.setenv("PENPATH_NIGHTLY_FAIL_ON", "pip install")

    result = _run_runner(tmp_path)

    assert result.returncode == 7
    assert "wall time" not in result.stdout
    assert len(stubbed_tools.read_text(encoding="utf-8").splitlines()) == 2


def test_runner_stops_when_time_binary_is_missing(
    stubbed_tools: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bad PENPATH_NIGHTLY_TIME override stops before the conversion or suite."""
    bad_time = tmp_path / "missing-time"
    monkeypatch.setenv("PENPATH_NIGHTLY_TIME", str(bad_time))

    result = _run_runner(tmp_path)

    assert result.returncode == 127
    assert str(bad_time) in result.stderr
    assert "wall time" not in result.stdout
    assert len(stubbed_tools.read_text(encoding="utf-8").splitlines()) == 2
