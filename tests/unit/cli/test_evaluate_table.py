"""Unit tests for the ``penpath evaluate`` machine-cost table."""

from __future__ import annotations

from typing import cast

from rich.console import Console

from penpath.cli.commands.evaluate import _cost_table
from penpath.core.simulation import LayerMetrics, MachineCostResult


def _cost_result() -> MachineCostResult:
    layer = cast(
        LayerMetrics,
        {
            "drawing_length_mm": 8254.45,
            "pen_up_travel_mm": 742.67,
            "num_lifts": 21,
            "num_short_segments": 0,
            "num_strokes": 22,
            "ink_coverage_pct": 6.2,
        },
    )
    cast(dict[str, object], layer)["pen"] = "stabilo_88_light_blue"
    total: LayerMetrics = {
        "drawing_length_mm": 11475.02,
        "pen_up_travel_mm": 960.37,
        "num_lifts": 29,
        "num_short_segments": 0,
        "num_strokes": 30,
        "ink_coverage_pct": 8.2,
    }
    return {"per_layer": {"#8CCFE8": layer}, "total": total}


def test_cost_table_headers_are_short() -> None:
    table = _cost_table(_cost_result())

    assert [column.header for column in table.columns] == [
        "Layer",
        "Pen",
        "Draw mm",
        "Travel mm",
        "Lifts",
        "Short",
        "Strokes",
        "Ink %",
    ]


def test_cost_table_fits_80_columns_without_truncating() -> None:
    console = Console(width=80, force_terminal=False, color_system=None)
    with console.capture() as capture:
        console.print(_cost_table(_cost_result()))
    rendered = capture.get()

    assert "…" not in rendered
    assert max(len(line) for line in rendered.splitlines()) <= 80
    assert "stabilo_88_light_blue" in rendered
    assert "11475.02" in rendered
