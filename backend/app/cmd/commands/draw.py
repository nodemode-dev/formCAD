import math

from app.cmd import jig
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.doc import geom
from app.doc.entities import Arc, Circle, Line, LwPolyline, Point

QUARTER = math.tan(math.pi / 8.0)


def _pt(v):
    return geom.as_pt(v)


def _make_arc(center, r, a0, a1):
    return Arc(center=list(center), radius=r, start_angle=geom.norm_angle(a0), end_angle=geom.norm_angle(a1))


def _arc_shape(a):
    return jig.arc(a.center, a.radius, a.start_angle, a.end_angle)


def _arc_from_bulge(ctx, p0, p1, bulge):
    res = geom.bulge_to_arc(p0, p1, bulge)
    if res is None:
        raise CommandError("Invalid arc or circle for these values.")
    center, r, a0, a1, _ccw = res
    return _make_arc(center, r, a0, a1)


@command("line", aliases=("l",), group="draw", label="Line", description="Connected straight segments, one entity each; Undo and Close options.", menu="Draw > Line")
def line(ctx):
    while True:
        first = yield ctx.point("Specify first point")
        if first.kind != "point":
            return
        pts = [first.value]
        made = []
        restart = False
        while True:
            opts = ["Undo"]
            if len(pts) >= 3:
                opts.append("Close")
            r = yield ctx.point("Specify next point", opts, base=pts[-1], jig=lambda p: jig.rubber(pts[-1], p))
            if r.kind == "enter":
                return
            if r.kind == "keyword" and r.value == "Undo":
                if made:
                    ctx.d.erase_entity(made.pop())
                    pts.pop()
                else:
                    restart = True
                    break
                continue
            if r.kind == "keyword" and r.value == "Close":
                made.append(ctx.add(Line(start=list(pts[-1]), end=list(pts[0]))))
                return
            if r.kind != "point":
                return
            p = r.value
            if ctx.same(p, pts[-1]):
                continue
            made.append(ctx.add(Line(start=list(pts[-1]), end=list(p))))
            pts.append(p)
        if not restart:
            return


@executes("line")
def line_exec(ctx, args):
    pts = [_pt(p) for p in args.get("points", [])]
    clean = []
    for p in pts:
        if not clean or not ctx.same(p, clean[-1]):
            clean.append(p)
    if len(clean) < 2:
        raise CommandError("A line needs at least two distinct points.")
    handles = [ctx.add(Line(start=list(a), end=list(b))) for a, b in zip(clean, clean[1:])]
    if args.get("closed") and len(clean) > 2 and not ctx.same(clean[-1], clean[0]):
        handles.append(ctx.add(Line(start=list(clean[-1]), end=list(clean[0]))))
    return {"handles": handles}


def _finish_circle(ctx, center, r):
    if not (r > ctx.d.tolerances["absolute"]) or not math.isfinite(r):
        raise CommandError("Value must be positive and nonzero.")
    h = ctx.add(Circle(center=list(center), radius=r))
    ctx.d.set_header("CIRCLERAD", float(r))
    return h


@command("circle", aliases=("c",), group="draw", label="Circle", description="Circle by centre and radius or diameter; 3P, 2P, Ttr options.", menu="Draw > Circle > Center, Radius")
def circle(ctx):
    r = yield ctx.point("Specify center point for circle", ["3P", "2P", "Ttr"])
    if r.kind == "keyword":
        if r.value == "3P":
            a = yield ctx.point("Specify first point on circle")
            if a.kind != "point":
                return
            b = yield ctx.point("Specify second point on circle", jig=lambda p: jig.rubber(a.value, p))
            if b.kind != "point":
                return
            c = yield ctx.point("Specify third point on circle", jig=lambda p: jig.circle_3p(a.value, b.value, p))
            if c.kind != "point":
                return
            res = geom.circle_from_3pts(a.value, b.value, c.value)
            if res is None:
                raise CommandError("Circle does not exist.")
            _finish_circle(ctx, res[0], res[1])
            return
        if r.value == "2P":
            a = yield ctx.point("Specify first end point of circle's diameter")
            if a.kind != "point":
                return
            b = yield ctx.point("Specify second end point of circle's diameter", base=a.value, jig=lambda p: jig.circle_2p(a.value, p))
            if b.kind != "point":
                return
            _finish_circle(ctx, geom.midpoint(a.value, b.value), geom.dist(a.value, b.value) / 2.0)
            return
        raise CommandError("Tan, Tan, Radius needs object picks from the canvas.")
    if r.kind != "point":
        return
    center = r.value
    last = float(ctx.d.header.get("CIRCLERAD", 0.0))
    default = last if last > 0 else None
    rr = yield ctx.distance("Specify radius of circle", ["Diameter"], default=default, base=center, positive=True, jig=lambda p: jig.circle_radius(center, p))
    if rr.kind == "keyword":
        dd = yield ctx.distance("Specify diameter of circle", default=default * 2 if default else None, base=center, positive=True, jig=lambda p: jig.circle_radius(center, p, 0.5))
        if dd.kind != "number":
            return
        _finish_circle(ctx, center, dd.value / 2.0)
        return
    if rr.kind != "number":
        return
    _finish_circle(ctx, center, rr.value)


