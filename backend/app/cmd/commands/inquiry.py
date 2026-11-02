import math

from app.cmd import units
from app.cmd.context import CommandError
from app.cmd.draw_support import pick_entity, pick_point
from app.cmd.prompts import Prompt
from app.cmd.registry import command, executes
from app.doc import geom
from app.doc import measure as M

def _num(ctx, v: float) -> str:
    return units.format_distance(v, 2, ctx.luprec())


def _store(ctx, name, value) -> None:
    try:
        ctx.setvar(name, float(value))
    except Exception:
        return None


def _vert(p, bulge=0.0):
    return {"p": [float(p[0]), float(p[1])], "bulge": bulge}


def _tail_tangent(verts):
    if len(verts) < 2:
        return 0.0
    a, b = verts[-2], verts[-1]
    bulge = a.get("bulge", 0.0) or 0.0
    chord = geom.angle_of(a["p"], b["p"])
    if abs(bulge) < 1e-12:
        return chord
    theta = 4.0 * math.atan(bulge)
    return chord + theta / 2.0


def _arc_bulge(prev_tangent, p0, p1):
    phi = geom.angle_of(p0, p1)
    d = (phi - prev_tangent + math.pi) % math.tau - math.pi
    if abs(abs(d) - math.pi) < 1e-9:
        return None
    return math.tan(d / 2.0)


def _walk(ctx, first, base_msg="Specify next point"):
    verts = [_vert(first)]
    arc_mode = False
    while True:
        n = len(verts)
        opts = ["Arc", "Length", "Undo", "Total"] if not arc_mode else ["Line", "Undo", "Total"]
        default = "Total" if n >= 3 else None
        msg = base_msg if not arc_mode else "Specify endpoint of arc"
        r = yield ctx.point(msg, opts, default=default, base=verts[-1]["p"], default_text="Total" if default else "")
        if r.kind == "enter" or (r.kind == "keyword" and r.value == "Total"):
            return verts, True
        if r.kind == "keyword":
            if r.value == "Arc":
                arc_mode = True
            elif r.value == "Line":
                arc_mode = False
            elif r.value == "Undo":
                if len(verts) > 1:
                    verts.pop()
                    if verts:
                        verts[-1]["bulge"] = 0.0
                else:
                    ctx.say("Nothing to undo.")
            elif r.value == "Length":
                ln = yield ctx.distance("Specify length of line", positive=True)
                if ln.kind == "number":
                    ang = _tail_tangent(verts) if n >= 2 else 0.0
                    p = geom.polar(verts[-1]["p"], ln.value, ang)
                    verts.append(_vert(p))
            continue
        if r.kind != "point":
            return verts, False
        p = r.value
        if arc_mode:
            tangent = _tail_tangent(verts) if n >= 2 else 0.0
            b = _arc_bulge(tangent, verts[-1]["p"], p)
            if b is None:
                ctx.say("Invalid arc endpoint.")
                continue
            verts[-1]["bulge"] = b
        verts.append(_vert(p))


def _poly_result(verts, closed=True):
    return M.polygon_measure(verts, closed)


def _report_area(ctx, area, perim) -> None:
    ctx.say("Area = %s, Perimeter = %s" % (_num(ctx, area), ctx.fd(perim)))
    _store(ctx, "AREA", area)
    _store(ctx, "PERIMETER", perim)


def _height(ctx, last):
    r = yield ctx.distance("Specify height", default=last)
    return r.value if r.kind == "number" else None


