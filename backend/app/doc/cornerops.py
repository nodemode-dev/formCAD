import math

from app.doc import geom, nurbs, splineedit
from app.doc.entities import Arc, Circle, Ellipse, Line, LwPolyline, Spline

TOL = 1e-9
PARALLEL = 1e-10
SAMPLES = 120
NEWTON_STEPS = 40
TOO_LARGE = "Radius is too large."
NO_FIT = "No fillet of that radius fits these objects."


def sub(a, b):
    return [a[0] - b[0], a[1] - b[1]]


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def unit(v):
    n = math.hypot(v[0], v[1])
    if n < TOL:
        return None
    return [v[0] / n, v[1] / n]


def lerp(a, b, t):
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]


def add_scaled(a, v, k):
    return [a[0] + v[0] * k, a[1] + v[1] * k]


def sign(v):
    return 1.0 if v >= 0 else -1.0


def piece_of(e):
    if isinstance(e, Line):
        return {"t": "line", "a": e.start[:2], "b": e.end[:2]}
    if isinstance(e, Arc):
        return {"t": "arc", "c": e.center[:2], "r": e.radius, "a0": e.start_angle, "a1": e.end_angle}
    if isinstance(e, Circle):
        return {"t": "circle", "c": e.center[:2], "r": e.radius}
    if isinstance(e, Ellipse):
        return {"t": "ell", "e": e}
    if isinstance(e, Spline):
        c = _spline_curve(e)
        if c is not None:
            return {"t": "spl", "e": e, "curve": c}
    return None


def _spline_curve(e):
    c = nurbs.Curve(int(e.degree), [float(k) for k in e.knots], [list(p) for p in e.control_points], [float(w) for w in e.weights] if e.weights else [], bool(e.closed))
    if c.valid():
        return c
    if e.fit_points and len(e.fit_points) >= 2:
        return nurbs.fit(e.fit_points, nurbs.KNOT_CHORD, bool(e.closed))[0]
    return None


def seg_piece(poly, i):
    n = len(poly.vertices)
    a, b = poly.vertices[i], poly.vertices[(i + 1) % n]
    arc = geom.bulge_to_arc(a["p"], b["p"], a.get("bulge", 0.0) or 0.0)
    if arc is None:
        return {"t": "line", "a": a["p"][:2], "b": b["p"][:2], "bounded": True}
    c, r, a0, a1, _ccw = arc
    return {"t": "arc", "c": c[:2], "r": r, "a0": a0, "a1": a1, "bounded": True}


def nearest_segment(poly, q):
    best, bi = None, 0
    n = len(poly.vertices)
    for i in range(n if poly.closed else n - 1):
        pc = seg_piece(poly, i)
        f = closest_bounded(pc, q)
        d = math.hypot(f[0] - q[0], f[1] - q[1])
        if best is None or d < best:
            best, bi = d, i
    return bi


def closest_bounded(pc, x):
    if pc["t"] == "line":
        a, b = pc["a"], pc["b"]
        d = sub(b, a)
        n2 = dot(d, d)
        t = min(max(dot(sub(x, a), d) / n2, 0.0), 1.0) if n2 > TOL else 0.0
        return add_scaled(a, d, t)
    if pc["t"] == "arc":
        c, r = pc["c"], pc["r"]
        v = unit(sub(x, c)) or [1.0, 0.0]
        ang = math.atan2(v[1], v[0])
        if geom.on_sweep(ang, pc["a0"], pc["a1"]):
            return add_scaled(c, v, r)
        ends = [geom.polar(c, r, pc["a0"]), geom.polar(c, r, pc["a1"])]
        return min(ends, key=lambda p: math.hypot(p[0] - x[0], p[1] - x[1]))[:2]
    return closest(pc, x)


def _ell_pt(e, t):
    ux, uy = e.major[0], e.major[1]
    vx, vy = -uy * e.ratio, ux * e.ratio
    return [e.center[0] + ux * math.cos(t) + vx * math.sin(t), e.center[1] + uy * math.cos(t) + vy * math.sin(t)]


