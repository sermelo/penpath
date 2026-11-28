"""Image loading with EXIF auto-orientation support."""

from pathlib import Path
from typing import Final

from PIL import Image, UnidentifiedImageError

SUPPORTED_FORMATS: Final[set[str]] = {"PNG", "JPEG", "TIFF", "BMP"}

EXIF_ORIENTATION_TAG: Final[int] = 274

ORIENTATION_TRANSFORMS: Final[dict[int, list[Image.Transpose]]] = {
    1: [],
    2: [Image.Transpose.FLIP_LEFT_RIGHT],
    3: [Image.Transpose.ROTATE_180],
    4: [Image.Transpose.FLIP_TOP_BOTTOM],
    5: [Image.Transpose.FLIP_LEFT_RIGHT, Image.Transpose.ROTATE_90],
    6: [Image.Transpose.ROTATE_270],
    7: [Image.Transpose.FLIP_LEFT_RIGHT, Image.Transpose.ROTATE_270],
    8: [Image.Transpose.ROTATE_90],
}


class ImageLoadError(Exception):
    """Raised when an image cannot be loaded."""

    pass


class UnsupportedFormatError(ImageLoadError):
    """Raised when the image format is not supported."""

    pass


def load_image(path: str | Path, *, auto_orient: bool = True) -> Image.Image:
    """Load an image, applying EXIF auto-orientation unless disabled.

    Supports PNG, JPEG, TIFF, and BMP formats. Applies EXIF orientation
    correction for all 8 orientation values by default; ``auto_orient=False``
    keeps the stored pixel orientation and size.

    Parameters
    ----------
    path : str | Path
        Path to the image file.
    auto_orient : bool
        Apply the EXIF orientation tag when true (default). When false, load
        the pixels exactly as stored.

    Returns
    -------
    PIL.Image.Image
        The loaded image, converted to RGB mode.

    Raises
    ------
    ImageLoadError
        If the file does not exist or cannot be read.
    UnsupportedFormatError
        If the image format is not supported.
    """
    path = Path(path)

    if not path.exists():
        raise ImageLoadError(f"Image file not found: {path}")

    if not path.is_file():
        raise ImageLoadError(f"Path is not a file: {path}")

    try:
        with Image.open(path) as img:
            img.load()
            format_name = img.format
            if format_name not in SUPPORTED_FORMATS:
                raise UnsupportedFormatError(
                    f"Unsupported image format: {format_name}. "
                    f"Supported formats: {', '.join(sorted(SUPPORTED_FORMATS))}"
                )

            image: Image.Image = img
            if auto_orient:
                image = _apply_exif_orientation(image)

            if image.mode not in ("RGB", "RGBA", "L", "LA"):
                image = image.convert("RGB")
            elif image.mode in ("RGBA", "LA"):
                pass
            else:
                image = image.convert("RGB")

            return image.copy()

    except UnidentifiedImageError as e:
        raise ImageLoadError(f"Cannot identify image file: {path}") from e
    except UnsupportedFormatError:
        raise
    except Exception as e:
        raise ImageLoadError(f"Failed to load image: {path}") from e


def _apply_exif_orientation(img: Image.Image) -> Image.Image:
    """Apply EXIF orientation correction to an image.

    Parameters
    ----------
    img : PIL.Image.Image
        The image to correct.

    Returns
    -------
    PIL.Image.Image
        The orientation-corrected image.
    """
    try:
        exif = img.getexif()
    except Exception:
        return img

    if exif is None:
        return img

    orientation = exif.get(EXIF_ORIENTATION_TAG)
    if orientation is None or orientation not in ORIENTATION_TRANSFORMS:
        return img

    transforms = ORIENTATION_TRANSFORMS[orientation]
    for transform in transforms:
        img = img.transpose(transform)

    return img