@executes("circle")
def circle_exec(ctx, args):
    if "center" in args:
        c = _pt(args["center"])
        r = args.get("radius")
        if r is None and args.get("diameter") is not None:
            r = float(args["diameter"]) / 2.0
        if r is None:
            raise CommandError("A radius or diameter is required.")
        return {"handle": _finish_circle(ctx, c, float(r))}
    pts = [_pt(p) for p in args.get("points", [])]
    if len(pts) == 2:
        return {"handle": _finish_circle(ctx, geom.midpoint(pts[0], pts[1]), geom.dist(pts[0], pts[1]) / 2.0)}
    if len(pts) == 3:
        res = geom.circle_from_3pts(*pts)
        if res is None:
            raise CommandError("Circle does not exist.")
        return {"handle": _finish_circle(ctx, res[0], res[1])}
    raise CommandError("Give center and radius, two points or three points.")


def _tail_point(e):
    if isinstance(e, Line):
        return list(e.end), geom.angle_of(e.start, e.end)
    ang = e.end_angle
    return geom.polar(e.center, e.radius, ang), ang + math.pi / 2.0


def _last_curve(ctx):
    found = None
    for e in ctx.d.entities(ctx.doc.current_space):
        if isinstance(e, (Line, Arc)):
            found = e
    return found


def _arc_from_start_end_tangent(ctx, s, e, phi):
    alpha = geom.angle_of(s, e)
    diff = (alpha - phi + math.pi) % (2 * math.pi) - math.pi
    if abs(abs(diff) - math.pi) < 1e-9 or geom.dist(s, e) < ctx.d.tolerances["absolute"]:
        raise CommandError("Invalid arc or circle for these values.")
    return _arc_from_bulge(ctx, s, e, math.tan(diff / 2.0))


def _arc_sca(ctx, s, c, theta):
    r = geom.dist(c, s)
    if r < ctx.d.tolerances["absolute"] or abs(theta) < 1e-12 or abs(theta) >= geom.TAU:
        raise CommandError("Invalid arc or circle for these values.")
    a0 = geom.angle_of(c, s)
    return _make_arc(c, r, a0, a0 + theta) if theta > 0 else _make_arc(c, r, a0 + theta, a0)


def _arc_scl(ctx, s, c, length):
    r = geom.dist(c, s)
    if r < ctx.d.tolerances["absolute"] or abs(length) > 2 * r:
        raise CommandError("Invalid arc or circle for these values.")
    theta = 2.0 * math.asin(abs(length) / (2.0 * r))
    if length < 0:
        theta = geom.TAU - theta
    return _arc_sca(ctx, s, c, theta)


def _arc_sce(ctx, s, c, e):
    r = geom.dist(c, s)
    if r < ctx.d.tolerances["absolute"]:
        raise CommandError("Invalid arc or circle for these values.")
    return _make_arc(c, r, geom.angle_of(c, s), geom.angle_of(c, e))


