"""Unit tests for penpath.core.image.pipeline."""

import pytest
from PIL import Image

from penpath.core.image.pipeline import (
    FilterPipeline,
    FilterStep,
    get_filter,
    list_filters,
)


class TestFilterRegistry:
    """Tests for filter registry functions."""

    def test_list_filters_returns_all_filters(self) -> None:
        """Test list_filters returns all registered filter names."""
        filters = list_filters()
        expected = [
            "box_blur",
            "brightness",
            "contrast",
            "gamma",
            "gaussian_blur",
            "grayscale",
            "invert",
            "posterize",
            "threshold",
        ]
        assert filters == expected

    def test_get_filter_returns_correct_function(self) -> None:
        """Test get_filter returns the correct filter function."""
        from penpath.core.image.filters import grayscale, threshold

        assert get_filter("grayscale") is grayscale
        assert get_filter("threshold") is threshold

    def test_get_filter_invalid_name_raises(self) -> None:
        """Test get_filter raises for unknown filter name."""
        with pytest.raises(ValueError, match="Unknown filter"):
            get_filter("nonexistent_filter")

    def test_get_filter_error_message_lists_available(self) -> None:
        """Test get_filter error message includes available filters."""
        with pytest.raises(ValueError) as exc_info:
            get_filter("bad_name")
        assert "grayscale" in str(exc_info.value)
        assert "threshold" in str(exc_info.value)


class TestFilterStep:
    """Tests for FilterStep dataclass."""

    def test_filter_step_creation(self) -> None:
        """Test creating a FilterStep with defaults."""
        step = FilterStep(name="grayscale", kwargs={"method": "luminance"})
        assert step.name == "grayscale"
        assert step.kwargs == {"method": "luminance"}
        assert step.enabled is True

    def test_filter_step_disabled(self) -> None:
        """Test creating a disabled FilterStep."""
        step = FilterStep(name="invert", kwargs={}, enabled=False)
        assert step.enabled is False


class TestFilterPipelineBasics:
    """Tests for basic FilterPipeline operations."""

    def test_empty_pipeline(self) -> None:
        """Test empty pipeline creation."""
        pipeline = FilterPipeline()
        assert len(pipeline) == 0
        assert list(pipeline) == []

    def test_add_step_returns_index(self) -> None:
        """Test add_step returns the index of added step."""
        pipeline = FilterPipeline()
        idx = pipeline.add_step("grayscale", method="luminance")
        assert idx == 0
        assert len(pipeline) == 1

    def test_add_step_invalid_filter_raises(self) -> None:
        """Test add_step raises for unknown filter."""
        pipeline = FilterPipeline()
        with pytest.raises(ValueError, match="Unknown filter"):
            pipeline.add_step("nonexistent")

    def test_add_multiple_steps(self) -> None:
        """Test adding multiple steps preserves order."""
        pipeline = FilterPipeline()
        pipeline.add_step("grayscale")
        pipeline.add_step("invert")
        pipeline.add_step("threshold", level=128)
        assert len(pipeline) == 3
        assert pipeline[0].name == "grayscale"
        assert pipeline[1].name == "invert"
        assert pipeline[2].name == "threshold"

    def test_remove_step(self) -> None:
        """Test removing a step by index."""
        pipeline = FilterPipeline()
        pipeline.add_step("grayscale")
        pipeline.add_step("invert")
        pipeline.add_step("threshold", level=128)
        pipeline.remove_step(1)  # Remove invert
        assert len(pipeline) == 2
        assert pipeline[0].name == "grayscale"
        assert pipeline[1].name == "threshold"

    def test_remove_step_invalid_index_raises(self) -> None:
        """Test remove_step raises for out of range index."""
        pipeline = FilterPipeline()
        pipeline.add_step("grayscale")
        with pytest.raises(IndexError):
            pipeline.remove_step(1)
        with pytest.raises(IndexError):
            pipeline.remove_step(-1)

    def test_enable_disable_step(self) -> None:
        """Test enabling and disabling steps."""
        pipeline = FilterPipeline()
        pipeline.add_step("grayscale")
        pipeline.add_step("invert")

        pipeline.disable_step(0)
        assert pipeline[0].enabled is False
        assert pipeline[1].enabled is True

        pipeline.enable_step(0)
        assert pipeline[0].enabled is True

    def test_enable_disable_invalid_index_raises(self) -> None:
        """Test enable/disable raise for out of range index."""
        pipeline = FilterPipeline()
        pipeline.add_step("grayscale")
        with pytest.raises(IndexError):
            pipeline.disable_step(1)
        with pytest.raises(IndexError):
            pipeline.enable_step(-1)

    def test_reorder_step(self) -> None:
        """Test reordering steps."""
        pipeline = FilterPipeline()
        pipeline.add_step("grayscale")  # 0
        pipeline.add_step("contrast", factor=1.5)  # 1
        pipeline.add_step("invert")  # 2

        pipeline.reorder(2, 0)  # Move invert to front
        assert pipeline[0].name == "invert"
        assert pipeline[1].name == "grayscale"
        assert pipeline[2].name == "contrast"

    def test_reorder_invalid_indices_raise(self) -> None:
        """Test reorder raises for out of range indices."""
        pipeline = FilterPipeline()
        pipeline.add_step("grayscale")
        with pytest.raises(IndexError):
            pipeline.reorder(1, 0)
        with pytest.raises(IndexError):
            pipeline.reorder(0, 1)
        with pytest.raises(IndexError):
            pipeline.reorder(-1, 0)


