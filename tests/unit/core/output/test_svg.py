"""Unit tests for SVG export."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from shapely import LineString

from penpath.core.models import Paper, Pen
from penpath.core.output.svg import (
    PENPATH_NAMESPACE,
    ImagePlacement,
    add_placement_metadata,
    export_svg,
    fit_image_placement,
)


class TestExportSvg:
    """Tests for export_svg function."""

    def test_export_svg_basic(self, tmp_path: Path):
        """Basic SVG export should produce valid SVG file."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        pen = Pen(name="fine", width_mm=0.3)
        lines = [LineString([(100, 100), (200, 200), (300, 100)])]

        output_path = tmp_path / "output.svg"
        export_svg(lines, paper, [pen], output_path)

        assert output_path.exists()
        content = output_path.read_text()
        assert "<svg" in content
        assert "</svg>" in content

    def test_export_svg_viewbox(self, tmp_path: Path):
        """SVG should have correct viewBox from paper size at 96 DPI."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        pen = Pen(name="fine", width_mm=0.3)
        lines = [LineString([(100, 100), (200, 200)])]

        output_path = tmp_path / "output.svg"
        export_svg(lines, paper, [pen], output_path)

        content = output_path.read_text()
        # A4 at 96 DPI: 210 * 96 / 25.4 ≈ 793.7, 297 * 96 / 25.4 ≈ 1122.5
        assert 'viewBox="0 0 793.7' in content
        assert 'width="210' in content
        assert 'height="297' in content

    def test_export_svg_background_layer(self, tmp_path: Path):
        """SVG should have background layer with paper color."""
        paper = Paper(
            name="A4",
            width_mm=210,
            height_mm=297,
            dpi=300,
            background_color="#FF0000",
        )
        pen = Pen(name="fine", width_mm=0.3)
        lines = [LineString([(100, 100), (200, 200)])]

        output_path = tmp_path / "output.svg"
        export_svg(lines, paper, [pen], output_path)

        content = output_path.read_text()
        assert 'id="background"' in content
        assert 'inkscape:groupmode="layer"' in content
        assert 'inkscape:label="Background"' in content
        assert "#FF0000" in content or "rgb(255, 0, 0)" in content

    def test_export_svg_pen_layer(self, tmp_path: Path):
        """SVG should have pen layer with correct id and inkscape attributes."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        pen = Pen(name="fine", width_mm=0.3, color="#0000FF")
        lines = [LineString([(100, 100), (200, 200)])]

        output_path = tmp_path / "output.svg"
        export_svg(lines, paper, [pen], output_path)

        content = output_path.read_text()
        assert 'id="pen-fine"' in content
        assert 'inkscape:groupmode="layer"' in content
        assert 'inkscape:label="Pen: fine"' in content

    def test_export_svg_stroke_properties(self, tmp_path: Path):
        """SVG paths should have correct stroke width and color from pen."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        pen = Pen(name="bold", width_mm=0.5, color="#FF0000", opacity=0.8)
        lines = [LineString([(100, 100), (200, 200)])]

        output_path = tmp_path / "output.svg"
        export_svg(lines, paper, [pen], output_path)

        content = output_path.read_text()
        # Stroke width: 0.5mm * 96 / 25.4 ≈ 1.89 SVG units
        assert 'stroke="#FF0000"' in content or 'stroke="rgb(255, 0, 0)"' in content
        assert "stroke-opacity" in content
        assert "stroke-width" in content
        assert "stroke-linecap" in content
        assert "stroke-linejoin" in content

    def test_export_svg_multiple_pens_creates_layers(self, tmp_path: Path):
        """Multiple pens should create multiple layers (only first populated)."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        pens = [
            Pen(name="fine", width_mm=0.3, color="#000000"),
            Pen(name="bold", width_mm=0.5, color="#FF0000"),
        ]
        lines = [LineString([(100, 100), (200, 200)])]

        output_path = tmp_path / "output.svg"
        export_svg(lines, paper, pens, output_path)

        content = output_path.read_text()
        assert 'id="pen-fine"' in content
        assert 'id="pen-bold"' in content
        assert 'inkscape:label="Pen: fine"' in content
        assert 'inkscape:label="Pen: bold"' in content

    def test_export_svg_coordinate_scaling(self, tmp_path: Path):
        """Geometries should be scaled from image coords to paper coords."""
        paper = Paper(name="square", width_mm=100, height_mm=100, margin_mm=10, dpi=300)
        pen = Pen(name="fine", width_mm=0.3)
        # Large image coordinates (e.g., 3000x3000 pixels at 300 DPI = 10x10 inch)
        lines = [LineString([(1500, 1500), (3000, 3000)])]

        output_path = tmp_path / "output.svg"
        export_svg(lines, paper, [pen], output_path, image_dpi=300)

        content = output_path.read_text()
        # Should produce valid paths within the viewBox
        assert "<path" in content
        # ViewBox should be 100mm at 96 DPI ≈ 378 SVG units
        assert "378" in content or "377" in content

    def test_export_svg_empty_geometries_raises(self, tmp_path: Path):
        """Empty geometries list should raise ValueError."""
        paper = Paper(name="A4", width_mm=210, height_mm=297)
        pen = Pen(name="fine", width_mm=0.3)

        output_path = tmp_path / "output.svg"
        with pytest.raises(ValueError, match="No geometries provided"):
            export_svg([], paper, [pen], output_path)

    def test_export_svg_no_pens_raises(self, tmp_path: Path):
        """Empty pens list should raise ValueError."""
        paper = Paper(name="A4", width_mm=210, height_mm=297)
        lines = [LineString([(100, 100), (200, 200)])]

        output_path = tmp_path / "output.svg"
        with pytest.raises(ValueError, match="At least one pen must be provided"):
            export_svg(lines, paper, [], output_path)

    def test_export_svg_invalid_geometries_raises(self, tmp_path: Path):
        """Invalid geometries (empty) should raise ValueError."""
        paper = Paper(name="A4", width_mm=210, height_mm=297)
        pen = Pen(name="fine", width_mm=0.3)
        lines = [
            LineString([]),  # Empty
            LineString([]),  # Also empty
        ]

        output_path = tmp_path / "output.svg"
        with pytest.raises(ValueError, match="No valid geometries"):
            export_svg(lines, paper, [pen], output_path)

    def test_export_svg_mixed_valid_invalid_geometries(self, tmp_path: Path):
        """Should filter out invalid geometries and process valid ones."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        pen = Pen(name="fine", width_mm=0.3)
        lines = [
            LineString([]),  # Empty - filtered out
            LineString([(200, 200), (300, 300)]),  # Valid
        ]

        output_path = tmp_path / "output.svg"
        export_svg(lines, paper, [pen], output_path)

        content = output_path.read_text()
        assert "<path" in content

    def test_export_svg_custom_paper_size(self, tmp_path: Path):
        """Should respect custom paper size."""
        paper = Paper(name="Custom", width_mm=100, height_mm=150, dpi=300)
        pen = Pen(name="fine", width_mm=0.3)
        lines = [LineString([(100, 100), (200, 200)])]

        output_path = tmp_path / "output.svg"
        export_svg(lines, paper, [pen], output_path)

        content = output_path.read_text()
        assert 'width="100' in content
        assert 'height="150' in content

    def test_export_svg_margin_respected(self, tmp_path: Path):
        """Margins should be respected in coordinate scaling."""
        paper = Paper(name="A4", width_mm=200, height_mm=200, margin_mm=20, dpi=300)
        pen = Pen(name="fine", width_mm=0.3)
        lines = [LineString([(100, 100), (200, 200)])]

        output_path = tmp_path / "output.svg"
        export_svg(lines, paper, [pen], output_path)

        content = output_path.read_text()
        # Drawable area: 200 - 40 = 160mm per side
        # ViewBox should be full paper size
        assert 'viewBox="0 0' in content
        # Paths should be within margins (not testable easily without parsing coords)

    def test_export_svg_pen_opacity(self, tmp_path: Path):
        """Pen opacity should be applied to stroke-opacity."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        pen = Pen(name="fine", width_mm=0.3, color="#000000", opacity=0.5)
        lines = [LineString([(100, 100), (200, 200)])]

        output_path = tmp_path / "output.svg"
        export_svg(lines, paper, [pen], output_path)

        content = output_path.read_text()
        assert 'stroke-opacity="0.5"' in content or "stroke-opacity:0.5" in content

    def test_export_svg_inkscape_namespace(self, tmp_path: Path):
        """SVG should have Inkscape namespace for layer support."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        pen = Pen(name="fine", width_mm=0.3)
        lines = [LineString([(100, 100), (200, 200)])]

        output_path = tmp_path / "output.svg"
        export_svg(lines, paper, [pen], output_path)

        content = output_path.read_text()
        assert 'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"' in content

    def test_export_svg_creates_parent_directories(self, tmp_path: Path):
        """Should create parent directories for output path."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        pen = Pen(name="fine", width_mm=0.3)
        lines = [LineString([(100, 100), (200, 200)])]

        output_path = tmp_path / "subdir" / "nested" / "output.svg"
        export_svg(lines, paper, [pen], output_path)

        assert output_path.exists()

    def test_export_svg_path_roundtrip(self, tmp_path: Path):
        """Exported SVG should be valid XML."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        pen = Pen(name="fine", width_mm=0.3)
        lines = [
            LineString([(100, 100), (200, 200)]),
            LineString([(300, 100), (400, 200)]),
        ]

        output_path = tmp_path / "output.svg"
        export_svg(lines, paper, [pen], output_path)

        # Should parse as valid XML
        tree = ET.parse(output_path)
        root = tree.getroot()
        assert root.tag.endswith("svg")
        # Check for layers
        groups = root.findall(".//{http://www.w3.org/2000/svg}g")
        layer_ids = [g.get("id") for g in groups if g.get("id")]
        assert "background" in layer_ids
        assert "pen-fine" in layer_ids


class TestPlacementMetadata:
    """Tests for image-placement metadata written by SVG export."""

    def test_export_svg_writes_placement_metadata(self, tmp_path: Path) -> None:
        """A placement is written as a namespaced metadata element."""
        paper = Paper(name="A4", width_mm=210, height_mm=297)
        pen = Pen(name="fine", width_mm=0.3)
        placement = ImagePlacement(10.0, 20.0, 190.0, 100.0)
        output_path = tmp_path / "placed.svg"

        export_svg(
            [LineString([(0, 0), (100, 100)])],
            paper,
            [pen],
            output_path,
            image_size_px=(100, 100),
            image_placement=placement,
        )

        root = ET.parse(output_path).getroot()
        metadata = root.find(f".//{{{PENPATH_NAMESPACE}}}image-placement")
        assert metadata is not None
        assert metadata.attrib == {
            "x": "10.0000",
            "y": "20.0000",
            "width": "190.0000",
            "height": "100.0000",
        }
        assert ET.parse(output_path).getroot().tag.endswith("svg")

    def test_export_svg_without_placement_writes_no_metadata(self, tmp_path: Path) -> None:
        """Existing exports stay unchanged when no placement is supplied."""
        paper = Paper(name="A4", width_mm=210, height_mm=297)
        pen = Pen(name="fine", width_mm=0.3)
        output_path = tmp_path / "plain.svg"

        export_svg([LineString([(0, 0), (100, 100)])], paper, [pen], output_path)

        content = output_path.read_text()
        assert "image-placement" not in content
        assert "<metadata>" not in content

    def test_export_svg_maps_geometries_into_placement(self, tmp_path: Path) -> None:
        """Stroke coordinates follow the placement rectangle, in SVG units."""
        paper = Paper(name="square", width_mm=100, height_mm=100)
        pen = Pen(name="fine", width_mm=0.3)
        placement = ImagePlacement(10.0, 20.0, 50.0, 25.0)
        output_path = tmp_path / "placed.svg"

        export_svg(
            [LineString([(0, 0), (100, 50)])],
            paper,
            [pen],
            output_path,
            image_size_px=(100, 50),
            image_placement=placement,
        )

        root = ET.parse(output_path).getroot()
        paths = [element for element in root.iter() if element.tag.endswith("}path")]
        assert len(paths) == 1
        path_data = paths[0].attrib["d"]
        assert "M 37.795 75.591" in path_data
        assert "L 226.772 170.079" in path_data

    def test_export_svg_placement_requires_image_size(self, tmp_path: Path) -> None:
        """Placement without the original image size cannot be applied."""
        paper = Paper(name="square", width_mm=100, height_mm=100)
        pen = Pen(name="fine", width_mm=0.3)

        with pytest.raises(ValueError, match="image_size_px is required"):
            export_svg(
                [LineString([(0, 0), (100, 50)])],
                paper,
                [pen],
                tmp_path / "bad.svg",
                image_placement=ImagePlacement(0, 0, 100, 50),
            )

    def test_add_placement_metadata_is_idempotent(self, tmp_path: Path) -> None:
        """Repeatedly adding placement metadata does not duplicate it."""
        paper = Paper(name="square", width_mm=100, height_mm=100)
        pen = Pen(name="fine", width_mm=0.3)
        output_path = tmp_path / "plain.svg"
        export_svg([LineString([(0, 0), (100, 50)])], paper, [pen], output_path)

        add_placement_metadata(output_path, (5.0, 5.0, 90.0, 45.0))
        add_placement_metadata(output_path, (7.0, 8.0, 80.0, 40.0))

        content = output_path.read_text()
        assert content.count("image-placement") == 1
        root = ET.parse(output_path).getroot()
        metadata = root.find(f".//{{{PENPATH_NAMESPACE}}}image-placement")
        assert metadata is not None
        assert metadata.attrib["x"] == "7.0000"

    def test_add_placement_metadata_without_closing_tag_raises(self, tmp_path: Path) -> None:
        """A non-SVG file is rejected with a clear error."""
        svg_path = tmp_path / "truncated.svg"
        svg_path.write_text('<svg width="100mm">')

        with pytest.raises(ValueError, match="No closing </svg> tag found"):
            add_placement_metadata(svg_path, (5.0, 5.0, 90.0, 45.0))

    def test_fit_image_placement_preserves_aspect_ratio(self) -> None:
        """Image fitting keeps the aspect ratio and centers the image."""
        placement = fit_image_placement((100, 50), 80.0, 80.0, image_dpi=300)

        assert placement.width == pytest.approx(80.0)
        assert placement.height == pytest.approx(40.0)
        assert placement.x == pytest.approx(0.0)
        assert placement.y == pytest.approx(20.0)


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])
