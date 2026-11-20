"""Unit tests for penpath.core.project."""

from __future__ import annotations

from pathlib import Path

import pytest

from penpath.core.image.pipeline import FilterPipeline
from penpath.core.models import ImageRef, Paper, Pen, Project, SketchLinesPFM
from penpath.core.project import (
    PROJECT_FILE_VERSION,
    ProjectLoadError,
    ProjectSaveError,
    load_yaml,
    save_yaml,
)


class TestLoadYaml:
    """Tests for load_yaml function."""

    def test_load_valid_project(self, tmp_path: Path) -> None:
        """Test loading a valid project YAML file."""
        img_path = tmp_path / "input.png"
        img_path.write_bytes(b"fake png")
        out_path = tmp_path / "output.svg"

        project = Project(
            image=ImageRef(path=img_path, filters=FilterPipeline(), dpi=300),
            paper=Paper(name="a4", width_mm=210.0, height_mm=297.0),
            pen=Pen(name="fine", width_mm=0.3),
            pfm=SketchLinesPFM(),
            output_path=out_path,
        )

        save_yaml(project, tmp_path / "project.yaml")
        loaded = load_yaml(tmp_path / "project.yaml")

        assert loaded.image.path == project.image.path
        assert loaded.image.dpi == project.image.dpi
        assert loaded.paper.name == project.paper.name
        assert loaded.paper.width_mm == project.paper.width_mm
        assert loaded.paper.height_mm == project.paper.height_mm
        assert loaded.pen.name == project.pen.name
        assert loaded.pen.width_mm == project.pen.width_mm
        assert loaded.output_path == project.output_path

    def test_load_nonexistent_file(self) -> None:
        """Test loading a nonexistent file raises ProjectLoadError."""
        with pytest.raises(ProjectLoadError, match="not found"):
            load_yaml(Path("/nonexistent/project.yaml"))

    def test_load_directory(self, tmp_path: Path) -> None:
        """Test loading a directory raises ProjectLoadError."""
        with pytest.raises(ProjectLoadError, match="not a file"):
            load_yaml(tmp_path)

    def test_load_empty_file(self, tmp_path: Path) -> None:
        """Test loading an empty file raises ProjectLoadError."""
        empty_file = tmp_path / "empty.yaml"
        empty_file.write_text("")
        with pytest.raises(ProjectLoadError, match="empty"):
            load_yaml(empty_file)

    def test_load_invalid_yaml(self, tmp_path: Path) -> None:
        """Test loading invalid YAML raises ProjectLoadError."""
        invalid_file = tmp_path / "invalid.yaml"
        invalid_file.write_text("{{{ invalid yaml }}}")
        with pytest.raises(ProjectLoadError, match="parse YAML"):
            load_yaml(invalid_file)

    def test_load_non_mapping_yaml(self, tmp_path: Path) -> None:
        """Test loading YAML that's not a mapping raises ProjectLoadError."""
        non_mapping = tmp_path / "non_mapping.yaml"
        non_mapping.write_text("- item1\n- item2\n")
        with pytest.raises(ProjectLoadError, match="must contain a YAML mapping"):
            load_yaml(non_mapping)

    def test_load_invalid_project_data(self, tmp_path: Path) -> None:
        """Test loading invalid project data raises ProjectLoadError."""
        invalid_file = tmp_path / "invalid_project.yaml"
        invalid_file.write_text("image: {}\npaper: {}\npen: {}\npfm: {}\noutput_path: out.svg\n")
        with pytest.raises(ProjectLoadError, match="validation failed"):
            load_yaml(invalid_file)

    def test_load_missing_required_fields(self, tmp_path: Path) -> None:
        """Test loading project with missing required fields raises error."""
        invalid_file = tmp_path / "missing_fields.yaml"
        invalid_file.write_text("version: 1\n")
        with pytest.raises(ProjectLoadError, match="validation failed"):
            load_yaml(invalid_file)


