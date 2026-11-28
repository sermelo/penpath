"""Unit tests for the private helpers extracted from ``convert_cmd``."""

from __future__ import annotations

import math
from pathlib import Path

import click
import pytest
from click.core import ParameterSource
from PIL import Image

from penpath.cli.commands import convert as convert_module
from penpath.cli.commands.convert import (
    _finalize_paper,
    _load_project_with_overrides,
    _run_conversion,
    _validate_convert_args,
)
from penpath.cli.config import Config
from penpath.core.drawing.pfm_sketch_lines import SketchLinesSettings
from penpath.core.image.load import ImageLoadError
from penpath.core.image.pipeline import FilterPipeline
from penpath.core.models import ImageRef, Paper, Pen, Project, SketchLinesPFM

Validated = tuple[bool, bool, float | tuple[float, float, float, float] | None, Path | None]


def _ctx(**sources: ParameterSource) -> click.Context:
    ctx = click.Context(click.Command("convert"))
    for name, source in sources.items():
        ctx.set_parameter_source(name, source)
    return ctx


def _validate(
    *,
    ctx: click.Context | None = None,
    input_path: Path = Path("in.png"),
    output_path: Path | None = None,
    output_option: Path | None = None,
    margin_spec: str | None = None,
    max_resolution_px: int | None = None,
    background_threshold: float | None = None,
    saturation: float = 1.0,
    pen_spec: str | None = None,
    palette_spec: str | None = None,
) -> Validated:
    return _validate_convert_args(
        ctx if ctx is not None else _ctx(),
        input_path,
        output_path,
        output_option,
        margin_spec,
        max_resolution_px,
        background_threshold,
        saturation,
        pen_spec,
        palette_spec,
    )


def _project(image: Path) -> Project:
    return Project.model_construct(
        image=ImageRef.model_construct(path=image, filters=FilterPipeline(), dpi=300),
        paper=Paper(name="a4", width_mm=210.0, height_mm=297.0),
        pen=Pen(name="fine", width_mm=0.3),
        pfm=SketchLinesPFM(settings=SketchLinesSettings(seed=42)),
        output_path=Path("out.svg"),
    )


def _project_yaml(path: Path, image: Path, output: Path) -> None:
    path.write_text(
        f"""version: 1
image:
  path: "{image}"
  filters:
    steps: []
  dpi: 300
paper:
  name: a4
  width_mm: 210.0
  height_mm: 297.0
pen:
  name: fine
  width_mm: 0.3
pfm:
  pfm_type: sketch_lines
  settings:
    seed: 42
output_path: "{output}"
"""
    )


def test_validate_convert_args_rejects_non_positive_max_resolution() -> None:
    with pytest.raises(click.BadParameter) as excinfo:
        _validate(max_resolution_px=0)
    assert excinfo.value.param_hint == "--max-resolution"
    assert excinfo.value.message == "must be a positive number of pixels"


def test_validate_convert_args_rejects_non_finite_background_threshold() -> None:
    with pytest.raises(click.BadParameter) as excinfo:
        _validate(background_threshold=math.inf)
    assert excinfo.value.param_hint == "--background-threshold"
    assert excinfo.value.message == "must be a finite, non-negative Lab distance"


def test_validate_convert_args_rejects_out_of_range_saturation() -> None:
    with pytest.raises(click.BadParameter) as excinfo:
        _validate(saturation=3.1)
    assert excinfo.value.param_hint == "--saturation"
    assert excinfo.value.message == "must be a finite number in [0, 3]"


def test_validate_convert_args_rejects_pen_and_palette_together() -> None:
    with pytest.raises(click.UsageError, match="mutually exclusive"):
        _validate(pen_spec="fine", palette_spec="stabilo_88")


def test_validate_convert_args_returns_explicit_sources_margins_and_output() -> None:
    ctx = _ctx(
        background_method=ParameterSource.COMMANDLINE,
        saturation=ParameterSource.COMMANDLINE,
    )

    explicit_method, explicit_saturation, margins, output = _validate(
        ctx=ctx,
        input_path=Path("in.png"),
        output_path=Path("out.svg"),
        output_option=Path("out.svg"),
        margin_spec="20,5,20,5",
    )

    assert explicit_method is True
    assert explicit_saturation is True
    assert margins == (20.0, 5.0, 20.0, 5.0)
    assert output == Path("out.svg")


def test_validate_convert_args_defaults_explicit_sources_to_false() -> None:
    explicit_method, explicit_saturation, margins, output = _validate()

    assert explicit_method is False
    assert explicit_saturation is False
    assert margins is None
    assert output is None


