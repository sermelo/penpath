"""Unit tests for core models."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest
from pydantic import ValidationError

from penpath.core.models import (
    ImageRef,
    Palette,
    Paper,
    Pen,
    PFMSettings,
    Project,
    SketchLinesPFM,
)


class TestPen:
    """Tests for Pen model."""

    def test_pen_minimal(self):
        """Test creating a pen with minimal required fields."""
        pen = Pen(name="test", width_mm=0.5)
        assert pen.name == "test"
        assert pen.width_mm == 0.5
        assert pen.color == "#000000"
        assert pen.opacity == 1.0
        assert pen.pen_type == "rollerball"

    def test_pen_full(self):
        """Test creating a pen with all fields."""
        pen = Pen(
            name="fine_red",
            width_mm=0.3,
            color="#FF0000",
            opacity=0.8,
            pen_type="fountain",
        )
        assert pen.name == "fine_red"
        assert pen.width_mm == 0.3
        assert pen.color == "#FF0000"
        assert pen.opacity == 0.8
        assert pen.pen_type == "fountain"

    def test_pen_named_color(self):
        """Test pen with named CSS color."""
        pen = Pen(name="blue", width_mm=0.5, color="blue")
        assert pen.color == "blue"

    def test_pen_invalid_width_zero(self):
        """Test that zero width raises error."""
        with pytest.raises(ValidationError):
            Pen(name="test", width_mm=0.0)

    def test_pen_invalid_width_negative(self):
        """Test that negative width raises error."""
        with pytest.raises(ValidationError):
            Pen(name="test", width_mm=-0.5)

    def test_pen_invalid_width_too_large(self):
        """Test that width > 10mm raises error."""
        with pytest.raises(ValidationError):
            Pen(name="test", width_mm=15.0)

    def test_pen_invalid_opacity(self):
        """Test that opacity outside [0,1] raises error."""
        with pytest.raises(ValidationError):
            Pen(name="test", width_mm=0.5, opacity=1.5)
        with pytest.raises(ValidationError):
            Pen(name="test", width_mm=0.5, opacity=-0.1)

    def test_pen_invalid_hex_color(self):
        """Test that invalid hex color raises error."""
        with pytest.raises(Exception, match="Invalid hex color"):
            Pen(name="test", width_mm=0.5, color="#GGGGGG")

    def test_pen_invalid_hex_color_length(self):
        """Test that invalid hex color length raises error."""
        with pytest.raises(Exception, match="Hex color must be"):
            Pen(name="test", width_mm=0.5, color="#12345")

    def test_pen_to_vpype_layer_name(self):
        """Test vpype layer name generation."""
        pen = Pen(name="fine", width_mm=0.3)
        assert pen.to_vpype_layer_name() == "pen-fine"


class TestPalette:
    """Tests for the Palette model."""

    def test_palette_round_trips_in_drawing_order(self):
        palette = Palette(
            name="custom",
            pens=[
                Pen(name="first", width_mm=0.4, color="#FF0000"),
                Pen(name="second", width_mm=0.5),
            ],
        )
        restored = Palette.model_validate(palette.model_dump())
        assert restored == palette
        assert [pen.name for pen in restored.pens] == ["first", "second"]

    def test_palette_requires_at_least_one_pen(self):
        with pytest.raises(ValidationError):
            Palette(name="empty", pens=[])


class TestPaper:
    """Tests for Paper model."""

    def test_paper_minimal(self):
        """Test creating a paper with minimal required fields."""
        paper = Paper(name="a4", width_mm=210.0, height_mm=297.0)
        assert paper.name == "a4"
        assert paper.width_mm == 210.0
        assert paper.height_mm == 297.0
        assert paper.margin_mm == 10.0
        assert paper.background_color == "#FFFFFF"

    def test_paper_full(self):
        """Test creating a paper with all fields."""
        paper = Paper(
            name="custom",
            width_mm=300.0,
            height_mm=400.0,
            margin_mm=20.0,
            background_color="#F0F0F0",
        )
        assert paper.margin_mm == 20.0
        assert paper.background_color == "#F0F0F0"

    def test_paper_drawable_dimensions(self):
        """Test drawable width/height properties."""
        paper = Paper(name="a4", width_mm=210.0, height_mm=297.0, margin_mm=10.0)
        assert paper.drawable_width_mm == 190.0
        assert paper.drawable_height_mm == 277.0

    def test_paper_zero_margin(self):
        """Test paper with zero margin."""
        paper = Paper(name="borderless", width_mm=200.0, height_mm=200.0, margin_mm=0.0)
        assert paper.drawable_width_mm == 200.0
        assert paper.drawable_height_mm == 200.0

    def test_paper_invalid_dimensions(self):
        """Test that invalid dimensions raise error."""
        with pytest.raises(ValidationError):
            Paper(name="test", width_mm=0.0, height_mm=297.0)
        with pytest.raises(ValidationError):
            Paper(name="test", width_mm=210.0, height_mm=0.0)
        with pytest.raises(ValidationError):
            Paper(name="test", width_mm=210.0, height_mm=297.0, margin_mm=-5.0)

    def test_paper_to_vpype_page_size(self):
        """Test vpype page size string generation."""
        paper = Paper(name="a4", width_mm=210.0, height_mm=297.0)
        assert paper.to_vpype_page_size() == "210.0x297.0mm"


class TestImageRef:
    """Tests for ImageRef model."""

    def test_image_ref_valid(self, tmp_path):
        """Test creating ImageRef with valid path."""
        img_path = tmp_path / "test.png"
        img_path.write_bytes(b"fake png")
        from penpath.core.image.pipeline import FilterPipeline

        img_ref = ImageRef(path=img_path, filters=FilterPipeline(), dpi=300)
        assert img_ref.path == img_path
        assert img_ref.dpi == 300
        assert img_ref.auto_equalize is True

    def test_image_ref_auto_equalize_can_be_disabled(self, tmp_path):
        """A project can keep its original tonal range explicitly."""
        img_path = tmp_path / "test.png"
        img_path.write_bytes(b"fake png")
        from penpath.core.image.pipeline import FilterPipeline

        img_ref = ImageRef(path=img_path, filters=FilterPipeline(), dpi=300, auto_equalize=False)
        assert img_ref.auto_equalize is False

    def test_image_ref_missing_file(self):
        """Test that missing file raises error."""
        from penpath.core.image.pipeline import FilterPipeline

        with pytest.raises(Exception, match="not found"):
            ImageRef(path=Path("/nonexistent.png"), filters=FilterPipeline())

    def test_image_ref_directory(self, tmp_path):
        """Test that directory path raises error."""
        from penpath.core.image.pipeline import FilterPipeline

        with pytest.raises(Exception, match="not a file"):
            ImageRef(path=tmp_path, filters=FilterPipeline())


class TestPFMSettings:
    """Tests for PFMSettings base model."""

    def test_pfm_settings_base(self):
        """Test base PFM settings."""
        settings = PFMSettings(pfm_type="sketch_lines")
        assert settings.pfm_type == "sketch_lines"

    def test_pfm_settings_get_model(self):
        """Test getting the settings model class."""
        settings = PFMSettings(pfm_type="sketch_lines")
        model_class = settings.get_settings_model()
        assert model_class.__name__ == "SketchLinesSettings"

    def test_to_typed_settings_uses_nested_payload(self):
        """Nested PFM settings (including the seed) reach the settings model."""
        from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings

        pfm = SketchLinesPFM(settings=SketchLinesSettings(seed=42, line_density=2.0))
        typed = pfm.to_typed_settings()
        assert isinstance(typed, SketchLinesSettings)
        assert typed.seed == 42
        assert typed.line_density == 2.0

    def test_to_typed_settings_keeps_flat_layout(self):
        """A flat PFM layout still passes its fields to the settings model."""
        from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings

        class FlatSketchPFM(PFMSettings):
            pfm_type: Literal["sketch_lines"] = "sketch_lines"
            seed: int | None = None
            line_density: float = 1.0

        typed = FlatSketchPFM(seed=42, line_density=2.0).to_typed_settings()
        assert isinstance(typed, SketchLinesSettings)
        assert typed.seed == 42
        assert typed.line_density == 2.0


class TestSketchLinesPFM:
    """Tests for SketchLinesPFM model."""

    def test_sketch_lines_pfm_default(self):
        """Test SketchLinesPFM with default settings."""
        pfm = SketchLinesPFM()
        assert pfm.pfm_type == "sketch_lines"
        assert pfm.settings.line_density == 0.75
        assert pfm.settings.min_length == 2.0

    def test_sketch_lines_pfm_custom(self):
        """Test SketchLinesPFM with custom settings."""
        from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings

        custom = SketchLinesSettings(line_density=2.0, min_length=5.0)
        pfm = SketchLinesPFM(settings=custom)
        assert pfm.settings.line_density == 2.0
        assert pfm.settings.min_length == 5.0

    def test_to_typed_settings_default_seed_is_none(self):
        """No seed on the command line means no determinism promise."""
        from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings

        typed = SketchLinesPFM().to_typed_settings()
        assert isinstance(typed, SketchLinesSettings)
        assert typed.seed is None


def _project_kwargs(tmp_path: Path) -> dict[str, object]:
    from penpath.core.image.pipeline import FilterPipeline

    img_path = tmp_path / "input.png"
    img_path.write_bytes(b"fake png")
    return {
        "image": ImageRef(path=img_path, filters=FilterPipeline(), dpi=300),
        "paper": Paper(name="a4", width_mm=210.0, height_mm=297.0),
        "pfm": SketchLinesPFM(),
        "output_path": tmp_path / "output.svg",
    }


class TestProject:
    """Tests for Project model."""

    def test_project_minimal(self, tmp_path):
        """Test creating a minimal project."""
        img_path = tmp_path / "input.png"
        img_path.write_bytes(b"fake png")
        out_path = tmp_path / "output.svg"

        from penpath.core.image.pipeline import FilterPipeline

        project = Project(
            image=ImageRef(path=img_path, filters=FilterPipeline(), dpi=300),
            paper=Paper(name="a4", width_mm=210.0, height_mm=297.0),
            pen=Pen(name="fine", width_mm=0.3),
            pfm=SketchLinesPFM(),
            output_path=out_path,
        )
        assert project.image.path == img_path
        assert project.output_path == out_path

    def test_project_invalid_output_extension(self, tmp_path):
        """Test that non-.svg output raises error."""
        img_path = tmp_path / "input.png"
        img_path.write_bytes(b"fake png")
        out_path = tmp_path / "output.png"

        from penpath.core.image.pipeline import FilterPipeline

        with pytest.raises(ValidationError, match=r"must have \.svg extension"):
            Project(
                image=ImageRef(path=img_path, filters=FilterPipeline(), dpi=300),
                paper=Paper(name="a4", width_mm=210.0, height_mm=297.0),
                pen=Pen(name="fine", width_mm=0.3),
                pfm=SketchLinesPFM(),
                output_path=out_path,
            )

    def test_project_model_dump_for_vpype(self, tmp_path):
        """Test model_dump_for_vpype method."""
        img_path = tmp_path / "input.png"
        img_path.write_bytes(b"fake png")
        out_path = tmp_path / "output.svg"

        from penpath.core.image.pipeline import FilterPipeline

        project = Project(
            image=ImageRef(path=img_path, filters=FilterPipeline(), dpi=300),
            paper=Paper(name="a4", width_mm=210.0, height_mm=297.0),
            pen=Pen(name="fine", width_mm=0.3, color="#FF0000", opacity=0.8),
            pfm=SketchLinesPFM(),
            output_path=out_path,
        )
        vpype_data = project.model_dump_for_vpype()
        assert vpype_data["page_size"] == "210.0x297.0mm"
        assert vpype_data["layer_name"] == "pen-fine"
        assert vpype_data["pen_width_mm"] == 0.3
        assert vpype_data["pen_color"] == "#FF0000"
        assert vpype_data["pen_opacity"] == 0.8

    def test_palette_returns_pens_in_given_order(self, tmp_path):
        """An explicit pen list is the effective palette, in order."""
        pens = [Pen(name="first", width_mm=0.4), Pen(name="second", width_mm=0.4)]
        project = Project(**_project_kwargs(tmp_path), pen=None, pens=pens)
        assert [pen.name for pen in project.palette] == ["first", "second"]

    def test_palette_falls_back_to_single_pen(self, tmp_path):
        """Old-style projects still expose one effective pen."""
        pen = Pen(name="fine", width_mm=0.3)
        project = Project(**_project_kwargs(tmp_path), pen=pen)
        assert project.palette == [pen]

    def test_pen_and_pens_are_mutually_exclusive(self, tmp_path):
        with pytest.raises(ValidationError, match="both 'pen' and 'pens'"):
            Project(
                **_project_kwargs(tmp_path),
                pen=Pen(name="fine", width_mm=0.3),
                pens=[Pen(name="other", width_mm=0.4)],
            )

    def test_project_requires_a_pen_or_pens(self, tmp_path):
        with pytest.raises(ValidationError, match=r"either 'pen' or 'pens'"):
            Project(**_project_kwargs(tmp_path))

    def test_model_dump_for_vpype_uses_first_palette_pen(self, tmp_path):
        pens = [
            Pen(name="first", width_mm=0.4, color="#FF0000"),
            Pen(name="second", width_mm=0.4, color="#0000FF"),
        ]
        project = Project(**_project_kwargs(tmp_path), pen=None, pens=pens)
        data = project.model_dump_for_vpype()
        assert data["layer_name"] == "pen-first"
        assert data["pen_color"] == "#FF0000"


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])
