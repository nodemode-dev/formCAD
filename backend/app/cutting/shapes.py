import math

import pyclipper as pc

SCALE = 1000.0
FLATTEN_TOL = 0.01
MAX_POINTS = 20000
MAX_LOOPS = 2000
MAX_CONVEX_INPUT = 300


class CutError(ValueError):
    pass


def area(pts) -> float:
    n = len(pts)
    s = 0.0
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return 0.5 * s


def perimeter(pts, closed=True) -> float:
    n = len(pts)
    s = 0.0
    for i in range(n if closed else n - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        s += math.hypot(x1 - x0, y1 - y0)
    return s


def bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def centroid(pts):
    a = area(pts)
    if abs(a) < 1e-12:
        xs, ys = zip(*pts)
        return sum(xs) / len(xs), sum(ys) / len(ys)
    cx = cy = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        c = x0 * y1 - x1 * y0
        cx += (x0 + x1) * c
        cy += (y0 + y1) * c
    return cx / (6 * a), cy / (6 * a)


def inside(pt, pts) -> bool:
    x, y = pt
    n = len(pts)
    ins = False
    j = n - 1
    for i in range(n):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            ins = not ins
        j = i
    return ins


def arc_points(c, r, a0, sweep, tol=FLATTEN_TOL):
    if r <= tol:
        return [(c[0] + r * math.cos(a0), c[1] + r * math.sin(a0))]
    step = 2.0 * math.acos(max(-1.0, min(1.0, 1.0 - tol / r)))
    n = max(2, int(math.ceil(abs(sweep) / max(step, 1e-3))))
    return [(c[0] + r * math.cos(a0 + sweep * i / n), c[1] + r * math.sin(a0 + sweep * i / n)) for i in range(n + 1)]


def circle_points(c, r, ccw=True, tol=FLATTEN_TOL):
    pts = arc_points(c, r, 0.0, 2 * math.pi if ccw else -2 * math.pi, tol)
    return pts[:-1]


def bulge_points(a, b, bulge, tol=FLATTEN_TOL):
    if abs(bulge) < 1e-12:
        return [a]
    d = math.hypot(b[0] - a[0], b[1] - a[1])
    if d < 1e-12:
        return [a]
    theta = 4.0 * math.atan(bulge)
    r = d / (2.0 * math.sin(abs(theta) / 2.0))
    mx, my = (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0
    nx, ny = -(b[1] - a[1]) / d, (b[0] - a[0]) / d
    off = r * math.cos(abs(theta) / 2.0)
    sgn = 1.0 if bulge > 0 else -1.0
    c = (mx + sgn * nx * off, my + sgn * ny * off)
    a0 = math.atan2(a[1] - c[1], a[0] - c[0])
    pts = arc_points(c, r, a0, theta, tol)
    return pts[:-1]


def seg_points(seg, tol=FLATTEN_TOL):
    t = seg.get("t", "line")
    if t == "line":
        return [tuple(seg["a"])]
    if t == "poly":
        return [tuple(p) for p in seg["pts"][:-1]]
    if t == "arc":
        c = seg["c"]
        r = float(seg["r"])
        a, b = seg["a"], seg["b"]
        s = math.atan2(a[1] - c[1], a[0] - c[0])
        e = math.atan2(b[1] - c[1], b[0] - c[0])
        if seg.get("ccw", True):
            sw = (e - s) % (2 * math.pi)
        else:
            sw = -((s - e) % (2 * math.pi))
        pts = arc_points(c, r, s, sw, tol)
        pts[0] = tuple(a)
        return pts[:-1]
    raise CutError("A profile segment is line, arc, poly or circle, not %s." % t)


def loop_from_segs(segs, tol=FLATTEN_TOL):
    if len(segs) == 1 and segs[0].get("t") == "circle":
        s = segs[0]
        return {"pts": circle_points(s["c"], float(s["r"]), bool(s.get("ccw", True)), tol), "circle": {"c": [float(s["c"][0]), float(s["c"][1])], "r": float(s["r"])}}
    pts = []
    for s in segs:
        pts.extend(seg_points(s, tol))
    return {"pts": pts, "circle": None}


def convex_sum(P, Q):
    def lowest(poly):
        k = min(range(len(poly)), key=lambda i: (poly[i][1], poly[i][0]))
        return poly[k:] + poly[:k]

    P = lowest(list(P))
    Q = lowest(list(Q))
    n, m = len(P), len(Q)
    P.append(P[0])
    P.append(P[1])
    Q.append(Q[0])
    Q.append(Q[1])
    out = []
    i = j = 0
    while i < n or j < m:
        out.append((P[i][0] + Q[j][0], P[i][1] + Q[j][1]))
        ex, ey = P[i + 1][0] - P[i][0], P[i + 1][1] - P[i][1]
        fx, fy = Q[j + 1][0] - Q[j][0], Q[j + 1][1] - Q[j][1]
        cr = ex * fy - ey * fx
        if i < n and (j == m or cr > 0):
            i += 1
        elif j < m and (i == n or cr < 0):
            j += 1
        else:
            i += 1
            j += 1
    return out


def _dp(pts, tol):
    if len(pts) < 3:
        return list(pts)
    a, b = pts[0], pts[-1]
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy)
    best, idx = -1.0, 0
    for i in range(1, len(pts) - 1):
        p = pts[i]
        d = abs(dx * (p[1] - a[1]) - dy * (p[0] - a[0])) / L if L > 1e-12 else math.hypot(p[0] - a[0], p[1] - a[1])
        if d > best:
            best, idx = d, i
    if best <= tol:
        return [a, b]
    return _dp(pts[: idx + 1], tol)[:-1] + _dp(pts[idx:], tol)


def decimate(pts, tol):
    n = len(pts)
    if n < 8:
        return list(pts)
    k = max(range(n), key=lambda i: math.hypot(pts[i][0] - pts[0][0], pts[i][1] - pts[0][1]))
    first = _dp(pts[: k + 1], tol)
    second = _dp(pts[k:] + [pts[0]], tol)
    out = first[:-1] + second[:-1]
    return out if len(out) >= 3 else list(pts)


def clean(pts, dist=0.01):
    p = pc.CleanPolygon([(int(round(x * SCALE)), int(round(y * SCALE))) for x, y in pts], dist * SCALE)
    return [(x / SCALE, y / SCALE) for x, y in p]


def orient(pts, ccw=True):
    if (area(pts) > 0) != ccw:
        return list(reversed(pts))
    return list(pts)


def make_loop(pts, circle=None, outer=True):
    pts = [(float(x), float(y)) for x, y in pts]
    if len(pts) < 3 and circle is None:
        raise CutError("A closed profile needs at least three points.")
    if circle is None:
        pts = clean(pts, 0.0005) or pts
        if len(pts) < 3 or abs(area(pts)) < 1e-9:
            raise CutError("A closed profile has no area.")
    return {"pts": orient(pts, outer), "circle": circle, "outer": bool(outer)}


def group_loops(raw_loops):
    if len(raw_loops) > MAX_LOOPS:
        raise CutError("%d closed shapes is more than the limit of %d." % (len(raw_loops), MAX_LOOPS))
    items = []
    for lp in raw_loops:
        pts = lp["pts"]
        if len(pts) < 3 and not lp.get("circle"):
            continue
        items.append({"pts": pts, "circle": lp.get("circle"), "a": abs(area(pts)), "handle": lp.get("handle")})
    items.sort(key=lambda it: -it["a"])
    for i, it in enumerate(items):
        probe = it["pts"][0]
        depth = 0
        parent = None
        for j in range(i):
            if inside(probe, items[j]["pts"]) and (items[j]["a"] > it["a"] * 1.0000001):
                depth += 1
                parent = j
        it["depth"] = depth
        it["parent"] = parent
    parts = []
    owner = {}
    for i, it in enumerate(items):
        if it["depth"] % 2 == 0:
            parts.append({"loops": [make_loop(it["pts"], it["circle"], True)], "handle": it.get("handle")})
            owner[i] = len(parts) - 1
    for i, it in enumerate(items):
        if it["depth"] % 2 == 1:
            j = it["parent"]
            while j is not None and j not in owner:
                j = items[j]["parent"]
            if j is None:
                continue
            parts[owner[j]]["loops"].append(make_loop(it["pts"], it["circle"], False))
    return parts


def normalize_part(spec: dict, index: int = 0) -> dict:
    name = str(spec.get("name") or "Part %d" % (index + 1))
    qty = int(spec.get("qty", 1))
    if qty < 1:
        raise CutError("Part %s has a quantity below 1." % name)
    raw = spec.get("loops")
    if not raw:
        raise CutError("Part %s has no profile loops." % name)
    if len(raw) > MAX_LOOPS:
        raise CutError("Part %s has more than %d loops." % (name, MAX_LOOPS))
    loops = []
    total = 0
    for lp in raw:
        if lp.get("segs"):
            built = loop_from_segs(lp["segs"])
        elif lp.get("circle") and not lp.get("pts"):
            c = lp["circle"]
            built = {"pts": circle_points(c["c"], float(c["r"])), "circle": {"c": [float(c["c"][0]), float(c["c"][1])], "r": float(c["r"])}}
        elif lp.get("pts"):
            built = {"pts": lp["pts"], "circle": lp.get("circle")}
        else:
            raise CutError("A loop of %s needs pts, segs or circle." % name)
        total += len(built["pts"])
        if total > MAX_POINTS:
            raise CutError("Part %s has more than %d profile points." % (name, MAX_POINTS))
        outer = lp.get("outer")
        if outer is None:
            outer = len(loops) == 0
        loops.append(make_loop(built["pts"], built["circle"], bool(outer)))
    outers = [l for l in loops if l["outer"]]
    if not outers:
        raise CutError("Part %s has no outer loop." % name)
    big = max(outers, key=lambda l: abs(area(l["pts"])))
    for l in outers:
        if l is not big:
            l["outer"] = False
            l["pts"] = orient(l["pts"], False)
    x0, y0, _, _ = bbox(big["pts"])
    for l in loops:
        l["pts"] = [(x - x0, y - y0) for x, y in l["pts"]]
        if l.get("circle"):
            l["circle"] = {"c": [l["circle"]["c"][0] - x0, l["circle"]["c"][1] - y0], "r": l["circle"]["r"]}
    loops.sort(key=lambda l: (not l["outer"]))
    out_area = abs(area(loops[0]["pts"]))
    net = out_area - sum(abs(area(l["pts"])) for l in loops[1:])
    rot = spec.get("rotations")
    if rot is None:
        rot = [0.0, 90.0, 180.0, 270.0]
    rot = [float(r) % 360.0 for r in rot]
    if not rot:
        raise CutError("Part %s allows no rotation." % name)
    return {"name": name, "qty": qty, "loops": loops, "area": net, "gross": out_area, "rotations": sorted(set(rot)), "source": spec.get("source", "profile"), "cut_length": sum(perimeter(l["pts"]) for l in loops)}


def to_ints(pts):
    return [(int(round(x * SCALE)), int(round(y * SCALE))) for x, y in pts]


def from_ints(paths):
    return [[(x / SCALE, y / SCALE) for x, y in p] for p in paths]


def offset(paths, delta, round_join=True, arc_tol=0.01):
    if not paths:
        return []
    co = pc.PyclipperOffset(2.0, arc_tol * SCALE)
    jt = pc.JT_ROUND if round_join else pc.JT_MITER
    for p in paths:
        co.AddPath(to_ints(p), jt, pc.ET_CLOSEDPOLYGON)
    return from_ints(co.Execute(delta * SCALE))


def transform(pts, rot_deg, tx, ty):
    c = math.cos(math.radians(rot_deg))
    s = math.sin(math.radians(rot_deg))
    return [(c * x - s * y + tx, s * x + c * y + ty) for x, y in pts]


def convex(pts) -> bool:
    n = len(pts)
    sign = 0
    for i in range(n):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % n]
        cx, cy = pts[(i + 2) % n]
        z = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        if abs(z) < 1e-12:
            continue
        s = 1 if z > 0 else -1
        if sign and s != sign:
            return False
        sign = s
    return True


