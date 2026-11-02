import math

from app.doc import curvepath, geom, nurbs
from app.doc.entities import Arc, Circle, Ellipse, Line, LwPolyline, Polyline3d, Spline

TAU = geom.TAU
EPS = geom.EPS
TANGENT_GAP = 1e-12
BIG_DEFAULT = 1e7
MAX_SAMPLES = 2048
HIT_TOL = 1e-8
GL_X = (0.0, 0.5384693101056831, -0.5384693101056831, 0.9061798459386640, -0.9061798459386640)
GL_W = (0.5688888888888889, 0.4786286704993665, 0.4786286704993665, 0.2369268850561891, 0.2369268850561891)

CURVE_KINDS = ("line", "arc", "circle", "ellipse", "lwpolyline", "polyline3d", "spline", "ray", "xline")
OPEN_KINDS = ("line", "arc", "lwpolyline", "polyline3d", "spline", "ellipse")


def _z(p) -> float:
    return float(p[2]) if len(p) > 2 else 0.0


def unit(v):
    n = math.hypot(v[0], v[1])
    if n <= 0.0:
        return (0.0, 0.0)
    return (v[0] / n, v[1] / n)


def _clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


def _gl(fn, a, b, panels):
    h = (b - a) / panels
    total = 0.0
    for k in range(panels):
        mid = a + (k + 0.5) * h
        for x, w in zip(GL_X, GL_W):
            total += w * fn(mid + 0.5 * h * x)
    return total * 0.5 * h


class Segment:
    kind = ""
    sw = 0.0
    ew = 0.0

    def widths_at(self, u0, u1):
        return self.sw + (self.ew - self.sw) * u0, self.sw + (self.ew - self.sw) * u1

    def tan_at(self, u):
        return unit(self.d(u))

    def start(self):
        return self.pt(0.0)

    def end(self):
        return self.pt(1.0)

    def speed_length(self, u0, u1, panels):
        if u0 == u1:
            return 0.0
        return abs(_gl(lambda u: math.hypot(*self.d(u)), u0, u1, panels))

    def sample_pts(self, n):
        return [self.pt(i / n) for i in range(n + 1)]

    def bbox(self):
        pts = self.sample_pts(24)
        return geom.bounds_of_points(pts)


class LineSegment(Segment):
    kind = "line"

    def __init__(self, p0, p1, sw=0.0, ew=0.0):
        self.p0 = [float(p0[0]), float(p0[1]), _z(p0)]
        self.p1 = [float(p1[0]), float(p1[1]), _z(p1)]
        self.dx = self.p1[0] - self.p0[0]
        self.dy = self.p1[1] - self.p0[1]
        self.L = math.hypot(self.dx, self.dy)
        self.sw = sw
        self.ew = ew

    def pt(self, u):
        return [self.p0[0] + u * self.dx, self.p0[1] + u * self.dy, self.p0[2] + u * (self.p1[2] - self.p0[2])]

    def d(self, u):
        return (self.dx, self.dy)

    def length(self, u0=0.0, u1=1.0):
        return abs(u1 - u0) * self.L

    def sub(self, u0, u1):
        a, b = self.widths_at(u0, u1)
        return LineSegment(self.pt(u0), self.pt(u1), a, b)

    def rev(self):
        return LineSegment(self.p1, self.p0, self.ew, self.sw)

    def closest(self, p):
        if self.L <= 0.0:
            return 0.0, self.pt(0.0), geom.dist(self.p0, p)
        u = _clamp(((p[0] - self.p0[0]) * self.dx + (p[1] - self.p0[1]) * self.dy) / (self.L * self.L), 0.0, 1.0)
        q = self.pt(u)
        return u, q, geom.dist(q, p)

    def sample_pts(self, n):
        return [self.pt(0.0), self.pt(1.0)]

    def bbox(self):
        return geom.bounds_of_points([self.p0, self.p1])


class AngularSegment(Segment):
    def fold(self, v, ext, atol):
        sa = self.sa
        if self.full:
            return (v % TAU) / sa
        v = v % TAU
        if v > TAU - atol:
            v -= TAU
        if -atol <= v <= sa + atol:
            return v / sa
        if not ext:
            return None
        ge = v - sa
        gs = TAU - v
        return 1.0 + ge / sa if ge <= gs else -gs / sa

    def wrap(self, u_raw, ext, tol):
        return self.fold(u_raw * self.sa, ext, tol / max(self.scale_len(), tol))


class ArcSegment(AngularSegment):
    kind = "arc"

    def __init__(self, c, r, a0, sweep, sw=0.0, ew=0.0):
        self.c = [float(c[0]), float(c[1]), _z(c)]
        self.r = float(r)
        self.a0 = float(a0)
        self.sweep = float(sweep)
        self.sg = 1.0 if sweep >= 0 else -1.0
        self.sa = abs(sweep)
        self.full = self.sa >= TAU - 1e-12
        self.sw = sw
        self.ew = ew

    def scale_len(self):
        return self.r

    def ang(self, u):
        return self.a0 + self.sweep * u

    def pt(self, u):
        a = self.a0 + self.sweep * u
        return [self.c[0] + self.r * math.cos(a), self.c[1] + self.r * math.sin(a), self.c[2]]

    def d(self, u):
        a = self.a0 + self.sweep * u
        k = self.sweep * self.r
        return (-k * math.sin(a), k * math.cos(a))

    def length(self, u0=0.0, u1=1.0):
        return self.r * self.sa * abs(u1 - u0)

    def sub(self, u0, u1):
        a, b = self.widths_at(u0, u1)
        return ArcSegment(self.c, self.r, self.a0 + self.sweep * u0, self.sweep * (u1 - u0), a, b)

    def rev(self):
        return ArcSegment(self.c, self.r, self.a0 + self.sweep, -self.sweep, self.ew, self.sw)

    def u_of_angle(self, theta, ext, tol):
        return self.fold((theta - self.a0) * self.sg, ext, tol / max(self.r, tol))

    def closest(self, p):
        dx, dy = p[0] - self.c[0], p[1] - self.c[1]
        if math.hypot(dx, dy) <= EPS:
            return 0.0, self.pt(0.0), self.r
        u = self.u_of_angle(math.atan2(dy, dx), False, 1e-12)
        if u is None:
            v = ((math.atan2(dy, dx) - self.a0) * self.sg) % TAU
            u = 1.0 if v - self.sa <= TAU - v else 0.0
        u = _clamp(u, 0.0, 1.0)
        q = self.pt(u)
        return u, q, geom.dist(q, p)

    def sample_pts(self, n):
        n = max(n, int(math.ceil(self.sa / (TAU / 360.0))), 4)
        return [self.pt(i / n) for i in range(n + 1)]

    def bbox(self):
        if self.sweep >= 0:
            return geom.arc_bounds(self.c, self.r, self.a0, self.a0 + self.sweep)
        return geom.arc_bounds(self.c, self.r, self.a0 + self.sweep, self.a0)


