"""Unit tests for core models."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from penpath.core.models import (
    ImageRef,
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


class TestSketchLinesPFM:
    """Tests for SketchLinesPFM model."""

    def test_sketch_lines_pfm_default(self):
        """Test SketchLinesPFM with default settings."""
        pfm = SketchLinesPFM()
        assert pfm.pfm_type == "sketch_lines"
        assert pfm.settings.line_density == 1.0
        assert pfm.settings.min_length == 10.0

    def test_sketch_lines_pfm_custom(self):
        """Test SketchLinesPFM with custom settings."""
        from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings
        custom = SketchLinesSettings(line_density=2.0, min_length=5.0)
        pfm = SketchLinesPFM(settings=custom)
        assert pfm.settings.line_density == 2.0
        assert pfm.settings.min_length == 5.0


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


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])