def triangulate(pts):
    n = len(pts)
    idx = list(range(n))
    tris = []
    guard = 0
    while len(idx) > 3 and guard < n * n:
        guard += 1
        ear = None
        m = len(idx)
        for k in range(m):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % m]
            a, b, c = pts[i0], pts[i1], pts[i2]
            if (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]) <= 1e-12:
                continue
            ok = True
            for j in idx:
                if j in (i0, i1, i2):
                    continue
                p = pts[j]
                d1 = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
                d2 = (c[0] - b[0]) * (p[1] - b[1]) - (c[1] - b[1]) * (p[0] - b[0])
                d3 = (a[0] - c[0]) * (p[1] - c[1]) - (a[1] - c[1]) * (p[0] - c[0])
                if d1 >= -1e-12 and d2 >= -1e-12 and d3 >= -1e-12:
                    ok = False
                    break
            if ok:
                ear = k
                break
        if ear is None:
            ear = 0
            for k in range(m):
                i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % m]
                a, b, c = pts[i0], pts[i1], pts[i2]
                if (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]) > 1e-12:
                    ear = k
                    break
        tris.append((idx[ear - 1], idx[ear], idx[(ear + 1) % len(idx)]))
        del idx[ear]
    if len(idx) == 3:
        tris.append(tuple(idx))
    return tris


