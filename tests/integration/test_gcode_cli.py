"""End-to-end tests for ``penpath gcode`` as a user runs it."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from penpath.cli.main import main

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SIMPLE_SVG = FIXTURES / "svg" / "gcode" / "simple.svg"
MULTI_PEN_SVG = FIXTURES / "svg" / "gcode" / "multi_pen.svg"
AQUILA_SVG = FIXTURES / "svg" / "gcode" / "aquila_card.svg"
GENERIC_PROFILE = FIXTURES.parent.parent / "src/penpath/presets/profiles/generic.yaml"
RAMPED_PROFILE = FIXTURES / "profiles" / "ramped.yaml"
GOLDEN = (FIXTURES / "golden" / "gcode" / "generic.gcode").read_text(encoding="utf-8")
GOLDEN_MULTI = (FIXTURES / "golden" / "gcode" / "multi_pen.gcode").read_text(encoding="utf-8")
GOLDEN_RAMPED = (FIXTURES / "golden" / "gcode" / "ramped.gcode").read_text(encoding="utf-8")
GOLDEN_AQUILA = (FIXTURES / "golden" / "gcode" / "aquila.gcode").read_text(encoding="utf-8")
SUMMARY_LINES = (
    "G-code summary",
    "Profile: generic",
    "Layers: 1",
    "Drawing length:",
    "Pen-up travel:",
    "Pen lifts:",
    "Estimated plot time:",
)


@pytest.fixture(autouse=True)
def isolated_profiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the real user profiles file out of these tests."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def card(tmp_path: Path) -> Path:
    target = tmp_path / "card.svg"
    shutil.copyfile(SIMPLE_SVG, target)
    return target


@pytest.fixture
def slightly_outside_card(tmp_path: Path) -> Path:
    """A 190x190 page whose rightmost point sits 0.131 mm past the Aquila area."""
    drawing = tmp_path / "card.svg"
    drawing.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg"
 xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
 width="190mm" height="190mm" viewBox="0 0 190 190">
<g inkscape:groupmode="layer" inkscape:label="stabilo_88_black" id="layer1"
 fill="none" stroke="#000000" stroke-width="0.3"><polyline points="10,10 190.131,10"/></g>
</svg>""",
        encoding="utf-8",
    )
    return drawing


def _user_profile(tmp_path: Path, name: str, body: str) -> Path:
    """Write a user profiles file with one machine under ``name``."""
    path = tmp_path / "profiles.yaml"
    indented = "".join(
        f"  {line}" if line.strip() else line for line in body.splitlines(keepends=True)
    )
    path.write_text(f"{name}:\n{indented}", encoding="utf-8")
    return path


def test_gcode_writes_default_output_matching_golden(runner: CliRunner, card: Path) -> None:
    result = runner.invoke(main, ["gcode", str(card), "--profile", "generic"])

    assert result.exit_code == 0, result.stderr
    assert result.stdout == ""
    assert card.with_suffix(".gcode").read_text(encoding="utf-8") == GOLDEN
    assert "G-code saved to:" in result.stderr
    for line in SUMMARY_LINES:
        assert line in result.stderr, result.stderr


def test_gcode_writes_explicit_output(runner: CliRunner, card: Path, tmp_path: Path) -> None:
    output = tmp_path / "nested" / "card.gcode"

    result = runner.invoke(main, ["gcode", str(card), "--profile", "generic", "-o", str(output)])

    assert result.exit_code == 0, result.stderr
    assert result.stdout == ""
    assert output.read_text(encoding="utf-8") == GOLDEN
    assert str(output) in result.stderr
    assert not card.with_suffix(".gcode").exists()


def test_gcode_unknown_profile_exits_2_and_lists_profiles(runner: CliRunner, card: Path) -> None:
    result = runner.invoke(main, ["gcode", str(card), "--profile", "nope"])

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "Unknown profile" in result.stderr
    assert "Available:" in result.stderr
    assert "generic" in result.stderr
    assert not card.with_suffix(".gcode").exists()


