import math

from app.dim import vec as V
from app.doc import geom
from app.doc.entities import Arc, Circle, Ellipse, Line, LwPolyline


def shapes_of(e):
    out = []
    if isinstance(e, Line):
        out.append(("line", V.xy(e.start), V.xy(e.end)))
    elif isinstance(e, Circle):
        out.append(("arc", V.xy(e.center), float(e.radius), 0.0, 2 * math.pi))
    elif isinstance(e, Arc):
        out.append(("arc", V.xy(e.center), float(e.radius), float(e.start_angle), geom.ccw_sweep(e.start_angle, e.end_angle)))
    elif isinstance(e, LwPolyline):
        n = len(e.vertices)
        cnt = n if e.closed else n - 1
        for i in range(max(cnt, 0)):
            v0, v1 = e.vertices[i], e.vertices[(i + 1) % n]
            b = float(v0.get("bulge", 0.0) or 0.0)
            arc = geom.bulge_to_arc(v0["p"], v1["p"], b) if abs(b) > 1e-12 else None
            if arc is None:
                out.append(("line", V.xy(v0["p"]), V.xy(v1["p"])))
            else:
                c, r, a0, a1, _ccw = arc
                out.append(("arc", V.xy(c), float(r), float(a0), geom.ccw_sweep(a0, a1)))
    elif isinstance(e, Ellipse):
        pts = []
        major = V.xy(e.major)
        ratio = float(e.ratio)
        c = V.xy(e.center)
        minor = (-major[1] * ratio, major[0] * ratio)
        n = 96
        for i in range(n + 1):
            t = 2 * math.pi * i / n
            pts.append((c[0] + major[0] * math.cos(t) + minor[0] * math.sin(t), c[1] + major[1] * math.cos(t) + minor[1] * math.sin(t)))
        for i in range(n):
            out.append(("line", pts[i], pts[i + 1]))
    return out


def seg_hits(p, q, shape):
    d = V.sub(q, p)
    ln = V.length(d)
    if ln < 1e-12:
        return []
    u = V.mul(d, 1.0 / ln)
    hits = []
    if shape[0] == "line":
        a, b = shape[1], shape[2]
        e = V.sub(b, a)
        den = V.cross(u, e)
        if abs(den) < 1e-12:
            return []
        t = V.cross(V.sub(a, p), e) / den
        s = V.cross(V.sub(a, p), u) / den
        if -1e-9 <= t <= ln + 1e-9 and -1e-9 <= s <= 1 + 1e-9:
            hits.append(V.add(p, V.mul(u, t)))
        return hits
    c, r, a0, sweep = shape[1], shape[2], shape[3], shape[4]
    f = V.sub(p, c)
    bq = V.dot(f, u)
    cq = V.dot(f, f) - r * r
    disc = bq * bq - cq
    if disc < 0:
        return []
    sq = math.sqrt(disc)
    for t in (-bq - sq, -bq + sq):
        if -1e-9 <= t <= ln + 1e-9:
            pt = V.add(p, V.mul(u, t))
            off = V.ccw(a0, V.ang_of(V.sub(pt, c)))
            if sweep >= 2 * math.pi - 1e-9 or off <= sweep + 1e-9:
                hits.append(pt)
    return hits