@command("arc", aliases=("a",), group="draw", label="Arc", description="Arc by three points with option switches to the other arc variants; Enter continues from the last line or arc.", menu="Draw > Arc > 3 Points")
def arc(ctx):
    r = yield ctx.point("Specify start point of arc", ["Center"])
    if r.kind == "enter":
        prev = _last_curve(ctx)
        if prev is None:
            raise CommandError("No line or arc to continue.")
        s, phi = _tail_point(prev)
        ctx.set_last(s)
        e = yield ctx.point("Specify end point of arc", base=s, jig=lambda p: [_arc_shape(_arc_from_start_end_tangent(ctx, s, p, phi))])
        if e.kind != "point":
            return
        ctx.add(_arc_from_start_end_tangent(ctx, s, e.value, phi))
        return
    if r.kind == "keyword":
        c = yield ctx.point("Specify center point of arc")
        if c.kind != "point":
            return
        s = yield ctx.point("Specify start point of arc", base=c.value, jig=lambda p: jig.rubber(c.value, p))
        if s.kind != "point":
            return
        yield from _finish_center_arc(ctx, s.value, c.value)
        return
    if r.kind != "point":
        return
    start = r.value
    m = yield ctx.point("Specify second point of arc", ["Center", "End"], base=start, jig=lambda p: jig.rubber(start, p))
    if m.kind == "keyword" and m.value == "Center":
        c = yield ctx.point("Specify center point of arc", jig=lambda p: jig.rubber(start, p))
        if c.kind != "point":
            return
        yield from _finish_center_arc(ctx, start, c.value)
        return
    if m.kind == "keyword" and m.value == "End":
        e = yield ctx.point("Specify end point of arc", base=start, jig=lambda p: jig.rubber(start, p))
        if e.kind != "point":
            return
        yield from _finish_end_arc(ctx, start, e.value)
        return
    if m.kind != "point":
        return
    e = yield ctx.point("Specify end point of arc", base=m.value, jig=lambda p: jig.arc_through(start, m.value, p))
    if e.kind != "point":
        return
    res = geom.arc_from_3pts(start, m.value, e.value)
    if res is None:
        raise CommandError("Invalid arc or circle for these values.")
    ctx.add(_make_arc(*res))


def _finish_center_arc(ctx, s, c):
    e = yield ctx.point("Specify end point of arc", ["Angle", "chord Length"], base=c, jig=lambda p: jig.arc_centre_ends(s, c, p) + jig.rubber(c, p))
    if e.kind == "point":
        ctx.add(_arc_sce(ctx, s, c, e.value))
    elif e.kind == "keyword" and e.value == "Angle":
        a = yield ctx.angle("Specify included angle", absolute=False)
        if a.kind != "number":
            return
        ctx.add(_arc_sca(ctx, s, c, a.value))
    elif e.kind == "keyword":
        ln = yield ctx.distance("Specify length of chord", base=s)
        if ln.kind != "number":
            return
        ctx.add(_arc_scl(ctx, s, c, ln.value))


def _finish_end_arc(ctx, s, e):
    k = yield ctx.point("Specify center point of arc", ["Angle", "Direction", "Radius"], base=s, jig=lambda p: jig.arc_centre_ends(s, p, e))
    if k.kind == "point":
        c = k.value
        if abs(geom.dist(c, s) - geom.dist(c, e)) > 1e-6 * max(1.0, geom.dist(c, s)):
            ctx.say("The end point is moved onto the circle.")
        ctx.add(_arc_sce(ctx, s, c, e))
        return
    if k.kind != "keyword":
        return
    if k.value == "Angle":
        a = yield ctx.angle("Specify included angle", absolute=False)
        if a.kind != "number":
            return
        if abs(a.value) < 1e-9 or abs(a.value) >= geom.TAU:
            raise CommandError("Invalid arc or circle for these values.")
        ctx.add(_arc_from_bulge(ctx, s, e, math.tan(a.value / 4.0)))
    elif k.value == "Direction":
        a = yield ctx.angle("Specify tangent direction for the start point of arc", base=s)
        if a.kind != "number":
            return
        ctx.add(_arc_from_start_end_tangent(ctx, s, e, a.value))
    else:
        rr = yield ctx.distance("Specify radius of arc", base=s)
        if rr.kind != "number" or rr.value == 0:
            return
        chord = geom.dist(s, e)
        R = abs(rr.value)
        if chord > 2 * R + 1e-12 or chord < ctx.d.tolerances["absolute"]:
            raise CommandError("Invalid arc or circle for these values.")
        theta = 2.0 * math.asin(min(1.0, chord / (2.0 * R)))
        if rr.value < 0:
            theta = geom.TAU - theta
        ctx.add(_arc_from_bulge(ctx, s, e, math.tan(theta / 4.0)))


@command("point", aliases=("po",), group="draw", label="Point", description="Places one point object (point style applies).", menu="Draw > Point > Single Point")
def point_cmd(ctx):
    ctx.say("Current point modes: PDMODE=%s PDSIZE=%s" % (ctx.var("PDMODE"), ctx.fd(ctx.var("PDSIZE"))))
    r = yield ctx.point("Specify a point")
    if r.kind == "point":
        ctx.add(Point(position=list(r.value)))


@command("point.multiple", group="draw", label="Multiple Point", description="Places points repeatedly until Enter.", menu="Draw > Point > Multiple Point")
def point_multiple(ctx):
    ctx.say("Current point modes: PDMODE=%s PDSIZE=%s" % (ctx.var("PDMODE"), ctx.fd(ctx.var("PDSIZE"))))
    while True:
        r = yield ctx.point("Specify a point")
        if r.kind != "point":
            return
        ctx.add(Point(position=list(r.value)))


