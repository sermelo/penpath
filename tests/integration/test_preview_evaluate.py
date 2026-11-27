"""End-to-end tests for the ``preview`` and ``evaluate`` CLI commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from PIL import Image, ImageDraw

from penpath.cli.main import main
from penpath.core import (
    get_image_placement,
    get_svg_paper_size,
    parse_svg_strokes,
    simulate_plot,
)


def _svg(with_metadata: bool = True) -> str:
    metadata = (
        '<metadata><penpath:image-placement x="0" y="0" width="100" height="100"/></metadata>'
        if with_metadata
        else ""
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
     xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
     xmlns:penpath="http://penpath.org/ns/penpath"
     width="100mm" height="100mm" viewBox="0 0 377.95 377.95">
  {metadata}
  <g inkscape:groupmode="layer" inkscape:label="Pen: fine" stroke="#000000" stroke-width="1">
    <path d="M 10 10 L 90 90" fill="none"/>
  </g>
  <g inkscape:groupmode="layer" inkscape:label="Pen: bold" stroke="#FF0000" stroke-width="1">
    <path d="M 10 90 L 90 10" fill="none"/>
  </g>
</svg>"""


@pytest.fixture
def drawing(tmp_path: Path) -> Path:
    path = tmp_path / "plot.svg"
    path.write_text(_svg(), encoding="utf-8")
    return path


@pytest.fixture
def plain_drawing(tmp_path: Path) -> Path:
    path = tmp_path / "plain.svg"
    path.write_text(_svg(with_metadata=False), encoding="utf-8")
    return path


@pytest.fixture
def reference(tmp_path: Path) -> Path:
    image = Image.new("RGB", (64, 64), "white")
    pixels = image.load()
    for index in range(64):
        pixels[index, index] = (0, 0, 0)
    path = tmp_path / "reference.png"
    image.save(path)
    return path


def _hand_svg() -> str:
    """Three 80 mm lines 30 mm apart, drawn in alternating directions."""
    return """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="0 0 100 100">
  <path d="M 10 10 L 90 10" fill="none" stroke="#000000" stroke-width="1"/>
  <path d="M 90 40 L 10 40" fill="none" stroke="#000000" stroke-width="1"/>
  <path d="M 10 70 L 90 70" fill="none" stroke="#000000" stroke-width="1"/>
</svg>"""


@pytest.fixture
def hand_drawing(tmp_path: Path) -> Path:
    path = tmp_path / "hand.svg"
    path.write_text(_hand_svg(), encoding="utf-8")
    return path


def _polygon_svg() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="0 0 100 100">
  <polygon points="10,10 90,10 90,90" fill="none" stroke="#000000" stroke-width="1"/>
</svg>"""


@pytest.fixture
def polygon_drawing(tmp_path: Path) -> Path:
    path = tmp_path / "polygon.svg"
    path.write_text(_polygon_svg(), encoding="utf-8")
    return path


def _filled_svg() -> str:
    """A 100 mm page filled by 1 mm-wide horizontal lines in one light-blue layer."""
    paths = " ".join(f"M 0 {y + 0.5} L 100 {y + 0.5}" for y in range(100))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
     xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
     width="100mm" height="100mm" viewBox="0 0 100 100">
  <g inkscape:groupmode="layer" inkscape:label="light blue"
     stroke="#89CFF0" stroke-width="1">
    <path d="{paths}" fill="none"/>
  </g>
</svg>"""


@pytest.fixture
def filled_drawing(tmp_path: Path) -> Path:
    path = tmp_path / "filled.svg"
    path.write_text(_filled_svg(), encoding="utf-8")
    return path


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


PLACED_DPI = 10
PLACEMENT_WIDTH_MM = PLACEMENT_HEIGHT_MM = 70
PLACEMENTS = ((20.0, 30.0), (60.0, 90.0), (100.0, 150.0))


