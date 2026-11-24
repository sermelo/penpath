"""Pen-plot test for the Aquila pen holder (stage 2, cadquery_models a07fb0b).

Test 1 (2026-11-18): all ladder lines looked the same (pressure doesn't show with the
Stabilo), but every stroke had an ink dot at both ends: the pen stood still on the paper
while Z went down and up. Test 3 lands and lifts the pen while moving (RAMP), pen down
at Z 9.0 (1 mm, ~13 g), ladder 9.5 / 9.0 / 8.5 only.

Writes G-code straight from Python (no vpype yet) for three checks:

(a) pressure ladder: 40 mm lines, pen down at LADDER_Z (mm past the touch height Z 10
    times ~13 g/mm, the flexure's rate, is the force).
    Line k has k short ticks at its left end; line 1 (lightest) is the one at the back.
(b) a 50 mm square with both diagonals, a 50 mm circle drawn anticlockwise and a 25 mm
    circle drawn clockwise: wobble, straightness, backlash (the circles' seams and the
    corners show it).
(c) a cross at a known commanded nozzle position CROSS. At the end the nozzle parks
    right above that commanded position, the pen ~2.5 mm over the paper, and holds still
    for MEASURE_SECONDS: the distance from the nozzle tip to the cross's centre is the
    pen's offset from the nozzle (look straight down, the nozzle is ~12 mm up).

All coordinates below are commanded NOZZLE positions. The pen draws ~20 mm to the left
(-X) and ~25 mm to the front (-Y) of them (rough guess from the holder's design), so
everything is kept well inside the 220 x 220 bed for that unknown.

Z procedure (the CR Touch triggers with the nozzle only ~0.85 mm above the bed, so the
pen tip, which hangs below the nozzle, must be out while homing):

1. Before starting: tape the paper down, pen OUT of the clamp (or pushed up above the
   nozzle). Start the file. It beeps and waits 10 s (last chance to abort), then homes.
2. It moves to Z10 clear of the drawing (TOUCH_XY) and pauses (M0) until the knob is
   pressed (it may take two presses): slide the pen down until it just touches the paper (the flexure must not
   move), tighten the clamp screw. The tip then rests on the paper until the countdown
   ends and leaves a blot: a scrap of paper under it, pulled away once tightened, avoids it.
3. It plots: pen up Z 12.5, pen down PEN_DOWN_Z except in the ladder. Each stroke
   starts with the pen hovering at HOVER_Z over a point a little before the stroke, then
   moves along the stroke while lowering, so the pen touches the paper (Z 10) right at
   the stroke's start already moving and reaches full pressure RAMP mm later; the end is
   the mirror image. No standing contact, so no ink dots.
Never home again with the pen in. No heaters, no fan.

The pen-in wait is an M0 pause: pause_test_a_m0.gcode showed the Aquila's firmware
resumes from it with the knob (a couple of presses, 2026-11-18). Tests 1-3 used a
timed countdown before that was known.

    python3 scripts/test_plot.py [OUT.gcode] [PREVIEW.png]
"""

import math
import sys

TOUCH_Z = 10.0  # mm, nozzle height at which the pen is set to just touch the paper
PEN_DOWN_Z = 9.0  # mm, normal drawing height (1 mm into the flexure, ~13 g)
PEN_UP_Z = 12.5  # mm, travel height (pen ~2.5 mm above the paper)
LADDER_Z = (9.5, 9.0, 8.5)  # mm, pen-down heights of the pressure ladder
HOVER_Z = 10.5  # mm, pen just clear of the paper before landing (the touch is set by eye)
RAMP = 1.5  # mm, distance after touching the paper over which the pen reaches full pressure
DRAW_SPEED = 25  # mm/s
TRAVEL_SPEED = 100  # mm/s
Z_SPEED = 10  # mm/s
MEASURE_SECONDS = 0  # s the nozzle holds still over the cross (offset measured in test 1: 0 = no wait)
CHORD = 0.5  # mm, segment length on circles

LADDER_X = (60.0, 100.0)  # mm, line ends
LADDER_Y0, LADDER_STEP = 175.0, 6.0  # mm, line 1 at the back, the rest towards the front
SQUARE = (110.0, 100.0, 50.0)  # mm, lower-left corner x, y and side
CROSS = (80.0, 115.0)  # mm, commanded nozzle position of the cross's centre
CROSS_ARM = 10.0  # mm
TOUCH_XY = (175.0, 75.0)  # mm, where the pen is set to touch: front-right, clear of the drawing
# (the pen rests on the paper for the rest of the countdown and leaves an ink blot there;
# test 1 had it in the middle of the drawing, 2026-11-18)

