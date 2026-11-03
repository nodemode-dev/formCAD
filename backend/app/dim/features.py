import math

from app.doc import geom
from app.drawann import viewsrc
from app.doc.entities import Arc, Circle, Ellipse, Insert, Line, LwPolyline, MText, Point, Spline, Text

RANK = {"start": 0, "end": 0, "vertex": 0, "center": 1, "mid": 2, "segmid": 2, "ins": 0, "pos": 0}


def _p(v):
    return (float(v[0]), float(v[1]))


def feature_point(e, link):
    t = link.get("t")
    if isinstance(e, Line):
        if t == "start":
            return _p(e.start)
        if t == "end":
            return _p(e.end)
        if t == "mid":
            return ((e.start[0] + e.end[0]) / 2.0, (e.start[1] + e.end[1]) / 2.0)
    elif isinstance(e, Arc):
        a0, a1 = e.start_angle, e.end_angle
        if t == "start":
            return _p(geom.polar(e.center, e.radius, a0))
        if t == "end":
            return _p(geom.polar(e.center, e.radius, a1))
        if t == "mid":
            return _p(geom.polar(e.center, e.radius, a0 + geom.ccw_sweep(a0, a1) / 2.0))
        if t == "center":
            return _p(e.center)
        if t == "ang":
            return _p(geom.polar(e.center, e.radius, float(link.get("a", 0.0))))
    elif isinstance(e, Circle):
        if t == "center":
            return _p(e.center)
        if t == "ang":
            return _p(geom.polar(e.center, e.radius, float(link.get("a", 0.0))))
    elif isinstance(e, Ellipse):
        if t == "center":
            return _p(e.center)
    elif isinstance(e, LwPolyline):
        i = int(link.get("i", -1))
        n = len(e.vertices)
        if t == "vertex" and 0 <= i < n:
            return _p(e.vertices[i]["p"])
        if t == "segmid" and 0 <= i < n and (i + 1 < n or e.closed):
            a, b = e.vertices[i]["p"], e.vertices[(i + 1) % n]["p"]
            return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
    elif isinstance(e, Point):
        if t == "start":
            return _p(e.position)
    elif isinstance(e, (Insert, Text, MText)):
        if t == "ins":
            return _p(getattr(e, "align_point", None) or e.position) if isinstance(e, Text) else _p(e.position)
    elif isinstance(e, Spline):
        pts = e.fit_points or e.control_points
        if pts and t == "start":
            return _p(pts[0])
        if pts and t == "end":
            return _p(pts[-1])
    return None


def features_of(e):
    out = []
    if isinstance(e, Line):
        out += [({"t": "start"}), ({"t": "end"}), ({"t": "mid"})]
    elif isinstance(e, Arc):
        out += [{"t": "start"}, {"t": "end"}, {"t": "center"}, {"t": "mid"}]
    elif isinstance(e, (Circle, Ellipse)):
        out += [{"t": "center"}]
    elif isinstance(e, LwPolyline):
        n = len(e.vertices)
        out += [{"t": "vertex", "i": i} for i in range(n)]
        cnt = n if e.closed else n - 1
        out += [{"t": "segmid", "i": i} for i in range(max(cnt, 0))]
    elif isinstance(e, Point):
        out += [{"t": "start"}]
    elif isinstance(e, (Insert, Text, MText)):
        out += [{"t": "ins"}]
    elif isinstance(e, Spline):
        out += [{"t": "start"}, {"t": "end"}]
    return out


def find_link(d, p, space, tol):
    best = None
    px, py = float(p[0]), float(p[1])
    for e in d.entities(space):
        if e.kind == "dimension" or not d.visible(e):
            continue
        if viewsrc.is_view(e):
            hit = viewsrc.nearest_link(d, e, (px, py), tol)
            if hit:
                return hit
            continue
        for link in features_of(e):
            fp = feature_point(e, link)
            if fp is None:
                continue
            if abs(fp[0] - px) <= tol and abs(fp[1] - py) <= tol:
                rank = RANK.get(link["t"], 3)
                if best is None or rank < best[0]:
                    best = (rank, dict(link, h=e.handle))
                    if rank == 0:
                        return best[1]
    return best[1] if best else None


def circle_link(e, p):
    a = math.atan2(p[1] - e.center[1], p[0] - e.center[0])
    return {"h": e.handle, "t": "ang", "a": a}
