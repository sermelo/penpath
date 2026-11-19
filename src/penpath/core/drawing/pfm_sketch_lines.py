"""Sketch Lines PFM (Pen Follower Module) implementation.

Port of PFMSketchLinesBasic.java from DrawingBotV3.
Generates sketch-like line drawings from images using darkest-pixel sampling
and random-angle line search.
"""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, Field, field_validator, model_validator
from shapely import LineString

if TYPE_CHECKING:
    from PIL import Image


class SketchLinesSettings(BaseModel):
    """Settings for the Sketch Lines PFM algorithm.

    Parameters
    ----------
    line_density : float
        Overall line density multiplier (0.01 - 10.0). Higher = more lines.
    min_length : float
        Minimum line length in pixels (1 - 1000).
    max_length : float
        Maximum line length in pixels (1 - 5000).
    angle_range : tuple[float, float]
        Min/max start angle in degrees (0 - 360). Search range for line directions.
    shading_enabled : bool
        Whether to vary line density based on local pixel darkness.
    squiggle_enabled : bool
        Whether to add perpendicular noise (squiggles) to lines.
    erase_enabled : bool
        Whether to randomly drop/erase line segments.
    seed : int | None
        Random seed for deterministic output. None = non-deterministic.
    search_angle_step : float
        Angle step in degrees when searching for darkest line (0.1 - 90).
    sample_step : float
        Pixel step when sampling for darkest pixel (1 - 100).
    """

    line_density: float = Field(default=1.0, ge=0.01, le=10.0)
    min_length: float = Field(default=10.0, ge=1.0, le=1000.0)
    max_length: float = Field(default=100.0, ge=1.0, le=5000.0)
    angle_range: tuple[float, float] = Field(default=(0.0, 360.0))
    shading_enabled: bool = True
    squiggle_enabled: bool = True
    erase_enabled: bool = True
    seed: int | None = None
    search_angle_step: float = Field(default=5.0, ge=0.1, le=90.0)
    sample_step: float = Field(default=10.0, ge=1.0, le=100.0)

    @field_validator("angle_range")
    @classmethod
    def validate_angle_range(cls, v: tuple[float, float]) -> tuple[float, float]:
        if len(v) != 2:
            raise ValueError("angle_range must be a tuple of 2 floats")
        min_angle, max_angle = v
        if not (0.0 <= min_angle <= 360.0 and 0.0 <= max_angle <= 360.0):
            raise ValueError("angle_range values must be in [0, 360]")
        if min_angle > max_angle:
            raise ValueError("angle_range min must be <= max")
        return v

    @field_validator("min_length")
    @classmethod
    def validate_min_length(cls, v: float, info: Any) -> float:
        return v

    @model_validator(mode="after")
    def validate_min_max_length(self) -> SketchLinesSettings:
        if self.min_length > self.max_length:
            raise ValueError("min_length must be <= max_length")
        return self