def _ell_tan(e, t):
    ux, uy = e.major[0], e.major[1]
    vx, vy = -uy * e.ratio, ux * e.ratio
    return [-ux * math.sin(t) + vx * math.cos(t), -uy * math.sin(t) + vy * math.cos(t)]


def _ell_range(e):
    full = abs(e.end_param - e.start_param) >= geom.TAU - 1e-12 or abs(e.end_param - e.start_param) < 1e-12
    return (e.start_param, geom.TAU) if full else (e.start_param, geom.ccw_sweep(e.start_param, e.end_param))


def closest_param(pc, x):
    t = pc["t"]
    if t == "ell":
        e = pc["e"]
        n = 720
        best, bt = None, 0.0
        for i in range(n):
            u = geom.TAU * i / n
            p = _ell_pt(e, u)
            d = (p[0] - x[0]) ** 2 + (p[1] - x[1]) ** 2
            if best is None or d < best:
                best, bt = d, u
        a, b = bt - geom.TAU / n, bt + geom.TAU / n
        for _ in range(60):
            m1, m2 = a + (b - a) / 3.0, b - (b - a) / 3.0
            d1 = math.dist(_ell_pt(e, m1), x)
            d2 = math.dist(_ell_pt(e, m2), x)
            if d1 < d2:
                b = m2
            else:
                a = m1
        return (a + b) / 2.0
    if t == "spl":
        return nurbs.closest_param(pc["curve"], [x[0], x[1], 0.0])
    if t in ("arc", "circle"):
        return math.atan2(x[1] - pc["c"][1], x[0] - pc["c"][0])
    d = sub(pc["b"], pc["a"])
    return dot(sub(x, pc["a"]), d) / dot(d, d)


def point_at_param(pc, u):
    t = pc["t"]
    if t == "ell":
        return _ell_pt(pc["e"], u)
    if t == "spl":
        return nurbs.point_at(pc["curve"], u)[:2]
    if t in ("arc", "circle"):
        return geom.polar(pc["c"], pc["r"], u)[:2]
    return lerp(pc["a"], pc["b"], u)


def closest(pc, x):
    t = pc["t"]
    if t == "line":
        a = pc["a"]
        d = unit(sub(pc["b"], a))
        return add_scaled(a, d, dot(sub(x, a), d))
    if t in ("arc", "circle"):
        v = unit(sub(x, pc["c"])) or [1.0, 0.0]
        return add_scaled(pc["c"], v, pc["r"])
    return point_at_param(pc, closest_param(pc, x))


def sample_normals(pc, hint, span, n=SAMPLES):
    out = []
    t = pc["t"]
    if t == "line":
        a = pc["a"]
        d = unit(sub(pc["b"], a))
        base = dot(sub(hint, a), d)
        for i in range(n + 1):
            s = base - span + 2.0 * span * i / n
            out.append((add_scaled(a, d, s), [-d[1], d[0]]))
    elif t in ("arc", "circle"):
        for i in range(n + 1):
            ang = geom.TAU * i / n
            out.append((geom.polar(pc["c"], pc["r"], ang)[:2], [math.cos(ang), math.sin(ang)]))
    elif t == "ell":
        for i in range(n + 1):
            u = geom.TAU * i / n
            tg = unit(_ell_tan(pc["e"], u)) or [1.0, 0.0]
            out.append((_ell_pt(pc["e"], u), [-tg[1], tg[0]]))
    else:
        c = pc["curve"]
        lo, hi = c.domain()
        for i in range(n * 2 + 1):
            u = lo + (hi - lo) * i / (n * 2)
            tg = unit(nurbs.tangent_at(c, u)[:2]) or [1.0, 0.0]
            out.append((nurbs.point_at(c, u)[:2], [-tg[1], tg[0]]))
    return out


