import math

from app.doc import geom
from app.doc.entities import AttDef, Arc, Circle, Dimension, Ellipse, Insert, Line, LwPolyline, MText, Point, Polyline3d, Ray, Solid, Spline, Text, XLine

MODES = {
    "endpoint": "end",
    "midpoint": "mid",
    "center": "cen",
    "gcenter": "gcen",
    "node": "nod",
    "quadrant": "qua",
    "intersection": "int",
    "apparent": "app",
    "extension": "ext",
    "insertion": "ins",
    "perpendicular": "per",
    "tangent": "tan",
    "nearest": "nea",
    "parallel": "par",
    "none": "none",
}

LABELS = {
    "end": "Endpoint",
    "mid": "Midpoint",
    "cen": "Center",
    "gcen": "Geometric center",
    "nod": "Node",
    "qua": "Quadrant",
    "int": "Intersection",
    "app": "Apparent intersection",
    "ext": "Extension",
    "ins": "Insertion",
    "per": "Perpendicular",
    "tan": "Tangent",
    "nea": "Nearest",
    "par": "Parallel",
    "none": "None",
}

DEFERRABLE = ("per", "tan")
SAMPLES = 720
MAX_CANDIDATES = 2000
MAX_PAIRS = 200


class SnapError(Exception):
    pass


def mode_of(word: str):
    return MODES.get(word)


def _unit(v):
    n = math.hypot(v[0], v[1])
    if n < geom.EPS:
        return None
    return [v[0] / n, v[1] / n]


def _rot90(v):
    return [-v[1], v[0]]


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _closest_to(cands, near):
    if not cands:
        return None
    return min(cands, key=lambda p: geom.dist(p, near))


def pieces(e):
    if isinstance(e, Line):
        return [("seg", e.start, e.end, False)]
    if isinstance(e, (Ray, XLine)):
        d = _unit(e.direction) or [1.0, 0.0]
        return [("seg", e.base, [e.base[0] + d[0], e.base[1] + d[1], 0.0], False)]
    if isinstance(e, Circle):
        return [("circle", e.center, e.radius)]
    if isinstance(e, Arc):
        return [("arc", e.center, e.radius, e.start_angle, e.end_angle)]
    if isinstance(e, Ellipse):
        return [("ell", e)]
    if isinstance(e, LwPolyline):
        out = []
        for p0, p1, bulge in e.segments():
            arc = geom.bulge_to_arc(p0, p1, bulge)
            if arc:
                c, r, a0, a1, _ccw = arc
                out.append(("arc", c, r, a0, a1))
            else:
                out.append(("seg", p0, p1, True))
        return out
    return []


def _ell_axes(e):
    u = [e.major[0], e.major[1]]
    v = [-u[1] * e.ratio, u[0] * e.ratio]
    return u, v


def _ell_sweep(e):
    full = abs(e.end_param - e.start_param) >= geom.TAU - 1e-12 or abs(e.end_param - e.start_param) < 1e-12
    return (e.start_param, geom.TAU) if full else (e.start_param, geom.ccw_sweep(e.start_param, e.end_param))


def _ell_point(e, t):
    u, v = _ell_axes(e)
    return [e.center[0] + u[0] * math.cos(t) + v[0] * math.sin(t), e.center[1] + u[1] * math.cos(t) + v[1] * math.sin(t), 0.0]


def _ell_deriv(e, t):
    u, v = _ell_axes(e)
    return [-u[0] * math.sin(t) + v[0] * math.cos(t), -u[1] * math.sin(t) + v[1] * math.cos(t)]


def _ell_roots(e, base, kind):
    t0, sweep = _ell_sweep(e)

    def f(t):
        p = _ell_point(e, t)
        d = _ell_deriv(e, t)
        rel = [p[0] - base[0], p[1] - base[1]]
        return geom.cross2(d, rel) if kind == "tan" else _dot(d, rel)

    out = []
    prev_t = t0
    prev = f(prev_t)
    for i in range(1, SAMPLES + 1):
        t = t0 + sweep * i / SAMPLES
        cur = f(t)
        if prev == 0.0:
            out.append(prev_t)
        elif prev * cur < 0:
            lo, hi, flo = prev_t, t, prev
            for _ in range(60):
                mid = (lo + hi) / 2.0
                fm = f(mid)
                if flo * fm <= 0:
                    hi = mid
                else:
                    lo, flo = mid, fm
            out.append((lo + hi) / 2.0)
        prev_t, prev = t, cur
    return [_ell_point(e, t) for t in out]


