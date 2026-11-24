"""Line drawing of a full moon with craters (outline only, no fill), drawn straight as strokes.

Craters are ellipses squashed towards the edge of the disc, as on a real sphere, each
with a short inner rim arc on its shadow side; a few small ones are single circles.

    python3 scripts/moon_craters.py OUT.gcode [PREVIEW.png] [--size MM] [--centre X,Y] [--seed N]
"""

import argparse
import math
import random

from aquila_plot import Plot


def ellipse(cx, cy, a, b, rot, start=0.0, end=2 * math.pi, step=0.4):
    """Points on an ellipse (semi-axes a, b, rotated by rot) between two angles, ~step mm apart."""
    n = max(8, int((end - start) * max(a, b) / step))
    c, s = math.cos(rot), math.sin(rot)
    pts = []
    for i in range(n + 1):
        t = start + (end - start) * i / n
        x, y = a * math.cos(t), b * math.sin(t)
        pts.append((cx + x * c - y * s, cy + x * s + y * c))
    return pts


def moon(radius, centre, seed):
    cx, cy = centre
    rng = random.Random(seed)
    strokes = [ellipse(cx, cy, radius, radius, 0.0)]
    craters = []  # (x, y, r) in disc coordinates, used to avoid overlaps
    sizes = [0.16] * 3 + [0.10] * 6 + [0.06] * 10 + [0.035] * 14
    for frac in sizes:
        r = frac * radius
        for _ in range(200):
            d = radius * math.sqrt(rng.random()) * 0.92
            ang = rng.uniform(0, 2 * math.pi)
            x, y = d * math.cos(ang), d * math.sin(ang)
            squash = math.sqrt(max(0.15, 1 - (d / radius) ** 2))  # foreshortening near the limb
            if d + r > radius * 0.97:
                continue
            if all(math.dist((x, y), (ox, oy)) > r + orr + 1.0 for ox, oy, orr in craters):
                craters.append((x, y, r))
                break
        else:
            continue
        # ellipse: full size along the limb (tangent), squashed along the radius
        a_tan, b_rad = r, r * squash
        rot = ang + math.pi / 2  # x axis of the ellipse along the tangent
        strokes.append(ellipse(cx + x, cy + y, a_tan, b_rad, rot))
        if r >= 0.06 * radius:  # inner rim on the side away from the light (light from upper left)
            strokes.append(ellipse(cx + x, cy + y, a_tan * 0.78, b_rad * 0.78, rot,
                                   *shadow_arc(rot)))
    return strokes


def shadow_arc(rot):
    """Start/end angles (ellipse parameter) of the inner arc facing the lower right."""
    light = math.radians(135)  # light comes from the upper left
    mid = light - rot + math.pi  # inside the crater, the rim facing away from the light
    return mid - 1.1, mid + 1.1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gcode")
    ap.add_argument("preview", nargs="?")
    ap.add_argument("--size", type=float, default=80.0, help="moon diameter, mm")
    ap.add_argument("--centre", default="145,65")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--pen", default="black")
    args = ap.parse_args()
    centre = tuple(float(v) for v in args.centre.split(","))

    from image_plot import order  # pylint: disable=import-outside-toplevel
    plot = Plot(f"Moon with craters, {args.size:.0f} mm, seed {args.seed}")
    plot.start(args.pen)
    strokes = order(moon(args.size / 2, centre, args.seed), plot.pos)
    for s in strokes:
        plot.stroke(s)
    plot.end()
    print(plot.save(args.gcode), f"{len(strokes)} strokes")
    if args.preview:
        from image_plot import preview  # pylint: disable=import-outside-toplevel
        preview(args.preview, strokes, plot.touch_spot, 0.4)


if __name__ == "__main__":
    main()
