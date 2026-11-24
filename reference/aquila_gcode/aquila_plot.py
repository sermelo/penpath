"""G-code writer for the Aquila pen plotter: what test 4 proved, as a reusable module.

Coordinates given to `Plot` are where the PEN draws on the bed (mm, X to the right,
Y towards the back, origin at the bed's front-left corner). The module turns them into
nozzle moves with PEN_OFFSET and refuses anything the pen can't reach.

Procedure in every file (settings proven by pen_test_4, 2026-11-18):
- start: pen OUT; beep, 10 s to abort, home (the CR Touch triggers with the nozzle
  ~0.85 mm over the bed: never home with a pen in), load the mesh with no fade;
- each pen (first and every colour change): the pen moves to TOUCH_SPOT at Z TOUCH_Z
  and an M0 pause waits for the knob (sometimes two presses): put the pen in, slide it
  down onto the paper (a scrap of plastic under the tip avoids a dot; pull it out once
  the pen has lifted and started moving), tighten the clamp, press the knob;
- strokes land and lift while moving (no ink dots), pen down PEN_DOWN_Z, up PEN_UP_Z.
"""

import math

PEN_OFFSET = (-22.7, -28.6)  # mm, pen relative to the nozzle (measured in test 1)
NOZZLE_RANGE = ((0.0, 220.0), (0.0, 220.0))  # mm, X and Y the nozzle may be sent to
TOUCH_Z = 10.0  # mm, nozzle height at which each pen is set to just touch the paper
PEN_DOWN_Z = 9.0  # mm, 1 mm into the ~13 g/mm flexure (~13 g)
PEN_UP_Z = 12.5  # mm, travel height, pen ~2.5 mm over the paper
HOVER_Z = 10.5  # mm, pen just clear of the paper before landing
RAMP = 1.5  # mm, distance after touching the paper over which the pen reaches full pressure
DRAW_SPEED = 25  # mm/s
TRAVEL_SPEED = 100  # mm/s
Z_SPEED = 10  # mm/s
END_Z = 80.0  # mm, nozzle height at the end: pen ~70 mm over the paper
END_XY = (0.0, 220.0)  # nozzle at the end: head far left (off the paper), bed fully forward
TOUCH_SPOT = (190.0, 12.0)  # mm (pen), where each pen is set: near the paper's front-right corner


def pen_reach():
    """((xmin, xmax), (ymin, ymax)) the pen can draw, clipped to the 220 x 220 bed."""
    return tuple((max(0.0, lo + off), min(220.0, hi + off)) for (lo, hi), off in zip(NOZZLE_RANGE, PEN_OFFSET))


