"""Golden G-code test: the exact text a user gets from the generic profile."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from penpath.core import (
    GcodeLayer,
    build_gcode,
    get_svg_paper_size,
    load_profile,
    parse_svg_strokes,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SVG_PATH = FIXTURES / "svg" / "gcode" / "simple.svg"
GOLDEN_PATH = FIXTURES / "golden" / "gcode" / "generic.gcode"
INKSCAPE_LABEL = "{http://www.inkscape.org/namespaces/inkscape}label"


def _layer_label(svg_path: Path) -> str:
    root = ET.parse(svg_path).getroot()
    for group in root.iter():
        label = group.get(INKSCAPE_LABEL)
        if label:
            return label
    raise AssertionError(f"{svg_path} has no Inkscape layer label")


def _build_fixture_gcode(profiles_path: Path) -> str:
    strokes = parse_svg_strokes(SVG_PATH)
    layer = GcodeLayer(
        pen=_layer_label(SVG_PATH),
        polylines=tuple(tuple(stroke.polyline) for stroke in strokes),
    )
    page_size = get_svg_paper_size(SVG_PATH)
    assert page_size is not None
    return build_gcode([layer], load_profile("generic", profiles_path=profiles_path), page_size)


def test_generic_gcode_matches_golden_byte_for_byte(
    update_golden: bool,
    tmp_path: Path,
) -> None:
    produced = _build_fixture_gcode(tmp_path / "profiles.yaml").encode("utf-8")
    if update_golden:
        GOLDEN_PATH.write_bytes(produced)
        return

    expected = GOLDEN_PATH.read_bytes() if GOLDEN_PATH.exists() else b""
    assert produced == expected, (
        f"G-code golden drift in {GOLDEN_PATH}. "
        "Regenerate with: uv run pytest tests/integration/test_gcode_golden.py --update-golden\n"
        f"produced:\n{produced.decode('utf-8')}\nexpected:\n{expected.decode('utf-8')}"
    )


@pytest.mark.parametrize("profile_name", ["generic"])
def test_golden_fixture_parses_two_drawn_polylines(profile_name: str, tmp_path: Path) -> None:
    strokes = parse_svg_strokes(SVG_PATH)
    assert len(strokes) == 2
    assert strokes[0].polyline == [(10.0, 10.0), (20.0, 10.0), (20.0, 20.0)]
    assert strokes[1].polyline == [(30.0, 30.0), (40.0, 30.0)]
    assert _build_fixture_gcode(tmp_path / "profiles.yaml").startswith(
        f"; penpath gcode profile={profile_name} "
    )
