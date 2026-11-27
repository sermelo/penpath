"""Likeness scoring for penpath.

Compares a simulated plot with the original image using SSIM after
greyscale conversion, downscaling, and Gaussian blur.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray
from PIL import Image
from skimage.filters import gaussian, sobel
from skimage.metrics import structural_similarity

if TYPE_CHECKING:
    pass


def prepare_for_comparison(
    image: Image.Image,
    target_size: tuple[int, int],
    blur_sigma: float,
) -> NDArray[np.float32]:
    """Prepare an image for likeness comparison.

    Converts to greyscale, resizes to target_size, and applies Gaussian blur.

    Parameters
    ----------
    image : PIL.Image.Image
        Input image (any mode).
    target_size : tuple[int, int]
        Target size as (width, height) in pixels.
    blur_sigma : float
        Standard deviation for Gaussian kernel. Must be >= 0.

    Returns
    -------
    np.ndarray
        Prepared image as float array in range [0, 1], shape (H, W).
    """
    if image.mode != "L":
        image = image.convert("L")

    image = image.resize(target_size, Image.Resampling.LANCZOS)

    arr = np.asarray(image, dtype=np.float32) / 255.0

    if blur_sigma > 0:
        arr = gaussian(arr, sigma=blur_sigma, mode="reflect", preserve_range=True)  # type: ignore[no-untyped-call]

    return arr


def _crop_and_prepare(
    simulated: Image.Image,
    original: Image.Image,
    placement_rect: tuple[float, float, float, float],
    target_size: tuple[int, int],
    blur_sigma: float,
    dpi_px_per_mm: float,
) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
    x_mm, y_mm, w_mm, h_mm = placement_rect

    mm_to_px = dpi_px_per_mm

    x_px = round(x_mm * mm_to_px)
    y_px = round(y_mm * mm_to_px)
    w_px = round(w_mm * mm_to_px)
    h_px = round(h_mm * mm_to_px)

    sim_w, sim_h = simulated.size
    x_px = max(0, min(x_px, sim_w - 1))
    y_px = max(0, min(y_px, sim_h - 1))
    w_px = max(1, min(w_px, sim_w - x_px))
    h_px = max(1, min(h_px, sim_h - y_px))

    simulated_cropped = simulated.crop((x_px, y_px, x_px + w_px, y_px + h_px))

    sim_prepared = prepare_for_comparison(simulated_cropped, target_size, blur_sigma)
    orig_prepared = prepare_for_comparison(original, target_size, blur_sigma)

    return sim_prepared, orig_prepared


def compute_likeness(
    simulated: Image.Image,
    original: Image.Image,
    placement_rect: tuple[float, float, float, float],
    target_size: tuple[int, int] = (256, 256),
    blur_sigma: float = 1.5,
    dpi_px_per_mm: float = 96 / 25.4,
) -> float:
    """Compute likeness score between simulated plot and original image.

    Crops the simulated image to the placement rectangle (specified in mm),
    then prepares both images for comparison and computes SSIM.

    Parameters
    ----------
    simulated : PIL.Image.Image
        Simulated plot image (rendered at dpi_px_per_mm pixels per millimetre).
    original : PIL.Image.Image
        Original reference image.
    placement_rect : tuple[float, float, float, float]
        Placement rectangle as (x_mm, y_mm, width_mm, height_mm) in millimetres.
    target_size : tuple[int, int], optional
        Target size for comparison as (width, height) in pixels. Default (256, 256).
    blur_sigma : float, optional
        Gaussian blur sigma for comparison. Default 1.5.
    dpi_px_per_mm : float, optional
        Pixels per millimetre of the simulated image, matching the scale used by
        penpath.core.simulation.simulate_plot. Default is 96/25.4 ≈ 3.7795 px/mm.

    Returns
    -------
    float
        SSIM score in range [0, 1], where 1 is identical.
    """
    sim_prepared, orig_prepared = _crop_and_prepare(
        simulated, original, placement_rect, target_size, blur_sigma, dpi_px_per_mm
    )

    score = structural_similarity(  # type: ignore[no-untyped-call]
        sim_prepared,
        orig_prepared,
        data_range=1.0,
        win_size=7,
    )

    return float(np.clip(score, 0.0, 1.0))


def compute_edge_likeness(
    simulated: Image.Image,
    original: Image.Image,
    placement_rect: tuple[float, float, float, float],
    target_size: tuple[int, int] = (256, 256),
    blur_sigma: float = 1.5,
    dpi_px_per_mm: float = 96 / 25.4,
) -> float:
    """Compare the structure of a simulated plot with the original image.

    Uses the same placement crop and greyscale preparation as ``compute_likeness``,
    then takes the Sobel gradient magnitude of both prepared images. Both edge
    maps are divided by one shared maximum before SSIM, so a near-blank page is
    not normalised into false edges; when both maps are entirely zero the images
    have the same (absent) structure and the score is 1.0.

    Parameters
    ----------
    simulated : PIL.Image.Image
        Simulated plot image (rendered at dpi_px_per_mm pixels per millimetre).
    original : PIL.Image.Image
        Original reference image.
    placement_rect : tuple[float, float, float, float]
        Placement rectangle as (x_mm, y_mm, width_mm, height_mm) in millimetres.
    target_size : tuple[int, int], optional
        Target size for comparison as (width, height) in pixels. Default (256, 256).
    blur_sigma : float, optional
        Gaussian blur sigma for comparison. Default 1.5.
    dpi_px_per_mm : float, optional
        Pixels per millimetre of the simulated image. Default is 96/25.4 ≈ 3.7795 px/mm.

    Returns
    -------
    float
        Edge SSIM score in range [0, 1], where 1 means matching structure.
    """
    sim_prepared, orig_prepared = _crop_and_prepare(
        simulated, original, placement_rect, target_size, blur_sigma, dpi_px_per_mm
    )

    sim_edges = sobel(sim_prepared)  # type: ignore[no-untyped-call]
    orig_edges = sobel(orig_prepared)  # type: ignore[no-untyped-call]

    shared_max = max(float(sim_edges.max()), float(orig_edges.max()))
    if shared_max <= 0.0:
        return 1.0

    score = structural_similarity(  # type: ignore[no-untyped-call]
        sim_edges / shared_max,
        orig_edges / shared_max,
        data_range=1.0,
        win_size=7,
    )

    return float(np.clip(score, 0.0, 1.0))


__all__ = ["compute_edge_likeness", "compute_likeness", "prepare_for_comparison"]