def test_gcode_missing_profile_exits_2_and_lists_profiles(runner: CliRunner, card: Path) -> None:
    result = runner.invoke(main, ["gcode", str(card)])

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "Missing option '--profile'" in result.stderr
    assert "generic" in result.stderr


def test_gcode_missing_profiles_file_exits_3_with_fix(
    runner: CliRunner, card: Path, tmp_path: Path
) -> None:
    missing = tmp_path / "missing.yaml"

    result = runner.invoke(
        main, ["gcode", str(card), "--profile", "generic", "--profiles", str(missing)]
    )

    assert result.exit_code == 3
    assert result.stdout == ""
    assert "Cannot read profile file" in result.stderr
    assert str(missing) in result.stderr
    assert "--profiles" in result.stderr


def test_gcode_invalid_yaml_exits_3_with_file_and_line(
    runner: CliRunner, card: Path, tmp_path: Path
) -> None:
    broken = tmp_path / "broken.yaml"
    broken.write_text("generic:\n  bed: [\n", encoding="utf-8")

    result = runner.invoke(
        main, ["gcode", str(card), "--profile", "generic", "--profiles", str(broken)]
    )

    assert result.exit_code == 3
    assert result.stdout == ""
    assert "Invalid YAML" in result.stderr
    assert "broken.yaml" in result.stderr
    assert "line" in result.stderr


def test_gcode_invalid_profile_value_exits_3_naming_key(
    runner: CliRunner, card: Path, tmp_path: Path
) -> None:
    profiles = _user_profile(
        tmp_path,
        "generic",
        """version: 1
name: generic
bed:
  size_mm: [210.0, 297.0]
feed:
  travel_mm_s: -1.0
  draw_mm_s: 50.0
pen:
  z_up: 5.0
  z_down: 0.0
""",
    )

    result = runner.invoke(
        main, ["gcode", str(card), "--profile", "generic", "--profiles", str(profiles)]
    )

    assert result.exit_code == 3
    assert "feed.travel_mm_s" in result.stderr


def test_gcode_point_outside_bed_exits_3_with_coordinates(
    runner: CliRunner, card: Path, tmp_path: Path
) -> None:
    profiles = _user_profile(
        tmp_path,
        "tiny",
        """version: 1
name: tiny
bed:
  size_mm: [15.0, 15.0]
feed:
  travel_mm_s: 100.0
  draw_mm_s: 50.0
pen:
  z_up: 5.0
  z_down: 0.0
""",
    )

    result = runner.invoke(
        main,
        ["gcode", str(card), "--profile", "tiny", "--profiles", str(profiles), "--no-fit"],
    )

    assert result.exit_code == 3
    assert "outside the usable area" in result.stderr
    assert "x=10.000, y=287.000" in result.stderr


def test_gcode_dry_run_sends_only_gcode_to_stdout(runner: CliRunner, card: Path) -> None:
    result = runner.invoke(main, ["gcode", str(card), "--profile", "generic", "--dry-run"])

    assert result.exit_code == 0, result.stderr
    assert result.stdout == GOLDEN
    for line in SUMMARY_LINES:
        assert line in result.stderr, result.stderr
    assert "G-code saved to:" not in result.stderr
    assert not card.with_suffix(".gcode").exists()


def test_gcode_uses_custom_user_profile(runner: CliRunner, card: Path, tmp_path: Path) -> None:
    body = GENERIC_PROFILE.read_text(encoding="utf-8").replace("name: generic", "name: custom")
    profiles = _user_profile(tmp_path, "custom", body)

    result = runner.invoke(
        main, ["gcode", str(card), "--profile", "custom", "--profiles", str(profiles), "--dry-run"]
    )

    assert result.exit_code == 0, result.stderr
    assert result.stdout.startswith("; penpath gcode profile=custom ")
    assert "Profile: custom" in result.stderr


