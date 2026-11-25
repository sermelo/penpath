"""Image filters for penpath."""

from __future__ import annotations

from enum import StrEnum

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps


class GrayscaleMethod(StrEnum):
    """Method for converting to grayscale."""

    LUMINANCE = "luminance"
    LIGHTNESS = "lightness"
    AVERAGE = "average"
    RED = "red"
    GREEN = "green"
    BLUE = "blue"


class DitherMethod(StrEnum):
    """Dithering method for threshold/posterize."""

    NONE = "none"
    FLOYD_STEINBERG = "floyd_steinberg"
    ORDERED = "ordered"


def auto_equalize(image: Image.Image) -> Image.Image:
    """Stretch the image's luminance range to 0-255 (linear auto levels).

    The range is measured with the same BT.601 luminance as :func:`grayscale`.
    One lookup table maps ``[lo, hi]`` to ``[0, 255]`` and is applied to every
    colour channel; an alpha channel is copied through unchanged. An image
    that already spans 0-255, and a near-uniform image whose range is narrower
    than 16 levels, are returned as a byte-identical copy.

    Parameters
    ----------
    image : PIL.Image.Image
        Input image in ``L``, ``LA``, ``RGB`` or ``RGBA`` mode.

    Returns
    -------
    PIL.Image.Image
        A new image in the same mode, with its tonal range normalized.

    Raises
    ------
    TypeError
        If the mode is not ``L``, ``LA``, ``RGB`` or ``RGBA``.
    """
    if image.mode not in ("L", "LA", "RGB", "RGBA"):
        raise TypeError(
            "auto_equalize supports L, LA, RGB and RGBA images, got "
            f"'{image.mode}'; convert the image to a supported mode first"
        )

    arr = np.asarray(image)
    if image.mode in ("L", "LA"):
        luminance = arr if image.mode == "L" else arr[:, :, 0]
        lo = int(luminance.min())
        hi = int(luminance.max())
    else:
        rgb = arr[:, :, :3].astype(np.float32)
        luminance = 0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]
        lo = int(np.floor(luminance.min()))
        hi = int(np.ceil(luminance.max()))

    if (lo == 0 and hi == 255) or hi - lo < 16:
        return image.copy()

    scale = 255.0 / (hi - lo)
    table = [round((value - lo) * scale) for value in range(256)]
    table = [min(255, max(0, value)) for value in table]

    if image.mode == "L":
        return image.point(table)
    if image.mode == "LA":
        lightness, alpha = image.split()
        return Image.merge("LA", (lightness.point(table), alpha))
    if image.mode == "RGB":
        red, green, blue = image.split()
        return Image.merge("RGB", (red.point(table), green.point(table), blue.point(table)))
    red, green, blue, alpha = image.split()
    return Image.merge(
        "RGBA",
        (red.point(table), green.point(table), blue.point(table), alpha),
    )


def _grayscale_luminance(rgb: Image.Image) -> Image.Image:
    """Convert RGB to grayscale using ITU-R BT.601 luminance formula."""
    arr = np.array(rgb, dtype=np.float32)
    gray = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
    return Image.fromarray(gray.astype(np.uint8))


def _grayscale_lightness(rgb: Image.Image) -> Image.Image:
    """Convert RGB to grayscale using lightness (max+min)/2."""
    arr = np.array(rgb, dtype=np.float32)
    gray = (np.max(arr, axis=2) + np.min(arr, axis=2)) / 2
    return Image.fromarray(gray.astype(np.uint8))


def _grayscale_average(rgb: Image.Image) -> Image.Image:
    """Convert RGB to grayscale using simple average."""
    arr = np.array(rgb, dtype=np.float32)
    gray = np.mean(arr, axis=2)
    return Image.fromarray(gray.astype(np.uint8))


def grayscale(
    image: Image.Image,
    method: GrayscaleMethod | str = GrayscaleMethod.LUMINANCE,
) -> Image.Image:
    """Convert an image to grayscale using the specified method.

    Parameters
    ----------
    image : PIL.Image.Image
        Input image (any mode).
    method : GrayscaleMethod | str
        Conversion method: luminance, lightness, average, red, green, blue.

    Returns
    -------
    PIL.Image.Image
        Grayscale image in 'L' mode.
    """
    if isinstance(method, str):
        method = GrayscaleMethod(method)

    if image.mode == "L":
        return image.copy()

    rgb = image.convert("RGB")

    match method:
        case GrayscaleMethod.LUMINANCE:
            return _grayscale_luminance(rgb)
        case GrayscaleMethod.LIGHTNESS:
            return _grayscale_lightness(rgb)
        case GrayscaleMethod.AVERAGE:
            return _grayscale_average(rgb)
        case GrayscaleMethod.RED:
            return rgb.split()[0]
        case GrayscaleMethod.GREEN:
            return rgb.split()[1]
        case GrayscaleMethod.BLUE:
            return rgb.split()[2]

    return _grayscale_luminance(rgb)


