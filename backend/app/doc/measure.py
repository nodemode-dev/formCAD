import math

from app.doc import curvepath, geom


class NoArea(Exception):
    pass


def segment_info(p0, p1, bulge):
    chord = geom.dist(p0, p1)
    if abs(bulge) < 1e-12 or chord < 1e-15:
        return chord, 0.0
    theta = 4.0 * math.atan(bulge)
    r = chord / (2.0 * math.sin(abs(theta) / 2.0))
    length = r * abs(theta)
    seg = (r * r / 2.0) * (abs(theta) - math.sin(abs(theta)))
    return length, math.copysign(seg, bulge)


def polygon_measure(verts, closed=True):
    n = len(verts)
    if n < 2:
        return 0.0, 0.0
    s = 0.0
    perim = 0.0
    seg_area = 0.0
    for i in range(n):
        a, b = verts[i], verts[(i + 1) % n]
        s += a["p"][0] * b["p"][1] - b["p"][0] * a["p"][1]
        if closed or i < n - 1:
            length, seg = segment_info(a["p"], b["p"], a.get("bulge", 0.0) or 0.0)
            perim += length
            seg_area += seg
    area = s / 2.0
    if area < 0:
        area = -area
        seg_area = -seg_area
    return area + seg_area, perim


def ellipse_perimeter(a: float, b: float, t0: float = 0.0, t1: float = math.tau, steps: int = 4000) -> float:
    n = steps if steps % 2 == 0 else steps + 1
    h = (t1 - t0) / n
    total = 0.0
    for i in range(n + 1):
        t = t0 + i * h
        f = math.hypot(a * math.sin(t), b * math.cos(t))
        w = 1 if i in (0, n) else (4 if i % 2 else 2)
        total += w * f
    return total * h / 3.0


def _sample_loop(loop, per=64):
    verts = loop.get("vertices", [])
    pts = []
    n = len(verts)
    for i in range(n):
        a, b = verts[i], verts[(i + 1) % n]
        bulge = a.get("bulge", 0.0) or 0.0
        pts.append((a["p"][0], a["p"][1]))
        arc = geom.bulge_to_arc(a["p"], b["p"], bulge) if abs(bulge) > 1e-12 else None
        if arc:
            c, r, a0, a1, ccw = arc
            sweep = 4.0 * math.atan(bulge)
            start = geom.angle_of(c, a["p"])
            for k in range(1, per):
                t = start + sweep * k / per
                pts.append((c[0] + r * math.cos(t), c[1] + r * math.sin(t)))
    return pts


def _poly_area(pts):
    s = 0.0
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        s += a[0] * b[1] - b[0] * a[1]
    return abs(s) / 2.0


def _inside(pt, poly):
    x, y = pt
    c = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            c = not c
        j = i
    return c


def loops_measure(loops):
    polys = [_sample_loop(lp) for lp in loops if len(lp.get("vertices", [])) >= 2]
    if not polys:
        raise NoArea()
    area = 0.0
    perim = 0.0
    for i, poly in enumerate(polys):
        depth = sum(1 for j, other in enumerate(polys) if j != i and _inside(poly[0], other))
        a = _poly_area(poly)
        area += a if depth % 2 == 0 else -a
        for k in range(len(poly)):
            perim += geom.dist(poly[k], poly[(k + 1) % len(poly)])
    return area, perim


def entity_measure(e):
    k = e.kind
    if k == "circle":
        return math.pi * e.radius**2, 2.0 * math.pi * e.radius
    if k == "ellipse":
        a = math.hypot(e.major[0], e.major[1])
        b = a * e.ratio
        full = abs(e.end_param - e.start_param) >= geom.TAU - 1e-12
        if not full:
            raise NoArea()
        return math.pi * a * b, ellipse_perimeter(a, b)
    if k == "lwpolyline":
        return polygon_measure(e.vertices, bool(e.closed))
    if k == "spline":
        cur = curvepath.build(e)
        if cur is None or cur.length <= 0:
            raise NoArea()
        n = 2000
        pts = [cur.at(cur.length * i / n)[0] for i in range(n)]
        return _poly_area([(p[0], p[1]) for p in pts]), cur.length
    if k == "polyline3d":
        pts = [(p[0], p[1]) for p in e.points]
        if len(pts) < 3:
            raise NoArea()
        per = sum(geom.dist(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts) if e.closed else len(pts) - 1))
        return _poly_area(pts), per
    if k == "hatch" or hasattr(e, "loops"):
        return loops_measure(e.loops)
    if k in ("solid", "wipeout"):
        pts = [(p[0], p[1]) for p in (e.corners if k == "solid" else e.points)]
        if k == "solid" and len(pts) == 4:
            pts = [pts[0], pts[1], pts[3], pts[2]]
        if len(pts) < 3:
            raise NoArea()
        return _poly_area(pts), sum(geom.dist(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts)))
    raise NoArea()


def line_dir(e, point=None):
    if e.kind == "line":
        return e.start, e.end
    if e.kind == "lwpolyline":
        best, bd = None, None
        n = len(e.vertices)
        count = n if e.closed else n - 1
        for i in range(count):
            a, b = e.vertices[i], e.vertices[(i + 1) % n]
            if abs(a.get("bulge", 0.0) or 0.0) > 1e-12:
                continue
            d = seg_distance(point, a["p"], b["p"]) if point is not None else 0.0
            if bd is None or d < bd:
                best, bd = (a["p"], b["p"]), d
        return best if best else (None, None)
    return None, None


def seg_distance(pt, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((pt[0] - a[0]) * dx + (pt[1] - a[1]) * dy) / L))
    return math.hypot(pt[0] - (a[0] + t * dx), pt[1] - (a[1] + t * dy))


def poly_arc_at(e, point):
    n = len(e.vertices)
    count = n if e.closed else n - 1
    best, bd = None, None
    for i in range(count):
        a, b = e.vertices[i], e.vertices[(i + 1) % n]
        bulge = a.get("bulge", 0.0) or 0.0
        arc = geom.bulge_to_arc(a["p"], b["p"], bulge) if abs(bulge) > 1e-12 else None
        if arc:
            c, r, a0, a1, ccw = arc
            d = abs(geom.dist(c, point) - r)
        else:
            d = seg_distance(point, a["p"], b["p"])
        if bd is None or d < bd:
            best, bd = (arc, bulge), d
    return best


def angle_between_lines(a0, a1, b0, b1):
    d1 = (a1[0] - a0[0], a1[1] - a0[1])
    d2 = (b1[0] - b0[0], b1[1] - b0[1])
    n = math.hypot(*d1) * math.hypot(*d2)
    if n == 0:
        return None
    cr = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(cr) < 1e-12 * n:
        return None
    c = max(-1.0, min(1.0, (d1[0] * d2[0] + d1[1] * d2[1]) / n))
    return math.acos(c)
