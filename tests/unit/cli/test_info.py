"""Unit tests for the ``penpath info`` PFM output helpers."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from penpath.cli.commands.info import (
    PFM_TABLE_WIDTH,
    _fold_cell,
    _format_margin_mm,
    _print_pfms_table,
    _setting_default,
)


def test_format_margin_mm_uniform_value_has_no_decimals() -> None:
    assert _format_margin_mm(10.0) == "10"


def test_format_margin_mm_per_side_uses_top_right_bottom_left_order() -> None:
    assert _format_margin_mm((10.0, 5.0, 10.0, 5.0)) == "10/5/10/5"
    assert _format_margin_mm([1.0, 2.0, 3.0, 4.0]) == "1/2/3/4"


def test_format_margin_mm_zero_is_visible() -> None:
    assert _format_margin_mm(0.0) == "0"


def test_fold_cell_keeps_long_preset_ids_whole() -> None:
    text = "sketch_lines:bold, sketch_lines:hatch_horizontal, sketch_lines:fine"
    folded = _fold_cell(text, 30)
    assert "sketch_lines:hatch_horizontal" in folded
    assert all(len(line) <= 30 for line in folded.splitlines())


def test_setting_default_shows_dash_for_required_fields() -> None:
    class RequiredSettings(BaseModel):
        required_value: int

    field = RequiredSettings.model_fields["required_value"]
    assert _setting_default(field) == "-"


def test_setting_default_shows_none_and_actual_values() -> None:
    class OptionalSettings(BaseModel):
        unset: int | None = None
        count: int = 4

    assert _setting_default(OptionalSettings.model_fields["unset"]) is None
    assert _setting_default(OptionalSettings.model_fields["count"]) == 4


def test_print_pfms_table_has_only_name_description_and_preset_ids(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rows: list[dict[str, Any]] = [
        {
            "name": "contour",
            "description": "Trace clean vector outlines from thresholded greyscale levels",
            "preset_ids": ["contour:portrait", "contour:silhouette"],
            "default_settings": {"levels": 1},
        }
    ]
    _print_pfms_table(rows)
    output = capsys.readouterr().out
    for column in ("Name", "Description", "Preset ids"):
        assert column in output
    for hidden in ("default_settings", "settings_model", "{"):
        assert hidden not in output
    assert "contour:portrait" in output
    assert max(len(line) for line in output.splitlines()) <= PFM_TABLE_WIDTH
