"""One-colour picture -> G-code, two modes. Image top = back of the bed.

- shape mode (default), for black-and-white images (icons, silhouettes, logos): the
  dark pixels (or opaque ones, if it has transparency) are the shape, drawn as an
  outline plus hatching;
- tone mode (--tones N), for grey pictures: N hatch layers at different angles
  (45, -45, 0, 90 deg, ...); layer k covers the parts darker than k/(N+1), so light
  greys get one layer, darker ones are cross-hatched, black gets all N. No outline.

    python3 scripts/image_plot.py IMAGE OUT.gcode [PREVIEW.png]
        [--size MM] [--centre X,Y] [--width MM] [--fill PERCENT] [--angle DEG] [--pen NAME]
        [--tones N]

--width is the pen's line width (Stabilo Point 88 ~0.4 mm, a marker ~1-2 mm). Lines are
kept half a width inside the shape, so the inked area has the image's size and edges.
--fill is how much of the shape the hatching inks: 100 = lines touching (solid), 50 =
gaps as wide as the lines, 0 = outline only. Hatch spacing = width / (fill / 100).
In tone mode --fill is per layer (default 35).

--size is the longest side in mm (default 70), --centre the picture's centre in pen
coordinates on the bed (default 150,60: paper in the bed's front-right corner).
"""

import argparse
import math

import numpy as np
from PIL import Image, ImageFilter
from contourpy import contour_generator

from aquila_plot import Plot

THRESHOLD = 128  # 0-255, darker than this is "ink"
TONE_ANGLES = (45.0, -45.0, 0.0, 90.0, 22.5, -67.5)  # deg, one per tone layer


def load_mask(path, shrink_px=0, blur=1):
    """Float image 0..1 (1 = ink), slightly blurred so outlines come out smooth, the ink
    shrunk by about `shrink_px` pixels (so a wide pen's line stays inside the shape)."""
    img = Image.open(path)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        white = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(white, img)
    grey = img.convert("L")
    pad = 4  # white margin, so shapes touching the image edge still get a closed outline
    padded = Image.new("L", (grey.width + 2 * pad, grey.height + 2 * pad), 255)
    padded.paste(grey, (pad, pad))
    grey = padded
    if shrink_px >= 0.5:
        grey = grey.filter(ImageFilter.MaxFilter(2 * round(shrink_px) + 1))  # white grows
    grey = grey.filter(ImageFilter.GaussianBlur(blur))
    return 1.0 - np.asarray(grey, dtype=float) / 255.0


def to_mm(mask, scale, centre):
    """Function mapping pixel (col, row) of the (padded, centred) mask to bed mm."""
    h, w = mask.shape
    cx, cy = centre

    def f(col, row):
        return cx + (col - w / 2) * scale, cy + (h / 2 - row) * scale
    return f


def outlines(mask, f, min_step=0.15):
    out = []
    for line in contour_generator(z=mask).lines(1 - THRESHOLD / 255):
        pts = []
        for col, row in line:
            p = f(col, row)
            if not pts or math.dist(p, pts[-1]) >= min_step:
                pts.append(p)
        if len(pts) > 2 and math.dist(pts[0], pts[-1]) < 2 * min_step:
            pts[-1] = pts[0]  # closed contour: end exactly where it began
        if len(pts) >= 2:
            out.append(pts)
    return out


def hatching(ink, f, scale, spacing, angle_deg, inset=0.0):
    """Parallel lines `spacing` mm apart at `angle_deg`, cut to `ink` (bool array)."""
    h, w = ink.shape
    a = math.radians(angle_deg)
    d = (math.cos(a), math.sin(a))  # along a line, in pixel (col, -row) terms
    n = (-d[1], d[0])  # across the lines
    step_px = 0.1 / scale  # sample every 0.1 mm
    gap_px = spacing / scale
    corners = [(0, 0), (w, 0), (0, h), (w, h)]
    across = [c[0] * n[0] - c[1] * n[1] for c in corners]
    along = [c[0] * d[0] - c[1] * d[1] for c in corners]
    t = np.arange(min(along), max(along), step_px)
    out = []
    for k, s in enumerate(np.arange(min(across) + gap_px / 2, max(across), gap_px)):
        cols = s * n[0] + t * d[0]
        rows = -(s * n[1] + t * d[1])
        inside = (cols >= 0) & (cols < w) & (rows >= 0) & (rows < h)
        hit = np.zeros_like(inside)
        hit[inside] = ink[rows[inside].astype(int), cols[inside].astype(int)]
        edges = np.flatnonzero(np.diff(np.concatenate(([0], hit.astype(int), [0]))))
        runs = []
        for start, stop in zip(edges[::2], edges[1::2]):
            p0, p1 = f(cols[start], rows[start]), f(cols[stop - 1], rows[stop - 1])
            length = math.dist(p0, p1)
            if length <= 2 * inset + 0.5:
                continue
            u = ((p1[0] - p0[0]) / length, (p1[1] - p0[1]) / length)
            runs.append([(p0[0] + u[0] * inset, p0[1] + u[1] * inset),
                         (p1[0] - u[0] * inset, p1[1] - u[1] * inset)])
        if k % 2:
            runs = [r[::-1] for r in runs[::-1]]
        out += runs
    return out


