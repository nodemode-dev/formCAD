import math

from app.cmd import grips, jig
from app.cmd.commands.modify import LOCKED_MSG, targets
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.doc import curveops, geom
from app.doc.entities import AttDef, Dimension, LwPolyline, MText, Polyline3d, Solid, Spline, Text

TEXT_KINDS = (Text, MText, AttDef)


def _clone_all(ctx, handles, fn, limit=None):
    out = []
    for h in handles[: limit or len(handles)]:
        e = ctx.d.get(h)
        if e is None:
            continue
        c = e.copy_as_new()
        try:
            fn(c)
        except (grips.GripError, ValueError, ZeroDivisionError):
            continue
        out.append(c)
    return out


def _preview(ctx, handles, fn):
    return jig.entity_items(_clone_all(ctx, handles, fn, jig.MAX_ITEMS), ctx.d)


def _commit(ctx, handles, fn, copy):
    if copy:
        rows = [ctx.d.get(h) for h in handles if ctx.d.get(h) is not None]
    else:
        rows = ctx.editable(handles)
    made = []
    skipped = 0
    for e in rows:
        c = e.copy_as_new()
        try:
            fn(c)
        except (grips.GripError, ValueError, ZeroDivisionError):
            skipped += 1
            continue
        if not c.valid():
            skipped += 1
            continue
        if copy:
            try:
                made.append(ctx.d.add_entity(c, e.owner))
            except ValueError:
                skipped += 1
        else:
            grips._assign(ctx.d.modify(e.handle), c)
            made.append(e.handle)
    if skipped:
        ctx.say("%d object(s) could not be changed that way." % skipped)
    if not made and not skipped and handles and not copy:
        ctx.say(LOCKED_MSG)
    return made


def rotate_fn(base, angle):
    xf = grips.Xf("rotate", base, angle)
    return lambda c: grips.transform(c, xf)


def _scale_heights(c, bz, k):
    for name in c.POINTS:
        v = getattr(c, name, None)
        if v is not None and len(v) > 2:
            v = list(v)
            v[2] = bz + (v[2] - bz) * k
            setattr(c, name, v)
    for name in c.POINT_LISTS:
        out = []
        for v in getattr(c, name):
            v = list(v)
            if len(v) > 2:
                v[2] = bz + (v[2] - bz) * k
            out.append(v)
        setattr(c, name, out)
    if hasattr(c, "thickness"):
        c.thickness = c.thickness * k
    if isinstance(c, LwPolyline):
        c.elevation = bz + (c.elevation - bz) * k


def scale_fn(base, k, bz=0.0):
    xf = grips.Xf("scale", base, 0.0, k)

    def fn(c):
        grips.transform(c, xf)
        _scale_heights(c, bz, k)

    return fn


def _mirror_text(c, ang, mirrtext):
    if isinstance(c, TEXT_KINDS):
        if mirrtext:
            c.rotation = geom.norm_angle(2.0 * ang - c.rotation)
            c.extra = dict(c.extra)
            c.extra["mirrored"] = not c.extra.get("mirrored", False)


def mirror_fn(p1, p2, mirrtext):
    ang = geom.angle_of(p1, p2)
    xf = grips.Xf("mirror", p1, ang)

    def fn(c):
        grips.transform(c, xf)
        _mirror_text(c, ang, mirrtext)

    return fn


@command("rotate", aliases=("ro",), group="modify", label="Rotate", description="Rotate objects about a base point; Copy and Reference options.", menu="Modify > Rotate")
def rotate(ctx):
    s = yield ctx.select("Select objects")
    if s.kind != "selection" or not s.value:
        return
    handles = list(s.value)
    b = yield ctx.point("Specify base point")
    if b.kind != "point":
        return
    base = b.value
    last = float(ctx.mem.get("rotate_angle", 0.0))
    copy = False
    ang = None
    while ang is None:
        a = yield ctx.angle("Specify rotation angle", ["Copy", "Reference"], default=last, base=base, absolute=False, jig=lambda q: _preview(ctx, handles, rotate_fn(base, geom.angle_of(base, q))))
        if a.kind == "keyword" and a.value == "Copy":
            copy = True
            ctx.say("Rotating/scaling a copy of the selected objects.")
            continue
        if a.kind == "keyword" and a.value == "Reference":
            ang = yield from _rotate_reference(ctx, base, handles)
            continue
        if a.kind == "number":
            ang = a.value
        elif a.kind == "point":
            if ctx.same(base, a.value):
                ctx.say("The point must differ from the base point.")
                continue
            ang = geom.angle_of(base, a.value)
        else:
            return
    ctx.mem["rotate_angle"] = ang
    _commit(ctx, handles, rotate_fn(base, ang), copy)


