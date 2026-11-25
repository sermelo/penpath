"""Unit tests for the by-path conversion benchmark's command-line contract."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

BENCHMARK_PATH = Path(__file__).resolve().parents[1] / "benchmarks" / "benchmark_convert.py"


@pytest.fixture(scope="module")
def benchmark() -> Any:
    """Load the benchmark script by path; it is not a pytest module."""
    spec = importlib.util.spec_from_file_location("benchmark_convert", BENCHMARK_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def advancing_clock(benchmark: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Advance two seconds on every benchmark time read, for deterministic totals."""
    current = 0.0

    def monotonic() -> float:
        nonlocal current
        current += 2.0
        return current

    monkeypatch.setattr(benchmark, "time", SimpleNamespace(monotonic=monotonic))


def tiny_image(path: Path) -> Path:
    """Write a small input so the real conversion stays quick in the test."""
    Image.new("L", (48, 36), 128).save(path)
    return path


def test_default_budget_and_options(benchmark: Any) -> None:
    args = benchmark.parse_args([])
    assert args.budget == benchmark.DEFAULT_BUDGET_S == 30.0
    assert args.image is None
    assert args.output is None


@pytest.mark.parametrize("bad_budget", ["0", "-1"])
def test_nonpositive_budget_is_a_usage_error(benchmark: Any, bad_budget: str) -> None:
    with pytest.raises(SystemExit) as excinfo:
        benchmark.parse_args(["--budget", bad_budget])
    assert excinfo.value.code == 2


def test_run_reports_stages_and_passes_within_budget(
    benchmark: Any, advancing_clock: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    image = tiny_image(tmp_path / "tiny.png")
    args = benchmark.parse_args(["--image", str(image), "--budget", "1000"])

    assert benchmark.run(args, tmp_path) == 0
    output = capsys.readouterr().out
    assert "stage" in output and "time (s)" in output
    for stage in ("Loading image", "Generating lines (PFM)", "Optimizing geometry"):
        assert stage in output
    assert "total (wall clock)" in output
    assert "PASS:" in output


def test_run_fails_when_total_exceeds_budget(
    benchmark: Any, advancing_clock: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    image = tiny_image(tmp_path / "tiny.png")
    args = benchmark.parse_args(["--image", str(image), "--budget", "1"])

    assert benchmark.run(args, tmp_path) == 1
    assert "FAIL:" in capsys.readouterr().out


def test_run_fails_when_conversion_fails(
    benchmark: Any, advancing_clock: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = benchmark.parse_args(["--image", str(tmp_path / "missing.png")])

    assert benchmark.run(args, tmp_path) == 1
    assert "penpath convert failed" in capsys.readouterr().err