def _seg_hit(p, r, q, s):
    den = cross(r, s)
    if abs(den) < 1e-14:
        return None
    qp = sub(q, p)
    t = cross(qp, s) / den
    u = cross(qp, r) / den
    if -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= u <= 1 + 1e-9:
        return add_scaled(p, r, t)
    return None


def _poly_hits(A, B):
    out = []
    for i in range(len(A) - 1):
        r = sub(A[i + 1], A[i])
        for j in range(len(B) - 1):
            h = _seg_hit(A[i], r, B[j], sub(B[j + 1], B[j]))
            if h is not None:
                out.append(h)
    return out


def _line_circle(pl, pc):
    a = pl["a"]
    d = unit(sub(pl["b"], a))
    f = sub(a, pc["c"])
    b = dot(f, d)
    cc = dot(f, f) - pc["r"] ** 2
    disc = b * b - cc
    if disc < -1e-12:
        return []
    root = math.sqrt(max(disc, 0.0))
    return [add_scaled(a, d, -b - root), add_scaled(a, d, -b + root)] if root > 1e-12 else [add_scaled(a, d, -b)]


def _circle_circle(c1, r1, c2, r2):
    d = math.hypot(c2[0] - c1[0], c2[1] - c1[1])
    if d < TOL or d > r1 + r2 + 1e-9 or d < abs(r1 - r2) - 1e-9:
        return []
    x = (d * d + r1 * r1 - r2 * r2) / (2 * d)
    h = math.sqrt(max(0.0, r1 * r1 - x * x))
    ux, uy = (c2[0] - c1[0]) / d, (c2[1] - c1[1]) / d
    bx, by = c1[0] + ux * x, c1[1] + uy * x
    if h < 1e-9:
        return [[bx, by]]
    return [[bx - uy * h, by + ux * h], [bx + uy * h, by - ux * h]]


def intersections(p1, p2, hint):
    k1, k2 = p1["t"], p2["t"]
    rnd = ("arc", "circle")
    if k1 == "line" and k2 == "line":
        d1, d2 = unit(sub(p1["b"], p1["a"])), unit(sub(p2["b"], p2["a"]))
        den = cross(d1, d2)
        if abs(den) < PARALLEL:
            return []
        t = cross(sub(p2["a"], p1["a"]), d2) / den
        return [add_scaled(p1["a"], d1, t)]
    if k1 == "line" and k2 in rnd:
        return _line_circle(p1, p2)
    if k2 == "line" and k1 in rnd:
        return _line_circle(p2, p1)
    if k1 in rnd and k2 in rnd:
        return _circle_circle(p1["c"], p1["r"], p2["c"], p2["r"])
    span = 40.0 * (math.hypot(hint[0], hint[1]) + 1.0)
    A = [s[0] for s in sample_normals(p1, hint, span, 240)]
    B = [s[0] for s in sample_normals(p2, hint, span, 240)]
    out = []
    for x in _poly_hits(A, B):
        for _ in range(40):
            x = closest(p2, closest(p1, x))
        if math.dist(closest(p1, x), closest(p2, x)) < 1e-7:
            if not any(math.dist(x, o) < 1e-6 for o in out):
                out.append(x)
    return out


def _line_circle_centers(pl, pc, r):
    a = pl["a"]
    d = unit(sub(pl["b"], a))
    n = [-d[1], d[0]]
    out = []
    for s in (1.0, -1.0):
        base = add_scaled(a, n, s * r)
        for R2 in {pc["r"] + r, abs(pc["r"] - r)}:
            f = sub(base, pc["c"])
            b = dot(f, d)
            disc = b * b - (dot(f, f) - R2 * R2)
            if disc < -1e-12:
                continue
            root = math.sqrt(max(disc, 0.0))
            for t in ({-b - root, -b + root}):
                out.append(add_scaled(base, d, t))
    return out


