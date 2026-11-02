import math

from app.doc import geom

TAU = geom.TAU
ELLIPSE_STEP = 0.04
INFINITE_REACH = 10.0


class Prim:
    __slots__ = ("kind", "a", "b", "c", "r", "a0", "sw", "src", "pid", "slack", "box", "rev")

    def __init__(self, kind, src=None, pid=0, slack=0.0):
        self.kind = kind
        self.rev = False
        self.a = self.b = self.c = None
        self.r = self.a0 = self.sw = 0.0
        self.src = src
        self.pid = pid
        self.slack = slack
        self.box = None

    def length(self):
        if self.kind == "line":
            return math.hypot(self.b[0] - self.a[0], self.b[1] - self.a[1])
        return self.r * self.sw

    def at(self, t):
        if self.kind == "line":
            return (self.a[0] + (self.b[0] - self.a[0]) * t, self.a[1] + (self.b[1] - self.a[1]) * t)
        ang = self.a0 + t
        return (self.c[0] + self.r * math.cos(ang), self.c[1] + self.r * math.sin(ang))

    def span(self):
        return 1.0 if self.kind == "line" else self.sw

    def scale_t(self, tol):
        n = self.length()
        if n <= 1e-300:
            return tol
        return tol / n if self.kind == "line" else tol / self.r


def line_prim(p, q, src=None, pid=0, slack=0.0):
    pr = Prim("line", src, pid, slack)
    pr.a = (float(p[0]), float(p[1]))
    pr.b = (float(q[0]), float(q[1]))
    pr.box = (min(pr.a[0], pr.b[0]), min(pr.a[1], pr.b[1]), max(pr.a[0], pr.b[0]), max(pr.a[1], pr.b[1]))
    return pr


def arc_prim(c, r, a0, sw, src=None, pid=0):
    pr = Prim("arc", src, pid)
    pr.c = (float(c[0]), float(c[1]))
    pr.r = float(r)
    pr.a0 = geom.norm_angle(a0)
    pr.sw = min(float(sw), TAU)
    if pr.sw >= TAU - 1e-12:
        x0, y0, x1, y1 = pr.c[0] - pr.r, pr.c[1] - pr.r, pr.c[0] + pr.r, pr.c[1] + pr.r
    else:
        x0, y0, x1, y1 = geom.arc_bounds(pr.c, pr.r, pr.a0, pr.a0 + pr.sw)
    pr.box = (x0, y0, x1, y1)
    return pr


def segment_prim(p0, p1, bulge, src, pid):
    arc = geom.bulge_to_arc([p0[0], p0[1], 0.0], [p1[0], p1[1], 0.0], bulge) if bulge else None
    if arc is None:
        return line_prim(p0, p1, src, pid)
    center, r, a_start, a_end, ccw = arc
    pr = arc_prim(center, r, a_start, geom.ccw_sweep(a_start, a_end) or TAU, src, pid)
    pr.rev = not ccw
    return pr


def polyline_prims(verts, closed, src, pid):
    out = []
    n = len(verts)
    count = n if closed else n - 1
    for i in range(max(count, 0)):
        a = verts[i]
        b = verts[(i + 1) % n]
        p0, p1 = a["p"], b["p"]
        if math.hypot(p1[0] - p0[0], p1[1] - p0[1]) < 1e-12:
            continue
        out.append(segment_prim(p0, p1, float(a.get("bulge", 0.0) or 0.0), src, pid))
    return out


def chain_prims(points, closed, src, pid, slack):
    out = []
    n = len(points)
    count = n if closed else n - 1
    for i in range(max(count, 0)):
        p0, p1 = points[i], points[(i + 1) % n]
        if math.hypot(p1[0] - p0[0], p1[1] - p0[1]) > 1e-12:
            out.append(line_prim(p0, p1, src, pid, slack))
    return out


