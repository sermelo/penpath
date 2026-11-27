"""Patch Hatch PFM: hand-drawn style cross-hatching in small patches.

Where the Hatch PFM lays page-wide parallel lines (an engraving or halftone
screen look), Patch Hatch imitates pen-and-ink hatching done by hand. The
image is cut into small irregular patches: a quadtree splits busy areas into
smaller cells, the cell centres are jittered and turned into Voronoi cells,
and every cell is grown slightly so neighbours overlap. Each patch gets its
own base direction, taken from the local structure tensor so strokes follow
the edges of the form; where the image has no clear direction the patch gets
a seeded random angle. Darker tones add layers at other angles inside the
patch, so tone is built up by cross-hatching. Line spacing is in millimetres
and never below the pen width, and the line ends are trimmed at random to
give the rough patch edges of hand hatching.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING

import numpy as np
import shapely
from numpy.typing import NDArray
from pydantic import BaseModel, Field, field_validator
from shapely import LineString, MultiPoint, Polygon, voronoi_polygons
from shapely.affinity import scale as scale_geometry
from shapely.geometry import box
from skimage.filters import gaussian

if TYPE_CHECKING:
    from PIL import Image

_EPS = 1e-9
_COHERENCE_MIN = 0.25
"""Below this structure-tensor coherence a patch has no clear direction."""


class PatchHatchSettings(BaseModel):
    """Settings for the Patch Hatch PFM (hand-drawn cross-hatching in patches).

    All lengths are in millimetres on paper. The image scale is passed to
    :func:`patch_hatch_strokes` as ``pixels_per_mm``.

    Parameters
    ----------
    spacing : float
        Distance between parallel lines inside a patch, in millimetres
        (greater than 0). Never below the pen width. Default 0.8.
    patch_size : float
        Size of the largest patches, in millimetres (greater than 0). Flat
        areas use patches this big. Default 10.0.
    min_patch_size : float
        Smallest patch size in millimetres (greater than 0, at most
        ``patch_size``). Busy areas are split down to this size. Default 4.0.
    detail : float
        Darkness standard deviation (0 - 1) above which a quadtree cell is
        split into four smaller patches. Lower values give more, smaller
        patches. Default 0.08.
    thresholds : tuple[float, ...] | None
        Minimum darkness ``1 - L/255`` for each layer, each in (0, 1) and
        strictly increasing, same length as ``layer_angles``. Default None:
        worked out from the pen width and spacing (see
        :func:`layer_thresholds`) so the ink coverage of ``n`` crossing
        layers matches the darkness that turns layer ``n`` on.
    layer_angles : tuple[float, ...]
        Angle of each layer relative to the patch's base direction, in
        degrees within [-360, 360]. Default ``(0, 60, 120, 90)``.
    follow_edges : bool
        When true, a patch's base direction runs along the local edges of the
        image (structure tensor); patches with no clear direction get a
        random angle. When false every patch gets a random angle. Default
        True.
    angle_jitter : float
        Seeded random change of each patch's base direction, in degrees
        (0 - 90). Default 12.0.
    overlap : float
        How much each patch grows past its cell so neighbours overlap, as a
        fraction of its size (0 - 1). Default 0.0: patches meet edge to edge
        and ``edge_jitter`` makes the seams rough.
    edge_jitter : float
        Largest random shift of each line end, in or out, in millimetres
        (>= 0), which gives patches rough, hand-drawn edges. Default 0.5.
    min_length : float
        Shortest line to keep, in millimetres (>= 0). Default 1.5.
    min_gap : float
        Gaps in a line shorter than this, in millimetres, are bridged
        (>= 0). Default 0.4.
    join_lines : bool
        Join consecutive lines of one layer inside a patch into one zig-zag
        stroke wherever the connector is at most twice the spacing. This cuts
        pen lifts about 4 times, but the connectors trace the patch borders,
        which shows as a net of outlines in light areas. Default False.
    join_in_dark : bool
        Join lines only where the connector is hidden: where the next,
        crossing layer is also drawn (for the last layer, where the last
        layer is drawn). Keeps light areas clean and still saves many pen
        lifts in dark areas. Ignored when ``join_lines`` is true. Default
        True.
    seed : int | None
        Random seed for patch layout and angles. None is non-deterministic.
        Default None.
    """

    spacing: float = Field(default=0.8, gt=0.0)
    patch_size: float = Field(default=10.0, gt=0.0)
    min_patch_size: float = Field(default=4.0, gt=0.0)
    detail: float = Field(default=0.08, ge=0.0, le=1.0)
    thresholds: tuple[float, ...] | None = None
    layer_angles: tuple[float, ...] = (0.0, 60.0, 120.0, 90.0)
    follow_edges: bool = True
    angle_jitter: float = Field(default=12.0, ge=0.0, le=90.0)
    overlap: float = Field(default=0.0, ge=0.0, le=1.0)
    edge_jitter: float = Field(default=0.5, ge=0.0)
    min_length: float = Field(default=1.5, ge=0.0)
    min_gap: float = Field(default=0.4, ge=0.0)
    join_lines: bool = False
    join_in_dark: bool = True
    seed: int | None = None

    @field_validator("layer_angles")
    @classmethod
    def validate_layer_angles(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        """Require every layer angle to lie in [-360, 360]."""
        for angle in value:
            if not -360.0 <= angle <= 360.0:
                raise ValueError(f"each layer angle must be in [-360, 360]; got {angle}")
        return value

    @field_validator("thresholds")
    @classmethod
    def validate_thresholds(cls, value: tuple[float, ...] | None) -> tuple[float, ...] | None:
        """Require every threshold to lie strictly between 0 and 1."""
        if value is None:
            return None
        if not value:
            raise ValueError("thresholds must hold at least one layer")
        for threshold in value:
            if not 0.0 < threshold < 1.0:
                raise ValueError(f"each threshold must be in (0, 1); got {threshold}")
        return value

    def model_post_init(self, __context: object) -> None:
        """Check paired layers and the patch size range."""
        if not self.layer_angles:
            raise ValueError("layer_angles must hold at least one layer")
        if self.thresholds is None:
            pass
        elif len(self.layer_angles) != len(self.thresholds):
            raise ValueError(
                "layer_angles and thresholds must have the same length "
                f"(got {len(self.layer_angles)} angles and {len(self.thresholds)} thresholds)"
            )
        elif any(later <= earlier for earlier, later in pairwise(self.thresholds)):
            raise ValueError(f"thresholds must be strictly increasing; got {self.thresholds}")
        if self.min_patch_size > self.patch_size:
            raise ValueError(
                f"min_patch_size ({self.min_patch_size}) must be <= patch_size ({self.patch_size})"
            )


def layer_thresholds(layers: int, spacing_mm: float, pen_width_mm: float) -> tuple[float, ...]:
    """Return the darkness at which each of ``layers`` hatch layers turns on.

    One layer of parallel lines ``spacing_mm`` apart drawn with a
    ``pen_width_mm`` pen covers ``f = min(1, pen_width / spacing)`` of the
    paper; ``n`` layers at different angles cover ``C(n) = 1 - (1 - f) ** n``.
    Layer ``n`` turns on halfway between ``C(n - 1)`` and ``C(n)``, so a tone
    gets the number of layers whose ink coverage is closest to its darkness.
    The result is clamped into (0, 1) and kept strictly increasing.

    Parameters
    ----------
    layers : int
        Number of layers (at least 1).
    spacing_mm : float
        Line spacing in millimetres (greater than 0).
    pen_width_mm : float
        Pen tip width in millimetres (greater than 0).

    Returns
    -------
    tuple[float, ...]
        One darkness threshold per layer, strictly increasing, in (0, 1).
    """
    if layers < 1:
        raise ValueError("layers must be at least 1")
    if spacing_mm <= 0.0 or pen_width_mm <= 0.0:
        raise ValueError("spacing_mm and pen_width_mm must be positive")
    fraction = min(1.0, pen_width_mm / spacing_mm)
    coverage = [1.0 - (1.0 - fraction) ** n for n in range(layers + 1)]
    values: list[float] = []
    for n in range(1, layers + 1):
        value = min(0.99, max(0.01, (coverage[n - 1] + coverage[n]) / 2.0))
        if values and value <= values[-1]:
            value = min(0.999, values[-1] + 0.001)
        values.append(value)
    return tuple(values)


def with_layer_angle_offset(settings: PatchHatchSettings, offset: float) -> PatchHatchSettings:
    """Return a copy with every layer angle rotated by ``offset`` degrees.

    Angles are wrapped into [-360, 360] so the copy stays valid. Used to give
    each palette pen its own hatch directions.
    """
    angles = tuple(math.remainder(angle + offset, 360.0) for angle in settings.layer_angles)
    return settings.model_copy(update={"layer_angles": angles})


@dataclass(frozen=True)
class _Cell:
    """A quadtree leaf in pixel coordinates."""

    x0: float
    y0: float
    size: float


def _darkness(image: Image.Image) -> NDArray[np.float64]:
    """Return darkness ``1 - L/255`` of the image as float64."""
    gray = image.convert("L") if image.mode != "L" else image
    return 1.0 - np.asarray(gray, dtype=np.float64) / 255.0


def _quadtree_cells(
    darkness: NDArray[np.float64],
    max_px: float,
    min_px: float,
    detail: float,
) -> list[_Cell]:
    """Split the image into square cells, smaller where the tone varies."""
    height, width = darkness.shape
    cells: list[_Cell] = []
    stack: list[_Cell] = []
    y = 0.0
    while y < height:
        x = 0.0
        while x < width:
            stack.append(_Cell(x, y, max_px))
            x += max_px
        y += max_px
    while stack:
        cell = stack.pop()
        x0, y0 = int(cell.x0), int(cell.y0)
        x1 = min(width, math.ceil(cell.x0 + cell.size))
        y1 = min(height, math.ceil(cell.y0 + cell.size))
        if x1 <= x0 or y1 <= y0:
            continue
        block = darkness[y0:y1, x0:x1]
        half = cell.size / 2.0
        if half >= min_px - _EPS and float(block.std()) > detail:
            for dy in (0.0, half):
                for dx in (0.0, half):
                    stack.append(_Cell(cell.x0 + dx, cell.y0 + dy, half))
        else:
            cells.append(cell)
    return cells


def _structure_tensor(
    darkness: NDArray[np.float64], sigma_px: float
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Return the smoothed structure tensor components Jxx, Jyy, Jxy."""

    def blur(values: NDArray[np.float64], sigma: float) -> NDArray[np.float64]:
        result = gaussian(values, sigma=sigma, preserve_range=True)  # type: ignore[no-untyped-call]
        return np.asarray(result, dtype=np.float64)

    smooth = blur(darkness, max(0.5, sigma_px / 4.0))
    gradients = np.gradient(smooth)
    grad_y = np.asarray(gradients[0], dtype=np.float64)
    grad_x = np.asarray(gradients[1], dtype=np.float64)
    return (
        blur(grad_x * grad_x, sigma_px),
        blur(grad_y * grad_y, sigma_px),
        blur(grad_x * grad_y, sigma_px),
    )


