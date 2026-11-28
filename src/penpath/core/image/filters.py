"""Image filters for penpath."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

_WIDE_RANGE_MIN_SPAN = 224


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


def auto_equalize(image: Image.Image, clip_percent: float = 0.0) -> Image.Image:
    """Stretch the image's luminance range to 0-255 (robust linear auto levels).

    The range is measured with the same BT.601 luminance as :func:`grayscale`,
    as the ``clip_percent`` and ``100 - clip_percent`` percentiles. With the
    default 0 these are the single darkest and lightest pixel (the original
    behaviour); with ``clip_percent=0.5`` a few
    extreme pixels (a dark speck, a specular highlight, which nearly every
    JPEG photo has) no longer hide a flat photo's narrow range. One lookup table maps
    ``[lo, hi]`` to ``[0, 255]`` (clipping the few pixels outside) and is
    applied to every colour channel; an alpha channel is copied through
    unchanged. A copy is returned unchanged when the measured range is
    narrower than 16 levels (blank or near-uniform input) or already spans at
    least 7/8 of 0-255 (224 levels), where the largest possible stretch is
    255/224 and a calibrated plot is left undisturbed.

    Parameters
    ----------
    image : PIL.Image.Image
        Input image in ``L``, ``LA``, ``RGB`` or ``RGBA`` mode.
    clip_percent : float, optional
        Percent of pixels ignored at each end when measuring the range
        (0 - 10). Default 0.

    Returns
    -------
    PIL.Image.Image
        A new image in the same mode, with its tonal range normalized.

    Raises
    ------
    TypeError
        If the mode is not ``L``, ``LA``, ``RGB`` or ``RGBA``.
    """
    if not 0.0 <= clip_percent <= 10.0:
        raise ValueError(f"clip_percent must be in 0 - 10, got {clip_percent}")
    if image.mode not in ("L", "LA", "RGB", "RGBA"):
        raise TypeError(
            "auto_equalize supports L, LA, RGB and RGBA images, got "
            f"'{image.mode}'; convert the image to a supported mode first"
        )

    arr = np.asarray(image)
    if image.mode in ("L", "LA"):
        luminance = (arr if image.mode == "L" else arr[:, :, 0]).astype(np.float32)
    else:
        rgb = arr[:, :, :3].astype(np.float32)
        luminance = 0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]
    low_value, high_value = np.percentile(
        luminance, [clip_percent, 100.0 - clip_percent], method="nearest"
    )
    lo = int(np.floor(low_value))
    hi = int(np.ceil(high_value))

    if hi - lo < 16 or hi - lo >= _WIDE_RANGE_MIN_SPAN:
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


def _on_luminance(
    image: Image.Image, transform: Callable[[Image.Image], Image.Image]
) -> Image.Image:
    """Apply a greyscale ``transform`` to the image's luminance, keeping colour."""
    if image.mode == "L":
        return transform(image)
    if image.mode == "LA":
        lightness, la_alpha = image.split()
        return Image.merge("LA", (transform(lightness), la_alpha))
    rgba_alpha = image.getchannel("A") if image.mode == "RGBA" else None
    y, cb, cr = image.convert("RGB").convert("YCbCr").split()
    result = Image.merge("YCbCr", (transform(y), cb, cr)).convert("RGB")
    if rgba_alpha is not None:
        result.putalpha(rgba_alpha)
    return result


def equalize(image: Image.Image) -> Image.Image:
    """Global histogram equalisation of the luminance.

    Spreads the image's grey levels so every level is about equally used,
    which brings out mid-tone detail in flat or low-contrast photos. Colour
    images are equalised on their luminance (YCbCr), so hues do not shift.

    Parameters
    ----------
    image : PIL.Image.Image
        Input image in ``L``, ``LA``, ``RGB`` or ``RGBA`` mode.

    Returns
    -------
    PIL.Image.Image
        The equalised image, same mode.
    """
    from PIL import ImageOps

    return _on_luminance(image, ImageOps.equalize)


def clahe(image: Image.Image, clip_limit: float = 0.01, tiles: int = 8) -> Image.Image:
    """Local contrast equalisation (CLAHE) of the luminance.

    Contrast Limited Adaptive Histogram Equalization evens out contrast
    region by region, so detail in both shadows and highlights shows, while
    ``clip_limit`` stops it from amplifying noise in flat areas.

    Parameters
    ----------
    image : PIL.Image.Image
        Input image in ``L``, ``LA``, ``RGB`` or ``RGBA`` mode.
    clip_limit : float
        Contrast limit, 0 - 1 (default 0.01). Higher means stronger local
        contrast and more noise.
    tiles : int
        Number of regions across the longest side (2 - 64, default 8).

    Returns
    -------
    PIL.Image.Image
        The equalised image, same mode.

    Raises
    ------
    ValueError
        If ``clip_limit`` or ``tiles`` is out of range.
    """
    if not 0.0 < clip_limit <= 1.0:
        raise ValueError(f"clip_limit must be in (0, 1], got {clip_limit}")
    if not 2 <= int(tiles) <= 64:
        raise ValueError(f"tiles must be in 2 - 64, got {tiles}")
    from skimage.exposure import equalize_adapthist

    def transform(gray: Image.Image) -> Image.Image:
        values = np.asarray(gray, dtype=np.float64) / 255.0
        kernel = max(8, round(max(values.shape) / int(tiles)))
        out = equalize_adapthist(values, kernel_size=kernel, clip_limit=clip_limit)
        return Image.fromarray(np.clip(np.rint(np.asarray(out) * 255.0), 0, 255).astype(np.uint8))

    return _on_luminance(image, transform)


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
