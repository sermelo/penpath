"""End-to-end check of the documented Aquila example as a user runs it."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "aquila"


@pytest.mark.skipif(shutil.which("make") is None, reason="make is not installed")
def test_aquila_example_makefile_produces_svg_and_gcode(tmp_path: Path) -> None:
    """A clean copy of the example makes both artifacts and both previews."""
    work = tmp_path / "aquila"
    shutil.copytree(EXAMPLE, work)
    for name in ("circle.svg", "circle.gcode", "circle.svg.png", "circle.gcode.png"):
        (work / name).unlink(missing_ok=True)
    result = subprocess.run(
        ["make", "-C", str(work), f"PENPATH={sys.executable} -m penpath"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"

    svg = work / "circle.svg"
    gcode = work / "circle.gcode"
    assert svg.is_file() and gcode.is_file()
    assert (work / "circle.svg.png").is_file()
    assert (work / "circle.gcode.png").is_file()

    assert 'width="190mm"' in svg.read_text(encoding="utf-8")
    assert 'height="190mm"' in svg.read_text(encoding="utf-8")

    text = gcode.read_text(encoding="ascii")
    assert text.startswith("; penpath gcode profile=aquila page=190.000x190.000")
    assert "; ---- pen 1:" in text
    assert "G1 X212.700 Y40.600 F6000" in text
    assert "G1 Z80.000 F600" in text
    assert "G1 X0.000 Y220.000 F6000" in text
    assert not any(line.split(" ", 1)[0] in {"M2", "M25"} for line in text.splitlines())