BED = 220.0  # mm
PEN_OFFSET_GUESS = (-22.7, -28.6)  # mm, pen relative to the nozzle (measured in test 1, 2026-11-18), preview only


def circle(cx, cy, r, clockwise=False):
    n = max(24, math.ceil(2 * math.pi * r / CHORD))
    sign = -1 if clockwise else 1
    return [(cx + r * math.cos(sign * 2 * math.pi * i / n), cy + r * math.sin(sign * 2 * math.pi * i / n))
            for i in range(n + 1)]


def strokes():
    """(z, points) per pen-down stroke, in drawing order, commanded nozzle coordinates."""
    out = []
    x0, x1 = LADDER_X
    for k, z in enumerate(LADDER_Z, start=1):
        y = LADDER_Y0 - (k - 1) * LADDER_STEP
        for i in range(k):  # k ticks numbering the line, left of it
            tx = x0 - 4.0 - i * 2.0
            out.append((PEN_DOWN_Z, [(tx, y - 2.0), (tx, y + 2.0)]))
        out.append((z, [(x0, y), (x1, y)]))
    sx, sy, side = SQUARE
    corners = [(sx, sy), (sx + side, sy), (sx + side, sy + side), (sx, sy + side), (sx, sy)]
    out.append((PEN_DOWN_Z, corners))
    out.append((PEN_DOWN_Z, [(sx, sy), (sx + side, sy + side)]))
    out.append((PEN_DOWN_Z, [(sx + side, sy), (sx, sy + side)]))
    cx, cy = sx + side / 2, sy + side / 2
    out.append((PEN_DOWN_Z, circle(cx, cy, side / 2)))
    out.append((PEN_DOWN_Z, circle(cx, cy, side / 4, clockwise=True)))
    px, py = CROSS
    out.append((PEN_DOWN_Z, [(px - CROSS_ARM, py), (px + CROSS_ARM, py)]))
    out.append((PEN_DOWN_Z, [(px, py - CROSS_ARM), (px, py + CROSS_ARM)]))
    return out


def ramped(points, z_down):
    """(x, y, z) points of one stroke: lands while moving, lifts while moving.

    The stroke is extended by `lead` before its start and after its end, and Z falls
    linearly from HOVER_Z to z_down over lead + RAMP, timed so it crosses TOUCH_Z exactly
    at the stroke's first point (and rises back the same way at the end)."""
    lead = RAMP * (HOVER_Z - TOUCH_Z) / (TOUCH_Z - z_down)

    def unit(a, b):
        d = math.dist(a, b)
        return ((b[0] - a[0]) / d, (b[1] - a[1]) / d)

    u0, u1 = unit(points[0], points[1]), unit(points[-2], points[-1])
    path = [(points[0][0] - u0[0] * lead, points[0][1] - u0[1] * lead), *points,
            (points[-1][0] + u1[0] * lead, points[-1][1] + u1[1] * lead)]
    cum = [0.0]
    for a, b in zip(path, path[1:]):
        cum.append(cum[-1] + math.dist(a, b))
    total = cum[-1]
    ramp = min(lead + RAMP, total / 2)

    def z_at(dist):
        return HOVER_Z - (HOVER_Z - z_down) * min(1.0, dist / ramp, (total - dist) / ramp)

    out = []  # path vertices plus the two points where the ramps end, in order
    for i, (a, b) in enumerate(zip(path, path[1:])):
        out.append((*a, z_at(cum[i])))
        for mark in sorted({ramp, total - ramp}):
            if cum[i] < mark < cum[i + 1]:
                t = (mark - cum[i]) / (cum[i + 1] - cum[i])
                out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, z_at(mark)))
    out.append((*path[-1], z_at(total)))
    return out


def countdown(seconds, text, step=30):
    lines = []
    left = seconds
    while left > 0:
        lines += [f"M117 {text} {left}s", f"G4 S{min(step, left)}"]
        left -= step
    return lines


