"""Unit tests for the public ``penpath.convert`` facade."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel
from shapely import LineString

import penpath
from penpath import Drawing, convert
from penpath.core import ResolutionError, build_project, resolve_palette
from penpath.core.drawing.registry import get_registry, register_pfm
from penpath.core.models import Paper, Pen
from penpath.presets.pfms import list_pfm_presets, register_pfm_preset

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CIRCLE = FIXTURES / "images" / "reference" / "circle.png"
SPHERE = FIXTURES / "images" / "reference" / "sphere.png"


def _svg_bytes(drawing: Drawing, tmp_path: Path, name: str) -> bytes:
    """Export a drawing without vpype so two runs can be compared byte for byte."""
    path = tmp_path / f"{name}.svg"
    drawing.to_svg(path, use_vpype=False)
    return path.read_bytes()


class SpySettings(BaseModel):
    """Settings for a registered PFM that records what it received."""

    seed: int | None = None


SPY_SEEN: dict[str, object] = {}


def _spy(image: object, settings: BaseModel) -> list[LineString]:
    """Record a PFM's settings and return one short stroke."""
    SPY_SEEN["settings"] = settings
    return [LineString([(0.0, 0.0), (1.0, 1.0)])]


@pytest.fixture
def spy_pfm() -> dict[str, object]:
    """Register a PFM and preset that capture the settings they were given."""
    SPY_SEEN.clear()
    if "api_test_spy" not in get_registry():
        register_pfm("api_test_spy", _spy, SpySettings)
    if "api_test_spy:calm" not in list_pfm_presets():
        register_pfm_preset("api_test_spy:calm", "api_test_spy", SpySettings(seed=7))
    return SPY_SEEN


def test_public_exports_expose_convert_and_drawing() -> None:
    """Library users can import the facade from the package root."""
    assert penpath.convert is convert
    assert penpath.Drawing is Drawing
    assert penpath.main.name == "main"


def test_convert_returns_drawing_for_a_fixture(tmp_path: Path) -> None:
    """A plain call converts a fixture without needing any CLI code."""
    drawing = convert(
        CIRCLE,
        settings={"seed": 42},
        use_vpype=False,
        max_resolution_px=48,
        output=tmp_path / "out.svg",
    )

    assert isinstance(drawing, Drawing)
    assert drawing.strokes_by_pen[0]
    assert (tmp_path / "out.svg").exists()


def test_preset_and_settings_reach_the_pfm(spy_pfm: dict[str, object]) -> None:
    """A named preset supplies settings and explicit settings win over it."""
    convert(
        CIRCLE,
        pfm="api_test_spy",
        preset="calm",
        use_vpype=False,
        max_resolution_px=48,
    )
    preset_settings = spy_pfm["settings"]
    assert isinstance(preset_settings, SpySettings)
    assert preset_settings.seed == 7

    convert(
        CIRCLE,
        pfm="api_test_spy",
        preset="calm",
        settings={"seed": 42},
        use_vpype=False,
        max_resolution_px=48,
    )
    override_settings = spy_pfm["settings"]
    assert isinstance(override_settings, SpySettings)
    assert override_settings.seed == 42


def test_typed_settings_model_with_bool_and_tuple_reaches_the_pfm(
    spy_pfm: dict[str, object],
) -> None:
    """Already-typed values are validated instead of parsed as CLI strings."""

    class TypedSettings(BaseModel):
        seed: int = 3
        shading_enabled: bool = False
        angle_range: tuple[float, float] = (0.0, 90.0)

    if "api_typed_spy" not in get_registry():
        register_pfm("api_typed_spy", _spy, TypedSettings)
    convert(
        CIRCLE,
        pfm="api_typed_spy",
        settings=TypedSettings(seed=11, shading_enabled=True, angle_range=(10.0, 40.0)),
        use_vpype=False,
        max_resolution_px=48,
    )

    received = spy_pfm["settings"]
    assert isinstance(received, TypedSettings)
    assert received.seed == 11
    assert received.shading_enabled is True
    assert received.angle_range == (10.0, 40.0)


def test_paper_and_pen_objects_override_defaults(tmp_path: Path) -> None:
    """Callers may pass Paper and Pen objects instead of preset names."""
    drawing = convert(
        CIRCLE,
        paper=Paper(name="small", width_mm=50.0, height_mm=50.0),
        pen=Pen(name="test", width_mm=0.2, color="#123456"),
        settings={"seed": 42},
        use_vpype=False,
        max_resolution_px=48,
        output=tmp_path / "objects.svg",
    )

    assert drawing.paper.name == "small"
    assert drawing.paper.width_mm == 50.0
    assert [pen.name for pen in drawing.pens] == ["test"]
    assert 'stroke="#123456"' in (tmp_path / "objects.svg").read_text()


def test_palette_object_adds_each_pen(tmp_path: Path) -> None:
    """An explicit list of pens is used as a palette."""
    drawing = convert(
        CIRCLE,
        palette=[
            Pen(name="red", width_mm=0.3, color="#FF0000"),
            Pen(name="blue", width_mm=0.3, color="#0000FF"),
        ],
        settings={"seed": 42},
        use_vpype=False,
        max_resolution_px=48,
    )

    assert {"red", "blue"} <= {pen.name for pen in drawing.pens}