def order(strokes, start):
    """Greedy nearest-neighbour order; a stroke may be drawn either way round."""
    left, out, pos = list(strokes), [], start
    while left:
        best = min(range(len(left)), key=lambda i: min(math.dist(pos, left[i][0]), math.dist(pos, left[i][-1])))
        s = left.pop(best)
        if math.dist(pos, s[-1]) < math.dist(pos, s[0]):
            s = s[::-1]
        out.append(s)
        pos = s[-1]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("gcode")
    ap.add_argument("preview", nargs="?")
    ap.add_argument("--size", type=float, default=70.0)
    ap.add_argument("--centre", default="150,60")
    ap.add_argument("--width", type=float, default=0.4)
    ap.add_argument("--fill", type=float)
    ap.add_argument("--angle", type=float, default=45.0)
    ap.add_argument("--pen", default="black")
    ap.add_argument("--tones", type=int, default=0)
    args = ap.parse_args()
    if args.fill is None:
        args.fill = 35.0 if args.tones else 50.0

    w, h = Image.open(args.image).size
    scale = args.size / max(w, h)
    centre = tuple(float(v) for v in args.centre.split(","))
    spacing = args.width / min(args.fill, 100) * 100 if args.fill > 0 else None
    if args.tones:
        dark = load_mask(args.image, blur=max(1.0, 0.3 / scale))  # smooth over ~0.3 mm
        f = to_mm(dark, scale, centre)
        strokes = []
        for k in range(args.tones):
            angle = TONE_ANGLES[k % len(TONE_ANGLES)] + args.angle - 45
            strokes += hatching(dark > (k + 1) / (args.tones + 1), f, scale, spacing, angle)
        mode = f"{args.tones} tone layers"
    else:
        mask = load_mask(args.image, args.width / 2 / scale)
        f = to_mm(mask, scale, centre)
        strokes = outlines(mask, f)
        if spacing:
            strokes += hatching(mask >= 1 - THRESHOLD / 255, f, scale, spacing, args.angle)
        mode = "shape"

    plot = Plot(f"Picture: {args.image.rsplit('/', 1)[-1]}, {args.size:.0f} mm, {mode}, "
                f"pen {args.width} mm, fill {args.fill:.0f}% (hatch {spacing or 0:.2f} mm)")
    plot.start(args.pen)
    strokes = order(strokes, plot.pos)
    for s in strokes:
        plot.stroke(s)
    plot.end()
    print(plot.save(args.gcode), f"{len(strokes)} strokes")
    if args.preview:
        preview(args.preview, strokes, plot.touch_spot, args.width)


def preview(path, strokes, touch, width):
    import matplotlib  # pylint: disable=import-outside-toplevel
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # pylint: disable=import-outside-toplevel
    from aquila_plot import pen_reach  # pylint: disable=import-outside-toplevel

    fig, ax = plt.subplots(figsize=(7, 7))
    pt_per_mm = 72 * 7 * 0.775 / 230  # line widths drawn to scale (axes ~80% of 7 in)
    ax.add_patch(plt.Rectangle((0, 0), 220, 220, fill=False, color="grey"))
    (x0, x1), (y0, y1) = pen_reach()
    ax.add_patch(plt.Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, color="grey", linestyle=":"))
    for s in strokes:
        xs, ys = zip(*s)
        ax.plot(xs, ys, color="black", linewidth=width * pt_per_mm, solid_capstyle="round", alpha=0.85)
    ax.plot(*touch, "rx")
    ax.text(touch[0], touch[1] + 4, "pen set here", color="red", ha="center", fontsize=7)
    ax.text(110, -4, "front of the printer", ha="center", color="grey")
    ax.set_xlim(-5, 225)
    ax.set_ylim(-8, 225)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.savefig(path, dpi=150, bbox_inches="tight")


if __name__ == "__main__":
    main()
