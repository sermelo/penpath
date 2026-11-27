"""vpype CLI wrapper for geometry optimization.

vpype contributes geometry only: it is called once per pen, its output is read
back with :func:`penpath.core.svg_parse.parse_svg_strokes`, and penpath writes
the final SVG itself so both export paths share one layout.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from shapely import LineString

from penpath.core.output.svg import (
    MM_PER_INCH,
    SVG_DPI,
    ImagePlacement,
    _as_placement,
    _clip_geometries_to_rect,
    _scale_geometries_to_placement,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from penpath.core.models import Paper, Pen
    from penpath.core.simulation import PenStroke


SVG_UNITS_PER_MM = SVG_DPI / MM_PER_INCH


def _create_vpype_script(geometries: Iterable[LineString], layer_id: int) -> str:
    """Generate a Python script for vpype's `script` command.

    The script returns geometries as a MultiLineString for the given layer.

    Parameters
    ----------
    geometries : Iterable[LineString]
        Line geometries in vpype user units (1/96 inch).
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


def _to_vpype_units(geometries: Iterable[LineString]) -> list[LineString]:
    """Convert millimetre geometry to vpype's 96-DPI user units."""
    transformed: list[LineString] = []
    for line in geometries:
        coords = list(line.coords)
        if len(coords) < 2:
            continue
        transformed.append(
            LineString([(x * SVG_UNITS_PER_MM, y * SVG_UNITS_PER_MM) for x, y in coords])
        )
    return transformed


def _optimise_one_pen(
    geometries: Sequence[LineString],
    paper: Paper,
    vpype_path: str,
    center: bool,
) -> list[PenStroke]:
    """Run one vpype call for one pen and read the optimised strokes back.

    vpype's ``reloop`` picks a random seam on closed paths, so the call pins
    vpype's own RNG with ``-s 0``; the PFM's seed alone cannot make the export
    reproducible.
    """
    from penpath.core.svg_parse import parse_svg_strokes

    script_content = _create_vpype_script(geometries, 1)
    with tempfile.TemporaryDirectory(prefix="penpath_vpype_") as tmp_dir:
        script_path = Path(tmp_dir) / "pen.py"
        script_path.write_text(script_content, encoding="utf-8")

        cmd = [
            vpype_path,
            "-s",
            "0",
            "script",
            "--layer",
            "1",
            str(script_path),
            "linemerge",
            "linesimplify",
            "reloop",
            "linesort",
            "write",
            "--page-size",
            paper.to_vpype_page_size(),
        ]
        if center:
            cmd.append("--center")
        cmd.extend(["--format", "SVG", "-"])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=False,
                check=True,
            )
        except FileNotFoundError as e:
            raise FileNotFoundError(
                f"vpype executable not found at '{vpype_path}'. "
                'Install it with: pip install "penpath[vpype]"'
            ) from e
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else "Unknown error"
            raise RuntimeError(f"vpype command failed (exit code {e.returncode}): {stderr}") from e

        svg_path = Path(tmp_dir) / "optimised.svg"
        svg_path.write_bytes(result.stdout)
        return parse_svg_strokes(svg_path)


def optimize_with_vpype(
    geometries_by_pen: Sequence[Sequence[LineString]],
    paper: Paper,
    pens: Sequence[Pen],
    vpype_path: str = "vpype",
    image_placement: ImagePlacement | tuple[float, float, float, float] | None = None,
    image_size_px: tuple[int, int] | None = None,
    clip_rect: ImagePlacement | tuple[float, float, float, float] | None = None,
) -> list[list[PenStroke]]:
    """Optimise each pen's geometry in exactly one vpype call per pen.

    A call carries a single layer, so vpype never merges or sorts geometry
    across pens. Strokes are read back in paper millimetres and penpath writes
    the final SVG. Without a placement vpype centres its output on the page;
    with one, the geometry is mapped into the placement rectangle first and
    vpype is not allowed to move it. Pens with no valid lines are skipped:
    vpype writes no SVG for empty geometry, so they return an empty list.

    Parameters
    ----------
    geometries_by_pen : Sequence[Sequence[LineString]]
        Image pixel geometries, one list per pen in drawing order.
    paper : Paper
        Paper configuration (size, margins).
    pens : Sequence[Pen]
        Pens in drawing order. Used for the one-call-per-pen contract.
    vpype_path : str, optional
        Path to vpype executable. Defaults to "vpype" in PATH.
    image_placement : ImagePlacement | tuple, optional
        Rectangle (x, y, width, height in mm) where the source image sits.
        ``image_size_px`` must also be provided.
    image_size_px : tuple[int, int], optional
        Original image size (width, height) in pixels.
    clip_rect : ImagePlacement | tuple, optional
        Rectangle in paper millimetres that the placed geometry is clipped to
        before vpype sees it, for ``fill`` mode. Keeps both export paths in
        agreement and prevents vpype from optimizing cropped-away ink.

    Returns
    -------
    list[list[PenStroke]]
        Optimised strokes per pen, in paper millimetres.

    Raises
    ------
    FileNotFoundError
        If vpype executable is not found.
    RuntimeError
        If a vpype command fails.
    ValueError
        If the pen/geometry counts disagree, a placement is given without
        the image size, or no valid geometry is supplied.
    """
    if not pens:
        raise ValueError("At least one pen must be provided")
    if len(geometries_by_pen) != len(pens):
        raise ValueError("geometries_by_pen must have one entry per pen")
    if image_placement is not None and image_size_px is None:
        raise ValueError("image_size_px is required when image_placement is provided")

    valid_by_pen = [
        [line for line in lines if not line.is_empty and len(list(line.coords)) >= 2]
        for lines in geometries_by_pen
    ]
    if not any(valid_by_pen):
        raise ValueError("No valid geometries (need at least 2 points per line)")

    placement = _as_placement(image_placement) if image_placement is not None else None
    clip = _as_placement(clip_rect) if clip_rect is not None else None
    optimized: list[list[PenStroke]] = []
    for lines in valid_by_pen:
        if not lines:
            optimized.append([])
            continue
        if placement is not None and image_size_px is not None:
            placed_mm = _scale_geometries_to_placement(lines, placement, image_size_px, clip)
        else:
            placed_mm = lines
        if clip is not None:
            placed_mm = _clip_geometries_to_rect(placed_mm, clip)
        if not placed_mm:
            optimized.append([])
            continue
        vpype_geometry = _to_vpype_units(placed_mm) if placement is not None else placed_mm
        optimized.append(
            _optimise_one_pen(vpype_geometry, paper, vpype_path, center=placement is None)
        )
    return optimized


__all__ = ["optimize_with_vpype"]