def _sample(
    darkness: NDArray[np.float64], xs: NDArray[np.float64], ys: NDArray[np.float64]
) -> NDArray[np.float64]:
    """Nearest-pixel darkness at the given points (clamped to the image)."""
    height, width = darkness.shape
    cols = np.clip(np.rint(xs).astype(np.int64), 0, width - 1)
    rows = np.clip(np.rint(ys).astype(np.int64), 0, height - 1)
    return darkness[rows, cols]


def _runs(
    mask: NDArray[np.bool_], step_px: float, min_gap_px: float, min_length_px: float
) -> list[tuple[int, int]]:
    """Return (start, end) sample index pairs of kept runs where ``mask`` is true."""
    if not mask.any():
        return []
    padded = np.concatenate(([False], mask, [False]))
    changes = np.flatnonzero(padded[1:] != padded[:-1])
    starts, ends = changes[0::2], changes[1::2] - 1
    runs: list[tuple[int, int]] = []
    for start, end in zip(starts.tolist(), ends.tolist(), strict=True):
        if runs and (start - runs[-1][1] - 1) * step_px < min_gap_px:
            runs[-1] = (runs[-1][0], end)
        else:
            runs.append((start, end))
    return [(s, e) for s, e in runs if e > s and (e - s) * step_px + _EPS >= min_length_px]


