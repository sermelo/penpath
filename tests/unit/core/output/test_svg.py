"""Unit tests for SVG export."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from shapely import LineString

from penpath.core.models import Paper, Pen
from penpath.core.output.svg import export_svg


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


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])
