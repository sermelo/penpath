"""Unit tests for SVG export."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from shapely import LineString

from penpath.core.image.resolution import WorkingResolution
from penpath.core.models import Paper, Pen
from penpath.core.output.svg import (
    PENPATH_NAMESPACE,
    ImagePlacement,
    add_placement_metadata,
    export_pen_layers,
    export_svg,
    fit_image_placement,
    write_penpath_svg,
)

SVG_NS = "{http://www.w3.org/2000/svg}"
INKSCAPE_NS = "{http://www.inkscape.org/namespaces/inkscape}"


def _layer_groups(root: ET.Element) -> list[ET.Element]:
    """Return the Inkscape layer groups in document order."""
    return [
        group
        for group in root.iter(SVG_NS + "g")
        if group.get(INKSCAPE_NS + "groupmode") == "layer"
    ]


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
        """Root width, height and viewBox are all in millimetres."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        pen = Pen(name="fine", width_mm=0.3)
        lines = [LineString([(100, 100), (200, 200)])]

        output_path = tmp_path / "output.svg"
        export_svg(lines, paper, [pen], output_path)

        root = ET.parse(output_path).getroot()
        assert root.get("width") == "210mm"
        assert root.get("height") == "297mm"
        assert root.get("viewBox") == "0 0 210 297"

    def test_export_svg_has_no_background_shape(self, tmp_path: Path):
        """The paper colour is not written as a shape vpype could plot."""
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

        root = ET.parse(output_path).getroot()
        assert list(root.iter(SVG_NS + "rect")) == []
        assert not any(
            child.tag.rsplit("}", 1)[-1] in {"rect", "circle", "ellipse", "polygon"}
            for child in root
        )
        assert "#FF0000" not in output_path.read_text()
        assert [group.get(INKSCAPE_NS + "label") for group in _layer_groups(root)] == ["fine"]

    def test_export_svg_pen_layer(self, tmp_path: Path):
        """The used pen gets a numbered layer labelled with its name."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        pen = Pen(name="fine", width_mm=0.3, color="#0000FF")
        lines = [LineString([(100, 100), (200, 200)])]

        output_path = tmp_path / "output.svg"
        export_svg(lines, paper, [pen], output_path)

        root = ET.parse(output_path).getroot()
        layers = _layer_groups(root)
        assert len(layers) == 1
        assert layers[0].get("id") == "layer1"
        assert layers[0].get(INKSCAPE_NS + "label") == "fine"

    def test_export_svg_stroke_properties(self, tmp_path: Path):
        """Paths use a hex stroke, no fill and a millimetre stroke width."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        pen = Pen(name="bold", width_mm=0.5, color="#FF0000", opacity=0.8)
        lines = [LineString([(100, 100), (200, 200)])]

        output_path = tmp_path / "output.svg"
        export_svg(lines, paper, [pen], output_path)

        root = ET.parse(output_path).getroot()
        path = root.find(".//" + SVG_NS + "path")
        assert path is not None
        assert path.get("fill") == "none"
        assert path.get("stroke") == "#FF0000"
        assert path.get("stroke-width") == "0.5"
        assert path.get("stroke-opacity") == "0.8"
        assert path.get("stroke-linecap") == "round"
        assert path.get("stroke-linejoin") == "round"

    def test_export_svg_multiple_pens_only_used_pens_get_layers(self, tmp_path: Path):
        """Only pens with geometry get a layer, numbered in drawing order."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        pens = [
            Pen(name="fine", width_mm=0.3, color="#000000"),
            Pen(name="bold", width_mm=0.5, color="#FF0000"),
        ]
        lines = [LineString([(100, 100), (200, 200)])]

        output_path = tmp_path / "output.svg"
        export_svg(lines, paper, pens, output_path)

        root = ET.parse(output_path).getroot()
        layers = _layer_groups(root)
        assert [layer.get("id") for layer in layers] == ["layer1"]
        assert [layer.get(INKSCAPE_NS + "label") for layer in layers] == ["fine"]

    def test_export_svg_coordinate_scaling(self, tmp_path: Path):
        """Geometries are scaled from image coords to paper millimetres."""
        paper = Paper(name="square", width_mm=100, height_mm=100, margin_mm=10, dpi=300)
        pen = Pen(name="fine", width_mm=0.3)
        lines = [LineString([(1500, 1500), (3000, 3000)])]

        output_path = tmp_path / "output.svg"
        export_svg(lines, paper, [pen], output_path, image_dpi=300)

        root = ET.parse(output_path).getroot()
        path = root.find(".//" + SVG_NS + "path")
        assert path is not None
        numbers = [
            float(number)
            for number in path.get("d", "").replace("M", " ").replace("L", " ").split()
        ]
        assert numbers
        assert all(10 <= number <= 90 for number in numbers)

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
            LineString([]),
            LineString([]),
        ]

        output_path = tmp_path / "output.svg"
        with pytest.raises(ValueError, match="No valid geometries"):
            export_svg(lines, paper, [pen], output_path)

    def test_export_svg_mixed_valid_invalid_geometries(self, tmp_path: Path):
        """Should filter out invalid geometries and process valid ones."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        pen = Pen(name="fine", width_mm=0.3)
        lines = [
            LineString([]),
            LineString([(200, 200), (300, 300)]),
        ]

        output_path = tmp_path / "output.svg"
        export_svg(lines, paper, [pen], output_path)

        assert root_has_path(output_path)

    def test_export_svg_custom_paper_size(self, tmp_path: Path):
        """Should respect custom paper size."""
        paper = Paper(name="Custom", width_mm=100, height_mm=150, dpi=300)
        pen = Pen(name="fine", width_mm=0.3)
        lines = [LineString([(100, 100), (200, 200)])]

        output_path = tmp_path / "output.svg"
        export_svg(lines, paper, [pen], output_path)

        root = ET.parse(output_path).getroot()
        assert root.get("width") == "100mm"
        assert root.get("height") == "150mm"
        assert root.get("viewBox") == "0 0 100 150"

    def test_export_svg_margin_respected(self, tmp_path: Path):
        """Margins should be respected in coordinate scaling."""
        paper = Paper(name="A4", width_mm=200, height_mm=200, margin_mm=20, dpi=300)
        pen = Pen(name="fine", width_mm=0.3)
        lines = [LineString([(100, 100), (200, 200)])]

        output_path = tmp_path / "output.svg"
        export_svg(lines, paper, [pen], output_path)

        root = ET.parse(output_path).getroot()
        assert root.get("viewBox") == "0 0 200 200"

    def test_export_svg_pen_opacity(self, tmp_path: Path):
        """Pen opacity should be applied to stroke-opacity."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        pen = Pen(name="fine", width_mm=0.3, color="#000000", opacity=0.5)
        lines = [LineString([(100, 100), (200, 200)])]

        output_path = tmp_path / "output.svg"
        export_svg(lines, paper, [pen], output_path)

        path = ET.parse(output_path).getroot().find(".//" + SVG_NS + "path")
        assert path is not None
        assert path.get("stroke-opacity") == "0.5"

    def test_export_svg_named_color_becomes_hex(self, tmp_path: Path):
        """Penpath writes the pen colour as hex even when given a CSS name."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        pen = Pen(name="red_fine", width_mm=0.3, color="red")
        lines = [LineString([(100, 100), (200, 200)])]

        output_path = tmp_path / "output.svg"
        export_svg(lines, paper, [pen], output_path)

        path = ET.parse(output_path).getroot().find(".//" + SVG_NS + "path")
        assert path is not None
        assert path.get("stroke") == "#FF0000"

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
        """Exported SVG should be valid XML with one layer per used pen."""
        paper = Paper(name="A4", width_mm=210, height_mm=297, dpi=300)
        pen = Pen(name="fine", width_mm=0.3)
        lines = [
            LineString([(100, 100), (200, 200)]),
            LineString([(300, 100), (400, 200)]),
        ]

        output_path = tmp_path / "output.svg"
        export_svg(lines, paper, [pen], output_path)

        root = ET.parse(output_path).getroot()
        assert root.tag.endswith("svg")
        assert [layer.get("id") for layer in _layer_groups(root)] == ["layer1"]


