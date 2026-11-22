"""Unit tests for SVG stroke parsing and image placement metadata."""

from __future__ import annotations

from pathlib import Path

import pytest
from shapely import LineString

from penpath.core.models import Paper, Pen
from penpath.core.output.svg import ImagePlacement, export_svg, fit_image_placement
from penpath.core.svg_parse import get_image_placement, parse_svg_strokes


def _paper() -> Paper:
    return Paper(name="square", width_mm=100, height_mm=100)


def _pen() -> Pen:
    return Pen(name="fine", width_mm=0.3, color="#000000")


def _export_with_placement(
    svg_path: Path,
    placement: ImagePlacement,
    image_size_px: tuple[int, int] = (100, 50),
    lines: list[LineString] | None = None,
) -> None:
    export_svg(
        lines if lines is not None else [LineString([(0, 0), (100, 50)])],
        _paper(),
        [_pen()],
        svg_path,
        image_size_px=image_size_px,
        image_placement=placement,
    )


class TestGetImagePlacement:
    def test_get_image_placement_uses_metadata(self, tmp_path: Path) -> None:
        """Placement stored as metadata is returned unchanged."""
        placement = ImagePlacement(12.5, 7.25, 80.0, 40.0)
        svg_path = tmp_path / "placed.svg"
        _export_with_placement(svg_path, placement)

        assert get_image_placement(svg_path, (100, 50)) == pytest.approx(placement)

    def test_get_image_placement_fallback_centers_and_preserves_aspect(
        self, tmp_path: Path
    ) -> None:
        """Without metadata, the image is fitted to the page and centered."""
        svg_path = tmp_path / "plain.svg"
        svg_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="200mm" height="100mm" '
            'viewBox="0 0 200 100"></svg>'
        )

        placement = get_image_placement(svg_path, (100, 100))

        assert placement == pytest.approx(ImagePlacement(50.0, 0.0, 100.0, 100.0))

    def test_get_image_placement_fallback_reads_unitless_viewbox(self, tmp_path: Path) -> None:
        """A viewBox in 96-DPI units maps to the correct page size in mm."""
        svg_path = tmp_path / "unitless.svg"
        svg_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="793.7008" height="377.9528" '
            'viewBox="0 0 793.7008 377.9528"></svg>'
        )

        placement = get_image_placement(svg_path, (100, 100))

        assert placement.x == pytest.approx(55.0, abs=0.01)
        assert placement.y == pytest.approx(0.0, abs=0.01)
        assert placement.width == pytest.approx(100.0, abs=0.01)
        assert placement.height == pytest.approx(100.0, abs=0.01)

    def test_get_image_placement_reads_data_attributes(self, tmp_path: Path) -> None:
        """The data-penpath-* variant of the metadata is also supported."""
        svg_path = tmp_path / "attrs.svg"
        svg_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
            'data-penpath-x="5" data-penpath-y="10" '
            'data-penpath-width="30" data-penpath-height="20"></svg>'
        )

        assert get_image_placement(svg_path, (100, 50)) == ImagePlacement(5, 10, 30, 20)

    def test_get_image_placement_invalid_image_size_raises(self, tmp_path: Path) -> None:
        """A zero-sized image cannot be fitted to the page."""
        svg_path = tmp_path / "plain.svg"
        svg_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm"></svg>'
        )

        with pytest.raises(ValueError, match="positive width and height"):
            get_image_placement(svg_path, (0, 50))


