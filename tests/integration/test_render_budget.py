"""End-to-end use of the shared render size and pixel budget from the public API."""

from __future__ import annotations

import pytest

from penpath.core import (
    MAX_RENDER_MEGAPIXELS,
    PenStroke,
    check_render_budget,
    render_size_px,
    simulate_plot,
)


def test_render_budget_guards_a_real_a5_simulate_plot_flow() -> None:
    """A caller sizes, budgets and renders a page with one shared rounding rule."""
    width_mm, height_mm = 148.0, 210.0
    px_per_mm = 3.0
    size = render_size_px(width_mm, height_mm, px_per_mm)
    assert size == (444, 630)

    check_render_budget(*size)
    stroke = PenStroke([(10.0, 10.0), (40.0, 10.0)], 0.4, "#000000")
    image = simulate_plot([stroke], width_mm, height_mm, dpi_px_per_mm=px_per_mm)

    assert image.size == size
    assert any(pixel != (255, 255, 255) for pixel in image.getdata())


def test_render_budget_refuses_old_50_px_per_mm_before_allocating() -> None:
    """The old 50 px/mm preview setting is refused before a render is attempted."""
    assert MAX_RENDER_MEGAPIXELS == 40.0
    size = render_size_px(148.0, 210.0, 50.0)
    assert size == (7400, 10500)

    with pytest.raises(ValueError, match=r"renders 7400x10500 px \(77\.7 MP\)"):
        check_render_budget(*size)
