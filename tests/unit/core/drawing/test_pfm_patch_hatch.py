"""Tests for the Patch Hatch PFM (hand-drawn cross-hatching in patches)."""

from __future__ import annotations

import itertools
import json
import math
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner
from PIL import Image, ImageDraw
from pydantic import ValidationError
from shapely import LineString

from penpath.cli.commands.convert import _resolve_pfm
from penpath.cli.main import main
from penpath.core.drawing.pfm_patch_hatch import (
    PatchHatchSettings,
    layer_thresholds,
    patch_hatch_strokes,
    with_layer_angle_offset,
)
from penpath.core.drawing.registry import get_pfm, list_pfms
from penpath.core.image.pipeline import FilterPipeline
from penpath.core.models import ImageRef, Paper, Pen, Project, RegisteredPFM
from penpath.core.project import load_yaml, save_yaml
from penpath.presets.pfms import (
    PATCH_HATCH_PRESETS,
    get_pfm_preset_by_id,
    list_presets_for_pfm,
)

PX_PER_MM = 4.0
PEN_MM = 0.3
_PRESET_IDS = [
    "patch_hatch:bold",
    "patch_hatch:default",
    "patch_hatch:fast",
    "patch_hatch:fine",
]


def _grey(level: int, size: tuple[int, int] = (160, 160)) -> Image.Image:
    return Image.new("L", size, level)


def _draw(image: Image.Image, **overrides: object) -> list[LineString]:
    settings = PatchHatchSettings(seed=7, **overrides)  # type: ignore[arg-type]
    return patch_hatch_strokes(image, settings, PX_PER_MM, PEN_MM)


def _ink_mm(lines: list[LineString]) -> float:
    return sum(line.length for line in lines) / PX_PER_MM


def _mean_axis_angle(lines: list[LineString]) -> float:
    """Length-weighted mean direction of the strokes' first segments, mod 180."""
    sum_cos = sum_sin = 0.0
    for line in lines:
        (ax, ay), (bx, by) = line.coords[0], line.coords[1]
        angle = math.atan2(by - ay, bx - ax)
        length = math.hypot(bx - ax, by - ay)
        sum_cos += length * math.cos(2.0 * angle)
        sum_sin += length * math.sin(2.0 * angle)
    return math.degrees(0.5 * math.atan2(sum_sin, sum_cos)) % 180.0


class TestSettings:
    def test_defaults(self) -> None:
        settings = PatchHatchSettings()
        assert settings.spacing == 0.8
        assert settings.thresholds is None
        assert settings.layer_angles == (0.0, 60.0, 120.0, 90.0)
        assert settings.follow_edges is True
        assert settings.join_lines is False
        assert settings.join_in_dark is True

    def test_thresholds_must_match_layers(self) -> None:
        with pytest.raises(ValidationError, match="same length"):
            PatchHatchSettings(thresholds=(0.2, 0.4))

    def test_thresholds_must_increase(self) -> None:
        with pytest.raises(ValidationError, match="strictly increasing"):
            PatchHatchSettings(layer_angles=(0.0, 90.0), thresholds=(0.5, 0.4))

    @pytest.mark.parametrize("bad", [0.0, 1.0, -0.1])
    def test_threshold_range(self, bad: float) -> None:
        with pytest.raises(ValidationError):
            PatchHatchSettings(layer_angles=(0.0,), thresholds=(bad,))

    def test_patch_size_order(self) -> None:
        with pytest.raises(ValidationError, match="min_patch_size"):
            PatchHatchSettings(patch_size=3.0, min_patch_size=5.0)

    def test_layer_angle_range(self) -> None:
        with pytest.raises(ValidationError, match="layer angle"):
            PatchHatchSettings(layer_angles=(0.0, 400.0, 0.0, 0.0))

    def test_empty_layers_rejected(self) -> None:
        with pytest.raises(ValidationError, match="at least one layer"):
            PatchHatchSettings(layer_angles=())