def area_flow(ctx, volume=False):
    total = 0.0
    mode = None
    height = ctx.mem.get("volume_height")
    while True:
        opts = ["Object", "Add area", "Subtract area"] if mode is None else ["Object", "Subtract area" if mode == "add" else "Add area"]
        msg = "Specify first corner point" if mode is None else "Specify first corner point (%s mode)" % ("ADD" if mode == "add" else "SUBTRACT")
        r = yield ctx.point(msg, opts, default="Object" if mode is None else None, default_text="Object" if mode is None else "")
        measures = []
        if r.kind == "keyword" and r.value == "Add area":
            mode = "add"
            continue
        if r.kind == "keyword" and r.value == "Subtract area":
            mode = "sub"
            continue
        if r.kind == "keyword" and r.value == "Object":
            s = yield ctx.select("Select objects", pick_one=(mode is None))
            if s.kind != "selection" or not s.value:
                if mode is None:
                    return
                continue
            for h in s.value:
                e = ctx.d.get(h)
                if e is None:
                    continue
                try:
                    measures.append(M.entity_measure(e))
                except M.NoArea:
                    ctx.say("The selected object has no area.")
            if not measures:
                if mode is None:
                    return
                continue
        elif r.kind == "point":
            verts, closed = yield from _walk(ctx, r.value)
            if len(verts) < 3:
                ctx.say("The polygon needs at least three points.")
                if mode is None:
                    return
                continue
            measures.append(_poly_result(verts, True))
        else:
            break
        for area, perim in measures:
            _report_area(ctx, area, perim)
            val = area
            if volume:
                h = yield from _height(ctx, height)
                if h is None:
                    return
                height = h
                ctx.mem["volume_height"] = h
                val = area * h
                ctx.say("Volume = %s" % _num(ctx, val))
                _store(ctx, "VOLUME", val)
            if mode is not None:
                total += val if mode == "add" else -val
                ctx.say("Total %s = %s" % ("volume" if volume else "area", _num(ctx, total)))
        if mode is None:
            return