class TestFilterPipelineApply:
    """Tests for FilterPipeline.apply() method."""

    def test_apply_empty_pipeline_returns_same_image(self) -> None:
        """Test empty pipeline returns copy of input."""
        pipeline = FilterPipeline()
        img = Image.new("RGB", (100, 100), color="red")
        result = pipeline.apply(img)
        assert result is not img
        assert list(result.getdata()) == list(img.getdata())

    def test_apply_single_filter(self) -> None:
        """Test applying a single filter."""
        pipeline = FilterPipeline()
        pipeline.add_step("grayscale", method="luminance")
        img = Image.new("RGB", (100, 100), color=(255, 128, 64))
        result = pipeline.apply(img)
        assert result.mode == "L"

    def test_apply_multiple_filters_in_order(self) -> None:
        """Test filters are applied in order."""
        pipeline = FilterPipeline()
        pipeline.add_step("grayscale")
        pipeline.add_step("invert")
        img = Image.new("RGB", (10, 10), color=(255, 0, 0))  # Red
        result = pipeline.apply(img)
        # Red -> grayscale (luminance ~76) -> invert (~179)
        assert result.mode == "L"
        assert result.getpixel((0, 0)) == 255 - 76  # 179

    def test_apply_skips_disabled_steps(self) -> None:
        """Test disabled steps are skipped."""
        pipeline = FilterPipeline()
        pipeline.add_step("grayscale")
        pipeline.add_step("invert")
        pipeline.disable_step(0)  # Disable grayscale
        img = Image.new("RGB", (10, 10), color=(255, 0, 0))
        result = pipeline.apply(img)
        # Should only invert (RGB -> RGB inverted)
        assert result.mode == "RGB"
        assert result.getpixel((0, 0)) == (0, 255, 255)

    def test_apply_with_filter_kwargs(self) -> None:
        """Test filter kwargs are passed correctly."""
        pipeline = FilterPipeline()
        pipeline.add_step("threshold", level=200, dither="none")
        img = Image.new("L", (10, 10), color=150)
        result = pipeline.apply(img)
        # Level 200, pixel 150 -> 0 (black)
        assert all(p == 0 for p in result.getdata())

    def test_apply_complex_chain(self) -> None:
        """Test a complex filter chain."""
        pipeline = FilterPipeline()
        pipeline.add_step("grayscale", method="luminance")
        pipeline.add_step("gaussian_blur", radius=1.0)
        pipeline.add_step("contrast", factor=1.5)
        pipeline.add_step("brightness", factor=1.1)
        pipeline.add_step("gamma", gamma=0.9)
        pipeline.add_step("threshold", level=128, dither="floyd_steinberg")

        img = Image.new("RGB", (200, 200), color=(200, 100, 50))
        result = pipeline.apply(img)
        assert result.mode == "L"
        assert all(p in (0, 255) for p in result.getdata())