class TestLayerThresholds:
    def test_values_follow_pen_coverage(self) -> None:
        # One layer of a 0.3 mm pen every 0.8 mm covers 0.375 of the paper.
        values = layer_thresholds(4, 0.8, 0.3)
        coverage = [1.0 - 0.625**n for n in range(5)]
        expected = [(coverage[n - 1] + coverage[n]) / 2.0 for n in range(1, 5)]
        assert values == pytest.approx(expected)

    def test_wider_pen_turns_layers_on_later(self) -> None:
        thin = layer_thresholds(4, 0.8, 0.2)
        wide = layer_thresholds(4, 0.8, 0.5)
        assert all(w > t for w, t in zip(wide, thin, strict=True))

    def test_strictly_increasing_inside_unit_interval(self) -> None:
        values = layer_thresholds(6, 0.3, 0.3)  # pen as wide as the spacing
        assert all(0.0 < v < 1.0 for v in values)
        assert all(b > a for a, b in itertools.pairwise(values))

    def test_rejects_bad_input(self) -> None:
        with pytest.raises(ValueError):
            layer_thresholds(0, 0.8, 0.3)
        with pytest.raises(ValueError):
            layer_thresholds(2, 0.0, 0.3)


class TestStrokes:
    def test_white_image_draws_nothing(self) -> None:
        assert _draw(_grey(255)) == []

    def test_strokes_stay_inside_the_image(self) -> None:
        image = _grey(60, (120, 90))
        lines = _draw(image)
        assert lines
        coords = np.concatenate([np.asarray(line.coords) for line in lines])
        assert coords[:, 0].min() >= 0.0 and coords[:, 0].max() <= 119.0
        assert coords[:, 1].min() >= 0.0 and coords[:, 1].max() <= 89.0
        assert all(line.length > 0.0 for line in lines)

    def test_darker_tone_uses_more_ink(self) -> None:
        inks = [_ink_mm(_draw(_grey(level))) for level in (200, 140, 80, 20)]
        assert inks == sorted(inks)
        assert inks[0] < inks[-1] / 2.0

    def test_darker_tone_adds_crossing_layers(self) -> None:
        # Light grey gets one direction per patch; black gets all four.
        light = PatchHatchSettings(seed=3, follow_edges=False, angle_jitter=0.0, join_in_dark=False)
        dark_lines = patch_hatch_strokes(_grey(0), light, PX_PER_MM, PEN_MM)
        light_lines = patch_hatch_strokes(_grey(190), light, PX_PER_MM, PEN_MM)
        assert len(dark_lines) > 3 * len(light_lines)

    def test_same_seed_same_strokes(self) -> None:
        image = _grey(90)
        first = [list(line.coords) for line in _draw(image)]
        second = [list(line.coords) for line in _draw(image)]
        assert first == second

    def test_spacing_never_below_pen_width(self) -> None:
        image = _grey(200)
        fine = patch_hatch_strokes(
            image, PatchHatchSettings(seed=1, spacing=0.05), PX_PER_MM, PEN_MM
        )
        at_pen = patch_hatch_strokes(
            image, PatchHatchSettings(seed=1, spacing=PEN_MM), PX_PER_MM, PEN_MM
        )
        assert _ink_mm(fine) == pytest.approx(_ink_mm(at_pen))

    def test_lines_follow_edges(self) -> None:
        # Vertical stripes: edges run vertically, so single-layer patches
        # hatch along them (90 degrees in image coordinates).
        image = Image.new("L", (200, 200), 255)
        draw = ImageDraw.Draw(image)
        for x in range(0, 200, 24):
            draw.rectangle((x, 0, x + 11, 199), fill=150)
        settings = PatchHatchSettings(seed=5, angle_jitter=0.0, edge_jitter=0.0)
        lines = patch_hatch_strokes(image, settings, PX_PER_MM, PEN_MM)
        assert lines
        assert abs(_mean_axis_angle(lines) - 90.0) < 10.0

    def test_join_lines_cuts_stroke_count(self) -> None:
        image = _grey(60)
        apart = _draw(image, join_in_dark=False)
        joined = _draw(image, join_lines=True)
        assert len(joined) * 2 < len(apart)
        assert _ink_mm(joined) > _ink_mm(apart)  # connectors add a little ink

    def test_join_in_dark_leaves_light_areas_unjoined(self) -> None:
        # Light grey turns on only the first layer, so no connector is hidden.
        image = _grey(190)
        assert len(_draw(image)) == len(_draw(image, join_in_dark=False))

    def test_join_in_dark_joins_where_layers_cross(self) -> None:
        image = _grey(30)
        assert len(_draw(image)) * 2 < len(_draw(image, join_in_dark=False))

    def test_busy_areas_get_smaller_patches(self) -> None:
        flat = _draw(_grey(120, (200, 200)), layer_angles=(0.0,), follow_edges=False)
        noise = np.random.default_rng(0).integers(60, 180, (200, 200)).astype(np.uint8)
        busy = _draw(Image.fromarray(noise), layer_angles=(0.0,), follow_edges=False)
        # More, smaller patches give more line pieces for similar ink.
        assert len(busy) > len(flat)

    @pytest.mark.parametrize(("ppm", "pen"), [(0.0, 0.3), (-1.0, 0.3), (4.0, 0.0), (math.nan, 0.3)])
    def test_rejects_bad_scale(self, ppm: float, pen: float) -> None:
        with pytest.raises(ValueError):
            patch_hatch_strokes(_grey(0), PatchHatchSettings(), ppm, pen)

    def test_tiny_image(self) -> None:
        assert patch_hatch_strokes(_grey(0, (1, 1)), PatchHatchSettings(), 4.0, 0.3) == []