def _layer_pieces(
    darkness: NDArray[np.float64],
    patch: Polygon,
    centre: tuple[float, float],
    radius: float,
    theta: float,
    threshold: float,
    spacing_px: float,
    rng: random.Random,
    lengths_px: tuple[float, float, float],
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Return the line pieces of one layer inside one patch, in drawing order.

    Parallel chords at angle ``theta`` are clipped to the (convex) patch,
    sampled every half pixel, and kept where darkness reaches ``threshold``.
    Every other line is reversed so consecutive pieces can be joined.
    """
    min_gap_px, min_length_px, edge_jitter_px = lengths_px
    height, width = darkness.shape
    cx, cy = centre
    dx, dy = math.cos(theta), math.sin(theta)
    nx, ny = -dy, dx
    offsets = np.arange(-radius + rng.uniform(0.0, spacing_px), radius, spacing_px)
    if offsets.size == 0:
        return []
    ox = cx + nx * offsets
    oy = cy + ny * offsets
    chords = shapely.linestrings(
        np.stack(
            (
                np.column_stack((ox - dx * radius, oy - dy * radius)),
                np.column_stack((ox + dx * radius, oy + dy * radius)),
            ),
            axis=1,
        )
    )
    clipped = shapely.intersection(chords, patch)
    coords, owner = shapely.get_coordinates(clipped, return_index=True)
    if owner.size == 0:
        return []
    lines, first = np.unique(owner, return_index=True)
    last = np.append(first[1:], owner.size) - 1
    starts, ends = coords[first], coords[last]
    lengths = np.hypot(ends[:, 0] - starts[:, 0], ends[:, 1] - starts[:, 1])
    keep = lengths > _EPS
    lines, starts, ends, lengths = lines[keep], starts[keep], ends[keep], lengths[keep]
    if lines.size == 0:
        return []
    counts = np.maximum(2, np.ceil(lengths / 0.5).astype(np.int64) + 1)
    offsets_in = np.concatenate(([0], np.cumsum(counts)[:-1]))
    owner_of = np.repeat(np.arange(lines.size), counts)
    position = np.arange(int(counts.sum())) - offsets_in[owner_of]
    ts = position / (counts[owner_of] - 1)
    xs_all = starts[owner_of, 0] + (ends[owner_of, 0] - starts[owner_of, 0]) * ts
    ys_all = starts[owner_of, 1] + (ends[owner_of, 1] - starts[owner_of, 1]) * ts
    mask_all = _sample(darkness, xs_all, ys_all) >= threshold
    hits = np.add.reduceat(mask_all.astype(np.int64), offsets_in)

    pieces: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for k in np.flatnonzero(hits).tolist():
        line_index = int(lines[k])
        length = float(lengths[k])
        count = int(counts[k])
        (ax, ay), (bx, by) = starts[k].tolist(), ends[k].tolist()
        step = length / (count - 1)
        ux, uy = (bx - ax) / length, (by - ay) / length
        if hits[k] == count:
            runs = [(0, count - 1)] if length + _EPS >= min_length_px else []
        else:
            begin = int(offsets_in[k])
            runs = _runs(mask_all[begin : begin + count], step, min_gap_px, min_length_px)
        for start, end in runs:
            # Move each end by up to edge_jitter, in or out, for rough edges.
            shift_a = rng.uniform(-edge_jitter_px, edge_jitter_px)
            shift_b = rng.uniform(-edge_jitter_px, edge_jitter_px)
            if (end - start) * step + shift_a + shift_b < max(min_length_px, step):
                shift_a = shift_b = 0.0
            sx = min(width - 1.0, max(0.0, ax + ux * (start * step - shift_a)))
            sy = min(height - 1.0, max(0.0, ay + uy * (start * step - shift_a)))
            ex = min(width - 1.0, max(0.0, ax + ux * (end * step + shift_b)))
            ey = min(height - 1.0, max(0.0, ay + uy * (end * step + shift_b)))
            if line_index % 2 == 1:
                sx, sy, ex, ey = ex, ey, sx, sy
            pieces.append(((sx, sy), (ex, ey)))
    return pieces


def _join_pieces(
    pieces: list[tuple[tuple[float, float], tuple[float, float]]],
    darkness: NDArray[np.float64],
    hide_level: float | None,
    max_connector_px: float,
) -> list[LineString]:
    """Turn line pieces into strokes, joining close consecutive pieces.

    A connector is drawn when it is at most ``max_connector_px`` long and
    either ``hide_level`` is ``-inf`` (join everywhere) or the darkness at
    both ends and the middle of the connector reaches ``hide_level``, where
    crossing layers hide it. ``None`` never joins.
    """
    if hide_level is None:
        return [LineString([a, b]) for a, b in pieces if a != b]
    strokes: list[LineString] = []
    current: list[tuple[float, float]] = []
    for start_point, end_point in pieces:
        joinable = False
        if current and math.dist(current[-1], start_point) <= max_connector_px:
            if hide_level == -math.inf:
                joinable = True
            else:
                (ax, ay), (bx, by) = current[-1], start_point
                xs = np.array([ax, (ax + bx) / 2.0, bx])
                ys = np.array([ay, (ay + by) / 2.0, by])
                joinable = bool(_sample(darkness, xs, ys).min() >= hide_level)
        if joinable:
            current.extend((start_point, end_point))
        else:
            if len(current) >= 2:
                strokes.append(LineString(current))
            current = [start_point, end_point]
    if len(current) >= 2:
        strokes.append(LineString(current))
    return strokes


def patch_hatch_strokes(
    image: Image.Image,
    settings: PatchHatchSettings,
    pixels_per_mm: float,
    pen_width_mm: float,
) -> list[LineString]:
    """Generate hand-drawn style cross-hatching in small patches.

    The image is converted to darkness ``1 - L/255`` and cut into patches: a
    quadtree splits cells whose darkness varies more than ``detail`` down to
    ``min_patch_size``, the cell centres are jittered and turned into Voronoi
    cells, and each cell is grown by ``overlap``. A patch's base direction
    runs along the local edges (structure tensor) when ``follow_edges`` is on
    and the direction is clear, otherwise it is random; ``angle_jitter`` adds
    a seeded variation. For each layer ``i``, lines at base angle plus
    ``layer_angles[i]`` are laid ``spacing`` mm apart (at least the pen
    width) across the patch, and kept where the local darkness reaches
    ``thresholds[i]``, so darker tones get more crossing layers. Line ends
    move in or out at random by up to ``edge_jitter`` mm. Lines of one layer in one
    patch are joined into zig-zag strokes everywhere with ``join_lines``, or
    only where crossing layers hide the connectors with ``join_in_dark``.

    Parameters
    ----------
    image : PIL.Image.Image
        Input image (any mode, converted to greyscale).
    settings : PatchHatchSettings
        Algorithm configuration, in millimetres on paper.
    pixels_per_mm : float
        Working-image pixels per paper millimetre. Must be positive.
    pen_width_mm : float
        Pen tip width in millimetres. Must be positive; it is the lower bound
        for the line spacing.

    Returns
    -------
    list[LineString]
        Strokes in image pixel coordinates (origin top-left), inside the
        image, with no zero-length strokes.

    Raises
    ------
    ValueError
        If ``pixels_per_mm`` or ``pen_width_mm`` is not a positive number.
    """
    if not math.isfinite(pixels_per_mm) or pixels_per_mm <= 0.0:
        raise ValueError(
            "pixels_per_mm must be a positive number; pass the working image's "
            "pixels per paper millimetre (for example 10.0)"
        )
    if not math.isfinite(pen_width_mm) or pen_width_mm <= 0.0:
        raise ValueError(
            "pen_width_mm must be a positive number; pass the pen tip width in "
            "millimetres (for example 0.3)"
        )

    darkness = _darkness(image)
    height, width = darkness.shape
    spacing_mm = max(settings.spacing, pen_width_mm)
    thresholds = (
        settings.thresholds
        if settings.thresholds is not None
        else layer_thresholds(len(settings.layer_angles), spacing_mm, pen_width_mm)
    )
    if height < 2 or width < 2 or float(darkness.max()) < thresholds[0]:
        return []

    rng = random.Random(settings.seed)
    max_px = settings.patch_size * pixels_per_mm
    min_px = settings.min_patch_size * pixels_per_mm
    spacing_px = spacing_mm * pixels_per_mm
    min_gap_px = settings.min_gap * pixels_per_mm
    min_length_px = settings.min_length * pixels_per_mm
    edge_jitter_px = settings.edge_jitter * pixels_per_mm
    frame = box(0.0, 0.0, float(width - 1), float(height - 1))

    cells = _quadtree_cells(darkness, max_px, min_px, settings.detail)
    centres = [
        (
            min(width - 1.0, max(0.0, c.x0 + c.size / 2.0 + rng.uniform(-0.3, 0.3) * c.size)),
            min(height - 1.0, max(0.0, c.y0 + c.size / 2.0 + rng.uniform(-0.3, 0.3) * c.size)),
        )
        for c in cells
    ]
    if len(centres) >= 2:
        regions = voronoi_polygons(MultiPoint(centres), extend_to=frame)
        polygons = [geom for geom in regions.geoms if isinstance(geom, Polygon)]
    else:
        polygons = [frame]

    sigma_px = max(1.0, settings.min_patch_size * pixels_per_mm / 2.0)
    jxx, jyy, jxy = _structure_tensor(darkness, sigma_px)
    hide_levels: list[float | None]
    if settings.join_lines:
        hide_levels = [-math.inf] * len(thresholds)
    elif settings.join_in_dark:
        hide_levels = [*thresholds[1:], thresholds[-1]]
    else:
        hide_levels = [None] * len(thresholds)
    strokes: list[LineString] = []

    for polygon in polygons:
        cell = polygon.intersection(frame)
        if cell.is_empty or cell.area <= 0.0:
            continue
        centre = cell.centroid
        cx, cy = float(centre.x), float(centre.y)
        grown = scale_geometry(
            cell, 1.0 + settings.overlap, 1.0 + settings.overlap, origin=(cx, cy)
        )
        patch = grown.intersection(frame)
        if not isinstance(patch, Polygon) or patch.is_empty:
            continue

        minx, miny, maxx, maxy = patch.bounds
        x0, y0 = max(0, int(minx)), max(0, int(miny))
        x1, y1 = min(width, int(maxx) + 1), min(height, int(maxy) + 1)
        if float(darkness[y0:y1, x0:x1].max()) < thresholds[0]:
            continue

        row = min(height - 1, max(0, round(cy)))
        col = min(width - 1, max(0, round(cx)))
        txx, tyy, txy = float(jxx[row, col]), float(jyy[row, col]), float(jxy[row, col])
        trace = txx + tyy
        coherence = math.sqrt((txx - tyy) ** 2 + 4.0 * txy * txy) / trace if trace > _EPS else 0.0
        if settings.follow_edges and coherence >= _COHERENCE_MIN:
            gradient_angle = 0.5 * math.degrees(math.atan2(2.0 * txy, txx - tyy))
            base = gradient_angle + 90.0
        else:
            base = rng.uniform(0.0, 180.0)
        base += rng.uniform(-settings.angle_jitter, settings.angle_jitter)
        radius = max(math.hypot(px - cx, py - cy) for px, py in patch.exterior.coords) + 1.0

        for layer, (offset_angle, threshold) in enumerate(
            zip(settings.layer_angles, thresholds, strict=True)
        ):
            pieces = _layer_pieces(
                darkness,
                patch,
                (cx, cy),
                radius,
                math.radians(base + offset_angle),
                threshold,
                spacing_px,
                rng,
                (min_gap_px, min_length_px, edge_jitter_px),
            )
            strokes.extend(_join_pieces(pieces, darkness, hide_levels[layer], 2.0 * spacing_px))

    return [stroke for stroke in strokes if stroke.length > 0.0]


__all__ = [
    "PatchHatchSettings",
    "layer_thresholds",
    "patch_hatch_strokes",
    "with_layer_angle_offset",
]