def _perp_piece(pc, base):
    k = pc[0]
    if k == "seg":
        _, a, b, bounded = pc
        d = [b[0] - a[0], b[1] - a[1]]
        n2 = _dot(d, d)
        if n2 < geom.EPS:
            return []
        t = _dot([base[0] - a[0], base[1] - a[1]], d) / n2
        if bounded and not -1e-9 <= t <= 1 + 1e-9:
            return []
        return [[a[0] + d[0] * t, a[1] + d[1] * t, 0.0]]
    if k in ("circle", "arc"):
        c, r = pc[1], pc[2]
        u = _unit([base[0] - c[0], base[1] - c[1]])
        if u is None:
            return []
        out = [[c[0] + r * u[0], c[1] + r * u[1], 0.0], [c[0] - r * u[0], c[1] - r * u[1], 0.0]]
        if k == "arc":
            out = [p for p in out if geom.on_sweep(geom.angle_of(c, p), pc[3], pc[4])]
        return out
    if k == "ell":
        return _ell_roots(pc[1], base, "per")
    return []


def _tan_piece(pc, base):
    k = pc[0]
    if k in ("circle", "arc"):
        c, r = pc[1], pc[2]
        d = geom.dist(c, base)
        if d <= r + geom.EPS:
            return []
        phi = geom.angle_of(c, base)
        alpha = math.acos(r / d)
        out = [geom.polar(c, r, phi + alpha), geom.polar(c, r, phi - alpha)]
        if k == "arc":
            out = [p for p in out if geom.on_sweep(geom.angle_of(c, p), pc[3], pc[4])]
        return out
    if k == "ell":
        return _ell_roots(pc[1], base, "tan")
    return []


def single(mode: str, entity, base, near):
    cands = []
    for pc in pieces(entity):
        cands.extend(_perp_piece(pc, base) if mode == "per" else _tan_piece(pc, base))
    if not cands:
        if mode == "tan":
            raise SnapError("No tangent point exists for this object from that point.")
        raise SnapError("No perpendicular point exists on this object from that point.")
    return _closest_to(cands, near)


def _line_dir(pc):
    return _unit([pc[2][0] - pc[1][0], pc[2][1] - pc[1][1]])


def _tt_circles(c1, r1, c2, r2):
    dx, dy = c2[0] - c1[0], c2[1] - c1[1]
    d = math.hypot(dx, dy)
    if d < geom.EPS:
        return []
    phi = math.atan2(dy, dx)
    out = []
    for e2 in (1.0, -1.0):
        k = e2 * r2 - r1
        if abs(k) > d:
            continue
        a = math.acos(max(-1.0, min(1.0, k / d)))
        for th in (phi + a, phi - a):
            n = [math.cos(th), math.sin(th)]
            out.append(([c1[0] - r1 * n[0], c1[1] - r1 * n[1], 0.0], [c2[0] - e2 * r2 * n[0], c2[1] - e2 * r2 * n[1], 0.0]))
    return out


def _arc_ok(pc, p):
    return pc[0] == "circle" or geom.on_sweep(geom.angle_of(pc[1], p), pc[3], pc[4])


def _circ_pieces(entity):
    return [pc for pc in pieces(entity) if pc[0] in ("circle", "arc")]


def _line_pieces(entity):
    return [pc for pc in pieces(entity) if pc[0] == "seg"]


def _score(p1, p2, n1, n2):
    return geom.dist(p1, n1) + geom.dist(p2, n2)


def _tan_per(tan_pc, per_pc, n_tan, n_per):
    out = []
    c, r = tan_pc[1], tan_pc[2]
    if per_pc[0] == "seg":
        u = _line_dir(per_pc)
        if u is None:
            return out
        for s in (1.0, -1.0):
            t = [c[0] + s * r * u[0], c[1] + s * r * u[1], 0.0]
            if not _arc_ok(tan_pc, t):
                continue
            foot = _perp_piece(per_pc, t)
            if foot:
                out.append((t, foot[0], _score(t, foot[0], n_tan, n_per)))
        return out
    if per_pc[0] in ("circle", "arc"):
        c2, r2 = per_pc[1], per_pc[2]
        for t in _tan_piece(tan_pc, c2):
            u = _unit([t[0] - c2[0], t[1] - c2[1]])
            if u is None:
                continue
            for s in (1.0, -1.0):
                q = [c2[0] + s * r2 * u[0], c2[1] + s * r2 * u[1], 0.0]
                if per_pc[0] == "arc" and not _arc_ok(per_pc, q):
                    continue
                out.append((t, q, _score(t, q, n_tan, n_per)))
    return out