def _bresenham_line(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
    """Bresenham's line algorithm - returns list of (x, y) points on the line."""
    points = []
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy

    x, y = x0, y0
    while True:
        points.append((x, y))
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x += sx
        if e2 < dx:
            err += dx
            y += sy
    return points


def _sample_line_luminance(
    luminance: NDArray[np.float32],
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    min_length: int,
) -> tuple[float, int, int]:
    """Sample luminance along a line using Bresenham. Returns (avg_luminance, end_x, end_y)."""
    h, w = luminance.shape
    points = _bresenham_line(x0, y0, x1, y1)

    if len(points) < min_length:
        return 255.0, x0, y0

    # Sample luminance values along the line
    lum_sum = 0.0
    count = 0
    last_valid_x, last_valid_y = x0, y0

    for x, y in points:
        if 0 <= x < w and 0 <= y < h:
            lum_sum += luminance[y, x]
            count += 1
            last_valid_x, last_valid_y = x, y
        else:
            break

    if count < min_length:
        return 255.0, x0, y0

    return lum_sum / count, last_valid_x, last_valid_y


def _find_darkest_pixel(
    luminance: NDArray[np.float32],
    sample_step: int,
    rng: random.Random,
) -> tuple[int, int]:
    """Find the darkest pixel using grid sampling with configurable step."""
    h, w = luminance.shape
    darkest_lum = 255.0
    darkest_x, darkest_y = 0, 0

    # Grid sampling
    for y in range(0, h, sample_step):
        for x in range(0, w, sample_step):
            # Sample a small region around this grid point
            region_lum = 0.0
            region_count = 0
            local_darkest = 255
            local_x, local_y = x, y

            for dy in range(min(sample_step, h - y)):
                for dx in range(min(sample_step, w - x)):
                    px, py = x + dx, y + dy
                    if 0 <= px < w and 0 <= py < h:
                        lum = luminance[py, px]
                        region_lum += lum
                        region_count += 1
                        if lum < local_darkest:
                            local_darkest = lum
                            local_x, local_y = px, py

            if region_count > 0:
                avg_lum = region_lum / region_count
                if avg_lum < darkest_lum:
                    darkest_lum = avg_lum
                    darkest_x, darkest_y = local_x, local_y

    # If all pixels are same brightness, pick random
    if darkest_lum >= 254.0:
        darkest_x = rng.randint(0, w - 1)
        darkest_y = rng.randint(0, h - 1)

    return darkest_x, darkest_y


def _find_darkest_line(
    luminance: NDArray[np.float32],
    x0: int,
    y0: int,
    min_length: int,
    max_length: int,
    start_angle: float,
    angle_step: float,
    num_tests: int,
    shading: bool,
    rng: random.Random,
) -> tuple[float, int, int]:
    """Search for the darkest line from (x0, y0) within angle range.

    Returns (avg_luminance, end_x, end_y).
    """
    h, w = luminance.shape
    best_lum = 255.0
    best_x, best_y = x0, y0

    if shading:
        # For shading, test only 2 directions (start_angle and start_angle + 180)
        num_tests = 2

    for i in range(num_tests):
        angle_deg = start_angle + 180.0 * i if shading else start_angle + angle_step * i

        angle_rad = math.radians(angle_deg)
        x1 = round(x0 + math.cos(angle_rad) * max_length)
        y1 = round(y0 + math.sin(angle_rad) * max_length)

        # Clamp to image bounds
        x1 = max(0, min(w - 1, x1))
        y1 = max(0, min(h - 1, y1))

        avg_lum, end_x, end_y = _sample_line_luminance(luminance, x0, y0, x1, y1, min_length)

        if avg_lum < best_lum:
            best_lum = avg_lum
            best_x, best_y = end_x, end_y

    return best_lum, best_x, best_y


def _add_squiggle(
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    squiggle_length: int,
    max_deviation: float,
    rng: random.Random,
) -> list[tuple[float, float]]:
    """Add perpendicular noise (squiggle) to a line segment.

    Returns list of (x, y) points forming a squiggly line.
    """
    dx = x1 - x0
    dy = y1 - y0
    length = math.hypot(dx, dy)

    if length < squiggle_length or max_deviation <= 0:
        return [(float(x0), float(y0)), (float(x1), float(y1))]

    # Perpendicular unit vector
    perp_x = -dy / length
    perp_y = dx / length

    num_segments = max(2, int(length / squiggle_length))
    points = [(float(x0), float(y0))]

    for i in range(1, num_segments):
        t = i / num_segments
        base_x = x0 + dx * t
        base_y = y0 + dy * t

        # Add perpendicular noise
        noise = rng.uniform(-max_deviation, max_deviation)
        squiggle_x = base_x + perp_x * noise
        squiggle_y = base_y + perp_y * noise

        points.append((squiggle_x, squiggle_y))

    points.append((float(x1), float(y1)))
    return points


def _should_erase(
    luminance: NDArray[np.float32],
    x: int,
    y: int,
    erase_min: float,
    erase_max: float,
    tone: float,
    rng: random.Random,
) -> bool:
    """Determine if a line segment should be erased based on local luminance."""
    h, w = luminance.shape
    if not (0 <= x < w and 0 <= y < h):
        return True

    lum = float(luminance[y, x]) / 255.0
    # Easing function similar to Java's easeInCubic
    x_progress = lum
    y_progress = (x_progress**3 * tone) + (x_progress * (1 - tone))

    erase_threshold = erase_min + y_progress * (erase_max - erase_min)
    return bool(rng.random() * 255 < erase_threshold)


def sketch_lines(
    image: Image.Image,
    settings: SketchLinesSettings,
) -> list[LineString]:
    """Generate sketch lines from an image using the Sketch Lines PFM algorithm.

    Parameters
    ----------
    image : PIL.Image
        Input image (any mode, will be converted to grayscale).
    settings : SketchLinesSettings
        Algorithm configuration parameters.

    Returns
    -------
    list[LineString]
        List of line geometries in image coordinates (pixels, origin top-left).
    """
    # Setup RNG
    rng = random.Random(settings.seed)

    # Convert to grayscale luminance (0=black, 255=white)
    gray = image.convert("L") if image.mode != "L" else image
    luminance = np.array(gray, dtype=np.float32)

    h, w = luminance.shape

    # Settings with validation
    min_len = int(max(1, settings.min_length))
    max_len = int(max(min_len, settings.max_length))
    line_density = max(0.01, settings.line_density)
    angle_min, angle_max = settings.angle_range
    search_step = max(0.1, settings.search_angle_step)
    sample_step = max(1, int(settings.sample_step))

    # Erase parameters (from Java defaults)
    erase_min = 1.0
    erase_max = 255.0
    tone = 0.5

    # Squiggle parameters
    squiggle_min_len = max(1, min_len // 2)
    squiggle_max_len = max(squiggle_min_len, max_len // 2)
    squiggle_max_dev = 2.0

    # Progress tracking
    initial_avg_lum = float(np.mean(luminance))
    desired_lum = 253.5
    max_lines = int(w * h * line_density * 0.001)  # Scale by image size and density
    max_lines = max(100, min(max_lines, 100000))

    lines: list[LineString] = []
    fails = 0
    max_fails = 1000

    # Track last position for linking lines
    last_x, last_y = -1, -1
    squiggle_count = 0

    while len(lines) < max_lines and fails < max_fails:
        # Find darkest pixel
        darkest_x, darkest_y = _find_darkest_pixel(luminance, sample_step, rng)

        # Link to previous position if not lifting pen
        if (
            squiggle_count > 0
            and last_x >= 0
            and last_y >= 0
            and (darkest_x != last_x or darkest_y != last_y)
        ):
            # Add linking line
            link_points = [(float(last_x), float(last_y)), (float(darkest_x), float(darkest_y))]
            if settings.squiggle_enabled:
                link_points = _add_squiggle(
                    last_x, last_y, darkest_x, darkest_y, squiggle_min_len, squiggle_max_dev, rng
                )
            if len(link_points) >= 2:
                line = LineString(link_points)
                if line.is_valid and line.length > 0:
                    lines.append(line)

        # Begin squiggle
        start_angle = rng.uniform(angle_min, angle_max)
        in_bounds = 0 <= darkest_y < h and 0 <= darkest_x < w
        initial_darkness = luminance[darkest_y, darkest_x] if in_bounds else 128
        allowable_darkness = (
            desired_lum
            if not settings.erase_enabled
            else initial_darkness + max(1, desired_lum * squiggle_max_dev / 100)
        )

        current_x, current_y = darkest_x, darkest_y
        squiggle_points: list[tuple[float, float]] = [(float(current_x), float(current_y))]
        squiggle_failed = False

        for s in range(squiggle_max_len):
            # Search for next line segment
            line_len = rng.randint(min_len, max_len)

            # Determine shading
            current_avg_lum = float(np.mean(luminance)) if lines else initial_avg_lum
            if current_avg_lum >= desired_lum:
                lum_progress = 0.0
            elif desired_lum > initial_avg_lum:
                lum_progress = (current_avg_lum - initial_avg_lum) / (
                    (desired_lum - initial_avg_lum) * line_density
                )
            else:
                lum_progress = 1.0

            shading = lum_progress > 0.5 if settings.shading_enabled else False

            avg_lum, next_x, next_y = _find_darkest_line(
                luminance,
                current_x,
                current_y,
                min_len,
                line_len,
                start_angle,
                search_step,
                max(1, int(360 / search_step)),
                shading,
                rng,
            )

            if avg_lum >= 255.0 or (next_x == current_x and next_y == current_y):
                squiggle_failed = True
                break

            # Check darkness constraints
            if (
                settings.erase_enabled
                and s >= squiggle_min_len
                and (avg_lum > allowable_darkness or avg_lum > current_avg_lum)
            ):
                break

            if not settings.erase_enabled and avg_lum > allowable_darkness:
                squiggle_failed = True
                break

            # Add segment to squiggle
            if settings.squiggle_enabled and s > 0:
                segment_points = _add_squiggle(
                    current_x, current_y, next_x, next_y, squiggle_min_len, squiggle_max_dev, rng
                )
                squiggle_points.extend(segment_points[1:])  # Skip duplicate start point
            else:
                squiggle_points.append((float(next_x), float(next_y)))

            # Erase on pixel data (simulate drawing)
            if settings.erase_enabled:
                # Sample points along the line for erase check
                segment_lum_points = _bresenham_line(current_x, current_y, next_x, next_y)
                for px, py in segment_lum_points:
                    if (
                        _should_erase(luminance, px, py, erase_min, erase_max, tone, rng)
                        and 0 <= px < w
                        and 0 <= py < h
                    ):
                        # Lighten the pixel (simulate erasing)
                        luminance[py, px] = min(255, luminance[py, px] + int(erase_max * 0.1))

            current_x, current_y = next_x, next_y

            # Update progress
            if len(lines) >= max_lines:
                break

        # End squiggle - create LineString from accumulated points
        if len(squiggle_points) >= 2 and not squiggle_failed:
            line = LineString(squiggle_points)
            if line.is_valid and line.length > 0:
                lines.append(line)
                last_x, last_y = current_x, current_y
                squiggle_count += 1
                fails = 0
            else:
                fails += 1
        else:
            # Erase the starting pixel if squiggle failed
            if 0 <= darkest_x < w and 0 <= darkest_y < h:
                luminance[darkest_y, darkest_x] = 255.0
            fails += 1

    return lines


__all__ = ["SketchLinesSettings", "sketch_lines"]