def test_gcode_multi_pen_writes_two_layers_in_document_order(
    runner: CliRunner, tmp_path: Path
) -> None:
    drawing = tmp_path / "card.svg"
    drawing.write_text(MULTI_PEN_SVG.read_text(encoding="utf-8"), encoding="utf-8")

    result = runner.invoke(main, ["gcode", str(drawing), "--profile", "generic"])

    assert result.exit_code == 0, result.stderr
    assert result.stdout == ""
    output = drawing.with_suffix(".gcode").read_text(encoding="utf-8")
    assert output == GOLDEN_MULTI
    assert output.count("; pen change") == 1
    assert output.index("; layer 1/2 pen=stabilo_88_yellow") < output.index("; pen change")
    assert output.index("; pen change") < output.index("; layer 2/2 pen=stabilo_88_red")
    assert "  Layers: 2" in result.stderr


def test_gcode_multi_pen_dry_run_sends_only_gcode_to_stdout(runner: CliRunner) -> None:
    result = runner.invoke(main, ["gcode", str(MULTI_PEN_SVG), "--profile", "generic", "--dry-run"])

    assert result.exit_code == 0, result.stderr
    assert result.stdout == GOLDEN_MULTI
    assert "G-code saved to:" not in result.stderr


def test_gcode_with_offset_and_ramp_matches_golden(runner: CliRunner, card: Path) -> None:
    """A user profile with a pen offset and ramp produces the pinned G-code."""
    result = runner.invoke(
        main,
        [
            "gcode",
            str(card),
            "--profile",
            "ramped",
            "--profiles",
            str(RAMPED_PROFILE),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.stderr
    assert result.stdout == GOLDEN_RAMPED
    assert "Profile: ramped" in result.stderr
    assert "G1 X12.000 Y290.000 Z2.000 F1800" in result.stdout


def test_gcode_aquila_writes_golden_file(runner: CliRunner, tmp_path: Path) -> None:
    """A user runs `penpath gcard.svg --profile aquila` on a card that fits the bed."""
    card = tmp_path / "card.svg"
    shutil.copyfile(AQUILA_SVG, card)

    result = runner.invoke(main, ["gcode", str(card), "--profile", "aquila"])

    assert result.exit_code == 0, result.stderr
    assert result.stdout == ""
    assert card.with_suffix(".gcode").read_text(encoding="utf-8") == GOLDEN_AQUILA
    assert "Profile: aquila" in result.stderr


def test_gcode_aquila_dry_run_keeps_the_reference_blocks(runner: CliRunner) -> None:
    """The built-in profile emits the proven start, pen-change and end sequences."""
    result = runner.invoke(main, ["gcode", str(AQUILA_SVG), "--profile", "aquila", "--dry-run"])

    assert result.exit_code == 0, result.stderr
    assert result.stdout == GOLDEN_AQUILA
    for line in (
        "M84 S0 ; no stepper timeout during the pauses",
        "G1 X212.700 Y40.600 F6000",
        "M0 Pen 1: stabilo_88_black. Touch paper, tighten, press knob",
        "G1 X0.000 Y220.000 F6000 ; head left, bed forward: paper free to take out",
        "M117 Plot done",
    ):
        assert line in result.stdout


def test_gcode_fits_slightly_oversized_page_by_default(
    runner: CliRunner, slightly_outside_card: Path
) -> None:
    """The reported repro: a page `convert` accepted now plots on the Aquila."""
    result = runner.invoke(main, ["gcode", str(slightly_outside_card), "--profile", "aquila"])

    assert result.exit_code == 0, result.stderr
    assert result.stdout == ""
    assert slightly_outside_card.with_suffix(".gcode").is_file()
    assert "Warning: drawing is" in result.stderr
    assert "past the aquila drawable area" in result.stderr
    assert "fitted with scale 1.000 and shift (-0.881, 0.000) mm" in result.stderr


def test_gcode_no_fit_rejects_slightly_oversized_page_with_fix(
    runner: CliRunner, slightly_outside_card: Path
) -> None:
    """The strict opt-out names the 0.131 mm overshoot and how to fix it."""
    result = runner.invoke(
        main, ["gcode", str(slightly_outside_card), "--profile", "aquila", "--no-fit"]
    )

    assert result.exit_code == 3
    assert result.stdout == ""
    assert "overshoot x=0.131 mm, y=0.000 mm" in result.stderr
    assert "Pass --fit (the default) or use a smaller --paper." in result.stderr
    assert not slightly_outside_card.with_suffix(".gcode").exists()


def test_gcode_dry_run_with_fit_keeps_stdout_gcode_only(
    runner: CliRunner, slightly_outside_card: Path
) -> None:
    result = runner.invoke(
        main, ["gcode", str(slightly_outside_card), "--profile", "aquila", "--dry-run", "--fit"]
    )

    assert result.exit_code == 0, result.stderr
    assert result.stdout.startswith("; penpath gcode profile=aquila ")
    assert all(
        line.startswith((";", "G", "M")) for line in result.stdout.splitlines() if line.strip()
    )
    assert "Warning:" not in result.stdout
    assert "Warning:" in result.stderr
    assert not slightly_outside_card.with_suffix(".gcode").exists()


def test_gcode_fit_within_tolerance_leaves_drawing_alone(runner: CliRunner, tmp_path: Path) -> None:
    """An overrun inside FIT_TOLERANCE_MM changes nothing and prints no warning."""
    drawing = tmp_path / "within_tolerance.svg"
    drawing.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg"
 xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
 width="190mm" height="190mm" viewBox="0 0 190 190">
<g inkscape:groupmode="layer" inkscape:label="stabilo_88_black" id="layer1"
 fill="none" stroke="#000000" stroke-width="0.3"><polyline points="10,10 189.28,10"/></g>
</svg>""",
        encoding="utf-8",
    )

    fitted = runner.invoke(
        main, ["gcode", str(drawing), "--profile", "aquila", "--dry-run", "--fit"]
    )
    strict = runner.invoke(
        main, ["gcode", str(drawing), "--profile", "aquila", "--dry-run", "--no-fit"]
    )

    assert fitted.exit_code == 0, fitted.stderr
    assert strict.exit_code == 0, strict.stderr
    assert "Warning:" not in fitted.stderr
    assert fitted.stdout == strict.stdout


def test_gcode_fits_far_point_by_default(runner: CliRunner, tmp_path: Path) -> None:
    """A point 9 mm outside is fitted rather than rejected with the default."""
    drawing = tmp_path / "outside.svg"
    drawing.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg"
 xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
 width="190mm" height="190mm" viewBox="0 0 190 190">
<g inkscape:groupmode="layer" inkscape:label="stabilo_88_black" id="layer1"
 fill="none" stroke="#000000" stroke-width="0.3"><polyline points="10,10 199,10"/></g>
</svg>""",
        encoding="utf-8",
    )

    result = runner.invoke(main, ["gcode", str(drawing), "--profile", "aquila"])

    assert result.exit_code == 0, result.stderr
    assert result.stdout == ""
    assert drawing.with_suffix(".gcode").is_file()
    assert "Warning: drawing is" in result.stderr
    assert "fitted with scale 1.000 and shift (-9.750, 0.000) mm" in result.stderr


def test_gcode_aquila_rejects_point_outside_machine_drawable_area(
    runner: CliRunner, tmp_path: Path
) -> None:
    """The built-in Aquila refuses a pen point past its reference reach with --no-fit."""
    drawing = tmp_path / "outside.svg"
    drawing.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg"
 xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
 width="190mm" height="190mm" viewBox="0 0 190 190">
<g inkscape:groupmode="layer" inkscape:label="stabilo_88_black" id="layer1"
 fill="none" stroke="#000000" stroke-width="0.3"><polyline points="10,10 199,10"/></g>
</svg>""",
        encoding="utf-8",
    )

    result = runner.invoke(main, ["gcode", str(drawing), "--profile", "aquila", "--no-fit"])

    assert result.exit_code == 3
    assert result.stdout == ""
    assert "outside the usable area" in result.stderr
    assert "X 0.000..197.300, Y 0.000..191.400" in result.stderr
    assert not drawing.with_suffix(".gcode").exists()


def test_gcode_rejects_point_outside_derived_drawable_area(
    runner: CliRunner, tmp_path: Path
) -> None:
    """The nozzle range shifted by the pen offset is the area the pen may use."""
    drawing = tmp_path / "wide.svg"
    drawing.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm"
 viewBox="0 0 100 100"><polyline points="105,10 106,10"/></svg>""",
        encoding="utf-8",
    )
    profiles = _user_profile(
        tmp_path,
        "offset",
        """version: 1
name: offset
bed:
  size_mm: [100.0, 100.0]
  pen_offset_mm: [-10.0, -10.0]
  nozzle_range_mm: [[20.0, 120.0], [20.0, 120.0]]
feed:
  travel_mm_s: 100.0
  draw_mm_s: 50.0
pen:
  z_up: 5.0
  z_down: 0.0
""",
    )

    result = runner.invoke(
        main,
        [
            "gcode",
            str(drawing),
            "--profile",
            "offset",
            "--profiles",
            str(profiles),
            "--no-fit",
        ],
    )

    assert result.exit_code == 3
    assert "x=105.000, y=90.000" in result.stderr
    assert "X 10.000..100.000" in result.stderr


