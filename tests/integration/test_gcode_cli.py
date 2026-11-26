"""End-to-end tests for ``penpath gcode`` as a user runs it."""

from __future__ import annotations

import shutil
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
    assert "outside the drawable area" in result.stderr
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
    assert "outside the drawable area" in result.stderr
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


def test_gcode_help_lists_its_options(runner: CliRunner) -> None:
    result = runner.invoke(main, ["gcode", "--help"])

    assert result.exit_code == 0
    for option in ("--profile", "--profiles", "--dry-run", "--fit", "--no-fit", "-o, --output"):
        assert option in result.stdout
