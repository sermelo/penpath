"""Unit tests for the shared preview/evaluate resolution and budget helpers."""

from __future__ import annotations

import click
import pytest

from penpath.cli.commands._resolution import enforce_render_budget, resolve_px_per_mm


def test_resolve_dpi_converts_to_px_per_mm() -> None:
    assert resolve_px_per_mm(254.0, None, 4.0) == pytest.approx(10.0)


def test_resolve_px_per_mm_keeps_value() -> None:
    assert resolve_px_per_mm(None, 4.0, 10.0) == 4.0


def test_resolve_uses_default_when_neither_flag_is_given() -> None:
    assert resolve_px_per_mm(None, None, 4.0) == 4.0


def test_resolve_rejects_both_flags_naming_them() -> None:
    with pytest.raises(click.UsageError) as exc:
        resolve_px_per_mm(100.0, 4.0, 4.0)

    assert "--dpi" in str(exc.value)
    assert "--px-per-mm" in str(exc.value)


@pytest.mark.parametrize(
    ("value", "flag"),
    [(0.0, "--px-per-mm"), (-1.0, "--px-per-mm"), (0.0, "--dpi"), (-1.0, "--dpi")],
)
def test_resolve_rejects_nonpositive_values(value: float, flag: str) -> None:
    with pytest.raises(click.BadParameter) as exc:
        if flag == "--dpi":
            resolve_px_per_mm(value, None, 4.0)
        else:
            resolve_px_per_mm(None, value, 4.0)

    assert exc.value.param_hint == flag


def test_resolve_rejects_nonfinite_value() -> None:
    with pytest.raises(click.BadParameter) as exc:
        resolve_px_per_mm(None, float("nan"), 4.0)

    assert exc.value.param_hint == "--px-per-mm"


def test_budget_allows_a_small_render() -> None:
    enforce_render_budget(148.0, 210.0, 4.0, force=False)


def test_budget_refuses_a_large_render_naming_size_limit_and_flags() -> None:
    with pytest.raises(click.ClickException) as exc:
        enforce_render_budget(148.0, 210.0, 1000.0, force=False)

    message = str(exc.value)
    assert "148000x210000 px" in message
    assert "31080.0 MP" in message
    assert "40 MP" in message
    assert "--force" in message
    assert "--px-per-mm" in message


def test_force_bypasses_only_the_budget() -> None:
    enforce_render_budget(148.0, 210.0, 1000.0, force=True)
