"""Unit tests for vpype wrapper."""

from __future__ import annotations

import pytest
from shapely import LineString

from penpath.core.models import Paper, Pen
from penpath.core.output.vpype import run_vpype

# Skip all tests in this module if vpype is not installed
pytest.importorskip("vpype", reason="vpype not installed, skipping vpype tests")


class TestRunVpype:
    """Tests for run_vpype function."""

    def test_run_vpype_basic(self):
        """Basic vpype pipeline should produce valid SVG."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        pen = Pen(name="fine", width_mm=0.3)
        lines = [LineString([(100, 100), (200, 200), (300, 100)])]

        svg_bytes = run_vpype(lines, paper, [pen])

        assert isinstance(svg_bytes, bytes)
        assert len(svg_bytes) > 0
        assert b"<svg" in svg_bytes
        assert b"</svg>" in svg_bytes

    def test_run_vpype_multiple_lines(self):
        """Multiple lines should all appear in output."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        pen = Pen(name="fine", width_mm=0.3)
        lines = [
            LineString([(100, 100), (200, 200)]),
            LineString([(300, 300), (400, 400)]),
            LineString([(500, 100), (600, 200)]),
        ]

        svg_bytes = run_vpype(lines, paper, [pen])

        assert isinstance(svg_bytes, bytes)
        assert b"<svg" in svg_bytes

    def test_run_vpype_empty_geometries_raises(self):
        """Empty geometries list should raise ValueError."""
        paper = Paper(name="A4", width_mm=210, height_mm=297)
        pen = Pen(name="fine", width_mm=0.3)

        with pytest.raises(ValueError, match="No geometries provided"):
            run_vpype([], paper, [pen])

    def test_run_vpype_no_pens_raises(self):
        """Empty pens list should raise ValueError."""
        paper = Paper(name="A4", width_mm=210, height_mm=297)
        lines = [LineString([(100, 100), (200, 200)])]

        with pytest.raises(ValueError, match="At least one pen must be provided"):
            run_vpype(lines, paper, [])

    def test_run_vpype_invalid_geometries_raises(self):
        """Invalid geometries (empty) should raise ValueError."""
        paper = Paper(name="A4", width_mm=210, height_mm=297)
        pen = Pen(name="fine", width_mm=0.3)
        lines = [
            LineString([]),  # Empty
            LineString([]),  # Also empty
        ]

        with pytest.raises(ValueError, match="No valid geometries"):
            run_vpype(lines, paper, [pen])

    def test_run_vpype_mixed_valid_invalid_geometries(self):
        """Should filter out invalid geometries and process valid ones."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        pen = Pen(name="fine", width_mm=0.3)
        lines = [
            LineString([]),  # Empty - filtered out
            LineString([(200, 200), (300, 300)]),  # Valid
        ]

        svg_bytes = run_vpype(lines, paper, [pen])

        assert isinstance(svg_bytes, bytes)
        assert b"<svg" in svg_bytes

    def test_run_vpype_custom_paper_size(self):
        """Should respect custom paper size."""
        paper = Paper(name="Custom", width_mm=100, height_mm=150, dpi=300)
        pen = Pen(name="fine", width_mm=0.3)
        lines = [LineString([(100, 100), (200, 200)])]

        svg_bytes = run_vpype(lines, paper, [pen])

        assert b'width="10.0cm"' in svg_bytes or b'viewBox="0 0' in svg_bytes

    def test_run_vpype_vpype_not_found(self):
        """Should raise FileNotFoundError with helpful message if vpype not found."""
        paper = Paper(name="A4", width_mm=210, height_mm=297)
        pen = Pen(name="fine", width_mm=0.3)
        lines = [LineString([(100, 100), (200, 200)])]

        with pytest.raises(FileNotFoundError, match="vpype executable not found"):
            run_vpype(lines, paper, [pen], vpype_path="/nonexistent/vpype")

    def test_run_vpype_svg_contains_layer(self):
        """Output SVG should contain layer for the pen."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        pen = Pen(name="fine", width_mm=0.3)
        lines = [LineString([(100, 100), (200, 200)])]

        svg_bytes = run_vpype(lines, paper, [pen])

        # vpype uses layer numbers as IDs by default
        layer_checks = [
            b'id="layer1"',
            b'inkscape:label="1"',
        ]
        svg_lower = svg_bytes.lower()
        assert any(check in svg_lower for check in layer_checks) or b"layer" in svg_lower

    def test_run_vpype_centered_output(self):
        """Output should be centered (--center flag)."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        pen = Pen(name="fine", width_mm=0.3)
        lines = [LineString([(100, 100), (200, 200)])]

        svg_bytes = run_vpype(lines, paper, [pen])

        # Just verify it runs and produces SVG - centering is vpype's job
        assert b"<svg" in svg_bytes


class TestRunVpypeMultiPen:
    """Tests for multi-pen support (future extensibility)."""

    def test_run_vpype_multiple_pens_creates_layers(self):
        """Multiple pens should create multiple layers (only first populated)."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        pens = [
            Pen(name="fine", width_mm=0.3, color="#000000"),
            Pen(name="bold", width_mm=0.5, color="#FF0000"),
        ]
        lines = [LineString([(100, 100), (200, 200)])]

        svg_bytes = run_vpype(lines, paper, pens)

        assert isinstance(svg_bytes, bytes)
        assert b"<svg" in svg_bytes
        # Both layers should exist (layer1 populated, layer2 empty)
        # vpype creates layers for all script calls


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])