class EllipseSegment(AngularSegment):
    kind = "ellipse"

    def __init__(self, c, ux, uy, ratio, t0, sweep):
        self.c = [float(c[0]), float(c[1]), _z(c)]
        self.ux = float(ux)
        self.uy = float(uy)
        self.ratio = float(ratio)
        self.vx = -self.uy * self.ratio
        self.vy = self.ux * self.ratio
        self.t0 = float(t0)
        self.sweep = float(sweep)
        self.sg = 1.0 if sweep >= 0 else -1.0
        self.sa = abs(sweep)
        self.full = self.sa >= TAU - 1e-12

    def scale_len(self):
        return math.hypot(self.ux, self.uy)

    def pt(self, u):
        t = self.t0 + self.sweep * u
        ct, st = math.cos(t), math.sin(t)
        return [self.c[0] + self.ux * ct + self.vx * st, self.c[1] + self.uy * ct + self.vy * st, self.c[2]]

    def d(self, u):
        t = self.t0 + self.sweep * u
        ct, st = math.cos(t), math.sin(t)
        return (self.sweep * (-self.ux * st + self.vx * ct), self.sweep * (-self.uy * st + self.vy * ct))

    def length(self, u0=0.0, u1=1.0):
        return self.speed_length(u0, u1, max(8, int(math.ceil(abs(u1 - u0) * self.sa / (TAU / 32.0)))))

    def sub(self, u0, u1):
        return EllipseSegment(self.c, self.ux, self.uy, self.ratio, self.t0 + self.sweep * u0, self.sweep * (u1 - u0))

    def rev(self):
        return EllipseSegment(self.c, self.ux, self.uy, self.ratio, self.t0 + self.sweep, -self.sweep)

    def u_of_param(self, t, ext, tol):
        return self.fold((t - self.t0) * self.sg, ext, tol / max(self.scale_len(), tol))

    def param_of_point(self, p):
        dx, dy = p[0] - self.c[0], p[1] - self.c[1]
        det = self.ux * self.vy - self.uy * self.vx
        if abs(det) <= 1e-18:
            return 0.0
        a = (dx * self.vy - dy * self.vx) / det
        b = (self.ux * dy - self.uy * dx) / det
        return math.atan2(b, a)

    def closest(self, p):
        n = max(48, int(self.sa / (TAU / 360.0)) + 1)
        best = None
        bu = 0.0
        for i in range(n + 1):
            u = i / n
            q = self.pt(u)
            dd = (q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2
            if best is None or dd < best:
                best, bu = dd, u
        a, b = max(0.0, bu - 1.0 / n), min(1.0, bu + 1.0 / n)
        for _ in range(60):
            m1 = a + (b - a) / 3.0
            m2 = b - (b - a) / 3.0
            if geom.dist(self.pt(m1), p) < geom.dist(self.pt(m2), p):
                b = m2
            else:
                a = m1
        u = (a + b) / 2.0
        q = self.pt(u)
        return u, q, geom.dist(q, p)

    def sample_pts(self, n):
        n = max(n, int(math.ceil(self.sa / (TAU / 720.0))), 8)
        return [self.pt(i / n) for i in range(n + 1)]


class SplineSegment(Segment):
    kind = "spline"

    def __init__(self, curve, t0, t1, closed=False):
        self.c = curve
        self.t0 = float(t0)
        self.t1 = float(t1)
        self.closed = closed

    def t(self, u):
        return self.t0 + (self.t1 - self.t0) * u

    def pt(self, u):
        return nurbs.point_at(self.c, self.t(u))

    def d(self, u):
        tg = nurbs.tangent_at(self.c, self.t(u))
        k = self.t1 - self.t0
        return (tg[0] * k, tg[1] * k)

    def span_count(self):
        lo, hi = min(self.t0, self.t1), max(self.t0, self.t1)
        return max(1, len([k for k in nurbs.spans(self.c) if lo <= k <= hi]) - 1)

    def length(self, u0=0.0, u1=1.0):
        return self.speed_length(u0, u1, max(8, 8 * self.span_count()))

    def sub(self, u0, u1):
        return SplineSegment(self.c, self.t(u0), self.t(u1), False)

    def rev(self):
        return SplineSegment(self.c, self.t1, self.t0, False)

    def closest(self, p):
        n = min(MAX_SAMPLES, max(64, 48 * self.span_count()))
        best = None
        bu = 0.0
        for i in range(n + 1):
            u = i / n
            q = self.pt(u)
            dd = (q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2
            if best is None or dd < best:
                best, bu = dd, u
        a, b = max(0.0, bu - 1.0 / n), min(1.0, bu + 1.0 / n)
        for _ in range(60):
            m1 = a + (b - a) / 3.0
            m2 = b - (b - a) / 3.0
            if geom.dist(self.pt(m1), p) < geom.dist(self.pt(m2), p):
                b = m2
            else:
                a = m1
        u = (a + b) / 2.0
        q = self.pt(u)
        return u, q, geom.dist(q, p)

    def sample_pts(self, n):
        n = min(MAX_SAMPLES, max(n, 32 * self.span_count(), 64))
        return [self.pt(i / n) for i in range(n + 1)]


class CurvePath:
    def __init__(self, segs, closed=False, kind="", elev=0.0):
        self.segs = list(segs)
        self.closed = bool(closed)
        self.kind = kind
        self.elev = elev
        self.lens = [s.length() for s in self.segs]
        self.total = sum(self.lens)

    @property
    def n(self):
        return len(self.segs)

    def locate(self, s):
        n = self.n
        if self.closed:
            if s >= n:
                s = s % n if s > n else float(n)
            elif s < 0:
                s = s % n
        if s <= 0.0:
            return 0, s
        if s >= n:
            return n - 1, s - (n - 1)
        i = min(int(math.floor(s)), n - 1)
        return i, s - i

    def point(self, s):
        i, u = self.locate(s)
        return self.segs[i].pt(u)

    def tangent(self, s):
        i, u = self.locate(s)
        return self.segs[i].tan_at(u)

    def start_point(self):
        return self.segs[0].pt(0.0)

    def end_point(self):
        return self.segs[-1].pt(1.0)

    def length_to(self, s):
        i, u = self.locate(s)
        return sum(self.lens[:i]) + self.segs[i].length(0.0, u) * (1 if u >= 0 else -1)

    def s_at_length(self, target):
        acc = 0.0
        for i, ln in enumerate(self.lens):
            if target <= acc + ln or i == self.n - 1:
                if ln <= 0:
                    return float(i)
                f = (target - acc) / ln
                seg = self.segs[i]
                if seg.kind in ("line", "arc") or abs(f) < 1e-15:
                    return i + f
                lo, hi = 0.0, 1.0
                want = target - acc
                if f > 1.0:
                    return i + f
                for _ in range(80):
                    mid = (lo + hi) / 2.0
                    if seg.length(0.0, mid) < want:
                        lo = mid
                    else:
                        hi = mid
                return i + (lo + hi) / 2.0
            acc += ln
        return float(self.n)

    def closest(self, p):
        best = None
        for i, sg in enumerate(self.segs):
            u, q, dd = sg.closest(p)
            if best is None or dd < best[2] - 1e-15:
                best = (i + u, q, dd)
        return best

    def side_of(self, p):
        s, q, dd = self.closest(p)
        t = self.tangent(s)
        cr = t[0] * (p[1] - q[1]) - t[1] * (p[0] - q[0])
        return s, q, dd, cr

    def slice(self, s0, s1):
        n = self.n
        if s1 < s0:
            if not self.closed:
                s0, s1 = s1, s0
            else:
                s1 += n
        if n == 1 and self.closed and self.segs[0].kind in ("arc", "ellipse") and s1 > 1.0:
            return [self.segs[0].sub(s0, s1)]
        out = []
        k = int(math.floor(s0 + 1e-12))
        while k < s1 - 1e-12:
            seg = self.segs[k % n]
            a = max(s0, k) - k
            b = min(s1, k + 1) - k
            if b - a > 1e-15:
                piece = seg.sub(a, b) if (a > 1e-15 or b < 1.0 - 1e-15) else seg
                if piece.length() > 1e-12:
                    out.append(piece)
            k += 1
        return out

    def sample(self, per_seg=32):
        pts = []
        for sg in self.segs:
            ps = sg.sample_pts(per_seg)
            if pts and geom.dist(pts[-1], ps[0]) <= 1e-12:
                ps = ps[1:]
            pts.extend(ps)
        return pts

    def bbox(self):
        box = None
        for sg in self.segs:
            box = geom.union_bounds(box, sg.bbox())
        return box

    def reversed(self):
        return CurvePath([s.rev() for s in reversed(self.segs)], self.closed, self.kind, self.elev)


def poly_to_segs(verts, closed):
    n = len(verts)
    segs = []
    count = n if closed else n - 1
    for i in range(max(count, 0)):
        a, b = verts[i], verts[(i + 1) % n]
        p0, p1 = a["p"], b["p"]
        sw, ew = float(a.get("sw", 0.0) or 0.0), float(a.get("ew", 0.0) or 0.0)
        bulge = a.get("bulge", 0.0) or 0.0
        if geom.dist(p0, p1) <= 1e-12:
            continue
        arc = geom.bulge_to_arc(p0, p1, bulge)
        if arc is None:
            segs.append(LineSegment(p0, p1, sw, ew))
        else:
            center = arc[0]
            theta = 4.0 * math.atan(bulge)
            segs.append(ArcSegment(center, arc[1], geom.angle_of(center, p0), theta, sw, ew))
    return segs


def path_of(e, big=BIG_DEFAULT):
    k = e.kind
    if k == "line":
        return CurvePath([LineSegment(e.start, e.end)], False, k)
    if k == "arc":
        return CurvePath([ArcSegment(e.center, e.radius, e.start_angle, geom.ccw_sweep(e.start_angle, e.end_angle))], False, k)
    if k == "circle":
        return CurvePath([ArcSegment(e.center, e.radius, 0.0, TAU)], True, k)
    if k == "ellipse":
        full = abs(e.end_param - e.start_param) >= TAU - 1e-12 or abs(geom.ccw_sweep(e.start_param, e.end_param) - TAU) < 1e-12
        sweep = TAU if full else geom.ccw_sweep(e.start_param, e.end_param)
        t0 = 0.0 if full else e.start_param
        return CurvePath([EllipseSegment(e.center, e.major[0], e.major[1], e.ratio, t0, sweep)], full, k)
    if k == "lwpolyline":
        segs = poly_to_segs(e.vertices, e.closed)
        if not segs:
            return None
        return CurvePath(segs, bool(e.closed), k, float(e.elevation))
    if k == "polyline3d":
        pts = e.points
        segs = [LineSegment(pts[i], pts[i + 1]) for i in range(len(pts) - 1) if geom.dist(pts[i], pts[i + 1]) > 1e-12]
        if e.closed and len(pts) > 2 and geom.dist(pts[-1], pts[0]) > 1e-12:
            segs.append(LineSegment(pts[-1], pts[0]))
        return CurvePath(segs, bool(e.closed), k) if segs else None
    if k == "spline" or k == "helix":
        c = curvepath.spline_curve(e) if k == "spline" else e.curve()
        if c is None or not c.valid():
            return None
        lo, hi = c.domain()
        return CurvePath([SplineSegment(c, lo, hi, bool(getattr(e, "closed", False)))], bool(getattr(e, "closed", False)), k)
    if k in ("ray", "xline"):
        d = unit(e.direction)
        if d == (0.0, 0.0):
            return None
        b = e.base
        start = [b[0] - d[0] * big, b[1] - d[1] * big, _z(b)] if k == "xline" else [b[0], b[1], _z(b)]
        return CurvePath([LineSegment(start, [b[0] + d[0] * big, b[1] + d[1] * big, _z(b)])], False, k)
    return None


def line_line(a, b, ea, eb, tol=EPS):
    cross = a.dx * b.dy - a.dy * b.dx
    if abs(cross) <= geom.PARALLEL_EPS * a.L * b.L or a.L <= 0 or b.L <= 0:
        return []
    wx, wy = b.p0[0] - a.p0[0], b.p0[1] - a.p0[1]
    u = (wx * b.dy - wy * b.dx) / cross
    v = (wx * a.dy - wy * a.dx) / cross
    ta, tb = tol / a.L, tol / b.L
    if not ea and not (-ta <= u <= 1.0 + ta):
        return []
    if not eb and not (-tb <= v <= 1.0 + tb):
        return []
    return [(u, v, a.pt(u))]


def _line_circle_points(ln, c, r):
    if ln.L <= 0:
        return []
    ex, ey = ln.dx / ln.L, ln.dy / ln.L
    wx, wy = ln.p0[0] - c[0], ln.p0[1] - c[1]
    bq = wx * ex + wy * ey
    h2 = wx * wx + wy * wy - bq * bq
    disc = r * r - h2
    if disc < -TANGENT_GAP:
        return []
    if disc <= TANGENT_GAP:
        return [-bq]
    w = math.sqrt(disc)
    return [-bq - w, -bq + w]


def line_arc(a, b, ea, eb, tol=EPS):
    out = []
    ta = tol / a.L if a.L > 0 else 0.0
    for t in _line_circle_points(a, b.c, b.r):
        u = t / a.L
        if not ea and not (-ta <= u <= 1.0 + ta):
            continue
        p = a.pt(u)
        v = b.u_of_angle(math.atan2(p[1] - b.c[1], p[0] - b.c[0]), eb, tol)
        if v is None:
            continue
        out.append((u, v, p))
    return out


def arc_arc(a, b, ea, eb, tol=EPS):
    dx, dy = b.c[0] - a.c[0], b.c[1] - a.c[1]
    d = math.hypot(dx, dy)
    if d <= tol:
        return []
    if d > a.r + b.r + tol or d < abs(a.r - b.r) - tol:
        return []
    x = (d * d + a.r * a.r - b.r * b.r) / (2.0 * d)
    h2 = a.r * a.r - x * x
    ex, ey = dx / d, dy / d
    mx, my = a.c[0] + ex * x, a.c[1] + ey * x
    if h2 <= TANGENT_GAP:
        pts = [(mx, my)]
    else:
        h = math.sqrt(h2)
        pts = [(mx - ey * h, my + ex * h), (mx + ey * h, my - ex * h)]
    out = []
    for px, py in pts:
        ua = a.u_of_angle(math.atan2(py - a.c[1], px - a.c[0]), ea, tol)
        ub = b.u_of_angle(math.atan2(py - b.c[1], px - b.c[0]), eb, tol)
        if ua is None or ub is None:
            continue
        out.append((ua, ub, [px, py, a.c[2]]))
    return out


def _ext_range(seg, box):
    if box is None:
        return 0.0, 1.0
    ux, uy = seg.dx / seg.L, seg.dy / seg.L
    ts = []
    for x in (box[0], box[2]):
        for y in (box[1], box[3]):
            ts.append(((x - seg.p0[0]) * ux + (y - seg.p0[1]) * uy) / seg.L)
    pad = 0.01 * (max(ts) - min(ts) + 1.0 / seg.L)
    return min(min(ts) - pad, 0.0), max(max(ts) + pad, 1.0)


def _numeric_samples(seg, ext, other_box):
    k = seg.kind
    if k == "line":
        lo, hi = _ext_range(seg, other_box) if ext else (0.0, 1.0)
        return [(lo, seg.pt(lo)), (hi, seg.pt(hi))]
    if k in ("arc", "ellipse"):
        span = TAU / seg.sa if ext and not seg.full else 1.0
        angle = seg.sa * span
        n = max(16, int(math.ceil(angle / (TAU / (720.0 if k == "ellipse" else 360.0)))))
        return [(span * i / n, seg.pt(span * i / n)) for i in range(n + 1)]
    n = min(MAX_SAMPLES, max(64, 32 * seg.span_count()))
    return [(i / n, seg.pt(i / n)) for i in range(n + 1)]


def _seg_cross(p, q, r, s):
    rx, ry = q[0] - p[0], q[1] - p[1]
    sx, sy = s[0] - r[0], s[1] - r[1]
    den = rx * sy - ry * sx
    if abs(den) < 1e-300:
        return None
    wx, wy = r[0] - p[0], r[1] - p[1]
    t = (wx * sy - wy * sx) / den
    u = (wx * ry - wy * rx) / den
    if -1e-9 <= t <= 1.0 + 1e-9 and -1e-9 <= u <= 1.0 + 1e-9:
        return t, u
    return None


def _poly_crossings(sa, sb):
    out = []
    na, nb = len(sa) - 1, len(sb) - 1
    if na <= 0 or nb <= 0:
        return out
    if na * nb <= 1600:
        for i in range(na):
            for j in range(nb):
                r = _seg_cross(sa[i][1], sa[i + 1][1], sb[j][1], sb[j + 1][1])
                if r:
                    out.append((sa[i][0] + (sa[i + 1][0] - sa[i][0]) * r[0], sb[j][0] + (sb[j + 1][0] - sb[j][0]) * r[1]))
        return out
    xs = [p[1][0] for p in sa] + [p[1][0] for p in sb]
    ys = [p[1][1] for p in sa] + [p[1][1] for p in sb]
    x0, y0 = min(xs), min(ys)
    cell = max(max(xs) - x0, max(ys) - y0, 1e-12) / 48.0
    grid = {}
    for j in range(nb):
        p, q = sb[j][1], sb[j + 1][1]
        for cx in range(int((min(p[0], q[0]) - x0) / cell), int((max(p[0], q[0]) - x0) / cell) + 1):
            for cy in range(int((min(p[1], q[1]) - y0) / cell), int((max(p[1], q[1]) - y0) / cell) + 1):
                grid.setdefault((cx, cy), []).append(j)
    for i in range(na):
        p, q = sa[i][1], sa[i + 1][1]
        seen = set()
        for cx in range(int((min(p[0], q[0]) - x0) / cell), int((max(p[0], q[0]) - x0) / cell) + 1):
            for cy in range(int((min(p[1], q[1]) - y0) / cell), int((max(p[1], q[1]) - y0) / cell) + 1):
                for j in grid.get((cx, cy), ()):
                    if j in seen:
                        continue
                    seen.add(j)
                    r = _seg_cross(p, q, sb[j][1], sb[j + 1][1])
                    if r:
                        out.append((sa[i][0] + (sa[i + 1][0] - sa[i][0]) * r[0], sb[j][0] + (sb[j + 1][0] - sb[j][0]) * r[1]))
    return out


def _refine(a, b, ua, ub, lim_a, lim_b):
    for _ in range(40):
        pa, pb = a.pt(ua), b.pt(ub)
        fx, fy = pa[0] - pb[0], pa[1] - pb[1]
        if math.hypot(fx, fy) <= 1e-13:
            break
        da, db = a.d(ua), b.d(ub)
        det = -da[0] * db[1] + db[0] * da[1]
        if abs(det) < 1e-300:
            break
        dua = (-fx * -db[1] - -db[0] * -fy) / det
        dub = (da[0] * -fy - da[1] * -fx) / det
        ua += dua
        ub += dub
        if lim_a:
            ua = _clamp(ua, lim_a[0], lim_a[1])
        if lim_b:
            ub = _clamp(ub, lim_b[0], lim_b[1])
        if abs(dua) < 1e-15 and abs(dub) < 1e-15:
            break
    pa, pb = a.pt(ua), b.pt(ub)
    return ua, ub, math.hypot(pa[0] - pb[0], pa[1] - pb[1]), [(pa[0] + pb[0]) / 2.0, (pa[1] + pb[1]) / 2.0, pa[2]]


def numeric_hits(a, b, ea, eb, tol=EPS):
    ba, bb = a.bbox(), b.bbox()
    if not ea and not eb and _boxes_apart(ba, bb, 1e-7):
        return []
    sa = _numeric_samples(a, ea, bb)
    sb = _numeric_samples(b, eb, ba)
    seeds = _poly_crossings(sa, sb)
    lim_a = (0.0, 1.0) if a.kind == "spline" else None
    lim_b = (0.0, 1.0) if b.kind == "spline" else None
    out = []
    for ua, ub in seeds:
        ua, ub, err, p = _refine(a, b, ua, ub, lim_a, lim_b)
        if err > HIT_TOL:
            continue
        if a.kind in ("arc", "ellipse"):
            ua = a.wrap(ua, ea, tol)
        elif a.kind == "line" and not ea and not (-tol / max(a.L, tol) <= ua <= 1.0 + tol / max(a.L, tol)):
            ua = None
        if b.kind in ("arc", "ellipse"):
            ub = b.wrap(ub, eb, tol)
        elif b.kind == "line" and not eb and not (-tol / max(b.L, tol) <= ub <= 1.0 + tol / max(b.L, tol)):
            ub = None
        if ua is None or ub is None:
            continue
        if any(math.hypot(p[0] - q[2][0], p[1] - q[2][1]) <= 1e-7 for q in out):
            continue
        out.append((ua, ub, p))
    out.sort(key=lambda h: h[0])
    return out


def seg_hits(a, b, ea=False, eb=False, tol=EPS):
    ka, kb = a.kind, b.kind
    if ka == "line" and kb == "line":
        return line_line(a, b, ea, eb, tol)
    if ka == "line" and kb == "arc":
        return line_arc(a, b, ea, eb, tol)
    if ka == "arc" and kb == "line":
        return [(v, u, p) for u, v, p in line_arc(b, a, eb, ea, tol)]
    if ka == "arc" and kb == "arc":
        return arc_arc(a, b, ea, eb, tol)
    return numeric_hits(a, b, ea, eb, tol)


def boxes_apart(a, b, pad):
    return a is None or b is None or a[2] < b[0] - pad or b[2] < a[0] - pad or a[3] < b[1] - pad or b[3] < a[1] - pad


_boxes_apart = boxes_apart


def path_hits(pa, pb, ea=False, eb=False, tol=EPS, same=False):
    out = []
    na, nb = pa.n, pb.n
    boxes_b = None if eb else [sg.bbox() for sg in pb.segs]
    boxes_a = None if ea else [sg.bbox() for sg in pa.segs]
    for i, sa in enumerate(pa.segs):
        for j, sb in enumerate(pb.segs):
            if same:
                if j <= i + 1:
                    continue
                if pa.closed and i == 0 and j == na - 1:
                    continue
            if boxes_a is not None and boxes_b is not None and _boxes_apart(boxes_a[i], boxes_b[j], tol + 1e-9):
                continue
            first_b = j == 0 and not pb.closed
            last_b = j == nb - 1 and not pb.closed
            ext_b = eb and (nb == 1 or first_b or last_b)
            ext_a = ea and (na == 1 or ((i == 0 or i == na - 1) and not pa.closed))
            for ua, ub, p in seg_hits(sa, sb, ext_a, ext_b, tol):
                if ext_b and nb > 1 and not pb.closed:
                    if first_b and not last_b and ub > 1.0 + 1e-9:
                        continue
                    if last_b and not first_b and ub < -1e-9:
                        continue
                if ext_a and na > 1 and not pa.closed:
                    if i == 0 and i != na - 1 and ua > 1.0 + 1e-9:
                        continue
                    if i == na - 1 and i != 0 and ua < -1e-9:
                        continue
                out.append((i + ua, j + ub, p))
    out.sort(key=lambda h: h[0])
    return out


def dedupe_params(vals, tol):
    out = []
    for v in sorted(vals):
        if not out or abs(v - out[-1]) > tol:
            out.append(v)
    return out


def extension_seg(path, at_end, big=BIG_DEFAULT):
    seg = path.segs[-1] if at_end else path.segs[0].rev()
    k = seg.kind
    if k == "line":
        t = seg.tan_at(1.0)
        e = seg.pt(1.0)
        return LineSegment(e, [e[0] + t[0] * big, e[1] + t[1] * big, e[2]])
    if k == "arc":
        rem = TAU - seg.sa
        if rem <= 1e-9:
            return None
        return ArcSegment(seg.c, seg.r, seg.a0 + seg.sweep, seg.sg * rem)
    if k == "ellipse":
        rem = TAU - seg.sa
        if rem <= 1e-9:
            return None
        return EllipseSegment(seg.c, seg.ux, seg.uy, seg.ratio, seg.t0 + seg.sweep, seg.sg * rem)
    t = seg.tan_at(1.0)
    e = seg.pt(1.0)
    if t == (0.0, 0.0):
        return None
    return LineSegment(e, [e[0] + t[0] * big, e[1] + t[1] * big, e[2]])


def entity_props(src, dst):
    for name in ("layer", "color", "linetype", "lineweight", "ltscale", "transparency", "plot_style", "visible", "thickness", "normal"):
        setattr(dst, name, getattr(src, name))
    dst.annotation_scales = list(src.annotation_scales)
    return dst


def _poly_verts(segs, closed):
    verts = []
    for sg in segs:
        p = sg.pt(0.0)
        if sg.kind == "arc":
            theta = sg.sweep
            bulge = math.tan(theta / 4.0)
        else:
            bulge = 0.0
        verts.append({"p": [p[0], p[1]], "bulge": bulge, "sw": float(sg.sw), "ew": float(sg.ew)})
    if not closed:
        q = segs[-1].pt(1.0)
        verts.append({"p": [q[0], q[1]], "bulge": 0.0, "sw": 0.0, "ew": 0.0})
    return verts


def build_entity(src, segs, closed=False):
    if not segs:
        return None
    k = src.kind
    if len(segs) > 1 and any(s.kind in ("spline", "ellipse") for s in segs):
        curves = [seg_curve(s) for s in segs]
        c = curves[0]
        for nx in curves[1:]:
            c = join_curves(c, nx)
        return entity_props(src, spline_entity(c, False))
    if k in ("lwpolyline",) or (len(segs) > 1 and all(s.kind in ("line", "arc") for s in segs)):
        if not all(s.kind in ("line", "arc") for s in segs):
            return None
        verts = _poly_verts(segs, closed)
        ent = LwPolyline(vertices=verts, closed=bool(closed))
        entity_props(src, ent)
        if isinstance(src, LwPolyline):
            ent.const_width = src.const_width
            ent.elevation = src.elevation
            ent.linetype_gen = src.linetype_gen
        return ent
    if k == "polyline3d":
        pts = [segs[0].pt(0.0)] + [s.pt(1.0) for s in segs]
        if closed:
            pts = pts[:-1]
        ent = Polyline3d(points=[list(p) for p in pts], closed=bool(closed))
        return entity_props(src, ent)
    s = segs[0]
    if s.kind == "line":
        ent = Line(start=list(s.pt(0.0)), end=list(s.pt(1.0)))
    elif s.kind == "arc":
        if s.full and closed:
            ent = Circle(center=list(s.c), radius=s.r)
        else:
            a0, sw = (s.a0, s.sweep) if s.sweep >= 0 else (s.a0 + s.sweep, -s.sweep)
            ent = Arc(center=list(s.c), radius=s.r, start_angle=geom.norm_angle(a0), end_angle=geom.norm_angle(a0 + sw))
    elif s.kind == "ellipse":
        if s.full:
            ent = Ellipse(center=list(s.c), major=[s.ux, s.uy, 0.0], ratio=s.ratio, start_param=0.0, end_param=TAU)
        else:
            t0, sw = (s.t0, s.sweep) if s.sweep >= 0 else (s.t0 + s.sweep, -s.sweep)
            ent = Ellipse(center=list(s.c), major=[s.ux, s.uy, 0.0], ratio=s.ratio, start_param=geom.norm_angle(t0), end_param=geom.norm_angle(t0 + sw))
    else:
        c = spline_piece(s)
        ent = spline_entity(c, closed and s.closed and abs(s.t1 - s.t0) >= (s.c.domain()[1] - s.c.domain()[0]) - 1e-12)
    return entity_props(src, ent)


def spline_entity(c, closed=False):
    return Spline(degree=c.degree, knots=list(c.knots), control_points=[list(map(float, p)) + [0.0] * (3 - len(p)) for p in c.ctrl], weights=list(c.weights) if c.weights else [], fit_points=[], closed=bool(closed and c.closed), fit_method=0)


def spline_piece(s):
    lo, hi = s.c.domain()
    a, b = s.t0, s.t1
    if a <= b:
        if abs(a - lo) <= 1e-12 and abs(b - hi) <= 1e-12 and not s.c.closed:
            return s.c
        return sub_curve(s.c, a, b)
    return reverse_curve(sub_curve(s.c, b, a))


def _hom(c):
    out = []
    for i, p in enumerate(c.ctrl):
        w = c.weights[i] if c.weights else 1.0
        out.append([p[0] * w, p[1] * w, (p[2] if len(p) > 2 else 0.0) * w, w])
    return out


def _unhom(h, degree, knots, closed=False):
    ctrl = []
    weights = []
    rational = any(abs(q[3] - 1.0) > 1e-12 for q in h)
    for q in h:
        w = q[3] if q[3] != 0.0 else 1.0
        ctrl.append([q[0] / w, q[1] / w, q[2] / w])
        weights.append(w)
    return nurbs.Curve(degree, list(knots), ctrl, weights if rational else [], closed)


def knot_mult(U, t, eps=1e-12):
    return sum(1 for k in U if abs(k - t) <= eps)


def insert_knot(c, t):
    p = c.degree
    U = list(c.knots)
    P = _hom(c)
    nc = len(P)
    s = knot_mult(U, t)
    k = nurbs.find_span(nc, p, t, U)
    Q = []
    for i in range(nc + 1):
        if i <= k - p:
            Q.append(list(P[i]))
        elif i <= k - s:
            den = U[i + p] - U[i]
            al = (t - U[i]) / den if den else 0.0
            Q.append([al * P[i][j] + (1.0 - al) * P[i - 1][j] for j in range(4)])
        else:
            Q.append(list(P[i - 1]))
    U.insert(k + 1, t)
    return _unhom(Q, p, U, c.closed)


def sub_curve(c, t0, t1):
    p = c.degree
    lo, hi = c.domain()
    t0 = _clamp(t0, lo, hi)
    t1 = _clamp(t1, lo, hi)
    if t1 <= t0:
        raise ValueError("empty parameter range")
    w = c
    for t in (t0, t1):
        m = knot_mult(w.knots, t)
        while m < p:
            w = insert_knot(w, t)
            m += 1
    U = list(w.knots)
    m0 = knot_mult(U, t0)
    s0 = next(i for i, k in enumerate(U) if abs(k - t0) <= 1e-12)
    s1 = next(i for i, k in enumerate(U) if abs(k - t1) <= 1e-12)
    start = s0 + m0 - p - 1
    end = s1 - 1
    h = _hom(w)
    ctrl = h[start : end + 1]
    inner = [k for k in U if t0 + 1e-12 < k < t1 - 1e-12]
    knots = [t0] * (p + 1) + inner + [t1] * (p + 1)
    if len(knots) != len(ctrl) + p + 1:
        raise ValueError("sub curve extraction failed")
    return _unhom(ctrl, p, knots, False)


def full_clamped(c):
    lo, hi = c.domain()
    if not c.closed and knot_mult(c.knots, lo) > c.degree and knot_mult(c.knots, hi) > c.degree:
        return c
    return sub_curve(c, lo, hi)


def reverse_curve(c):
    lo, hi = c.domain()
    knots = [lo + hi - k for k in reversed(c.knots)]
    return nurbs.Curve(c.degree, knots, [list(p) for p in reversed(c.ctrl)], list(reversed(c.weights)) if c.weights else [], c.closed)


def _elevate_bezier(P, q):
    for _ in range(q):
        p = len(P) - 1
        Q = [list(P[0])]
        for i in range(1, p + 1):
            a = i / (p + 1.0)
            Q.append([a * P[i - 1][j] + (1.0 - a) * P[i][j] for j in range(4)])
        Q.append(list(P[p]))
        P = Q
    return P


def elevate(c, q):
    if q <= c.degree:
        return c
    c = full_clamped(c)
    p = c.degree
    lo, hi = c.domain()
    w = c
    for t in sorted({k for k in c.knots if lo + 1e-12 < k < hi - 1e-12}):
        m = knot_mult(w.knots, t)
        while m < p:
            w = insert_knot(w, t)
            m += 1
    h = _hom(w)
    breaks = sorted({k for k in w.knots if lo + 1e-12 < k < hi - 1e-12})
    nsp = (len(h) - 1) // p
    ctrl = []
    for k in range(nsp):
        seg = _elevate_bezier(h[k * p : (k + 1) * p + 1], q - p)
        ctrl.extend(seg if k == 0 else seg[1:])
    knots = [lo] * (q + 1)
    for b in breaks:
        knots.extend([b] * q)
    knots.extend([hi] * (q + 1))
    return _unhom(ctrl, q, knots, False)


def join_curves(a, b):
    a = full_clamped(a)
    b = full_clamped(b)
    q = max(a.degree, b.degree)
    a = elevate(a, q)
    b = elevate(b, q)
    ha, hb = _hom(a), _hom(b)
    f = ha[-1][3] / hb[0][3] if hb[0][3] else 1.0
    hb = [[x * f for x in row] for row in hb]
    mid = [(ha[-1][j] + hb[0][j]) / 2.0 for j in range(4)]
    ha[-1] = mid
    hb[0] = mid
    shift = a.domain()[1] - b.domain()[0]
    knots = list(a.knots[:-1]) + [k + shift for k in b.knots[q + 1 :]]
    return _unhom(ha + hb[1:], q, knots, False)


def line_curve(p0, p1):
    return nurbs.Curve(1, [0.0, 0.0, 1.0, 1.0], [[p0[0], p0[1], _z(p0)], [p1[0], p1[1], _z(p1)]], [], False)


def conic_curve(c, U, V, t0, sweep):
    n = max(1, int(math.ceil(abs(sweep) / (math.pi / 2.0) - 1e-9)))
    dt = sweep / n
    wm = math.cos(dt / 2.0)
    cz = _z(c)
    ctrl, weights = [], []

    def at(t, k=1.0):
        return [c[0] + k * (U[0] * math.cos(t) + V[0] * math.sin(t)), c[1] + k * (U[1] * math.cos(t) + V[1] * math.sin(t)), cz]

    for i in range(n):
        a = t0 + i * dt
        ctrl.append(at(a))
        weights.append(1.0)
        ctrl.append(at(a + dt / 2.0, 1.0 / wm))
        weights.append(wm)
    ctrl.append(at(t0 + sweep))
    weights.append(1.0)
    knots = [0.0] * 3
    for i in range(1, n):
        knots.extend([float(i), float(i)])
    knots.extend([float(n)] * 3)
    return nurbs.Curve(2, knots, ctrl, weights, False)


def seg_curve(seg):
    k = seg.kind
    if k == "line":
        return line_curve(seg.p0, seg.p1)
    if k == "arc":
        return conic_curve(seg.c, (seg.r, 0.0), (0.0, seg.r), seg.a0, seg.sweep)
    if k == "ellipse":
        return conic_curve(seg.c, (seg.ux, seg.uy), (seg.vx, seg.vy), seg.t0, seg.sweep)
    return spline_piece(seg)


def curve_length(c, t0=None, t1=None):
    lo, hi = c.domain()
    t0 = lo if t0 is None else t0
    t1 = hi if t1 is None else t1
    if t0 == t1:
        return 0.0
    ks = [t0] + [k for k in nurbs.spans(c) if min(t0, t1) < k < max(t0, t1)] + [t1]
    if t0 > t1:
        ks = [t0] + [k for k in sorted((k for k in nurbs.spans(c) if t1 < k < t0), reverse=True)] + [t1]
    total = 0.0
    for a, b in zip(ks, ks[1:]):
        total += abs(_gl(lambda t: math.hypot(*nurbs.tangent_at(c, t)[:2]), a, b, 16))
    return total


def t_at_length(c, t_from, length):
    lo, hi = c.domain()
    forward = length >= 0
    target = abs(length)
    far = hi if forward else lo
    if curve_length(c, t_from, far) <= target:
        return far
    a, b = t_from, far
    for _ in range(70):
        m = (a + b) / 2.0
        if curve_length(c, t_from, m) < target:
            a = m
        else:
            b = m
    return (a + b) / 2.0


def extend_straight(c, at_end, dist):
    c = full_clamped(c)
    if not at_end:
        return reverse_curve(extend_straight(reverse_curve(c), True, dist))
    lo, hi = c.domain()
    t = nurbs.tangent_at(c, hi)
    n = math.hypot(t[0], t[1])
    if n <= 0:
        raise ValueError("no end tangent")
    e = nurbs.point_at(c, hi)
    q = [e[0] + t[0] / n * dist, e[1] + t[1] / n * dist, e[2]]
    return join_curves(c, line_curve(e, q))


def point_in_poly(p, poly):
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i][0], poly[i][1]
        xj, yj = poly[j][0], poly[j][1]
        if (yi > p[1]) != (yj > p[1]) and p[0] < (xj - xi) * (p[1] - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def polyline_path(pts, closed=False):
    segs = [LineSegment(pts[i], pts[i + 1]) for i in range(len(pts) - 1) if geom.dist(pts[i], pts[i + 1]) > 1e-12]
    if closed and len(pts) > 2 and geom.dist(pts[-1], pts[0]) > 1e-12:
        segs.append(LineSegment(pts[-1], pts[0]))
    return CurvePath(segs, closed, "lwpolyline") if segs else None


def crosses_line_chain(path, pts, closed=False):
    chain = polyline_path(pts, closed)
    if chain is None or path is None:
        return False
    box = chain.bbox()
    pb = path.bbox()
    if _boxes_apart(box, pb, 1e-9):
        return False
    return bool(path_hits(path, chain))


def hit_by_polygon(e, poly, kind, tol=EPS):
    if kind == "window":
        b = e.bounds()
        if b is None:
            return False
        return all(point_in_poly([x, y], poly) for x, y in ((b[0], b[1]), (b[2], b[1]), (b[2], b[3]), (b[0], b[3]))) and not crosses_line_chain(path_of_safe(e), poly, True)
    path = path_of_safe(e)
    if path is None:
        b = e.bounds()
        if b is None:
            return False
        corners = [[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]]]
        return any(point_in_poly(c, poly) for c in corners) or crosses_line_chain(polyline_path(corners, True), poly, True) or point_in_poly(poly[0], corners)
    if crosses_line_chain(path, poly, True):
        return True
    return point_in_poly(path.start_point(), poly)


def path_of_safe(e):
    try:
        return path_of(e)
    except Exception:
        return None


def hit_by_fence(e, pts):
    path = path_of_safe(e)
    if path is None:
        return False
    return crosses_line_chain(path, pts, False)


def offset_seg(sg, d):
    if sg.kind == "line":
        if sg.L <= 0:
            return None
        nx, ny = -sg.dy / sg.L, sg.dx / sg.L
        return LineSegment([sg.p0[0] + nx * d, sg.p0[1] + ny * d, sg.p0[2]], [sg.p1[0] + nx * d, sg.p1[1] + ny * d, sg.p1[2]], sg.sw, sg.ew)
    r = sg.r - d * sg.sg
    if r <= 1e-12:
        return None
    return ArcSegment(sg.c, r, sg.a0, sg.sweep, sg.sw, sg.ew)


def _full_geom_hits(a, b):
    return [p for _ua, _ub, p in seg_hits(a, b, True, True)]


def _join_point(a, b, tol):
    ea, sb = a.pt(1.0), b.pt(0.0)
    if geom.dist(ea, sb) <= tol:
        return [(ea[0] + sb[0]) / 2.0, (ea[1] + sb[1]) / 2.0, ea[2]]
    hits = _full_geom_hits(a, b)
    if not hits:
        return None
    return min(hits, key=lambda p: geom.dist(p, ea))


def _retarget(sg, p0, p1):
    if sg.kind == "line":
        return LineSegment(p0, p1, sg.sw, sg.ew)
    a_start = math.atan2(p0[1] - sg.c[1], p0[0] - sg.c[0])
    a_end = math.atan2(p1[1] - sg.c[1], p1[0] - sg.c[0])
    sw = ((a_end - a_start) * sg.sg) % TAU
    if sw <= 1e-12:
        sw = TAU if geom.dist(p0, p1) <= 1e-9 and sg.sa > math.pi else 0.0
    if sw <= 1e-12:
        return None
    if sw > sg.sa + math.pi:
        return None
    return ArcSegment(sg.c, sg.r, a_start, sg.sg * sw, sg.sw, sg.ew)


def offset_path(path, d, tol=EPS):
    if path.n == 1 and path.closed and path.segs[0].kind == "arc":
        o = offset_seg(path.segs[0], d)
        return ([o], True) if o else None
    raw = [offset_seg(sg, d) for sg in path.segs]
    segs = [s for s in raw if s is not None]
    closed = path.closed
    dropped = 0 if len(segs) == path.n else 1
    for _round in range(len(segs) + 1):
        n = len(segs)
        if n == 0 or (closed and n < 2):
            return None
        nj = n if closed else n - 1
        joins = []
        for i in range(nj):
            a, b = segs[i], segs[(i + 1) % n]
            joins.append(_join_point(a, b, tol))
        out = []
        bad = None
        for i, sg in enumerate(segs):
            if closed:
                p0 = joins[i - 1] if joins[i - 1] is not None else sg.pt(0.0)
                p1 = joins[i] if joins[i] is not None else sg.pt(1.0)
            else:
                p0 = joins[i - 1] if i > 0 and joins[i - 1] is not None else sg.pt(0.0)
                p1 = joins[i] if i < n - 1 and joins[i] is not None else sg.pt(1.0)
            if sg.kind == "line":
                if sg.L > 0 and ((p1[0] - p0[0]) * sg.dx + (p1[1] - p0[1]) * sg.dy) <= 1e-15:
                    bad = i
                    break
                if geom.dist(p0, p1) <= 1e-12:
                    bad = i
                    break
            new = _retarget(sg, p0, p1)
            if new is None:
                bad = i
                break
            out.append(new)
        if bad is None:
            result = []
            for i, sg in enumerate(out):
                result.append(sg)
                nxt = out[(i + 1) % len(out)]
                if (closed or i < len(out) - 1) and joins[i] is None:
                    result.append(LineSegment(sg.pt(1.0), nxt.pt(0.0)))
            if closed and dropped:
                old, new = _loop_area(path.segs), _loop_area(result)
                if len(result) < 2 or old * new <= 0.0 or abs(new) <= 1e-9 * abs(old):
                    return None
            return result, closed
        del segs[bad]
        dropped += 1
    return None


def _loop_area(segs) -> float:
    pts = []
    for sg in segs:
        pts.extend(sg.sample_pts(48)[:-1])
    total = 0.0
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        total += a[0] * b[1] - b[0] * a[1]
    return total / 2.0


def tessellate_offset(pts, closed, d):
    n = len(pts)
    out = []
    for i in range(n):
        if closed:
            a, b = pts[(i - 1) % n], pts[(i + 1) % n]
        else:
            a, b = pts[max(i - 1, 0)], pts[min(i + 1, n - 1)]
        tx, ty = unit((b[0] - a[0], b[1] - a[1]))
        out.append([pts[i][0] - ty * d, pts[i][1] + tx * d, _z(pts[i])])
    return out


def thin(pts, limit, closed):
    if len(pts) <= limit:
        return pts
    step = (len(pts) - 1) / float(limit - 1)
    out = [pts[int(round(i * step))] for i in range(limit)]
    if closed and geom.dist(out[0], out[-1]) <= 1e-9:
        out.pop()
    return out


def offset_ellipse_like(seg_path, d, closed):
    seg = seg_path.segs[0]
    pts = seg.sample_pts(max(96, 720))
    if closed:
        pts = pts[:-1]
    moved = tessellate_offset(pts, closed, d)
    keep = []
    for p in moved:
        if not keep or geom.dist(keep[-1], p) > 1e-9:
            keep.append(p)
    return keep


def offset_spline(seg, d, closed):
    pts = seg.sample_pts(256)
    if closed:
        pts = pts[:-1]
    moved = tessellate_offset(pts, closed, d)
    moved = thin(moved, 40, closed)
    curve, _flat = nurbs.fit(moved, nurbs.KNOT_CHORD, closed)
    return curve


def offset_entity(e, dist, side_pt, tol=EPS, big=BIG_DEFAULT):
    k = e.kind
    if k in ("line", "ray", "xline"):
        if k == "line":
            ln = LineSegment(e.start, e.end)
        else:
            dx, dy = unit(e.direction)
            ln = LineSegment(e.base, [e.base[0] + dx, e.base[1] + dy, _z(e.base)])
        if ln.L <= 0:
            return None
        cr = ln.dx * (side_pt[1] - ln.p0[1]) - ln.dy * (side_pt[0] - ln.p0[0])
        sgn = 1.0 if cr >= 0 else -1.0
        nx, ny = -ln.dy / ln.L, ln.dx / ln.L
        c = e.copy_as_new()
        if k == "line":
            c.start = [e.start[0] + nx * dist * sgn, e.start[1] + ny * dist * sgn, _z(e.start)]
            c.end = [e.end[0] + nx * dist * sgn, e.end[1] + ny * dist * sgn, _z(e.end)]
        else:
            c.base = [e.base[0] + nx * dist * sgn, e.base[1] + ny * dist * sgn, _z(e.base)]
        return c
    if k in ("circle", "arc"):
        r = e.radius
        inside = geom.dist(e.center, side_pt) < r
        nr = r - dist if inside else r + dist
        if nr <= 1e-12:
            return None
        c = e.copy_as_new()
        c.radius = nr
        c.thickness = 0.0
        return c
    path = path_of(e, big)
    if path is None:
        return None
    if k == "lwpolyline":
        s, q, dd, cr = path.side_of(side_pt)
        sgn = 1.0 if cr >= 0 else -1.0
        res = offset_path(path, dist * sgn, tol)
        if res is None:
            return None
        segs, closed = res
        return build_entity(e, segs, closed)
    if k == "polyline3d":
        s, q, dd, cr = path.side_of(side_pt)
        sgn = 1.0 if cr >= 0 else -1.0
        res = offset_path(path, dist * sgn, tol)
        if res is None:
            return None
        return build_entity(e, res[0], res[1])
    if k == "ellipse":
        seg = path.segs[0]
        full = path.closed
        s, q, dd, cr = path.side_of(side_pt)
        sgn = 1.0 if cr >= 0 else -1.0
        if full:
            c0 = seg.c
            ux, uy = seg.ux, seg.uy
            rx, ry = side_pt[0] - c0[0], side_pt[1] - c0[1]
            det = ux * seg.vy - uy * seg.vx
            a = (rx * seg.vy - ry * seg.vx) / det
            b = (ux * ry - uy * rx) / det
            outside = a * a + b * b > 1.0
            sgn = -1.0 if outside else 1.0
        pts = offset_ellipse_like(path, dist * sgn, full)
        if len(pts) < 2 or (full and len(pts) < 3):
            return None
        verts = [{"p": [p[0], p[1]], "bulge": 0.0, "sw": 0.0, "ew": 0.0} for p in pts]
        ent = LwPolyline(vertices=verts, closed=full)
        return entity_props(e, ent)
    if k == "spline":
        seg = path.segs[0]
        s, q, dd, cr = path.side_of(side_pt)
        sgn = 1.0 if cr >= 0 else -1.0
        curve = offset_spline(seg, dist * sgn, path.closed)
        ent = spline_entity(curve, path.closed)
        if path.closed:
            ent.closed = True
        return entity_props(e, ent)
    return None


def tessellate_entity(e, per_seg=32):
    p = path_of_safe(e)
    return p.sample(per_seg) if p is not None else []
