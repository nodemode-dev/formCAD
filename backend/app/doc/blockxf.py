import math

from app.doc import geom
from app.doc.entities import Arc, Circle, Ellipse, Insert, Line, LwPolyline, MText, Point, Polyline3d, Solid, Spline, Text
from app.text.model import affine, compose

ARC_STEP = math.pi / 18.0
MAX_COPIES = 10000


def insert_matrices(ent, rec):
    base = rec["base"] if rec else [0.0, 0.0, 0.0]
    sx = float(ent.scale[0]) if ent.scale else 1.0
    sy = float(ent.scale[1]) if ent.scale and len(ent.scale) > 1 else sx
    ca, sa = math.cos(ent.rotation), math.sin(ent.rotation)
    core = compose(affine(ca, sa, -sa, ca, ent.position[0], ent.position[1]), compose(affine(sx, 0.0, 0.0, sy, 0.0, 0.0), affine(1, 0, 0, 1, -base[0], -base[1])))
    arr = ent.array or {}
    rows = max(1, min(int(arr.get("rows", 1) or 1), 100))
    cols = max(1, min(int(arr.get("cols", arr.get("columns", 1)) or 1), 100))
    rs = float(arr.get("row_spacing", 0.0) or 0.0)
    cs = float(arr.get("col_spacing", arr.get("column_spacing", 0.0)) or 0.0)
    out = []
    for r in range(rows):
        for c in range(cols):
            dx, dy = c * cs, r * rs
            out.append(compose(affine(1, 0, 0, 1, dx * ca - dy * sa, dx * sa + dy * ca), core))
    return out


def _pt(m, p):
    z = p[2] if len(p) > 2 else 0.0
    return [m[0] * p[0] + m[2] * p[1] + m[4], m[1] * p[0] + m[3] * p[1] + m[5], z]


def _vec(m, v):
    return [m[0] * v[0] + m[2] * v[1], m[1] * v[0] + m[3] * v[1]]


def classify(m):
    sx = math.hypot(m[0], m[1])
    sy = math.hypot(m[2], m[3])
    dot = m[0] * m[2] + m[1] * m[3]
    det = m[0] * m[3] - m[1] * m[2]
    similar = abs(sx - sy) <= 1e-9 * max(sx, sy, 1e-12) and abs(dot) <= 1e-9 * max(sx * sy, 1e-12)
    return similar, det < 0, sx, sy, math.atan2(m[1], m[0])


def conjugate_ellipse(center, a_vec, b_vec, a0, a1):
    t0 = 0.5 * math.atan2(2.0 * (a_vec[0] * b_vec[0] + a_vec[1] * b_vec[1]), (a_vec[0] ** 2 + a_vec[1] ** 2) - (b_vec[0] ** 2 + b_vec[1] ** 2))

    def at(t):
        return [a_vec[0] * math.cos(t) + b_vec[0] * math.sin(t), a_vec[1] * math.cos(t) + b_vec[1] * math.sin(t)]

    u, v = at(t0), at(t0 + math.pi / 2.0)
    if math.hypot(v[0], v[1]) > math.hypot(u[0], u[1]):
        t0 += math.pi / 2.0
        u, v = at(t0), at(t0 + math.pi / 2.0)
    lu = math.hypot(u[0], u[1])
    lv = math.hypot(v[0], v[1])
    if lu < geom.EPS:
        return None
    ratio = max(min(lv / lu, 1.0), 1e-6)
    s0, s1 = a0 - t0, a1 - t0
    if u[0] * v[1] - u[1] * v[0] < 0:
        s0, s1 = -(a1 - t0), -(a0 - t0)
    full = abs(a1 - a0) >= geom.TAU - 1e-12
    ell = Ellipse(center=[center[0], center[1], 0.0], major=[u[0], u[1], 0.0], ratio=ratio)
    if full:
        ell.start_param, ell.end_param = 0.0, geom.TAU
    else:
        ell.start_param, ell.end_param = geom.norm_angle(s0), geom.norm_angle(s1)
    return ell


