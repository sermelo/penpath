"""Unit tests for SVG stroke parsing and image placement metadata."""

from __future__ import annotations

from pathlib import Path

import pytest
from shapely import LineString

from penpath.core.image.resolution import WorkingResolution
from penpath.core.models import Paper, Pen
from penpath.core.output.svg import ImagePlacement, export_svg, fit_image_placement
from penpath.core.simulation import compute_machine_cost
from penpath.core.svg_parse import get_image_placement, get_svg_paper_size, parse_svg_strokes


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

    def test_get_image_placement_ignores_resolution_attributes(self, tmp_path: Path) -> None:
        """The new image/source size attributes do not disturb placement reads."""
        placement = ImagePlacement(12.5, 7.25, 80.0, 40.0)
        resolution = WorkingResolution(
            source_size_px=(4080, 3072),
            target_size_px=(475, 358),
            scale=0.116,
            working_px=475,
            paper_side_mm=190.0,
            pen_width_mm=0.4,
        )
        svg_path = tmp_path / "downscaled.svg"
        export_svg(
            [LineString([(0, 0), (100, 50)])],
            _paper(),
            [_pen()],
            svg_path,
            image_size_px=(475, 358),
            image_placement=placement,
            resolution=resolution,
        )

        assert get_image_placement(svg_path, (4080, 3072)) == pytest.approx(placement)

    def test_get_image_placement_malformed_metadata_falls_back(self, tmp_path: Path) -> None:
        """A broken placement element is ignored in favour of the page fit."""
        svg_path = tmp_path / "badmeta.svg"
        svg_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'xmlns:penpath="http://penpath.org/ns/penpath" '
            'width="100mm" height="80mm" viewBox="0 0 100 80">'
            '<metadata><penpath:image-placement x="oops"/></metadata>'
            "</svg>"
        )

        assert get_image_placement(svg_path, (100, 100)) == pytest.approx(
            ImagePlacement(10.0, 0.0, 80.0, 80.0)
        )

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

    def test_penpath_mm_viewbox_gives_mm_paper_and_strokes(self, tmp_path: Path) -> None:
        """The parser derives a 1 mm/unit scale from the new root layout."""
        svg_path = tmp_path / "a4.svg"
        export_svg(
            [LineString([(0, 0), (10, 10)])],
            Paper(name="a4", width_mm=210, height_mm=297),
            [Pen(name="fine", width_mm=0.4, color="#000000")],
            svg_path,
        )

        assert get_svg_paper_size(svg_path) == pytest.approx((210.0, 297.0))
        strokes = parse_svg_strokes(svg_path)
        assert len(strokes) == 1
        assert strokes[0].width_mm == pytest.approx(0.4)

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

    def test_parse_svg_strokes_polygon_fill_none_closes_path(self, tmp_path: Path) -> None:
        """An unfilled polygon becomes a stroke including the closing edge."""
        svg_path = tmp_path / "polygon.svg"
        svg_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
            'viewBox="0 0 100 100">'
            '<polygon points="0,0 30,0 30,40" fill="none" stroke="#000000" '
            'stroke-width="1mm"/>'
            "</svg>"
        )

        strokes = parse_svg_strokes(svg_path)

        assert len(strokes) == 1
        assert strokes[0].polyline == [(0.0, 0.0), (30.0, 0.0), (30.0, 40.0), (0.0, 0.0)]
        assert strokes[0].width_mm == pytest.approx(1.0)
        cost = compute_machine_cost(strokes)
        assert cost["total"]["drawing_length_mm"] == pytest.approx(120.0)

    def test_parse_svg_strokes_polygon_with_fill_is_ignored(self, tmp_path: Path) -> None:
        """A filled polygon is a shape, not a stroke, even with a stroke colour."""
        svg_path = tmp_path / "filled.svg"
        svg_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
            'viewBox="0 0 100 100">'
            '<polygon points="0,0 30,0 30,40" fill="#FF0000" stroke="#000000"/>'
            '<polygon points="40,40 50,40 50,50" fill="black" stroke="#000000"/>'
            "</svg>"
        )

        assert parse_svg_strokes(svg_path) == []

    def test_parse_svg_strokes_polygon_inherits_fill_none(self, tmp_path: Path) -> None:
        """A polygon with no local fill uses the inherited group style."""
        svg_path = tmp_path / "grouped.svg"
        svg_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
            'viewBox="0 0 100 100">'
            '<g fill="none" stroke="#0000FF" stroke-width="2mm">'
            '<polygon points="10,10 20,10 20,20"/>'
            "</g></svg>"
        )

        strokes = parse_svg_strokes(svg_path)

        assert len(strokes) == 1
        assert strokes[0].color == "#0000FF"
        assert strokes[0].polyline[-1] == strokes[0].polyline[0]

    def test_parse_svg_strokes_polygon_already_closed_has_no_duplicate_point(
        self, tmp_path: Path
    ) -> None:
        """A polygon whose points repeat the first adds no zero-length edge."""
        svg_path = tmp_path / "closed.svg"
        svg_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
            'viewBox="0 0 100 100">'
            '<polygon points="0,0 30,0 30,40 0,0" fill="none" stroke="#000000"/>'
            "</svg>"
        )

        strokes = parse_svg_strokes(svg_path)

        assert len(strokes) == 1
        assert strokes[0].polyline == [(0.0, 0.0), (30.0, 0.0), (30.0, 40.0), (0.0, 0.0)]

    def test_parse_svg_strokes_unfilled_rect_stays_unparsed(self, tmp_path: Path) -> None:
        """Outline shapes other than polygons stay out of scope, even unfilled."""
        svg_path = tmp_path / "rect.svg"
        svg_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
            'viewBox="0 0 100 100">'
            '<rect x="10" y="10" width="80" height="80" fill="none" stroke="#000000"/>'
            "</svg>",
            encoding="utf-8",
        )

        assert parse_svg_strokes(svg_path) == []

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

    def test_parse_svg_strokes_missing_file_raises(self, tmp_path: Path) -> None:
        """A missing SVG file is reported as a file error."""
        with pytest.raises(FileNotFoundError):
            parse_svg_strokes(tmp_path / "missing.svg")