class TestWritePenpathSvg:
    """Tests for the shared writer used by both export paths."""

    def test_write_penpath_svg_numbers_used_pens_in_drawing_order(self, tmp_path: Path) -> None:
        """Every used pen gets layerN with its own name, colour and width."""
        paper = Paper(name="A4", width_mm=210, height_mm=297)
        pens = [
            Pen(name="red", width_mm=0.3, color="#FF0000"),
            Pen(name="unused", width_mm=0.5, color="#00FF00"),
            Pen(name="blue", width_mm=0.4, color="#0000FF"),
        ]
        lines = [
            [LineString([(10, 10), (20, 20)])],
            [],
            [LineString([(30, 30), (40, 40)])],
        ]
        output_path = tmp_path / "layers.svg"

        write_penpath_svg(lines, paper, pens, output_path)

        root = ET.parse(output_path).getroot()
        layers = _layer_groups(root)
        assert [layer.get("id") for layer in layers] == ["layer1", "layer2"]
        assert [layer.get(INKSCAPE_NS + "label") for layer in layers] == ["red", "blue"]
        strokes = [layer.find(SVG_NS + "path").get("stroke") for layer in layers]
        assert strokes == ["#FF0000", "#0000FF"]
        widths = [layer.find(SVG_NS + "path").get("stroke-width") for layer in layers]
        assert widths == ["0.3", "0.4"]

    def test_write_penpath_svg_rejects_mismatched_pen_counts(self, tmp_path: Path) -> None:
        """One geometry entry per pen is required."""
        paper = Paper(name="A4", width_mm=210, height_mm=297)
        pens = [Pen(name="fine", width_mm=0.3)]

        with pytest.raises(ValueError, match="one entry per pen"):
            write_penpath_svg([], paper, pens, tmp_path / "bad.svg")