class TestFilterPipelineSerialization:
    """Tests for FilterPipeline.to_dict() and from_dict()."""

    def test_to_dict_empty_pipeline(self) -> None:
        """Test serializing empty pipeline."""
        pipeline = FilterPipeline()
        data = pipeline.to_dict()
        assert data == {"steps": []}

    def test_to_dict_with_steps(self) -> None:
        """Test serializing pipeline with steps."""
        pipeline = FilterPipeline()
        pipeline.add_step("grayscale", method="luminance")
        pipeline.add_step("threshold", level=128, dither="floyd_steinberg")
        pipeline.disable_step(0)

        data = pipeline.to_dict()
        assert "steps" in data
        assert len(data["steps"]) == 2
        assert data["steps"][0] == {
            "name": "grayscale",
            "kwargs": {"method": "luminance"},
            "enabled": False,
        }
        assert data["steps"][1] == {
            "name": "threshold",
            "kwargs": {"level": 128, "dither": "floyd_steinberg"},
            "enabled": True,
        }

    def test_from_dict_empty(self) -> None:
        """Test deserializing empty pipeline."""
        data = {"steps": []}
        pipeline = FilterPipeline.from_dict(data)
        assert len(pipeline) == 0

    def test_from_dict_with_steps(self) -> None:
        """Test deserializing pipeline with steps."""
        data = {
            "steps": [
                {"name": "grayscale", "kwargs": {"method": "average"}, "enabled": True},
                {"name": "invert", "kwargs": {}, "enabled": False},
            ]
        }
        pipeline = FilterPipeline.from_dict(data)
        assert len(pipeline) == 2
        assert pipeline[0].name == "grayscale"
        assert pipeline[0].kwargs == {"method": "average"}
        assert pipeline[0].enabled is True
        assert pipeline[1].name == "invert"
        assert pipeline[1].enabled is False

    def test_round_trip_serialization(self) -> None:
        """Test round-trip serialization preserves pipeline."""
        pipeline = FilterPipeline()
        pipeline.add_step("grayscale", method="lightness")
        pipeline.add_step("gaussian_blur", radius=2.0)
        pipeline.add_step("contrast", factor=1.2)
        pipeline.disable_step(1)

        data = pipeline.to_dict()
        restored = FilterPipeline.from_dict(data)

        assert len(restored) == len(pipeline)
        for orig, rest in zip(pipeline, restored, strict=True):
            assert orig.name == rest.name
            assert orig.kwargs == rest.kwargs
            assert orig.enabled == rest.enabled

    def test_from_dict_invalid_step_format_raises(self) -> None:
        """Test from_dict raises for invalid step format."""
        data = {"steps": [{"name": "grayscale"}, "not_a_dict"]}
        with pytest.raises(ValueError, match="Each step must be a dictionary"):
            FilterPipeline.from_dict(data)

    def test_from_dict_missing_name_raises(self) -> None:
        """Test from_dict raises for missing step name."""
        data = {"steps": [{"kwargs": {}}]}
        with pytest.raises(ValueError, match="missing 'name'"):
            FilterPipeline.from_dict(data)

    def test_from_dict_unknown_filter_raises(self) -> None:
        """Test from_dict raises for unknown filter name."""
        data = {"steps": [{"name": "nonexistent", "kwargs": {}}]}
        with pytest.raises(ValueError, match="Unknown filter"):
            FilterPipeline.from_dict(data)


class TestFilterPipelineRepr:
    """Tests for FilterPipeline.__repr__."""

    def test_repr_empty(self) -> None:
        """Test repr of empty pipeline."""
        pipeline = FilterPipeline()
        assert repr(pipeline) == "FilterPipeline([])"

    def test_repr_with_steps(self) -> None:
        """Test repr with steps."""
        pipeline = FilterPipeline()
        pipeline.add_step("grayscale", method="luminance")
        pipeline.add_step("threshold", level=128)
        pipeline.disable_step(0)
        r = repr(pipeline)
        assert "grayscale" in r
        assert "threshold" in r
        assert "disabled" in r


class TestFilterPipelineIteration:
    """Tests for FilterPipeline iteration and indexing."""

    def test_iteration(self) -> None:
        """Test iterating over pipeline steps."""
        pipeline = FilterPipeline()
        pipeline.add_step("grayscale")
        pipeline.add_step("invert")
        steps = list(pipeline)
        assert len(steps) == 2
        assert steps[0].name == "grayscale"
        assert steps[1].name == "invert"

    def test_indexing(self) -> None:
        """Test indexing into pipeline."""
        pipeline = FilterPipeline()
        pipeline.add_step("grayscale")
        pipeline.add_step("invert")
        assert pipeline[0].name == "grayscale"
        assert pipeline[1].name == "invert"

    def test_indexing_out_of_range_raises(self) -> None:
        """Test indexing out of range raises."""
        pipeline = FilterPipeline()
        pipeline.add_step("grayscale")
        with pytest.raises(IndexError):
            _ = pipeline[1]


