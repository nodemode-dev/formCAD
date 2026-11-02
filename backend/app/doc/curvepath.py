import bisect
import math

from app.doc import geom, nurbs

TABLE_STEPS = 2048
MAX_LEN = 1e12


class Seg:
    def __init__(self, length, fn, tan):
        self.length = length
        self.fn = fn
        self.tan = tan


def _line_seg(p0, p1):
    d = geom.dist(p0, p1)
    ang = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
    z0 = p0[2] if len(p0) > 2 else 0.0
    z1 = p1[2] if len(p1) > 2 else 0.0

    def fn(s):
        t = s / d if d else 0.0
        return [p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t, z0 + (z1 - z0) * t]

    return Seg(d, fn, lambda s: ang)


def _arc_seg(center, r, a0, sweep):
    length = abs(sweep) * r
    sgn = 1.0 if sweep >= 0 else -1.0

    def fn(s):
        a = a0 + sgn * s / r
        return [center[0] + r * math.cos(a), center[1] + r * math.sin(a), 0.0]

    def tan(s):
        return a0 + sgn * s / r + sgn * math.pi / 2.0

    return Seg(length, fn, tan)


def _param_seg(f, t0, t1, steps=TABLE_STEPS):
    ts = [t0 + (t1 - t0) * i / steps for i in range(steps + 1)]
    pts = [f(t) for t in ts]
    acc = [0.0]
    for a, b in zip(pts, pts[1:]):
        acc.append(acc[-1] + math.dist(a, b))

    def param_at(s):
        s = min(max(s, 0.0), acc[-1])
        i = bisect.bisect_right(acc, s) - 1
        i = min(max(i, 0), steps - 1)
        span = acc[i + 1] - acc[i]
        w = (s - acc[i]) / span if span > 0 else 0.0
        return ts[i] + (ts[i + 1] - ts[i]) * w

    def fn(s):
        return f(param_at(s))

    def tan(s):
        t = param_at(s)
        h = (t1 - t0) / (steps * 8.0)
        a, b = f(max(t0, t - h)), f(min(t1, t + h))
        return math.atan2(b[1] - a[1], b[0] - a[0])

    return Seg(acc[-1], fn, tan)


class Path:
    def __init__(self, segs, closed):
        self.segs = [s for s in segs if s.length > 0]
        self.closed = closed
        self.length = sum(s.length for s in self.segs)
        self.starts = []
        pos = 0.0
        for s in self.segs:
            self.starts.append(pos)
            pos += s.length

    def _find(self, s):
        s = min(max(s, 0.0), self.length)
        i = bisect.bisect_right(self.starts, s) - 1
        i = min(max(i, 0), len(self.segs) - 1)
        return self.segs[i], s - self.starts[i]

    def at(self, s):
        seg, local = self._find(s)
        return seg.fn(local), seg.tan(local)

    def locate(self, pt, steps=4000) -> float:
        best, bs = None, 0.0
        n = max(steps, 8)
        for i in range(n + 1):
            s = self.length * i / n
            p = self._find(s)[0].fn(self._find(s)[1])
            d = math.hypot(p[0] - pt[0], p[1] - pt[1])
            if best is None or d < best:
                best, bs = d, s
        h = self.length / n
        a, b = max(0.0, bs - h), min(self.length, bs + h)
        for _ in range(50):
            m1 = a + (b - a) / 3.0
            m2 = b - (b - a) / 3.0
            q1 = self.at(m1)[0]
            q2 = self.at(m2)[0]
            if math.hypot(q1[0] - pt[0], q1[1] - pt[1]) < math.hypot(q2[0] - pt[0], q2[1] - pt[1]):
                b = m2
            else:
                a = m1
        return (a + b) / 2.0


KINDS = ("line", "arc", "circle", "ellipse", "lwpolyline", "polyline3d", "spline", "helix")


def poly_segs(verts, closed):
    n = len(verts)
    segs = []
    count = n if closed else n - 1
    for i in range(max(count, 0)):
        a, b = verts[i]["p"], verts[(i + 1) % n]["p"]
        bulge = verts[i].get("bulge", 0.0) or 0.0
        arc = geom.bulge_to_arc(a, b, bulge)
        if arc is None:
            segs.append(_line_seg(a, b))
        else:
            center, r, a0, a1, ccw = arc
            theta = 4.0 * math.atan(bulge)
            start = geom.angle_of(center, a)
            segs.append(_arc_seg(center, r, start, theta))
    return segs


def spline_curve(e):
    c = nurbs.Curve(int(e.degree), [float(k) for k in e.knots], [list(p) for p in e.control_points], [float(w) for w in e.weights] if e.weights else [], bool(e.closed))
    if not c.valid():
        fit = e.fit_points
        if fit and len(fit) >= 2:
            c, _flat = nurbs.fit(fit, nurbs.KNOT_CHORD, bool(e.closed))
        else:
            return None
    return c


def build(e):
    k = e.kind
    if k == "line":
        return Path([_line_seg(e.start, e.end)], False)
    if k == "arc":
        sweep = geom.ccw_sweep(e.start_angle, e.end_angle)
        return Path([_arc_seg(e.center, e.radius, e.start_angle, sweep)], False)
    if k == "circle":
        return Path([_arc_seg(e.center, e.radius, 0.0, geom.TAU)], True)
    if k == "ellipse":
        full = abs(e.end_param - e.start_param) >= geom.TAU - 1e-12 or abs(geom.ccw_sweep(e.start_param, e.end_param) - geom.TAU) < 1e-12
        sweep = geom.TAU if full else geom.ccw_sweep(e.start_param, e.end_param)
        ux, uy = e.major[0], e.major[1]
        vx, vy = -uy * e.ratio, ux * e.ratio

        def f(t):
            return [e.center[0] + ux * math.cos(t) + vx * math.sin(t), e.center[1] + uy * math.cos(t) + vy * math.sin(t), 0.0]

        return Path([_param_seg(f, e.start_param, e.start_param + sweep)], full)
    if k == "lwpolyline":
        return Path(poly_segs(e.vertices, e.closed), bool(e.closed))
    if k == "polyline3d":
        pts = e.points
        segs = [_line_seg(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
        if e.closed and len(pts) > 2:
            segs.append(_line_seg(pts[-1], pts[0]))
        return Path(segs, bool(e.closed))
    if k in ("spline", "helix"):
        c = spline_curve(e) if k == "spline" else e.curve()
        if c is None or not c.valid():
            return None
        lo, hi = c.domain()
        steps = max(TABLE_STEPS, 64 * len(nurbs.spans(c)))
        return Path([_param_seg(lambda t: nurbs.point_at(c, t), lo, hi, min(steps, 20000))], bool(getattr(e, "closed", False)))
    return None