def threshold(
    image: Image.Image,
    level: int = 128,
    dither: DitherMethod | str = DitherMethod.NONE,
) -> Image.Image:
    """Apply threshold (binarization) to an image.

    Parameters
    ----------
    image : PIL.Image.Image
        Input grayscale image ('L' mode).
    level : int
        Threshold level (0-255). Pixels >= level become 255, others become 0.
    dither : DitherMethod | str
        Dithering method: none, floyd_steinberg, ordered.

    Returns
    -------
    PIL.Image.Image
        Binary image in 'L' mode (values 0 or 255).
    """
    if isinstance(dither, str):
        dither = DitherMethod(dither)

    if image.mode != "L":
        image = grayscale(image)

    if not 0 <= level <= 255:
        raise ValueError(f"Threshold level must be 0-255, got {level}")

    match dither:
        case DitherMethod.NONE:
            return image.point(lambda x: 255 if x >= level else 0)
        case DitherMethod.FLOYD_STEINBERG:
            return _floyd_steinberg_dither(image, level)
        case DitherMethod.ORDERED:
            return _ordered_dither(image, level)

    return image.point(lambda x: 255 if x >= level else 0)


def _floyd_steinberg_dither(image: Image.Image, level: int) -> Image.Image:
    """Apply Floyd-Steinberg dithering with threshold."""
    arr = np.array(image, dtype=np.float32)
    h, w = arr.shape

    for y in range(h):
        for x in range(w):
            old = arr[y, x]
            new = 255.0 if old >= level else 0.0
            arr[y, x] = new
            error = old - new

            if x + 1 < w:
                arr[y, x + 1] += error * 7 / 16
            if y + 1 < h:
                if x > 0:
                    arr[y + 1, x - 1] += error * 3 / 16
                arr[y + 1, x] += error * 5 / 16
                if x + 1 < w:
                    arr[y + 1, x + 1] += error * 1 / 16

    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