def test_gcode_uses_a_user_profiles_asymmetric_margin(
    runner: CliRunner, card: Path, tmp_path: Path
) -> None:
    """A user profile's per-side margin shapes the header and the reachable check."""
    profiles = _user_profile(
        tmp_path,
        "asymmetric",
        """version: 1
name: asymmetric
bed:
  size_mm: [210.0, 297.0]
  margin_mm: [1.0, 2.0, 3.0, 4.0]
feed:
  travel_mm_s: 100.0
  draw_mm_s: 50.0
pen:
  z_up: 5.0
  z_down: 0.0
gcode:
  end: M2
""",
    )

    result = runner.invoke(
        main,
        ["gcode", str(card), "--profile", "asymmetric", "--profiles", str(profiles), "--dry-run"],
    )

    assert result.exit_code == 0, result.stderr
    assert result.stdout.startswith(
        "; penpath gcode profile=asymmetric page=210.000x297.000 "
        "page_origin=0.000,0.000 usable_x=4.000..208.000 usable_y=3.000..296.000 "
        "z_up=5.000 z_down=0.000\n"
    )
    assert "G0 X10.000 Y287.000 F6000\n" in result.stdout
    assert result.stdout.endswith("M2\n")


def _margin_profile(tmp_path: Path) -> Path:
    """Write a synthetic 30x30 machine with a 10 mm safety margin."""
    return _user_profile(
        tmp_path,
        "margin10",
        """version: 1
name: margin10
bed:
  size_mm: [30.0, 30.0]
  margin_mm: 10.0
feed:
  travel_mm_s: 100.0
  draw_mm_s: 50.0
pen:
  z_up: 5.0
  z_down: 0.0
gcode:
  end: M2
""",
    )