def _circle_circle_centers(a, b, r):
    out = []
    for R1 in {a["r"] + r, abs(a["r"] - r)}:
        for R2 in {b["r"] + r, abs(b["r"] - r)}:
            out.extend(_circle_circle(a["c"], R1, b["c"], R2))
    return out


def _numeric_centers(p1, p2, q1, q2, r):
    span = 20.0 * (r + math.dist(q1, q2) + 1.0)
    S1 = sample_normals(p1, q1, span)
    S2 = sample_normals(p2, q2, span)
    seeds = []
    for s1 in (1.0, -1.0):
        A = [add_scaled(p, nv, s1 * r) for p, nv in S1]
        for s2 in (1.0, -1.0):
            B = [add_scaled(p, nv, s2 * r) for p, nv in S2]
            seeds.extend(_poly_hits(A, B))
    out = []
    for x in seeds:
        ok = False
        for _ in range(NEWTON_STEPS):
            f1, f2 = closest(p1, x), closest(p2, x)
            g1, g2 = unit(sub(x, f1)), unit(sub(x, f2))
            if g1 is None or g2 is None:
                break
            e1 = math.dist(x, f1) - r
            e2 = math.dist(x, f2) - r
            if abs(e1) < 1e-10 and abs(e2) < 1e-10:
                ok = True
                break
            den = cross(g1, g2)
            if abs(den) < 1e-12:
                break
            dx = (-e1 * g2[1] + e2 * g1[1]) / den
            dy = (-g1[0] * e2 + g2[0] * e1) / den
            x = [x[0] + dx, x[1] + dy]
        if ok and not any(math.dist(x, o) < 1e-6 for o in out):
            out.append(x)
    return out


def _foot(pc, center, r):
    if pc["t"] == "line":
        return closest(pc, center)
    if pc["t"] in ("arc", "circle"):
        v = unit(sub(center, pc["c"])) or [1.0, 0.0]
        cands = [add_scaled(pc["c"], v, pc["r"]), add_scaled(pc["c"], v, -pc["r"])]
        return min(cands, key=lambda f: abs(math.dist(f, center) - r))
    return closest(pc, center)


def _ref_point(pc, other, pick, hint):
    pts = intersections(pc, other, hint)
    if not pts:
        return None
    return min(pts, key=lambda p: math.dist(p, pick))


def solve(p1, p2, q1, q2, r):
    q1, q2 = q1[:2], q2[:2]
    if p1["t"] == "line" and p2["t"] == "line":
        d1, d2 = unit(sub(p1["b"], p1["a"])), unit(sub(p2["b"], p2["a"]))
        if abs(cross(d1, d2)) < PARALLEL:
            raise ValueError("Lines are parallel.")
        x = intersections(p1, p2, q1)[0]
        w1 = _dir_from(p1, x, q1)
        w2 = _dir_from(p2, x, q2)
        if r <= TOL:
            return {"center": None, "r": 0.0, "f1": x, "f2": x, "ref1": x, "ref2": x}
        cg = dot(w1, w2)
        if cg < -1.0 + 1e-12:
            raise ValueError("Lines are parallel.")
        gamma = math.acos(max(-1.0, min(1.0, cg)))
        if gamma < 1e-9:
            raise ValueError("Lines are parallel.")
        t = r / math.tan(gamma / 2.0)
        bis = unit([w1[0] + w2[0], w1[1] + w2[1]])
        center = add_scaled(x, bis, r / math.sin(gamma / 2.0))
        return {"center": center, "r": r, "f1": add_scaled(x, w1, t), "f2": add_scaled(x, w2, t), "ref1": x, "ref2": x}
    hint = [abs(q1[0]) + abs(q2[0]), abs(q1[1]) + abs(q2[1])]
    if r <= TOL:
        pts = intersections(p1, p2, hint)
        if not pts:
            raise ValueError("The objects do not intersect.")
        x = min(pts, key=lambda p: math.dist(p, q1) + math.dist(p, q2))
        return {"center": None, "r": 0.0, "f1": x, "f2": x, "ref1": x, "ref2": x}
    kinds = {p1["t"], p2["t"]}
    simple = kinds <= {"line", "arc", "circle"}
    if simple:
        if p1["t"] == "line":
            cands = _line_circle_centers(p1, p2, r)
        elif p2["t"] == "line":
            cands = _line_circle_centers(p2, p1, r)
        else:
            cands = _circle_circle_centers(p1, p2, r)
    else:
        cands = _numeric_centers(p1, p2, q1, q2, r)
    best = None
    for c in cands:
        f1, f2 = _foot(p1, c, r), _foot(p2, c, r)
        score = math.dist(f1, q1) + math.dist(f2, q2)
        if best is None or score < best[0]:
            best = (score, c, f1, f2)
    if best is None:
        raise ValueError(NO_FIT)
    _s, c, f1, f2 = best
    return {"center": c, "r": r, "f1": f1, "f2": f2, "ref1": _ref_point(p1, p2, q1, hint), "ref2": _ref_point(p2, p1, q2, hint)}


