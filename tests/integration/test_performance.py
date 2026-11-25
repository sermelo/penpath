"""Timing test for a large conversion through the real ``penpath convert`` CLI.

A 12 MP photo is the VPS budget case (30 s, see ``docs/TESTING.md``), but the
working resolution is set by the paper and pen, not by the input pixels. Once
the source is larger than the working image, the drawing cost of a 12 MP photo
and of a 1 MP photo is the same: only load and downscale grow with input size.
This test therefore uses a smaller image and the 190x190 mm / 0.4 mm pen budget
settings, so it still exercises the whole pipeline while staying quick in CI.
It asserts a generous 120 s bound because a slow shared runner must not make CI
flaky; the 30 s VPS budget is enforced by ``tests/benchmarks/benchmark_convert.py``.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
from click.testing import CliRunner
from PIL import Image

from penpath.cli.main import main

CI_BUDGET_S = 120.0


def make_large_image(path: Path) -> Path:
    """Write a deterministic 1200x900 image with the same content as the benchmark."""
    width, height = 1200, 900
    y = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None]
    x = np.linspace(0.0, 1.0, width, dtype=np.float32)[None, :]
    tone = 255.0 * (1.0 - x) * (0.55 + 0.45 * y)
    disc = ((x - 0.35) ** 2 + (y - 0.45) ** 2) < 0.16**2
    tone = np.where(disc, tone * 0.25, tone)
    tone = np.where((x > 0.6) & (x < 0.9) & (y > 0.1) & (y < 0.8), 255.0 - tone, tone)
    Image.fromarray(np.clip(tone, 0.0, 255.0).astype(np.uint8)).save(path)
    return path


def test_convert_large_image_meets_ci_budget(tmp_path: Path) -> None:
    """The CLI converts a large image well inside the generous CI bound."""
    image = make_large_image(tmp_path / "large.png")
    output = tmp_path / "large.svg"

    started_at = time.monotonic()
    result = CliRunner().invoke(
        main,
        [
            "convert",
            str(image),
            "-o",
            str(output),
            "--paper",
            "190x190",
            "--pen",
            "0.4,black",
            "--quiet",
        ],
        env={"XDG_CONFIG_HOME": str(tmp_path / "config")},
    )
    elapsed = time.monotonic() - started_at

    assert result.exit_code == 0, result.output
    assert output.exists()
    assert elapsed < CI_BUDGET_S, (
        f"convert took {elapsed:.2f} s, over the {CI_BUDGET_S:.0f} s CI bound; "
        "the 30 s VPS budget is checked by tests/benchmarks/benchmark_convert.py"
    )