def write(path):
    f_draw, f_travel, f_z = DRAW_SPEED * 60, TRAVEL_SPEED * 60, Z_SPEED * 60
    tx, ty = TOUCH_XY
    lines = [
        f"; Aquila pen holder test plot (pen_holder_aquila/scripts/test_plot.py), ramp {RAMP} mm, hover Z {HOVER_Z}",
        "; BEFORE STARTING: paper taped down, pen OUT of the clamp. Never home with the pen in.",
        f"; touch Z {TOUCH_Z}, pen down Z {PEN_DOWN_Z}, pen up Z {PEN_UP_Z}, ladder Z {LADDER_Z}",
        "G21",
        "G90",
        "M104 S0",
        "M140 S0",
        "M107",
        "M84 S0 ; no stepper timeout during the timed waits",
        "M201 X500 Y500 Z100",
        "M203 X500 Y500 Z10",
        "M204 P500 T500",
        "M205 X8.00 Y8.00 Z0.40",
        "M300 S1000 P300",
        "M117 Pen OUT? Homing in 10s",
        "G4 S10",
        "G28",
        "M420 S1 Z0 ; saved CR Touch mesh, no fade (fade would drop it at Z 10)",
        f"G1 Z{TOUCH_Z} F{f_z}",
        f"G1 X{tx:.2f} Y{ty:.2f} F{f_travel}",
        "M300 S1000 P300",
        "M117 Pen in, touch, tighten, press knob",
        "M0 Pen in, touch, tighten, press knob",
        "M300 S1500 P200",
        "M117 Plotting",
        f"G1 Z{PEN_UP_Z} F{f_z}",
    ]
    drawn = travelled = 0.0
    pos = (tx, ty)
    for z, points in strokes():
        stroke = ramped(points, z)
        lines.append(f"G0 X{stroke[0][0]:.3f} Y{stroke[0][1]:.3f} F{f_travel}")
        travelled += math.dist(pos, stroke[0][:2])
        lines.append(f"G1 Z{stroke[0][2]:.3f} F{f_z}")
        for a, b in zip(stroke, stroke[1:]):
            lines.append(f"G1 X{b[0]:.3f} Y{b[1]:.3f} Z{b[2]:.3f} F{f_draw}")
            drawn += math.dist(a[:2], b[:2])
        lines.append(f"G1 Z{PEN_UP_Z} F{f_z}")
        pos = stroke[-1][:2]
    cx, cy = CROSS
    lines += [
        f"G0 X{cx:.3f} Y{cy:.3f} F{f_travel} ; nozzle over the cross's commanded centre",
        "M300 S1000 P300",
        *countdown(MEASURE_SECONDS, "Measure nozzle-cross"),
        "G1 Z40 F600",
        "M84 S120 ; stepper timeout back to the usual 120 s",
        "M84",
        "M117 Pen test done",
    ]
    with open(path, "w", encoding="ascii") as f:
        f.write("\n".join(lines) + "\n")
    minutes = (drawn / DRAW_SPEED + travelled / TRAVEL_SPEED + MEASURE_SECONDS + 10) / 60
    print(f"{path}: {drawn / 1000:.2f} m drawn, ~{minutes:.0f} min plus the pen-in pause")


def preview(path):
    """Where the lines should land on the paper, assuming PEN_OFFSET_GUESS."""
    import matplotlib  # pylint: disable=import-outside-toplevel
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # pylint: disable=import-outside-toplevel

    dx, dy = PEN_OFFSET_GUESS
    fig, ax = plt.subplots(figsize=(7, 7))
    ax.add_patch(plt.Rectangle((0, 0), BED, BED, fill=False, color="grey"))
    for z, points in strokes():
        xs, ys = zip(*points)
        ax.plot([x + dx for x in xs], [y + dy for y in ys], color="tab:blue",
                linewidth=0.6 + 1.2 * (TOUCH_Z - z) / 2.5)
    x0 = LADDER_X[1] + dx + 3
    for k, z in enumerate(LADDER_Z, start=1):
        g = 13 * (TOUCH_Z - z)
        ax.text(x0, LADDER_Y0 - (k - 1) * LADDER_STEP + dy, f"{k}: Z {z} (~{g:.0f} g)", va="center", fontsize=8)
    ax.plot(CROSS[0], CROSS[1], "x", color="tab:red")
    ax.text(CROSS[0] + 2, CROSS[1] + 2, "nozzle parks here", color="tab:red", fontsize=8)
    ax.text(BED / 2, 4, "front of the printer", ha="center", color="grey")
    ax.set_title(f"pen marks with the guessed offset {PEN_OFFSET_GUESS} mm", fontsize=9)
    ax.set_xlim(-5, BED + 5)
    ax.set_ylim(-5, BED + 5)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.savefig(path, dpi=110, bbox_inches="tight")


if __name__ == "__main__":
    args = sys.argv[1:]
    write(args[0] if args else "pen_test_1.gcode")
    if len(args) > 1:
        preview(args[1])
