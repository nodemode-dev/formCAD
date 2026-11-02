import math

from app.cmd import jig
from app.cmd.context import CommandError
from app.cmd.draw_support import add_like, add_props, ensure_linetype, pick_entity, rect_corners, signed_area, with_jig
from app.cmd.registry import command, executes
from app.doc import curvepath, geom
from app.doc.entities import Circle, Ellipse, Line, LwPolyline, Polyline3d, Spline
from app.doc.kinds.wipeout import Wipeout

THETA = 4.0 * math.atan(0.5)
RATIO = THETA / (2.0 * math.sin(THETA / 2.0))
CALLIGRAPHY = 0.15
MAX_3D = 20000
CLOUD_TYPES = ("Rectangular", "Polygonal", "Freehand")
CLOUD_MSG = "The revision cloud needs at least three points enclosing an area."


def _xy(p):
    return [float(p[0]), float(p[1])]


def _orient(pts):
    return list(pts) if signed_area(pts) >= 0 else list(reversed(pts))


def _lerp(a, b, t):
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]


def edge_vertices(pts, arclen):
    chord = arclen / RATIO
    out = []
    n = len(pts)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        k = max(1, int(round(geom.dist(a, b) / chord)))
        for j in range(k):
            out.append(_lerp(a, b, j / k))
    return out


def perimeter_vertices(pts, arclen):
    chord = arclen / RATIO
    n = len(pts)
    seg = [geom.dist(pts[i], pts[(i + 1) % n]) for i in range(n)]
    total = sum(seg)
    count = max(3, int(round(total / chord)))
    out = []
    i = 0
    acc = 0.0
    for k in range(count):
        s = total * k / count
        while i < n - 1 and acc + seg[i] <= s:
            acc += seg[i]
            i += 1
        t = (s - acc) / seg[i] if seg[i] else 0.0
        out.append(_lerp(pts[i], pts[(i + 1) % n], t))
    return out


def cloud_vertices(verts, style, reverse):
    n = len(verts)
    out = []
    for i in range(n):
        a, b = verts[i], verts[(i + 1) % n]
        arc = geom.dist(a, b) * RATIO
        sw, ew = (0.0, CALLIGRAPHY * arc) if style == 1 else (0.0, 0.0)
        out.append({"p": _xy(a), "bulge": -0.5 if reverse else 0.5, "sw": sw, "ew": ew})
    return out


def make_cloud(verts, arclen, style, reverse) -> LwPolyline:
    if len(verts) < 3 or abs(signed_area(verts)) <= geom.EPS:
        raise CommandError(CLOUD_MSG)
    ent = LwPolyline(vertices=cloud_vertices(verts, style, reverse), closed=True)
    ent.extra = {"revcloud": {"arc_length": float(arclen), "style": int(style), "reverse": bool(reverse)}}
    return ent


def rect_cloud(a, b, arclen, style, reverse):
    return make_cloud(edge_vertices(_orient(rect_corners(a, b)), arclen), arclen, style, reverse)


def poly_cloud(pts, arclen, style, reverse):
    flat = [_xy(p) for p in pts]
    if len(flat) < 3 or abs(signed_area(flat)) <= geom.EPS:
        raise CommandError(CLOUD_MSG)
    return make_cloud(edge_vertices(_orient(flat), arclen), arclen, style, reverse)


def free_cloud(pts, arclen, style, reverse):
    flat = [_xy(p) for p in pts]
    if len(flat) < 3 or abs(signed_area(flat)) <= geom.EPS:
        raise CommandError(CLOUD_MSG)
    return make_cloud(perimeter_vertices(_orient(flat), arclen), arclen, style, reverse)


def object_ok(ent) -> bool:
    if isinstance(ent, Circle):
        return True
    if isinstance(ent, Ellipse):
        return abs(ent.end_param - ent.start_param) >= geom.TAU - 1e-9 or abs(geom.ccw_sweep(ent.start_param, ent.end_param) - geom.TAU) < 1e-9
    if isinstance(ent, LwPolyline):
        return bool(ent.closed) and len(ent.vertices) >= 2
    if isinstance(ent, Spline):
        return bool(ent.closed)
    return False


