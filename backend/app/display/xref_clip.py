import math

from app.display import flatten, insert, shapes
from app.doc import xclip

GEOM_KEYS = ("type", "p1", "p2", "c", "r", "a0", "a1", "major", "ratio", "verts", "closed", "elev", "ctrl", "fit", "p", "size", "rot", "insert", "height", "box", "dir")
EPS = 1e-12


def inside(poly, x, y):
    return flatten.point_in_ring(x, y, poly)


def _cut(p, q, a, b):
    rx, ry = q[0] - p[0], q[1] - p[1]
    sx, sy = b[0] - a[0], b[1] - a[1]
    den = rx * sy - ry * sx
    if abs(den) < EPS:
        return None
    t = ((a[0] - p[0]) * sy - (a[1] - p[1]) * sx) / den
    u = ((a[0] - p[0]) * ry - (a[1] - p[1]) * rx) / den
    if 0.0 < t < 1.0 and -1e-9 <= u <= 1.0 + 1e-9:
        return t
    return None


def clip_segment(p, q, poly, invert):
    ts = [0.0, 1.0]
    n = len(poly)
    for i in range(n):
        t = _cut(p, q, poly[i], poly[(i + 1) % n])
        if t is not None:
            ts.append(t)
    ts.sort()
    out = []
    for i in range(len(ts) - 1):
        t0, t1 = ts[i], ts[i + 1]
        if t1 - t0 < 1e-12:
            continue
        tm = (t0 + t1) / 2.0
        mx, my = p[0] + (q[0] - p[0]) * tm, p[1] + (q[1] - p[1]) * tm
        if inside(poly, mx, my) != invert:
            out.append(((p[0] + (q[0] - p[0]) * t0, p[1] + (q[1] - p[1]) * t0), (p[0] + (q[0] - p[0]) * t1, p[1] + (q[1] - p[1]) * t1)))
    return out


def clip_path(pts, closed, poly, invert):
    runs = []
    cur = None
    n = len(pts)
    count = n if closed else n - 1
    for i in range(max(count, 0)):
        a, b = pts[i], pts[(i + 1) % n]
        for s, e in clip_segment(a, b, poly, invert):
            if cur is not None and abs(cur[-1][0] - s[0]) < 1e-9 and abs(cur[-1][1] - s[1]) < 1e-9:
                cur.append(e)
            else:
                cur = [s, e]
                runs.append(cur)
    if n == 1 and (inside(poly, pts[0][0], pts[0][1]) != invert):
        runs.append([pts[0]])
    return runs


def _props(part):
    return {k: v for k, v in part.items() if k not in GEOM_KEYS}


def _poly_part(run, base):
    out = _props(base)
    out.update({"type": "poly", "verts": [[p[0], p[1], 0.0, 0.0, 0.0] for p in run], "closed": False, "elev": 0.0})
    return out


def _points_of(g):
    t = g["type"]
    if t == "circle":
        return flatten.arc_pts(g["c"][0], g["c"][1], g["r"], 0.0, 2 * math.pi)[:-1], True
    if t == "arc":
        sweep = flatten.ccw(g["a0"], g["a1"]) or 2 * math.pi
        return flatten.arc_pts(g["c"][0], g["c"][1], g["r"], g["a0"], sweep), False
    if t == "ellipse":
        return flatten.ellipse_pts(g["c"], g["major"], g["ratio"], g["a0"], g["a1"]), False
    if t == "poly":
        return flatten.poly_pts(g["verts"], g["closed"]), g["closed"]
    return None, False


def clip_part(g, poly, invert):
    t = g["type"]
    if t == "line":
        out = []
        for s, e in clip_segment(g["p1"], g["p2"], poly, invert):
            q = dict(g)
            q["p1"], q["p2"] = [s[0], s[1]], [e[0], e[1]]
            out.append(q)
        return out
    pts, closed = _points_of(g)
    if pts is not None:
        return [_poly_part(r, g) for r in clip_path(pts, closed, poly, invert) if len(r) > 1]
    if t == "point":
        return [g] if inside(poly, g["p"][0], g["p"][1]) != invert else []
    if t == "text":
        return [g] if inside(poly, g["insert"][0], g["insert"][1]) != invert else []
    if t == "spline":
        ps = g.get("fit") or g.get("ctrl") or []
        flags = [inside(poly, p[0], p[1]) != invert for p in ps]
        return [g] if any(flags) or not flags else []
    return [g]