class TestParseSvgStrokesPenUp:
    @staticmethod
    def _hand_svg() -> str:
        """Three 80 mm lines 30 mm apart, drawn in alternating directions."""
        return """<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm"
    viewBox="0 0 100 100">
  <path d="M 10 10 L 90 10" fill="none" stroke="#000000" stroke-width="1"/>
  <path d="M 90 40 L 10 40" fill="none" stroke="#000000" stroke-width="1"/>
  <path d="M 10 70 L 90 70" fill="none" stroke="#000000" stroke-width="1"/>
</svg>"""

    def _write(self, tmp_path: Path, svg: str) -> Path:
        path = tmp_path / "hand.svg"
        path.write_text(svg, encoding="utf-8")
        return path

    def test_default_omits_pen_up_moves(self, tmp_path: Path) -> None:
        """The default keeps the existing behaviour: only drawn strokes."""
        svg = self._write(tmp_path, self._hand_svg())

        strokes = parse_svg_strokes(svg)

        assert len(strokes) == 3
        assert all(not stroke.pen_up for stroke in strokes)
        cost = compute_machine_cost(strokes)
        assert cost["total"]["drawing_length_mm"] == pytest.approx(240.0)
        assert cost["total"]["pen_up_travel_mm"] == 0.0
        assert cost["total"]["num_lifts"] == 0
        assert cost["total"]["num_strokes"] == 3

    def test_include_pen_up_inserts_travel_between_noncontiguous_strokes(
        self, tmp_path: Path
    ) -> None:
        """The hand-made SVG draws 240 mm, travels 60 mm and lifts twice."""
        svg = self._write(tmp_path, self._hand_svg())

        strokes = parse_svg_strokes(svg, include_pen_up=True)

        assert [stroke.pen_up for stroke in strokes] == [False, True, False, True, False]
        assert strokes[1].polyline == [(90.0, 10.0), (90.0, 40.0)]
        assert strokes[3].polyline == [(10.0, 40.0), (10.0, 70.0)]
        cost = compute_machine_cost(strokes)
        assert cost["total"]["drawing_length_mm"] == pytest.approx(240.0)
        assert cost["total"]["pen_up_travel_mm"] == pytest.approx(60.0)
        assert cost["total"]["num_lifts"] == 2
        assert cost["total"]["num_strokes"] == 3

    def test_single_stroke_has_no_travel_or_lift(self, tmp_path: Path) -> None:
        """One stroke has no other stroke to travel from."""
        svg = self._write(
            tmp_path,
            '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
            'viewBox="0 0 100 100">'
            '<path d="M 10 10 L 90 10" fill="none" stroke="#000000" stroke-width="1"/>'
            "</svg>",
        )

        strokes = parse_svg_strokes(svg, include_pen_up=True)

        assert len(strokes) == 1
        cost = compute_machine_cost(strokes)
        assert cost["total"]["drawing_length_mm"] == pytest.approx(80.0)
        assert cost["total"]["pen_up_travel_mm"] == 0.0
        assert cost["total"]["num_lifts"] == 0
        assert cost["total"]["num_strokes"] == 1

    def test_contiguous_strokes_get_no_travel(self, tmp_path: Path) -> None:
        """Strokes that end where the next starts need no lift."""
        svg = self._write(
            tmp_path,
            '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
            'viewBox="0 0 100 100">'
            '<path d="M 10 10 L 20 10" fill="none" stroke="#000000" stroke-width="1"/>'
            '<path d="M 20 10 L 30 10" fill="none" stroke="#000000" stroke-width="1"/>'
            "</svg>",
        )

        strokes = parse_svg_strokes(svg, include_pen_up=True)

        assert len(strokes) == 2
        assert all(not stroke.pen_up for stroke in strokes)
        cost = compute_machine_cost(strokes)
        assert cost["total"]["pen_up_travel_mm"] == 0.0
        assert cost["total"]["num_lifts"] == 0
        assert cost["total"]["drawing_length_mm"] == pytest.approx(20.0)

    @pytest.mark.parametrize(("gap", "expect_travel"), [(0.005, False), (0.02, True)])
    def test_travel_epsilon_boundary(self, tmp_path: Path, gap: float, expect_travel: bool) -> None:
        """Gaps below 0.01 mm are contiguous; larger gaps produce a lift."""
        svg = self._write(
            tmp_path,
            '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
            'viewBox="0 0 100 100">'
            '<path d="M 10 10 L 20 10" fill="none" stroke="#000000" stroke-width="1"/>'
            f'<path d="M {20 + gap} 10 L 30 10" fill="none" stroke="#000000" stroke-width="1"/>'
            "</svg>",
        )

        strokes = parse_svg_strokes(svg, include_pen_up=True)

        assert len(strokes) == (3 if expect_travel else 2)
        cost = compute_machine_cost(strokes)
        assert cost["total"]["num_lifts"] == (1 if expect_travel else 0)
        assert cost["total"]["pen_up_travel_mm"] == pytest.approx(gap if expect_travel else 0.0)

    def test_travel_uses_following_stroke_style(self, tmp_path: Path) -> None:
        """A travel move takes the colour and width of the pen about to draw."""
        svg = self._write(
            tmp_path,
            '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
            'viewBox="0 0 100 100">'
            '<path d="M 0 0 L 10 0" fill="none" stroke="#000000" stroke-width="1"/>'
            '<path d="M 20 0 L 30 0" fill="none" stroke="#FF0000" stroke-width="2"/>'
            "</svg>",
        )

        strokes = parse_svg_strokes(svg, include_pen_up=True)

        assert strokes[1].pen_up is True
        assert strokes[1].color == "#FF0000"
        assert strokes[1].width_mm == pytest.approx(2.0)

    def test_per_layer_numbers_add_up_to_total(self, tmp_path: Path) -> None:
        """Per-layer travel, lifts and strokes sum to the total."""
        svg = self._write(
            tmp_path,
            '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
            'viewBox="0 0 100 100">'
            '<path d="M 0 0 L 10 0" fill="none" stroke="#000000" stroke-width="1"/>'
            '<path d="M 20 0 L 30 0" fill="none" stroke="#FF0000" stroke-width="1"/>'
            '<path d="M 40 0 L 50 0" fill="none" stroke="#000000" stroke-width="1"/>'
            "</svg>",
        )

        strokes = parse_svg_strokes(svg, include_pen_up=True)
        cost = compute_machine_cost(strokes)
        total = cost["total"]
        per_layer = cost["per_layer"]

        assert total["drawing_length_mm"] == pytest.approx(30.0)
        assert total["pen_up_travel_mm"] == pytest.approx(20.0)
        assert total["num_lifts"] == 2
        assert total["num_strokes"] == 3
        assert per_layer["#000000"]["drawing_length_mm"] == pytest.approx(20.0)
        assert per_layer["#000000"]["pen_up_travel_mm"] == pytest.approx(10.0)
        assert per_layer["#000000"]["num_lifts"] == 1
        assert per_layer["#000000"]["num_strokes"] == 2
        assert per_layer["#FF0000"]["drawing_length_mm"] == pytest.approx(10.0)
        assert per_layer["#FF0000"]["pen_up_travel_mm"] == pytest.approx(10.0)
        assert per_layer["#FF0000"]["num_lifts"] == 1
        assert per_layer["#FF0000"]["num_strokes"] == 1
        for key in ("drawing_length_mm", "pen_up_travel_mm", "num_lifts", "num_strokes"):
            assert sum(layer[key] for layer in per_layer.values()) == pytest.approx(total[key])


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


