"""Unit tests for penpath.core.project."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from penpath.core.image.background import DEFAULT_BACKGROUND_THRESHOLD
from penpath.core.image.pipeline import FilterPipeline
from penpath.core.models import ImageRef, Paper, Pen, Project, SketchLinesPFM, SketchSquaresPFM
from penpath.core.project import (
    PROJECT_FILE_VERSION,
    ProjectLoadError,
    ProjectSaveError,
    load_yaml,
    save_yaml,
)
from penpath.presets.palettes import get_palette


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
  path: "{tmp_path / "input.png"}"
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


def _yaml_data(tmp_path: Path) -> dict[str, Any]:
    img_path = tmp_path / "input.png"
    img_path.write_bytes(b"fake png")
    return {
        "version": PROJECT_FILE_VERSION,
        "image": {"path": str(img_path), "filters": {"steps": []}, "dpi": 300},
        "paper": {"name": "a4", "width_mm": 210.0, "height_mm": 297.0},
        "pfm": {"pfm_type": "sketch_lines", "settings": {}},
        "output_path": str(tmp_path / "output.svg"),
    }


def _write_yaml(tmp_path: Path, data: dict[str, Any], filename: str = "project.yaml") -> Path:
    path = tmp_path / filename
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path


class TestPaletteProjectFiles:
    """Palette and pen-list keys in project files."""

    def test_old_project_with_pen_still_loads(self, tmp_path: Path) -> None:
        data = _yaml_data(tmp_path)
        data["pen"] = {"name": "fine", "width_mm": 0.3}
        project = load_yaml(_write_yaml(tmp_path, data))
        assert project.pen is not None
        assert project.palette == [project.pen]
        assert project.palette_name is None

    def test_project_without_auto_equalize_loads_as_true(self, tmp_path: Path) -> None:
        """An older YAML without the field gets the new default."""
        data = _yaml_data(tmp_path)
        data["pen"] = {"name": "fine", "width_mm": 0.3}
        assert "auto_equalize" not in data["image"]
        project = load_yaml(_write_yaml(tmp_path, data))
        assert project.image.auto_equalize is True

    def test_project_auto_equalize_false_round_trips(self, tmp_path: Path) -> None:
        data = _yaml_data(tmp_path)
        data["image"]["auto_equalize"] = False
        data["pen"] = {"name": "fine", "width_mm": 0.3}
        project = load_yaml(_write_yaml(tmp_path, data))
        assert project.image.auto_equalize is False
        save_path = tmp_path / "saved.yaml"
        save_yaml(project, save_path)
        assert load_yaml(save_path).image.auto_equalize is False

    def test_palette_name_expands_to_ordered_pens(self, tmp_path: Path) -> None:
        data = _yaml_data(tmp_path)
        data["palette"] = "stabilo_88"
        project = load_yaml(_write_yaml(tmp_path, data))
        assert project.pen is None
        assert project.palette_name == "stabilo_88"
        assert [pen.name for pen in project.palette] == [
            pen.name for pen in get_palette("stabilo_88").pens
        ]

    def test_explicit_pens_keep_their_order(self, tmp_path: Path) -> None:
        data = _yaml_data(tmp_path)
        data["pens"] = [
            {"name": "first", "width_mm": 0.4, "color": "#FF0000"},
            {"name": "second", "width_mm": 0.4, "color": "#0000FF"},
        ]
        project = load_yaml(_write_yaml(tmp_path, data))
        assert [pen.name for pen in project.palette] == ["first", "second"]
        assert project.palette_name is None

    def test_unknown_palette_is_a_clear_error(self, tmp_path: Path) -> None:
        data = _yaml_data(tmp_path)
        data["palette"] = "missing"
        with pytest.raises(ProjectLoadError, match="Unknown palette: missing"):
            load_yaml(_write_yaml(tmp_path, data))

    @pytest.mark.parametrize(
        "extra",
        [
            {"pen": {"name": "fine", "width_mm": 0.3}, "palette": "stabilo_88"},
            {
                "palette": "stabilo_88",
                "pens": [{"name": "first", "width_mm": 0.4}],
            },
            {
                "pen": {"name": "fine", "width_mm": 0.3},
                "pens": [{"name": "first", "width_mm": 0.4}],
            },
        ],
    )
    def test_pen_fields_are_mutually_exclusive(self, tmp_path: Path, extra: dict[str, Any]) -> None:
        data = _yaml_data(tmp_path)
        data.update(extra)
        with pytest.raises(ProjectLoadError, match="mutually exclusive"):
            load_yaml(_write_yaml(tmp_path, data))

    def test_save_round_trips_builtin_palette_name(self, tmp_path: Path) -> None:
        base = _yaml_data(tmp_path)
        project = Project(
            image=ImageRef(path=base["image"]["path"], filters=FilterPipeline(), dpi=300),
            paper=Paper(name="a4", width_mm=210.0, height_mm=297.0),
            pen=None,
            pens=get_palette("stabilo_88").pens,
            palette_name="stabilo_88",
            pfm=SketchLinesPFM(),
            output_path=base["output_path"],
        )
        path = tmp_path / "palette.yaml"
        save_yaml(project, path)
        content = path.read_text()
        assert "# Built-in palette (drawing order)" in content
        assert "palette: stabilo_88" in content
        assert "pens:" not in content

        loaded = load_yaml(path)
        assert loaded.palette_name == "stabilo_88"
        assert [pen.name for pen in loaded.palette] == [pen.name for pen in project.palette]

    def test_save_round_trips_explicit_pens(self, tmp_path: Path) -> None:
        base = _yaml_data(tmp_path)
        pens = [Pen(name="first", width_mm=0.4, color="#FF0000")]
        project = Project(
            image=ImageRef(path=base["image"]["path"], filters=FilterPipeline(), dpi=300),
            paper=Paper(name="a4", width_mm=210.0, height_mm=297.0),
            pen=None,
            pens=pens,
            pfm=SketchLinesPFM(),
            output_path=base["output_path"],
        )
        path = tmp_path / "pens.yaml"
        save_yaml(project, path)
        content = path.read_text()
        assert "# Ordered pens (drawing order)" in content
        assert "pens:" in content
        assert "palette:" not in content

        loaded = load_yaml(path)
        assert loaded.palette == pens
        assert loaded.palette_name is None


class TestBackgroundProjectFiles:
    """Background options load old files unchanged and round-trip when set."""

    def test_old_project_loads_with_mode_defaults(self, tmp_path: Path) -> None:
        data = _yaml_data(tmp_path)
        data["pen"] = {"name": "fine", "width_mm": 0.3}
        project = load_yaml(_write_yaml(tmp_path, data))
        assert project.image.background is None
        assert project.image.background_threshold == DEFAULT_BACKGROUND_THRESHOLD

    def test_background_fields_round_trip(self, tmp_path: Path) -> None:
        data = _yaml_data(tmp_path)
        data["palette"] = "stabilo_88"
        data["image"]["background"] = False
        data["image"]["background_threshold"] = 4.5
        project = load_yaml(_write_yaml(tmp_path, data))
        assert project.image.background is False
        assert project.image.background_threshold == 4.5

        path = tmp_path / "saved.yaml"
        save_yaml(project, path)
        saved = yaml.safe_load(path.read_text())
        assert saved["image"]["background"] is False
        assert saved["image"]["background_threshold"] == 4.5
        loaded = load_yaml(path)
        assert loaded.image.background is False
        assert loaded.image.background_threshold == 4.5

    def test_unset_background_is_not_written_on_save(self, tmp_path: Path) -> None:
        data = _yaml_data(tmp_path)
        data["pen"] = {"name": "fine", "width_mm": 0.3}
        project = load_yaml(_write_yaml(tmp_path, data))
        path = tmp_path / "saved.yaml"
        save_yaml(project, path)
        saved = yaml.safe_load(path.read_text())
        assert "background" not in saved["image"]
        assert load_yaml(path).image.background is None

    def test_negative_threshold_is_rejected(self, tmp_path: Path) -> None:
        data = _yaml_data(tmp_path)
        data["pen"] = {"name": "fine", "width_mm": 0.3}
        data["image"]["background_threshold"] = -1.0
        with pytest.raises(ProjectLoadError, match="validation failed"):
            load_yaml(_write_yaml(tmp_path, data))

    def test_old_project_loads_with_the_local_method(self, tmp_path: Path) -> None:
        data = _yaml_data(tmp_path)
        data["pen"] = {"name": "fine", "width_mm": 0.3}
        assert "background_method" not in data["image"]
        assert load_yaml(_write_yaml(tmp_path, data)).image.background_method == "local"

    @pytest.mark.parametrize("method", ["global", "local"])
    def test_background_method_round_trips(self, tmp_path: Path, method: str) -> None:
        data = _yaml_data(tmp_path)
        data["pen"] = {"name": "fine", "width_mm": 0.3}
        data["image"]["background_method"] = method
        project = load_yaml(_write_yaml(tmp_path, data))
        assert project.image.background_method == method

        path = tmp_path / "saved.yaml"
        save_yaml(project, path)
        saved = yaml.safe_load(path.read_text())
        assert saved["image"]["background_method"] == method
        assert load_yaml(path).image.background_method == method

    def test_unknown_background_method_is_rejected(self, tmp_path: Path) -> None:
        data = _yaml_data(tmp_path)
        data["pen"] = {"name": "fine", "width_mm": 0.3}
        data["image"]["background_method"] = "diagonal"
        with pytest.raises(ProjectLoadError, match="validation failed"):
            load_yaml(_write_yaml(tmp_path, data))


class TestSaturationProjectFiles:
    """Saturation options load old files unchanged and round-trip when set."""

    def test_old_project_loads_with_disabled_defaults(self, tmp_path: Path) -> None:
        data = _yaml_data(tmp_path)
        data["pen"] = {"name": "fine", "width_mm": 0.3}
        project = load_yaml(_write_yaml(tmp_path, data))
        assert project.image.saturation == 1.0
        assert project.image.palette_adapt is False

    def test_saturation_fields_round_trip(self, tmp_path: Path) -> None:
        data = _yaml_data(tmp_path)
        data["palette"] = "stabilo_88"
        data["image"]["saturation"] = 2.5
        data["image"]["palette_adapt"] = True
        project = load_yaml(_write_yaml(tmp_path, data))
        assert project.image.saturation == 2.5
        assert project.image.palette_adapt is True

        path = tmp_path / "saved.yaml"
        save_yaml(project, path)
        saved = yaml.safe_load(path.read_text())
        assert saved["image"]["saturation"] == 2.5
        assert saved["image"]["palette_adapt"] is True
        loaded = load_yaml(path)
        assert loaded.image.saturation == 2.5
        assert loaded.image.palette_adapt is True

    def test_out_of_range_saturation_is_rejected(self, tmp_path: Path) -> None:
        data = _yaml_data(tmp_path)
        data["pen"] = {"name": "fine", "width_mm": 0.3}
        data["image"]["saturation"] = 3.5
        with pytest.raises(ProjectLoadError, match="validation failed"):
            load_yaml(_write_yaml(tmp_path, data))


class TestSketchSquaresPFMProjectFiles:
    """Sketch Squares survives a project-file round trip and selects its model."""

    def test_handwritten_yaml_loads_as_sketch_squares(self, tmp_path: Path) -> None:
        data = _yaml_data(tmp_path)
        data["pen"] = {"name": "fine", "width_mm": 0.3}
        data["pfm"] = {
            "pfm_type": "sketch_squares",
            "settings": {"grid_angle": 12.5, "line_density": 0.5, "seed": 42},
        }
        project = load_yaml(_write_yaml(tmp_path, data))

        assert isinstance(project.pfm, SketchSquaresPFM)
        assert project.pfm.settings.grid_angle == 12.5
        assert project.pfm.settings.line_density == 0.5
        assert project.pfm.settings.seed == 42
        assert project.pfm.to_typed_settings() == project.pfm.settings

    def test_save_and_load_round_trip(self, tmp_path: Path) -> None:
        from penpath.core.drawing.pfm_sketch_squares import SketchSquaresSettings

        img_path = tmp_path / "input.png"
        img_path.write_bytes(b"fake png")
        original = Project(
            image=ImageRef(path=img_path, filters=FilterPipeline(), dpi=300),
            paper=Paper(name="a4", width_mm=210.0, height_mm=297.0),
            pen=Pen(name="fine", width_mm=0.3),
            pfm=SketchSquaresPFM(
                settings=SketchSquaresSettings(
                    grid_angle=0.0, line_density=1.1, max_length=75.0, seed=42
                )
            ),
            output_path=tmp_path / "output.svg",
        )
        path = tmp_path / "squares.yaml"
        save_yaml(original, path)

        assert "pfm_type: sketch_squares" in path.read_text()
        loaded = load_yaml(path)
        assert isinstance(loaded.pfm, SketchSquaresPFM)
        assert loaded.pfm.settings == original.pfm.settings
        assert loaded.pfm.to_typed_settings() == original.pfm.settings


class TestStyleProjectFiles:
    """The saved look is a documented project field."""

    def test_old_project_loads_without_a_style(self, tmp_path: Path) -> None:
        data = _yaml_data(tmp_path)
        data["pen"] = {"name": "fine", "width_mm": 0.3}
        assert load_yaml(_write_yaml(tmp_path, data)).style is None

    @pytest.mark.parametrize("style", ["sketch", "hatch", "outline"])
    def test_style_round_trips(self, tmp_path: Path, style: str) -> None:
        data = _yaml_data(tmp_path)
        data["pen"] = {"name": "fine", "width_mm": 0.3}
        data["style"] = style
        project = load_yaml(_write_yaml(tmp_path, data))
        assert project.style == style

        path = tmp_path / "saved.yaml"
        save_yaml(project, path)
        saved = yaml.safe_load(path.read_text())
        assert saved["style"] == style
        assert "# Saved look preset" in path.read_text()
        assert load_yaml(path).style == style

    def test_unset_style_is_not_written_on_save(self, tmp_path: Path) -> None:
        data = _yaml_data(tmp_path)
        data["pen"] = {"name": "fine", "width_mm": 0.3}
        path = tmp_path / "saved.yaml"
        save_yaml(load_yaml(_write_yaml(tmp_path, data)), path)
        assert "style" not in yaml.safe_load(path.read_text())

    def test_unknown_style_is_a_clear_error(self, tmp_path: Path) -> None:
        data = _yaml_data(tmp_path)
        data["pen"] = {"name": "fine", "width_mm": 0.3}
        data["style"] = "scribble"
        with pytest.raises(ProjectLoadError, match="validation failed"):
            load_yaml(_write_yaml(tmp_path, data))


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])