class TestSaveYaml:
    """Tests for save_yaml function."""

    def test_save_valid_project(self, tmp_path: Path) -> None:
        """Test saving a valid project creates a YAML file."""
        img_path = tmp_path / "input.png"
        img_path.write_bytes(b"fake png")
        out_path = tmp_path / "output.svg"

        project = Project(
            image=ImageRef(path=img_path, filters=FilterPipeline(), dpi=300),
            paper=Paper(name="a4", width_mm=210.0, height_mm=297.0),
            pen=Pen(name="fine", width_mm=0.3),
            pfm=SketchLinesPFM(),
            output_path=out_path,
        )

        save_path = tmp_path / "saved_project.yaml"
        save_yaml(project, save_path)

        assert save_path.exists()
        assert save_path.is_file()
        content = save_path.read_text()
        assert "penpath project file" in content
        assert "version:" in content
        assert "image:" in content
        assert "paper:" in content
        assert "pen:" in content
        assert "pfm:" in content
        assert "output_path:" in content

    def test_save_creates_parent_directories(self, tmp_path: Path) -> None:
        """Test save_yaml creates parent directories if they don't exist."""
        img_path = tmp_path / "input.png"
        img_path.write_bytes(b"fake png")
        out_path = tmp_path / "output.svg"

        project = Project(
            image=ImageRef(path=img_path, filters=FilterPipeline(), dpi=300),
            paper=Paper(name="a4", width_mm=210.0, height_mm=297.0),
            pen=Pen(name="fine", width_mm=0.3),
            pfm=SketchLinesPFM(),
            output_path=out_path,
        )

        save_path = tmp_path / "subdir" / "nested" / "project.yaml"
        save_yaml(project, save_path)

        assert save_path.exists()

    def test_save_includes_metadata(self, tmp_path: Path) -> None:
        """Test saved project includes metadata with timestamps."""
        img_path = tmp_path / "input.png"
        img_path.write_bytes(b"fake png")
        out_path = tmp_path / "output.svg"

        project = Project(
            image=ImageRef(path=img_path, filters=FilterPipeline(), dpi=300),
            paper=Paper(name="a4", width_mm=210.0, height_mm=297.0),
            pen=Pen(name="fine", width_mm=0.3),
            pfm=SketchLinesPFM(),
            output_path=out_path,
        )

        save_path = tmp_path / "project.yaml"
        save_yaml(project, save_path)
        content = save_path.read_text()

        assert "metadata:" in content
        assert "created:" in content
        assert "modified:" in content
        assert "version:" in content


class TestRoundTrip:
    """Tests for load/save round-trip safety."""

    def test_round_trip_minimal_project(self, tmp_path: Path) -> None:
        """Test round-trip with minimal project."""
        img_path = tmp_path / "input.png"
        img_path.write_bytes(b"fake png")
        out_path = tmp_path / "output.svg"

        original = Project(
            image=ImageRef(path=img_path, filters=FilterPipeline(), dpi=300),
            paper=Paper(name="a4", width_mm=210.0, height_mm=297.0),
            pen=Pen(name="fine", width_mm=0.3),
            pfm=SketchLinesPFM(),
            output_path=out_path,
        )

        save_path = tmp_path / "roundtrip.yaml"
        save_yaml(original, save_path)
        loaded = load_yaml(save_path)

        assert loaded.image.path == original.image.path
        assert loaded.image.dpi == original.image.dpi
        assert loaded.paper.name == original.paper.name
        assert loaded.paper.width_mm == original.paper.width_mm
        assert loaded.paper.height_mm == original.paper.height_mm
        assert loaded.pen.name == original.pen.name
        assert loaded.pen.width_mm == original.pen.width_mm
        assert loaded.output_path == original.output_path

    def test_round_trip_with_filters(self, tmp_path: Path) -> None:
        """Test round-trip with filter pipeline."""
        img_path = tmp_path / "input.png"
        img_path.write_bytes(b"fake png")
        out_path = tmp_path / "output.svg"

        pipeline = FilterPipeline()
        pipeline.add_step("grayscale", method="luminance")
        pipeline.add_step("threshold", level=128, dither="floyd_steinberg")

        original = Project(
            image=ImageRef(path=img_path, filters=pipeline, dpi=300),
            paper=Paper(name="a4", width_mm=210.0, height_mm=297.0),
            pen=Pen(name="fine", width_mm=0.3),
            pfm=SketchLinesPFM(),
            output_path=out_path,
        )

        save_path = tmp_path / "roundtrip_filters.yaml"
        save_yaml(original, save_path)
        loaded = load_yaml(save_path)

        assert len(loaded.image.filters.steps) == 2
        assert loaded.image.filters.steps[0].name == "grayscale"
        assert loaded.image.filters.steps[0].kwargs == {"method": "luminance"}
        assert loaded.image.filters.steps[1].name == "threshold"
        assert loaded.image.filters.steps[1].kwargs == {"level": 128, "dither": "floyd_steinberg"}

    def test_round_trip_with_custom_pen(self, tmp_path: Path) -> None:
        """Test round-trip with custom pen settings."""
        img_path = tmp_path / "input.png"
        img_path.write_bytes(b"fake png")
        out_path = tmp_path / "output.svg"

        original = Project(
            image=ImageRef(path=img_path, filters=FilterPipeline(), dpi=300),
            paper=Paper(name="a4", width_mm=210.0, height_mm=297.0),
            pen=Pen(name="bold_red", width_mm=0.7, color="#FF0000", opacity=0.9, pen_type="marker"),
            pfm=SketchLinesPFM(),
            output_path=out_path,
        )

        save_path = tmp_path / "roundtrip_pen.yaml"
        save_yaml(original, save_path)
        loaded = load_yaml(save_path)

        assert loaded.pen.name == "bold_red"
        assert loaded.pen.width_mm == 0.7
        assert loaded.pen.color == "#FF0000"
        assert loaded.pen.opacity == 0.9
        assert loaded.pen.pen_type == "marker"

    def test_round_trip_with_custom_paper(self, tmp_path: Path) -> None:
        """Test round-trip with custom paper settings."""
        img_path = tmp_path / "input.png"
        img_path.write_bytes(b"fake png")
        out_path = tmp_path / "output.svg"

        original = Project(
            image=ImageRef(path=img_path, filters=FilterPipeline(), dpi=300),
            paper=Paper(
                name="custom",
                width_mm=300.0,
                height_mm=400.0,
                margin_mm=20.0,
                background_color="#F0F0F0",
                dpi=600,
            ),
            pen=Pen(name="fine", width_mm=0.3),
            pfm=SketchLinesPFM(),
            output_path=out_path,
        )

        save_path = tmp_path / "roundtrip_paper.yaml"
        save_yaml(original, save_path)
        loaded = load_yaml(save_path)

        assert loaded.paper.name == "custom"
        assert loaded.paper.width_mm == 300.0
        assert loaded.paper.height_mm == 400.0
        assert loaded.paper.margin_mm == 20.0
        assert loaded.paper.background_color == "#F0F0F0"
        assert loaded.paper.dpi == 600

    def test_round_trip_with_custom_pfm_settings(self, tmp_path: Path) -> None:
        """Test round-trip with custom PFM settings."""
        img_path = tmp_path / "input.png"
        img_path.write_bytes(b"fake png")
        out_path = tmp_path / "output.svg"

        from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings

        custom_pfm = SketchLinesPFM(
            settings=SketchLinesSettings(
                line_density=2.5,
                min_length=5.0,
                max_length=200.0,
                angle_range=(30.0, 60.0),
                shading_enabled=False,
                squiggle_enabled=False,
                erase_enabled=False,
                seed=42,
            )
        )

        original = Project(
            image=ImageRef(path=img_path, filters=FilterPipeline(), dpi=300),
            paper=Paper(name="a4", width_mm=210.0, height_mm=297.0),
            pen=Pen(name="fine", width_mm=0.3),
            pfm=custom_pfm,
            output_path=out_path,
        )

        save_path = tmp_path / "roundtrip_pfm.yaml"
        save_yaml(original, save_path)
        loaded = load_yaml(save_path)

        assert loaded.pfm.pfm_type == "sketch_lines"
        assert loaded.pfm.settings.line_density == 2.5
        assert loaded.pfm.settings.min_length == 5.0
        assert loaded.pfm.settings.max_length == 200.0
        assert loaded.pfm.settings.angle_range == (30.0, 60.0)
        assert loaded.pfm.settings.shading_enabled is False
        assert loaded.pfm.settings.squiggle_enabled is False
        assert loaded.pfm.settings.erase_enabled is False
        assert loaded.pfm.settings.seed == 42