_BAYER_8x8 = np.array(
    [
        [0, 48, 12, 60, 3, 51, 15, 63],
        [32, 16, 44, 28, 35, 19, 47, 31],
        [8, 56, 4, 52, 11, 59, 7, 55],
        [40, 24, 36, 20, 43, 27, 39, 23],
        [2, 50, 14, 62, 1, 49, 13, 61],
        [34, 18, 46, 30, 33, 17, 45, 29],
        [10, 58, 6, 54, 9, 57, 5, 53],
        [42, 26, 38, 22, 41, 25, 37, 21],
    ],
    dtype=np.uint8,
) * (255 // 64)


def _ordered_dither(image: Image.Image, level: int) -> Image.Image:
    """Apply ordered (Bayer) dithering with threshold."""
    arr = np.array(image, dtype=np.uint16)
    h, w = arr.shape

    threshold_map = np.tile(_BAYER_8x8, ((h + 7) // 8, (w + 7) // 8))[:h, :w]
    threshold_vals = level + (threshold_map.astype(np.int16) - 128)

    result = np.where(arr >= threshold_vals, 255, 0).astype(np.uint8)
    return Image.fromarray(result)


def posterize(
    image: Image.Image,
    levels: int = 4,
    dither: DitherMethod | str = DitherMethod.NONE,
) -> Image.Image:
    """Reduce an image to a specified number of tonal levels (posterization).

    Parameters
    ----------
    image : PIL.Image.Image
        Input grayscale image ('L' mode).
    levels : int
        Number of output levels (2-256).
    dither : DitherMethod | str
        Dithering method: none, floyd_steinberg, ordered.

    Returns
    -------
    PIL.Image.Image
        Posterized image in 'L' mode.
    """
    if isinstance(dither, str):
        dither = DitherMethod(dither)

    if image.mode != "L":
        image = grayscale(image)

    if not 2 <= levels <= 256:
        raise ValueError(f"Posterize levels must be 2-256, got {levels}")

    if levels == 256:
        return image.copy()

    if dither == DitherMethod.NONE:
        step_int = 256 // levels
        return image.point(lambda x: min((x // step_int) * step_int + step_int // 2, 255))

    arr = np.array(image, dtype=np.float32)
    h, w = arr.shape
    step = 256.0 / levels

    if dither == DitherMethod.FLOYD_STEINBERG:
        for y in range(h):
            for x in range(w):
                old = arr[y, x]
                quantized = round(old / step) * step
                quantized = min(max(quantized, 0), 255)
                arr[y, x] = quantized
                error = old - quantized

                if x + 1 < w:
                    arr[y, x + 1] += error * 7 / 16
                if y + 1 < h:
                    if x > 0:
                        arr[y + 1, x - 1] += error * 3 / 16
                    arr[y + 1, x] += error * 5 / 16
                    if x + 1 < w:
                        arr[y + 1, x + 1] += error * 1 / 16

        return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    if dither == DitherMethod.ORDERED:
        threshold_map = np.tile(_BAYER_8x8, ((h + 7) // 8, (w + 7) // 8))[:h, :w]
        dither_vals = (threshold_map.astype(np.float32) - 128) * (step / 256)
        quantized = np.round((arr + dither_vals) / step) * step
        quantized = np.clip(quantized, 0, 255).astype(np.uint8)
        return Image.fromarray(quantized)

    return image.point(lambda x: min((x // step) * step + step // 2, 255))


def gaussian_blur(image: Image.Image, radius: float = 2.0) -> Image.Image:
    """Apply Gaussian blur to an image.

    Parameters
    ----------
    image : PIL.Image.Image
        Input image.
    radius : float
        Blur radius (sigma), must be >= 0.

    Returns
    -------
    PIL.Image.Image
        Blurred image.
    """
    if radius < 0:
        raise ValueError(f"Blur radius must be >= 0, got {radius}")

    if radius == 0:
        return image.copy()

    return image.filter(ImageFilter.GaussianBlur(radius=radius))


def box_blur(image: Image.Image, radius: int = 2) -> Image.Image:
    """Apply box blur to an image.

    Parameters
    ----------
    image : PIL.Image.Image
        Input image.
    radius : int
        Blur radius in pixels, must be >= 0.

    Returns
    -------
    PIL.Image.Image
        Blurred image.
    """
    if radius < 0:
        raise ValueError(f"Blur radius must be >= 0, got {radius}")

    if radius == 0:
        return image.copy()

    return image.filter(ImageFilter.BoxBlur(radius=radius))


def contrast(image: Image.Image, factor: float = 1.0) -> Image.Image:
    """Adjust image contrast.

    Parameters
    ----------
    image : PIL.Image.Image
        Input image.
    factor : float
        Contrast factor. 1.0 = no change, <1.0 = lower contrast, >1.0 = higher contrast.
        Must be >= 0.

    Returns
    -------
    PIL.Image.Image
        Contrast-adjusted image.
    """
    if factor < 0:
        raise ValueError(f"Contrast factor must be >= 0, got {factor}")

    if abs(factor - 1.0) < 1e-9:
        return image.copy()

    enhancer = ImageEnhance.Contrast(image)
    return enhancer.enhance(factor)


def brightness(image: Image.Image, factor: float = 1.0) -> Image.Image:
    """Adjust image brightness.

    Parameters
    ----------
    image : PIL.Image.Image
        Input image.
    factor : float
        Brightness factor. 1.0 = no change, <1.0 = darker, >1.0 = brighter.
        Must be >= 0.

    Returns
    -------
    PIL.Image.Image
        Brightness-adjusted image.
    """
    if factor < 0:
        raise ValueError(f"Brightness factor must be >= 0, got {factor}")

    if abs(factor - 1.0) < 1e-9:
        return image.copy()

    enhancer = ImageEnhance.Brightness(image)
    return enhancer.enhance(factor)


def gamma(image: Image.Image, gamma: float = 1.0) -> Image.Image:
    """Apply gamma correction to an image.

    Parameters
    ----------
    image : PIL.Image.Image
        Input image.
    gamma : float
        Gamma value. 1.0 = no change, <1.0 = brighter midtones, >1.0 = darker midtones.
        Must be > 0.

    Returns
    -------
    PIL.Image.Image
        Gamma-corrected image.
    """
    if gamma <= 0:
        raise ValueError(f"Gamma must be > 0, got {gamma}")

    if abs(gamma - 1.0) < 1e-9:
        return image.copy()

    table = [int((i / 255.0) ** gamma * 255) for i in range(256)]

    if image.mode == "L":
        return image.point(table)
    elif image.mode in ("RGB", "RGBA"):
        return image.point(table * (3 if image.mode == "RGB" else 4))
    else:
        return image.convert("RGB").point(table * 3).convert(image.mode)


def invert(image: Image.Image) -> Image.Image:
    """Invert an image (negative).

    Parameters
    ----------
    image : PIL.Image.Image
        Input image.

    Returns
    -------
    PIL.Image.Image
        Inverted image.
    """
    if image.mode == "RGBA":
        r, g, b, a = image.split()
        r = ImageOps.invert(r)
        g = ImageOps.invert(g)
        b = ImageOps.invert(b)
        return Image.merge("RGBA", (r, g, b, a))
    elif image.mode == "LA":
        lightness, a = image.split()
        lightness = ImageOps.invert(lightness)
        return Image.merge("LA", (lightness, a))
    elif image.mode == "RGB" or image.mode == "L":
        return ImageOps.invert(image)
    else:
        rgb = image.convert("RGB")
        inverted = ImageOps.invert(rgb)
        return inverted.convert(image.mode)
