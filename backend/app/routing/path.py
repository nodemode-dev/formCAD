import math

import numpy as np

MAX_POINTS = 2000
EPS = 1e-9


class PathError(ValueError):
    pass


def _pts(points):
    a = np.asarray(points, dtype=float)
    if a.ndim != 2 or a.shape[1] not in (2, 3):
        raise PathError("A route needs a list of 2 or 3 coordinate points.")
    if len(a) < 2:
        raise PathError("A route needs at least two points.")
    if len(a) > MAX_POINTS:
        raise PathError("A route is limited to %d points." % MAX_POINTS)
    if a.shape[1] == 2:
        a = np.hstack([a, np.zeros((len(a), 1))])
    keep = [0]
    for i in range(1, len(a)):
        if np.linalg.norm(a[i] - a[keep[-1]]) > EPS:
            keep.append(i)
    a = a[keep]
    if len(a) < 2:
        raise PathError("A route needs two distinct points.")
    return a


def _r3(v):
    return [round(float(x), 6) for x in v]


def fillet_polyline(points, radius, min_radius=None):
    a = _pts(points)
    r = float(radius)
    if r < 0:
        raise PathError("Bend radius cannot be negative.")
    need = float(min_radius) if min_radius is not None else r
    n = len(a)
    seg = [np.linalg.norm(a[i + 1] - a[i]) for i in range(n - 1)]
    dirs = [(a[i + 1] - a[i]) / seg[i] for i in range(n - 1)]
    corners = {}
    for i in range(1, n - 1):
        d0, d1 = dirs[i - 1], dirs[i]
        c = float(np.clip(np.dot(d0, d1), -1.0, 1.0))
        theta = math.acos(c)
        if theta < 1e-6:
            continue
        if math.pi - theta < 1e-6:
            raise PathError("The route doubles back on itself at point %d." % i)
        corners[i] = {"theta": theta, "want": r}
    trim = [0.0] * n
    eff = {}
    for i, c in corners.items():
        half = math.tan(c["theta"] / 2.0)
        t_want = r * half
        room_a = float(seg[i - 1]) * (0.5 if (i - 1) in corners else 1.0)
        room_b = float(seg[i]) * (0.5 if (i + 1) in corners else 1.0)
        t = min(t_want, room_a, room_b)
        eff[i] = float(t / half) if half > EPS else 0.0
        trim[i] = t
    pieces = []
    length = 0.0
    cur = a[0]
    tight = math.inf
    flags = []
    for i in range(1, n):
        if i in corners:
            t = trim[i]
            d0, d1 = dirs[i - 1], dirs[i]
            p0 = a[i] - d0 * t
            p1 = a[i] + d1 * t
            if np.linalg.norm(p0 - cur) > EPS:
                pieces.append({"k": "line", "a": _r3(cur), "b": _r3(p0)})
                length += float(np.linalg.norm(p0 - cur))
            th = corners[i]["theta"]
            rr = eff[i]
            bis = (d1 - d0)
            bn = np.linalg.norm(bis)
            centre = a[i] + (bis / bn) * (rr / math.cos(th / 2.0)) if bn > EPS else a[i]
            pieces.append({"k": "arc", "a": _r3(p0), "b": _r3(p1), "c": _r3(centre), "r": round(rr, 6), "angle": round(th, 6)})
            length += rr * th
            tight = min(tight, rr)
            if rr + 1e-6 < need:
                flags.append({"index": i, "point": _r3(a[i]), "radius": round(rr, 4), "required": round(need, 4)})
            cur = p1
    if np.linalg.norm(a[-1] - cur) > EPS:
        pieces.append({"k": "line", "a": _r3(cur), "b": _r3(a[-1])})
        length += float(np.linalg.norm(a[-1] - cur))
    return {"mode": "fillet", "pieces": pieces, "length": round(length, 4), "tightest": None if tight is math.inf else round(tight, 4), "required": round(need, 4), "violations": flags, "ok": not flags}


def sample(path, step=2.0):
    out = []
    for p in path["pieces"]:
        a = np.array(p["a"])
        b = np.array(p["b"])
        if p["k"] == "line":
            k = max(1, int(math.ceil(np.linalg.norm(b - a) / step)))
            for j in range(k):
                out.append(_r3(a + (b - a) * (j / k)))
        else:
            c = np.array(p["c"])
            u = a - c
            v = b - c
            k = max(2, int(math.ceil(p["r"] * p["angle"] / step)))
            w = np.cross(np.cross(u, v), u)
            wn = np.linalg.norm(w)
            w = w / wn * np.linalg.norm(u) if wn > EPS else v
            for j in range(k):
                t = p["angle"] * j / k
                out.append(_r3(c + u * math.cos(t) + w * math.sin(t)))
    last = path["pieces"][-1]["b"]
    out.append(list(last))
    return out


def spline_path(points, required=0.0, per_span=24):
    a = _pts(points)
    n = len(a)
    if n == 2:
        samples = [a[0], a[1]]
    else:
        ext = np.vstack([2 * a[0] - a[1], a, 2 * a[-1] - a[-2]])
        samples = []
        for i in range(1, n):
            p0, p1, p2, p3 = ext[i - 1], ext[i], ext[i + 1], ext[i + 2]
            t0 = 0.0
            t1 = t0 + max(np.linalg.norm(p1 - p0), EPS) ** 0.5
            t2 = t1 + max(np.linalg.norm(p2 - p1), EPS) ** 0.5
            t3 = t2 + max(np.linalg.norm(p3 - p2), EPS) ** 0.5
            for j in range(per_span):
                t = t1 + (t2 - t1) * j / per_span
                a1 = (t1 - t) / (t1 - t0) * p0 + (t - t0) / (t1 - t0) * p1
                a2 = (t2 - t) / (t2 - t1) * p1 + (t - t1) / (t2 - t1) * p2
                a3 = (t3 - t) / (t3 - t2) * p2 + (t - t2) / (t3 - t2) * p3
                b1 = (t2 - t) / (t2 - t0) * a1 + (t - t0) / (t2 - t0) * a2
                b2 = (t3 - t) / (t3 - t1) * a2 + (t - t1) / (t3 - t1) * a3
                samples.append((t2 - t) / (t2 - t1) * b1 + (t - t1) / (t2 - t1) * b2)
        samples.append(a[-1])
    s = np.array(samples)
    length = float(np.sum(np.linalg.norm(np.diff(s, axis=0), axis=1)))
    tight = math.inf
    flags = []
    for i in range(1, len(s) - 1):
        u = s[i] - s[i - 1]
        v = s[i + 1] - s[i]
        w = s[i + 1] - s[i - 1]
        cr = np.linalg.norm(np.cross(u, v))
        den = np.linalg.norm(u) * np.linalg.norm(v) * np.linalg.norm(w)
        rad = den / (2.0 * cr) if cr > 1e-12 else math.inf
        if rad < tight:
            tight = rad
        if rad + 1e-6 < required:
            flags.append({"index": i, "point": _r3(s[i]), "radius": round(rad, 4), "required": round(float(required), 4)})
    return {"mode": "spline", "samples": [_r3(p) for p in s], "length": round(length, 4), "tightest": None if tight is math.inf else round(tight, 4), "required": round(float(required), 4), "violations": flags[:50], "ok": not flags}
