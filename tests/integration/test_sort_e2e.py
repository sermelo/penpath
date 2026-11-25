"""End-to-end check that ``penpath convert`` uses the optimized geometry sort."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from click.testing import CliRunner
from PIL import Image
from shapely import LineString

from penpath.cli.main import main
from penpath.core.geometry import pipeline as pipeline_module

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _travel(lines: list[LineString]) -> float:
    total = 0.0
    for i in range(len(lines) - 1):
        end = list(lines[i].coords)[-1]
        start = next(iter(lines[i + 1].coords))
        total += math.hypot(start[0] - end[0], start[1] - end[1])
    return total


def _strokes(lines: list[LineString]) -> set[tuple[tuple[float, float], ...]]:
    result = set()
    for line in lines:
        coords = tuple((float(x), float(y)) for x, y in line.coords)
        result.add(min(coords, coords[::-1]))
    return result


def test_convert_sorts_geometry_without_changing_strokes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real convert run sorts the drawing and keeps every stroke."""
    image_path = tmp_path / "input.png"
    image = Image.new("L", (120, 120), 255)
    for y in range(30, 90):
        for x in range(30, 90):
            image.putpixel((x, y), 40)
    image.save(image_path)

    seen: list[tuple[list[LineString], list[LineString]]] = []
    real_sort = pipeline_module.sort_lines

    def capture(lines, start_point=None):
        result = real_sort(lines, start_point)
        seen.append((list(lines), result))
        return result

    monkeypatch.setattr(pipeline_module, "sort_lines", capture)

    output = tmp_path / "out.svg"
    result = CliRunner().invoke(
        main,
        ["convert", str(image_path), "-o", str(output), "-s", "seed=42", "--no-vpype"],
    )

    assert result.exit_code == 0, result.output
    assert output.exists()
    assert len(seen) == 1
    unsorted, sorted_lines = seen[0]
    assert len(sorted_lines) >= 3
    assert _strokes(sorted_lines) == _strokes(unsorted)
    assert _travel(sorted_lines) <= _travel(unsorted) + 1e-9