def convex(poly):
    sign = 0
    n = len(poly)
    for i in range(n):
        a, b, c = poly[i], poly[(i + 1) % n], poly[(i + 2) % n]
        z = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        if abs(z) < 1e-12:
            continue
        s = 1 if z > 0 else -1
        if sign and s != sign:
            return False
        sign = s
    return True


def _sutherland(ring, poly):
    if area(poly) < 0:
        poly = list(reversed(poly))
    out = ring
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        src, out = out, []
        if not src:
            break
        prev = src[-1]
        for cur in src:
            c_in = (b[0] - a[0]) * (cur[1] - a[1]) - (b[1] - a[1]) * (cur[0] - a[0]) >= 0
            p_in = (b[0] - a[0]) * (prev[1] - a[1]) - (b[1] - a[1]) * (prev[0] - a[0]) >= 0
            if c_in != p_in:
                t = _cut_line(prev, cur, a, b)
                if t is not None:
                    out.append((prev[0] + (cur[0] - prev[0]) * t, prev[1] + (cur[1] - prev[1]) * t))
            if c_in:
                out.append(cur)
            prev = cur
    return out


def _cut_line(p, q, a, b):
    rx, ry = q[0] - p[0], q[1] - p[1]
    sx, sy = b[0] - a[0], b[1] - a[1]
    den = rx * sy - ry * sx
    if abs(den) < EPS:
        return None
    return ((a[0] - p[0]) * sy - (a[1] - p[1]) * sx) / den


def area(poly):
    s = 0.0
    for i, p in enumerate(poly):
        q = poly[(i + 1) % len(poly)]
        s += p[0] * q[1] - q[0] * p[1]
    return s / 2.0


def clip_prims(prims, poly, invert):
    out = []
    is_convex = convex(poly)
    for p in prims:
        if p["t"] == "fill":
            rings = []
            for r in p["rings"]:
                pts = [(r[i], r[i + 1]) for i in range(0, len(r), 2)]
                if not pts:
                    continue
                if is_convex and not invert:
                    c = _sutherland(pts, poly)
                    if len(c) >= 3:
                        rings.append(flatten.flat_xy(c))
                else:
                    cx = sum(q[0] for q in pts) / len(pts)
                    cy = sum(q[1] for q in pts) / len(pts)
                    if inside(poly, cx, cy) != invert:
                        rings.append(list(r))
            if rings:
                q = dict(p)
                q["rings"] = rings
                out.append(q)
            continue
        flat = p["pts"]
        pts = [(flat[i], flat[i + 1]) for i in range(0, len(flat), 2)]
        for run in clip_path(pts, bool(p.get("closed")), poly, invert):
            if len(run) > 1:
                q = dict(p)
                q["pts"] = flatten.flat_xy(run)
                q["closed"] = False
                out.append(q)
    return out


def _parts(g):
    return g["parts"] if g.get("type") == "compound" else [g]


def clipped(e, ctx):
    res = ORIGINAL(e, ctx)
    clip = xclip.get(e)
    if not res or clip is None or not clip.get("on", True):
        return res
    g, prims, grips, bb = res
    poly = [(float(p[0]), float(p[1])) for p in clip["points"]]
    invert = bool(clip.get("invert"))
    parts = []
    for part in _parts(g):
        parts.extend(clip_part(part, poly, invert))
    prims = clip_prims(prims, poly, invert)
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    if bb is not None and not invert:
        bb = [max(bb[0], min(xs)), max(bb[1], min(ys)), min(bb[2], max(xs)), min(bb[3], max(ys))]
        if bb[0] > bb[2] or bb[1] > bb[3]:
            bb = [e.position[0], e.position[1], e.position[0], e.position[1]]
    return {"type": "compound", "parts": parts}, prims, grips, bb


ORIGINAL = insert.insert
shapes.BUILDERS["insert"] = clipped