class Plot:
    def __init__(self, title, touch_spot=TOUCH_SPOT):
        self.title = title
        self.touch_spot = touch_spot
        self.lines = []
        self.pos = None  # pen position, mm
        self.drawn = self.travelled = 0.0
        self.pens = []

    def _nozzle(self, x, y):
        (xmin, xmax), (ymin, ymax) = pen_reach()
        if not (xmin - 1e-6 <= x <= xmax + 1e-6 and ymin - 1e-6 <= y <= ymax + 1e-6):
            raise ValueError(f"pen point ({x:.1f}, {y:.1f}) outside the reachable area {pen_reach()}")
        return x - PEN_OFFSET[0], y - PEN_OFFSET[1]

    def _move(self, x, y, z=None, feed=None):
        nx, ny = self._nozzle(x, y)
        z_part = f" Z{z:.3f}" if z is not None else ""
        self.lines.append(f"G1 X{nx:.3f} Y{ny:.3f}{z_part} F{feed}")

    def start(self, first_pen):
        f_z = Z_SPEED * 60
        self.lines += [
            f"; {self.title} (pen_holder_aquila/scripts/aquila_plot.py)",
            "; BEFORE STARTING: paper held down, pen OUT of the clamp. Never home with a pen in.",
            f"; touch Z {TOUCH_Z}, pen down Z {PEN_DOWN_Z}, up Z {PEN_UP_Z}, offset {PEN_OFFSET}",
            "G21", "G90", "M104 S0", "M140 S0", "M107",
            "M84 S0 ; no stepper timeout during the pauses",
            "M201 X500 Y500 Z100", "M203 X500 Y500 Z10", "M204 P500 T500", "M205 X8.00 Y8.00 Z0.40",
            "M300 S1000 P300", "M117 Pen OUT? Homing in 10s", "G4 S10",
            "G28",
            "M420 S1 Z0 ; saved CR Touch mesh, no fade",
            f"G1 Z{PEN_UP_Z} F{f_z}",
        ]
        self.pen(first_pen)

    def pen(self, name):
        """Pause at the touch spot for the next pen (first pen or a colour change)."""
        self.pens.append(name)
        f_z, f_travel = Z_SPEED * 60, TRAVEL_SPEED * 60
        self.lines.append(f"; ---- pen {len(self.pens)}: {name} ----")
        self.lines.append(f"G1 Z{PEN_UP_Z} F{f_z}")
        self._move(*self.touch_spot, feed=f_travel)
        self.lines += [
            f"G1 Z{TOUCH_Z} F{f_z}",
            "M300 S1000 P300",
            f"M117 Pen {len(self.pens)}: {name}, touch, knob",
            f"M0 Pen {len(self.pens)}: {name}. Touch paper, tighten, press knob",
            "M300 S1500 P200",
            f"M117 Plotting {name}",
            f"G1 Z{PEN_UP_Z} F{f_z}",
        ]
        self.pos = self.touch_spot

    def stroke(self, points, z_down=PEN_DOWN_Z):
        """One pen-down polyline [(x, y), ...] in pen coordinates; lands and lifts while moving."""
        points = [p for i, p in enumerate(points) if i == 0 or math.dist(p, points[i - 1]) > 1e-6]
        if len(points) < 2:
            return
        f_draw, f_travel, f_z = DRAW_SPEED * 60, TRAVEL_SPEED * 60, Z_SPEED * 60
        path = ramped(points, z_down)
        self._move(*path[0][:2], feed=f_travel)
        self.travelled += math.dist(self.pos, path[0][:2])
        self.lines.append(f"G1 Z{path[0][2]:.3f} F{f_z}")
        for a, b in zip(path, path[1:]):
            self._move(b[0], b[1], b[2], f_draw)
            self.drawn += math.dist(a[:2], b[:2])
        self.lines.append(f"G1 Z{PEN_UP_Z} F{f_z}")
        self.pos = path[-1][:2]

    def end(self):
        self.lines += [
            f"G1 Z{END_Z} F{Z_SPEED * 60}",
            f"G1 X{END_XY[0]} Y{END_XY[1]} F{TRAVEL_SPEED * 60} ; head left, bed forward: paper free to take out",
            "M300 S1500 P150", "G4 P200", "M300 S1500 P150",
            "M84 S120 ; stepper timeout back to the usual 120 s",
            "M84",
            "M117 Plot done",
        ]

    def save(self, path):
        with open(path, "w", encoding="ascii") as f:
            f.write("\n".join(self.lines) + "\n")
        minutes = (self.drawn / DRAW_SPEED + self.travelled / TRAVEL_SPEED) / 60
        return f"{path}: {len(self.pens)} pen(s), {self.drawn / 1000:.2f} m drawn, ~{minutes:.0f} min plus pauses"


def ramped(points, z_down):
    """(x, y, z) points of one stroke, extended by a lead-in and lead-out.

    Z falls linearly from HOVER_Z to z_down over lead + RAMP, timed so it crosses TOUCH_Z
    exactly at the stroke's first point, and rises the same way at the end."""
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

    out = []
    for i, (a, b) in enumerate(zip(path, path[1:])):
        out.append((*a, z_at(cum[i])))
        for mark in sorted({ramp, total - ramp}):
            if cum[i] < mark < cum[i + 1]:
                t = (mark - cum[i]) / (cum[i + 1] - cum[i])
                out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, z_at(mark)))
    out.append((*path[-1], z_at(total)))
    return out