def _dir_from(pc, x, q):
    d = unit(sub(pc["b"], pc["a"]))
    s = dot(sub(q, x), d)
    if abs(s) < TOL:
        far = max((pc["a"], pc["b"]), key=lambda p: abs(dot(sub(p, x), d)))
        s = dot(sub(far, x), d)
    return [d[0] * sign(s), d[1] * sign(s)]


def fillet_arc(res, tol=TOL):
    c = res["center"]
    a1 = geom.angle_of(c, res["f1"])
    a2 = geom.angle_of(c, res["f2"])
    if geom.ccw_sweep(a1, a2) <= math.pi + 1e-12:
        return c, res["r"], geom.norm_angle(a1), geom.norm_angle(a2)
    return c, res["r"], geom.norm_angle(a2), geom.norm_angle(a1)


def cut_line(a, b, foot, ref, q):
    u = unit(sub(b, a))
    if u is None:
        raise ValueError("Cannot trim a zero length line.")
    base = ref if ref is not None else foot
    s = dot(sub(q, base), u)
    if abs(s) < TOL:
        s = dot(sub(lerp(a, b, 0.5), base), u)
    if s > 0:
        if dot(sub(b, foot), u) <= 1e-9:
            raise ValueError(TOO_LARGE)
        return [foot[0], foot[1], 0.0], None
    if dot(sub(foot, a), u) <= 1e-9:
        raise ValueError(TOO_LARGE)
    return None, [foot[0], foot[1], 0.0]


def cut_arc(a0, a1, center, foot, ref, q):
    tf = geom.angle_of(center, foot)
    tq = geom.angle_of(center, q)
    tr = geom.angle_of(center, ref) if ref is not None else tf
    delta = math.fmod(tq - tr, geom.TAU)
    if delta > math.pi:
        delta -= geom.TAU
    if delta < -math.pi:
        delta += geom.TAU
    if abs(delta) < 1e-12:
        delta = 1.0
    if delta > 0:
        gap = math.fmod(a1 - tf, geom.TAU)
        gap += geom.TAU if gap < 0 else 0.0
        if gap < 1e-9 or gap > geom.TAU - 1e-9:
            raise ValueError(TOO_LARGE)
        return geom.norm_angle(tf), None
    gap = math.fmod(tf - a0, geom.TAU)
    gap += geom.TAU if gap < 0 else 0.0
    if gap < 1e-9 or gap > geom.TAU - 1e-9:
        raise ValueError(TOO_LARGE)
    return None, geom.norm_angle(tf)


