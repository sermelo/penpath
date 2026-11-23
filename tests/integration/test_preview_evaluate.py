"""End-to-end tests for the ``preview`` and ``evaluate`` CLI commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from PIL import Image

from penpath.cli.main import main


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

    def test_preview_requires_output(self, runner: CliRunner, drawing: Path) -> None:
        result = runner.invoke(main, ["preview", str(drawing)])
        assert result.exit_code != 0


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
