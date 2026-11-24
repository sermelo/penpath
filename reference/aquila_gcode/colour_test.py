"""Two-colour test: pen-change procedure, registration between pens, hatching density.

- 3 x 3 crosses with a 4 mm square round each centre, 50 mm apart, drawn by BOTH pens:
  any gap between the two colours is the registration error of a pen change (the hex
  bore's play, the clamp, the touch height).
- three hatch patches 20 x 20 mm with lines 0.6 / 1.0 / 1.5 mm apart: pen 1 horizontal,
  pen 2 vertical over the same patches, so they show how dense hatching looks and how
  two colours mix where they cross (what a photo will be built from).

    python3 scripts/colour_test.py OUT.gcode [PREVIEW.png] [--pens NAME1,NAME2]
"""

import sys

from aquila_plot import Plot

CENTRES = [(x, y) for y in (150.0, 100.0, 50.0) for x in (50.0, 100.0, 150.0)]  # mm, pen coordinates
ARM, BOX = 6.0, 2.0  # mm, cross half-length and half-side of the square
PATCHES = [((65.0, 115.0), 0.6), ((115.0, 115.0), 1.0), ((65.0, 65.0), 1.5)]  # lower-left corner, spacing
PATCH = 20.0  # mm


def marks():
    out = []
    for x, y in CENTRES:
        out.append([(x - ARM, y), (x + ARM, y)])
        out.append([(x, y - ARM), (x, y + ARM)])
        out.append([(x - BOX, y - BOX), (x + BOX, y - BOX), (x + BOX, y + BOX), (x - BOX, y + BOX), (x - BOX, y - BOX)])
    return out


def hatch(corner, spacing, vertical):
    """Boustrophedon hatch lines across one patch, one stroke per line."""
    x0, y0 = corner
    n = int(PATCH / spacing) + 1
    out = []
    for i in range(n):
        t = i * spacing
        if vertical:
            line = [(x0 + t, y0), (x0 + t, y0 + PATCH)]
        else:
            line = [(x0, y0 + t), (x0 + PATCH, y0 + t)]
        out.append(line if i % 2 == 0 else line[::-1])
    return out


def strokes_for(pen_index):
    out = marks()
    for corner, spacing in PATCHES:
        out += hatch(corner, spacing, vertical=pen_index == 1)
    return out


def main(args):
    pens = ["colour 1", "colour 2"]
    if "--pens" in args:
        at = args.index("--pens")
        pens = args[at + 1].split(",")
        del args[at:at + 2]
    plot = Plot("Two-colour test: registration and hatching")
    plot.start(pens[0])
    for i, name in enumerate(pens[:2]):
        if i:
            plot.pen(name)
        for points in strokes_for(i):
            plot.stroke(points)
    plot.end()
    print(plot.save(args[0]))
    if len(args) > 1:
        preview(args[1], pens)


def preview(path, pens):
    import matplotlib  # pylint: disable=import-outside-toplevel
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # pylint: disable=import-outside-toplevel

    fig, ax = plt.subplots(figsize=(7, 7))
    ax.add_patch(plt.Rectangle((0, 0), 220, 220, fill=False, color="grey"))
    for i, colour in enumerate(("tab:blue", "tab:red")):
        for points in strokes_for(i):
            xs, ys = zip(*points)
            ax.plot(xs, ys, color=colour, linewidth=0.5, alpha=0.8)
    for (x, y), spacing in PATCHES:
        ax.text(x + PATCH / 2, y - 4, f"{spacing} mm", ha="center", fontsize=8)
    ax.text(110, 4, "front of the printer", ha="center", color="grey")
    ax.set_title(f"pen 1 = {pens[0]} (blue), pen 2 = {pens[1]} (red), pen coordinates on the bed", fontsize=9)
    ax.set_xlim(-5, 225)
    ax.set_ylim(-5, 225)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.savefig(path, dpi=110, bbox_inches="tight")


if __name__ == "__main__":
    main(sys.argv[1:])