def _rotate_reference(ctx, base, handles):
    while True:
        r = yield ctx.angle("Specify the reference angle", default=0.0, base=base, absolute=False)
        if r.kind == "number":
            ref = r.value
            break
        if r.kind == "point":
            q = yield ctx.point("Specify second point", base=r.value, jig=lambda c: [jig.line(r.value, c)])
            if q.kind != "point":
                return None
            if ctx.same(r.value, q.value):
                ctx.say("The two points must differ.")
                continue
            ref = geom.angle_of(r.value, q.value)
            break
        return None
    while True:
        n = yield ctx.angle("Specify the new angle", ["Points"], base=base, absolute=False, jig=lambda q: _preview(ctx, handles, rotate_fn(base, geom.angle_of(base, q) - ref)))
        if n.kind == "number":
            return n.value - ref
        if n.kind == "point":
            if ctx.same(base, n.value):
                ctx.say("The point must differ from the base point.")
                continue
            return geom.angle_of(base, n.value) - ref
        if n.kind == "keyword" and n.value == "Points":
            p1 = yield ctx.point("Specify first point")
            if p1.kind != "point":
                return None
            p2 = yield ctx.point("Specify second point", base=p1.value, jig=lambda c: [jig.line(p1.value, c)])
            if p2.kind != "point":
                return None
            if ctx.same(p1.value, p2.value):
                ctx.say("The two points must differ.")
                continue
            return geom.angle_of(p1.value, p2.value) - ref
        return None


@executes("rotate")
def rotate_exec(ctx, args):
    handles = targets(ctx, args)
    base = geom.as_pt(args.get("base", [0.0, 0.0]))
    if "angle" not in args:
        raise CommandError("Give angle in degrees.")
    ang = math.radians(float(args["angle"]))
    if args.get("reference") is not None:
        ang = math.radians(float(args["angle"]) - float(args["reference"]))
    made = _commit(ctx, handles, rotate_fn(base, ang), bool(args.get("copy")))
    return {"rotated" if not args.get("copy") else "created": made if args.get("copy") else len(made)}


@command("scale", aliases=("sc",), group="modify", label="Scale", description="Scale objects about a base point; Copy and Reference options.", menu="Modify > Scale")
def scale(ctx):
    s = yield ctx.select("Select objects")
    if s.kind != "selection" or not s.value:
        return
    handles = list(s.value)
    b = yield ctx.point("Specify base point")
    if b.kind != "point":
        return
    base = b.value
    bz = float(ctx.d.header.get("ELEVATION", 0.0))
    last = float(ctx.mem.get("scale_factor", 1.0))
    copy = False
    k = None
    while k is None:
        a = yield ctx.distance("Specify scale factor", ["Copy", "Reference"], default=last, base=base, positive=True, jig=lambda q: _scale_preview(ctx, handles, base, q, bz))
        if a.kind == "keyword" and a.value == "Copy":
            copy = True
            ctx.say("Rotating/scaling a copy of the selected objects.")
            continue
        if a.kind == "keyword" and a.value == "Reference":
            k = yield from _scale_reference(ctx, base, handles, bz)
            continue
        if a.kind == "number":
            k = a.value
        elif a.kind == "point":
            k = geom.dist(base, a.value)
            if k <= geom.EPS:
                ctx.say("Value must be positive and nonzero.")
                k = None
                continue
        else:
            return
    ctx.mem["scale_factor"] = k
    _commit(ctx, handles, scale_fn(base, k, bz), copy)


def _scale_preview(ctx, handles, base, q, bz):
    k = geom.dist(base, q)
    if k <= geom.EPS:
        return []
    return _preview(ctx, handles, scale_fn(base, k, bz))