def object_cloud(ctx, ent, arclen, style, reverse):
    if not object_ok(ent):
        raise CommandError("Select a closed polyline, circle, ellipse or closed spline.")
    path = curvepath.build(ent)
    if path is None or path.length <= geom.EPS:
        raise CommandError("Select a closed polyline, circle, ellipse or closed spline.")
    count = max(3, int(round(path.length / (arclen / RATIO))))
    verts = [_xy(path.at(path.length * k / count)[0]) for k in range(count)]
    return make_cloud(verts, arclen, style, reverse)


def _replace_with(ctx, src, cloud) -> int:
    h = add_like(ctx, cloud, src)
    ctx.d.erase_entity(src.handle)
    return h


def _cloud_shape(ent):
    return jig.poly([[v["p"][0], v["p"][1], v["bulge"]] for v in ent.vertices], True)


def _try(fn, *a):
    try:
        return [_cloud_shape(fn(*a))]
    except CommandError:
        return []


def _revcloud(ctx, mode):
    ctype = mode
    while True:
        arclen = float(ctx.var("REVCLOUDARCLEN"))
        style = int(ctx.var("REVCLOUDSTYLE"))
        prompt = ctx.point("Specify start point", ["Arc length", "Object", "Rectangular", "Polygonal", "Freehand", "Style"], default_text="Object")
        r = yield prompt
        if r.kind == "keyword":
            if r.value == "Arc length":
                a = yield ctx.number("Specify arc length", default=arclen, positive=True)
                if a.kind in ("number", "enter"):
                    ctx.setvar("REVCLOUDARCLEN", arclen if a.kind == "enter" else float(a.value))
                continue
            if r.value == "Style":
                s = yield ctx.keyword("Select arc style", ["Normal", "Calligraphy"], "Calligraphy" if style else "Normal")
                if s.kind in ("keyword", "enter"):
                    pick = s.value if s.kind == "keyword" else ("Calligraphy" if style else "Normal")
                    ctx.setvar("REVCLOUDSTYLE", 1 if pick == "Calligraphy" else 0)
                continue
            if r.value in CLOUD_TYPES:
                ctype = CLOUD_TYPES.index(r.value)
                ctx.setvar("REVCLOUDTYPE", ctype)
                continue
            yield from _object_mode(ctx, arclen, style)
            return
        if r.kind == "enter":
            yield from _object_mode(ctx, arclen, style)
            return
        if r.kind != "point":
            return
        start = r.value
        if ctype == 0:
            c = yield ctx.point("Specify opposite corner", base=start, rect=True, jig=lambda p: _try(rect_cloud, start, p, arclen, style, False))
            if c.kind != "point":
                return
            ctx.add(rect_cloud(start, c.value, arclen, style, False))
        else:
            pts = [start]
            while True:
                opts = ["Undo"] if len(pts) > 1 else []
                n = yield ctx.point("Specify next point", opts, base=pts[-1], jig=lambda p: _try(poly_cloud if ctype == 1 else free_cloud, pts + [p], arclen, style, False))
                if n.kind == "enter":
                    break
                if n.kind == "keyword" and n.value == "Undo":
                    pts.pop()
                    continue
                if n.kind != "point":
                    return
                if not ctx.same(n.value, pts[-1]):
                    pts.append(n.value)
            ctx.add((poly_cloud if ctype == 1 else free_cloud)(pts, arclen, style, False))
        ctx.say("Revision cloud finished.")
        return


def _object_mode(ctx, arclen, style):
    while True:
        r = yield ctx.entity("Select object")
        if r.kind != "entity":
            return
        ent = pick_entity(ctx, r.value)
        if ent is None or not object_ok(ent):
            ctx.say("Select a closed polyline, circle, ellipse or closed spline.")
            continue
        break
    rev = yield ctx.yesno("Reverse direction?", "No")
    reverse = rev.kind == "keyword" and rev.value == "Yes"
    _replace_with(ctx, ent, object_cloud(ctx, ent, arclen, style, reverse))
    ctx.say("Revision cloud finished.")


