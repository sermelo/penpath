"""Integration test for full pipeline: photo → filter → sketch lines → geometry
optimize → vpype → SVG."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from shapely import LineString

from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings, sketch_lines
from penpath.core.geometry.pipeline import optimize
from penpath.core.image.filters import grayscale, threshold
from penpath.core.image.load import load_image
from penpath.core.models import Paper, Pen
from penpath.core.output.vpype import run_vpype


class TestFullPipelineIntegration:
    """Integration tests for the complete photo-to-SVG pipeline."""

    @pytest.fixture
    def synthetic_image(self, tmp_path: Path) -> Path:
        """Create a simple synthetic test image with a gradient."""
        img_path = tmp_path / "test_input.png"
        # Create a 200x200 gradient image
        img = Image.new("RGB", (200, 200), "white")
        pixels = img.load()
        for y in range(200):
            for x in range(200):
                # Create a diagonal gradient with a dark region
                val = int(255 * (1 - (x + y) / 400))
                if 50 < x < 150 and 50 < y < 150:
                    val = int(val * 0.3)  # Dark square in center
                pixels[x, y] = (val, val, val)
        img.save(img_path)
        return img_path

    def test_full_pipeline_photo_to_svg(self, synthetic_image: Path):
        """Round-trip: photo → filter → sketch lines → geometry optimize → vpype → SVG."""
        # 1. Load image
        image = load_image(synthetic_image)
        assert image.size == (200, 200)

        # 2. Apply filters: grayscale + threshold
        gray = grayscale(image)
        thresholded = threshold(gray, level=128, dither=False)

        # 3. Generate sketch lines
        settings = SketchLinesSettings(
            line_density=0.5,
            min_length=5.0,
            max_length=30.0,
            angle_range=(0.0, 360.0),
            shading_enabled=True,
            squiggle_enabled=False,  # Disable for predictable test
            erase_enabled=False,
            seed=42,  # Deterministic
            search_angle_step=10.0,
            sample_step=10.0,
        )
        lines = sketch_lines(thresholded, settings)

        # Should generate some lines
        assert len(lines) > 0
        assert all(isinstance(line, LineString) for line in lines)
        assert all(line.is_valid for line in lines)

        # 4. Optimize geometry
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        optimized_lines = optimize(
            lines,
            paper,
            simplify_tol_mm=0.1,
            merge_angle_deg=5.0,
            merge_dist_mm=0.5,
        )

        # Optimization should not increase line count significantly
        # (may decrease due to merging, or increase slightly due to splitting)
        assert len(optimized_lines) > 0
        assert all(line.is_valid for line in optimized_lines)

        # 5. Run vpype pipeline to produce SVG
        pen = Pen(name="fine", width_mm=0.3, color="#000000")
        svg_bytes = run_vpype(optimized_lines, paper, [pen])

        # 6. Verify SVG output
        assert isinstance(svg_bytes, bytes)
        assert len(svg_bytes) > 0
        assert b"<svg" in svg_bytes
        assert b"</svg>" in svg_bytes
        assert b"viewBox" in svg_bytes
        assert b"210" in svg_bytes  # Page width in mm
        assert b"297" in svg_bytes  # Page height in mm

        # Verify we can parse the SVG and it has reasonable content
        import xml.etree.ElementTree as ET

        root = ET.fromstring(svg_bytes)
        assert root.tag.endswith("svg")
        # Should have at least one path or group
        has_content = any(
            elem.tag.endswith(("path", "g", "line", "polyline")) for elem in root.iter()
        )
        assert has_content

    def test_full_pipeline_geometry_count_preserved(self, synthetic_image: Path):
        """Verify geometry count is reasonable through the pipeline."""
        image = load_image(synthetic_image)
        gray = grayscale(image)
        thresholded = threshold(gray, level=128, dither=False)

        settings = SketchLinesSettings(
            line_density=0.3,
            min_length=10.0,
            max_length=50.0,
            angle_range=(0.0, 360.0),
            shading_enabled=False,
            squiggle_enabled=False,
            erase_enabled=False,
            seed=123,
        )
        lines = sketch_lines(thresholded, settings)
        initial_count = len(lines)

        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        optimized_lines = optimize(lines, paper, simplify_tol_mm=0.1)

        # Optimization should reduce or maintain line count (merging)
        # but not explode it
        assert len(optimized_lines) <= initial_count * 2  # Allow some splitting

        pen = Pen(name="fine", width_mm=0.3)
        svg_bytes = run_vpype(optimized_lines, paper, [pen])

        # Parse SVG and count paths
        import xml.etree.ElementTree as ET

        root = ET.fromstring(svg_bytes)

        # Count path/polyline elements (vpype may output either)
        path_count = sum(1 for elem in root.iter() if elem.tag.endswith(("path", "polyline")))

        # vpype's linemerge/linesort may further reduce count
        # Just verify we have some output
        assert path_count > 0
        assert path_count <= len(optimized_lines) * 2  # Sanity check

    def test_full_pipeline_deterministic_with_seed(self, synthetic_image: Path):
        """Same seed should produce identical geometry output."""
        image = load_image(synthetic_image)
        gray = grayscale(image)
        thresholded = threshold(gray, level=128, dither=False)

        settings = SketchLinesSettings(
            line_density=0.5,
            min_length=5.0,
            max_length=30.0,
            seed=42,
            squiggle_enabled=False,
            erase_enabled=False,
        )

        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        pen = Pen(name="fine", width_mm=0.3)

        # Run pipeline twice
        lines1 = sketch_lines(thresholded, settings)
        opt1 = optimize(lines1, paper)
        svg1 = run_vpype(opt1, paper, [pen])

        lines2 = sketch_lines(thresholded, settings)
        opt2 = optimize(lines2, paper)
        svg2 = run_vpype(opt2, paper, [pen])

        # SVG metadata (timestamps, temp paths) will differ, but geometry should be identical
        # Parse and compare polyline points
        import xml.etree.ElementTree as ET

        def extract_polyline_points(svg_bytes: bytes) -> list[str]:
            root = ET.fromstring(svg_bytes)
            points = []
            for elem in root.iter():
                if elem.tag.endswith("polyline") and "points" in elem.attrib:
                    points.append(elem.attrib["points"])
            return points

        points1 = extract_polyline_points(svg1)
        points2 = extract_polyline_points(svg2)

        assert points1 == points2, "Geometry should be deterministic with same seed"

    def test_full_pipeline_different_paper_sizes(self, synthetic_image: Path):
        """Pipeline should work with different paper sizes."""
        image = load_image(synthetic_image)
        gray = grayscale(image)
        thresholded = threshold(gray, level=128, dither=False)

        settings = SketchLinesSettings(
            line_density=0.5,
            min_length=5.0,
            max_length=30.0,
            seed=42,
            squiggle_enabled=False,
            erase_enabled=False,
        )

        papers = [
            Paper(name="A4", width_mm=210, height_mm=297),
            Paper(name="A3", width_mm=297, height_mm=420),
            Paper(name="Letter", width_mm=215.9, height_mm=279.4),
            Paper(name="Custom", width_mm=100, height_mm=100),
        ]

        pen = Pen(name="fine", width_mm=0.3)

        for paper in papers:
            lines = sketch_lines(thresholded, settings)
            optimized_lines = optimize(lines, paper)
            svg_bytes = run_vpype(optimized_lines, paper, [pen])

            assert isinstance(svg_bytes, bytes)
            assert b"<svg" in svg_bytes
            # Verify page size in SVG
            width_str = str(int(paper.width_mm)).encode()
            alt_width_str = str(paper.width_mm).encode()
            assert width_str in svg_bytes or alt_width_str in svg_bytes


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])
