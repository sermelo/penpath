"""Unit tests for penpath.core.image.separate."""

import numpy as np
import pytest
from PIL import Image

from penpath.core.image.filters import grayscale
from penpath.core.image.separate import separate_palette
from penpath.core.models import Pen
from penpath.presets.palettes import get_palette

RED = Pen(name="red", width_mm=0.4, color="#FF0000")
BLUE = Pen(name="blue", width_mm=0.4, color="#0000FF")
WHITE = Pen(name="white", width_mm=0.4, color="#FFFFFF")


def _three_region_image(size: int = 30) -> Image.Image:
    """Build a white image with a red square and a blue square."""
    image = Image.new("RGB", (size, size), "white")
    for y in range(2, 13):
        for x in range(2, 13):
            image.putpixel((x, y), (255, 0, 0))
    for y in range(16, 27):
        for x in range(16, 27):
            image.putpixel((x, y), (0, 0, 255))
    return image


def _region_mask(size: int, start: int, end: int) -> np.ndarray:
    mask = np.zeros((size, size), dtype=bool)
    mask[start:end, start:end] = True
    return mask


def _swatch_owner(colour: tuple[int, int, int], pens: list[Pen]) -> str:
    """Return the pen that owns a large uniform swatch of one colour."""
    image = Image.new("RGB", (30, 30), "white")
    for y in range(2, 28):
        for x in range(2, 28):
            image.putpixel((x, y), colour)
    owners = [
        pen.name for pen, layer in separate_palette(image, pens) if np.any(np.asarray(layer) < 255)
    ]
    assert len(owners) == 1
    return owners[0]


def test_separate_palette_regions_are_dark_only_for_own_pen() -> None:
    image = _three_region_image()
    pens = [RED, BLUE, WHITE]

    separated = separate_palette(image, pens)

    assert [pen for pen, _ in separated] == pens
    for _, layer in separated:
        assert layer.mode == "L"
        assert layer.size == image.size

    layers = {pen.name: np.asarray(layer) for pen, layer in separated}
    luminance = np.asarray(grayscale(image))
    red_mask = _region_mask(30, 2, 13)
    blue_mask = _region_mask(30, 16, 27)

    assert np.array_equal(layers["red"][red_mask], luminance[red_mask])
    assert np.all(layers["red"][~red_mask] == 255)
    assert np.array_equal(layers["blue"][blue_mask], luminance[blue_mask])
    assert np.all(layers["blue"][~blue_mask] == 255)
    assert np.all(layers["white"] == 255)


def test_separate_palette_follows_pen_order() -> None:
    separated = separate_palette(_three_region_image(), [BLUE, RED])

    assert [pen for pen, _ in separated] == [BLUE, RED]
    blue_layer = np.asarray(separated[0][1])
    red_layer = np.asarray(separated[1][1])
    blue_mask = _region_mask(30, 16, 27)
    red_mask = _region_mask(30, 2, 13)

    assert np.all(blue_layer[blue_mask] < 128)
    assert np.all(blue_layer[red_mask] == 255)
    assert np.all(red_layer[red_mask] < 128)
    assert np.all(red_layer[blue_mask] == 255)


def test_separate_palette_single_pen_keeps_all_luminance() -> None:
    image = _three_region_image()

    separated = separate_palette(image, [BLUE])

    assert len(separated) == 1
    assert separated[0][0] is BLUE
    assert np.array_equal(np.asarray(separated[0][1]), np.asarray(grayscale(image)))


def test_separate_palette_empty_palette_raises() -> None:
    with pytest.raises(ValueError, match="at least one pen"):
        separate_palette(_three_region_image(), [])


def test_separate_palette_no_pixels_raises() -> None:
    with pytest.raises(ValueError, match="at least one pixel"):
        separate_palette(Image.new("RGB", (0, 0)), [RED])


def test_separate_palette_invalid_pen_colour_names_pen() -> None:
    broken = Pen(name="broken", width_mm=0.4, color="not-a-colour")

    with pytest.raises(ValueError, match="broken"):
        separate_palette(_three_region_image(), [broken])


def test_separate_palette_with_builtin_stabilo_palette() -> None:
    image = _three_region_image()
    pens = get_palette("stabilo_88").pens

    separated = separate_palette(image, pens)

    assert [pen for pen, _ in separated] == pens
    assert all(layer.mode == "L" and layer.size == image.size for _, layer in separated)

    layers = [np.asarray(layer) for _, layer in separated]
    red_mask = _region_mask(30, 2, 13)
    blue_mask = _region_mask(30, 16, 27)
    red_owners = [i for i, layer in enumerate(layers) if np.any(layer[red_mask] < 128)]
    blue_owners = [i for i, layer in enumerate(layers) if np.any(layer[blue_mask] < 128)]

    assert len(red_owners) == 1
    assert len(blue_owners) == 1
    assert red_owners != blue_owners
    background = ~(red_mask | blue_mask)
    assert all(np.all(layer[background] == 255) for layer in layers)