class TestVersionMigration:
    """Tests for version migration placeholder."""

    def test_load_v1_project(self, tmp_path: Path) -> None:
        """Test loading a v1 project works without migration."""
        img_path = tmp_path / "input.png"
        img_path.write_bytes(b"fake png")
        out_path = tmp_path / "output.svg"

        project = Project(
            image=ImageRef(path=img_path, filters=FilterPipeline(), dpi=300),
            paper=Paper(name="a4", width_mm=210.0, height_mm=297.0),
            pen=Pen(name="fine", width_mm=0.3),
            pfm=SketchLinesPFM(),
            output_path=out_path,
        )

        save_path = tmp_path / "v1_project.yaml"
        save_yaml(project, save_path)

        # Manually change version to test migration path
        content = save_path.read_text()
        content = content.replace(f"version: {PROJECT_FILE_VERSION}", "version: 1")
        save_path.write_text(content)

        loaded = load_yaml(save_path)
        assert loaded.image.path == project.image.path

    def test_load_future_version_warns(self, tmp_path: Path) -> None:
        """Test loading a future version project (placeholder for migration)."""
        img_path = tmp_path / "input.png"
        img_path.write_bytes(b"fake png")
        out_path = tmp_path / "output.svg"

        project = Project(
            image=ImageRef(path=img_path, filters=FilterPipeline(), dpi=300),
            paper=Paper(name="a4", width_mm=210.0, height_mm=297.0),
            pen=Pen(name="fine", width_mm=0.3),
            pfm=SketchLinesPFM(),
            output_path=out_path,
        )

        save_path = tmp_path / "future_project.yaml"
        save_yaml(project, save_path)

        # Manually change version to future version
        content = save_path.read_text()
        content = content.replace(f"version: {PROJECT_FILE_VERSION}", "version: 999")
        save_path.write_text(content)

        # Should still load (migration is a no-op placeholder for now)
        loaded = load_yaml(save_path)
        assert loaded.image.path == project.image.path