def _per_per(pa, pb, na, nb):
    out = []
    if pa[0] == "seg" and pb[0] == "seg":
        ua, ub = _line_dir(pa), _line_dir(pb)
        if ua is None or ub is None or abs(geom.cross2(ua, ub)) > 1e-9:
            return out
        for q in _perp_piece(pa, nb):
            foot = _perp_piece(pb, q)
            if foot:
                out.append((q, foot[0], _score(q, foot[0], na, nb)))
        return out
    if pa[0] == "seg":
        res = _per_per(pb, pa, nb, na)
        return [(q, p, s) for p, q, s in res]
    ca, ra = pa[1], pa[2]
    if pb[0] == "seg":
        ub = _line_dir(pb)
        if ub is None:
            return out
        n = _rot90(ub)
        for s in (1.0, -1.0):
            p = [ca[0] + s * ra * n[0], ca[1] + s * ra * n[1], 0.0]
            if pa[0] == "arc" and not _arc_ok(pa, p):
                continue
            foot = _perp_piece(pb, p)
            if foot:
                out.append((p, foot[0], _score(p, foot[0], na, nb)))
        return out
    cb, rb = pb[1], pb[2]
    u = _unit([cb[0] - ca[0], cb[1] - ca[1]])
    if u is None:
        return out
    for s1 in (1.0, -1.0):
        for s2 in (1.0, -1.0):
            p = [ca[0] + s1 * ra * u[0], ca[1] + s1 * ra * u[1], 0.0]
            q = [cb[0] + s2 * rb * u[0], cb[1] + s2 * rb * u[1], 0.0]
            if (pa[0] == "arc" and not _arc_ok(pa, p)) or (pb[0] == "arc" and not _arc_ok(pb, q)):
                continue
            out.append((p, q, _score(p, q, na, nb)))
    return out


def pair(m1: str, e1, n1, m2: str, e2, n2):
    best = None

    def offer(res):
        nonlocal best
        for p, q, s in res:
            if best is None or s < best[2]:
                best = (p, q, s)

    for a in pieces(e1):
        for b in pieces(e2):
            if m1 == "tan" and m2 == "tan":
                if a[0] in ("circle", "arc") and b[0] in ("circle", "arc"):
                    for p, q in _tt_circles(a[1], a[2], b[1], b[2]):
                        if _arc_ok(a, p) and _arc_ok(b, q):
                            offer([(p, q, _score(p, q, n1, n2))])
            elif m1 == "tan" and m2 == "per":
                if a[0] in ("circle", "arc"):
                    offer(_tan_per(a, b, n1, n2))
            elif m1 == "per" and m2 == "tan":
                if b[0] in ("circle", "arc"):
                    offer([(p, q, s) for q, p, s in _tan_per(b, a, n2, n1)])
            else:
                offer(_per_per(a, b, n1, n2))
    if best is None:
        raise SnapError("No line satisfies both snaps (parallel lines, concentric circles or a point inside a circle).")
    return best[0], best[1]


def _arc_mid(c, r, a0, a1):
    return geom.polar(c, r, a0 + geom.ccw_sweep(a0, a1) / 2.0)