class TestParseSvgStrokes:
    def test_parse_svg_strokes_from_penpath_export(self, tmp_path: Path) -> None:
        """Exported paths come back as strokes in paper millimetres."""
        placement = ImagePlacement(10.0, 20.0, 80.0, 40.0)
        svg_path = tmp_path / "placed.svg"
        _export_with_placement(svg_path, placement)

        strokes = parse_svg_strokes(svg_path)

        assert len(strokes) == 1
        stroke = strokes[0]
        assert stroke.width_mm == pytest.approx(0.3)
        assert stroke.color == "#000000"
        assert stroke.pen_up is False
        assert stroke.polyline[0] == pytest.approx((10.0, 20.0), abs=0.01)
        assert stroke.polyline[-1] == pytest.approx((90.0, 60.0), abs=0.01)

    def test_parse_svg_strokes_ignores_background(self, tmp_path: Path) -> None:
        """The paper background rect is not a pen stroke."""
        svg_path = tmp_path / "placed.svg"
        _export_with_placement(svg_path, ImagePlacement(0, 0, 100, 50))

        strokes = parse_svg_strokes(svg_path)

        assert all(stroke.polyline for stroke in strokes)
        assert len(strokes) == 1

    def test_parse_svg_strokes_multiple_subpaths(self, tmp_path: Path) -> None:
        """Each move-to starts a new stroke."""
        svg_path = tmp_path / "subpaths.svg"
        svg_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
            'viewBox="0 0 100 100">'
            '<path d="M 10 10 L 20 20 M 30 30 L 40 40" fill="none" '
            'stroke="#000000" stroke-width="1mm"/>'
            "</svg>"
        )

        strokes = parse_svg_strokes(svg_path)

        assert len(strokes) == 2
        assert strokes[0].polyline == [(10.0, 10.0), (20.0, 20.0)]
        assert strokes[1].polyline == [(30.0, 30.0), (40.0, 40.0)]
        assert strokes[0].width_mm == pytest.approx(1.0)

    def test_parse_svg_strokes_polyline_with_group_transform(self, tmp_path: Path) -> None:
        """Polylines and ancestor transforms are handled."""
        svg_path = tmp_path / "polyline.svg"
        svg_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
            'viewBox="0 0 100 100">'
            '<g transform="translate(5 7)">'
            '<polyline points="10,10 20,10 20,20" fill="none" stroke="red" '
            'stroke-width="0.5"/>'
            "</g></svg>"
        )

        strokes = parse_svg_strokes(svg_path)

        assert len(strokes) == 1
        assert strokes[0].polyline == [(15.0, 17.0), (25.0, 17.0), (25.0, 27.0)]
        assert strokes[0].color == "#FF0000"
        assert strokes[0].width_mm == pytest.approx(0.5)

    def test_parse_svg_strokes_skips_hidden_and_filled_shapes(self, tmp_path: Path) -> None:
        """Only visible, non-filled geometry becomes a stroke."""
        svg_path = tmp_path / "mixed.svg"
        svg_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
            'viewBox="0 0 100 100">'
            '<defs><path d="M 0 0 L 10 10" fill="none" stroke="#000000"/></defs>'
            '<path d="M 1 1 L 2 2" fill="#FF0000"/>'
            '<path d="M 3 3 L 4 4" fill="none" stroke="#000000" display="none"/>'
            '<path d="M 5 5 L 6 6" fill="none" stroke="#000000"/>'
            "</svg>"
        )

        strokes = parse_svg_strokes(svg_path)

        assert len(strokes) == 1
        assert strokes[0].polyline == [(5.0, 5.0), (6.0, 6.0)]

    def test_parse_svg_strokes_empty_svg(self, tmp_path: Path) -> None:
        """An SVG with no drawable geometry produces no strokes."""
        svg_path = tmp_path / "empty.svg"
        svg_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm"></svg>'
        )

        assert parse_svg_strokes(svg_path) == []


class TestPlacementConsistency:
    def test_same_drawing_at_two_placements_maps_to_identical_image_strokes(
        self, tmp_path: Path
    ) -> None:
        """Correct metadata makes a shifted drawing score the same.

        Mapping parsed strokes back through each SVG's own placement must
        recover the same image-space geometry. That is the property likeness
        scoring relies on when comparing the two plots with the original image.
        """
        lines = [LineString([(10, 5), (90, 45)])]
        placements = [
            ImagePlacement(5.0, 5.0, 90.0, 45.0),
            ImagePlacement(55.0, 30.0, 40.0, 20.0),
        ]
        image_space_strokes: list[list[tuple[float, float]]] = []

        for index, placement in enumerate(placements):
            svg_path = tmp_path / f"plot{index}.svg"
            _export_with_placement(svg_path, placement, lines=lines)

            parsed_placement = get_image_placement(svg_path, (100, 50))
            strokes = parse_svg_strokes(svg_path)
            assert len(strokes) == 1
            image_space_strokes.append(
                [
                    (
                        (point[0] - parsed_placement.x) * 100 / parsed_placement.width,
                        (point[1] - parsed_placement.y) * 50 / parsed_placement.height,
                    )
                    for point in strokes[0].polyline
                ]
            )

        for point_a, point_b in zip(image_space_strokes[0], image_space_strokes[1], strict=True):
            assert point_a == pytest.approx(point_b, abs=0.05)

    def test_fit_image_placement_uses_drawable_area_offset(self) -> None:
        """Placement within a margin is offset from the page origin."""
        placement = fit_image_placement(
            (100, 50),
            area_width_mm=180.0,
            area_height_mm=277.0,
            image_dpi=300,
            offset_x_mm=10.0,
            offset_y_mm=10.0,
        )

        assert placement.width == pytest.approx(180.0)
        assert placement.height == pytest.approx(90.0)
        assert placement.x == pytest.approx(10.0)
        assert placement.y == pytest.approx(10.0 + (277.0 - 90.0) / 2)
