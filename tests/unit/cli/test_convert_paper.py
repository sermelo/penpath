"""Unit tests for paper and margin resolution in the convert command."""

from __future__ import annotations

import click
import pytest

from penpath.cli.commands.convert import (
    _check_drawable_area,
    _parse_margin_parts,
    _resolve_paper,
)
from penpath.cli.config import Config
from penpath.core.models import Paper


class TestParseMarginParts:
    """One margin means all sides; four are top,right,bottom,left."""

    def test_single_margin_applies_to_all_sides(self) -> None:
        assert _parse_margin_parts(["12.5"], "--margin") == 12.5

    def test_four_margins_keep_their_side_order(self) -> None:
        assert _parse_margin_parts(["20", "5", "20", "5"], "--margin") == (20.0, 5.0, 20.0, 5.0)

    @pytest.mark.parametrize("spec", [["1", "2"], ["1", "2", "3"], ["1", "2", "3", "4", "5"]])
    def test_wrong_number_of_values_names_the_order(self, spec: list[str]) -> None:
        with pytest.raises(click.BadParameter) as excinfo:
            _parse_margin_parts(spec, "--margin")
        assert "top,right,bottom,left" in str(excinfo.value.message)

    @pytest.mark.parametrize("spec", [["-1"], ["5,-1,5,5"], ["nan"], ["inf"], ["abc"]])
    def test_invalid_values_are_rejected(self, spec: list[str]) -> None:
        with pytest.raises(click.BadParameter) as excinfo:
            _parse_margin_parts(spec, "--margin")
        assert excinfo.value.param_hint == "--margin"


class TestResolvePaperInlineMargins:
    """Inline papers no longer average per-side margins."""

    def test_no_margin_keeps_the_ten_millimetre_default(self) -> None:
        paper = _resolve_paper("190x190", Config())
        assert paper.width_mm == 190.0
        assert paper.margin_mm == 10.0

    def test_one_margin_is_a_scalar(self) -> None:
        paper = _resolve_paper("190x190,5", Config())
        assert paper.margin_mm == 5.0

    def test_four_margins_are_kept_per_side(self) -> None:
        paper = _resolve_paper("190x190,20,5,20,5", Config())
        assert paper.margins_mm == (20.0, 5.0, 20.0, 5.0)
        assert paper.drawable_origin_mm == (5.0, 20.0)
        assert paper.drawable_width_mm == 180.0
        assert paper.drawable_height_mm == 150.0

    @pytest.mark.parametrize(
        "spec",
        ["190x190,1,2", "190x190,1,2,3,4,5", "190x190,-1", "190x190,nan", "190x190,abc"],
    )
    def test_invalid_inline_margins_are_rejected(self, spec: str) -> None:
        with pytest.raises(click.BadParameter) as excinfo:
            _resolve_paper(spec, Config())
        assert excinfo.value.param_hint == "--paper"

    def test_builtin_preset_is_unchanged(self) -> None:
        paper = _resolve_paper("a4", Config())
        assert (paper.width_mm, paper.height_mm, paper.margin_mm) == (210.0, 297.0, 10.0)


class TestDrawableAreaCheck:
    """A margin that leaves no room to draw fails with a fix to apply."""

    def test_zero_sized_drawable_area_is_rejected(self) -> None:
        paper = Paper(name="tiny", width_mm=50, height_mm=50, margin_mm=(30, 5, 30, 5))
        with pytest.raises(click.BadParameter) as excinfo:
            _check_drawable_area(paper, "--margin")
        message = str(excinfo.value.message)
        assert "no drawable area" in message
        assert "reduce the margin or use a larger paper" in message
        assert excinfo.value.param_hint == "--margin"

    def test_usable_paper_passes(self) -> None:
        paper = Paper(name="square", width_mm=190, height_mm=190, margin_mm=(20, 5, 20, 5))
        _check_drawable_area(paper, "--paper")