def mode_points(e) -> list:
    out = []
    if isinstance(e, Line):
        out += [("end", e.start), ("end", e.end), ("mid", geom.midpoint(e.start, e.end))]
    elif isinstance(e, Arc):
        c, r, a0, a1 = e.center, e.radius, e.start_angle, e.end_angle
        out += [("end", geom.polar(c, r, a0)), ("end", geom.polar(c, r, a1)), ("mid", _arc_mid(c, r, a0, a1)), ("cen", c)]
        for k in range(4):
            if geom.on_sweep(k * math.pi / 2.0, a0, a1):
                out.append(("qua", geom.polar(c, r, k * math.pi / 2.0)))
    elif isinstance(e, Circle):
        out.append(("cen", e.center))
        for k in range(4):
            out.append(("qua", geom.polar(e.center, e.radius, k * math.pi / 2.0)))
    elif isinstance(e, Ellipse):
        out.append(("cen", e.center))
        t0, sweep = _ell_sweep(e)
        if sweep < geom.TAU - 1e-9:
            out += [("end", _ell_point(e, e.start_param)), ("end", _ell_point(e, e.end_param)), ("mid", _ell_point(e, t0 + sweep / 2.0))]
        for k in range(4):
            if sweep >= geom.TAU - 1e-9 or geom.on_sweep(k * math.pi / 2.0, t0, t0 + sweep):
                out.append(("qua", _ell_point(e, k * math.pi / 2.0)))
    elif isinstance(e, LwPolyline):
        for v in e.vertices:
            out.append(("end", v["p"]))
        for p0, p1, bulge in e.segments():
            arc = geom.bulge_to_arc(p0, p1, bulge)
            if arc:
                out.append(("mid", _arc_mid(arc[0], arc[1], arc[2], arc[3])))
            else:
                out.append(("mid", geom.midpoint(p0, p1)))
        if e.closed and len(e.vertices) >= 3:
            out.append(("gcen", _centroid([v["p"] for v in e.vertices])))
    elif isinstance(e, Polyline3d):
        out += [("end", p) for p in e.points]
    elif isinstance(e, Spline):
        pts = e.fit_points or e.control_points
        if pts and not e.closed:
            out += [("end", pts[0]), ("end", pts[-1])]
    elif isinstance(e, Point):
        out.append(("nod", e.position))
    elif isinstance(e, (Text, MText, AttDef, Insert)):
        out.append(("ins", getattr(e, "align_point", None) or e.position))
    elif isinstance(e, Ray):
        out.append(("end", e.base))
    elif isinstance(e, Solid):
        out += [("end", p) for p in e.corners]
    elif isinstance(e, Dimension):
        for p in (e.def_point, e.p13, e.p14):
            if p:
                out.append(("nod", p))
    return out


def _centroid(pts):
    a = cx = cy = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i][0], pts[i][1]
        x1, y1 = pts[(i + 1) % n][0], pts[(i + 1) % n][1]
        w = x0 * y1 - x1 * y0
        a += w
        cx += (x0 + x1) * w
        cy += (y0 + y1) * w
    if abs(a) < geom.EPS:
        return [sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n, 0.0]
    return [cx / (3.0 * a), cy / (3.0 * a), 0.0]


def nearest_on(e, near):
    best = None
    for pc in pieces(e):
        k = pc[0]
        cand = None
        if k == "seg":
            _, a, b, bounded = pc
            d = [b[0] - a[0], b[1] - a[1]]
            n2 = _dot(d, d)
            if n2 < geom.EPS:
                continue
            t = _dot([near[0] - a[0], near[1] - a[1]], d) / n2
            if isinstance(e, XLine):
                pass
            elif isinstance(e, Ray):
                t = max(0.0, t)
            else:
                t = max(0.0, min(1.0, t))
            cand = [a[0] + d[0] * t, a[1] + d[1] * t, 0.0]
        elif k in ("circle", "arc"):
            c, r = pc[1], pc[2]
            u = _unit([near[0] - c[0], near[1] - c[1]]) or [1.0, 0.0]
            p = [c[0] + r * u[0], c[1] + r * u[1], 0.0]
            if k == "arc" and not geom.on_sweep(geom.angle_of(c, p), pc[3], pc[4]):
                ends = [geom.polar(c, r, pc[3]), geom.polar(c, r, pc[4])]
                p = _closest_to(ends, near)
            cand = p
        elif k == "ell":
            t0, sweep = _ell_sweep(pc[1])
            cand = _closest_to([_ell_point(pc[1], t0 + sweep * i / SAMPLES) for i in range(SAMPLES + 1)], near)
        if cand is not None and (best is None or geom.dist(cand, near) < geom.dist(best, near)):
            best = cand
    return best


def _seg_seg(a, b):
    p, r = a[1], [a[2][0] - a[1][0], a[2][1] - a[1][1]]
    q, s = b[1], [b[2][0] - b[1][0], b[2][1] - b[1][1]]
    den = geom.cross2(r, s)
    if abs(den) < 1e-14 * max(1.0, _dot(r, r) ** 0.5 * _dot(s, s) ** 0.5):
        return []
    qp = [q[0] - p[0], q[1] - p[1]]
    t = geom.cross2(qp, s) / den
    u = geom.cross2(qp, r) / den
    if (a[3] and not -1e-9 <= t <= 1 + 1e-9) or (b[3] and not -1e-9 <= u <= 1 + 1e-9):
        return []
    return [[p[0] + r[0] * t, p[1] + r[1] * t, 0.0]]