def convex_parts(pts):
    if convex(pts):
        return [list(pts)]
    if len(pts) > MAX_CONVEX_INPUT:
        raise CutError("An outline of %d vertices is too complex to split for nesting; at most %d are supported. Simplify the outline." % (len(pts), MAX_CONVEX_INPUT))
    tris = triangulate(pts)
    pieces = [list(t) for t in tris]

    def ccw_convex(poly):
        P = [pts[i] for i in poly]
        return convex(P)

    i = 0
    while i < len(pieces):
        j = i + 1
        while j < len(pieces):
            A, B = pieces[i], pieces[j]
            shared = None
            for ai in range(len(A)):
                u, v = A[ai], A[(ai + 1) % len(A)]
                for bi in range(len(B)):
                    if B[bi] == v and B[(bi + 1) % len(B)] == u:
                        shared = (ai, bi)
                        break
                if shared:
                    break
            if shared:
                ai, bi = shared
                new = [A[(ai + 1 + k) % len(A)] for k in range(len(A))] + [B[(bi + 2 + k) % len(B)] for k in range(len(B) - 2)]
                if len(set(new)) == len(new) and ccw_convex(new):
                    pieces[i] = new
                    del pieces[j]
                    continue
            j += 1
        i += 1
    return [[pts[k] for k in p] for p in pieces]
