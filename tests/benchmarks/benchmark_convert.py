"""Benchmark the full-size conversion on the budget case: 12 MP, 190x190 mm, 0.4 mm pen.

Run by path, not through pytest:

    uv run python tests/benchmarks/benchmark_convert.py
    uv run python tests/benchmarks/benchmark_convert.py --budget 120
    uv run python tests/benchmarks/benchmark_convert.py --image photo.jpg

The benchmark drives ``penpath convert`` through the same CLI entry point a
user runs, and times each stage with the CLI's own stage reporter. It exits 1
when the wall-clock total exceeds the budget (30 s by default).
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ClassVar

import click
import numpy as np
from click.testing import CliRunner
from PIL import Image
from rich.console import Console

from penpath.cli.commands import convert as convert_module
from penpath.cli.main import main as cli_app
from penpath.cli.progress import StageReporter

SOURCE_SIZE_PX = (4080, 3072)
DEFAULT_BUDGET_S = 30.0
PAPER_SPEC = "190x190"
PEN_SPEC = "0.4,black"


class TimingReporter(StageReporter):
    """Stage reporter that also keeps the elapsed time of each stage."""

    instances: ClassVar[list[TimingReporter]] = []

    def __init__(self, console: Console, *, quiet: bool = False) -> None:
        super().__init__(console, quiet=True)
        self.stages: list[tuple[str, float]] = []
        self._stage_name_for_timing = "Starting..."
        self._stage_started_at = time.monotonic()
        self.instances.append(self)

    def start(self, name: str) -> None:
        """Begin timing a stage when the pipeline begins it."""
        self._stage_name_for_timing = name
        self._stage_started_at = time.monotonic()
        super().start(name)

    def finish(self) -> None:
        """Record the elapsed time when the pipeline reports the stage done."""
        elapsed = time.monotonic() - self._stage_started_at
        super().finish()
        self.stages.append((self._stage_name_for_timing, elapsed))


def make_test_image(path: Path) -> None:
    """Write a deterministic 4080x3072 greyscale image with tone and shapes."""
    width, height = SOURCE_SIZE_PX
    y = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None]
    x = np.linspace(0.0, 1.0, width, dtype=np.float32)[None, :]
    tone = 255.0 * (1.0 - x) * (0.55 + 0.45 * y)
    disc = ((x - 0.35) ** 2 + (y - 0.45) ** 2) < 0.16**2
    tone = np.where(disc, tone * 0.25, tone)
    tone = np.where((x > 0.6) & (x < 0.9) & (y > 0.1) & (y < 0.8), 255.0 - tone, tone)
    Image.fromarray(np.clip(tone, 0.0, 255.0).astype(np.uint8)).save(path)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the benchmark's options."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--image",
        type=Path,
        help=f"input image (default: a deterministic {SOURCE_SIZE_PX[0]}x"
        f"{SOURCE_SIZE_PX[1]} image)",
    )
    parser.add_argument(
        "--budget",
        type=float,
        default=DEFAULT_BUDGET_S,
        help=f"fail when the conversion takes longer than this many seconds "
        f"(default: {DEFAULT_BUDGET_S:g})",
    )
    parser.add_argument("--output", type=Path, help="SVG output path (default: a temporary file)")
    args = parser.parse_args(argv)
    if args.budget <= 0:
        parser.error("--budget must be a positive number of seconds")
    return args


def run(args: argparse.Namespace, work_dir: Path) -> int:
    """Run the CLI conversion once and report its stage timings."""
    image = args.image or work_dir / "benchmark_12mp.png"
    if args.image is None:
        make_test_image(image)
    output = args.output or work_dir / "benchmark.svg"

    TimingReporter.instances.clear()
    original_reporter = convert_module.StageReporter
    convert_module.StageReporter = TimingReporter
    try:
        started_at = time.monotonic()
        result = CliRunner().invoke(
            cli_app,
            [
                "convert",
                str(image),
                "-o",
                str(output),
                "--paper",
                PAPER_SPEC,
                "--pen",
                PEN_SPEC,
                "--quiet",
            ],
            env={"XDG_CONFIG_HOME": str(work_dir / "config")},
        )
        total = time.monotonic() - started_at
    finally:
        convert_module.StageReporter = original_reporter
    stages = TimingReporter.instances[0].stages if TimingReporter.instances else []

    if result.exit_code != 0:
        click.echo(f"penpath convert failed (exit {result.exit_code}):", err=True)
        click.echo(result.output, err=True)
        return 1

    click.echo(f"Input: {image} ({image.stat().st_size / 1_000_000:.1f} MB on disk)")
    click.echo(f"Paper: {PAPER_SPEC} mm, pen: {PEN_SPEC} mm")
    click.echo()
    click.echo(f"{'stage':<28}{'time (s)':>10}")
    for name, elapsed in stages:
        click.echo(f"{name:<28}{elapsed:>10.2f}")
    click.echo(f"{'total (wall clock)':<28}{total:>10.2f}")
    click.echo(f"{'budget':<28}{args.budget:>10.2f}")
    if total > args.budget:
        click.echo(f"FAIL: {total:.2f} s exceeds the {args.budget:.2f} s budget")
        return 1
    click.echo(f"PASS: {total:.2f} s is within the {args.budget:.2f} s budget")
    return 0


def main() -> int:
    """Run the benchmark from the command line."""
    args = parse_args()
    with TemporaryDirectory() as temp_dir:
        return run(args, Path(temp_dir))


if __name__ == "__main__":
    raise SystemExit(main())