@executes("point", "point.multiple")
def point_exec(ctx, args):
    pts = args.get("points") or ([args["point"]] if "point" in args else [])
    if not pts:
        raise CommandError("A point is required.")
    return {"handles": [ctx.add(Point(position=_pt(p))) for p in pts]}


def _corner_polygon(w, h, origin, u, v):
    return [[origin[0] + u[0] * x + v[0] * y, origin[1] + u[1] * x + v[1] * y] for x, y in ((0, 0), (w, 0), (w, h), (0, h))]


def _rect_vertices(corners, fillet, chamfer, orientation):
    n = 4
    sides = [geom.dist(corners[i], corners[(i + 1) % n]) for i in range(n)]
    short = min(sides)
    if fillet > 0 and fillet * 2 <= short + 1e-12:
        a = b = fillet
        arc_b = QUARTER * orientation
    elif chamfer and chamfer[0] + chamfer[1] <= short + 1e-12 and chamfer[0] + chamfer[1] > 0:
        a, b = chamfer
        arc_b = 0.0
    else:
        return [{"p": [c[0], c[1]], "bulge": 0.0, "sw": 0.0, "ew": 0.0} for c in corners]
    verts = []
    for i in range(n):
        c = corners[i]
        prev = corners[(i - 1) % n]
        nxt = corners[(i + 1) % n]
        lp = geom.dist(c, prev)
        ln = geom.dist(c, nxt)
        t1 = [c[0] + (prev[0] - c[0]) * a / lp, c[1] + (prev[1] - c[1]) * a / lp]
        t2 = [c[0] + (nxt[0] - c[0]) * b / ln, c[1] + (nxt[1] - c[1]) * b / ln]
        verts.append({"p": t1, "bulge": arc_b, "sw": 0.0, "ew": 0.0})
        verts.append({"p": t2, "bulge": 0.0, "sw": 0.0, "ew": 0.0})
    return verts


def _build_rect(ctx, c1, c2, rot, center_mode):
    m = ctx.mem.setdefault("rect", {"fillet": 0.0, "chamfer": None, "elevation": 0.0, "thickness": 0.0, "width": 0.0})
    u = (math.cos(rot), math.sin(rot))
    v = (-math.sin(rot), math.cos(rot))
    dx, dy = c2[0] - c1[0], c2[1] - c1[1]
    w = dx * u[0] + dy * u[1]
    h = dx * v[0] + dy * v[1]
    origin = c1
    if center_mode:
        origin = [c1[0] - w * u[0] - h * v[0], c1[1] - w * u[1] - h * v[1]]
        w, h = 2 * w, 2 * h
    return finish_rect(ctx, m, origin, w, h, u, v)


def finish_rect(ctx, m, origin, w, h, u, v):
    tol = ctx.d.tolerances["absolute"]
    if abs(w) < tol or abs(h) < tol:
        raise CommandError("The rectangle has no area.")
    corners = _corner_polygon(w, h, origin, u, v)
    orient = 1.0 if w * h > 0 else -1.0
    verts = _rect_vertices(corners, m["fillet"], m["chamfer"], orient)
    width = m["width"]
    for vtx in verts:
        vtx["sw"] = vtx["ew"] = width
    ent = LwPolyline(vertices=verts, closed=True, const_width=width, elevation=m["elevation"])
    handle = ctx.add(ent)
    ctx.d.get(handle).thickness = m["thickness"]
    return handle


def _rect_preview(ctx, m, c1, c2, rot, center_mode, dims):
    u = (math.cos(rot), math.sin(rot))
    v = (-math.sin(rot), math.cos(rot))
    dx, dy = c2[0] - c1[0], c2[1] - c1[1]
    w = dx * u[0] + dy * u[1]
    h = dx * v[0] + dy * v[1]
    origin = c1
    if dims:
        w = dims[0] * (1.0 if w >= 0 else -1.0)
        h = dims[1] * (1.0 if h >= 0 else -1.0)
        if center_mode:
            origin = [c1[0] - (w * u[0] + h * v[0]) / 2, c1[1] - (w * u[1] + h * v[1]) / 2]
    elif center_mode:
        origin = [c1[0] - w * u[0] - h * v[0], c1[1] - w * u[1] - h * v[1]]
        w, h = 2 * w, 2 * h
    tol = ctx.d.tolerances["absolute"]
    if abs(w) < tol or abs(h) < tol:
        return jig.rubber(c1, c2)
    corners = _corner_polygon(w, h, origin, u, v)
    verts = _rect_vertices(corners, m["fillet"], m["chamfer"], 1.0 if w * h > 0 else -1.0)
    return [jig.poly(verts, True)]


