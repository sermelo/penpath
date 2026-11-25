"""Generate the six basic-shape fixtures as plain-text PBM (P1) files.

Run from anywhere with ``uv run python tests/fixtures/images/basic/generate_basic.py``.
The files are written beside this script and are byte-for-byte reproducible.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

OUTPUT_DIR = Path(__file__).resolve().parent
SIZE = 64
CENTRE = (SIZE - 1) / 2


def _canvas(black: bool) -> np.ndarray:
    """Return a 64x64 bitmap of zeros (white) or ones (black)."""
    return np.full((SIZE, SIZE), int(black), dtype=np.uint8)


def make_black_square() -> np.ndarray:
    """Return a 25x25 black square centred on white."""
    bitmap = _canvas(False)
    bitmap[19:44, 19:44] = 1
    return bitmap


def make_white_square() -> np.ndarray:
    """Return a 25x25 white square centred on black."""
    bitmap = _canvas(True)
    bitmap[19:44, 19:44] = 0
    return bitmap


def make_black_disc() -> np.ndarray:
    """Return a black disc of radius 22.4 centred on white."""
    yy, xx = np.ogrid[:SIZE, :SIZE]
    inside = (xx - CENTRE) ** 2 + (yy - CENTRE) ** 2 <= (SIZE * 0.35) ** 2
    return inside.astype(np.uint8)


def make_horizontal_line() -> np.ndarray:
    """Return a 51x2 black bar centred on white."""
    bitmap = _canvas(False)
    bitmap[31:33, 6:57] = 1
    return bitmap


def make_checkerboard() -> np.ndarray:
    """Return eight by eight 8x8 cells, black where row plus col is even."""
    cell = np.arange(SIZE) // 8
    return (((cell[:, None] + cell[None, :]) % 2) == 0).astype(np.uint8)


def make_triangle() -> np.ndarray:
    """Return a filled black triangle with its apex up, on white."""
    bitmap = _canvas(False)
    for y in range(SIZE):
        if y > 6:
            half_width = int(y * 0.45)
            bitmap[y, 32 - half_width : 32 + half_width] = 1
    return bitmap


def make_fixtures() -> dict[str, np.ndarray]:
    """Return all six bitmaps keyed by file name."""
    return {
        "black_square.pbm": make_black_square(),
        "white_square.pbm": make_white_square(),
        "black_disc.pbm": make_black_disc(),
        "horizontal_line.pbm": make_horizontal_line(),
        "checkerboard.pbm": make_checkerboard(),
        "triangle.pbm": make_triangle(),
    }


def to_pbm(bitmap: np.ndarray) -> bytes:
    """Encode a 0/1 bitmap as an ASCII PBM (P1) file."""
    rows = ["".join("1" if value else "0" for value in row) for row in bitmap]
    height, width = bitmap.shape
    return (
        f"P1\n{width} {height}\n".encode("ascii")
        + b"\n".join(row.encode("ascii") for row in rows)
        + b"\n"
    )


def write_fixtures(output_dir: Path) -> None:
    """Write all six fixtures into ``output_dir``."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, bitmap in make_fixtures().items():
        (output_dir / name).write_bytes(to_pbm(bitmap))


def main() -> None:
    """Write the fixtures beside this script."""
    write_fixtures(OUTPUT_DIR)


if __name__ == "__main__":
    main()