def _scale_reference(ctx, base, handles, bz):
    while True:
        r = yield ctx.distance("Specify reference length", default=1.0, base=base, positive=True)
        if r.kind == "number":
            ref = r.value
            break
        if r.kind == "point":
            q = yield ctx.point("Specify second point", base=r.value, jig=lambda c: [jig.line(r.value, c)])
            if q.kind != "point":
                return None
            ref = geom.dist(r.value, q.value)
            if ref <= geom.EPS:
                ctx.say("The two points must differ.")
                continue
            break
        return None
    while True:
        n = yield ctx.distance("Specify new length", ["Points"], base=base, positive=True, jig=lambda q: _scale_preview_ref(ctx, handles, base, q, ref, bz))
        if n.kind == "number":
            return n.value / ref
        if n.kind == "point":
            d = geom.dist(base, n.value)
            if d <= geom.EPS:
                ctx.say("Value must be positive and nonzero.")
                continue
            return d / ref
        if n.kind == "keyword" and n.value == "Points":
            p1 = yield ctx.point("Specify first point")
            if p1.kind != "point":
                return None
            p2 = yield ctx.point("Specify second point", base=p1.value, jig=lambda c: [jig.line(p1.value, c)])
            if p2.kind != "point":
                return None
            d = geom.dist(p1.value, p2.value)
            if d <= geom.EPS:
                ctx.say("The two points must differ.")
                continue
            return d / ref
        return None


def _scale_preview_ref(ctx, handles, base, q, ref, bz):
    d = geom.dist(base, q)
    if d <= geom.EPS:
        return []
    return _preview(ctx, handles, scale_fn(base, d / ref, bz))


@executes("scale")
def scale_exec(ctx, args):
    handles = targets(ctx, args)
    b = geom.as_pt(args.get("base", [0.0, 0.0, float(ctx.d.header.get("ELEVATION", 0.0))]))
    k = float(args.get("factor", 0.0))
    if args.get("reference") is not None:
        ref = float(args["reference"])
        if ref <= 0:
            raise CommandError("The reference length must be positive.")
        k = float(args["factor"]) / ref
    if not k > 0 or not math.isfinite(k):
        raise CommandError("Value must be positive and nonzero.")
    made = _commit(ctx, handles, scale_fn(b, k, b[2]), bool(args.get("copy")))
    return {"created": made} if args.get("copy") else {"scaled": len(made)}


@command("mirror", aliases=("mi",), group="modify", label="Mirror", description="Mirror objects about a line, optionally erasing the source.", menu="Modify > Mirror")
def mirror(ctx):
    s = yield ctx.select("Select objects")
    if s.kind != "selection" or not s.value:
        return
    handles = list(s.value)
    a = yield ctx.point("Specify first point of mirror line")
    if a.kind != "point":
        return
    mt = bool(int(ctx.d.header.get("MIRRTEXT", 0)))

    def prev(q):
        if ctx.same(a.value, q):
            return []
        return [jig.line(a.value, q)] + _preview(ctx, handles, mirror_fn(a.value, q, mt))

    while True:
        b = yield ctx.point("Specify second point of mirror line", base=a.value, jig=prev)
        if b.kind != "point":
            return
        if ctx.same(a.value, b.value):
            ctx.say("Mirror line points must differ.")
            continue
        break
    e = yield ctx.yesno("Erase source objects?", "No")
    if e.kind not in ("keyword", "enter"):
        return
    erase = e.kind == "keyword" and e.value == "Yes"
    _commit(ctx, handles, mirror_fn(a.value, b.value, mt), not erase)


@executes("mirror")
def mirror_exec(ctx, args):
    handles = targets(ctx, args)
    p1, p2 = geom.as_pt(args["p1"]), geom.as_pt(args["p2"])
    if ctx.same(p1, p2):
        raise CommandError("Mirror line points must differ.")
    erase = bool(args.get("erase"))
    made = _commit(ctx, handles, mirror_fn(p1, p2, bool(int(ctx.d.header.get("MIRRTEXT", 0)))), not erase)
    return {"mirrored": len(made), "handles": made}