def _rect_modes(m):
    out = []
    if m["chamfer"]:
        out.append("Chamfer=%g x %g" % tuple(m["chamfer"]))
    if m["fillet"] > 0:
        out.append("Fillet=%g" % m["fillet"])
    if m["elevation"]:
        out.append("Elevation=%g" % m["elevation"])
    if m["thickness"]:
        out.append("Thickness=%g" % m["thickness"])
    if m["width"]:
        out.append("Width=%g" % m["width"])
    return out


@command("rectang", aliases=("rec", "rectangle"), group="draw", label="Rectangle", description="Closed rectangle polyline with chamfer, fillet, width, elevation, thickness, area, dimensions, rotation and centre modes.", menu="Draw > Rectangle")
def rectang(ctx):
    m = ctx.mem.setdefault("rect", {"fillet": 0.0, "chamfer": None, "elevation": 0.0, "thickness": 0.0, "width": 0.0})
    modes = _rect_modes(m)
    if modes:
        ctx.say("Current rectangle modes: " + " ".join(modes))
    center_mode = False
    rot = 0.0
    while True:
        msg = "Specify center point for rectangle" if center_mode else "Specify first corner point"
        r = yield ctx.point(msg, ["Chamfer", "CEnter", "Elevation", "Fillet", "Thickness", "Width"])
        if r.kind != "keyword":
            break
        k = r.value
        if k == "CEnter":
            center_mode = not center_mode
        elif k == "Chamfer":
            a = yield ctx.distance("Specify first chamfer distance for rectangles", default=(m["chamfer"][0] if m["chamfer"] else 0.0), nonneg=True)
            if a.kind != "number":
                return
            b = yield ctx.distance("Specify second chamfer distance for rectangles", default=a.value, nonneg=True)
            if b.kind != "number":
                return
            m["chamfer"] = (a.value, b.value) if a.value > 0 or b.value > 0 else None
            m["fillet"] = 0.0
        elif k == "Fillet":
            a = yield ctx.distance("Specify fillet radius for rectangles", default=m["fillet"], nonneg=True)
            if a.kind != "number":
                return
            m["fillet"] = a.value
            m["chamfer"] = None
        elif k == "Elevation":
            a = yield ctx.distance("Specify the elevation for rectangles", default=m["elevation"])
            if a.kind == "number":
                m["elevation"] = a.value
        elif k == "Thickness":
            a = yield ctx.distance("Specify the thickness for rectangles", default=m["thickness"])
            if a.kind == "number":
                m["thickness"] = a.value
        elif k == "Width":
            a = yield ctx.distance("Specify line width for rectangles", default=m["width"], nonneg=True)
            if a.kind == "number":
                m["width"] = a.value
    if r.kind != "point":
        return
    c1 = r.value
    dims = None
    while True:
        o = yield ctx.point("Specify other corner point", ["Area", "Dimensions", "Rotation"], base=c1, rect=True, jig=lambda p: _rect_preview(ctx, m, c1, p, rot, center_mode, dims))
        if o.kind == "point":
            break
        if o.kind != "keyword":
            return
        if o.value == "Rotation":
            q = yield ctx.angle("Specify rotation angle", ["Pick points"], default=0.0)
            if q.kind == "keyword":
                p1 = yield ctx.point("Specify first point")
                p2 = yield ctx.point("Specify second point", base=p1.value)
                if p1.kind == "point" and p2.kind == "point":
                    rot = geom.angle_of(p1.value, p2.value)
            elif q.kind == "number":
                rot = q.value
        elif o.value == "Dimensions":
            ln = yield ctx.distance("Specify length for rectangles", positive=True)
            if ln.kind != "number":
                return
            wd = yield ctx.distance("Specify width for rectangles", positive=True)
            if wd.kind != "number":
                return
            dims = (ln.value, wd.value)
        else:
            ar = yield ctx.number("Enter area of rectangle in current units", positive=True)
            if ar.kind != "number":
                return
            basis = yield ctx.keyword("Calculate rectangle dimensions based on [Length/Width]", ["Length", "Width"], "Length")
            if basis.kind != "keyword":
                return
            val = yield ctx.distance("Enter rectangle %s" % basis.value.lower(), positive=True)
            if val.kind != "number":
                return
            ln = val.value if basis.value == "Length" else ar.value / val.value
            wd = ar.value / val.value if basis.value == "Length" else val.value
            u = (math.cos(rot), math.sin(rot))
            v = (-math.sin(rot), math.cos(rot))
            origin = c1
            if center_mode:
                origin = [c1[0] - (ln * u[0] + wd * v[0]) / 2, c1[1] - (ln * u[1] + wd * v[1]) / 2]
            finish_rect(ctx, m, origin, ln, wd, u, v)
            return
    c2 = o.value
    if dims:
        u = (math.cos(rot), math.sin(rot))
        v = (-math.sin(rot), math.cos(rot))
        dx, dy = c2[0] - c1[0], c2[1] - c1[1]
        sx = 1.0 if dx * u[0] + dy * u[1] >= 0 else -1.0
        sy = 1.0 if dx * v[0] + dy * v[1] >= 0 else -1.0
        w, h = dims[0] * sx, dims[1] * sy
        origin = c1
        if center_mode:
            origin = [c1[0] - (w * u[0] + h * v[0]) / 2, c1[1] - (w * u[1] + h * v[1]) / 2]
        finish_rect(ctx, m, origin, w, h, u, v)
        return
    _build_rect(ctx, c1, c2, rot, center_mode)


