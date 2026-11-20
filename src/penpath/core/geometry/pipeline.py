"""Combined geometry optimization pipeline.

This module provides the high-level `optimize` function that chains
simplification, merging, and sorting in the correct order.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from shapely import LineString

from penpath.core.geometry.merge import merge_lines
from penpath.core.geometry.simplify import simplify
from penpath.core.geometry.sort import sort_lines

if TYPE_CHECKING:
    from collections.abc import Iterable

    from penpath.core.models import Paper


def optimize(
    lines: Iterable[LineString],
    paper: Paper,
    simplify_tol_mm: float = 0.1,
    merge_angle_deg: float = 5.0,
    merge_dist_mm: float = 0.5,
) -> list[LineString]:
    """Run the full geometry optimization pipeline.

    Pipeline order:
    1. Simplify (RDP) - reduce point count while preserving shape
    2. Merge - join collinear/connected segments
    3. Sort - minimize pen-up travel distance

    Parameters
    ----------
    lines : Iterable[LineString]
        Input line geometries in pixel coordinates.
    paper : Paper
        Paper configuration (provides DPI for mm conversions).
    simplify_tol_mm : float, optional
        RDP tolerance in millimetres. Default 0.1mm. Set to 0 to skip.
    merge_angle_deg : float, optional
        Maximum angle deviation for collinear join in degrees. Default 5°.
    merge_dist_mm : float, optional
        Maximum gap distance for collinear join in millimetres. Default 0.5mm.

    Returns
    -------
    list[LineString]
        Optimized lines in the same coordinate system.

    Raises
    ------
    ValueError
        If parameters are out of valid ranges.

    Examples
    --------
    >>> from shapely import LineString
    >>> from penpath.core.models import Paper
    >>> lines = [LineString([(0, 0), (10, 5), (20, 0)])]
    >>> paper = Paper(name="A4", width_mm=210, height_mm=297)
    >>> optimized = optimize(lines, paper, simplify_tol_mm=0.1)
    >>> len(optimized)
    1
    """
    # Validate parameters
    if simplify_tol_mm < 0:
        raise ValueError("simplify_tol_mm must be >= 0")
    if not (0 <= merge_angle_deg <= 180):
        raise ValueError("merge_angle_deg must be in [0, 180]")
    if merge_dist_mm < 0:
        raise ValueError("merge_dist_mm must be >= 0")

    lines_list = list(lines)

    if not lines_list:
        return []

    # Step 1: Simplify
    if simplify_tol_mm > 0:
        lines_list = simplify(lines_list, simplify_tol_mm, paper.dpi)
    else:
        # Still need to ensure we have a list
        lines_list = list(lines_list)

    # Step 2: Merge
    lines_list = merge_lines(
        lines_list,
        angle_tol_deg=merge_angle_deg,
        dist_tol_mm=merge_dist_mm,
        paper_dpi=paper.dpi,
    )

    # Step 3: Sort
    lines_list = sort_lines(lines_list)

    return lines_list


__all__ = [
    "optimize",
]
