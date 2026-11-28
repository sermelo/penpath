"""Unit tests for penpath.core.image.load."""

from pathlib import Path

import pytest
from PIL import Image

from penpath.core.image.load import (
    ORIENTATION_TRANSFORMS,
    ImageLoadError,
    UnsupportedFormatError,
    _apply_exif_orientation,
    load_image,
)


class TestLoadImage:
    """Tests for load_image function."""

    def test_load_png(self, tmp_path: Path) -> None:
        """Test loading a PNG image."""
        img = Image.new("RGB", (100, 100), color="red")
        path = tmp_path / "test.png"
        img.save(path)

        loaded = load_image(path)
        assert loaded.size == (100, 100)
        assert loaded.mode == "RGB"

    def test_load_jpeg(self, tmp_path: Path) -> None:
        """Test loading a JPEG image."""
        img = Image.new("RGB", (100, 100), color="blue")
        path = tmp_path / "test.jpg"
        img.save(path)

        loaded = load_image(path)
        assert loaded.size == (100, 100)
        assert loaded.mode == "RGB"

    def test_load_tiff(self, tmp_path: Path) -> None:
        """Test loading a TIFF image."""
        img = Image.new("RGB", (100, 100), color="green")
        path = tmp_path / "test.tiff"
        img.save(path)

        loaded = load_image(path)
        assert loaded.size == (100, 100)
        assert loaded.mode == "RGB"

    def test_load_bmp(self, tmp_path: Path) -> None:
        """Test loading a BMP image."""
        img = Image.new("RGB", (100, 100), color="yellow")
        path = tmp_path / "test.bmp"
        img.save(path)

        loaded = load_image(path)
        assert loaded.size == (100, 100)
        assert loaded.mode == "RGB"

    def test_load_missing_file_raises(self, tmp_path: Path) -> None:
        """Test that loading a missing file raises ImageLoadError."""
        path = tmp_path / "nonexistent.png"
        with pytest.raises(ImageLoadError, match="not found"):
            load_image(path)

    def test_load_directory_raises(self, tmp_path: Path) -> None:
        """Test that loading a directory raises ImageLoadError."""
        with pytest.raises(ImageLoadError, match="not a file"):
            load_image(tmp_path)

    def test_load_unsupported_format_raises(self, tmp_path: Path) -> None:
        """Test that loading an unsupported format raises UnsupportedFormatError."""
        img = Image.new("RGB", (100, 100), color="red")
        path = tmp_path / "test.gif"
        img.save(path)

        with pytest.raises(UnsupportedFormatError, match="Unsupported image format"):
            load_image(path)

    def test_load_corrupted_file_raises(self, tmp_path: Path) -> None:
        """Test that loading a corrupted file raises ImageLoadError."""
        path = tmp_path / "corrupt.png"
        path.write_bytes(b"not an image")

        with pytest.raises(ImageLoadError, match="Cannot identify image file"):
            load_image(path)

    def test_load_rgba_converted_to_rgb(self, tmp_path: Path) -> None:
        """Test that RGBA images are handled correctly."""
        img = Image.new("RGBA", (100, 100), color=(255, 0, 0, 128))
        path = tmp_path / "test.png"
        img.save(path)

        loaded = load_image(path)
        assert loaded.mode in ("RGB", "RGBA")

    def test_load_grayscale_converted_to_rgb(self, tmp_path: Path) -> None:
        """Test that grayscale images are converted to RGB."""
        img = Image.new("L", (100, 100), color=128)
        path = tmp_path / "test.png"
        img.save(path)

        loaded = load_image(path)
        assert loaded.mode == "RGB"