def _edge_page(tmp_path: Path) -> Path:
    """A 30x30 page whose stroke needs the full bed: no 10 mm margin fits it."""
    drawing = tmp_path / "edge.svg"
    drawing.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg"
  xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
  width="30mm" height="30mm" viewBox="0 0 30 30">
<g inkscape:groupmode="layer" inkscape:label="black" id="layer1"
  fill="none" stroke="#000000" stroke-width="0.3"><polyline points="5,5 8,5"/></g>
</svg>""",
        encoding="utf-8",
    )
    return drawing


def _margin_args(profiles: Path, drawing: Path, *extra: str) -> list[str]:
    return [
        "gcode",
        str(drawing),
        "--profile",
        "margin10",
        "--profiles",
        str(profiles),
        "--dry-run",
        *extra,
    ]


def test_gcode_margin_zero_uses_the_full_bed(runner: CliRunner, tmp_path: Path) -> None:
    """--margin 0 makes a page that needs the full bed plot with --no-fit."""
    profiles = _margin_profile(tmp_path)
    drawing = _edge_page(tmp_path)

    without_override = runner.invoke(main, _margin_args(profiles, drawing, "--no-fit"))
    assert without_override.exit_code == 3
    assert "outside the usable area" in without_override.stderr

    result = runner.invoke(main, _margin_args(profiles, drawing, "--no-fit", "--margin", "0"))

    assert result.exit_code == 0, result.stderr
    assert result.stdout.startswith("; penpath gcode profile=margin10 page=30.000x30.000 ")
    assert "usable_x=0.000..30.000 usable_y=0.000..30.000" in result.stdout
    assert "X5.000 Y25.000" in result.stdout
    assert "X8.000 Y25.000" in result.stdout
    assert "Warning:" not in result.stderr


def test_gcode_margin_zero_skips_the_fit_warning(runner: CliRunner, tmp_path: Path) -> None:
    """The override is applied before the default --fit path runs."""
    profiles = _margin_profile(tmp_path)
    drawing = _edge_page(tmp_path)

    fitted = runner.invoke(main, _margin_args(profiles, drawing))
    overridden = runner.invoke(main, _margin_args(profiles, drawing, "--margin", "0"))

    assert fitted.exit_code == 0, fitted.stderr
    assert "Warning: drawing is" in fitted.stderr
    assert overridden.exit_code == 0, overridden.stderr
    assert "Warning:" not in overridden.stderr
    assert "usable_x=0.000..30.000" in overridden.stdout
    assert "X5.000 Y25.000" in overridden.stdout


def test_gcode_margin_changes_the_usable_area(runner: CliRunner, tmp_path: Path) -> None:
    """A smaller override shrinks the header's usable area without moving the ink."""
    profiles = _margin_profile(tmp_path)
    drawing = tmp_path / "inside.svg"
    drawing.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg"
  xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
  width="30mm" height="30mm" viewBox="0 0 30 30">