def test_separate_palette_accepts_named_css_colours() -> None:
    red = Pen(name="red", width_mm=0.4, color="red")
    white = Pen(name="white", width_mm=0.4, color="white")

    separated = separate_palette(_three_region_image(), [red, white])

    assert [pen for pen, _ in separated] == [red, white]
    red_layer = np.asarray(separated[0][1])
    assert np.all(red_layer[_region_mask(30, 2, 13)] < 128)


def test_separate_palette_drops_isolated_colour_speckles() -> None:
    image = Image.new("RGB", (30, 30), "white")
    image.putpixel((15, 15), (255, 0, 0))

    separated = separate_palette(image, [RED, WHITE])

    assert np.all(np.asarray(separated[0][1]) == 255)
    assert np.all(np.asarray(separated[1][1]) == 255)


def test_separate_palette_keeps_thin_connected_features() -> None:
    image = Image.new("RGB", (80, 80), "white")
    for index in range(64):
        image.putpixel((index, index), (255, 0, 0))

    separated = separate_palette(image, [RED, WHITE])

    expected = np.zeros((80, 80), dtype=bool)
    expected[np.arange(64), np.arange(64)] = True
    red_layer = np.asarray(separated[0][1])
    assert np.all(red_layer[expected] < 255)
    assert np.all(red_layer[~expected] == 255)


@pytest.mark.parametrize("mode", ["RGBA", "L"])
def test_separate_palette_handles_non_rgb_input(mode: str) -> None:
    image = _three_region_image().convert(mode)
    pens = [RED, BLUE, WHITE]

    separated = separate_palette(image, pens)

    assert [pen for pen, _ in separated] == pens
    assert all(layer.mode == "L" and layer.size == image.size for _, layer in separated)
    dark_in_layers = sum(int(np.count_nonzero(np.asarray(layer) < 128)) for _, layer in separated)
    assert dark_in_layers == int(np.count_nonzero(np.asarray(grayscale(image)) < 128))


STABILO = get_palette("stabilo_88").pens


@pytest.mark.parametrize(
    ("colour", "expected"),
    [
        ((138, 149, 133), "stabilo_88_light_green"),
        ((128, 169, 102), "stabilo_88_light_green"),
    ],
)
def test_separate_palette_muted_green_field_picks_a_green_pen(
    colour: tuple[int, int, int], expected: str
) -> None:
    """A muted landscape field is green by hue, never light blue."""
    assert _swatch_owner(colour, STABILO) == expected


@pytest.mark.parametrize(
    ("colour", "expected"),
    [
        ((225, 133, 123), "stabilo_88_red"),
        ((172, 158, 85), "stabilo_88_yellow"),
        ((213, 141, 100), "stabilo_88_orange"),
    ],
)
def test_separate_palette_muted_swatches_pick_their_hue_family(
    colour: tuple[int, int, int], expected: str
) -> None:
    """Hue decides first, so muted red, yellow and orange do not collapse."""
    owner = _swatch_owner(colour, STABILO)
    assert owner == expected
    assert owner not in {"stabilo_88_brown", "stabilo_88_light_blue", "stabilo_88_black"}


def test_separate_palette_saturated_green_is_not_stolen_by_black() -> None:
    """A vivid green keeps a green pen even though black has zero chroma."""
    assert _swatch_owner((0, 150, 62), STABILO) == "stabilo_88_green"


def test_separate_palette_dark_neutral_picks_black_and_pale_neutral_keeps_light_pen() -> None:
    """Near-neutral pixels keep the old lightness-led Lab assignment."""
    assert _swatch_owner((40, 40, 40), STABILO) == "stabilo_88_black"
    assert _swatch_owner((230, 230, 230), STABILO) == "stabilo_88_light_blue"


def test_separate_palette_pure_red_and_blue_stay_on_distinct_chromatic_pens() -> None:
    """Pure colours still separate into distinct, non-neutral regions."""
    image = _three_region_image()
    layers = [np.asarray(layer) for _, layer in separate_palette(image, STABILO)]
    red_mask = _region_mask(30, 2, 13)
    blue_mask = _region_mask(30, 16, 27)
    red_owners = [index for index, layer in enumerate(layers) if np.any(layer[red_mask] < 128)]
    blue_owners = [index for index, layer in enumerate(layers) if np.any(layer[blue_mask] < 128)]

    assert len(red_owners) == len(blue_owners) == 1
    assert red_owners != blue_owners
    assert STABILO[red_owners[0]].color != "#000000"
    assert STABILO[blue_owners[0]].color != "#000000"