@command("revcloud", group="draw", label="Rectangular", description="Rectangular revision cloud (also Object, Polygonal, Freehand, arc length, style).", menu="Draw > Revision Cloud > Rectangular")
def revcloud(ctx):
    yield from _revcloud(ctx, 0)


@command("revcloud.polygonal", group="draw", label="Polygonal", description="Polygonal revision cloud.", menu="Draw > Revision Cloud > Polygonal")
def revcloud_polygonal(ctx):
    yield from _revcloud(ctx, 1)


@command("revcloud.freehand", group="draw", label="Freehand", description="Freehand revision cloud.", menu="Draw > Revision Cloud > Freehand")
def revcloud_freehand(ctx):
    yield from _revcloud(ctx, 2)


def _cloud_exec(ctx, args, mode):
    arclen = float(args.get("arc_length", ctx.var("REVCLOUDARCLEN")))
    if not (arclen > 0 and math.isfinite(arclen)):
        raise CommandError("Value must be positive and nonzero.")
    style = args.get("style", ctx.var("REVCLOUDSTYLE"))
    style = 1 if str(style).lower() in ("1", "calligraphy") else 0
    reverse = bool(args.get("reverse", False))
    if "handle" in args:
        ent = ctx.d.get(int(args["handle"]))
        if ent is None:
            raise CommandError("Select a closed polyline, circle, ellipse or closed spline.")
        return {"handle": _replace_with(ctx, ent, object_cloud(ctx, ent, arclen, style, reverse))}
    if "p1" in args and "p2" in args:
        return {"handle": ctx.add(rect_cloud(geom.as_pt(args["p1"]), geom.as_pt(args["p2"]), arclen, style, reverse))}
    if "freehand" in args:
        return {"handle": ctx.add(free_cloud([geom.as_pt(p) for p in args["freehand"]], arclen, style, reverse))}
    if "points" in args:
        return {"handle": ctx.add((free_cloud if mode == 2 else poly_cloud)([geom.as_pt(p) for p in args["points"]], arclen, style, reverse))}
    raise CommandError("Give p1 and p2, points, freehand points or a handle.")


@executes("revcloud")
def revcloud_exec(ctx, args):
    return _cloud_exec(ctx, args, 0)


@executes("revcloud.polygonal")
def revcloud_polygonal_exec(ctx, args):
    return _cloud_exec(ctx, args, 1)


@executes("revcloud.freehand")
def revcloud_freehand_exec(ctx, args):
    return _cloud_exec(ctx, args, 2)


FRAME_NAMES = ("OFF", "ON", "Display but not plot")


def wipeout_from_polyline(ent):
    if not isinstance(ent, LwPolyline):
        raise CommandError("Select a closed polyline.")
    if any(abs(v.get("bulge", 0.0) or 0.0) > 1e-12 for v in ent.vertices):
        raise CommandError("Polylines with arc segments cannot be used for wipeouts.")
    if not ent.closed or len(ent.vertices) < 3:
        raise CommandError("Select a closed polyline with at least three vertices.")
    return [[v["p"][0], v["p"][1], 0.0] for v in ent.vertices]


def make_wipeout(pts) -> Wipeout:
    flat = [[float(p[0]), float(p[1]), 0.0] for p in pts]
    if len(flat) < 3 or abs(signed_area(flat)) <= geom.EPS:
        raise CommandError("The wipeout needs at least three points enclosing an area.")
    return Wipeout(points=flat)