<g inkscape:groupmode="layer" inkscape:label="black" id="layer1"
  fill="none" stroke="#000000" stroke-width="0.3"><polyline points="12,12 16,12"/></g>
</svg>""",
        encoding="utf-8",
    )

    baseline = runner.invoke(main, _margin_args(profiles, drawing))
    overridden = runner.invoke(main, _margin_args(profiles, drawing, "--margin", "5"))

    assert baseline.exit_code == 0, baseline.stderr
    assert overridden.exit_code == 0, overridden.stderr
    assert "usable_x=10.000..20.000 usable_y=10.000..20.000" in baseline.stdout
    assert "usable_x=5.000..25.000 usable_y=5.000..25.000" in overridden.stdout
    assert "X12.000 Y18.000" in baseline.stdout
    assert "X12.000 Y18.000" in overridden.stdout


def test_gcode_negative_margin_exits_2(runner: CliRunner, tmp_path: Path) -> None:
    profiles = _margin_profile(tmp_path)
    drawing = _edge_page(tmp_path)

    result = runner.invoke(main, _margin_args(profiles, drawing, "--margin", "-1"))

    assert result.exit_code == 2
    assert "Invalid value for '--margin'" in result.stderr
    assert result.stdout == ""


def test_gcode_margin_help_names_the_option(runner: CliRunner) -> None:
    result = runner.invoke(main, ["gcode", "--help"])

    assert result.exit_code == 0
    assert "--margin" in result.stdout
    assert "is allowed but not recommended on the Aquila" in result.stdout


def test_gcode_margin_end_to_end_from_the_shell(tmp_path: Path) -> None:
    """A user runs `python -m penpath gcode ... --margin 0` and pipes G-code out."""
    profiles = _margin_profile(tmp_path)
    drawing = _edge_page(tmp_path)
    env = dict(os.environ)
    env["XDG_CONFIG_HOME"] = str(tmp_path / "xdg")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "penpath",
            *_margin_args(profiles, drawing, "--no-fit", "--margin", "0"),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "usable_x=0.000..30.000 usable_y=0.000..30.000" in result.stdout
    assert "X5.000 Y25.000" in result.stdout
    assert all(
        line.startswith((";", "G", "M")) for line in result.stdout.splitlines() if line.strip()
    )
    assert not drawing.with_suffix(".gcode").exists()