def _region(area):
    kind, pts = area["kind"], area["pts"]
    if kind in ("window", "crossing") and len(pts) >= 2:
        x0, x1 = sorted((pts[0][0], pts[1][0]))
        y0, y1 = sorted((pts[0][1], pts[1][1]))
        return lambda p: x0 <= p[0] <= x1 and y0 <= p[1] <= y1
    if kind in ("wp", "cp") and len(pts) >= 3:
        poly = [[p[0], p[1]] for p in pts]
        return lambda p: curveops.point_in_poly(p, poly)
    return None


def _inside_for(areas, handle):
    regs = []
    for a in areas:
        if handle in a["handles"]:
            r = _region(a)
            if r is not None:
                regs.append(r)
    if not regs:
        return None
    return lambda p: any(r(p) for r in regs)


def _shift(p, vec):
    q = list(p)
    q[0] += vec[0]
    q[1] += vec[1]
    return q


def stretch_entity(e, inside, vec) -> bool:
    if inside is None:
        e.move_by([vec[0], vec[1], 0.0])
        return True
    changed = False
    if isinstance(e, LwPolyline):
        for v in e.vertices:
            if inside(v["p"]):
                v["p"] = _shift(v["p"], vec)
                changed = True
        return changed
    if e.kind == "line":
        if inside(e.start):
            e.start = _shift(e.start, vec)
            changed = True
        if inside(e.end):
            e.end = _shift(e.end, vec)
            changed = True
        return changed
    if isinstance(e, Polyline3d) or isinstance(e, Solid) or e.kind == "wipeout":
        name = "corners" if isinstance(e, Solid) else "points"
        pts = getattr(e, name)
        for i, p in enumerate(pts):
            if inside(p):
                pts[i] = _shift(p, vec)
                changed = True
        return changed
    if e.kind == "mline":
        for v in e.vertices:
            if inside(v["p"]):
                v["p"] = _shift(v["p"], vec)
                changed = True
        return changed
    if isinstance(e, Dimension):
        for name in Dimension.POINTS:
            v = getattr(e, name)
            if v and inside(v):
                setattr(e, name, _shift(v, vec))
                changed = True
                if name == "text_point":
                    e.text_moved = True
        return changed
    if e.kind in ("ray", "xline"):
        if inside(e.base):
            e.base = _shift(e.base, vec)
            return True
        return False
    if e.kind in ("arc", "circle", "ellipse", "helix"):
        anchor = e.center
    else:
        gs = grips.grips_of(e)
        anchor = gs[0]["p"] if gs else None
    if anchor is not None and inside(anchor):
        e.move_by([vec[0], vec[1], 0.0])
        return True
    return False


def _stretch_preview(ctx, handles, areas, vec):
    out = []
    for h in handles[: jig.MAX_ITEMS]:
        e = ctx.d.get(h)
        if e is None:
            continue
        c = e.copy_as_new()
        if stretch_entity(c, _inside_for(areas, h), vec) and c.valid():
            out.append(c)
    return jig.entity_items(out, ctx.d)


def _stretch_apply(ctx, handles, areas, vec) -> int:
    n = 0
    for e in ctx.editable(handles):
        c = e.copy_as_new()
        if stretch_entity(c, _inside_for(areas, e.handle), vec) and c.valid():
            grips._assign(ctx.d.modify(e.handle), c)
            n += 1
    return n


@command("stretch", aliases=("s",), group="modify", label="Stretch", description="Move vertices inside a crossing window or polygon.", menu="Modify > Stretch")
def stretch(ctx):
    s = yield ctx.select("Select objects to stretch by crossing-window or crossing-polygon")
    if s.kind != "selection" or not s.value:
        return
    handles = list(s.value)
    areas = [a for a in getattr(ctx.runner, "sel_areas", []) if a["kind"] != "fence"]
    b = yield ctx.point("Specify base point", ["Displacement"], default="Displacement", default_text="Displacement")
    if b.kind == "keyword" or b.kind == "enter":
        d = yield ctx.point("Specify displacement", default=[0.0, 0.0, 0.0], jig=lambda q: _stretch_preview(ctx, handles, areas, [q[0], q[1]]))
        if d.kind != "point":
            return
        vec = [d.value[0], d.value[1]]
    elif b.kind == "point":
        p = yield ctx.point("Specify second point or", base=b.value, default_text="use first point as displacement", jig=lambda q: _stretch_preview(ctx, handles, areas, [q[0] - b.value[0], q[1] - b.value[1]]))
        if p.kind == "point":
            vec = [p.value[0] - b.value[0], p.value[1] - b.value[1]]
        elif p.kind == "enter":
            vec = [b.value[0], b.value[1]]
        else:
            return
    else:
        return
    _stretch_apply(ctx, handles, areas, vec)


