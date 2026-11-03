import math

TWO_PI = 2.0 * math.pi


def span(a0, a1):
    s = (a1 - a0) % TWO_PI
    return s if s > 1e-12 else TWO_PI


def _bspline_point(deg, knots, ctrl, w, u):
    n = len(ctrl)
    k = deg
    span_i = k
    for i in range(k, n):
        if knots[i] <= u < knots[i + 1]:
            span_i = i
            break
    else:
        span_i = n - 1
    d = []
    for j in range(k + 1):
        idx = span_i - k + j
        wt = w[idx] if w else 1.0
        d.append([ctrl[idx][0] * wt, ctrl[idx][1] * wt, wt])
    for r in range(1, k + 1):
        for j in range(k, r - 1, -1):
            i = span_i - k + j
            den = knots[i + k + 1 - r] - knots[i]
            a = (u - knots[i]) / den if den > 1e-14 else 0.0
            d[j] = [(1 - a) * d[j - 1][c] + a * d[j][c] for c in range(3)]
    wt = d[k][2] or 1.0
    return [d[k][0] / wt, d[k][1] / wt]


def sample(rec, per=None):
    t = rec["t"]
    if t == "line":
        return [list(rec["a"]), list(rec["b"])]
    if t in ("arc", "circle"):
        c, r = rec["c"], rec["r"]
        a0, sw = (0.0, TWO_PI) if t == "circle" else (rec["a0"], span(rec["a0"], rec["a1"]))
        n = max(6, int(sw / 0.12) + 1) if per is None else per
        return [[c[0] + r * math.cos(a0 + sw * i / n), c[1] + r * math.sin(a0 + sw * i / n)] for i in range(n + 1)]
    if t == "ellipse":
        c, m = rec["c"], rec["major"]
        ratio = rec["ratio"]
        a0, a1 = rec["a0"], rec["a1"]
        sw = a1 - a0
        if sw <= 0:
            sw += TWO_PI
        n = max(12, int(sw / 0.1) + 1) if per is None else per
        out = []
        for i in range(n + 1):
            u = a0 + sw * i / n
            cu, su = math.cos(u), math.sin(u)
            out.append([c[0] + m[0] * cu - m[1] * ratio * su, c[1] + m[1] * cu + m[0] * ratio * su])
        return out
    if t == "spline":
        knots, ctrl, w, deg = rec["knots"], rec["ctrl"], rec.get("w"), rec["deg"]
        lo, hi = knots[deg], knots[len(ctrl)]
        n = per or max(8, 4 * (len(ctrl) - deg))
        out = []
        for i in range(n + 1):
            u = lo + (hi - lo) * i / n
            if i == n:
                u = hi - 1e-12 * max(1.0, abs(hi))
            out.append(_bspline_point(deg, knots, ctrl, w, u))
        return out
    if t == "poly":
        return [list(p) for p in rec["pts"]]
    return []


def ends(rec):
    pts = sample(rec, 4 if rec["t"] not in ("line", "poly") else None)
    return (pts[0], pts[-1]) if pts else (None, None)


def display(rec):
    t = rec["t"]
    if t == "line":
        return {"type": "line", "p1": list(rec["a"]), "p2": list(rec["b"])}
    if t == "circle":
        return {"type": "circle", "c": list(rec["c"]), "r": rec["r"]}
    if t == "arc":
        return {"type": "arc", "c": list(rec["c"]), "r": rec["r"], "a0": rec["a0"], "a1": rec["a1"]}
    if t == "ellipse":
        return {"type": "ellipse", "c": list(rec["c"]), "major": list(rec["major"]), "ratio": rec["ratio"], "a0": rec["a0"], "a1": rec["a1"]}
    if t == "spline":
        w = rec.get("w")
        return {"type": "spline", "degree": rec["deg"], "knots": list(rec["knots"]), "ctrl": [list(p) for p in rec["ctrl"]], "weights": list(w) if w else None, "fit": None, "closed": False}
    pts = rec.get("pts") or []
    return {"type": "poly", "verts": [[p[0], p[1], 0.0, 0.0, 0.0] for p in pts], "closed": False, "elev": 0.0}


def loop_points(loop):
    pts = []
    for rec in loop:
        s = sample(rec)
        if not s:
            continue
        if pts and math.hypot(pts[-1][0] - s[0][0], pts[-1][1] - s[0][1]) > math.hypot(pts[-1][0] - s[-1][0], pts[-1][1] - s[-1][1]):
            s = s[::-1]
        pts.extend(s if not pts else s[1:])
    if len(pts) > 2 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 1e-9:
        pts.pop()
    return pts


def rings(face):
    out = []
    if face.get("outer"):
        out.append(loop_points(face["outer"]))
    for h in face.get("holes") or []:
        out.append(loop_points(h))
    return [r for r in out if len(r) >= 3]


def bounds(recs):
    lo = [1e300, 1e300]
    hi = [-1e300, -1e300]
    for rec in recs:
        for p in sample(rec):
            lo[0] = min(lo[0], p[0])
            lo[1] = min(lo[1], p[1])
            hi[0] = max(hi[0], p[0])
            hi[1] = max(hi[1], p[1])
    return [lo[0], lo[1], hi[0], hi[1]] if lo[0] <= hi[0] else None


def length(rec):
    t = rec["t"]
    if t == "line":
        return math.hypot(rec["b"][0] - rec["a"][0], rec["b"][1] - rec["a"][1])
    if t == "circle":
        return TWO_PI * rec["r"]
    if t == "arc":
        return rec["r"] * span(rec["a0"], rec["a1"])
    pts = sample(rec, 200)
    return sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(len(pts) - 1))
