"""End-to-end CLI checks for selecting the stipple PFM and its presets."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner
from PIL import Image

from penpath.cli.commands.convert import _resolve_pfm
from penpath.cli.main import main
from penpath.core.drawing import StippleSettings
from penpath.core.models import RegisteredPFM
from penpath.core.simulation import compute_machine_cost, simulate_plot
from penpath.core.svg_parse import parse_svg_strokes


def _portrait(path: Path) -> Path:
    image = Image.new("RGB", (80, 80), "white")
    for y in range(18, 62):
        for x in range(20, 60):
            image.putpixel((x, y), (20, 20, 20))
    image.save(path)
    return path


def test_info_pfms_lists_stipple_and_its_presets() -> None:
    result = CliRunner().invoke(main, ["info", "pfms", "--format", "json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    by_name = {row["name"]: row for row in data["available_pfms"]}
    assert "stipple" in by_name
    assert by_name["stipple"]["settings_model"] == "StippleSettings"
    assert by_name["stipple"]["default_settings"]["max_strokes"] == 10000
    assert by_name["stipple"]["default_settings"]["dot_shape"] == "dash"
    assert by_name["stipple"]["presets"] == [
        "stipple_bold",
        "stipple_default",
        "stipple_fine",
    ]
    for name in ("stipple_default", "stipple_fine", "stipple_bold"):
        assert name in data["presets"]


def test_convert_help_points_to_pfm_registry() -> None:
    result = CliRunner().invoke(main, ["convert", "--help"])
    assert result.exit_code == 0, result.output
    assert "--pfm TEXT" in result.output
    assert "penpath info pfms" in result.output


def test_convert_with_stipple_and_seed_writes_an_svg(tmp_path: Path) -> None:
    image = _portrait(tmp_path / "portrait.png")
    output = tmp_path / "stipple.svg"
    result = CliRunner().invoke(
        main,
        [
            "convert",
            str(image),
            "-o",
            str(output),
            "--pfm",
            "stipple",
            "-s",
            "seed=42",
            "--no-vpype",
            "--quiet",
        ],
    )
    assert result.exit_code == 0, result.output
    assert output.exists()
    assert parse_svg_strokes(output)


def test_convert_with_stipple_fine_preset_writes_an_svg(tmp_path: Path) -> None:
    image = _portrait(tmp_path / "portrait.png")
    output = tmp_path / "fine.svg"
    result = CliRunner().invoke(
        main,
        [
            "convert",
            str(image),
            "-o",
            str(output),
            "--pfm",
            "stipple_fine",
            "-s",
            "seed=42",
            "--no-vpype",
            "--quiet",
        ],
    )
    assert result.exit_code == 0, result.output
    assert output.exists()
    assert parse_svg_strokes(output)


def test_unknown_dot_shape_exits_2_naming_the_setting(tmp_path: Path) -> None:
    image = _portrait(tmp_path / "portrait.png")
    result = CliRunner().invoke(
        main,
        [
            "convert",
            str(image),
            "-o",
            str(tmp_path / "bad.svg"),
            "--pfm",
            "stipple",
            "-s",
            "dot_shape=square",
            "--no-vpype",
        ],
    )

    assert result.exit_code == 2
    assert "dot_shape" in result.output


def test_convert_with_circle_dot_shape_writes_closed_rings(tmp_path: Path) -> None:
    image = _portrait(tmp_path / "portrait.png")
    output = tmp_path / "circles.svg"
    result = CliRunner().invoke(
        main,
        [
            "convert",
            str(image),
            "-o",
            str(output),
            "--pfm",
            "stipple",
            "-s",
            "dot_shape=circle",
            "-s",
            "seed=42",
            "--no-vpype",
            "--quiet",
        ],
    )

    assert result.exit_code == 0, result.output
    strokes = parse_svg_strokes(output)
    assert strokes
    assert all(len(stroke.polyline) == 13 for stroke in strokes)
    assert all(stroke.polyline[0] == stroke.polyline[-1] for stroke in strokes)
    assert all(len(set(stroke.polyline)) >= 9 for stroke in strokes)


def test_convert_with_tap_dot_shape_survives_svg_preview_and_cost(tmp_path: Path) -> None:
    image = _portrait(tmp_path / "portrait.png")
    output = tmp_path / "taps.svg"
    result = CliRunner().invoke(
        main,
        [
            "convert",
            str(image),
            "-o",
            str(output),
            "--pfm",
            "stipple",
            "-s",
            "dot_shape=tap",
            "-s",
            "seed=42",
            "--no-vpype",
            "--quiet",
        ],
    )

    assert result.exit_code == 0, result.output
    strokes = parse_svg_strokes(output)
    assert strokes
    assert all(len(stroke.polyline) == 2 for stroke in strokes)
    assert all(stroke.polyline[0] == stroke.polyline[-1] for stroke in strokes)
    assert compute_machine_cost(strokes)["total"]["num_strokes"] == len(strokes)
    assert simulate_plot(strokes, 80.0, 80.0, dpi_px_per_mm=1.0).size == (80, 80)


def test_stipple_fine_preset_selects_its_own_settings() -> None:
    pfm = _resolve_pfm("stipple_fine", {"seed": "42"})
    assert isinstance(pfm, RegisteredPFM)
    assert pfm.pfm_type == "stipple"
    settings = pfm.to_typed_settings()
    assert isinstance(settings, StippleSettings)
    assert settings.seed == 42
    assert settings.max_radius == 1.5