@executes("stretch")
def stretch_exec(ctx, args):
    if "delta" in args:
        vec = geom.as_pt(args["delta"])[:2]
    elif "from" in args and "to" in args:
        a, b = geom.as_pt(args["from"]), geom.as_pt(args["to"])
        vec = [b[0] - a[0], b[1] - a[1]]
    else:
        raise CommandError("Give delta or from and to.")
    area = None
    if "window" in args:
        w = args["window"]
        if len(w) != 2:
            raise CommandError("A window needs two corners.")
        area = {"kind": "crossing", "pts": [list(map(float, w[0])), list(map(float, w[1]))]}
    elif "polygon" in args:
        pts = args["polygon"]
        if not 3 <= len(pts) <= 10000:
            raise CommandError("A polygon needs 3 to 10000 points.")
        area = {"kind": "cp", "pts": [list(map(float, p)) for p in pts]}
    elif "fence" in args:
        pts = args["fence"]
        if not 2 <= len(pts) <= 10000:
            raise CommandError("A fence needs 2 to 10000 points.")
        area = {"kind": "fence", "pts": [list(map(float, p)) for p in pts]}
    if area is None:
        handles = targets(ctx, args)
        return {"stretched": _stretch_apply(ctx, handles, [], vec)}
    region = _region(area)
    rows = []
    for e in ctx.visible_entities():
        if "handles" in args and e.handle not in [int(h) for h in args["handles"]]:
            continue
        if area["kind"] == "fence":
            if curveops.hit_by_fence(e, area["pts"]):
                rows.append((e.handle, None))
            continue
        if region is None:
            continue
        b = e.bounds()
        if b is None:
            continue
        poly = [[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]]]
        if area["kind"] == "crossing":
            hit = curveops.hit_by_polygon(e, [[area["pts"][0][0], area["pts"][0][1]], [area["pts"][1][0], area["pts"][0][1]], [area["pts"][1][0], area["pts"][1][1]], [area["pts"][0][0], area["pts"][1][1]]], "cross")
        else:
            hit = curveops.hit_by_polygon(e, [[p[0], p[1]] for p in area["pts"]], "cross")
        if hit:
            rows.append((e.handle, region))
    n = 0
    for h, reg in rows:
        e = ctx.d.get(h)
        if e is None or ctx.locked(e):
            continue
        c = e.copy_as_new()
        if stretch_entity(c, reg, vec) and c.valid():
            grips._assign(ctx.d.modify(h), c)
            n += 1
    return {"stretched": n}


def _align_fn(s1, d1, s2, d2, scale_flag):
    shift = [d1[0] - s1[0], d1[1] - s1[1], 0.0]
    ang = 0.0
    k = 1.0
    if s2 is not None and d2 is not None:
        vs = [s2[0] - s1[0], s2[1] - s1[1]]
        vd = [d2[0] - d1[0], d2[1] - d1[1]]
        ls, ld = math.hypot(*vs), math.hypot(*vd)
        if ls > geom.EPS and ld > geom.EPS:
            ang = math.atan2(vd[1], vd[0]) - math.atan2(vs[1], vs[0])
            if scale_flag:
                k = ld / ls
    rot = grips.Xf("rotate", d1, ang)
    sc = grips.Xf("scale", d1, 0.0, k)

    def fn(c):
        c.move_by(shift)
        if abs(ang) > 0.0:
            grips.transform(c, rot)
        if abs(k - 1.0) > 0.0:
            grips.transform(c, sc)

    return fn


