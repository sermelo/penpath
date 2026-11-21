"""vpype CLI wrapper for line optimization and SVG export."""

from __future__ import annotations

import contextlib
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from shapely import LineString

if TYPE_CHECKING:
    from collections.abc import Iterable

    from penpath.core.models import Paper, Pen


def _create_vpype_script(geometries: Iterable[LineString], layer_id: int) -> str:
    """Generate a Python script for vpype's `script` command.

    The script returns geometries as a MultiLineString for the given layer.

    Parameters
    ----------
    geometries : Iterable[LineString]
        Line geometries in pixel coordinates (1/96 inch = 1 SVG pixel).
    layer_id : int
        Target layer ID (1-indexed for vpype).

    Returns
    -------
    str
        Python script content.
    """
    coords_list = []
    for line in geometries:
        if line.is_empty:
            continue
        coords = list(line.coords)
        if len(coords) < 2:
            continue
        coords_list.append(coords)

    if not coords_list:
        return """
def generate():
    from shapely import MultiLineString
    return MultiLineString()
"""

    coords_repr = ",\n        ".join(str(c) for c in coords_list)
    return f"""
def generate():
    from shapely import MultiLineString
    return MultiLineString([
        {coords_repr}
    ])
"""


def run_vpype(
    geometries: list[LineString],
    paper: Paper,
    pens: list[Pen],
    vpype_path: str = "vpype",
) -> bytes:
    """Run vpype pipeline for line optimization and SVG export.

    Pipeline: linemerge -> linesimplify -> reloop -> linesort -> write
    Output is centered on the page with the specified page size.

    Parameters
    ----------
    geometries : list[LineString]
        Input line geometries in pixel coordinates (1/96 inch per unit).
    paper : Paper
        Paper configuration (size, margins, DPI).
    pens : list[Pen]
        Pen configurations. First pen gets all geometries (MVP: single pen).
    vpype_path : str, optional
        Path to vpype executable. Defaults to "vpype" in PATH.

    Returns
    -------
    bytes
        SVG output from vpype stdout.

    Raises
    ------
    FileNotFoundError
        If vpype executable is not found.
    RuntimeError
        If vpype command fails.
    ValueError
        If no pens provided or no valid geometries.
    """
    if not pens:
        raise ValueError("At least one pen must be provided")

    if not geometries:
        raise ValueError("No geometries provided")

    valid_geometries = [g for g in geometries if not g.is_empty and len(list(g.coords)) >= 2]
    if not valid_geometries:
        raise ValueError("No valid geometries (need at least 2 points per line)")

    # Create temporary script files for each layer
    temp_files: list[Path] = []
    try:
        # Build vpype command
        cmd = [vpype_path]

        # Add script commands for each pen layer
        for i, _pen in enumerate(pens):
            layer_id = i + 1  # vpype layers are 1-indexed
            script_content = _create_vpype_script(
                valid_geometries if i == 0 else [],  # Only first pen gets geometries (MVP)
                layer_id,
            )

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False, prefix=f"penpath_vpype_layer{layer_id}_"
            ) as f:
                f.write(script_content)
                temp_files.append(Path(f.name))

            cmd.extend(["script", "--layer", str(layer_id), str(temp_files[-1])])

        # Add optimization pipeline
        cmd.extend(
            [
                "linemerge",
                "linesimplify",
                "reloop",
                "linesort",
                "write",
                "--page-size",
                paper.to_vpype_page_size(),
                "--center",
                "--format",
                "SVG",
                "-",  # Write to stdout
            ]
        )

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=False,
            check=True,
        )
        return result.stdout

    except FileNotFoundError as e:
        raise FileNotFoundError(
            f"vpype executable not found at '{vpype_path}'. Install it with: pip install vpype"
        ) from e
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else "Unknown error"
        raise RuntimeError(f"vpype command failed (exit code {e.returncode}): {stderr}") from e
    finally:
        # Clean up temporary script files
        for temp_file in temp_files:
            with contextlib.suppress(OSError):
                temp_file.unlink()


__all__ = ["run_vpype"]
