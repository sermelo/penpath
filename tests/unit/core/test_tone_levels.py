"""Tests for equalised tone levels and each PFM's tone targets."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from penpath.core.drawing.pfm_contour import ContourSettings
from penpath.core.drawing.pfm_engraving import EngravingSettings
from penpath.core.drawing.pfm_hatch import HatchSettings
from penpath.core.drawing.pfm_patch_hatch import PatchHatchSettings, layer_thresholds
from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings
from penpath.core.drawing.tone_targets import CONTINUOUS_LEVELS, pfm_tone_targets
from penpath.core.image.tone_levels import (
    apply_tone_levels,
    equalize_to_targets,
    equalized_thresholds,
    quantize_levels,
    uniform_targets,
)


def test_thresholds_split_inked_pixels_evenly() -> None:
    darkness = np.concatenate((np.zeros(5000), np.linspace(0.3, 0.5, 1000)))
    thresholds = equalized_thresholds(darkness, 4)
    levels = quantize_levels(darkness[darkness > 0.01], thresholds)
    counts = np.bincount(levels, minlength=4)
    assert counts.min() > 230 and counts.max() < 270


def test_thresholds_handle_blank_and_flat_images() -> None:
    assert equalized_thresholds(np.zeros(10), 4) == (0.25, 0.5, 0.75)
    flat = equalized_thresholds(np.full(10, 0.4), 3)
    assert flat[1] > flat[0]
    with pytest.raises(ValueError):
        equalized_thresholds(np.zeros(3), 1)


def test_equalize_to_targets_puts_quantiles_on_targets() -> None:
    darkness = np.linspace(0.3, 0.5, 1001)  # a washed-out photo
    mapped = equalize_to_targets(darkness, (0.2, 0.4, 0.6, 0.8))
    for target in (0.2, 0.4, 0.6, 0.8):
        share = float(np.mean(mapped < target))
        assert share == pytest.approx(target, abs=0.02)
    assert np.all(np.diff(mapped) >= 0)  # order kept


def test_paper_stays_paper_and_black_stays_black() -> None:
    darkness = np.array([0.0, 0.3, 0.4, 1.0])
    mapped = equalize_to_targets(darkness, (0.5,))
    assert mapped[0] == 0.0 and mapped[-1] == 1.0


def test_apply_tone_levels_returns_greyscale() -> None:
    image = Image.fromarray(np.tile(np.linspace(120, 160, 50), (10, 1)).astype(np.uint8))
    result = apply_tone_levels(image.convert("RGB"), uniform_targets(4))
    assert result.mode == "L"
    values = np.asarray(result)
    assert values.max() - values.min() > 120  # stretched over the steps


def test_uniform_targets() -> None:
    assert uniform_targets(4) == (0.25, 0.5, 0.75)
    with pytest.raises(ValueError):
        uniform_targets(1)


def test_hatch_targets_are_its_bands() -> None:
    assert pfm_tone_targets(HatchSettings(), 0.3) == (0.2, 0.4, 0.6, 0.8)


def test_patch_hatch_targets_follow_pen_width() -> None:
    settings = PatchHatchSettings()
    assert pfm_tone_targets(settings, 0.3) == pytest.approx(layer_thresholds(4, 0.8, 0.3))
    assert pfm_tone_targets(settings, 0.5) != pfm_tone_targets(settings, 0.3)


def test_engraving_targets_one_per_stroke() -> None:
    targets = pfm_tone_targets(EngravingSettings(), 0.3)  # 1.5 mm / 0.3 mm: 5 strokes
    assert len(targets) == 5
    assert targets[0] == pytest.approx(0.05 + 0.95 * 0.2)


def test_contour_targets_are_its_levels() -> None:
    targets = pfm_tone_targets(ContourSettings(threshold=128, levels=1), 0.3)
    assert targets == pytest.approx((1 - 128 / 255,))


def test_continuous_algorithms_get_even_steps() -> None:
    assert pfm_tone_targets(SketchLinesSettings(), 0.3) == uniform_targets(CONTINUOUS_LEVELS)


def test_convert_equalize_levels_flag(tmp_path: pytest.TempPathFactory) -> None:
    from pathlib import Path

    from click.testing import CliRunner

    from penpath.cli.main import main

    folder = Path(str(tmp_path))
    source = folder / "flat.png"
    Image.fromarray(np.tile(np.linspace(120, 160, 60), (40, 1)).astype(np.uint8)).save(source)
    outputs = {}
    for flag in ("--no-equalize-levels", "--equalize-levels"):
        output = folder / f"{flag}.svg"
        result = CliRunner().invoke(
            main,
            ["convert", str(source), "-o", str(output), "--no-vpype", "--pfm", "hatch", flag],
        )
        assert result.exit_code == 0, result.output
        outputs[flag] = output.read_text()
    assert outputs["--no-equalize-levels"] != outputs["--equalize-levels"]