def ellipse_points(e):
    full = abs(e.end_param - e.start_param) >= TAU - 1e-12 or abs(geom.ccw_sweep(e.start_param, e.end_param) - TAU) < 1e-12 or abs(geom.ccw_sweep(e.start_param, e.end_param)) < 1e-12
    sweep = TAU if full else geom.ccw_sweep(e.start_param, e.end_param)
    n = max(24, int(math.ceil(sweep / ELLIPSE_STEP)))
    ux, uy = e.major[0], e.major[1]
    vx, vy = -uy * e.ratio, ux * e.ratio
    pts = []
    for i in range(n + 1):
        t = e.start_param + sweep * i / n
        pts.append((e.center[0] + ux * math.cos(t) + vx * math.sin(t), e.center[1] + uy * math.cos(t) + vy * math.sin(t)))
    if full:
        pts[-1] = pts[0]
    major = math.hypot(ux, uy)
    return pts, full, major * (1.0 - math.cos(ELLIPSE_STEP / 2.0)) * 1.2


def spline_points(e):
    from app.doc import curvepath, nurbs

    c = curvepath.spline_curve(e)
    if c is None or not c.valid():
        return None
    pts = [(p[0], p[1]) for p in nurbs.sample(c, 32)]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    diag = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
    closed = bool(e.closed) or math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 1e-9 * max(diag, 1.0)
    if closed:
        pts[-1] = pts[0]
    return pts, closed, diag * 2e-4


def reach_of(boxes):
    if not boxes:
        return 1000.0
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[2] for b in boxes)
    y1 = max(b[3] for b in boxes)
    return max(math.hypot(x1 - x0, y1 - y0), 1.0) * INFINITE_REACH


def prims_of(e, reach=1000.0):
    k = e.kind
    h = e.handle
    if k == "line":
        if math.hypot(e.end[0] - e.start[0], e.end[1] - e.start[1]) < 1e-12:
            return []
        return [line_prim(e.start, e.end, h, 0)]
    if k == "circle":
        return [arc_prim(e.center, e.radius, 0.0, TAU, h, 0)]
    if k == "arc":
        sw = geom.ccw_sweep(e.start_angle, e.end_angle)
        return [arc_prim(e.center, e.radius, e.start_angle, sw if sw > 1e-12 else TAU, h, 0)]
    if k == "lwpolyline":
        return polyline_prims(e.vertices, bool(e.closed), h, 0)
    if k == "polyline3d":
        return chain_prims([(p[0], p[1]) for p in e.points], bool(e.closed), h, 0, 0.0)
    if k == "ellipse":
        pts, full, slack = ellipse_points(e)
        return chain_prims(pts, False, h, 0, slack)
    if k == "spline":
        res = spline_points(e)
        if res is None:
            return []
        pts, closed, slack = res
        return chain_prims(pts, False, h, 0, slack)
    if k in ("xline", "ray"):
        d = math.hypot(e.direction[0], e.direction[1])
        if d < 1e-12:
            return []
        ux, uy = e.direction[0] / d, e.direction[1] / d
        lo = -reach if k == "xline" else 0.0
        return [line_prim((e.base[0] + ux * lo, e.base[1] + uy * lo), (e.base[0] + ux * reach, e.base[1] + uy * reach), h, 0)]
    if k == "region":
        out = []
        for i, loop in enumerate(e.loops):
            out.extend(polyline_prims(loop.get("vertices", []), True, h, i))
        return out
    return []


def closed_loop_of(e):
    k = e.kind
    if k == "circle":
        c, r = e.center, e.radius
        return [{"p": [c[0] + r, c[1]], "bulge": 1.0}, {"p": [c[0] - r, c[1]], "bulge": 1.0}]
    if k == "lwpolyline" and e.closed and len(e.vertices) >= 2:
        return [{"p": [float(v["p"][0]), float(v["p"][1])], "bulge": float(v.get("bulge", 0.0) or 0.0)} for v in e.vertices]
    if k == "ellipse":
        pts, full, _s = ellipse_points(e)
        if full:
            return [{"p": [p[0], p[1]], "bulge": 0.0} for p in pts[:-1]]
    if k == "spline":
        res = spline_points(e)
        if res is not None and res[1] and len(res[0]) > 3:
            return [{"p": [p[0], p[1]], "bulge": 0.0} for p in res[0][:-1]]
    if k == "polyline3d" and e.closed and len(e.points) >= 3:
        return [{"p": [p[0], p[1]], "bulge": 0.0} for p in e.points]
    return None


def line_line(a, b):
    rx, ry = a.b[0] - a.a[0], a.b[1] - a.a[1]
    sx, sy = b.b[0] - b.a[0], b.b[1] - b.a[1]
    den = rx * sy - ry * sx
    la = math.hypot(rx, ry)
    lb = math.hypot(sx, sy)
    if abs(den) <= 1e-12 * la * lb:
        return []
    qx, qy = b.a[0] - a.a[0], b.a[1] - a.a[1]
    t = (qx * sy - qy * sx) / den
    u = (qx * ry - qy * rx) / den
    return [(t, u)]