def _placed_svg(
    x_mm: float, y_mm: float, meta_x_mm: float | None = None, meta_y_mm: float | None = None
) -> str:
    """An A4 SVG with two X strokes at (x, y) and matching placement metadata."""
    meta_x = x_mm if meta_x_mm is None else meta_x_mm
    meta_y = y_mm if meta_y_mm is None else meta_y_mm
    path = (
        f"M {x_mm} {y_mm} L {x_mm + PLACEMENT_WIDTH_MM} {y_mm + PLACEMENT_HEIGHT_MM} "
        f"M {x_mm + PLACEMENT_WIDTH_MM} {y_mm} L {x_mm} {y_mm + PLACEMENT_HEIGHT_MM}"
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
     xmlns:penpath="http://penpath.org/ns/penpath"
     width="210mm" height="297mm" viewBox="0 0 210 297">
  <metadata><penpath:image-placement x="{meta_x}" y="{meta_y}"
     width="{PLACEMENT_WIDTH_MM}" height="{PLACEMENT_HEIGHT_MM}"/></metadata>
  <g stroke="#000000" stroke-width="1">
    <path d="{path}" fill="none"/>
  </g>
</svg>"""


@pytest.fixture
def placed_reference(tmp_path: Path) -> Path:
    """A 70x70 mm region at 10 px/mm showing the same X as the placed strokes."""
    side_px = PLACEMENT_WIDTH_MM * PLACED_DPI
    image = Image.new("RGB", (side_px, side_px), "white")
    draw = ImageDraw.Draw(image)
    draw.line([(0, 0), (side_px - 1, side_px - 1)], fill="black", width=PLACED_DPI)
    draw.line([(side_px - 1, 0), (0, side_px - 1)], fill="black", width=PLACED_DPI)
    path = tmp_path / "reference.png"
    image.save(path)
    return path


def _render_preview(runner: CliRunner, source: Path, output: Path, *extra: str) -> Image.Image:
    result = runner.invoke(main, ["preview", str(source), "-o", str(output), "--dpi", "5", *extra])
    assert result.exit_code == 0, result.output
    with Image.open(output) as image:
        return image.copy()


def _placed_likeness(runner: CliRunner, reference: Path, svg_path: Path) -> float:
    result = runner.invoke(
        main, ["evaluate", str(reference), str(svg_path), "--json", "--dpi", str(PLACED_DPI)]
    )
    assert result.exit_code == 0, result.output
    return float(json.loads(result.stdout)["likeness"])


def _placed_crop_bytes(reference: Path, svg_path: Path) -> bytes:
    """The simulated ink cropped to the rectangle the metadata reports."""
    strokes = parse_svg_strokes(svg_path)
    width_mm, height_mm = get_svg_paper_size(svg_path) or (210.0, 297.0)
    simulated = simulate_plot(strokes, width_mm, height_mm, dpi_px_per_mm=PLACED_DPI)
    with Image.open(reference) as opened:
        placement = get_image_placement(svg_path, opened.size)
    x_px = round(placement.x * PLACED_DPI)
    y_px = round(placement.y * PLACED_DPI)
    width_px = round(placement.width * PLACED_DPI)
    height_px = round(placement.height * PLACED_DPI)
    crop = simulated.crop((x_px, y_px, x_px + width_px, y_px + height_px))
    return crop.tobytes()


class TestPreview:
    def test_preview_writes_image_at_requested_scale(
        self, runner: CliRunner, drawing: Path, tmp_path: Path
    ) -> None:
        output = tmp_path / "preview.png"
        result = runner.invoke(main, ["preview", str(drawing), "-o", str(output), "--dpi", "5"])

        assert result.exit_code == 0, result.output
        assert output.exists()
        with Image.open(output) as image:
            assert image.size == (500, 500)
            assert image.mode == "RGB"

    def test_preview_uses_paper_colour(
        self, runner: CliRunner, drawing: Path, tmp_path: Path
    ) -> None:
        output = tmp_path / "preview.png"
        result = runner.invoke(
            main,
            ["preview", str(drawing), "-o", str(output), "--dpi", "2", "--paper-color", "#FFFF00"],
        )

        assert result.exit_code == 0, result.output
        with Image.open(output) as image:
            assert image.getpixel((0, 0)) == (255, 255, 0)

    def test_preview_layer_filters_strokes(
        self, runner: CliRunner, drawing: Path, tmp_path: Path
    ) -> None:
        all_px = tmp_path / "all.png"
        one_px = tmp_path / "one.png"
        runner.invoke(main, ["preview", str(drawing), "-o", str(all_px), "--dpi", "5"])
        result = runner.invoke(
            main,
            ["preview", str(drawing), "-o", str(one_px), "--dpi", "5", "--layer", "Pen: fine"],
        )

        assert result.exit_code == 0, result.output
        with Image.open(all_px) as all_img, Image.open(one_px) as one_img:
            assert all_img.tobytes() != one_img.tobytes()

    def test_preview_missing_layer_returns_error(
        self, runner: CliRunner, drawing: Path, tmp_path: Path
    ) -> None:
        result = runner.invoke(
            main,
            ["preview", str(drawing), "-o", str(tmp_path / "p.png"), "--layer", "missing"],
        )
        assert result.exit_code != 0

    def test_preview_rejects_nonpositive_dpi(self, runner: CliRunner, drawing: Path) -> None:
        result = runner.invoke(main, ["preview", str(drawing), "-o", "p.png", "--dpi", "0"])
        assert result.exit_code != 0

    def test_preview_invalid_paper_colour_is_clean_error(
        self, runner: CliRunner, drawing: Path, tmp_path: Path
    ) -> None:
        result = runner.invoke(
            main,
            [
                "preview",
                str(drawing),
                "-o",
                str(tmp_path / "p.png"),
                "--paper-color",
                "notacolour",
            ],
        )

        assert result.exit_code == 2
        assert "--paper-color" in result.output
        assert "Traceback" not in result.output
        assert not (tmp_path / "p.png").exists()

    def test_preview_requires_output(self, runner: CliRunner, drawing: Path) -> None:
        result = runner.invoke(main, ["preview", str(drawing)])
        assert result.exit_code != 0

    def test_preview_renders_polygon_closing_edge(
        self, runner: CliRunner, polygon_drawing: Path, tmp_path: Path
    ) -> None:
        """The closing edge of an unfilled polygon is drawn in the preview."""
        output = tmp_path / "polygon.png"
        result = runner.invoke(
            main, ["preview", str(polygon_drawing), "-o", str(output), "--dpi", "5"]
        )

        assert result.exit_code == 0, result.output
        with Image.open(output) as image:
            assert image.getpixel((250, 250)) == (0, 0, 0)

    def test_preview_ignores_filled_polygon(self, runner: CliRunner, tmp_path: Path) -> None:
        """A filled polygon is not drawn, while an unfilled one still is."""
        svg = tmp_path / "mixed.svg"
        svg.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
            'viewBox="0 0 100 100">'
            '<polygon points="70,70 90,70 90,90" fill="#000000" stroke="#000000"/>'
            '<polygon points="10,10 90,10 90,90" fill="none" stroke="#000000" '
            'stroke-width="1"/>'
            "</svg>",
            encoding="utf-8",
        )
        output = tmp_path / "mixed.png"
        result = runner.invoke(main, ["preview", str(svg), "-o", str(output), "--dpi", "5"])

        assert result.exit_code == 0, result.output
        with Image.open(output) as image:
            assert image.getpixel((250, 250)) == (0, 0, 0)
            assert image.getpixel((400, 350)) == (255, 255, 255)

    def test_preview_travel_changes_svg_png_with_light_lines(
        self, runner: CliRunner, hand_drawing: Path, tmp_path: Path
    ) -> None:
        ink = _render_preview(runner, hand_drawing, tmp_path / "ink.png")
        travel = _render_preview(runner, hand_drawing, tmp_path / "travel.png", "--travel")
        no_travel = _render_preview(runner, hand_drawing, tmp_path / "no-travel.png", "--no-travel")

        assert ink.tobytes() != travel.tobytes()
        assert ink.tobytes() == no_travel.tobytes()
        assert ink.getpixel((450, 125)) == (255, 255, 255)
        assert travel.getpixel((450, 125)) == (200, 200, 200)

    def test_preview_travel_leaves_svg_ink_pixels_unchanged(
        self, runner: CliRunner, hand_drawing: Path, tmp_path: Path
    ) -> None:
        ink = _render_preview(runner, hand_drawing, tmp_path / "ink.png")
        travel = _render_preview(runner, hand_drawing, tmp_path / "travel.png", "--travel")
        ink_pixels = [
            (x, y)
            for y in range(ink.height)
            for x in range(ink.width)
            if ink.getpixel((x, y)) != (255, 255, 255)
        ]

        assert ink_pixels
        assert all(travel.getpixel(pixel) == ink.getpixel(pixel) for pixel in ink_pixels)

    def test_preview_travel_works_with_layer(self, runner: CliRunner, tmp_path: Path) -> None:
        svg = tmp_path / "layers.svg"
        svg.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
            'width="100mm" height="100mm" viewBox="0 0 100 100">'
            '<g inkscape:groupmode="layer" inkscape:label="fine" id="layer1" '
            'stroke="#000000" stroke-width="1">'
            '<path d="M 10 10 L 30 10"/><path d="M 30 40 L 10 40"/></g>'
            '<g inkscape:groupmode="layer" inkscape:label="bold" id="layer2" '
            'stroke="#000000" stroke-width="1">'
            '<path d="M 10 70 L 30 70"/></g></svg>',
            encoding="utf-8",
        )

        ink = _render_preview(runner, svg, tmp_path / "ink.png", "--layer", "fine")
        travel = _render_preview(
            runner, svg, tmp_path / "travel.png", "--layer", "fine", "--travel"
        )

        assert ink.tobytes() != travel.tobytes()
        assert travel.getpixel((150, 125)) == (200, 200, 200)
        assert travel.getpixel((100, 350)) == (255, 255, 255)


class TestEvaluate:
    def test_evaluate_json_has_all_fields(
        self, runner: CliRunner, drawing: Path, reference: Path
    ) -> None:
        result = runner.invoke(main, ["evaluate", str(reference), str(drawing), "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert isinstance(data["likeness"], float)
        assert 0.0 <= data["likeness"] <= 1.0
        cost = data["machine_cost"]
        expected = {
            "drawing_length_mm",
            "pen_up_travel_mm",
            "num_lifts",
            "num_short_segments",
            "num_strokes",
            "ink_coverage_pct",
        }
        assert set(cost["total"]) == expected
        assert cost["total"]["num_strokes"] == 2
        assert cost["per_layer"]["#000000"]["num_strokes"] == 1
        assert cost["per_layer"]["#FF0000"]["num_strokes"] == 1

    def test_evaluate_polygon_length_includes_closing_edge(
        self, runner: CliRunner, polygon_drawing: Path, reference: Path
    ) -> None:
        """Evaluate counts the closing edge of a polygon as drawn ink."""
        result = runner.invoke(main, ["evaluate", str(reference), str(polygon_drawing), "--json"])

        assert result.exit_code == 0, result.output
        cost = json.loads(result.stdout)["machine_cost"]["total"]
        assert cost["num_strokes"] == 1
        assert cost["drawing_length_mm"] == pytest.approx(80 + 80 + 80 * 2**0.5, abs=0.01)

    def test_evaluate_reports_exact_cost_for_hand_svg(
        self, runner: CliRunner, hand_drawing: Path, reference: Path
    ) -> None:
        """The hand-made SVG reports 240 mm drawn, 60 mm travel and 2 lifts."""
        result = runner.invoke(main, ["evaluate", str(reference), str(hand_drawing), "--json"])

        assert result.exit_code == 0, result.output
        cost = json.loads(result.stdout)["machine_cost"]["total"]
        assert cost["drawing_length_mm"] == pytest.approx(240.0, abs=0.01)
        assert cost["pen_up_travel_mm"] == pytest.approx(60.0, abs=0.01)
        assert cost["num_lifts"] == 2
        assert cost["num_strokes"] == 3

    def test_evaluate_counts_travel_and_lifts_between_strokes(
        self, runner: CliRunner, drawing: Path, reference: Path
    ) -> None:
        """A drawing with separated strokes reports a lift and real travel."""
        result = runner.invoke(main, ["evaluate", str(reference), str(drawing), "--json"])

        assert result.exit_code == 0, result.output
        cost = json.loads(result.stdout)["machine_cost"]["total"]
        assert cost["num_lifts"] == 1
        assert cost["pen_up_travel_mm"] == pytest.approx(80 * 100 / 377.95, abs=0.01)
        assert cost["num_strokes"] == 2

    def test_evaluate_rejects_malformed_svg(
        self, runner: CliRunner, reference: Path, tmp_path: Path
    ) -> None:
        """A broken polygon SVG is a clean runtime error, not a traceback."""
        svg = tmp_path / "broken.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><polygon', encoding="utf-8")
        result = runner.invoke(main, ["evaluate", str(reference), str(svg), "--json"])

        assert result.exit_code == 1
        assert "Could not parse SVG" in result.output
        assert "Traceback" not in result.output
        assert result.stdout.strip() == ""

    def test_evaluate_rejects_polygon_without_points(
        self, runner: CliRunner, reference: Path, tmp_path: Path
    ) -> None:
        """An unfilled polygon with no points yields a clear no-strokes error."""
        svg = tmp_path / "empty_polygon.svg"
        svg.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
            'viewBox="0 0 100 100">'
            '<polygon points="" fill="none" stroke="#000000"/>'
            "</svg>",
            encoding="utf-8",
        )
        result = runner.invoke(main, ["evaluate", str(reference), str(svg), "--json"])

        assert result.exit_code == 1
        assert "No pen strokes found in SVG" in result.output
        assert result.stdout.strip() == ""

    def test_evaluate_counts_all_ink_in_millimetre_svg(
        self, runner: CliRunner, reference: Path, tmp_path: Path
    ) -> None:
        """A millimetre viewBox yields millimetre lengths for a closed stroke."""
        svg_path = tmp_path / "mm_plot.svg"
        svg_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
            'width="210mm" height="297mm" viewBox="0 0 210 297">'
            '<g id="layer1" inkscape:groupmode="layer" inkscape:label="fine">'
            '<path d="M 10 10 L 110 10 L 110 110 L 10 110 Z" '
            'fill="none" stroke="#000000" stroke-width="0.3"/>'
            "</g></svg>",
            encoding="utf-8",
        )

        result = runner.invoke(main, ["evaluate", str(reference), str(svg_path), "--json"])

        assert result.exit_code == 0, result.output
        strokes = parse_svg_strokes(svg_path)
        assert len(strokes) == 1
        cost = json.loads(result.stdout)["machine_cost"]["total"]
        assert cost["num_strokes"] == 1
        assert cost["drawing_length_mm"] == pytest.approx(400.0, abs=0.1)

    def test_evaluate_json_writes_only_json_to_stdout(
        self, runner: CliRunner, drawing: Path, reference: Path
    ) -> None:
        result = runner.invoke(main, ["evaluate", str(reference), str(drawing), "--json"])

        assert result.exit_code == 0, result.output
        assert result.stdout.strip().startswith("{")
        assert "Evaluation:" not in result.stdout
        assert "Machine Cost" not in result.stdout

    def test_evaluate_human_output_has_tables(
        self, runner: CliRunner, drawing: Path, reference: Path
    ) -> None:
        result = runner.invoke(main, ["evaluate", str(reference), str(drawing)])

        assert result.exit_code == 0, result.output
        assert "Likeness" in result.output
        assert "Machine Cost" in result.output
        assert "SSIM" in result.output

    def test_evaluate_plain_svg_uses_centred_fallback(
        self, runner: CliRunner, plain_drawing: Path, reference: Path
    ) -> None:
        result = runner.invoke(main, ["evaluate", str(reference), str(plain_drawing), "--json"])

        assert result.exit_code == 0, result.output
        assert isinstance(json.loads(result.stdout)["likeness"], float)

    def test_evaluate_layer_filters_cost(
        self, runner: CliRunner, drawing: Path, reference: Path
    ) -> None:
        result = runner.invoke(
            main, ["evaluate", str(reference), str(drawing), "--layer", "Pen: bold", "--json"]
        )

        assert result.exit_code == 0, result.output
        cost = json.loads(result.stdout)["machine_cost"]
        assert cost["total"]["num_strokes"] == 1
        assert list(cost["per_layer"]) == ["#FF0000"]

    def test_evaluate_rejects_bad_image(
        self, runner: CliRunner, drawing: Path, tmp_path: Path
    ) -> None:
        bad = tmp_path / "bad.png"
        bad.write_bytes(b"not an image")
        result = runner.invoke(main, ["evaluate", str(bad), str(drawing), "--json"])
        assert result.exit_code != 0

    def test_evaluate_rejects_nonpositive_dpi(
        self, runner: CliRunner, drawing: Path, reference: Path
    ) -> None:
        result = runner.invoke(
            main, ["evaluate", str(reference), str(drawing), "--dpi", "-1", "--json"]
        )
        assert result.exit_code != 0

    def test_evaluate_invalid_paper_colour_is_clean_error(
        self, runner: CliRunner, drawing: Path, reference: Path
    ) -> None:
        result = runner.invoke(
            main,
            [
                "evaluate",
                str(reference),
                str(drawing),
                "--paper-color",
                "notacolour",
                "--json",
            ],
        )

        assert result.exit_code == 2
        assert "--paper-color" in result.output
        assert "Traceback" not in result.output
        assert result.stdout.strip() == ""


class TestEvaluateEdgeLikeness:
    """The extra diagnostic is a sibling of likeness in JSON and in the table."""

    def test_json_reports_both_scores(
        self, runner: CliRunner, drawing: Path, reference: Path
    ) -> None:
        result = runner.invoke(main, ["evaluate", str(reference), str(drawing), "--json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert {"likeness", "edge_likeness", "machine_cost"} <= set(data)
        assert isinstance(data["likeness"], float)
        assert isinstance(data["edge_likeness"], float)
        assert 0.0 <= data["edge_likeness"] <= 1.0

    def test_human_output_has_edge_ssim_row(
        self, runner: CliRunner, drawing: Path, reference: Path
    ) -> None:
        result = runner.invoke(main, ["evaluate", str(reference), str(drawing)])

        assert result.exit_code == 0, result.output
        assert "Likeness" in result.output
        assert "SSIM" in result.output
        assert "Edge SSIM" in result.output

    def test_luc_135_repro_is_caught_by_edge_ssim(self, runner: CliRunner) -> None:
        """The pale-area repro scores well in greyscale but its edges do not match."""
        fixtures = Path(__file__).resolve().parents[1] / "fixtures"
        image = fixtures / "images/background/pencil_on_pale_grey.png"
        svg = fixtures / "golden/svg/pencil_palette_before_background.svg"

        result = runner.invoke(main, ["evaluate", str(image), str(svg), "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)

        # Measured on this fixture with the shipped defaults (96/25.4 px/mm):
        # grey 0.7820, edge 0.2154. The 0.40 ceiling is the midpoint between
        # that repro and the lowest matching-edge drawing measured below (0.7215,
        # the hatched-square unit case), rounded down to one decimal.
        assert data["likeness"] == pytest.approx(0.7820, abs=0.001)
        assert data["edge_likeness"] == pytest.approx(0.2154, abs=0.001)
        assert data["edge_likeness"] < data["likeness"] - 0.5
        assert data["edge_likeness"] < 0.40

    def test_matching_edges_still_score_high(self, runner: CliRunner) -> None:
        """The same figure drawn without the pale-area scribble keeps its edges."""
        fixtures = Path(__file__).resolve().parents[1] / "fixtures"
        image = fixtures / "images/background/pencil_on_pale_grey.png"
        svg = fixtures / "golden/svg/single_pen_before_background.svg"

        result = runner.invoke(main, ["evaluate", str(image), str(svg), "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)

        # Measured 0.8756; the 0.70 floor is that value rounded down to 0.1.
        assert data["edge_likeness"] == pytest.approx(0.8756, abs=0.001)
        assert data["edge_likeness"] > 0.70
        assert data["edge_likeness"] > data["likeness"] - 0.15


class TestEvaluatePenNames:
    """Each colour row carries the Inkscape layer's pen name, human and JSON."""

    def test_two_layers_report_pen_names_in_json_and_table(
        self, runner: CliRunner, drawing: Path, reference: Path
    ) -> None:
        json_result = runner.invoke(main, ["evaluate", str(reference), str(drawing), "--json"])

        assert json_result.exit_code == 0, json_result.output
        cost = json.loads(json_result.stdout)["machine_cost"]
        assert cost["per_layer"]["#000000"]["pen"] == "Pen: fine"
        assert cost["per_layer"]["#FF0000"]["pen"] == "Pen: bold"
        assert "pen" not in cost["total"]

        human = runner.invoke(
            main, ["evaluate", str(reference), str(drawing)], env={"COLUMNS": "200"}
        )

        assert human.exit_code == 0, human.output
        assert "Pen" in human.output
        assert "Pen: fine" in human.output
        assert "Pen: bold" in human.output
        assert "#000000" in human.output
        assert "#FF0000" in human.output
        assert "TOTAL" in human.output

    def test_long_pen_names_are_readable_at_narrow_width(self, runner: CliRunner) -> None:
        """Underscore pen names fold at 80 columns instead of truncating (LUC-134 QA)."""
        fixtures = Path(__file__).resolve().parents[1] / "fixtures"
        image = fixtures / "images/background/pencil_on_pale_grey.png"
        svg = fixtures / "golden/svg/pencil_palette_before_background.svg"

        result = runner.invoke(
            main, ["evaluate", str(image), str(svg), "--coverage-warn", "0"], env={"COLUMNS": "80"}
        )

        assert result.exit_code == 0, result.output
        machine_cost = result.output.split("Machine Cost", 1)[1]
        pen_column = "".join(
            line.split("│")[2].replace(" ", "")
            for line in machine_cost.splitlines()
            if line.startswith("│")
        )
        assert "stabilo_88_light_blue" in pen_column
        assert "stabilo_88_black" in pen_column
        assert "…" not in pen_column

    def test_svg_without_layers_falls_back_to_hex(
        self, runner: CliRunner, hand_drawing: Path, reference: Path
    ) -> None:
        result = runner.invoke(main, ["evaluate", str(reference), str(hand_drawing), "--json"])

        assert result.exit_code == 0, result.output
        per_layer = json.loads(result.stdout)["machine_cost"]["per_layer"]
        assert per_layer["#000000"]["pen"] == "#000000"

    def test_layer_filter_keeps_the_pen_name(
        self, runner: CliRunner, drawing: Path, reference: Path
    ) -> None:
        result = runner.invoke(
            main, ["evaluate", str(reference), str(drawing), "--layer", "Pen: bold", "--json"]
        )

        assert result.exit_code == 0, result.output
        per_layer = json.loads(result.stdout)["machine_cost"]["per_layer"]
        assert list(per_layer) == ["#FF0000"]
        assert per_layer["#FF0000"]["pen"] == "Pen: bold"


class TestEvaluateCoverage:
    """Ink coverage is reported per layer and warns on stderr when a page fills up."""

    def test_page_filling_layer_warns_and_reports_coverage(
        self, runner: CliRunner, filled_drawing: Path, reference: Path
    ) -> None:
        result = runner.invoke(
            main,
            ["evaluate", str(reference), str(filled_drawing), "--json", "--dpi", "10"],
        )

        assert result.exit_code == 0, result.output
        cost = json.loads(result.stdout)["machine_cost"]
        assert cost["per_layer"]["#89CFF0"]["ink_coverage_pct"] > 90.0
        assert 0.0 < cost["total"]["ink_coverage_pct"] <= 100.0
        assert "Warning" in result.stderr
        assert "#89CFF0" in result.stderr
        assert "--background-threshold" in result.stderr
        assert "--saturation" in result.stderr
        assert "Warning" not in result.stdout

    def test_sparse_plot_does_not_warn(
        self, runner: CliRunner, hand_drawing: Path, reference: Path
    ) -> None:
        result = runner.invoke(main, ["evaluate", str(reference), str(hand_drawing), "--json"])

        assert result.exit_code == 0, result.output
        coverage = json.loads(result.stdout)["machine_cost"]["total"]["ink_coverage_pct"]
        assert 0.0 < coverage < 50.0
        assert "Warning" not in result.stderr

    def test_coverage_warn_changes_the_threshold(
        self, runner: CliRunner, hand_drawing: Path, reference: Path
    ) -> None:
        result = runner.invoke(
            main,
            [
                "evaluate",
                str(reference),
                str(hand_drawing),
                "--json",
                "--coverage-warn",
                "1",
            ],
        )

        assert result.exit_code == 0, result.output
        assert "Warning" in result.stderr

    def test_coverage_warn_rejects_negative_value(
        self, runner: CliRunner, drawing: Path, reference: Path
    ) -> None:
        result = runner.invoke(
            main,
            ["evaluate", str(reference), str(drawing), "--json", "--coverage-warn", "-5"],
        )

        assert result.exit_code == 2
        assert "--coverage-warn" in result.output
        assert "Traceback" not in result.output
        assert result.stdout.strip() == ""

    def test_coverage_warn_zero_disables_the_warning(
        self, runner: CliRunner, filled_drawing: Path, reference: Path
    ) -> None:
        result = runner.invoke(
            main,
            [
                "evaluate",
                str(reference),
                str(filled_drawing),
                "--json",
                "--coverage-warn",
                "0",
            ],
        )

        assert result.exit_code == 0, result.output
        assert "Warning" not in result.stderr
        assert json.loads(result.stdout)["machine_cost"]["total"]["ink_coverage_pct"] > 90.0

    def test_json_stdout_stays_valid_json_with_warning(
        self, runner: CliRunner, filled_drawing: Path, reference: Path
    ) -> None:
        result = runner.invoke(
            main, ["evaluate", str(reference), str(filled_drawing), "--json", "--dpi", "10"]
        )

        assert result.exit_code == 0, result.output
        assert result.stdout.strip().startswith("{")
        assert "Evaluation:" not in result.stdout
        assert "Machine Cost" not in result.stdout
        json.loads(result.stdout)

    def test_human_output_has_coverage_column(
        self, runner: CliRunner, drawing: Path, reference: Path
    ) -> None:
        result = runner.invoke(main, ["evaluate", str(reference), str(drawing)])

        assert result.exit_code == 0, result.output
        assert "Coverage" in result.output
        assert "Machine Cost" in result.output

    def test_luc_91_repro_light_blue_layer_reports_coverage(self, runner: CliRunner) -> None:
        """The committed part-1 repro reports its pale-area layer with a lower threshold."""
        fixtures = Path(__file__).resolve().parents[1] / "fixtures"
        image = fixtures / "images/background/pencil_on_pale_grey.png"
        svg = fixtures / "golden/svg/pencil_palette_before_background.svg"

        result = runner.invoke(
            main, ["evaluate", str(image), str(svg), "--json", "--coverage-warn", "5"]
        )

        assert result.exit_code == 0, result.output
        per_layer = json.loads(result.stdout)["machine_cost"]["per_layer"]
        assert per_layer["#8CCFE8"]["pen"] == "stabilo_88_light_blue"
        assert per_layer["#000000"]["pen"] == "stabilo_88_black"
        assert per_layer["#8CCFE8"]["ink_coverage_pct"] > 5.0
        assert per_layer["#8CCFE8"]["ink_coverage_pct"] > per_layer["#000000"]["ink_coverage_pct"]
        assert "#8CCFE8" in result.stderr
        assert "Warning" in result.stderr


class TestEvaluatePlacementLikeness:
    """Likeness follows the placement metadata, not where the drawing sits on the page."""

    def test_evaluate_likeness_is_identical_at_every_placement(
        self, runner: CliRunner, placed_reference: Path, tmp_path: Path
    ) -> None:
        """The same strokes score the same wherever they are drawn, with matching metadata."""
        scores: list[float] = []
        crops: list[bytes] = []
        for index, (x_mm, y_mm) in enumerate(PLACEMENTS):
            svg_path = tmp_path / f"placed_{index}.svg"
            svg_path.write_text(_placed_svg(x_mm, y_mm), encoding="utf-8")
            scores.append(_placed_likeness(runner, placed_reference, svg_path))
            crops.append(_placed_crop_bytes(placed_reference, svg_path))

        assert scores[0] == pytest.approx(scores[1], abs=1e-6)
        assert scores[0] == pytest.approx(scores[2], abs=1e-6)
        assert all(crop == crops[0] for crop in crops[1:])

    def test_evaluate_likeness_changes_with_wrong_metadata(
        self, runner: CliRunner, placed_reference: Path, tmp_path: Path
    ) -> None:
        """Wrong metadata crops the wrong pixels, so the score must not match."""
        correct = tmp_path / "correct.svg"
        correct.write_text(_placed_svg(20, 30), encoding="utf-8")
        wrong = tmp_path / "wrong.svg"
        wrong.write_text(_placed_svg(20, 30, meta_x_mm=100, meta_y_mm=150), encoding="utf-8")

        correct_score = _placed_likeness(runner, placed_reference, correct)
        wrong_score = _placed_likeness(runner, placed_reference, wrong)

        assert abs(wrong_score - correct_score) > 1e-6


class TestCommandHelp:
    @pytest.mark.parametrize("command", ["preview", "evaluate"])
    def test_command_help(self, runner: CliRunner, command: str) -> None:
        result = runner.invoke(main, [command, "--help"])

        assert result.exit_code == 0
        assert "Usage:" in result.output
        assert "--dpi" in result.output

    def test_preview_help_describes_travel(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["preview", "--help"])

        assert result.exit_code == 0
        assert "--travel" in result.output
        assert "thin light lines" in result.output

    def test_evaluate_help_describes_both_ssim_scores(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["evaluate", "--help"])

        assert result.exit_code == 0
        assert "greyscale SSIM" in result.output
        assert "edge SSIM" in result.output
