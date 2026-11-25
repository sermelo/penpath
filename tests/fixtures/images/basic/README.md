# Basic-shape fixtures

Six small, simple shapes used by the basic-level gate. They are stored as ASCII
PBM (P1) files so an agent that cannot look at a raster image can still read and
check every pixel as text. Each file is 64x64 pixels and about 4 KB. Part 2 of
LUC-75 renders a fixture to PNG in a temporary folder before calling the CLI;
`.pbm` is test data only and is not a product input format.

| File | What it is | What it catches | Black pixels |
|------|------------|-----------------|-------------:|
| `black_square.pbm` | Black square, rows/columns 19:44 (25x25), centred on white | Filling a compact solid area and placing it in the middle of the canvas | 625 |
| `white_square.pbm` | The same square in white, on a black canvas | Inversion and inverted-tone handling: most of the canvas is black | 3471 |
| `black_disc.pbm` | Black disc, centre (31.5, 31.5), radius `64 * 0.35`, on white | Curved edges and even coverage of a round shape | 1568 |
| `horizontal_line.pbm` | Black bar, rows 31:33 (2 px), columns 6:57 (51 px), centred, on white | Very thin features: a shape only two pixels tall must survive | 102 |
| `checkerboard.pbm` | 8x8 cells of 8x8 px; cell (row, col) is black when row + col is even | Sharp alternating edges, regular structure and repeated detail | 2048 |
| `triangle.pbm` | Filled black triangle, apex up: row y > 6 spans columns `32 - int(y * 0.45)` to `32 + int(y * 0.45)`, on white | Slanted edges and growing width towards the base | 1742 |

## Reading a P1 file

The first line is the magic `P1`, the second is the width and height (`64 64`),
and the following 64 lines hold the pixels, one character per pixel: `1` means
black and `0` means white. Whitespace separates tokens, so the end-of-line
characters are harmless and keep each row readable. For example, the header of
every fixture is:

```text
P1
64 64
```

## Rebuild

Run from the repository root:

```bash
uv run python tests/fixtures/images/basic/generate_basic.py
```

The script uses NumPy only, takes no random input and rewrites the six files
byte for byte. `pytest tests/integration/test_basic_shapes.py` checks that the
committed files match a fresh regeneration and have the expected shape counts.