def _report_distance(ctx, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    dz = (b[2] if len(b) > 2 else 0.0) - (a[2] if len(a) > 2 else 0.0)
    dist = math.sqrt(dx * dx + dy * dy + dz * dz)
    ang = math.atan2(dy, dx)
    ctx.say("Distance = %s,  Angle in XY Plane = %s,  Angle from XY Plane = %s" % (ctx.fd(dist), ctx.fa(ang), ctx.fa(math.atan2(dz, math.hypot(dx, dy)))))
    ctx.say("Delta X = %s,  Delta Y = %s,  Delta Z = %s" % (ctx.fd(dx), ctx.fd(dy), ctx.fd(dz)))
    _store(ctx, "DISTANCE", dist)
    ctx.set_last(b)
    return dist


def distance_flow(ctx):
    a = yield ctx.point("Specify first point")
    if a.kind != "point":
        return
    b = yield ctx.point("Specify second point", ["Multiple points"], base=a.value)
    if b.kind == "point":
        _report_distance(ctx, a.value, b.value)
        return
    if b.kind != "keyword":
        return
    verts, closed = yield from _walk(ctx, a.value)
    if len(verts) < 2:
        return
    length = M.polygon_measure(verts, False)[1]
    ctx.say("Distance = %s" % ctx.fd(length))
    _store(ctx, "DISTANCE", length)
    ctx.set_last(verts[-1]["p"])


def _radius_of(ctx, e, point):
    if e.kind in ("arc", "circle"):
        return e.radius
    if e.kind == "lwpolyline":
        found = M.poly_arc_at(e, point or e.vertices[0]["p"])
        if found and found[0]:
            return found[0][1]
    return None


def _report_radius(ctx, r) -> None:
    ctx.say("Radius = %s" % ctx.fd(r))
    ctx.say("Diameter = %s" % ctx.fd(2.0 * r))


def radius_flow(ctx):
    while True:
        r = yield ctx.entity("Select arc or circle")
        if r.kind != "entity":
            return
        e = pick_entity(ctx, r.value)
        rad = _radius_of(ctx, e, pick_point(r.value)) if e is not None else None
        if rad is None:
            ctx.say("Select an arc, circle or polyline arc.")
            continue
        _report_radius(ctx, rad)
        return


def _say_angle(ctx, a) -> None:
    ctx.say("Angle = %s" % ctx.fa(a))


def _between_dirs(c, p, q):
    a1, a2 = geom.angle_of(c, p), geom.angle_of(c, q)
    d = abs((a2 - a1 + math.pi) % math.tau - math.pi)
    return d


def angle_flow(ctx):
    while True:
        r = yield Prompt("Select arc, circle, line or <specify vertex>", ("entity",), [])
        if r.kind == "enter":
            v = yield ctx.point("Specify angle vertex")
            if v.kind != "point":
                return
            p1 = yield ctx.point("Specify first angle endpoint", base=v.value)
            if p1.kind != "point":
                return
            p2 = yield ctx.point("Specify second angle endpoint", base=v.value)
            if p2.kind != "point":
                return
            if geom.same_point(v.value, p1.value) or geom.same_point(v.value, p2.value):
                ctx.say("The vertex and the endpoints must differ.")
                return
            _say_angle(ctx, _between_dirs(v.value, p1.value, p2.value))
            return
        if r.kind != "entity":
            return
        e = pick_entity(ctx, r.value)
        pt = pick_point(r.value)
        if e is None:
            continue
        if e.kind == "arc":
            _say_angle(ctx, geom.ccw_sweep(e.start_angle, e.end_angle))
            return
        if e.kind == "circle":
            q = yield ctx.point("Specify second angle endpoint", base=e.center)
            if q.kind != "point":
                return
            _say_angle(ctx, _between_dirs(e.center, pt, q.value))
            return
        if e.kind == "lwpolyline":
            found = M.poly_arc_at(e, pt)
            if found and found[0]:
                _say_angle(ctx, abs(4.0 * math.atan(found[1])))
                return
        a0, a1 = M.line_dir(e, pt)
        if a0 is None:
            ctx.say("Select an arc, circle, line or polyline segment.")
            continue
        while True:
            s = yield ctx.entity("Select second line")
            if s.kind != "entity":
                return
            e2 = pick_entity(ctx, s.value)
            b0, b1 = M.line_dir(e2, pick_point(s.value)) if e2 is not None else (None, None)
            if b0 is None:
                ctx.say("Select a line or polyline segment.")
                continue
            ang = M.angle_between_lines(a0, a1, b0, b1)
            if ang is None:
                ctx.say("The lines are parallel.")
                return
            _say_angle(ctx, ang)
            return


def _quick_report(ctx, e, pt) -> dict:
    out = {"handle": e.handle, "kind": e.kind}
    k = e.kind
    if k == "line":
        out.update(length=geom.dist(e.start, e.end), angle=geom.angle_of(e.start, e.end))
        ctx.say("Length = %s,  Angle = %s" % (ctx.fd(out["length"]), ctx.fa(out["angle"])))
    elif k == "circle":
        out.update(radius=e.radius, diameter=2 * e.radius, circumference=2 * math.pi * e.radius, area=math.pi * e.radius**2)
        ctx.say("Radius = %s,  Diameter = %s,  Circumference = %s,  Area = %s" % (ctx.fd(e.radius), ctx.fd(2 * e.radius), ctx.fd(out["circumference"]), _num(ctx, out["area"])))
    elif k == "arc":
        sweep = geom.ccw_sweep(e.start_angle, e.end_angle)
        out.update(radius=e.radius, angle=sweep, length=e.radius * sweep)
        ctx.say("Radius = %s,  Angle = %s,  Length = %s" % (ctx.fd(e.radius), ctx.fa(sweep), ctx.fd(out["length"])))
    else:
        try:
            area, perim = M.entity_measure(e)
        except M.NoArea:
            raise CommandError("Nothing measurable found there.")
        out.update(area=area, perimeter=perim)
        _report_area(ctx, area, perim)
    return out


def quick_target(ctx, pt):
    aperture = float(ctx.doc.view.get("height", 100.0)) * 0.02
    best, bd = None, None
    from app.cmd import snaps

    for e in ctx.visible_entities():
        box = e.bounds()
        if box is None:
            continue
        if not (box[0] - aperture <= pt[0] <= box[2] + aperture and box[1] - aperture <= pt[1] <= box[3] + aperture):
            continue
        try:
            near = snaps.search([e], "nea", pt, aperture, e)
        except Exception:
            near = None
        if near is None:
            continue
        d = geom.dist(near[0], pt)
        if bd is None or d < bd:
            best, bd = e, d
    return best


def quick_flow(ctx):
    r = yield ctx.point("Move the cursor over an object or click to measure")
    if r.kind != "point":
        return
    e = quick_target(ctx, r.value)
    if e is None:
        ctx.say("Nothing measurable found there.")
        return
    _quick_report(ctx, e, r.value)


@command("measuregeom", group="inquiry", label="Measure Geometry", description="Measure distance, radius, angle, area, volume or quick.", menu="Tools > Inquiry", undoable=False, repeatable=False)
def measuregeom(ctx):
    last = ctx.mem.get("measure_option", "Distance")
    r = yield ctx.keyword("Enter an option", ["Distance", "Radius", "Angle", "ARea", "Volume", "Quick"], last)
    if r.kind != "keyword":
        return
    ctx.mem["measure_option"] = r.value
    if r.value == "Distance":
        yield from distance_flow(ctx)
    elif r.value == "Radius":
        yield from radius_flow(ctx)
    elif r.value == "Angle":
        yield from angle_flow(ctx)
    elif r.value == "ARea":
        yield from area_flow(ctx, False)
    elif r.value == "Volume":
        yield from area_flow(ctx, True)
    else:
        yield from quick_flow(ctx)


@command("radius.measure", aliases=("radius",), group="inquiry", label="Radius", description="Report the radius and diameter of an arc or circle.", menu="Tools > Inquiry > Radius", undoable=False, repeatable=False)
def radius_cmd(ctx):
    yield from radius_flow(ctx)


@command("angle.measure", aliases=("angle",), group="inquiry", label="Angle", description="Report an angle from an arc, circle, lines or vertex.", menu="Tools > Inquiry > Angle", undoable=False, repeatable=False)
def angle_cmd(ctx):
    yield from angle_flow(ctx)


@command("volume.measure", aliases=("volume",), group="inquiry", label="Volume", description="Volume of a closed 2D shape extruded by a height.", menu="Tools > Inquiry > Volume", undoable=False, repeatable=False)
def volume_cmd(ctx):
    yield from area_flow(ctx, True)


def _points(args, key="points"):
    pts = args.get(key)
    if not isinstance(pts, (list, tuple)):
        raise CommandError("Points are required.")
    return [geom.as_pt(p) for p in pts]


def _entity(ctx, h):
    e = ctx.d.get(int(h)) if h is not None else None
    if e is None:
        raise CommandError("No such object.")
    return e


def distance_exec(ctx, args):
    pts = _points(args)
    if len(pts) < 2:
        raise CommandError("Two points are required.")
    verts = [_vert(p) for p in pts]
    length = M.polygon_measure(verts, False)[1]
    a, b = pts[0], pts[-1]
    dx, dy = b[0] - a[0], b[1] - a[1]
    _store(ctx, "DISTANCE", length if len(pts) > 2 else math.hypot(dx, dy))
    out = {"distance": length, "angle": math.degrees(math.atan2(dy, dx)) % 360.0, "delta": [dx, dy, 0.0], "straight": math.hypot(dx, dy)}
    ctx.say("Distance = %s" % ctx.fd(length))
    return out


def radius_exec(ctx, args):
    e = _entity(ctx, args.get("handle"))
    pt = geom.as_pt(args["point"]) if args.get("point") is not None else None
    r = _radius_of(ctx, e, pt)
    if r is None:
        raise CommandError("Select an arc, circle or polyline arc.")
    _report_radius(ctx, r)
    return {"radius": r, "diameter": 2.0 * r}


def angle_exec(ctx, args):
    if args.get("vertex") is not None:
        v, p1, p2 = geom.as_pt(args["vertex"]), geom.as_pt(args["p1"]), geom.as_pt(args["p2"])
        if geom.same_point(v, p1) or geom.same_point(v, p2):
            raise CommandError("The vertex and the endpoints must differ.")
        a = _between_dirs(v, p1, p2)
    else:
        e = _entity(ctx, args.get("handle"))
        pt = geom.as_pt(args["point"]) if args.get("point") is not None else None
        if e.kind == "arc":
            a = geom.ccw_sweep(e.start_angle, e.end_angle)
        elif e.kind == "circle":
            if args.get("point") is None or args.get("point2") is None:
                raise CommandError("Two points on the circle are required.")
            a = _between_dirs(e.center, geom.as_pt(args["point"]), geom.as_pt(args["point2"]))
        elif e.kind == "lwpolyline" and pt is not None and (M.poly_arc_at(e, pt) or (None,))[0]:
            a = abs(4.0 * math.atan(M.poly_arc_at(e, pt)[1]))
        else:
            a0, a1 = M.line_dir(e, pt)
            if a0 is None:
                raise CommandError("Select an arc, circle, line or polyline segment.")
            e2 = _entity(ctx, args.get("handle2"))
            pt2 = geom.as_pt(args["point2"]) if args.get("point2") is not None else None
            b0, b1 = M.line_dir(e2, pt2)
            if b0 is None:
                raise CommandError("Select a line or polyline segment.")
            a = M.angle_between_lines(a0, a1, b0, b1)
            if a is None:
                raise CommandError("The lines are parallel.")
    _say_angle(ctx, a)
    return {"angle": math.degrees(a), "radians": a}


def area_exec(ctx, args):
    height = args.get("height")
    out = {"items": []}
    total = 0.0

    def one(area, perim, sign):
        nonlocal total
        row = {"area": area, "perimeter": perim}
        val = area
        if height is not None:
            val = area * float(height)
            row["volume"] = val
        total += sign * val
        out["items"].append(row)
        _report_area(ctx, area, perim)

    groups = [(args.get("add"), 1.0), (args.get("subtract"), -1.0)]
    if args.get("points") is not None:
        verts = [_vert(p) for p in _points(args)]
        if len(verts) < 3:
            raise CommandError("The polygon needs at least three points.")
        one(*M.polygon_measure(verts, True), 1.0)
    handles = args.get("handles", [args["handle"]] if args.get("handle") is not None else [])
    for h in handles:
        try:
            one(*M.entity_measure(_entity(ctx, h)), 1.0)
        except M.NoArea:
            raise CommandError("The selected object has no area.")
    for items, sign in groups:
        for it in items or []:
            if isinstance(it, dict) and "points" in it:
                one(*M.polygon_measure([_vert(p) for p in it["points"]], True), sign)
            else:
                try:
                    one(*M.entity_measure(_entity(ctx, it["handle"] if isinstance(it, dict) else it)), sign)
                except M.NoArea:
                    raise CommandError("The selected object has no area.")
    if not out["items"]:
        raise CommandError("Give points, a handle or add and subtract lists.")
    out["total"] = total
    out["area"] = out["items"][0]["area"] if len(out["items"]) == 1 else total
    out["perimeter"] = out["items"][0]["perimeter"]
    if height is not None:
        out["height"] = float(height)
        out["volume"] = total
        _store(ctx, "VOLUME", total)
    return out


@executes("measuregeom")
def measuregeom_exec(ctx, args):
    mode = str(args.get("mode", "distance")).lower()
    if mode == "distance":
        return distance_exec(ctx, args)
    if mode == "radius":
        return radius_exec(ctx, args)
    if mode == "angle":
        return angle_exec(ctx, args)
    if mode == "area":
        return area_exec(ctx, {k: v for k, v in args.items() if k != "height"})
    if mode == "volume":
        if args.get("height") is None:
            raise CommandError("A height is required.")
        return area_exec(ctx, args)
    if mode == "quick":
        pt = geom.as_pt(args["point"])
        e = quick_target(ctx, pt)
        if e is None:
            raise CommandError("Nothing measurable found there.")
        return _quick_report(ctx, e, pt)
    raise CommandError("Mode must be distance, radius, angle, area, volume or quick.")


@executes("radius.measure")
def radius_measure_exec(ctx, args):
    return radius_exec(ctx, args)


@executes("angle.measure")
def angle_measure_exec(ctx, args):
    return angle_exec(ctx, args)


@executes("volume.measure")
def volume_measure_exec(ctx, args):
    if args.get("height") is None:
        raise CommandError("A height is required.")
    return area_exec(ctx, args)