@command("wipeout", group="draw", label="Wipeout", description="Masking polygon from points or a closed polyline; Frames display mode.", menu="Draw > Wipeout")
def wipeout(ctx):
    while True:
        r = yield ctx.point("Specify first point", ["Frames", "Polyline"], default_text="Polyline")
        if r.kind == "keyword" and r.value == "Frames":
            cur = int(ctx.var("WIPEOUTFRAME"))
            f = yield ctx.keyword("Enter mode", ["ON", "OFF", "Display but not plot"], FRAME_NAMES[cur])
            if f.kind in ("keyword", "enter"):
                name = f.value if f.kind == "keyword" else FRAME_NAMES[cur]
                ctx.setvar("WIPEOUTFRAME", FRAME_NAMES.index(name))
            continue
        break
    if r.kind == "enter" or (r.kind == "keyword" and r.value == "Polyline"):
        while True:
            e = yield ctx.entity("Select a closed polyline")
            if e.kind != "entity":
                return
            ent = pick_entity(ctx, e.value)
            try:
                pts = wipeout_from_polyline(ent)
            except CommandError as err:
                ctx.say(str(err))
                continue
            break
        er = yield ctx.yesno("Erase polyline?", "No")
        ctx.add(make_wipeout(pts))
        if er.kind == "keyword" and er.value == "Yes":
            ctx.d.erase_entity(ent.handle)
        return
    if r.kind != "point":
        return
    pts = [r.value]
    while True:
        opts = ["Undo"] if len(pts) > 1 else []
        n = yield ctx.point("Specify next point", opts, base=pts[-1], jig=lambda p: [jig.poly([[q[0], q[1], 0.0] for q in pts + [p]], True)] if len(pts) >= 2 else [jig.line(pts[-1], p)])
        if n.kind == "enter":
            break
        if n.kind == "keyword" and n.value == "Undo":
            pts.pop()
            continue
        if n.kind != "point":
            return
        if not ctx.same(n.value, pts[-1]):
            pts.append(n.value)
    ctx.add(make_wipeout(pts))


@executes("wipeout")
def wipeout_exec(ctx, args):
    if "frames" in args:
        v = args["frames"]
        mode = {"on": 1, "off": 0, "display": 2}.get(str(v).lower(), v)
        if mode not in (0, 1, 2):
            raise CommandError("Frames must be on, off or display (0, 1, 2).")
        ctx.setvar("WIPEOUTFRAME", int(mode))
        if "points" not in args and "handle" not in args:
            return {"frames": int(mode)}
    if "handle" in args:
        ent = ctx.d.get(int(args["handle"]))
        pts = wipeout_from_polyline(ent)
        h = ctx.add(make_wipeout(pts))
        if args.get("erase"):
            ctx.d.erase_entity(ent.handle)
        return {"handle": h}
    pts = [geom.as_pt(p) for p in args.get("points", [])]
    return {"handle": ctx.add(make_wipeout(pts))}


@command("3dpoly", aliases=("3p",), group="draw", label="3D Polyline", description="Polyline with 3D vertices.", menu="Draw > 3D Polyline")
def poly3d(ctx):
    first = yield ctx.point("Specify start point of polyline")
    if first.kind != "point":
        return
    pts = [list(first.value)]
    handle = None

    def live():
        nonlocal handle
        if len(pts) >= 2 and handle is None:
            handle = ctx.add(Polyline3d(points=[list(p) for p in pts]))
        elif handle is not None:
            if len(pts) < 2:
                ctx.d.erase_entity(handle)
                handle = None
            else:
                ctx.d.modify(handle).points = [list(p) for p in pts]

    while True:
        opts = ["Undo"]
        if len(pts) >= 3:
            opts.append("Close")
        r = yield ctx.point("Specify endpoint of line", opts, base=pts[-1], jig=lambda p: [jig.poly([[q[0], q[1], 0.0] for q in pts + [p]], False)])
        if r.kind == "enter":
            return
        if r.kind == "keyword":
            if r.value == "Undo":
                if len(pts) > 1:
                    pts.pop()
                    live()
                continue
            if r.value == "Close":
                if handle is not None:
                    ctx.d.modify(handle).closed = True
                return
        if r.kind != "point":
            return
        if ctx.same(r.value, pts[-1]) and abs(r.value[2] - pts[-1][2]) <= geom.EPS:
            continue
        if len(pts) >= MAX_3D:
            ctx.say("The polyline has reached the vertex limit.")
            return
        pts.append(list(r.value))
        live()


@executes("3dpoly")
def poly3d_exec(ctx, args):
    clean = []
    for p in args.get("points", []):
        q = geom.as_pt(p)
        if not clean or max(abs(q[i] - clean[-1][i]) for i in range(3)) > geom.EPS:
            clean.append(q)
    if len(clean) < 2:
        raise CommandError("A 3D polyline needs at least two distinct points.")
    if len(clean) > MAX_3D:
        raise CommandError("A 3D polyline holds at most %d vertices." % MAX_3D)
    closed = bool(args.get("closed")) and len(clean) >= 3
    return {"handle": ctx.add(Polyline3d(points=clean, closed=closed))}