@executes("rectang")
def rectang_exec(ctx, args):
    m = {"fillet": float(args.get("fillet", 0.0)), "chamfer": None, "elevation": float(args.get("elevation", 0.0)), "thickness": float(args.get("thickness", 0.0)), "width": float(args.get("width", 0.0))}
    if m["width"] < 0 or m["fillet"] < 0:
        raise CommandError("Negative widths and radii are refused.")
    if args.get("chamfer"):
        ch = args["chamfer"]
        if min(ch) < 0:
            raise CommandError("Negative chamfer is refused.")
        m["chamfer"] = (float(ch[0]), float(ch[1]))
        m["fillet"] = 0.0
    rot = math.radians(float(args.get("rotation", 0.0)))
    p1 = _pt(args["p1"])
    center = bool(args.get("center"))
    if "p2" in args:
        return {"handle": _build_rect(ctx, p1, _pt(args["p2"]), rot, center)}
    if "dimensions" in args:
        ln, wd = (float(x) for x in args["dimensions"])
        u = (math.cos(rot), math.sin(rot))
        v = (-math.sin(rot), math.cos(rot))
        origin = [p1[0] - (ln * u[0] + wd * v[0]) / 2, p1[1] - (ln * u[1] + wd * v[1]) / 2] if center else p1
        return {"handle": finish_rect(ctx, m, origin, ln, wd, u, v)}
    raise CommandError("Give p2 or dimensions.")


def _vertex(p, bulge=0.0, sw=0.0, ew=0.0):
    return {"p": [p[0], p[1]], "bulge": bulge, "sw": sw, "ew": ew}


class _PlineState:
    def __init__(self, ctx):
        self.ctx = ctx
        self.verts = []
        self.handle = None
        self.closed = False
        self.sw = 0.0
        self.ew = 0.0
        self.arc_mode = False
        self.tangent_override = None

    def tangent(self):
        if len(self.verts) < 2:
            return self.tangent_override if self.tangent_override is not None else 0.0
        if self.tangent_override is not None:
            return self.tangent_override
        a, b = self.verts[-2], self.verts[-1]
        ang = geom.angle_of(a["p"], b["p"])
        if abs(a["bulge"]) > 1e-12:
            ang += 2.0 * math.atan(a["bulge"])
        return ang

    def sync(self):
        d = self.ctx.d
        if len(self.verts) < 2:
            if self.handle is not None:
                d.erase_entity(self.handle)
                self.handle = None
            return
        widths = {(v["sw"], v["ew"]) for v in self.verts[:-1]}
        const = 0.0
        if len(widths) == 1:
            sw, ew = next(iter(widths))
            if sw == ew:
                const = sw
        verts = [dict(v, p=list(v["p"])) for v in self.verts]
        if self.handle is None:
            self.handle = self.ctx.add(LwPolyline(vertices=verts, closed=self.closed, const_width=const))
        else:
            e = d.modify(self.handle)
            e.vertices = verts
            e.closed = self.closed
            e.const_width = const

    def add_vertex(self, p, bulge_prev=0.0):
        if self.verts:
            self.verts[-1]["bulge"] = bulge_prev
            self.verts[-1]["sw"] = self.sw
            self.verts[-1]["ew"] = self.ew
        self.verts.append(_vertex(p))
        self.tangent_override = None
        self.sync()

    def pop_vertex(self):
        if not self.verts:
            return False
        self.verts.pop()
        if self.verts:
            self.verts[-1]["bulge"] = 0.0
        self.tangent_override = None
        self.sync()
        return True


