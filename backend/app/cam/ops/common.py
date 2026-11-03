import math

import numpy as np

from app.cam import geom, limits
from app.cam import toolpath as T
from app.cam.limits import CamError


def levels(top: float, bottom: float, step: float) -> list:
    depth = top - bottom
    if depth <= 1e-9:
        raise CamError("The bottom must be below the top of the cut.")
    n = max(1, int(math.ceil(depth / max(step, 1e-3) - 1e-9)))
    limits.need(n, "passes", "Depth levels")
    return [top - depth * (i + 1) / n for i in range(n)]


def start_moves(ctx, f: dict) -> list:
    t = ctx.tool
    return [["comment", "%s T%d %s" % (ctx.op.get("label") or ctx.op["type"], t.number, t.name)], T.tool_change(t.number, f["rpm"], t.name), T.spindle(f["rpm"], "cw")]


class Pen:
    def __init__(self, ctx, moves: list):
        self.ctx = ctx
        self.m = moves
        self.pos = None

    def rapid(self, x, y, z, **o):
        self.m.append(T.rapid(x, y, z, **o))
        self.pos = (x, y, z)

    def feed(self, x, y, z, f, k=None):
        self.m.append(T.feed(x, y, z, f, k))
        self.pos = (x, y, z)

    def arc(self, direction, x, y, z, cx, cy, cz, f, k=None):
        self.m.append(T.arc(direction, x, y, z, cx, cy, cz, f, "xy", k))
        self.pos = (x, y, z)

    def to_clearance(self):
        h = self.ctx.h
        if self.pos is not None and self.pos[2] < h.clearance - 1e-9:
            self.rapid(self.pos[0], self.pos[1], h.clearance, k="retract")

    def over(self, x, y, z=None):
        h = self.ctx.h
        z = h.retract if z is None else z
        if self.pos is None:
            self.rapid(x, y, h.clearance, k="approach")
        elif self.pos[2] < z - 1e-9:
            self.rapid(self.pos[0], self.pos[1], z, k="retract")
        self.rapid(x, y, z, k="approach")

    def finish(self):
        self.to_clearance()


def ring_points(ring, closed=True):
    pts = [tuple(p) for p in ring]
    if closed:
        pts.append(pts[0])
    return pts


def ramp_along(pen, pts, z_from, z_to, f_ramp, f_cut, angle_deg):
    depth = z_from - z_to
    if depth <= 1e-9:
        return
    need = depth / max(math.tan(math.radians(angle_deg)), 1e-3)
    seg = np.asarray(pts, dtype=float)
    d = np.hypot(*np.diff(seg, axis=0).T)
    total = float(d.sum())
    if total < 1e-6:
        pen.feed(pts[0][0], pts[0][1], z_to, f_ramp, "ramp")
        return
    limits.need(int(need / total) + 1, "passes", "Ramp turns")
    done = 0.0
    k = 0
    last = (len(d), 0.0)
    while done < need - 1e-9:
        i = k % len(d)
        ln = float(d[i])
        step = min(ln, need - done)
        frac = step / ln if ln > 0 else 1.0
        done += step
        a, b = seg[i], seg[i + 1]
        pen.feed(a[0] + (b[0] - a[0]) * frac, a[1] + (b[1] - a[1]) * frac, z_from - depth * (done / need), f_ramp, "ramp")
        last = (i, frac)
        k += 1
    i, frac = last
    if frac < 1.0:
        pen.feed(seg[i + 1][0], seg[i + 1][1], z_to, f_cut, "cut")
    for j in range(i + 2, len(seg)):
        pen.feed(seg[j][0], seg[j][1], z_to, f_cut, "cut")


def helix_at(pen, cx, cy, radius, z_from, z_to, f_ramp, angle_deg, start_angle=0.0):
    depth = z_from - z_to
    circ = 2.0 * math.pi * radius
    turns = max(1, int(math.ceil(depth / (circ * max(math.tan(math.radians(angle_deg)), 1e-3)) - 1e-9)))
    limits.need(turns, "passes", "Helix turns")
    a0 = start_angle
    sx, sy = cx + radius * math.cos(a0), cy + radius * math.sin(a0)
    ox, oy = cx + radius * math.cos(a0 + math.pi), cy + radius * math.sin(a0 + math.pi)
    if not (at_xy(pen, sx, sy) and abs(pen.pos[2] - z_from) < 1e-9):
        pen.feed(sx, sy, z_from, f_ramp, "ramp")
    n_half = 2 * turns
    for i in range(n_half):
        z = z_from - depth * (i + 1) / n_half
        if i % 2 == 0:
            pen.arc("ccw", ox, oy, z, cx, cy, z, f_ramp, "ramp")
        else:
            pen.arc("ccw", sx, sy, z, cx, cy, z, f_ramp, "ramp")
    pen.arc("ccw", ox, oy, z_to, cx, cy, z_to, f_ramp, "ramp")
    pen.arc("ccw", sx, sy, z_to, cx, cy, z_to, f_ramp, "ramp")


