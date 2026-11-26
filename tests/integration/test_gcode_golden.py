"""Golden G-code tests: the exact text a user gets from each fixture SVG.

The generic goldens pin the plain stroke shape; ``ramped.gcode`` pins the pen
offset and the D7 landing ramp from a user profile fixture.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from penpath.core import (
    build_gcode,
    get_svg_paper_size,
    list_svg_layers,
    load_profile,
    parse_svg_layers,
    parse_svg_strokes,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SIMPLE_SVG = FIXTURES / "svg" / "gcode" / "simple.svg"
MULTI_PEN_SVG = FIXTURES / "svg" / "gcode" / "multi_pen.svg"
GOLDEN_DIR = FIXTURES / "golden" / "gcode"
RAMPED_PROFILES = FIXTURES / "profiles" / "ramped.yaml"


def _build_fixture_gcode(svg_path: Path, profiles_path: Path, profile_name: str = "generic") -> str:
    page_size = get_svg_paper_size(svg_path)
    assert page_size is not None
    return build_gcode(
        parse_svg_layers(svg_path),
        load_profile(profile_name, profiles_path=profiles_path),
        page_size,
    )


@pytest.mark.parametrize(
    ("svg_path", "golden_name", "profile_name"),
    [
        (SIMPLE_SVG, "generic.gcode", "generic"),
        (MULTI_PEN_SVG, "multi_pen.gcode", "generic"),
        (SIMPLE_SVG, "ramped.gcode", "ramped"),
    ],
)
def test_gcode_matches_golden_byte_for_byte(
    svg_path: Path,
    golden_name: str,
    profile_name: str,
    update_golden: bool,
    tmp_path: Path,
) -> None:
    profiles_path = RAMPED_PROFILES if profile_name == "ramped" else tmp_path / "profiles.yaml"
    produced = _build_fixture_gcode(svg_path, profiles_path, profile_name).encode("utf-8")
    golden_path = GOLDEN_DIR / golden_name
    if update_golden:
        golden_path.write_bytes(produced)
        return

    expected = golden_path.read_bytes() if golden_path.exists() else b""
    assert produced == expected, (
        f"G-code golden drift in {golden_path}. "
        "Regenerate with: uv run pytest tests/integration/test_gcode_golden.py --update-golden\n"
        f"produced:\n{produced.decode('utf-8')}\nexpected:\n{expected.decode('utf-8')}"
    )


@pytest.mark.parametrize("svg_path", [SIMPLE_SVG, MULTI_PEN_SVG])
def test_golden_fixture_parses_the_expected_strokes(svg_path: Path, tmp_path: Path) -> None:
    strokes = parse_svg_strokes(svg_path)
    if svg_path == SIMPLE_SVG:
        assert len(strokes) == 2
        assert strokes[0].polyline == [(10.0, 10.0), (20.0, 10.0), (20.0, 20.0)]
        assert strokes[1].polyline == [(30.0, 30.0), (40.0, 30.0)]
    else:
        assert len(strokes) == 4
        assert list_svg_layers(svg_path) == [
            ("layer1", "stabilo_88_yellow"),
            ("layer2", "stabilo_88_red"),
        ]
    assert _build_fixture_gcode(svg_path, tmp_path / "profiles.yaml").startswith(
        "; penpath gcode profile=generic "
    )