def centermark_lines(ent, ext):
    r = ent.radius + ext
    c = ent.center
    return [Line(start=[c[0] - r, c[1], 0.0], end=[c[0] + r, c[1], 0.0]), Line(start=[c[0], c[1] - r, 0.0], end=[c[0], c[1] + r, 0.0])]


def _add_center(ctx, lines) -> list:
    name = ensure_linetype(ctx, "CENTER")
    return [add_props(ctx, ln, linetype=name) for ln in lines]


def _nearest_curve(ctx, p, kinds):
    best, bd = None, None
    for e in ctx.visible_entities():
        if e.kind not in kinds:
            continue
        d = abs(geom.dist(e.center, p) - e.radius) if e.kind in ("circle", "arc") else min(geom.dist(e.start, p), geom.dist(e.end, p))
        if bd is None or d < bd:
            best, bd = e, d
    return best


@command("centermark", group="draw", label="Center Mark", description="Cross centre mark lines for circles and arcs on the CENTER linetype.", menu="Draw > Center Mark")
def centermark(ctx):
    def shape(p):
        e = _nearest_curve(ctx, p, ("circle", "arc"))
        return [jig.line(l.start, l.end) for l in centermark_lines(e, float(ctx.var("CENTEREXE")))] if e is not None else []

    while True:
        r = yield with_jig(ctx.entity("Select circle or arc"), shape)
        if r.kind != "entity":
            return
        ent = pick_entity(ctx, r.value)
        if ent is None or ent.kind not in ("circle", "arc"):
            ctx.say("Select a circle or arc.")
            continue
        _add_center(ctx, centermark_lines(ent, float(ctx.var("CENTEREXE"))))


@executes("centermark")
def centermark_exec(ctx, args):
    out = []
    for h in args.get("handles", [args["handle"]] if "handle" in args else []):
        ent = ctx.d.get(int(h))
        if ent is None or ent.kind not in ("circle", "arc"):
            raise CommandError("Select a circle or arc.")
        out.extend(_add_center(ctx, centermark_lines(ent, float(args.get("extension", ctx.var("CENTEREXE"))))))
    if not out:
        raise CommandError("Select a circle or arc.")
    return {"handles": out}


def centerline_line(a: Line, b: Line, ext: float) -> Line:
    a0, a1 = a.start, a.end
    b0, b1 = b.start, b.end
    da = (a1[0] - a0[0], a1[1] - a0[1])
    db = (b1[0] - b0[0], b1[1] - b0[1])
    if da[0] * db[0] + da[1] * db[1] < 0:
        b0, b1 = b1, b0
    m0 = [(a0[0] + b0[0]) / 2.0, (a0[1] + b0[1]) / 2.0, 0.0]
    m1 = [(a1[0] + b1[0]) / 2.0, (a1[1] + b1[1]) / 2.0, 0.0]
    d = geom.dist(m0, m1)
    if d <= geom.EPS:
        raise CommandError("The lines do not define a center line.")
    ux, uy = (m1[0] - m0[0]) / d, (m1[1] - m0[1]) / d
    return Line(start=[m0[0] - ux * ext, m0[1] - uy * ext, 0.0], end=[m1[0] + ux * ext, m1[1] + uy * ext, 0.0])


def _pick_line(ctx, prompt, shape=None):
    while True:
        r = yield with_jig(ctx.entity(prompt), shape)
        if r.kind != "entity":
            return None
        ent = pick_entity(ctx, r.value)
        if ent is None or ent.kind != "line":
            ctx.say("Select a line.")
            continue
        return ent


