"""Layered SVG -> Aquila G-code: one pen per layer, with the proven pen-change procedure.

Input is the layout agreed with penpath: Inkscape layer groups (layer1, layer2, ... in
drawing order = file order), pen name in the layer label, stroke colour, mm units, paper size in the
SVG. Read with vpype.read_multilayer_svg, so penpath's output works unchanged.

    .venv/bin/python scripts/svg_plot.py IN.svg OUT.gcode [PREVIEW.png]
        [--at X,Y]      pen coordinates (mm) of the page's lower-left corner
                        (default: page against the reachable area's right and front edges)
        [--layers 1,3]  only these layers (1-based, file order), in this order (default: all)
        [--margin N]    skip anything within N mm of the page edge (default 0)

Pen coordinates: X right, Y to the back, origin at the bed's front-left corner. The SVG
has Y down, so it is flipped. Anything outside the reachable area is an error, not
clipped silently.
"""

import argparse
import math
import sys

import os
import vpype as vp

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aquila_plot import Plot, pen_reach


INK = "{http://www.inkscape.org/namespaces/inkscape}"


def load(path):
    """([(name, colour hex or None, LineCollection in px)], width_px, height_px), one entry per
    top-level layer group in file order.

    vpype.read_multilayer_svg takes the layer id from the DIGITS in the label ("stabilo_88_red"
    and "stabilo_88_green" both become layer 88 and merge), so each group is read on its own."""
    import io
    import xml.etree.ElementTree as ET

    root = ET.parse(path).getroot()
    if root.get("width") is None or root.get("height") is None:
        raise SystemExit("the SVG has no width/height: need the paper size (mm)")
    out, size = [], None
    for n, g in enumerate((g for g in root if g.tag.rsplit("}", 1)[-1] == "g"), 1):
        single = ET.Element(root.tag, root.attrib)
        single.append(g)
        text = ET.tostring(single, encoding="unicode")
        lc, w, h = vp.read_svg(io.StringIO(text), quantization=0.05, simplify=False)
        size = (w, h)
        out.append((g.get(INK + "label") or g.get("id") or f"layer{n}", g.get("stroke"), lc))
    if not out:
        raise SystemExit("no layer groups in the SVG")
    return out, *size


def strokes(lc, flip_h, at, margin, page_w, page_h):
    """Polylines of a layer as [(x, y)] in pen coordinates."""
    out = []
    for line in lc:
        pts = [(p.real, p.imag) for p in line]
        for x, y in pts:
            if not (margin - 1e-6 <= x <= page_w - margin + 1e-6 and margin - 1e-6 <= y <= page_h - margin + 1e-6):
                raise ValueError(f"point ({x:.1f}, {y:.1f}) mm is inside the {margin} mm margin / off the page")
        out.append([(at[0] + x, at[1] + (page_h - y)) for x, y in pts])
    return out


def order_nearest(lines, start):
    """Greedy nearest-endpoint order (reversing lines when it helps); short travel, no change in drawing."""
    left, pos, out = list(lines), start, []
    while left:
        i, rev, best = 0, False, math.inf
        for k, l in enumerate(left):
            for r, p in ((False, l[0]), (True, l[-1])):
                d = math.dist(pos, p)
                if d < best:
                    i, rev, best = k, r, d
        l = left.pop(i)
        l = l[::-1] if rev else l
        out.append(l)
        pos = l[-1]
    return out


def build(svg, out, preview=None, at=None, layers=None, margin=0.0, sort=True):
    found, wpx, hpx = load(svg)
    w, h = wpx * 25.4 / 96, hpx * 25.4 / 96  # vpype works in px (96/in)
    (xmin, xmax), (ymin, ymax) = pen_reach()
    at = at or (xmax - w, ymin)
    chosen = [found[i - 1] for i in layers] if layers else found  # --layers: 1-based, file order
    plot = Plot(f"{svg}: {len(chosen)} layer(s), page {w:.0f} x {h:.0f} mm at ({at[0]:.1f}, {at[1]:.1f})")
    drawing = []
    for n, (name, colour, lc) in enumerate(chosen):
        lines = strokes(vp.LineCollection([l * 25.4 / 96 for l in lc.lines]), True, at, margin, w, h)
        if sort:
            lines = order_nearest(lines, plot.pos or plot.touch_spot)
        (plot.start if n == 0 else plot.pen)(name)
        for l in lines:
            plot.stroke(l)
        drawing.append((name, colour, lines))
    plot.end()
    print(plot.save(out))
    if preview:
        draw_preview(preview, drawing, at, w, h)
    return plot


def draw_preview(path, drawing, at, w, h):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    fig, ax = plt.subplots(figsize=(7, 7))
    (xmin, xmax), (ymin, ymax) = pen_reach()
    ax.add_patch(Rectangle((xmin, ymin), xmax - xmin, ymax - ymin, fill=False, ls=":", ec="grey"))
    ax.add_patch(Rectangle(at, w, h, fill=False, ec="black", lw=0.8))
    for name, color, lines in drawing:
        c = color or "k"
        for i, l in enumerate(lines):
            ax.plot(*zip(*l), color=c, lw=0.6, label=name if i == 0 else None)
    ax.set_aspect("equal")
    ax.legend(loc="upper left", fontsize=7)
    ax.set_title("pen coordinates, mm")
    fig.savefig(path, dpi=110, bbox_inches="tight")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("svg")
    ap.add_argument("gcode")
    ap.add_argument("preview", nargs="?")
    ap.add_argument("--at")
    ap.add_argument("--layers")
    ap.add_argument("--margin", type=float, default=0.0)
    ap.add_argument("--no-sort", action="store_true")
    a = ap.parse_args()
    build(a.svg, a.gcode, a.preview,
          at=tuple(float(v) for v in a.at.split(",")) if a.at else None,
          layers=[int(v) for v in a.layers.split(",")] if a.layers else None,
          margin=a.margin, sort=not a.no_sort)