class TestFilterPipelineWithRealFilters:
    """Tests using actual filter implementations from filters.py."""

    def test_grayscale_threshold_chain(self) -> None:
        """Test grayscale -> threshold chain."""
        pipeline = FilterPipeline()
        pipeline.add_step("grayscale", method="luminance")
        pipeline.add_step("threshold", level=128, dither="none")

        img = Image.new("RGB", (100, 100), color=(200, 100, 50))
        result = pipeline.apply(img)
        assert result.mode == "L"
        assert all(p in (0, 255) for p in result.getdata())

    def test_grayscale_posterize_chain(self) -> None:
        """Test grayscale -> posterize chain."""
        pipeline = FilterPipeline()
        pipeline.add_step("grayscale", method="average")
        pipeline.add_step("posterize", levels=4, dither="none")

        img = Image.new("RGB", (100, 100), color=(200, 100, 50))
        result = pipeline.apply(img)
        assert result.mode == "L"
        assert len(set(result.getdata())) <= 4

    def test_blur_contrast_chain(self) -> None:
        """Test blur -> contrast chain."""
        pipeline = FilterPipeline()
        pipeline.add_step("gaussian_blur", radius=2.0)
        pipeline.add_step("contrast", factor=2.0)

        img = Image.new("RGB", (100, 100), color=(128, 128, 128))
        result = pipeline.apply(img)
        assert result.size == (100, 100)
        assert result.mode == "RGB"

    def test_invert_twice_returns_original(self) -> None:
        """Test invert -> invert returns original."""
        pipeline = FilterPipeline()
        pipeline.add_step("invert")
        pipeline.add_step("invert")

        img = Image.new("RGB", (10, 10), color=(255, 128, 64))
        result = pipeline.apply(img)
        assert list(result.getdata()) == list(img.getdata())

    def test_all_filters_in_pipeline(self) -> None:
        """Test pipeline with all available filters."""
        pipeline = FilterPipeline()
        pipeline.add_step("grayscale", method="luminance")
        pipeline.add_step("gaussian_blur", radius=1.0)
        pipeline.add_step("box_blur", radius=1)
        pipeline.add_step("contrast", factor=1.2)
        pipeline.add_step("brightness", factor=1.1)
        pipeline.add_step("gamma", gamma=0.9)
        pipeline.add_step("posterize", levels=8, dither="ordered")
        pipeline.add_step("threshold", level=128, dither="floyd_steinberg")
        pipeline.add_step("invert")

        img = Image.new("RGB", (50, 50), color=(200, 150, 100))
        result = pipeline.apply(img)
        assert result.mode == "L"
        assert all(p in (0, 255) for p in result.getdata())


class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_reorder_same_index_noop(self) -> None:
        """Test reordering to same index is a no-op."""
        pipeline = FilterPipeline()
        pipeline.add_step("grayscale")
        pipeline.add_step("invert")
        pipeline.reorder(0, 0)
        assert pipeline[0].name == "grayscale"

    def test_remove_then_add(self) -> None:
        """Test removing and adding steps."""
        pipeline = FilterPipeline()
        pipeline.add_step("grayscale")
        pipeline.add_step("invert")
        pipeline.remove_step(0)
        pipeline.add_step("threshold", level=128)
        assert len(pipeline) == 2
        assert pipeline[0].name == "invert"
        assert pipeline[1].name == "threshold"

    def test_disable_all_steps(self) -> None:
        """Test disabling all steps."""
        pipeline = FilterPipeline()
        pipeline.add_step("grayscale")
        pipeline.add_step("invert")
        pipeline.disable_step(0)
        pipeline.disable_step(1)
        img = Image.new("RGB", (10, 10), color="red")
        result = pipeline.apply(img)
        assert list(result.getdata()) == list(img.getdata())

    def test_enable_all_steps(self) -> None:
        """Test enabling all steps after disabling."""
        pipeline = FilterPipeline()
        pipeline.add_step("grayscale")
        pipeline.add_step("invert")
        pipeline.disable_step(0)
        pipeline.disable_step(1)
        pipeline.enable_step(0)
        pipeline.enable_step(1)
        assert pipeline[0].enabled is True
        assert pipeline[1].enabled is True
