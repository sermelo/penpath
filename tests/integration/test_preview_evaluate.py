"""End-to-end tests for the ``preview`` and ``evaluate`` CLI commands."""

from __future__ import annotations

import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from click.testing import CliRunner
from PIL import Image
from shapely import LineString

from penpath.cli.main import main
from penpath.core.models import Paper, Pen
from penpath.core.output.vpype import run_vpype


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


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


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

    def test_evaluate_counts_all_ink_in_vpype_output(
        self, runner: CliRunner, reference: Path, tmp_path: Path
    ) -> None:
        """Every polygon in real vpype SVG output is counted as drawn ink."""
        vpype_path = shutil.which("vpype")
        if vpype_path is None:
            pytest.skip("vpype executable not found")

        rectangle = LineString([(100, 100), (200, 100), (200, 200), (100, 200), (100, 100)])
        svg_bytes = run_vpype(
            [rectangle],
            Paper(name="A4", width_mm=210, height_mm=297, dpi=300),
            [Pen(name="fine", width_mm=0.3, color="#000000")],
            vpype_path=vpype_path,
        )
        svg_path = tmp_path / "vpype_plot.svg"
        svg_path.write_bytes(svg_bytes)
        root = ET.fromstring(svg_bytes)
        geometry = [
            element
            for element in root.iter()
            if element.tag.rsplit("}", 1)[-1].lower() in ("polygon", "polyline", "line", "path")
        ]
        assert any(element.tag.rsplit("}", 1)[-1].lower() == "polygon" for element in geometry)

        result = runner.invoke(main, ["evaluate", str(reference), str(svg_path), "--json"])

        assert result.exit_code == 0, result.output
        cost = json.loads(result.stdout)["machine_cost"]["total"]
        assert cost["num_strokes"] == len(geometry)
        assert cost["drawing_length_mm"] == pytest.approx(400 * 25.4 / 96, abs=0.1)

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


class TestCommandHelp:
    @pytest.mark.parametrize("command", ["preview", "evaluate"])
    def test_command_help(self, runner: CliRunner, command: str) -> None:
        result = runner.invoke(main, [command, "--help"])

        assert result.exit_code == 0
        assert "Usage:" in result.output
        assert "--dpi" in result.output