def test_builtin_palette_name_is_resolved() -> None:
    """A palette name string resolves to that palette's pens."""
    drawing = convert(
        CIRCLE,
        palette="stabilo_88",
        settings={"seed": 42},
        use_vpype=False,
        max_resolution_px=48,
    )

    assert len(drawing.pens) == 12
    assert "stabilo_88_blue" in {pen.name for pen in drawing.pens}


def test_palette_name_and_objects_produce_identical_drawings(tmp_path: Path) -> None:
    """A name, its resolved Palette and its pens all take the palette path."""
    palette = resolve_palette("stabilo_88")
    by_name = convert(
        SPHERE,
        palette="stabilo_88",
        settings={"seed": 42},
        use_vpype=False,
        max_resolution_px=64,
    )
    by_object = convert(
        SPHERE,
        palette=palette,
        settings={"seed": 42},
        use_vpype=False,
        max_resolution_px=64,
    )
    by_list = convert(
        SPHERE,
        palette=list(palette.pens),
        settings={"seed": 42},
        use_vpype=False,
        max_resolution_px=64,
    )

    assert by_object.strokes_by_pen == by_name.strokes_by_pen
    assert by_list.strokes_by_pen == by_name.strokes_by_pen
    assert _svg_bytes(by_object, tmp_path, "object") == _svg_bytes(by_name, tmp_path, "name")
    assert _svg_bytes(by_list, tmp_path, "list") == _svg_bytes(by_name, tmp_path, "same")


def test_pen_and_palette_overrides_on_base_match_direct_mode(tmp_path: Path) -> None:
    """Switching mode on a project base applies build_project's mode defaults."""
    pen_direct = convert(
        SPHERE,
        pen="fine",
        settings={"seed": 42},
        use_vpype=False,
        max_resolution_px=64,
    )
    palette_base = build_project(SPHERE, palette="stabilo_88", settings={"seed": 42})
    pen_override = convert(
        SPHERE,
        project=palette_base,
        pen="fine",
        settings={"seed": 42},
        use_vpype=False,
        max_resolution_px=64,
    )
    assert pen_override.strokes_by_pen == pen_direct.strokes_by_pen
    assert _svg_bytes(pen_override, tmp_path, "pen_override") == _svg_bytes(
        pen_direct, tmp_path, "pen_direct"
    )

    palette_direct = convert(
        SPHERE,
        palette="stabilo_88",
        settings={"seed": 42},
        use_vpype=False,
        max_resolution_px=64,
    )
    pen_base = build_project(SPHERE, pen="fine", settings={"seed": 42})
    palette_override = convert(
        SPHERE,
        project=pen_base,
        palette="stabilo_88",
        settings={"seed": 42},
        use_vpype=False,
        max_resolution_px=64,
    )
    assert palette_override.strokes_by_pen == palette_direct.strokes_by_pen
    assert _svg_bytes(palette_override, tmp_path, "palette_override") == _svg_bytes(
        palette_direct, tmp_path, "palette_direct"
    )


def test_one_pen_palette_base_override_matches_direct_pen(tmp_path: Path) -> None:
    """A one-pen palette base is still palette mode for a pen override."""
    pen_direct = convert(
        SPHERE,
        pen="fine",
        settings={"seed": 42},
        use_vpype=False,
        max_resolution_px=64,
    )
    solo_base = build_project(SPHERE, palette="solo=0.3,#000000", settings={"seed": 42})
    pen_override = convert(
        SPHERE,
        project=solo_base,
        pen="fine",
        settings={"seed": 42},
        use_vpype=False,
        max_resolution_px=64,
    )

    assert pen_override.strokes_by_pen == pen_direct.strokes_by_pen
    assert _svg_bytes(pen_override, tmp_path, "solo_override") == _svg_bytes(
        pen_direct, tmp_path, "solo_direct"
    )


def test_pen_and_palette_together_is_rejected() -> None:
    """The library rejects the same conflict the CLI rejects."""
    with pytest.raises(ResolutionError, match="mutually exclusive"):
        convert(CIRCLE, pen="fine", palette="stabilo_88")


def test_project_base_is_overridden_without_mutating_it(tmp_path: Path) -> None:
    """A resolved project is the base; explicit arguments win on a copy."""
    base = build_project(
        CIRCLE,
        paper="a4",
        pen="0.5,#000000",
        settings={"seed": "42"},
        dpi=150,
        output_path=tmp_path / "base.svg",
    )
    drawing = convert(
        CIRCLE,
        project=base,
        dpi=base.image.dpi,
        paper="100x100",
        output=tmp_path / "override.svg",
        use_vpype=False,
        max_resolution_px=48,
    )

    assert drawing.paper.width_mm == 100.0
    assert base.paper.width_mm == 210.0
    assert base.output_path == tmp_path / "base.svg"
    assert (tmp_path / "override.svg").exists()