@command("centerline", group="draw", label="Center Line", description="Centre line midway between two lines.", menu="Draw > Center Line")
def centerline(ctx):
    ext = float(ctx.var("CENTEREXE"))
    a = yield from _pick_line(ctx, "Select first line")
    if a is None:
        return

    def shape(p):
        e = _nearest_curve(ctx, p, ("line",))
        if e is None or e.handle == a.handle:
            return []
        try:
            ln = centerline_line(a, e, ext)
        except CommandError:
            return []
        return [jig.line(ln.start, ln.end)]

    b = yield from _pick_line(ctx, "Select second line", shape)
    if b is None:
        return
    if b.handle == a.handle:
        raise CommandError("Select two different lines.")
    _add_center(ctx, [centerline_line(a, b, ext)])


@executes("centerline")
def centerline_exec(ctx, args):
    hs = [int(h) for h in args.get("handles", [])]
    if len(hs) != 2:
        raise CommandError("Give the handles of two lines.")
    a, b = ctx.d.get(hs[0]), ctx.d.get(hs[1])
    if a is None or b is None or a.kind != "line" or b.kind != "line":
        raise CommandError("Select a line.")
    return {"handles": _add_center(ctx, [centerline_line(a, b, float(args.get("extension", ctx.var("CENTEREXE"))))])}


ZIGZAG = ((-0.5, 0.0), (-0.25, 0.5), (0.25, -0.5), (0.5, 0.0))


def _block_symbol(ctx, name):
    space = "block:" + name
    pts, segs = [], []
    for e in ctx.d.entities(space):
        if e.kind == "point" and e.layer.lower() == "defpoints":
            pts.append(_xy(e.position))
        elif e.kind == "line":
            segs.append((_xy(e.start), _xy(e.end), 0.0))
        elif e.kind == "lwpolyline":
            n = len(e.vertices)
            for i in range(n if e.closed else n - 1):
                segs.append((_xy(e.vertices[i]["p"]), _xy(e.vertices[(i + 1) % n]["p"]), float(e.vertices[i].get("bulge", 0.0) or 0.0)))
    if len(pts) != 2:
        raise CommandError("The break-line block must hold exactly two points on layer Defpoints.")
    a, b = pts
    chain = [[a, 0.0]]
    cur = a
    pool = list(segs)
    while geom.dist(cur, b) > 1e-6:
        found = None
        for s in pool:
            if geom.dist(s[0], cur) <= 1e-6:
                found = (s[1], s[2], s)
                break
            if geom.dist(s[1], cur) <= 1e-6:
                found = (s[0], -s[2], s)
                break
        if found is None:
            raise CommandError("The lines of the break-line block do not chain between its two points.")
        pool.remove(found[2])
        chain[-1][1] = found[1]
        chain.append([found[0], 0.0])
        cur = found[0]
    return a, b, chain


def breakline_vertices(ctx, p1, p2, loc, size, ext, block):
    L = geom.dist(p1, p2)
    if L <= geom.EPS:
        raise CommandError("The two points coincide.")
    u = ((p2[0] - p1[0]) / L, (p2[1] - p1[1]) / L)
    v = (-u[1], u[0])
    scale = float(size) * float(ctx.var("DIMSCALE") or 1.0)
    if block:
        a, b, chain = _block_symbol(ctx, block)
        width = geom.dist(a, b) * scale
        e1 = ((b[0] - a[0]) / geom.dist(a, b), (b[1] - a[1]) / geom.dist(a, b))
        e2 = (-e1[1], e1[0])
        local = [(((q[0] - a[0]) * e1[0] + (q[1] - a[1]) * e1[1]) * scale, ((q[0] - a[0]) * e2[0] + (q[1] - a[1]) * e2[1]) * scale, bu) for q, bu in chain]
    else:
        width = scale
        local = [((x + 0.5) * scale, y * scale, 0.0) for x, y in ZIGZAG]
    if width > L + 1e-9:
        raise CommandError("The line is shorter than the break symbol.")
    t = (loc[0] - p1[0]) * u[0] + (loc[1] - p1[1]) * u[1]
    t = min(max(t, width / 2.0), L - width / 2.0)
    s0 = t - width / 2.0
    verts = [{"p": [p1[0] - u[0] * ext, p1[1] - u[1] * ext], "bulge": 0.0}]
    for x, y, bu in local:
        verts.append({"p": [p1[0] + u[0] * (s0 + x) + v[0] * y, p1[1] + u[1] * (s0 + x) + v[1] * y], "bulge": bu})
    verts.append({"p": [p2[0] + u[0] * ext, p2[1] + u[1] * ext], "bulge": 0.0})
    out = []
    for q in verts:
        if out and geom.dist(out[-1]["p"], q["p"]) <= 1e-9:
            out[-1]["bulge"] = q["bulge"] or out[-1]["bulge"]
            continue
        out.append({"p": q["p"], "bulge": q["bulge"], "sw": 0.0, "ew": 0.0})
    out[-1]["bulge"] = 0.0
    return out