def test_load_project_with_overrides_applies_every_flag_group(tmp_path: Path) -> None:
    image = tmp_path / "image.png"
    Image.new("L", (8, 8), "white").save(image)
    project_path = tmp_path / "project.yaml"
    _project_yaml(project_path, image, tmp_path / "from_project.svg")
    replacement = tmp_path / "other.png"
    replacement.write_bytes(image.read_bytes())
    overridden_output = tmp_path / "override.svg"

    project = _load_project_with_overrides(
        project_path,
        replacement,
        Config(),
        filter_specs=("grayscale",),
        style_name=None,
        pfm_name=None,
        pfm_settings=("seed=7",),
        pen_spec="0.6,#00FF00,fineliner",
        palette_spec=None,
        paper_spec="100x100,5",
        resolved_output=overridden_output,
        dpi=72,
        no_auto_orient=True,
        auto_equalize_flag=False,
        equalize_levels_flag=True,
        auto_levels_clip_opt=0.5,
        max_coverage_opt=0.9,
        background_flag=True,
        key_layer_flag=False,
        background_threshold=12.0,
        explicit_background_method=True,
        background_method="global",
        saturation=2.0,
        explicit_saturation=True,
        palette_adapt=True,
    )

    assert project.image.path == replacement
    assert len(project.image.filters.steps) == 1
    assert project.pfm.settings.seed == 7
    assert project.pen is not None and project.pen.width_mm == 0.6
    assert (project.paper.width_mm, project.paper.margin_mm) == (100.0, 5.0)
    assert project.output_path == overridden_output
    assert project.image.dpi == 72
    assert project.image.auto_orient is False
    assert project.image.auto_equalize is False
    assert project.image.equalize_levels is True
    assert project.image.auto_levels_clip == 0.5
    assert project.image.max_coverage == 0.9
    assert project.image.background is True
    assert project.image.key_layer is False
    assert project.image.background_threshold == 12.0
    assert project.image.background_method == "global"
    assert project.image.saturation == 2.0
    assert project.image.palette_adapt is False


def test_load_project_with_overrides_keeps_project_when_flags_are_unset(tmp_path: Path) -> None:
    image = tmp_path / "image.png"
    Image.new("L", (8, 8), "white").save(image)
    project_path = tmp_path / "project.yaml"
    output = tmp_path / "from_project.svg"
    _project_yaml(project_path, image, output)

    project = _load_project_with_overrides(
        project_path,
        image,
        Config(),
        filter_specs=(),
        style_name=None,
        pfm_name=None,
        pfm_settings=(),
        pen_spec=None,
        palette_spec=None,
        paper_spec=None,
        resolved_output=None,
        dpi=300,
        no_auto_orient=False,
        auto_equalize_flag=None,
        equalize_levels_flag=None,
        auto_levels_clip_opt=None,
        max_coverage_opt=None,
        background_flag=None,
        key_layer_flag=None,
        background_threshold=None,
        explicit_background_method=False,
        background_method="local",
        saturation=1.0,
        explicit_saturation=False,
        palette_adapt=False,
    )

    assert project.image.path == image
    assert project.output_path == output
    assert project.image.dpi == 300
    assert project.image.auto_equalize is True
    assert project.pfm.settings.seed == 42


def test_load_project_with_overrides_reports_a_broken_project(tmp_path: Path) -> None:
    bad_path = tmp_path / "broken.yaml"
    bad_path.write_text("version: 1\nimage: [\n")

    with pytest.raises(click.ClickException, match="Failed to load project"):
        _load_project_with_overrides(
            bad_path,
            Path("in.png"),
            Config(),
            filter_specs=(),
            style_name=None,
            pfm_name=None,
            pfm_settings=(),
            pen_spec=None,
            palette_spec=None,
            paper_spec=None,
            resolved_output=None,
            dpi=300,
            no_auto_orient=False,
            auto_equalize_flag=None,
            equalize_levels_flag=None,
            auto_levels_clip_opt=None,
            max_coverage_opt=None,
            background_flag=None,
            key_layer_flag=None,
            background_threshold=None,
            explicit_background_method=False,
            background_method="local",
            saturation=1.0,
            explicit_saturation=False,
            palette_adapt=False,
        )


def test_finalize_paper_applies_margin_and_fit() -> None:
    project = _project(Path("in.png"))

    _finalize_paper(project, 5.0, "fill", None)

    assert project.paper.margin_mm == 5.0
    assert project.paper.fit == "fill"


def test_finalize_paper_names_the_margin_flag_when_drawable_area_is_empty() -> None:
    project = _project(Path("in.png"))
    project.paper = Paper(name="tiny", width_mm=50, height_mm=50)

    with pytest.raises(click.BadParameter) as excinfo:
        _finalize_paper(project, 30.0, None, None)

    assert excinfo.value.param_hint == "--margin"


def test_run_conversion_passes_the_project_to_the_api(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_convert(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr(convert_module, "convert", fake_convert)
    project = _project(Path("in.png"))

    _run_conversion(
        Path("in.png"),
        project,
        no_vpype=True,
        vpype_path="vpype",
        max_resolution_px=64,
        no_downscale=True,
        quiet=True,
    )

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == (Path("in.png"),)
    assert kwargs["project"] is project
    assert kwargs["dpi"] == 300
    assert kwargs["output"] == Path("out.svg")
    assert kwargs["use_vpype"] is False
    assert kwargs["vpype_path"] == "vpype"
    assert kwargs["max_resolution_px"] == 64
    assert kwargs["no_downscale"] is True


def test_run_conversion_maps_image_load_errors_to_click(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise ImageLoadError("bad image")

    monkeypatch.setattr(convert_module, "convert", fail)

    with pytest.raises(click.ClickException, match="Image load error: bad image"):
        _run_conversion(
            Path("in.png"),
            _project(Path("in.png")),
            no_vpype=True,
            vpype_path="vpype",
            max_resolution_px=None,
            no_downscale=False,
            quiet=True,
        )
