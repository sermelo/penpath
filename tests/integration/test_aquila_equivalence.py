"""Regression check that penpath's Aquila G-code matches sergio's reference script.

Source: sermelo/penpath, branch aquila-gcode-reference,
``reference/aquila_gcode/svg_plot.py`` + ``aquila_plot.py``. The reference output
is pinned as a golden file; the reference Python itself is never imported.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pytest

from penpath.core import (
    build_gcode,
    get_svg_paper_size,
    load_profile,
    parse_svg_layers,
    with_margin_mm,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SVG = FIXTURES / "svg" / "gcode" / "aquila_two_layers.svg"
REFERENCE = FIXTURES / "golden" / "gcode" / "aquila_reference_two_layers.gcode"

NUMBER = re.compile(r"-?\d+\.\d+")
COMMAND = re.compile(r"^(G\d+)\b")


def _normalize(line: str) -> str:
    """Spell numeric values the same way in both outputs, without changing them."""
    return NUMBER.sub(lambda match: f"{float(match.group()):g}", line)


def _commands(text: str) -> list[tuple[str, dict[str, float]]]:
    """Return ``(command, values)`` for each machine command line."""
    out: list[tuple[str, dict[str, float]]] = []
    for line in text.splitlines():
        match = COMMAND.match(line)
        if match is None:
            continue
        values = {
            key: float(value) for key, value in re.findall(r"([XYZF])(-?\d+(?:\.\d+)?)", line)
        }
        out.append((match.group(1), values))
    return out


def _start_block(lines: list[str]) -> list[str]:
    """Return the machine lines from G21 through the first Z12.5 lift."""
    start = next(index for index, line in enumerate(lines) if line.startswith("G21"))
    end = next(
        index
        for index in range(start, len(lines))
        if COMMAND.match(lines[index]) and "Z" in lines[index] and "F" in lines[index]
    )
    return [_normalize(line) for line in lines[start : end + 1] if not line.startswith(";")]


def _end_block(lines: list[str]) -> list[str]:
    """Return the machine lines from the Z80 park lift to the end of the file."""
    start = next(
        index
        for index, line in enumerate(lines)
        if COMMAND.match(line) and re.search(r"\bZ80(?:\.0+)?\b", line)
    )
    return [_normalize(line) for line in lines[start:] if not line.startswith(";")]


def _pen_blocks(lines: list[str]) -> list[list[str]]:
    """Return each pen's change block from its comment through the post-pause lift."""
    blocks: list[list[str]] = []
    for index, line in enumerate(lines):
        if not line.startswith("; ---- pen "):
            continue
        message = next(
            offset
            for offset in range(index, len(lines))
            if lines[offset].startswith("M117 Plotting")
        )
        lift = message + 1
        assert COMMAND.match(lines[lift]) is not None
        blocks.append(
            [_normalize(item) for item in lines[index : lift + 1] if not item.startswith(";")]
        )
    return blocks


def _penpath_text() -> str:
    """Emit the two-layer SVG through the built-in profile with its margin removed."""
    page_size = get_svg_paper_size(SVG)
    assert page_size is not None
    # Sergio's reference script ran without a safety margin; the shipped profile keeps 10 mm.
    profile = with_margin_mm(load_profile("aquila"), 0.0)
    return build_gcode(parse_svg_layers(SVG), profile, page_size)


@pytest.fixture(scope="module")
def outputs() -> tuple[list[str], list[str]]:
    """Reference and penpath G-code lines for the shared layered SVG."""
    return REFERENCE.read_text(encoding="ascii").splitlines(), _penpath_text().splitlines()


def test_aquila_reference_start_block_matches(outputs: tuple[list[str], list[str]]) -> None:
    """The start sequence is identical once decimals are spelled the same way."""
    reference, produced = outputs
    assert _start_block(produced) == _start_block(reference)


def test_aquila_reference_pen_changes_match_in_order(
    outputs: tuple[list[str], list[str]],
) -> None:
    """Both scripts pause at the touch spot for pen 1 and then pen 2."""
    reference, produced = outputs
    assert _pen_blocks(produced) == _pen_blocks(reference)
    assert len(_pen_blocks(produced)) == 2
    assert sum(line.startswith("M0 ") for line in produced) == 2


def test_aquila_reference_end_block_parks_without_m2(
    outputs: tuple[list[str], list[str]],
) -> None:
    """The end parks at X0 Y220 Z80, disables steppers and has no M2 or M25."""
    reference, produced = outputs
    assert _end_block(produced) == _end_block(reference)
    assert not any(line.split(" ", 1)[0] in {"M2", "M25"} for line in produced)


def test_aquila_reference_coordinates_z_and_feeds_match(
    outputs: tuple[list[str], list[str]],
) -> None:
    """The XY points, Z heights and feed values agree; only counts of G0 differ."""
    reference, produced = outputs
    ref_commands, pen_commands = _commands("\n".join(reference)), _commands("\n".join(produced))
    ref_xy = Counter(
        (round(values["X"], 3), round(values["Y"], 3))
        for _, values in ref_commands
        if "X" in values
    )
    pen_xy = Counter(
        (round(values["X"], 3), round(values["Y"], 3))
        for _, values in pen_commands
        if "X" in values
    )
    assert pen_xy == ref_xy

    ref_z = Counter(round(values["Z"], 3) for _, values in ref_commands if "Z" in values)
    pen_z = Counter(round(values["Z"], 3) for _, values in pen_commands if "Z" in values)
    assert pen_z == ref_z + Counter({12.5: 1})

    ref_feeds = {int(values["F"]) for _, values in ref_commands if "F" in values}
    pen_feeds = {int(values["F"]) for _, values in pen_commands if "F" in values}
    assert pen_feeds == ref_feeds == {600, 1500, 6000}