def _break_ent(verts) -> LwPolyline:
    ent = LwPolyline(vertices=verts, closed=False)
    ent.extra = {"breakline": True}
    return ent


@command("breakline", group="express", label="Break-line Symbol", description="Polyline with a break symbol inserted along it.", menu="Tools > Express Tools > Break-line Symbol")
def breakline(ctx):
    while True:
        block = str(ctx.var("BRKBLOCK") or "")
        size = float(ctx.var("BRKSIZE"))
        ext = float(ctx.var("BRKEXT"))
        ctx.say("Current block = %s Size = %s Extension = %s" % (block or "<built-in>", ctx.fd(size), ctx.fd(ext)))
        r = yield ctx.point("Specify first point for breakline", ["Block", "Size", "Extension"])
        if r.kind == "keyword":
            if r.value == "Block":
                b = yield ctx.word("Enter block name (. for the built-in symbol)", default=block or ".")
                name = (b.value if b.kind in ("text",) else (block or ".")) if b.kind != "enter" else (block or ".")
                name = str(name).strip()
                if name in ("", "."):
                    ctx.setvar("BRKBLOCK", "")
                elif not ctx.d.table_get("blocks", name):
                    ctx.say("Block %s not found." % name)
                else:
                    try:
                        _block_symbol(ctx, name)
                        ctx.setvar("BRKBLOCK", ctx.d.table_get("blocks", name)["name"])
                    except CommandError as err:
                        ctx.say(str(err))
            elif r.value == "Size":
                s = yield ctx.number("Enter size", default=size, positive=True)
                if s.kind == "number":
                    ctx.setvar("BRKSIZE", float(s.value))
            else:
                x = yield ctx.number("Enter extension", default=ext, minimum=0)
                if x.kind == "number":
                    ctx.setvar("BRKEXT", float(x.value))
            continue
        if r.kind != "point":
            return
        p1 = r.value
        break

    def shape(p, loc=None):
        try:
            return [jig.poly([[q["p"][0], q["p"][1], q["bulge"]] for q in breakline_vertices(ctx, p1, p, loc or geom.midpoint(p1, p), size, ext, block or None)])]
        except CommandError:
            return [jig.line(p1, p)]

    s = yield ctx.point("Specify second point for breakline", base=p1, jig=shape)
    if s.kind != "point":
        return
    p2 = s.value
    mid = geom.midpoint(p1, p2)
    loc = yield ctx.point("Specify location for break symbol", default=mid, default_text="Midpoint", base=p1, jig=lambda p: shape(p2, p))
    if loc.kind not in ("point", "enter"):
        return
    at = loc.value if loc.kind == "point" else mid
    ctx.add(_break_ent(breakline_vertices(ctx, p1, p2, at, size, ext, block or None)))


@executes("breakline")
def breakline_exec(ctx, args):
    p1, p2 = geom.as_pt(args["p1"]), geom.as_pt(args["p2"])
    loc = geom.as_pt(args["location"]) if args.get("location") else geom.midpoint(p1, p2)
    size = float(args.get("size", 1.0))
    ext = float(args.get("extension", 0.0))
    block = args.get("block") or None
    if size <= 0 or ext < 0:
        raise CommandError("Size must be positive and extension must not be negative.")
    if block and not ctx.d.table_get("blocks", block):
        raise CommandError("Block %s not found." % block)
    return {"handle": ctx.add(_break_ent(breakline_vertices(ctx, p1, p2, loc, size, ext, block)))}