class TestAngleOffset:
    def test_rotates_and_wraps(self) -> None:
        settings = PatchHatchSettings(layer_angles=(0.0, 350.0))
        rotated = with_layer_angle_offset(settings.model_copy(update={"thresholds": None}), 30.0)
        assert rotated.layer_angles == pytest.approx((30.0, 20.0))
        assert settings.layer_angles == (0.0, 350.0)


class TestRegistrationAndPresets:
    def test_registered(self) -> None:
        assert "patch_hatch" in list_pfms()
        fn, model = get_pfm("patch_hatch")
        assert fn is patch_hatch_strokes
        assert model is PatchHatchSettings

    def test_info_pfms_lists_it(self) -> None:
        result = CliRunner().invoke(main, ["info", "pfms", "--format", "json"])
        assert result.exit_code == 0, result.output
        row = next(
            p for p in json.loads(result.stdout)["available_pfms"] if p["name"] == "patch_hatch"
        )
        assert row["settings_model"] == "PatchHatchSettings"
        assert row["presets"] == _PRESET_IDS

    @pytest.mark.parametrize("preset_id", _PRESET_IDS)
    def test_presets_resolve(self, preset_id: str) -> None:
        pfm_type, settings = get_pfm_preset_by_id(preset_id)
        assert pfm_type == "patch_hatch"
        assert settings == PATCH_HATCH_PRESETS[preset_id.partition(":")[2]]
        assert preset_id in list_presets_for_pfm("patch_hatch")

    def test_cli_settings_override(self) -> None:
        pfm = _resolve_pfm("patch_hatch:fine", {"spacing": "0.6", "join_lines": "yes"})
        assert isinstance(pfm, RegisteredPFM)
        assert isinstance(pfm.settings, PatchHatchSettings)
        assert pfm.settings.spacing == 0.6
        assert pfm.settings.join_lines is True
        assert pfm.settings.patch_size == PATCH_HATCH_PRESETS["fine"].patch_size

    def test_project_round_trip(self, tmp_path: Path) -> None:
        image_path = tmp_path / "input.png"
        image_path.write_bytes(b"fake png")
        settings = PatchHatchSettings(spacing=0.7, seed=42, thresholds=(0.2, 0.4, 0.6, 0.8))
        project = Project(
            image=ImageRef(path=image_path, filters=FilterPipeline(), dpi=300),
            paper=Paper(name="a4", width_mm=210.0, height_mm=297.0),
            pen=Pen(name="fine", width_mm=0.3),
            pfm=RegisteredPFM(pfm_type="patch_hatch", settings=settings),
            output_path=tmp_path / "out.svg",
        )
        path = tmp_path / "project.yaml"
        save_yaml(project, path)
        loaded = load_yaml(path)
        assert isinstance(loaded.pfm, RegisteredPFM)
        assert loaded.pfm.to_typed_settings() == settings


def test_convert_cli_writes_svg(tmp_path: Path) -> None:
    image = Image.new("RGB", (80, 80), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((10, 10, 70, 70), fill=(70, 70, 70))
    source = tmp_path / "source.png"
    image.save(source)
    output = tmp_path / "out.svg"
    result = CliRunner().invoke(
        main,
        [
            "convert",
            str(source),
            "-o",
            str(output),
            "--no-vpype",
            "--pfm",
            "patch_hatch",
            "-s",
            "seed=1",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "<path" in output.read_text() or "<polyline" in output.read_text()
