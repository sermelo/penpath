"""Tests for the library-only contour stroke tracer."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw
from pydantic import ValidationError
from shapely import LineString

from penpath.core import ContourSettings, contour_strokes, load_image
from penpath.core.drawing import contour_strokes as drawing_contour_strokes
from penpath.core.drawing.pfm_contour import ContourSettings as ModuleContourSettings
from penpath.core.drawing.pfm_contour import contour_strokes as module_contour_strokes

REFERENCE_IMAGES = Path(__file__).resolve().parents[4] / "tests/fixtures/images/reference"


def _image(gray: np.ndarray) -> Image.Image:
    """Build a fast greyscale PIL image from a uint8-compatible array."""
    return Image.fromarray(np.asarray(gray, dtype=np.uint8))


def _blank(value: int = 255) -> np.ndarray:
    return np.full((128, 128), value, dtype=np.uint8)


def _square() -> np.ndarray:
    image = Image.fromarray(_blank())
    ImageDraw.Draw(image).rectangle((20, 20, 100, 100), fill=0)
    return np.asarray(image)


def _disc() -> np.ndarray:
    image = Image.fromarray(_blank())
    ImageDraw.Draw(image).ellipse((20, 20, 100, 100), fill=0)
    return np.asarray(image)


def _tones() -> np.ndarray:
    image = _blank()
    image[20:50, 20:50] = 50
    yy, xx = np.ogrid[:128, :128]
    distance = (xx - 90) ** 2 + (yy - 90) ** 2
    image[(distance <= 25**2) & (distance >= 15**2)] = 200
    return image


def _assert_clean(strokes: list[LineString], image: Image.Image) -> None:
    assert strokes
    width, height = image.size
    for stroke in strokes:
        assert isinstance(stroke, LineString)
        assert stroke.is_valid
        assert stroke.length > 0.0
        assert len(list(stroke.coords)) >= 2
        assert stroke.coords[0] == stroke.coords[-1]
        for x, y in stroke.coords:
            assert 0.0 <= x <= width - 1
            assert 0.0 <= y <= height - 1


class TestContourSettings:
    def test_defaults(self) -> None:
        assert ContourSettings().model_dump() == {
            "threshold": 128,
            "levels": 1,
            "turn_policy": "minority",
            "turd_size": 20,
            "alpha_max": 1.0,
            "opticurve": True,
            "smoothing": 0.5,
            "simplify_tolerance": 0.75,
            "seed": None,
        }

    @pytest.mark.parametrize(
        "field,value",
        [
            ("threshold", -1),
            ("threshold", 256),
            ("levels", 0),
            ("levels", 9),
            ("turn_policy", "up"),
            ("turd_size", -1),
            ("turd_size", 10001),
            ("alpha_max", -0.1),
            ("alpha_max", 1.3335),
            ("smoothing", -0.1),
            ("smoothing", 1.1),
            ("simplify_tolerance", -0.1),
            ("simplify_tolerance", 10.1),
        ],
    )
    def test_out_of_range_values_are_rejected(self, field: str, value: object) -> None:
        with pytest.raises(ValidationError):
            ContourSettings(**{field: value})


class TestContourStrokes:
    def test_public_exports_point_to_same_function(self) -> None:
        assert contour_strokes is drawing_contour_strokes is module_contour_strokes
        assert ContourSettings is ModuleContourSettings

    def test_blank_and_empty_images_return_no_strokes(self) -> None:
        assert contour_strokes(_image(_blank()), ContourSettings()) == []
        assert contour_strokes(Image.new("L", (0, 0), 255), ContourSettings()) == []

    def test_turd_size_removes_single_pixel_speck(self) -> None:
        speck = _blank()
        speck[10, 10] = 0
        assert contour_strokes(_image(speck), ContourSettings()) == []
        assert len(contour_strokes(_image(speck), ContourSettings(turd_size=0))) == 1

    def test_black_square_yields_closed_contour(self) -> None:
        strokes = contour_strokes(_image(_square()), ContourSettings())
        assert len(strokes) == 1
        stroke = strokes[0]
        assert stroke.coords[0] == stroke.coords[-1]
        assert stroke.bounds == (19.5, 19.5, 100.5, 100.5)

    def test_black_disc_yields_closed_contour(self) -> None:
        strokes = contour_strokes(_image(_disc()), ContourSettings())
        _assert_clean(strokes, _image(_disc()))
        assert any(stroke.coords[0] == stroke.coords[-1] for stroke in strokes)

    def test_strokes_are_valid_in_bounds_and_non_zero(self) -> None:
        image = _image(_tones())
        for settings in (
            ContourSettings(),
            ContourSettings(levels=3),
            ContourSettings(turn_policy="random", seed=42),
            ContourSettings(alpha_max=0.0, simplify_tolerance=0.0, smoothing=0.0),
            ContourSettings(turd_size=0, simplify_tolerance=10.0),
        ):
            _assert_clean(contour_strokes(image, settings), image)

    @pytest.mark.parametrize(
        "policy", ["black", "white", "left", "right", "minority", "majority", "random"]
    )
    def test_seed_is_deterministic_for_every_turn_policy(self, policy: str) -> None:
        image = _image(_tones())
        options = {"turn_policy": policy, "seed": 42, "turd_size": 5}
        first = contour_strokes(image, ContourSettings(**options))
        second = contour_strokes(image, ContourSettings(**options))
        _assert_clean(first, image)
        assert [list(stroke.coords) for stroke in first] == [
            list(stroke.coords) for stroke in second
        ]
        if policy != "random":
            other = contour_strokes(image, ContourSettings(**{**options, "seed": 7}))
            assert [list(stroke.coords) for stroke in first] == [
                list(stroke.coords) for stroke in other
            ]

    def test_three_levels_add_contours_over_one_level(self) -> None:
        image = _image(_tones())
        single = contour_strokes(image, ContourSettings(turd_size=5))
        multi = contour_strokes(image, ContourSettings(levels=3, turd_size=5))
        assert len(multi) > len(single)

    def test_smoothing_changes_the_simplified_polygon(self) -> None:
        image = _image(_disc())
        plain = contour_strokes(image, ContourSettings(smoothing=0.0))
        smoothed = contour_strokes(image, ContourSettings(smoothing=0.5))
        assert [list(stroke.coords) for stroke in smoothed] != [
            list(stroke.coords) for stroke in plain
        ]

    @pytest.mark.parametrize("name", ["face.jpg", "photo.jpg"])
    def test_reference_images_give_valid_in_bounds_strokes(self, name: str) -> None:
        image = load_image(REFERENCE_IMAGES / name)
        strokes = contour_strokes(image, ContourSettings())
        _assert_clean(strokes, image)