def _poly_points(verts, closed, m):
    n = len(verts)
    pts = []
    count = n if closed else n - 1
    for i in range(max(count, 0)):
        a, b = verts[i], verts[(i + 1) % n]
        pts.append(_pt(m, a["p"])[:2])
        arc = geom.bulge_to_arc(a["p"], b["p"], a.get("bulge", 0.0) or 0.0)
        if arc is not None:
            c, r, a0, a1, ccw = arc
            theta = 4.0 * math.atan(a["bulge"])
            start = geom.angle_of(c, a["p"])
            steps = max(2, int(math.ceil(abs(theta) / ARC_STEP)))
            for k in range(1, steps):
                pts.append(_pt(m, geom.polar(c, r, start + theta * k / steps))[:2])
    if not closed and n:
        pts.append(_pt(m, verts[-1]["p"])[:2])
    return pts


def apply_loose(e, m):
    k = e.kind
    if isinstance(e, Line):
        e.start, e.end = _pt(m, e.start), _pt(m, e.end)
        return e
    if isinstance(e, Point):
        e.position = _pt(m, e.position)
        return e
    if isinstance(e, Circle):
        a_vec, b_vec = _vec(m, [e.radius, 0.0]), _vec(m, [0.0, e.radius])
        out = conjugate_ellipse(_pt(m, e.center), a_vec, b_vec, 0.0, geom.TAU)
        return _carry(e, out)
    if isinstance(e, Arc):
        a_vec, b_vec = _vec(m, [e.radius, 0.0]), _vec(m, [0.0, e.radius])
        a1 = e.start_angle + geom.ccw_sweep(e.start_angle, e.end_angle)
        out = conjugate_ellipse(_pt(m, e.center), a_vec, b_vec, e.start_angle, a1)
        return _carry(e, out)
    if isinstance(e, Ellipse):
        u = e.major
        v = [-u[1] * e.ratio, u[0] * e.ratio]
        a1 = e.start_param + (geom.TAU if abs(e.end_param - e.start_param) < 1e-12 else geom.ccw_sweep(e.start_param, e.end_param))
        full = abs(e.end_param - e.start_param) >= geom.TAU - 1e-12 or abs(e.end_param - e.start_param) < 1e-12
        out = conjugate_ellipse(_pt(m, e.center), _vec(m, u), _vec(m, v), 0.0 if full else e.start_param, geom.TAU if full else a1)
        return _carry(e, out)
    if isinstance(e, LwPolyline):
        pts = _poly_points(e.vertices, e.closed, m)
        sx = math.hypot(m[0], m[1])
        e.vertices = [{"p": [p[0], p[1]], "bulge": 0.0, "sw": 0.0, "ew": 0.0} for p in pts]
        e.const_width *= sx
        return e
    if isinstance(e, Polyline3d):
        e.points = [_pt(m, p) for p in e.points]
        return e
    if isinstance(e, Solid):
        e.corners = [_pt(m, p) for p in e.corners]
        return e
    if isinstance(e, Spline):
        e.control_points = [_pt(m, p) for p in e.control_points]
        e.fit_points = [_pt(m, p) for p in e.fit_points]
        return e
    if isinstance(e, (Text, MText)):
        e.position = _pt(m, e.position)
        e.height *= math.hypot(m[2], m[3])
        e.rotation += math.atan2(m[1], m[0])
        return e
    if isinstance(e, Insert):
        e.position = _pt(m, e.position)
        e.rotation += math.atan2(m[1], m[0])
        sx, sy = math.hypot(m[0], m[1]), math.hypot(m[2], m[3])
        e.scale = [e.scale[0] * sx, e.scale[1] * sy, e.scale[2] if len(e.scale) > 2 else sx]
        return e
    return None


def _carry(src, out):
    if out is None:
        return None
    for name in ("layer", "color", "linetype", "lineweight", "ltscale", "transparency", "visible", "plot_style", "handle", "owner"):
        setattr(out, name, getattr(src, name))
    return out


def clone_through(e, m):
    from app.cmd import grips

    c = type(e).from_dict(e.to_dict())
    similar, mirror, sx, sy, theta = classify(m)
    if not similar:
        return apply_loose(c, m)
    origin = [0.0, 0.0]
    try:
        if abs(sx - 1.0) > 1e-12:
            grips.transform(c, grips.Xf("scale", origin, k=sx))
        if mirror:
            grips.transform(c, grips.Xf("mirror", origin, 0.0))
        if abs(theta) > 1e-12:
            grips.transform(c, grips.Xf("rotate", origin, theta))
    except grips.GripError:
        return None
    c.move_by([m[4], m[5], 0.0])
    return c