def helix_fits(region_c, x, y, radius) -> bool:
    for k in range(12):
        a = 2.0 * math.pi * k / 12
        if not geom.inside((x + radius * math.cos(a), y + radius * math.sin(a)), region_c):
            return False
    return geom.inside((x, y), region_c)


def segment_inside(region_rings, a, b, step=0.5) -> bool:
    ln = math.dist(a, b)
    n = max(2, int(ln / step) + 1)
    for i in range(n + 1):
        t = i / n
        if not geom.inside((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t), region_rings):
            return False
    return True


def at_xy(pen, x, y) -> bool:
    return pen.pos is not None and abs(pen.pos[0] - x) < 1e-6 and abs(pen.pos[1] - y) < 1e-6


def entry_at(ctx, pen, ring_pts, locus, z_from, z_to, f, entry: str, helix_dia: float, ramp_angle: float):
    t = ctx.tool
    x0, y0 = ring_pts[0]
    if entry == "plunge":
        pen.feed(x0, y0, z_to, f["vf_plunge"], "plunge")
        return
    if entry == "helix":
        hr = max((helix_dia - t.diameter) / 2.0, 0.05)
        for k in range(8):
            a = 2.0 * math.pi * k / 8
            cx, cy = x0 - hr * math.cos(a), y0 - hr * math.sin(a)
            if helix_fits(locus, cx, cy, hr):
                sx, sy = cx + hr * math.cos(a), cy + hr * math.sin(a)
                if not at_xy(pen, sx, sy):
                    pen.feed(sx, sy, z_from, f["vf_cut"], "link")
                helix_at(pen, cx, cy, hr, z_from, z_to, f["vf_ramp"], ramp_angle, a)
                return
        ctx.warn("A helical entry did not fit; a ramp along the path was used.")
    ramp_along(pen, ring_pts, z_from, z_to, f["vf_ramp"], f["vf_cut"], ramp_angle)


def circle3(a, b, c):
    ax, ay = a
    bx, by = b
    cx, cy = c
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    return ux, uy, math.hypot(ax - ux, ay - uy)


def arc_run(pts, i, tol, max_radius=1500.0):
    n = len(pts)
    best = None
    j = i + 3
    while j < n:
        seg = np.asarray(pts[i : j + 1], dtype=float)
        mid = pts[(i + j) // 2]
        c = circle3(pts[i], mid, pts[j])
        if c is None or c[2] > max_radius or c[2] < 0.02:
            break
        turn = (mid[0] - pts[i][0]) * (pts[j][1] - mid[1]) - (mid[1] - pts[i][1]) * (pts[j][0] - mid[0])
        if abs(turn) < 1e-9:
            break
        dev = np.abs(np.hypot(seg[:, 0] - c[0], seg[:, 1] - c[1]) - c[2]).max()
        if dev > tol:
            break
        v = np.diff(seg, axis=0)
        cr = v[:-1, 0] * v[1:, 1] - v[:-1, 1] * v[1:, 0]
        if np.any(cr * turn < -1e-9):
            break
        best = (j, c, 1 if turn > 0 else -1)
        j += 1
    return best


def cut_polyline(pen, pts, z, f_cut, k="cut", arc_tol=0.01):
    n = len(pts)
    i = 0
    while i < n - 1:
        run = arc_run(pts, i, arc_tol) if arc_tol and n - i >= 4 else None
        if run is not None and run[0] - i >= 3:
            j, c, turn = run
            pen.arc("ccw" if turn > 0 else "cw", pts[j][0], pts[j][1], z, c[0], c[1], z, f_cut, k)
            i = j
        else:
            pen.feed(pts[i + 1][0], pts[i + 1][1], z, f_cut, k)
            i += 1


def order_rings(rings, start):
    left = [list(r) for r in rings]
    out = []
    cur = start
    while left:
        best, bi, bd = None, 0, float("inf")
        for i, r in enumerate(left):
            a = np.asarray(r, dtype=float)
            d = float(np.hypot(a[:, 0] - cur[0], a[:, 1] - cur[1]).min())
            if d < bd:
                bd, bi = d, i
        ring = geom.rotate_to(left.pop(bi), cur)
        out.append(ring)
        cur = ring[0]
    return out


