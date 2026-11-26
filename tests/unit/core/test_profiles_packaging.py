"""Check that built-in profile YAML files ship inside the wheel."""

from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_builtin_profile_yaml_is_packaged_in_wheel(tmp_path: Path) -> None:
    """The wheel contains every built-in profile, ready for importlib.resources."""
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path), str(_REPO_ROOT)],
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = list(tmp_path.glob("*.whl"))
    assert wheels, "uv build did not produce a wheel"

    with zipfile.ZipFile(wheels[0]) as wheel:
        names = set(wheel.namelist())
        assert "penpath/presets/profiles/generic.yaml" in names
        assert "penpath/presets/profiles/aquila.yaml" in names
        assert "penpath/presets/profiles/__init__.py" in names
        assert "penpath/core/profiles.py" in names