class TestGetSvgPaperSize:
    def test_get_svg_paper_size_from_width_and_height(self, tmp_path: Path) -> None:
        svg = tmp_path / "size.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="200mm" height="100mm"/>')
        assert get_svg_paper_size(svg) == pytest.approx((200.0, 100.0))

    def test_get_svg_paper_size_from_viewbox(self, tmp_path: Path) -> None:
        svg = tmp_path / "viewbox.svg"
        svg.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
            'viewBox="0 0 200 200"/>'
        )
        assert get_svg_paper_size(svg) == pytest.approx((100.0, 100.0))

    def test_get_svg_paper_size_missing_returns_none(self, tmp_path: Path) -> None:
        svg = tmp_path / "nosize.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><path d="M 0 0 L 1 1"/></svg>')
        assert get_svg_paper_size(svg) is None


class TestLayerFiltering:
    @staticmethod
    def _layered_svg() -> str:
        return """<svg xmlns="http://www.w3.org/2000/svg"
    xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
    width="100mm" height="100mm" viewBox="0 0 100 100">
  <g inkscape:groupmode="layer" inkscape:label="Pen: fine" stroke="#000000" stroke-width="1">
    <path d="M 0 0 L 10 10" fill="none"/>
  </g>
  <g inkscape:groupmode="layer" inkscape:label="Pen: bold" stroke="#FF0000" stroke-width="1">
    <path d="M 20 20 L 30 30" fill="none"/>
  </g>
</svg>"""

    def test_parse_all_strokes_without_filter(self, tmp_path: Path) -> None:
        svg = tmp_path / "layers.svg"
        svg.write_text(self._layered_svg())
        assert len(parse_svg_strokes(svg)) == 2

    def test_parse_single_layer_by_label(self, tmp_path: Path) -> None:
        svg = tmp_path / "layers.svg"
        svg.write_text(self._layered_svg())
        strokes = parse_svg_strokes(svg, layer="Pen: bold")
        assert len(strokes) == 1
        assert strokes[0].color == "#FF0000"

    def test_parse_unknown_layer_returns_empty(self, tmp_path: Path) -> None:
        svg = tmp_path / "layers.svg"
        svg.write_text(self._layered_svg())
        assert parse_svg_strokes(svg, layer="does not exist") == []

    def test_parse_layer_by_id_when_pens_share_a_colour(self, tmp_path: Path) -> None:
        svg = tmp_path / "layer-ids.svg"
        svg.write_text(
            """<svg xmlns="http://www.w3.org/2000/svg"
    xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
    width="100mm" height="100mm" viewBox="0 0 100 100">
  <g id="layer1" inkscape:groupmode="layer" inkscape:label="pen a"
     stroke="#FF0000" stroke-width="1">
    <path d="M 0 0 L 10 10" fill="none"/>
  </g>
  <g id="layer2" inkscape:groupmode="layer" inkscape:label="pen b"
     stroke="#FF0000" stroke-width="1">
    <path d="M 20 20 L 30 30" fill="none"/>
  </g>
</svg>""",
            encoding="utf-8",
        )
        first = parse_svg_strokes(svg, layer="layer1")
        second = parse_svg_strokes(svg, layer="layer2")
        assert len(first) == len(second) == 1
        assert first[0].polyline == [(0.0, 0.0), (10.0, 10.0)]
        assert second[0].polyline == [(20.0, 20.0), (30.0, 30.0)]
