import math

import numpy as np

MOTION = ("rapid", "feed", "arc")


def rapid(x, y, z, **opts):
    m = ["rapid", float(x), float(y), float(z)]
    if opts:
        m.append(opts)
    return m


def feed(x, y, z, f, k=None, **opts):
    m = ["feed", float(x), float(y), float(z), float(f)]
    if k:
        opts["k"] = k
    if opts:
        m.append(opts)
    return m


def arc(direction, x, y, z, cx, cy, cz, f, plane="xy", k=None, **opts):
    m = ["arc", direction, float(x), float(y), float(z), float(cx), float(cy), float(cz), float(f), plane]
    if k:
        opts["k"] = k
    if opts:
        m.append(opts)
    return m


def tool_change(number, rpm, name=""):
    return ["tool", int(number), float(rpm), str(name)]


def spindle(rpm, direction="cw"):
    return ["spindle", float(rpm), direction]


def opts_of(m) -> dict:
    return m[-1] if isinstance(m[-1], dict) else {}


def arc_sweep(start, m) -> float:
    plane = m[9]
    ia, ib = {"xy": (0, 1), "zx": (2, 0), "yz": (1, 2)}[plane]
    c = (m[5 + ia], m[5 + ib])
    e = (m[2 + ia], m[2 + ib])
    s = (start[ia], start[ib])
    a0 = math.atan2(s[1] - c[1], s[0] - c[0])
    a1 = math.atan2(e[1] - c[1], e[0] - c[0])
    d = a1 - a0
    if m[1] == "ccw":
        while d <= 1e-12:
            d += 2.0 * math.pi
    else:
        while d >= -1e-12:
            d -= 2.0 * math.pi
    return d


def arc_points(start, m, tol=0.01) -> list:
    plane = m[9]
    ia, ib = {"xy": (0, 1), "zx": (2, 0), "yz": (1, 2)}[plane]
    ic = 3 - ia - ib
    c = (m[5 + ia], m[5 + ib])
    r = math.hypot(start[ia] - c[0], start[ib] - c[1])
    sweep = arc_sweep(start, m)
    if r < 1e-9:
        return [tuple(m[2:5])]
    step = 2.0 * math.acos(max(0.0, 1.0 - tol / r)) if r > tol else math.pi / 2
    n = max(2, int(math.ceil(abs(sweep) / max(step, 1e-3))))
    n = min(n, 2000)
    a0 = math.atan2(start[ib] - c[1], start[ia] - c[0])
    out = []
    for k in range(1, n + 1):
        t = a0 + sweep * k / n
        p = [0.0, 0.0, 0.0]
        p[ia] = c[0] + r * math.cos(t)
        p[ib] = c[1] + r * math.sin(t)
        p[ic] = start[ic] + (m[2 + ic] - start[ic]) * k / n
        out.append(tuple(p))
    out[-1] = tuple(m[2:5])
    return out


def arc_length(start, m) -> float:
    plane = m[9]
    ia, ib = {"xy": (0, 1), "zx": (2, 0), "yz": (1, 2)}[plane]
    ic = 3 - ia - ib
    r = math.hypot(start[ia] - m[5 + ia], start[ib] - m[5 + ib])
    sw = abs(arc_sweep(start, m))
    return math.hypot(r * sw, m[2 + ic] - start[ic])