class TestYamlOutputFormat:
    """Tests for YAML output format and comments."""

    def test_output_has_header_comments(self, tmp_path: Path) -> None:
        """Test saved YAML has header comments."""
        img_path = tmp_path / "input.png"
        img_path.write_bytes(b"fake png")
        out_path = tmp_path / "output.svg"

        project = Project(
            image=ImageRef(path=img_path, filters=FilterPipeline(), dpi=300),
            paper=Paper(name="a4", width_mm=210.0, height_mm=297.0),
            pen=Pen(name="fine", width_mm=0.3),
            pfm=SketchLinesPFM(),
            output_path=out_path,
        )

        save_path = tmp_path / "project.yaml"
        save_yaml(project, save_path)
        content = save_path.read_text()

        assert content.startswith("# penpath project file")
        assert f"# version: {PROJECT_FILE_VERSION}" in content.split("\n")[1]

    def test_output_has_section_comments(self, tmp_path: Path) -> None:
        """Test saved YAML has section comments."""
        img_path = tmp_path / "input.png"
        img_path.write_bytes(b"fake png")
        out_path = tmp_path / "output.svg"

        project = Project(
            image=ImageRef(path=img_path, filters=FilterPipeline(), dpi=300),
            paper=Paper(name="a4", width_mm=210.0, height_mm=297.0),
            pen=Pen(name="fine", width_mm=0.3),
            pfm=SketchLinesPFM(),
            output_path=out_path,
        )

        save_path = tmp_path / "project.yaml"
        save_yaml(project, save_path)
        content = save_path.read_text()

        assert "# Input image configuration" in content
        assert "# Paper configuration" in content
        assert "# Pen configuration" in content
        assert "# Pen Follower Module (PFM) configuration" in content
        assert "# Output SVG file path" in content

    def test_output_is_valid_yaml(self, tmp_path: Path) -> None:
        """Test saved YAML can be parsed by standard YAML loader."""
        import yaml

        img_path = tmp_path / "input.png"
        img_path.write_bytes(b"fake png")
        out_path = tmp_path / "output.svg"

        project = Project(
            image=ImageRef(path=img_path, filters=FilterPipeline(), dpi=300),
            paper=Paper(name="a4", width_mm=210.0, height_mm=297.0),
            pen=Pen(name="fine", width_mm=0.3),
            pfm=SketchLinesPFM(),
            output_path=out_path,
        )

        save_path = tmp_path / "project.yaml"
        save_yaml(project, save_path)

        # Should parse without error
        with save_path.open("r") as f:
            data = yaml.safe_load(f)

        assert data is not None
        assert isinstance(data, dict)
        assert data["version"] == PROJECT_FILE_VERSION


class TestErrorHandling:
    """Tests for error handling edge cases."""

    def test_save_to_readonly_directory_fails(self, tmp_path: Path) -> None:
        """Test saving to a read-only directory raises ProjectSaveError."""
        # This test might not work in all environments (e.g., running as root)
        # Skip if we can't create readonly dirs
        import os

        if os.geteuid() == 0:
            pytest.skip("Running as root, cannot test readonly directories")

        img_path = tmp_path / "input.png"
        img_path.write_bytes(b"fake png")
        out_path = tmp_path / "output.svg"

        project = Project(
            image=ImageRef(path=img_path, filters=FilterPipeline(), dpi=300),
            paper=Paper(name="a4", width_mm=210.0, height_mm=297.0),
            pen=Pen(name="fine", width_mm=0.3),
            pfm=SketchLinesPFM(),
            output_path=out_path,
        )

        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir(mode=0o555)
        save_path = readonly_dir / "project.yaml"

        try:
            with pytest.raises(ProjectSaveError):
                save_yaml(project, save_path)
        finally:
            # Restore permissions for cleanup
            readonly_dir.chmod(0o755)

    def test_load_with_invalid_pfm_type(self, tmp_path: Path) -> None:
        """Test loading project with unknown PFM type raises validation error."""
        invalid_file = tmp_path / "invalid_pfm.yaml"
        invalid_file.write_text(
            f"""version: {PROJECT_FILE_VERSION}
image:
  path: "{tmp_path / 'input.png'}"
  filters:
    steps: []
  dpi: 300
paper:
  name: a4
  width_mm: 210.0
  height_mm: 297.0
pen:
  name: fine
  width_mm: 0.3
pfm:
  pfm_type: unknown_pfm
  settings: {{}}
output_path: output.svg
"""
        )
        with pytest.raises(ProjectLoadError, match="validation failed"):
            load_yaml(invalid_file)


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])