def cut_ellipse(e, foot, ref, q):
    pc = {"t": "ell", "e": e}
    tf = closest_param(pc, foot)
    tq = closest_param(pc, q)
    tr = closest_param(pc, ref) if ref is not None else tf
    delta = math.fmod(tq - tr, geom.TAU)
    if delta > math.pi:
        delta -= geom.TAU
    if delta < -math.pi:
        delta += geom.TAU
    if delta >= 0:
        gap = geom.norm_angle(e.end_param - tf)
        if gap < 1e-9:
            raise ValueError(TOO_LARGE)
        return geom.norm_angle(tf), None
    gap = geom.norm_angle(tf - e.start_param)
    if gap < 1e-9:
        raise ValueError(TOO_LARGE)
    return None, geom.norm_angle(tf)


def cut_spline(e, curve, foot, ref, q):
    pc = {"t": "spl", "e": e, "curve": curve}
    lo, hi = curve.domain()
    tf = closest_param(pc, foot)
    tq = closest_param(pc, q)
    tr = closest_param(pc, ref) if ref is not None else tf
    keep_after = tq >= tr
    if math.dist(point_at_param(pc, tf), foot) > 1e-6 * max(1.0, math.dist(foot, q)) + 1e-6:
        raise ValueError("Cannot extend a spline to the fillet.")
    if keep_after:
        if tf >= hi - 1e-9:
            raise ValueError(TOO_LARGE)
        if tf <= lo + 1e-9:
            return curve
        return splineedit.split_at(curve, tf)[1]
    if tf <= lo + 1e-9:
        raise ValueError(TOO_LARGE)
    if tf >= hi - 1e-9:
        return curve
    return splineedit.split_at(curve, tf)[0]


def solve_chamfer_lines(p1, p2, q1, q2, d1, d2):
    da, db = unit(sub(p1["b"], p1["a"])), unit(sub(p2["b"], p2["a"]))
    if abs(cross(da, db)) < PARALLEL:
        raise ValueError("Lines are parallel.")
    x = intersections(p1, p2, q1)[0]
    w1 = _dir_from(p1, x, q1)
    w2 = _dir_from(p2, x, q2)
    return {"x": x, "w1": w1, "w2": w2, "c1": add_scaled(x, w1, d1), "c2": add_scaled(x, w2, d2)}


def angle_distance(w1, w2, length, angle):
    gamma = math.acos(max(-1.0, min(1.0, dot(w1, w2))))
    beta = math.pi - gamma - angle
    if beta <= 1e-9 or angle <= 1e-9 or math.sin(beta) <= 1e-12:
        raise ValueError("The chamfer angle does not fit this corner.")
    return length * math.sin(angle) / math.sin(beta)


def corner_cut(prev, v, nxt, kind, a, b):
    din = unit(sub(v, prev))
    dout = unit(sub(nxt, v))
    if din is None or dout is None:
        return None
    cr = cross(din, dout)
    turn = math.atan2(abs(cr), dot(din, dout))
    if turn < 1e-9 or turn > math.pi - 1e-9:
        return None
    if kind == "fillet":
        t = a * math.tan(turn / 2.0)
        ta = tb = t
        bulge = math.tan(turn / 4.0) * sign(cr)
    else:
        ta, tb, bulge = a, b, 0.0
    return {"ta": ta, "tb": tb, "A": add_scaled(v, din, -ta), "B": add_scaled(v, dout, tb), "bulge": bulge, "turn": turn}


def line_intersection(a1, a2, b1, b2):
    p = {"t": "line", "a": a1[:2], "b": a2[:2]}
    q = {"t": "line", "a": b1[:2], "b": b2[:2]}
    pts = intersections(p, q, a1)
    return pts[0] if pts else None


