"""Unit tests for working-resolution planning and application."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from PIL import Image

from penpath.core.image.resolution import (
    MAX_WORKING_LONGEST_PX,
    MIN_WORKING_LONGEST_PX,
    WorkingResolution,
    apply_working_resolution,
    plan_working_resolution,
)
from penpath.core.models import Paper


def _paper(width_mm: float = 190.0, height_mm: float = 190.0) -> Paper:
    return Paper(name="square", width_mm=width_mm, height_mm=height_mm)


class TestPlanWorkingResolution:
    def test_formula_uses_paper_longest_side_and_pen_width(self) -> None:
        resolution = plan_working_resolution((4080, 3072), _paper(190, 190), 0.4)

        assert resolution.working_px == 475
        assert resolution.target_size_px == (475, 358)
        assert resolution.scale == pytest.approx(475 / 4080)
        assert resolution.source_size_px == (4080, 3072)
        assert resolution.paper_side_mm == 190.0
        assert resolution.pen_width_mm == 0.4

    @pytest.mark.parametrize(
        ("paper_width", "paper_height", "pen_width", "expected"),
        [
            (210.0, 297.0, 0.3, 990),
            (210.0, 297.0, 0.8, 371),
        ],
    )
    def test_formula_for_a4_paper(
        self, paper_width: float, paper_height: float, pen_width: float, expected: int
    ) -> None:
        resolution = plan_working_resolution(
            (4000, 3000), _paper(paper_width, paper_height), pen_width
        )

        assert resolution.working_px == expected

    def test_derived_value_clamped_to_minimum(self) -> None:
        resolution = plan_working_resolution((4000, 3000), _paper(210, 297), 100.0)

        assert resolution.working_px == MIN_WORKING_LONGEST_PX

    def test_derived_value_clamped_to_maximum(self) -> None:
        resolution = plan_working_resolution((4000, 3000), _paper(210, 297), 0.001)

        assert resolution.working_px == MAX_WORKING_LONGEST_PX

    def test_small_source_is_never_enlarged(self) -> None:
        resolution = plan_working_resolution((200, 150), _paper(210, 297), 0.3)

        assert resolution.target_size_px == (200, 150)
        assert resolution.scale == 1.0
        assert resolution.working_px == 990

    def test_aspect_ratio_preserved_for_portrait_image(self) -> None:
        resolution = plan_working_resolution((3000, 4000), _paper(190, 190), 0.4)

        assert resolution.target_size_px == (356, 475)

    def test_rounds_both_sides_to_whole_pixels(self) -> None:
        resolution = plan_working_resolution((1001, 777), _paper(190, 190), 0.4)

        assert all(isinstance(side, int) for side in resolution.target_size_px)

    def test_max_resolution_replaces_derived_value(self) -> None:
        resolution = plan_working_resolution(
            (4080, 3072), _paper(190, 190), 0.4, max_longest_px=800
        )

        assert resolution.working_px == 800
        assert resolution.target_size_px == (800, 602)

    def test_max_resolution_is_not_clamped(self) -> None:
        resolution = plan_working_resolution((4080, 3072), _paper(190, 190), 0.4, max_longest_px=64)

        assert resolution.working_px == 64
        assert resolution.target_size_px == (64, 48)

    def test_max_resolution_never_enlarges(self) -> None:
        resolution = plan_working_resolution((200, 150), _paper(190, 190), 0.4, max_longest_px=800)

        assert resolution.target_size_px == (200, 150)
        assert resolution.scale == 1.0

    @pytest.mark.parametrize(
        ("image_size", "pen_width", "override"),
        [
            ((0, 100), 0.4, None),
            ((100, -1), 0.4, None),
            ((100, 100), 0.0, None),
            ((100, 100), -0.4, None),
            ((100, 100), 0.4, 0),
            ((100, 100), 0.4, -5),
        ],
    )
    def test_invalid_inputs_raise(
        self,
        image_size: tuple[int, int],
        pen_width: float,
        override: int | None,
    ) -> None:
        with pytest.raises(ValueError):
            plan_working_resolution(image_size, _paper(), pen_width, max_longest_px=override)

    def test_result_is_frozen(self) -> None:
        resolution = plan_working_resolution((300, 200), _paper(), 0.4)

        with pytest.raises(FrozenInstanceError):
            resolution.working_px = 100  # type: ignore[misc]

    def test_public_dataclass_can_be_built_directly(self) -> None:
        resolution = WorkingResolution(
            source_size_px=(200, 150),
            target_size_px=(64, 48),
            scale=0.32,
            working_px=64,
            paper_side_mm=190.0,
            pen_width_mm=0.4,
        )

        assert resolution.target_size_px == (64, 48)


class TestApplyWorkingResolution:
    def test_downscale_preserves_mode_and_size(self) -> None:
        image = Image.new("RGB", (200, 100), "white")
        resolution = plan_working_resolution((200, 100), _paper(), 0.4, max_longest_px=100)

        working = apply_working_resolution(image, resolution)

        assert working.size == (100, 50)
        assert working.mode == "RGB"
        assert working is not image

    def test_grayscale_mode_is_preserved(self) -> None:
        image = Image.new("L", (200, 100), 0)
        resolution = plan_working_resolution((200, 100), _paper(), 0.4, max_longest_px=100)

        assert apply_working_resolution(image, resolution).mode == "L"

    def test_uses_lanczos_resampling(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[object] = []
        original_resize = Image.Image.resize

        def spy_resize(
            self: Image.Image,
            size: tuple[int, int],
            resample: object = None,
            **kwargs: object,
        ) -> Image.Image:
            seen.append(resample)
            return original_resize(self, size, resample, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(Image.Image, "resize", spy_resize)
        image = Image.new("RGB", (200, 100), "white")
        resolution = plan_working_resolution((200, 100), _paper(), 0.4, max_longest_px=100)

        apply_working_resolution(image, resolution)

        assert seen == [Image.Resampling.LANCZOS]

    def test_small_source_is_returned_unchanged(self) -> None:
        image = Image.new("L", (100, 50), 0)
        resolution = plan_working_resolution((100, 50), _paper(), 0.4)

        working = apply_working_resolution(image, resolution)

        assert working is image
        assert working.size == (100, 50)