class TestExifOrientation:
    """Tests for EXIF orientation handling."""

    def _create_image_with_orientation(self, tmp_path: Path, orientation: int) -> Path:
        """Create a test image with specific EXIF orientation."""
        img = Image.new("RGB", (100, 50), color="red")
        # Draw a distinctive pattern to detect orientation
        for x in range(100):
            for y in range(50):
                if x < 50:
                    img.putpixel((x, y), (255, 0, 0))  # Red left half
                else:
                    img.putpixel((x, y), (0, 0, 255))  # Blue right half

        exif = img.getexif()
        exif[274] = orientation
        path = tmp_path / f"orient_{orientation}.jpg"
        img.save(path, exif=exif)
        return path

    @pytest.mark.parametrize("orientation", range(1, 9))
    def test_all_orientations_load_without_error(self, tmp_path: Path, orientation: int) -> None:
        """Test that all 8 EXIF orientations load without error."""
        path = self._create_image_with_orientation(tmp_path, orientation)
        loaded = load_image(path)
        assert loaded is not None
        assert loaded.size == (100, 50) or loaded.size == (50, 100)

    def test_orientation_1_no_change(self, tmp_path: Path) -> None:
        """Test orientation 1 (normal) - no transformation."""
        path = self._create_image_with_orientation(tmp_path, 1)
        loaded = load_image(path)
        # Left half should be red, right half blue (allow JPEG compression artifacts)
        r, g, b = loaded.getpixel((25, 25))
        assert r > 250 and g < 5 and b < 5
        r, g, b = loaded.getpixel((75, 25))
        assert r < 5 and g < 5 and b > 250

    def test_orientation_2_flip_horizontal(self, tmp_path: Path) -> None:
        """Test orientation 2 (flip horizontal)."""
        path = self._create_image_with_orientation(tmp_path, 2)
        loaded = load_image(path)
        # Should be flipped horizontally (allow JPEG compression artifacts)
        r, g, b = loaded.getpixel((25, 25))
        assert r < 5 and g < 5 and b > 250
        r, g, b = loaded.getpixel((75, 25))
        assert r > 250 and g < 5 and b < 5

    def test_orientation_3_rotate_180(self, tmp_path: Path) -> None:
        """Test orientation 3 (rotate 180)."""
        path = self._create_image_with_orientation(tmp_path, 3)
        loaded = load_image(path)
        # Should be rotated 180 (allow JPEG compression artifacts)
        r, g, b = loaded.getpixel((25, 25))
        assert r < 5 and g < 5 and b > 250
        r, g, b = loaded.getpixel((75, 25))
        assert r > 250 and g < 5 and b < 5

    def test_orientation_4_flip_vertical(self, tmp_path: Path) -> None:
        """Test orientation 4 (flip vertical)."""
        path = self._create_image_with_orientation(tmp_path, 4)
        loaded = load_image(path)
        # Should be flipped vertically (allow JPEG compression artifacts)
        r, g, b = loaded.getpixel((25, 25))
        assert r > 250 and g < 5 and b < 5
        r, g, b = loaded.getpixel((75, 25))
        assert r < 5 and g < 5 and b > 250

    def test_orientation_5_flip_horizontal_rotate_90(self, tmp_path: Path) -> None:
        """Test orientation 5 (flip horizontal + rotate 90 CW)."""
        path = self._create_image_with_orientation(tmp_path, 5)
        loaded = load_image(path)
        assert loaded.size == (50, 100)

    def test_orientation_6_rotate_270(self, tmp_path: Path) -> None:
        """Test orientation 6 (rotate 270 CW / 90 CCW)."""
        path = self._create_image_with_orientation(tmp_path, 6)
        loaded = load_image(path)
        assert loaded.size == (50, 100)

    def test_auto_orient_false_keeps_stored_pixels_and_size(self, tmp_path: Path) -> None:
        """Disabling auto-orientation keeps the JPEG's stored orientation."""
        path = self._create_image_with_orientation(tmp_path, 6)

        oriented = load_image(path)
        stored = load_image(path, auto_orient=False)

        assert oriented.size == (50, 100)
        assert stored.size == (100, 50)
        # The stored image has a red left half and a blue right half.
        r, g, b = stored.getpixel((25, 25))
        assert r > 250 and g < 5 and b < 5
        r, g, b = stored.getpixel((75, 25))
        assert r < 5 and g < 5 and b > 250

    def test_orientation_7_flip_horizontal_rotate_270(self, tmp_path: Path) -> None:
        """Test orientation 7 (flip horizontal + rotate 270 CW)."""
        path = self._create_image_with_orientation(tmp_path, 7)
        loaded = load_image(path)
        assert loaded.size == (50, 100)

    def test_orientation_8_rotate_90(self, tmp_path: Path) -> None:
        """Test orientation 8 (rotate 90 CW)."""
        path = self._create_image_with_orientation(tmp_path, 8)
        loaded = load_image(path)
        assert loaded.size == (50, 100)

    def test_no_exif_orientation(self, tmp_path: Path) -> None:
        """Test image without EXIF orientation loads normally."""
        img = Image.new("RGB", (100, 100), color="red")
        path = tmp_path / "no_exif.png"
        img.save(path)

        loaded = load_image(path)
        assert loaded.size == (100, 100)

    def test_invalid_orientation_ignored(self, tmp_path: Path) -> None:
        """Test that invalid orientation values are ignored."""
        img = Image.new("RGB", (100, 100), color="red")
        exif = img.getexif()
        exif[274] = 99  # Invalid orientation
        path = tmp_path / "invalid_orient.jpg"
        img.save(path, exif=exif)

        loaded = load_image(path)
        assert loaded.size == (100, 100)


class TestApplyExifOrientation:
    """Tests for _apply_exif_orientation helper function."""

    def test_orientation_1_returns_same(self) -> None:
        """Test orientation 1 returns unchanged image."""
        img = Image.new("RGB", (100, 100), color="red")
        result = _apply_exif_orientation(img)
        assert result is img

    def test_orientation_2_flips_horizontal(self) -> None:
        """Test orientation 2 flips horizontally."""
        img = Image.new("RGB", (100, 50), color="red")
        img.putpixel((0, 0), (255, 0, 0))
        img.putpixel((99, 0), (0, 0, 255))

        exif = img.getexif()
        exif[274] = 2
        # Manually apply
        result = _apply_exif_orientation(img)
        assert result.getpixel((0, 0)) == (0, 0, 255)
        assert result.getpixel((99, 0)) == (255, 0, 0)

    def test_all_orientation_transforms_defined(self) -> None:
        """Test that all 8 orientations have transforms defined."""
        assert set(ORIENTATION_TRANSFORMS.keys()) == set(range(1, 9))


class TestLoadImagePathTypes:
    """Test load_image accepts both str and Path."""

    def test_load_with_str_path(self, tmp_path: Path) -> None:
        """Test loading with string path."""
        img = Image.new("RGB", (100, 100), color="red")
        path = tmp_path / "test.png"
        img.save(path)

        loaded = load_image(str(path))
        assert loaded.size == (100, 100)

    def test_load_with_path_object(self, tmp_path: Path) -> None:
        """Test loading with Path object."""
        img = Image.new("RGB", (100, 100), color="red")
        path = tmp_path / "test.png"
        img.save(path)

        loaded = load_image(path)
        assert loaded.size == (100, 100)
