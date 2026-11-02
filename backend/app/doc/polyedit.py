import copy
import math

from app.doc import geom, nurbs

TOL = 1e-9
JOIN_MERGE = 1e-6


def clone_verts(verts):
    return copy.deepcopy(verts)


def vertex(p, bulge=0.0, sw=0.0, ew=0.0):
    return {"p": [float(p[0]), float(p[1])], "bulge": float(bulge), "sw": float(sw), "ew": float(ew)}


def reverse_vertices(verts, closed):
    n = len(verts)
    out = []
    for k in range(n):
        if closed:
            src = verts[(-k) % n]
            seg = verts[(-k - 1) % n]
        else:
            src = verts[n - 1 - k]
            seg = verts[n - 2 - k] if k < n - 1 else None
        v = copy.deepcopy(src)
        if seg is None:
            v["bulge"] = 0.0
            v["sw"] = 0.0
            v["ew"] = 0.0
        else:
            v["bulge"] = -(seg.get("bulge", 0.0) or 0.0)
            v["sw"] = seg.get("ew", 0.0)
            v["ew"] = seg.get("sw", 0.0)
        out.append(v)
    return out


def _unit(v):
    n = math.hypot(v[0], v[1])
    return None if n < TOL else [v[0] / n, v[1] / n]


def _sub(a, b):
    return [a[0] - b[0], a[1] - b[1]]


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _rot(v, a):
    return [v[0] * math.cos(a) - v[1] * math.sin(a), v[0] * math.sin(a) + v[1] * math.cos(a)]


def seg_count(verts, closed):
    n = len(verts)
    return n if closed else n - 1


def vertex_tangents(verts, closed):
    n = len(verts)
    pts = [v["p"] for v in verts]
    out = [None] * n
    for i in range(n):
        tg = verts[i].get("tg")
        if isinstance(tg, (int, float)):
            out[i] = [math.cos(tg), math.sin(tg)]
    for i in range(n):
        if out[i] is not None:
            continue
        if not closed and (i == 0 or i == n - 1):
            continue
        a, b, c = pts[(i - 1) % n], pts[i], pts[(i + 1) % n]
        d1, d2 = _unit(_sub(b, a)), _unit(_sub(c, b))
        if d1 is None or d2 is None:
            out[i] = d1 or d2 or [1.0, 0.0]
            continue
        cr = _cross(d1, d2)
        if abs(cr) < 1e-12:
            out[i] = d1
            continue
        va, vb = _sub(a, c), _sub(b, c)
        alpha = abs(math.atan2(_cross(va, vb), _dot(va, vb)))
        out[i] = _rot(d1, alpha if cr > 0 else -alpha)
    if not closed and n >= 2:
        for i, nb in ((0, 1), (n - 1, n - 2)):
            if out[i] is not None:
                continue
            chord = _unit(_sub(pts[1], pts[0])) if i == 0 else _unit(_sub(pts[n - 1], pts[n - 2]))
            other = out[nb]
            if other is None or chord is None:
                out[i] = chord or [1.0, 0.0]
            else:
                k = 2.0 * _dot(other, chord)
                out[i] = [k * chord[0] - other[0], k * chord[1] - other[1]]
    return out


def biarc(p0, t0, p1, t1):
    v = _sub(p1, p0)
    vv = _dot(v, v)
    t = [t0[0] + t1[0], t0[1] + t1[1]]
    a = _dot(t, t) - 4.0
    b = -2.0 * _dot(v, t)
    if abs(a) < 1e-12:
        if abs(b) < 1e-14:
            return None
        d = -vv / b
    else:
        disc = b * b - 4.0 * a * vv
        if disc < 0:
            return None
        root = math.sqrt(disc)
        roots = [r for r in ((-b - root) / (2 * a), (-b + root) / (2 * a)) if r > 1e-12]
        if not roots:
            return None
        d = min(roots)
    p2 = [p0[0] + d * t0[0], p0[1] + d * t0[1]]
    p3 = [p1[0] - d * t1[0], p1[1] - d * t1[1]]
    j = [(p2[0] + p3[0]) / 2.0, (p2[1] + p3[1]) / 2.0]
    tj = _unit(_sub(p3, p2))
    c1 = _unit(_sub(j, p0))
    c2 = _unit(_sub(p1, j))
    if tj is None or c1 is None or c2 is None:
        return None
    f1 = math.atan2(_cross(t0, c1), _dot(t0, c1))
    f2 = math.atan2(_cross(tj, c2), _dot(tj, c2))
    return j, math.tan(f1 / 2.0), math.tan(f2 / 2.0)