def end_data(e):
    if isinstance(e, Line):
        a, b = e.start[:2], e.end[:2]
        d = unit(sub(b, a))
        return {"s": (a, [-d[0], -d[1]], 0.0), "e": (b, d, 0.0)}
    if isinstance(e, Arc):
        c, r = e.center[:2], e.radius
        sp, ep = geom.polar(c, r, e.start_angle)[:2], geom.polar(c, r, e.end_angle)[:2]
        ts = [-math.sin(e.start_angle), math.cos(e.start_angle)]
        te = [-math.sin(e.end_angle), math.cos(e.end_angle)]
        return {"s": (sp, [-ts[0], -ts[1]], -1.0 / r), "e": (ep, te, 1.0 / r)}
    if isinstance(e, LwPolyline):
        if e.closed or len(e.vertices) < 2:
            return None
        v = e.vertices
        s0 = _travel(v[0]["p"], v[1]["p"], v[0].get("bulge", 0.0) or 0.0)
        s1 = _travel(v[-2]["p"], v[-1]["p"], v[-2].get("bulge", 0.0) or 0.0)
        return {"s": (v[0]["p"][:2], [-s0[0][0], -s0[0][1]], -s0[2]), "e": (v[-1]["p"][:2], s1[1], s1[2])}
    if isinstance(e, Ellipse):
        full = abs(e.end_param - e.start_param) >= geom.TAU - 1e-12 or abs(e.end_param - e.start_param) < 1e-12
        if full:
            return None
        out = {}
        for key, u, sg in (("s", e.start_param, -1.0), ("e", e.end_param, 1.0)):
            tg = unit(_ell_tan(e, u))
            out[key] = (_ell_pt(e, u), [tg[0] * sg, tg[1] * sg], _ell_curv(e, u) * sg)
        return out
    if isinstance(e, Spline):
        if e.closed:
            return None
        c = _spline_curve(e)
        if c is None:
            return None
        lo, hi = c.domain()
        out = {}
        for key, u, sg in (("s", lo, -1.0), ("e", hi, 1.0)):
            tg = unit(nurbs.tangent_at(c, u)[:2])
            if tg is None:
                return None
            out[key] = (nurbs.point_at(c, u)[:2], [tg[0] * sg, tg[1] * sg], splineedit.curvature(c, u) * sg)
        return out
    return None


def _ell_curv(e, u):
    h = 1e-5
    a, b, c = _ell_pt(e, u - h), _ell_pt(e, u), _ell_pt(e, u + h)
    d1 = [(c[0] - a[0]) / (2 * h), (c[1] - a[1]) / (2 * h)]
    d2 = [(c[0] - 2 * b[0] + a[0]) / (h * h), (c[1] - 2 * b[1] + a[1]) / (h * h)]
    den = math.hypot(d1[0], d1[1]) ** 3
    return cross(d1, d2) / den if den > 1e-18 else 0.0


def _travel(p0, p1, bulge):
    d = unit(sub(p1, p0))
    if abs(bulge) < geom.TINY_BULGE:
        return d, d, 0.0
    theta = 4.0 * math.atan(bulge)
    half = theta / 2.0
    rot = lambda v, a: [v[0] * math.cos(a) - v[1] * math.sin(a), v[0] * math.sin(a) + v[1] * math.cos(a)]
    chord = math.dist(p0, p1)
    return rot(d, -half), rot(d, half), 2.0 * math.sin(half) / chord


def blend_curve(pa, ta, ka, pb, tb, kb, smooth):
    g = math.dist(pa, pb)
    if g < TOL:
        raise ValueError("The ends coincide.")
    if not smooth:
        c = [pa + [0.0], add_scaled(pa, ta, g / 3.0) + [0.0], add_scaled(pb, tb, g / 3.0) + [0.0], pb + [0.0]]
        return nurbs.Curve(3, [0.0] * 4 + [1.0] * 4, c, [], False)
    a = g / 5.0

    def inner(p, t, k):
        n = [-t[1], t[0]]
        p1 = add_scaled(p, t, a)
        h = 1.25 * k * a * a
        p2 = add_scaled(add_scaled(p1, t, a), n, h)
        return p1, p2

    p1, p2 = inner(pa, ta, ka)
    q1, q2 = inner(pb, tb, kb)
    ctrl = [pa, p1, p2, q2, q1, pb]
    return nurbs.Curve(5, [0.0] * 6 + [1.0] * 6, [list(p) + [0.0] for p in ctrl], [], False)