@command("align", aliases=("al",), group="modify", label="Align", description="Align objects by one to three source and destination point pairs, optional scale.", menu="Modify > 3D Operations > Align")
def align(ctx):
    s = yield ctx.select("Select objects")
    if s.kind != "selection" or not s.value:
        return
    handles = list(s.value)
    s1 = yield ctx.point("Specify first source point")
    if s1.kind != "point":
        return
    d1 = yield ctx.point("Specify first destination point", base=s1.value, jig=lambda q: _preview(ctx, handles, _align_fn(s1.value, q, None, None, False)) + [jig.line(s1.value, q)])
    if d1.kind != "point":
        return
    s2 = yield ctx.point("Specify second source point or", default_text="continue", jig=lambda q: [jig.line(s1.value, q)])
    if s2.kind != "point":
        _commit(ctx, handles, _align_fn(s1.value, d1.value, None, None, False), False)
        return
    d2 = yield ctx.point("Specify second destination point", base=d1.value, jig=lambda q: _preview(ctx, handles, _align_fn(s1.value, d1.value, s2.value, q, False)) + [jig.line(d1.value, q)])
    if d2.kind != "point":
        return
    s3 = yield ctx.point("Specify third source point or", default_text="continue")
    if s3.kind == "point":
        d3 = yield ctx.point("Specify third destination point")
        if d3.kind != "point":
            return
        ctx.say("The third pair has no effect in the XY plane.")
    sc = yield ctx.yesno("Scale objects based on alignment points?", "No")
    if sc.kind not in ("keyword", "enter"):
        return
    flag = sc.kind == "keyword" and sc.value == "Yes"
    _commit(ctx, handles, _align_fn(s1.value, d1.value, s2.value, d2.value, flag), False)


@executes("align")
def align_exec(ctx, args):
    handles = targets(ctx, args)
    s1, d1 = geom.as_pt(args["s1"]), geom.as_pt(args["d1"])
    s2 = geom.as_pt(args["s2"]) if args.get("s2") is not None else None
    d2 = geom.as_pt(args["d2"]) if args.get("d2") is not None else None
    if (s2 is None) != (d2 is None):
        raise CommandError("Give both s2 and d2.")
    made = _commit(ctx, handles, _align_fn(s1, d1, s2, d2, bool(args.get("scale"))), False)
    return {"aligned": len(made)}


def reverse_entity(e) -> bool:
    k = e.kind
    if k == "line":
        e.start, e.end = e.end, e.start
        return True
    if isinstance(e, LwPolyline):
        n = len(e.vertices)
        old = e.vertices
        new = []
        for k2 in range(n):
            src = old[n - 1 - k2]
            seg = (n - 2 - k2) % n
            has = (n - 2 - k2) >= 0 or e.closed
            new.append({"p": list(src["p"]), "bulge": -old[seg].get("bulge", 0.0) if has else 0.0, "sw": old[seg].get("ew", 0.0) if has else 0.0, "ew": old[seg].get("sw", 0.0) if has else 0.0})
        e.vertices = new
        return True
    if isinstance(e, Polyline3d):
        e.points = list(reversed(e.points))
        return True
    if isinstance(e, Spline):
        if e.knots:
            lo, hi = e.knots[e.degree], e.knots[len(e.control_points)]
            e.knots = [lo + hi - x for x in reversed(e.knots)]
        e.control_points = list(reversed(e.control_points))
        e.weights = list(reversed(e.weights)) if e.weights else []
        e.fit_points = list(reversed(e.fit_points)) if e.fit_points else []
        st, en = e.start_tangent, e.end_tangent
        e.start_tangent = [-x for x in en] if en else None
        e.end_tangent = [-x for x in st] if st else None
        return True
    return False


def _reverse_apply(ctx, handles) -> int:
    n = 0
    for e in ctx.editable(handles):
        c = e.copy_as_new()
        if reverse_entity(c):
            grips._assign(ctx.d.modify(e.handle), c)
            n += 1
    return n


@command("reverse", group="modify", label="Reverse", description="Reverse direction of lines, polylines and splines.", menu="")
def reverse(ctx):
    s = yield ctx.select("Select objects")
    if s.kind != "selection" or not s.value:
        return
    n = _reverse_apply(ctx, s.value)
    ctx.say("%d object(s) direction has been reversed." % n)


@executes("reverse")
def reverse_exec(ctx, args):
    n = _reverse_apply(ctx, targets(ctx, args))
    ctx.say("%d object(s) direction has been reversed." % n)
    return {"reversed": n}