def fit_biarcs(verts, closed):
    n = len(verts)
    if n < 3 and not (n == 2 and not closed):
        raise ValueError("Cannot fit that polyline.")
    tans = vertex_tangents(verts, closed)
    out = []
    for i in range(seg_count(verts, closed)):
        a, b = verts[i], verts[(i + 1) % n]
        res = biarc(a["p"], tans[i], b["p"], tans[(i + 1) % n])
        first = copy.deepcopy(a)
        if res is None:
            first["bulge"] = 0.0
            out.append(first)
            continue
        j, b1, b2 = res
        first["bulge"] = b1
        out.append(first)
        out.append(vertex(j, b2, a.get("ew", 0.0), a.get("ew", 0.0)))
    if not closed:
        last = copy.deepcopy(verts[-1])
        last["bulge"] = 0.0
        out.append(last)
    return out


def spline_vertices(verts, closed, segs):
    pts = [[v["p"][0], v["p"][1], 0.0] for v in verts]
    if len(pts) < 3:
        raise ValueError("A spline frame needs at least three vertices.")
    curve = nurbs.from_control_points(pts, 3, closed)
    lo, hi = curve.domain()
    count = max(abs(int(segs)), 2) * (len(pts) if closed else len(pts) - 1)
    out = []
    for k in range(count + (0 if closed else 1)):
        u = lo + (hi - lo) * k / count
        q = nurbs.point_at(curve, u)
        out.append(vertex(q))
    w = verts[0].get("sw", 0.0)
    for v in out:
        v["sw"] = v["ew"] = w
    return out


def arc_end_points(e):
    a0, a1 = e.start_angle, e.end_angle
    return geom.polar(e.center, e.radius, a0)[:2], geom.polar(e.center, e.radius, a1)[:2], math.tan(geom.ccw_sweep(a0, a1) / 4.0)


def pieces_of(e):
    if e.kind == "line":
        return [vertex(e.start), vertex(e.end)], False
    if e.kind == "arc":
        p0, p1, b = arc_end_points(e)
        return [vertex(p0, b), vertex(p1)], False
    if e.kind == "lwpolyline":
        return clone_verts(e.vertices), bool(e.closed)
    return None, False


def _same(a, b, tol):
    return math.hypot(a[0] - b[0], a[1] - b[1]) <= tol


def join_chain(base, cands, fuzz):
    chain = clone_verts(base)
    left = list(cands)
    used = []
    progress = True
    while progress and left:
        progress = False
        for item in list(left):
            vs, closed = item[1], item[2]
            if closed or len(vs) < 2:
                continue
            tail = chain[-1]["p"]
            head = chain[0]["p"]
            tol = max(fuzz, JOIN_MERGE)
            options = (
                ("tail_start", _same(tail, vs[0]["p"], tol), vs, tail),
                ("tail_end", _same(tail, vs[-1]["p"], tol), reverse_vertices(vs, False), tail),
                ("head_end", _same(head, vs[-1]["p"], tol), vs, head),
                ("head_start", _same(head, vs[0]["p"], tol), reverse_vertices(vs, False), head),
            )
            for kind, ok, seq, anchor in options:
                if not ok:
                    continue
                seq = clone_verts(seq)
                if kind.startswith("tail"):
                    gap = math.hypot(anchor[0] - seq[0]["p"][0], anchor[1] - seq[0]["p"][1])
                    if gap <= JOIN_MERGE:
                        chain[-1]["bulge"] = seq[0].get("bulge", 0.0)
                        chain.extend(seq[1:])
                    else:
                        chain[-1]["bulge"] = 0.0
                        chain.extend(seq)
                else:
                    gap = math.hypot(anchor[0] - seq[-1]["p"][0], anchor[1] - seq[-1]["p"][1])
                    if gap <= JOIN_MERGE:
                        chain = seq[:-1] + chain
                    else:
                        seq[-1]["bulge"] = 0.0
                        chain = seq + chain
                used.append(item[0])
                left.remove(item)
                progress = True
                break
    return chain, used


def straighten(verts, closed, a, b):
    n = len(verts)
    out = clone_verts(verts)
    if a == b:
        out[a]["bulge"] = 0.0
        return out
    if closed:
        idx = [(a + k) % n for k in range(1, (b - a) % n)]
        out[a]["bulge"] = 0.0
        return [v for k, v in enumerate(out) if k not in idx]
    lo, hi = min(a, b), max(a, b)
    out[lo]["bulge"] = 0.0
    return out[: lo + 1] + out[hi:]


def break_between(verts, closed, a, b):
    n = len(verts)
    if closed:
        if a == b:
            return [rotate_from(verts, a, n + 1)]
        seq = [(b + k) % n for k in range((a - b) % n + 1)]
        part = [copy.deepcopy(verts[k]) for k in seq]
        part[-1]["bulge"] = 0.0
        return [part]
    lo, hi = min(a, b), max(a, b)
    first = clone_verts(verts[: lo + 1])
    first[-1]["bulge"] = 0.0
    second = clone_verts(verts[hi:])
    out = []
    if len(first) >= 2:
        out.append(first)
    if len(second) >= 2:
        out.append(second)
    return out


def rotate_from(verts, start, count):
    n = len(verts)
    part = [copy.deepcopy(verts[(start + k) % n]) for k in range(count)]
    part[-1]["bulge"] = 0.0
    return part