def _bulge_tangent(s, e, phi):
    alpha = geom.angle_of(s, e)
    diff = (alpha - phi + math.pi) % (2 * math.pi) - math.pi
    if abs(abs(diff) - math.pi) < 1e-9 or geom.dist(s, e) < geom.EPS:
        return None
    return math.tan(diff / 2.0)


def _pline_arc_preview(last, p, tangent):
    b = _bulge_tangent(last, p, tangent)
    if b is None:
        return jig.rubber(last, p)
    return [jig.segment(last, p, b)]


def _width_prompts(ctx, st, half):
    label = "half-width" if half else "width"
    a = yield ctx.distance("Specify starting %s" % label, default=st.sw / (2 if half else 1), nonneg=True)
    if a.kind != "number":
        return
    b = yield ctx.distance("Specify ending %s" % label, default=a.value, nonneg=True)
    if b.kind != "number":
        return
    k = 2.0 if half else 1.0
    st.sw = max(0.0, a.value * k)
    st.ew = max(0.0, b.value * k)


@command("pline", aliases=("pl",), group="draw", label="Polyline", description="Single polyline with line and arc segments, widths, Close and Undo.", menu="Draw > Polyline")
def pline(ctx):
    st = _PlineState(ctx)
    st.sw = st.ew = float(ctx.d.header.get("PLINEWID", 0.0))
    first = yield ctx.point("Specify start point")
    if first.kind != "point":
        return
    st.add_vertex(first.value)
    ctx.say("Current line-width is %s" % ctx.fd(st.sw))
    while True:
        last = st.verts[-1]["p"]
        if not st.arc_mode:
            opts = ["Arc"]
            if len(st.verts) >= 2:
                opts.append("Close")
            opts += ["Halfwidth", "Length", "Undo", "Width"]
            r = yield ctx.point("Specify next point", opts, base=last, jig=lambda p: jig.rubber(last, p))
            if r.kind == "enter":
                return
            if r.kind == "point":
                if ctx.same(r.value, last):
                    continue
                st.add_vertex(r.value)
                continue
            k = r.value
            if k == "Arc":
                st.arc_mode = True
            elif k == "Close":
                if len(st.verts) < 2:
                    continue
                st.verts[-1]["sw"], st.verts[-1]["ew"] = st.sw, st.ew
                st.closed = True
                st.sync()
                return
            elif k in ("Halfwidth", "Width"):
                yield from _width_prompts(ctx, st, k == "Halfwidth")
            elif k == "Length":
                ln = yield ctx.distance("Specify length of line", positive=True)
                if ln.kind == "number":
                    st.add_vertex(geom.polar(last, ln.value, st.tangent()))
            elif k == "Undo":
                if len(st.verts) <= 1:
                    st.pop_vertex()
                    return
                st.pop_vertex()
            continue
        opts = ["Angle", "CEnter", "CLose", "Direction", "Halfwidth", "Line", "Radius", "Second pt", "Undo", "Width"]
        r = yield ctx.point("Specify endpoint of arc", opts, base=last, jig=lambda p: _pline_arc_preview(last, p, st.tangent()))
        if r.kind == "enter":
            return
        if r.kind == "point":
            b = _bulge_tangent(last, r.value, st.tangent())
            if b is None:
                ctx.say("Invalid arc or circle for these values.")
                continue
            st.add_vertex(r.value, b)
            continue
        k = r.value
        if k == "Line":
            st.arc_mode = False
        elif k == "Undo":
            if len(st.verts) <= 1:
                st.pop_vertex()
                return
            st.pop_vertex()
        elif k in ("Halfwidth", "Width"):
            yield from _width_prompts(ctx, st, k == "Halfwidth")
        elif k == "CLose":
            first_p = st.verts[0]["p"]
            b = _bulge_tangent(last, first_p, st.tangent())
            if b is None:
                ctx.say("Invalid arc or circle for these values.")
                continue
            st.verts[-1]["bulge"] = b
            st.verts[-1]["sw"], st.verts[-1]["ew"] = st.sw, st.ew
            st.closed = True
            st.sync()
            return
        elif k == "Second pt":
            p2 = yield ctx.point("Specify second point on arc", base=last, jig=lambda p: jig.rubber(last, p))
            if p2.kind != "point":
                continue
            p3 = yield ctx.point("Specify end point of arc", base=p2.value, jig=lambda p: jig.arc_through(last, p2.value, p))
            if p3.kind != "point":
                continue
            res = geom.circle_from_3pts(last, p2.value, p3.value)
            if res is None:
                ctx.say("Invalid arc or circle for these values.")
                continue
            ccw = geom.cross2(geom.sub(p2.value, last), geom.sub(p3.value, last)) > 0
            st.add_vertex(p3.value, geom.bulge_from_arc_points(last, p3.value, res[0], ccw))
        elif k == "Direction":
            a = yield ctx.angle("Specify the tangent direction for the start point of arc", base=last)
            if a.kind != "number":
                continue
            e = yield ctx.point("Specify endpoint of arc", base=last, jig=lambda p: _pline_arc_preview(last, p, a.value))
            if e.kind != "point":
                continue
            b = _bulge_tangent(last, e.value, a.value)
            if b is None:
                ctx.say("Invalid arc or circle for these values.")
                continue
            st.add_vertex(e.value, b)
        elif k == "Angle":
            a = yield ctx.angle("Specify included angle", absolute=False)
            if a.kind != "number" or abs(a.value) < 1e-9 or abs(a.value) >= geom.TAU:
                continue
            e = yield ctx.point("Specify endpoint of arc", ["CEnter", "Radius"], base=last, jig=lambda p: [jig.segment(last, p, math.tan(a.value / 4.0))])
            if e.kind == "point":
                st.add_vertex(e.value, math.tan(a.value / 4.0))
            elif e.kind == "keyword" and e.value == "CEnter":
                c = yield ctx.point("Specify center point of arc", base=last)
                if c.kind != "point":
                    continue
                rad = geom.dist(c.value, last)
                a1 = geom.angle_of(c.value, last) + a.value
                st.add_vertex(geom.polar(c.value, rad, a1), math.tan(a.value / 4.0))
            elif e.kind == "keyword":
                rr = yield ctx.distance("Specify radius of arc", positive=True, base=last)
                if rr.kind != "number":
                    continue
                dflt = st.tangent() + a.value / 2.0
                chord_dir = yield ctx.angle("Specify direction of chord for arc", default=dflt, base=last)
                if chord_dir.kind != "number":
                    continue
                chord = 2.0 * rr.value * math.sin(abs(a.value) / 2.0)
                st.add_vertex(geom.polar(last, chord, chord_dir.value), math.tan(a.value / 4.0))
        elif k == "CEnter":
            c = yield ctx.point("Specify center point of arc", base=last)
            if c.kind != "point":
                continue
            rad = geom.dist(c.value, last)
            a0 = geom.angle_of(c.value, last)
            tang = st.tangent()
            ccw = math.cos(tang - (a0 + math.pi / 2.0)) >= 0
            e = yield ctx.point("Specify endpoint of arc", ["Angle", "Length"], base=c.value)
            if e.kind == "point":
                a1 = geom.angle_of(c.value, e.value)
                sweep = geom.ccw_sweep(a0, a1) if ccw else -geom.ccw_sweep(a1, a0)
                st.add_vertex(geom.polar(c.value, rad, a1), math.tan(sweep / 4.0))
            elif e.kind == "keyword" and e.value == "Angle":
                a = yield ctx.angle("Specify included angle", absolute=False)
                if a.kind != "number" or abs(a.value) < 1e-9 or abs(a.value) >= geom.TAU:
                    continue
                sweep = abs(a.value) if ccw else -abs(a.value)
                st.add_vertex(geom.polar(c.value, rad, a0 + sweep), math.tan(sweep / 4.0))
            elif e.kind == "keyword":
                ln = yield ctx.distance("Specify length of chord", positive=True, base=last)
                if ln.kind != "number" or ln.value > 2 * rad:
                    ctx.say("Invalid arc or circle for these values.")
                    continue
                sweep = 2.0 * math.asin(ln.value / (2.0 * rad))
                sweep = sweep if ccw else -sweep
                st.add_vertex(geom.polar(c.value, rad, a0 + sweep), math.tan(sweep / 4.0))
        elif k == "Radius":
            rr = yield ctx.distance("Specify radius of arc", positive=True, base=last)
            if rr.kind != "number":
                continue
            e = yield ctx.point("Specify endpoint of arc", base=last)
            if e.kind != "point":
                continue
            chord = geom.dist(last, e.value)
            if chord > 2 * rr.value or chord < geom.EPS:
                ctx.say("Invalid arc or circle for these values.")
                continue
            theta = 2.0 * math.asin(chord / (2.0 * rr.value))
            alpha = geom.angle_of(last, e.value)
            diff = (alpha - st.tangent() + math.pi) % (2 * math.pi) - math.pi
            sign = 1.0 if diff >= 0 else -1.0
            st.add_vertex(e.value, sign * math.tan(theta / 4.0))
