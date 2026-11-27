"""Integration test for full pipeline: photo → filter → sketch lines → geometry
optimize → vpype → penpath SVG.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from PIL import Image
from shapely import LineString

from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings, sketch_lines
from penpath.core.geometry.pipeline import optimize
from penpath.core.image.filters import grayscale, threshold
from penpath.core.image.load import load_image
from penpath.core.models import Paper, Pen
from penpath.core.output.svg import write_penpath_svg
from penpath.core.output.vpype import optimize_with_vpype

pytest.importorskip("vpype", reason="vpype not installed, skipping integration tests")

SVG_NS = "{http://www.w3.org/2000/svg}"


class TestFullPipelineIntegration:
    """Integration tests for the complete photo-to-SVG pipeline."""

    @pytest.fixture
    def synthetic_image(self, tmp_path: Path) -> Path:
        """Create a simple synthetic test image with a gradient."""
        img_path = tmp_path / "test_input.png"
        img = Image.new("RGB", (200, 200), "white")
        pixels = img.load()
        for y in range(200):
            for x in range(200):
                val = int(255 * (1 - (x + y) / 400))
                if 50 < x < 150 and 50 < y < 150:
                    val = int(val * 0.3)
                pixels[x, y] = (val, val, val)
        img.save(img_path)
        return img_path

    def test_full_pipeline_photo_to_svg(self, synthetic_image: Path, tmp_path: Path):
        """Round-trip: photo → filters → sketch lines → optimize → vpype → penpath SVG."""
        image = load_image(synthetic_image)
        assert image.size == (200, 200)

        gray = grayscale(image)
        thresholded = threshold(gray, level=128, dither=False)

        settings = SketchLinesSettings(
            line_density=0.5,
            min_length=5.0,
            max_length=30.0,
            angle_range=(0.0, 360.0),
            shading_enabled=True,
            squiggle_enabled=False,
            erase_enabled=False,
            seed=42,
            search_angle_step=10.0,
            sample_step=10.0,
        )
        lines = sketch_lines(thresholded, settings)

        assert len(lines) > 0
        assert all(isinstance(line, LineString) for line in lines)
        assert all(line.is_valid for line in lines)

        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        optimized_lines = optimize(
            lines,
            paper,
            simplify_tol_mm=0.1,
            merge_angle_deg=5.0,
            merge_dist_mm=0.5,
        )

        assert len(optimized_lines) > 0
        assert all(line.is_valid for line in optimized_lines)

        pen = Pen(name="fine", width_mm=0.3, color="#000000")
        strokes = optimize_with_vpype([optimized_lines], paper, [pen])[0]
        assert strokes

        output = tmp_path / "plot.svg"
        write_penpath_svg(
            [[LineString(stroke.polyline) for stroke in strokes]],
            paper,
            [pen],
            output,
        )

        root = ET.parse(output).getroot()
        assert root.get("width") == "210mm"
        assert root.get("height") == "297mm"
        assert root.get("viewBox") == "0 0 210 297"
        assert root.findall(SVG_NS + "rect") == []
        groups = list(root.iter(SVG_NS + "g"))
        assert len(groups) == 1
        assert groups[0].get("id") == "layer1"
        assert root.find(".//" + SVG_NS + "path") is not None

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

        assert len(optimized_lines) <= initial_count * 2

        pen = Pen(name="fine", width_mm=0.3)
        strokes = optimize_with_vpype([optimized_lines], paper, [pen])[0]

        assert len(strokes) > 0
        assert len(strokes) <= len(optimized_lines) * 2

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

        geometry: list[list[tuple[float, float]]] = []
        for _ in range(2):
            lines = sketch_lines(thresholded, settings)
            optimized = optimize(lines, paper)
            strokes = optimize_with_vpype([optimized], paper, [pen])[0]
            geometry.append([point for stroke in strokes for point in stroke.polyline])

        assert geometry[0] == geometry[1], "Geometry should be deterministic with same seed"

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
            strokes = optimize_with_vpype([optimized_lines], paper, [pen])[0]

            assert strokes
            points = [point for stroke in strokes for point in stroke.polyline]
            assert max(point[0] for point in points) <= paper.width_mm + 0.1
            assert max(point[1] for point in points) <= paper.height_mm + 0.1


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])
