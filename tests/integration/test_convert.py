"""Integration tests for ``penpath convert`` settings and seed reproducibility."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from click.testing import CliRunner, Result
from PIL import Image

from penpath.cli.commands import convert as convert_module
from penpath.cli.main import main
from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings
from penpath.core.drawing.registry import get_pfm

if TYPE_CHECKING:
    from pydantic import BaseModel
    from shapely import LineString


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def reference_image(tmp_path: Path) -> Path:
    """A small deterministic gradient with a dark region, like a real reference."""
    image = Image.new("RGB", (200, 200), "white")
    pixels = image.load()
    for y in range(200):
        for x in range(200):
            value = int(255 * (1 - (x + y) / 400))
            if 50 < x < 150 and 50 < y < 150:
                value = int(value * 0.3)
            pixels[x, y] = (value, value, value)
    path = tmp_path / "reference.png"
    image.save(path)
    return path


def _convert(runner: CliRunner, image: Path, output: Path) -> Result:
    """Run convert as a user would, with a fixed seed and the direct SVG export."""
    return runner.invoke(
        main,
        ["convert", str(image), "-o", str(output), "-s", "seed=42", "--no-vpype"],
    )


class TestConvertSeed:
    """The seed given on the command line must reach the drawing algorithm."""

    def test_cli_seed_reaches_pfm(
        self,
        runner: CliRunner,
        reference_image: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        seen: list[SketchLinesSettings] = []
        real_get_pfm = get_pfm

        def capture_pfm(pfm_type: str) -> tuple[Callable[..., list[LineString]], type[BaseModel]]:
            pfm_fn, settings_model = real_get_pfm(pfm_type)

            def wrapped(image: object, settings: SketchLinesSettings) -> list[LineString]:
                seen.append(settings)
                return pfm_fn(image, settings)

            return wrapped, settings_model

        monkeypatch.setattr(convert_module, "get_pfm", capture_pfm)
        result = _convert(runner, reference_image, tmp_path / "seeded.svg")
        assert result.exit_code == 0, result.output
        assert len(seen) == 1
        assert seen[0].seed == 42

    def test_seed_determinism(
        self, runner: CliRunner, reference_image: Path, tmp_path: Path
    ) -> None:
        """Two runs with the same seed give the same SVG and the same scores."""
        first = tmp_path / "a.svg"
        second = tmp_path / "b.svg"

        result_a = _convert(runner, reference_image, first)
        result_b = _convert(runner, reference_image, second)
        assert result_a.exit_code == 0, result_a.output
        assert result_b.exit_code == 0, result_b.output

        assert first.exists() and second.exists()
        assert first.read_bytes() == second.read_bytes()

        eval_a = runner.invoke(main, ["evaluate", str(reference_image), str(first), "--json"])
        eval_b = runner.invoke(main, ["evaluate", str(reference_image), str(second), "--json"])
        assert eval_a.exit_code == 0, eval_a.output
        assert eval_b.exit_code == 0, eval_b.output
        assert json.loads(eval_a.stdout) == json.loads(eval_b.stdout)
