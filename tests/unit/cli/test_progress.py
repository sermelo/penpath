"""Unit tests for the CLI stage reporter."""

from __future__ import annotations

from io import StringIO
from types import SimpleNamespace

import pytest
from rich.console import Console

from penpath.cli import progress as progress_module
from penpath.cli.progress import StageReporter


class RecordingStream(StringIO):
    """A StringIO that counts explicit flushes."""

    def __init__(self) -> None:
        super().__init__()
        self.flushes = 0

    def flush(self) -> None:
        self.flushes += 1
        super().flush()


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Advance one second on every time read, for deterministic durations."""
    current = 0.0

    def monotonic() -> float:
        nonlocal current
        current += 1.0
        return current

    monkeypatch.setattr(progress_module, "time", SimpleNamespace(monotonic=monotonic))


def test_non_terminal_reports_flushed_numbered_lines(clock: None) -> None:
    stream = RecordingStream()
    reporter = StageReporter(Console(file=stream), total_stages=6)
    reporter.set_total_stages(3)

    with reporter:
        reporter.start("Loading image")
        reporter.finish()
        reporter.start("Generating lines (PFM)")
        reporter.finish()
    reporter.message("Working resolution: 32x32 px")
    reporter.summary()

    output = stream.getvalue()
    assert "[1/3] Loading image... done in 1.0 s" in output
    assert "[2/3] Generating lines (PFM)... done in 1.0 s" in output
    assert "Working resolution: 32x32 px" in output
    assert "Done in " in output
    assert stream.flushes >= 4


def test_terminal_keeps_bar_and_final_summary(clock: None) -> None:
    stream = StringIO()
    reporter = StageReporter(Console(file=stream, force_terminal=True), total_stages=2)

    with reporter:
        reporter.start("Loading image")
        reporter.finish()
        reporter.start("Exporting SVG")
        reporter.finish()
    reporter.summary()
    reporter.message("SVG saved to: plot.svg")

    output = stream.getvalue()
    assert "Exporting SVG" in output
    assert "100%" in output
    assert "\x1b[?25h" in output
    assert "Done in " in output
    assert "SVG saved to: plot.svg" in output
    assert "[1/2]" not in output


def test_quiet_writes_nothing(clock: None) -> None:
    stream = StringIO()
    reporter = StageReporter(Console(file=stream), quiet=True)

    with reporter:
        reporter.start("Loading image")
        reporter.finish()
        reporter.message("Working resolution: 32x32 px")
    reporter.summary()
    reporter.message("SVG saved to: plot.svg")

    assert stream.getvalue() == ""