def line_circle(ln, c, r):
    dx, dy = ln.b[0] - ln.a[0], ln.b[1] - ln.a[1]
    fx, fy = ln.a[0] - c[0], ln.a[1] - c[1]
    qa = dx * dx + dy * dy
    qb = 2.0 * (fx * dx + fy * dy)
    qc = fx * fx + fy * fy - r * r
    disc = qb * qb - 4.0 * qa * qc
    if disc < -1e-9 * qa * r * r - 1e-18:
        return []
    if disc < 0.0:
        disc = 0.0
    s = math.sqrt(disc)
    ts = [(-qb - s) / (2.0 * qa), (-qb + s) / (2.0 * qa)]
    if s < 1e-12 * max(abs(qb), 1e-300):
        ts = [ts[0]]
    return ts


def arc_param(arc, x, y):
    return geom.ccw_sweep(arc.a0, math.atan2(y - arc.c[1], x - arc.c[0]))


def arc_has(arc, s, tol):
    if arc.sw >= TAU - 1e-12:
        return True
    return s <= arc.sw + tol or s >= TAU - tol


def circle_circle(a, b):
    dx, dy = b.c[0] - a.c[0], b.c[1] - a.c[1]
    d = math.hypot(dx, dy)
    if d < 1e-12:
        return []
    if d > a.r + b.r + 1e-9 * max(a.r, b.r) or d < abs(a.r - b.r) - 1e-9 * max(a.r, b.r):
        return []
    x = (d * d + a.r * a.r - b.r * b.r) / (2.0 * d)
    h2 = a.r * a.r - x * x
    h = math.sqrt(h2) if h2 > 0.0 else 0.0
    mx, my = a.c[0] + dx * x / d, a.c[1] + dy * x / d
    if h <= 1e-9 * a.r:
        return [(mx, my)]
    return [(mx - dy * h / d, my + dx * h / d), (mx + dy * h / d, my - dx * h / d)]


def intersections(a, b, tol):
    out = []
    if a.kind == "line" and b.kind == "line":
        for t, u in line_line(a, b):
            if -a.scale_t(tol) <= t <= 1.0 + a.scale_t(tol) and -b.scale_t(tol) <= u <= 1.0 + b.scale_t(tol):
                out.append((min(max(t, 0.0), 1.0), min(max(u, 0.0), 1.0)))
        return out
    if a.kind == "arc" and b.kind == "line":
        return [(t, u) for u, t in intersections(b, a, tol)]
    if a.kind == "line":
        for t in line_circle(a, b.c, b.r):
            if -a.scale_t(tol) <= t <= 1.0 + a.scale_t(tol):
                x, y = a.at(t)
                s = arc_param(b, x, y)
                if arc_has(b, s, b.scale_t(tol)):
                    out.append((min(max(t, 0.0), 1.0), min(s, b.sw)))
        return out
    for x, y in circle_circle(a, b):
        s1 = arc_param(a, x, y)
        s2 = arc_param(b, x, y)
        if arc_has(a, s1, a.scale_t(tol)) and arc_has(b, s2, b.scale_t(tol)):
            out.append((min(s1, a.sw), min(s2, b.sw)))
    return out


def closest_param(p, x, y):
    if p.kind == "line":
        dx, dy = p.b[0] - p.a[0], p.b[1] - p.a[1]
        n2 = dx * dx + dy * dy
        t = ((x - p.a[0]) * dx + (y - p.a[1]) * dy) / n2 if n2 > 0 else 0.0
        t = min(max(t, 0.0), 1.0)
        q = p.at(t)
        return t, math.hypot(q[0] - x, q[1] - y)
    s = arc_param(p, x, y)
    if s > p.sw:
        qa = p.at(0.0)
        qb = p.at(p.sw)
        da = math.hypot(qa[0] - x, qa[1] - y)
        db = math.hypot(qb[0] - x, qb[1] - y)
        return (0.0, da) if da <= db else (p.sw, db)
    return s, abs(math.hypot(x - p.c[0], y - p.c[1]) - p.r)