class Toolpath:
    def __init__(self, moves=None, meta=None):
        self.moves = moves if moves is not None else []
        self.meta = meta if meta is not None else {}

    def append(self, m):
        self.moves.append(m)

    def extend(self, ms):
        self.moves.extend(ms)

    def __len__(self):
        return len(self.moves)

    def walk(self):
        pos = None
        for m in self.moves:
            kind = m[0]
            if kind in MOTION:
                end = tuple(m[1:4]) if kind != "arc" else tuple(m[2:5])
                yield pos, m, end
                pos = end
            else:
                yield pos, m, None
                if kind == "cycle":
                    pos = (m[2], m[3], m[5])

    def bbox(self):
        pts = []
        for start, m, e in self.walk():
            if e is None:
                continue
            if m[0] == "arc" and start is not None:
                pts.extend(arc_points(start, m, 0.05))
            else:
                pts.append(e)
        pts += [(m[2], m[3], m[4]) for m in self.moves if m[0] == "cycle"]
        if not pts:
            return None
        a = np.asarray(pts)
        return [a.min(axis=0).tolist(), a.max(axis=0).tolist()]

    def lengths(self) -> dict:
        cut = rap = 0.0
        for start, m, end in self.walk():
            if end is None or start is None:
                continue
            if m[0] == "rapid":
                rap += math.dist(start, end)
            elif m[0] == "feed":
                cut += math.dist(start, end)
            else:
                cut += arc_length(start, m)
        return {"cut": cut, "rapid": rap}

    def z_min(self):
        zs = [e[2] for _, m, e in self.walk() if e is not None and m[0] != "rapid"]
        zs += [m[4] for m in self.moves if m[0] == "cycle"]
        return min(zs) if zs else None

    def flatten(self, tol=0.01) -> dict:
        rapid_pts, cut_pts = [], []
        for start, m, end in self.walk():
            if end is None or start is None:
                continue
            if m[0] == "rapid":
                rapid_pts.extend([*start, *end])
            elif m[0] == "feed":
                cut_pts.extend([*start, *end])
            else:
                prev = start
                for p in arc_points(start, m, tol):
                    cut_pts.extend([*prev, *p])
                    prev = p
        return {"rapid": [round(v, 4) for v in rapid_pts], "cut": [round(v, 4) for v in cut_pts]}

    def to_json(self) -> list:
        return self.moves

    @staticmethod
    def from_json(data) -> "Toolpath":
        return Toolpath([list(m) for m in data])

    def summary(self, time_s=0.0) -> dict:
        ln = self.lengths()
        bb = self.bbox()
        return {"moves": len(self.moves), "cut_length": round(ln["cut"], 3), "rapid_length": round(ln["rapid"], 3), "time_s": round(time_s, 2), "min": bb[0] if bb else None, "max": bb[1] if bb else None, "z_min": self.z_min()}


DEFAULT_MACHINE = {"rapid": 8000.0, "accel": 800.0, "tool_change_s": 8.0, "spindle_s": 2.0, "arc_junction": True}


def cycle_time(moves, machine=None) -> dict:
    m = dict(DEFAULT_MACHINE)
    m.update(machine or {})
    a = max(float(m["accel"]), 1.0)
    simple = 0.0
    trap = 0.0
    other = 0.0
    segs = []
    pos = None
    for kind_start, mv, end in Toolpath(moves).walk():
        k = mv[0]
        if end is not None:
            if kind_start is None:
                pos = end
                continue
            if k == "rapid":
                f = float(m["rapid"])
                ln = math.dist(kind_start, end)
                tt = None
            elif k == "feed":
                f = mv[4]
                ln = math.dist(kind_start, end)
            else:
                f = mv[8]
                ln = arc_length(kind_start, mv)
            if ln < 1e-9:
                continue
            v = max(f, 1.0) / 60.0
            simple += ln / v
            segs.append((ln, v, kind_start, end, k))
            pos = end
        elif k == "dwell":
            other += float(mv[1])
        elif k == "tool":
            other += float(m["tool_change_s"])
        elif k == "spindle":
            if mv[2] != "off":
                other += float(m["spindle_s"])
        elif k == "cycle":
            depth = max(float(mv[5]) - float(mv[4]), 0.0)
            f = max(float(mv[8]), 1.0) / 60.0
            passes = 1
            if mv[1] in ("peck", "chip") and mv[6] and mv[6] > 0:
                passes = int(math.ceil(depth / mv[6]))
            other += depth / f + (mv[7] or 0.0) + (passes - 1) * 0.3 + 2.0 * depth / (float(m["rapid"]) / 60.0)
    n = len(segs)
    vmax = [s[1] for s in segs]
    vj = [0.0] * (n + 1)
    for i in range(1, n):
        v0 = np.asarray(segs[i - 1][3]) - np.asarray(segs[i - 1][2])
        v1 = np.asarray(segs[i][3]) - np.asarray(segs[i][2])
        n0, n1 = np.linalg.norm(v0), np.linalg.norm(v1)
        if n0 < 1e-12 or n1 < 1e-12:
            vj[i] = 0.0
            continue
        c = float(np.dot(v0, v1) / (n0 * n1))
        vj[i] = min(vmax[i - 1], vmax[i]) * max(c, 0.0)
    for i in range(n):
        ln, v, _, _, _ = segs[i]
        v_in, v_out = min(vj[i], v), min(vj[i + 1], v)
        d_acc = max((v * v - v_in * v_in) / (2.0 * a), 0.0)
        d_dec = max((v * v - v_out * v_out) / (2.0 * a), 0.0)
        if d_acc + d_dec <= ln:
            t = (v - v_in) / a + (v - v_out) / a + (ln - d_acc - d_dec) / v
        else:
            vp = math.sqrt(max((2.0 * a * ln + v_in * v_in + v_out * v_out) / 2.0, 0.0))
            t = (vp - v_in) / a + (vp - v_out) / a
        trap += t
    return {"simple_s": simple + other, "trapezoid_s": trap + other, "other_s": other}