class TestExportPenLayers:
    """Per-pen geometry maps into each pen's own layer, never across pens."""

    def test_export_pen_layers_skips_unused_pens_in_drawing_order(self, tmp_path: Path) -> None:
        paper = Paper(name="A4", width_mm=210, height_mm=297)
        pens = [
            Pen(name="red", width_mm=0.4, color="#FF0000"),
            Pen(name="unused", width_mm=0.4, color="#00FF00"),
            Pen(name="blue", width_mm=0.4, color="#0000FF"),
        ]
        placement = ImagePlacement(10.0, 20.0, 100.0, 50.0)
        output_path = tmp_path / "layers.svg"

        export_pen_layers(
            [
                [LineString([(0, 0), (50, 50)])],
                [],
                [LineString([(50, 0), (100, 50)])],
            ],
            paper,
            pens,
            output_path,
            image_placement=placement,
            image_size_px=(100, 100),
        )

        root = ET.parse(output_path).getroot()
        layers = _layer_groups(root)
        assert [layer.get("id") for layer in layers] == ["layer1", "layer2"]
        assert [layer.get(INKSCAPE_NS + "label") for layer in layers] == ["red", "blue"]
        assert [
            layer.find(SVG_NS + "path").get("stroke")  # type: ignore[union-attr]
            for layer in layers
        ] == ["#FF0000", "#0000FF"]

    def test_export_pen_layers_rejects_mismatched_pen_counts(self, tmp_path: Path) -> None:
        paper = Paper(name="A4", width_mm=210, height_mm=297)
        pens = [Pen(name="red", width_mm=0.4), Pen(name="blue", width_mm=0.4)]
        with pytest.raises(ValueError, match="one entry per pen"):
            export_pen_layers(
                [[]],
                paper,
                pens,
                tmp_path / "bad.svg",
                ImagePlacement(0, 0, 100, 100),
                (100, 100),
            )


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
        """Stroke coordinates are the placement rectangle, in millimetres."""
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
        paths = list(root.iter(SVG_NS + "path"))
        assert len(paths) == 1
        path_data = paths[0].attrib["d"]
        assert "M 10.000 20.000" in path_data
        assert "L 60.000 45.000" in path_data

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


class TestResolutionMetadata:
    """Both SVG writers record the working and source image sizes."""

    @staticmethod
    def _resolution() -> WorkingResolution:
        return WorkingResolution(
            source_size_px=(4080, 3072),
            target_size_px=(475, 358),
            scale=0.116,
            working_px=475,
            paper_side_mm=190.0,
            pen_width_mm=0.4,
        )

    @staticmethod
    def _expected_attributes() -> dict[str, str]:
        return {
            "x": "10.0000",
            "y": "20.0000",
            "width": "190.0000",
            "height": "100.0000",
            "image-width": "475",
            "image-height": "358",
            "source-width": "4080",
            "source-height": "3072",
        }

    def test_export_svg_writes_resolution_attributes(self, tmp_path: Path) -> None:
        paper = Paper(name="A4", width_mm=210, height_mm=297)
        pen = Pen(name="fine", width_mm=0.3)
        placement = ImagePlacement(10.0, 20.0, 190.0, 100.0)
        output_path = tmp_path / "downscaled.svg"

        export_svg(
            [LineString([(0, 0), (100, 100)])],
            paper,
            [pen],
            output_path,
            image_placement=placement,
            image_size_px=(475, 358),
            resolution=self._resolution(),
        )

        metadata = (
            ET.parse(output_path).getroot().find(f".//{{{PENPATH_NAMESPACE}}}image-placement")
        )
        assert metadata is not None
        assert metadata.attrib == self._expected_attributes()

    def test_add_placement_metadata_writes_resolution_attributes(self, tmp_path: Path) -> None:
        paper = Paper(name="A4", width_mm=210, height_mm=297)
        pen = Pen(name="fine", width_mm=0.3)
        placement = ImagePlacement(10.0, 20.0, 190.0, 100.0)
        output_path = tmp_path / "vpype.svg"
        export_svg([LineString([(0, 0), (100, 100)])], paper, [pen], output_path)

        add_placement_metadata(output_path, placement, self._resolution())

        metadata = (
            ET.parse(output_path).getroot().find(f".//{{{PENPATH_NAMESPACE}}}image-placement")
        )
        assert metadata is not None
        assert metadata.attrib == self._expected_attributes()

    def test_add_placement_metadata_stays_idempotent_with_resolution(self, tmp_path: Path) -> None:
        paper = Paper(name="A4", width_mm=210, height_mm=297)
        pen = Pen(name="fine", width_mm=0.3)
        output_path = tmp_path / "vpype.svg"
        export_svg([LineString([(0, 0), (100, 100)])], paper, [pen], output_path)

        add_placement_metadata(output_path, (10.0, 20.0, 190.0, 100.0), self._resolution())
        add_placement_metadata(output_path, (10.0, 20.0, 190.0, 100.0), self._resolution())

        assert output_path.read_text().count("image-placement") == 1


def root_has_path(svg_path: Path) -> bool:
    """Return whether an SVG contains at least one path element."""
    root = ET.parse(svg_path).getroot()
    return root.find(".//" + SVG_NS + "path") is not None


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])
