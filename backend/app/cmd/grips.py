import copy
import math
from dataclasses import fields

from app.cmd import annot_grips, jig
from app.doc import geom
from app.doc.entities import AttDef, Arc, Circle, Dimension, Ellipse, Hatch, Insert, Line, LwPolyline, MText, Point, Polyline3d, Ray, Solid, Spline, Text, XLine

MAX_OTHERS = 200
MAX_COPIES = 1000
MODES = ("stretch", "move", "rotate", "scale", "mirror")
OPTIONS = ("add_vertex", "remove_vertex", "convert_arc", "convert_line", "lengthen", "radius")
DEGENERATE = "The objects can't be edited that way (locked, or the result would be degenerate)."


class GripError(Exception):
    pass


def _g(p, kind, gid):
    return {"id": gid, "p": [float(p[0]), float(p[1])], "kind": kind}


def _minor_vec(e):
    return [-e.major[1] * e.ratio, e.major[0] * e.ratio]


def _seg_mid(p0, p1, bulge):
    arc = geom.bulge_to_arc(p0, p1, bulge)
    if arc:
        c, r, a0, a1, _ccw = arc
        return geom.polar(c, r, a0 + geom.ccw_sweep(a0, a1) / 2.0)
    return geom.midpoint(p0, p1)


def grips_of(e) -> list:
    out = []
    if isinstance(e, Line):
        out = [_g(e.start, "end", "start"), _g(geom.midpoint(e.start, e.end), "mid", "mid"), _g(e.end, "end", "end")]
    elif isinstance(e, Point):
        out = [_g(e.position, "node", "pos")]
    elif isinstance(e, Circle):
        out = [_g(e.center, "center", "center")]
        for k in range(4):
            out.append(_g(geom.polar(e.center, e.radius, k * math.pi / 2.0), "quadrant", "q%d" % k))
    elif isinstance(e, Arc):
        a0, a1 = e.start_angle, e.end_angle
        mid = a0 + geom.ccw_sweep(a0, a1) / 2.0
        out = [_g(geom.polar(e.center, e.radius, a0), "end", "start"), _g(geom.polar(e.center, e.radius, mid), "mid", "mid"), _g(geom.polar(e.center, e.radius, a1), "end", "end"), _g(e.center, "center", "center")]
    elif isinstance(e, Ellipse):
        c, u, v = e.center, e.major, _minor_vec(e)
        out = [
            _g(c, "center", "center"),
            _g([c[0] + u[0], c[1] + u[1]], "major", "major1"),
            _g([c[0] + v[0], c[1] + v[1]], "minor", "minor1"),
            _g([c[0] - u[0], c[1] - u[1]], "major", "major2"),
            _g([c[0] - v[0], c[1] - v[1]], "minor", "minor2"),
        ]
    elif isinstance(e, LwPolyline):
        n = len(e.vertices)
        for i, v in enumerate(e.vertices):
            out.append(_g(v["p"], "vertex", "v%d" % i))
            if i < n - 1 or e.closed:
                nxt = e.vertices[(i + 1) % n]
                out.append(_g(_seg_mid(v["p"], nxt["p"], v.get("bulge", 0.0)), "segmid", "m%d" % i))
    elif isinstance(e, Polyline3d):
        out = [_g(p, "vertex", "v%d" % i) for i, p in enumerate(e.points)]
    elif isinstance(e, Spline):
        if e.fit_points:
            out = [_g(p, "fit", "f%d" % i) for i, p in enumerate(e.fit_points)]
        else:
            out = [_g(p, "ctrl", "c%d" % i) for i, p in enumerate(e.control_points)]
    elif isinstance(e, (Ray, XLine)):
        n = math.hypot(e.direction[0], e.direction[1]) or 1.0
        out = [_g(e.base, "base", "base"), _g([e.base[0] + e.direction[0] / n, e.base[1] + e.direction[1] / n], "dir", "dir")]
    elif isinstance(e, Text):
        out = [_g(e.align_point or e.position, "insert", "ins")]
    elif isinstance(e, Insert):
        out = [_g(e.position, "insert", "ins")] + [_g(a["at"], "attribute", "att:" + str(a["tag"])) for a in e.attributes if isinstance(a, dict) and a.get("at") and a.get("vis", True) and not a.get("lock_position")]
    elif isinstance(e, (MText, AttDef)):
        out = [_g(e.position, "insert", "ins")]
    elif isinstance(e, Dimension):
        from app.dim import dimgrips

        out = [_g(p, kind, gid) for gid, kind, p in dimgrips.points(e)]
    elif isinstance(e, Hatch) or e.kind == "region":
        b = e.bounds()
        if b:
            out = [_g([(b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0], "center", "center")]
    elif isinstance(e, Solid):
        out = [_g(p, "corner", "k%d" % i) for i, p in enumerate(e.corners)]
    elif e.kind == "wipeout":
        out = [_g(p, "vertex", "v%d" % i) for i, p in enumerate(e.points)]
    elif e.kind == "mline":
        out = [_g(v["p"], "vertex", "v%d" % i) for i, v in enumerate(e.vertices)]
    elif e.kind == "helix":
        out = [_g(e.center, "center", "center")]
    elif e.kind in ("assoc_array", "viewport"):
        out = [_g(p, kind, gid) for gid, p, kind in e.grip_points()]
    elif e.kind in ("mleader", "leader", "table"):
        out = [_g(p, kind, gid) for gid, p, kind in annot_grips.points_of(e)]
    return out


def grips_for(doc, handle):
    e = doc.drawing.get(handle)
    if e is None or doc.drawing.layer_locked(e.layer):
        return []
    return grips_of(e)


def grip_sets(doc, handles) -> list:
    d = doc.drawing
    out = []
    for h in handles[:200]:
        e = d.get(h)
        if e is not None and not d.layer_locked(e.layer):
            out.append({"h": h, "grips": grips_of(e)})
    return out


def _find(e, grip):
    gs = grips_of(e)
    if isinstance(grip, int) and not isinstance(grip, bool):
        if 0 <= grip < len(gs):
            return gs[grip]
    else:
        for g in gs:
            if g["id"] == grip:
                return g
    raise GripError("No grip of a selected object there.")


def _idx(gid: str) -> int:
    return int(gid[1:])


def _shift(e, frm, to):
    e.move_by([to[0] - frm[0], to[1] - frm[1], 0.0])


def _bulge_through(p0, t, p1):
    res = geom.circle_from_3pts(p0, t, p1)
    if res is None:
        raise GripError(DEGENERATE)
    ccw = geom.cross2(geom.sub(t, p0), geom.sub(p1, p0)) > 0
    return geom.bulge_from_arc_points(p0, p1, res[0], ccw)


def _stretch_ellipse(e, gid, t):
    c = e.center
    u = [e.major[0], e.major[1]]
    big = math.hypot(u[0], u[1])
    small = e.ratio * big
    d = [t[0] - c[0], t[1] - c[1]]
    n = math.hypot(d[0], d[1])
    if n < geom.EPS:
        raise GripError(DEGENERATE)
    shift = -math.pi / 2.0
    swap = False
    if gid in ("major1", "major2"):
        if gid == "major2":
            d = [-d[0], -d[1]]
        if n >= small:
            e.major = [d[0], d[1], 0.0]
            e.ratio = small / n
            return
        ux, uy = d[0] / n, d[1] / n
        e.major = [-uy * small, ux * small, 0.0]
        e.ratio = n / small
        swap = True
    else:
        if gid == "minor2":
            d = [-d[0], -d[1]]
        if n <= big:
            e.ratio = n / big
            return
        e.major = [d[0], d[1], 0.0]
        e.ratio = big / n
        swap = True
    if swap and abs(e.end_param - e.start_param) < geom.TAU - 1e-12:
        e.start_param += shift
        e.end_param += shift


def stretch(e, gid, to) -> None:
    t = [to[0], to[1], 0.0]
    g = _find(e, gid)
    gid = g["id"]
    pos = g["p"]
    if isinstance(e, Line):
        if gid == "start":
            e.start = t
        elif gid == "end":
            e.end = t
        else:
            _shift(e, pos, t)
    elif isinstance(e, Circle):
        if gid == "center":
            _shift(e, pos, t)
        else:
            e.radius = geom.dist(e.center, t)
    elif isinstance(e, Arc):
        if gid == "center":
            _shift(e, pos, t)
        else:
            c, r, a0, a1 = e.center, e.radius, e.start_angle, e.end_angle
            s = geom.polar(c, r, a0)
            m = geom.polar(c, r, a0 + geom.ccw_sweep(a0, a1) / 2.0)
            en = geom.polar(c, r, a1)
            if gid == "start":
                s = t
            elif gid == "mid":
                m = t
            else:
                en = t
            res = geom.arc_from_3pts(s, m, en)
            if res is None:
                raise GripError(DEGENERATE)
            e.center, e.radius, e.start_angle, e.end_angle = res[0], res[1], res[2], res[3]
    elif isinstance(e, Ellipse):
        if gid == "center":
            _shift(e, pos, t)
        else:
            _stretch_ellipse(e, gid, t)
    elif isinstance(e, LwPolyline):
        n = len(e.vertices)
        i = _idx(gid)
        if gid[0] == "v":
            e.vertices[i]["p"] = [t[0], t[1]]
        else:
            a, b = e.vertices[i], e.vertices[(i + 1) % n]
            if abs(a.get("bulge", 0.0)) < geom.TINY_BULGE:
                dx, dy = t[0] - pos[0], t[1] - pos[1]
                a["p"] = [a["p"][0] + dx, a["p"][1] + dy]
                b["p"] = [b["p"][0] + dx, b["p"][1] + dy]
            else:
                a["bulge"] = _bulge_through(a["p"], t, b["p"])
    elif isinstance(e, Polyline3d):
        i = _idx(gid)
        e.points[i] = [t[0], t[1], e.points[i][2] if len(e.points[i]) > 2 else 0.0]
    elif isinstance(e, Spline):
        i = _idx(gid)
        if gid[0] == "f":
            e.fit_points[i] = list(t)
        else:
            e.control_points[i] = list(t)
    elif isinstance(e, (Ray, XLine)):
        if gid == "base":
            _shift(e, pos, t)
        else:
            d = [t[0] - e.base[0], t[1] - e.base[1]]
            n = math.hypot(d[0], d[1])
            if n < geom.EPS:
                raise GripError(DEGENERATE)
            e.direction = [d[0] / n, d[1] / n, 0.0]
    elif isinstance(e, Dimension):
        from app.dim import dimgrips

        if not dimgrips.stretch(e, gid, t):
            raise GripError(DEGENERATE)
    elif isinstance(e, Solid):
        e.corners[_idx(gid)] = list(t)
    elif e.kind == "wipeout":
        e.points[_idx(gid)] = list(t)
    elif e.kind == "mline":
        e.vertices[_idx(gid)]["p"] = [t[0], t[1]]
    elif e.kind in ("assoc_array", "viewport"):
        e.stretch_grip(gid, t)
    elif e.kind in ("mleader", "leader", "table"):
        annot_grips.stretch(e, gid, t)
    elif isinstance(e, Insert) and str(gid).startswith("att:"):
        from app.doc import attribs

        try:
            attribs.move_attribute(e, str(gid)[4:], t)
        except attribs.AttribError as err:
            raise GripError(str(err))
    else:
        _shift(e, pos, t)


def option_edit(e, gid, to, option, value) -> None:
    t = [to[0], to[1], 0.0]
    g = _find(e, gid)
    gid = g["id"]
    if isinstance(e, LwPolyline):
        n = len(e.vertices)
        if gid[0] not in ("v", "m"):
            raise GripError("Option not available for this grip.")
        i = _idx(gid)
        if option == "add_vertex":
            e.vertices[i]["bulge"] = 0.0
            e.vertices.insert(i + 1, {"p": [t[0], t[1]], "bulge": 0.0, "sw": e.vertices[i].get("sw", 0.0), "ew": e.vertices[i].get("ew", 0.0)})
            return
        if option == "remove_vertex" and gid[0] == "v":
            if n <= 2:
                raise GripError("A polyline needs at least two vertices.")
            del e.vertices[i]
            e.vertices[(i - 1) % len(e.vertices)]["bulge"] = 0.0
            return
        if gid[0] == "m":
            seg = e.vertices[i]
            nxt = e.vertices[(i + 1) % n]
            if option == "convert_arc":
                if abs(seg.get("bulge", 0.0)) >= geom.TINY_BULGE:
                    raise GripError("That segment is already an arc.")
                seg["bulge"] = _bulge_through(seg["p"], t, nxt["p"])
                return
            if option == "convert_line":
                if abs(seg.get("bulge", 0.0)) < geom.TINY_BULGE:
                    raise GripError("That segment is already straight.")
                seg["bulge"] = 0.0
                return
        raise GripError("Option not available for this grip.")
    if option == "lengthen" and isinstance(e, Line) and gid in ("start", "end"):
        far = e.start if gid == "end" else e.end
        near = e.end if gid == "end" else e.start
        u = geom.sub(near, far)
        ln = math.hypot(u[0], u[1])
        if ln < geom.EPS:
            raise GripError(DEGENERATE)
        u = [u[0] / ln, u[1] / ln]
        new_len = ln + value if value is not None else (t[0] - far[0]) * u[0] + (t[1] - far[1]) * u[1]
        moved = [far[0] + u[0] * new_len, far[1] + u[1] * new_len, 0.0]
        if gid == "end":
            e.end = moved
        else:
            e.start = moved
        return
    if option == "lengthen" and isinstance(e, Arc) and gid in ("start", "end"):
        if value is not None:
            da = value / e.radius
            ang = e.end_angle + da if gid == "end" else e.start_angle - da
        else:
            ang = geom.angle_of(e.center, t)
        if gid == "end":
            e.end_angle = geom.norm_angle(ang)
        else:
            e.start_angle = geom.norm_angle(ang)
        return
    if option == "radius" and isinstance(e, Arc) and gid == "mid":
        r = value if value is not None else geom.dist(e.center, t)
        if not r > geom.EPS:
            raise GripError(DEGENERATE)
        e.radius = r
        return
    raise GripError("Option not available for this grip.")


class Xf:
    def __init__(self, mode, base, angle=0.0, k=1.0):
        self.mode = mode
        self.base = base
        self.angle = angle
        self.k = k if mode == "scale" else 1.0
        self.flip = mode == "mirror"

    def vec(self, v):
        x, y = v[0], v[1]
        if self.mode == "rotate":
            c, s = math.cos(self.angle), math.sin(self.angle)
            return [x * c - y * s, x * s + y * c]
        if self.mode == "scale":
            return [x * self.k, y * self.k]
        c, s = math.cos(self.angle), math.sin(self.angle)
        dot = x * c + y * s
        return [2 * dot * c - x, 2 * dot * s - y]

    def pt(self, p):
        r = self.vec([p[0] - self.base[0], p[1] - self.base[1]])
        return [self.base[0] + r[0], self.base[1] + r[1], p[2] if len(p) > 2 else 0.0]

    def ang(self, a):
        if self.mode == "rotate":
            return a + self.angle
        if self.mode == "mirror":
            return 2 * self.angle - a
        return a


def _pt2(xf, p):
    q = xf.pt(p)
    return [q[0], q[1]]


def transform(e, xf) -> None:
    P = xf.pt
    if isinstance(e, Line):
        e.start, e.end = P(e.start), P(e.end)
    elif isinstance(e, Point):
        e.position = P(e.position)
    elif isinstance(e, Circle):
        e.center = P(e.center)
        e.radius *= xf.k
    elif isinstance(e, Arc):
        e.center = P(e.center)
        e.radius *= xf.k
        a0, a1 = xf.ang(e.start_angle), xf.ang(e.end_angle)
        if xf.flip:
            a0, a1 = a1, a0
        e.start_angle, e.end_angle = geom.norm_angle(a0), geom.norm_angle(a1)
    elif isinstance(e, Ellipse):
        e.center = P(e.center)
        v = xf.vec(e.major)
        e.major = [v[0], v[1], 0.0]
        if xf.flip and abs(e.end_param - e.start_param) < geom.TAU - 1e-12:
            e.start_param, e.end_param = -e.end_param, -e.start_param
    elif isinstance(e, LwPolyline):
        for v in e.vertices:
            v["p"] = _pt2(xf, v["p"])
            if xf.flip:
                v["bulge"] = -v.get("bulge", 0.0)
            v["sw"] = v.get("sw", 0.0) * xf.k
            v["ew"] = v.get("ew", 0.0) * xf.k
        e.const_width *= xf.k
    elif isinstance(e, Polyline3d):
        e.points = [P(p) for p in e.points]
    elif isinstance(e, Spline):
        e.control_points = [P(p) for p in e.control_points]
        e.fit_points = [P(p) for p in e.fit_points]
        for name in ("start_tangent", "end_tangent"):
            tv = getattr(e, name)
            if tv:
                w = xf.vec(tv)
                setattr(e, name, [w[0], w[1], tv[2] if len(tv) > 2 else 0.0])
        e.fit_tolerance *= xf.k
    elif isinstance(e, (Ray, XLine)):
        e.base = P(e.base)
        w = xf.vec(e.direction)
        n = math.hypot(w[0], w[1]) or 1.0
        e.direction = [w[0] / n, w[1] / n, 0.0]
    elif isinstance(e, Text):
        e.position = P(e.position)
        if e.align_point is not None:
            e.align_point = P(e.align_point)
        e.height *= xf.k
        if xf.mode == "rotate":
            e.rotation += xf.angle
    elif isinstance(e, (MText, AttDef)):
        e.position = P(e.position)
        if isinstance(e, AttDef) and e.align_point is not None:
            e.align_point = P(e.align_point)
        e.height *= xf.k
        if isinstance(e, MText):
            e.width *= xf.k
        if xf.mode == "rotate":
            e.rotation += xf.angle
    elif isinstance(e, Insert):
        e.position = P(e.position)
        e.scale = [s * xf.k for s in e.scale]
        if xf.mode == "rotate":
            e.rotation += xf.angle
        elif xf.flip:
            e.rotation = xf.ang(e.rotation)
            e.scale[1] = -e.scale[1]
    elif isinstance(e, Hatch):
        for loop in e.loops:
            for v in loop.get("vertices", []):
                v["p"] = _pt2(xf, v["p"])
                if xf.flip and "bulge" in v:
                    v["bulge"] = -v["bulge"]
        e.origin = _pt2(xf, e.origin)
        e.pattern_scale *= xf.k
        if xf.mode == "rotate":
            e.pattern_angle += xf.angle
            if e.gradient:
                e.gradient["angle"] = float(e.gradient.get("angle", 0.0)) + xf.angle
        elif xf.flip:
            e.pattern_angle = xf.ang(e.pattern_angle)
            if e.gradient:
                e.gradient["angle"] = xf.ang(float(e.gradient.get("angle", 0.0)))
    elif e.kind == "region":
        for loop in e.loops:
            for v in loop.get("vertices", []):
                v["p"] = _pt2(xf, v["p"])
                if xf.flip:
                    v["bulge"] = -(v.get("bulge", 0.0) or 0.0)
    elif isinstance(e, Solid):
        e.corners = [P(p) for p in e.corners]
    elif isinstance(e, Dimension):
        from app.dim import dimgrips

        dimgrips.transform(e, xf, P)
    elif e.kind == "wipeout":
        e.points = [P(p) for p in e.points]
    elif e.kind == "mline":
        for v in e.vertices:
            v["p"] = _pt2(xf, v["p"])
        e.scale *= -xf.k if xf.flip else xf.k
    elif e.kind == "helix":
        e.center = P(e.center)
        e.base_radius *= xf.k
        e.top_radius *= xf.k
        e.height *= xf.k
        e.start_angle = geom.norm_angle(xf.ang(e.start_angle))
        if xf.flip:
            e.ccw = not e.ccw
        e.rebuild()
    elif e.kind == "assoc_array":
        e.apply_xf(xf)
    elif hasattr(e, "apply_transform"):
        e.apply_transform(xf)
    else:
        raise GripError(DEGENERATE)


def _targets(doc, ent):
    d = doc.drawing
    sel = [h for h in doc.selection if h in d.ents]
    if ent.handle not in sel:
        return [ent]
    out = [ent]
    for h in sel:
        e = d.get(h)
        if e is not None and e is not ent and not d.layer_locked(e.layer):
            out.append(e)
    return out


def _clone(e):
    return e.copy_as_new()


def plan(doc, handle, grip, mode, to, base=None, copy_flag=False, ref=None, option=None, value=None, more=None) -> list:
    d = doc.drawing
    if mode not in MODES:
        raise GripError("Grip mode must be one of %s." % ", ".join(MODES))
    ent = d.get(handle)
    if ent is None:
        raise GripError("No such object.")
    if d.layer_locked(ent.layer):
        raise GripError("The object is on a locked layer.")
    g = _find(ent, grip)
    pos = g["p"]
    to = [float(to[0]), float(to[1])]
    anchor = [float(base[0]), float(base[1])] if base is not None else None
    tos = [to] + [[float(p[0]), float(p[1])] for p in (more or [])][:MAX_COPIES] if copy_flag else [to]
    ops = []
    tol = d.tolerances["absolute"]
    if option is not None:
        if option not in OPTIONS:
            raise GripError("Unknown grip option.")
        if mode != "stretch":
            raise GripError("Grip options belong to the stretch mode.")
        c = _clone(ent)
        option_edit(c, g["id"], to, option, value)
        return [("add" if copy_flag else "replace", ent.handle, c)]
    for t in tos:
        if mode == "stretch":
            target = [pos[0] + t[0] - anchor[0], pos[1] + t[1] - anchor[1]] if anchor else t
            c = _clone(ent)
            stretch(c, g["id"], target)
            ops.append(("add" if copy_flag else "replace", ent.handle, c))
            if not copy_flag:
                for other in _targets(doc, ent)[1 : MAX_OTHERS + 1]:
                    for og in grips_of(other):
                        if geom.dist(og["p"], pos) <= tol:
                            oc = _clone(other)
                            stretch(oc, og["id"], target)
                            ops.append(("replace", other.handle, oc))
                            break
            continue
        centre = anchor or pos
        targets = _targets(doc, ent)
        if mode == "move":
            vec = [t[0] - centre[0], t[1] - centre[1], 0.0]
            xf = None
        elif mode == "rotate":
            if geom.dist(centre, t) < geom.EPS:
                raise GripError("Rotation needs a point away from the base.")
            if ref is not None:
                start_ang = float(ref)
            elif geom.dist(centre, pos) > geom.EPS:
                start_ang = geom.angle_of(centre, pos)
            else:
                start_ang = 0.0
            xf = Xf("rotate", centre, geom.angle_of(centre, t) - start_ang)
        elif mode == "scale":
            if ref is not None:
                length = float(ref)
            elif geom.dist(centre, pos) > geom.EPS:
                length = geom.dist(centre, pos)
            else:
                length = 1.0
            k = geom.dist(centre, t) / length if length > 0 else 0.0
            if not k > geom.EPS or not math.isfinite(k):
                raise GripError("scale factor would be zero")
            xf = Xf("scale", centre, 0.0, k)
        else:
            if geom.dist(centre, t) < geom.EPS:
                raise GripError("Two distinct points are needed.")
            xf = Xf("mirror", centre, geom.angle_of(centre, t))
        for target in targets:
            c = _clone(target)
            if xf is None:
                c.move_by(vec)
            else:
                transform(c, xf)
            ops.append(("add" if copy_flag else "replace", target.handle, c))
    for _op, _h, c in ops:
        if not c.valid():
            raise GripError(DEGENERATE)
    return ops


def _assign(target, clone) -> None:
    for f in fields(type(target)):
        if f.name in ("handle", "owner"):
            continue
        setattr(target, f.name, copy.deepcopy(getattr(clone, f.name)))


def run(doc, handle, grip, mode, to, base=None, copy_flag=False, preview=False, ref=None, option=None, value=None, more=None) -> dict:
    with doc.lock:
        rn = doc.get_runner()
        if rn.run is not None:
            raise GripError("Finish or cancel the running command first.")
        ops = plan(doc, handle, grip, mode, to, base, copy_flag, ref, option, value, more)
        d = doc.drawing
        if preview:
            return {"items": jig.entity_items([c for _o, _h, c in ops], d)}
        changed = []
        label = "Grip %s" % mode
        with doc.transaction(label):
            for op, h, c in ops:
                if op == "replace":
                    _assign(d.modify(h), c)
                    changed.append(h)
                else:
                    try:
                        changed.append(d.add_entity(c, d.get(h).owner))
                    except ValueError as err:
                        raise GripError(str(err))
        return {"rev": doc.rev, "label": label, "handles": changed}
