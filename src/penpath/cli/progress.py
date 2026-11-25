"""Stage reporting for CLI commands that run a long pipeline."""

from __future__ import annotations

import time
from types import TracebackType
from typing import Self

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

DEFAULT_TOTAL_STAGES = 6


class StageReporter:
    """Report pipeline stages to stderr as a bar or flushed plain lines.

    A terminal gets a live rich bar, kept on screen so the final summary stays
    visible. Redirected stderr gets one flushed ``[n/N] name... done in X s``
    line per finished stage, so a log fills in while the command runs.
    ``quiet`` suppresses every message, but never errors raised by the caller.
    """

    def __init__(
        self,
        console: Console,
        *,
        total_stages: int = DEFAULT_TOTAL_STAGES,
        quiet: bool = False,
    ) -> None:
        self._console = console
        self._total_stages = total_stages
        self._quiet = quiet
        self._run_started_at = time.monotonic()
        self._stage_started_at = self._run_started_at
        self._stage_name = "Starting..."
        self._stage_index = 0
        self._progress: Progress | None = None
        self._task_id: TaskID | None = None

    @property
    def uses_bar(self) -> bool:
        """Whether a live progress bar is active (stderr is a terminal)."""
        return self._progress is not None

    def __enter__(self) -> Self:
        if not self._quiet and self._console.is_terminal:
            self._progress = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                console=self._console,
                transient=False,
            )
            self._progress.__enter__()
            self._task_id = self._progress.add_task("Starting...", total=self._total_stages)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._progress is not None:
            self._progress.__exit__(exc_type, exc_value, traceback)
            self._progress = None
            self._task_id = None

    def set_total_stages(self, total: int) -> None:
        """Update the stage count once optional stages are known."""
        self._total_stages = total
        if self._progress is not None and self._task_id is not None:
            self._progress.update(self._task_id, total=total)

    def start(self, name: str) -> None:
        """Begin a stage, naming it on the terminal bar and starting its timer."""
        self._stage_name = name
        self._stage_started_at = time.monotonic()
        if self._progress is not None and self._task_id is not None:
            self._progress.update(self._task_id, description=f"{name}...")

    def finish(self) -> None:
        """Report the current stage as finished, with its elapsed time."""
        if self._quiet:
            return
        now = time.monotonic()
        elapsed = now - self._stage_started_at
        self._stage_started_at = now
        self._stage_index += 1
        if self._progress is not None and self._task_id is not None:
            self._progress.update(self._task_id, description=self._stage_name, advance=1)
        else:
            self._console.print(
                f"[{self._stage_index}/{self._total_stages}] "
                f"{self._stage_name}... done in {elapsed:.1f} s",
                markup=False,
            )
            self._console.file.flush()

    def message(self, text: str, *, markup: bool = True, style: str | None = None) -> None:
        """Write one non-error message to stderr unless quiet."""
        if self._quiet:
            return
        self._console.print(text, markup=markup, style=style)
        self._console.file.flush()

    def summary(self) -> None:
        """Write the total run time after the stages have finished."""
        if self._quiet:
            return
        total = time.monotonic() - self._run_started_at
        self._console.print(f"Done in {total:.1f} s", markup=False)
        self._console.file.flush()


__all__ = ["StageReporter"]