def _seg_circ(sg, ci):
    p = sg[1]
    d = [sg[2][0] - p[0], sg[2][1] - p[1]]
    c, r = ci[1], ci[2]
    f = [p[0] - c[0], p[1] - c[1]]
    a = _dot(d, d)
    if a < geom.EPS:
        return []
    b = 2.0 * _dot(f, d)
    cc = _dot(f, f) - r * r
    disc = b * b - 4.0 * a * cc
    if disc < 0:
        return []
    root = math.sqrt(disc)
    out = []
    for t in sorted({(-b - root) / (2 * a), (-b + root) / (2 * a)}):
        if sg[3] and not -1e-9 <= t <= 1 + 1e-9:
            continue
        q = [p[0] + d[0] * t, p[1] + d[1] * t, 0.0]
        if ci[0] == "arc" and not geom.on_sweep(geom.angle_of(c, q), ci[3], ci[4]):
            continue
        out.append(q)
    return out


def _circ_circ(a, b):
    c1, r1, c2, r2 = a[1], a[2], b[1], b[2]
    d = geom.dist(c1, c2)
    if d < geom.EPS or d > r1 + r2 + geom.EPS or d < abs(r1 - r2) - geom.EPS:
        return []
    x = (d * d + r1 * r1 - r2 * r2) / (2 * d)
    h = math.sqrt(max(0.0, r1 * r1 - x * x))
    phi = geom.angle_of(c1, c2)
    base = geom.polar(c1, x, phi)
    out = [[base[0] - h * math.sin(phi), base[1] + h * math.cos(phi), 0.0], [base[0] + h * math.sin(phi), base[1] - h * math.cos(phi), 0.0]]
    res = []
    for q in out:
        if a[0] == "arc" and not geom.on_sweep(geom.angle_of(c1, q), a[3], a[4]):
            continue
        if b[0] == "arc" and not geom.on_sweep(geom.angle_of(c2, q), b[3], b[4]):
            continue
        res.append(q)
    return res


def crossings(e1, e2):
    out = []
    for a in pieces(e1):
        for b in pieces(e2):
            if a[0] == "seg" and b[0] == "seg":
                out += _seg_seg(a, b)
            elif a[0] == "seg" and b[0] in ("circle", "arc"):
                out += _seg_circ(a, b)
            elif b[0] == "seg" and a[0] in ("circle", "arc"):
                out += _seg_circ(b, a)
            elif a[0] in ("circle", "arc") and b[0] in ("circle", "arc"):
                out += _circ_circ(a, b)
    return out


def _near_box(e, near, pad):
    b = e.bounds()
    if b is None:
        return False
    return b[0] - pad <= near[0] <= b[2] + pad and b[1] - pad <= near[1] <= b[3] + pad


def search(ents, mode: str, near, aperture: float, only=None):
    best = None
    pool = [only] if only is not None else [e for e in ents if _near_box(e, near, aperture)][:MAX_CANDIDATES]
    if mode == "int" or mode == "app":
        for i in range(len(pool)):
            for j in range(i + 1, min(len(pool), MAX_PAIRS)):
                for p in crossings(pool[i], pool[j]):
                    d = geom.dist(p, near)
                    if d <= aperture and (best is None or d < best[0]):
                        best = (d, p, pool[i].handle)
        return None if best is None else (best[1], best[2])
    for e in pool:
        if mode == "nea":
            p = nearest_on(e, near)
            if p is None:
                continue
            cands = [p]
        else:
            cands = [p for m, p in mode_points(e) if m == mode]
        for p in cands:
            d = geom.dist(p, near)
            if (only is not None or d <= aperture) and (best is None or d < best[0]):
                best = (d, p, e.handle)
    return None if best is None else ([best[1][0], best[1][1], 0.0], best[2])


def nearest_curve(ents, near, aperture: float):
    best = None
    for e in ents:
        if not pieces(e) or not _near_box(e, near, aperture):
            continue
        p = nearest_on(e, near)
        if p is None:
            continue
        d = geom.dist(p, near)
        if d <= aperture and (best is None or d < best[0]):
            best = (d, e)
    return None if best is None else best[1]
