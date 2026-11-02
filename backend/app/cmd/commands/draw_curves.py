import itertools
import math

from app.cmd import jig, snaps
from app.cmd.commands.draw import (
    _arc_from_start_end_tangent,
    _arc_sca,
    _arc_scl,
    _arc_sce,
    _arc_sea,
    _arc_ser,
    _finish_circle,
    _make_arc,
    _pt,
    anum,
    dnum,
    flow_arc_continue,
    flow_center_end,
    flow_circle_2p,
    flow_circle_3p,
    flow_circle_radius,
    step_chord,
    step_direction,
    step_end_angle,
    step_included,
    step_radius,
)
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.doc import geom
from app.doc.entities import Arc, Ellipse, Line, LwPolyline, Ray, XLine

UNIT_MIN = 1e-12


def _unit(v):
    n = math.hypot(v[0], v[1])
    if n < UNIT_MIN:
        return None
    return [v[0] / n, v[1] / n]


def _dir3(u):
    return [u[0], u[1], 0.0]


def _inf(kind, base, u):
    return {"type": kind, "p": [float(base[0]), float(base[1])], "dir": [float(u[0]), float(u[1])]}


def _through_dir(base, p):
    return _unit([p[0] - base[0], p[1] - base[1]])


def _add_xline(ctx, base, u):
    return ctx.add(XLine(base=[base[0], base[1], 0.0], direction=_dir3(u)))


def _seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    n2 = dx * dx + dy * dy
    if n2 < UNIT_MIN:
        return geom.dist(p, a)
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / n2))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def _line_of(ent, pick):
    if isinstance(ent, Line):
        u = _unit([ent.end[0] - ent.start[0], ent.end[1] - ent.start[1]])
        return (list(ent.start), u) if u else None
    if isinstance(ent, (XLine, Ray)):
        u = _unit(ent.direction)
        return (list(ent.base), u) if u else None
    if isinstance(ent, LwPolyline):
        best = None
        for p0, p1, bulge in ent.segments():
            d = _seg_dist(pick, p0, p1)
            if best is None or d < best[0]:
                best = (d, p0, p1, bulge)
        if best is None or abs(best[3]) > geom.TINY_BULGE:
            return None
        u = _unit([best[2][0] - best[1][0], best[2][1] - best[1][1]])
        return (list(best[1]), u) if u else None
    return None


LINE_MESSAGE = "Select a line, ray, construction line or straight polyline segment."


def _pick_line(ctx, msg):
    while True:
        r = yield ctx.entity(msg)
        if r.kind != "entity":
            return None
        ent = ctx.d.get(r.value["handle"])
        found = _line_of(ent, r.value["point"]) if ent is not None else None
        if found is None:
            ctx.say(LINE_MESSAGE)
            continue
        return found, r.value["point"]


def _bisector(v, a, b):
    u1 = _through_dir(v, a)
    u2 = _through_dir(v, b)
    if u1 is None or u2 is None:
        return None
    s = [u1[0] + u2[0], u1[1] + u2[1]]
    if math.hypot(s[0], s[1]) < 1e-9:
        return [-u1[1], u1[0]]
    return _unit(s)


def _through_loop(ctx, base):
    while True:
        def preview(p):
            u = _through_dir(base, p)
            return [_inf("xline", base, u)] if u else jig.rubber(base, p)

        t = yield ctx.point("Specify through point", base=base, jig=preview)
        if t.kind != "point":
            return
        u = _through_dir(base, t.value)
        if u is None:
            continue
        _add_xline(ctx, base, u)


@command("xline", aliases=("xl",), group="draw", label="Construction Line", description="Infinite construction lines: Hor, Ver, Ang, Bisect, Offset.", menu="Draw > Construction Line")
def xline(ctx):
    r = yield ctx.point("Specify a point", ["Hor", "Ver", "Ang", "Bisect", "Offset"])
    if r.kind == "point":
        yield from _through_loop(ctx, r.value)
        return
    if r.kind != "keyword":
        return
    k = r.value
    if k in ("Hor", "Ver"):
        u = [1.0, 0.0] if k == "Hor" else [0.0, 1.0]
        while True:
            t = yield ctx.point("Specify through point", jig=lambda p: [_inf("xline", p, u)])
            if t.kind != "point":
                return
            _add_xline(ctx, t.value, u)
    elif k == "Ang":
        yield from _xline_angle(ctx)
    elif k == "Bisect":
        yield from _xline_bisect(ctx)
    else:
        yield from _xline_offset(ctx)


def _xline_angle(ctx):
    ang = None
    while ang is None:
        ask = ctx.angle("Enter angle of xline (0)", ["Reference"], default=0.0)
        ask.default_text = ""
        a = yield ask
        if a.kind == "number":
            ang = a.value
        elif a.kind == "keyword":
            got = yield from _pick_line(ctx, "Select a line object")
            if got is None:
                return
            (_p, u), _pk = got
            ref = math.atan2(u[1], u[0])
            rel = yield ctx.angle("Enter angle of xline relative to reference", default=0.0, absolute=False)
            if rel.kind != "number":
                return
            ang = ref + rel.value
        else:
            return
    yield from _fixed_loop(ctx, [math.cos(ang), math.sin(ang)])


def _fixed_loop(ctx, u):
    while True:
        t = yield ctx.point("Specify through point", jig=lambda p: [_inf("xline", p, u)])
        if t.kind != "point":
            return
        _add_xline(ctx, t.value, u)


def _xline_bisect(ctx):
    v = yield ctx.point("Specify angle vertex point")
    if v.kind != "point":
        return
    a = yield ctx.point("Specify angle start point", base=v.value, jig=lambda p: jig.rubber(v.value, p))
    if a.kind != "point":
        return
    while True:
        def preview(p):
            u = _bisector(v.value, a.value, p)
            return [_inf("xline", v.value, u)] + jig.rubber(v.value, p) if u else jig.rubber(v.value, p)

        b = yield ctx.point("Specify angle end point", base=v.value, jig=preview)
        if b.kind != "point":
            return
        u = _bisector(v.value, a.value, b.value)
        if u is None:
            ctx.say("Value must be positive and nonzero.")
            continue
        _add_xline(ctx, v.value, u)


def _xline_offset(ctx):
    last = float(ctx.d.header.get("OFFSETDIST", -1.0))
    ask = ctx.distance("Specify offset distance", ["Through"], default=last if last >= 0 else "Through", nonneg=True)
    ask.default_text = ctx.fd(last) if last >= 0 else "Through"
    d = yield ask
    through = False
    dist = 0.0
    if d.kind == "keyword":
        through = True
    elif d.kind == "number":
        dist = d.value
    elif d.kind == "point":
        p2 = yield ctx.point("Specify second point", base=d.value, jig=lambda p: jig.rubber(d.value, p))
        if p2.kind != "point":
            return
        dist = geom.dist(d.value, p2.value)
    else:
        return
    if dist < 0:
        ctx.say("Requires a positive number.")
        return
    if through:
        ctx.d.set_header("OFFSETDIST", -1.0)
    else:
        ctx.d.set_header("OFFSETDIST", float(dist))
    while True:
        got = yield from _pick_line(ctx, "Select a line object")
        if got is None:
            return
        (p, u), pick = got
        n = [-u[1], u[0]]
        if through:
            def preview(q, p=p, u=u):
                return [_inf("xline", q, u)]

            t = yield ctx.point("Specify through point", base=pick, jig=preview)
            if t.kind != "point":
                return
            _add_xline(ctx, t.value, u)
        else:
            def preview2(q, p=p, u=u, n=n):
                side = 1.0 if (q[0] - p[0]) * n[0] + (q[1] - p[1]) * n[1] >= 0 else -1.0
                return [_inf("xline", [p[0] + side * dist * n[0], p[1] + side * dist * n[1]], u)]

            t = yield ctx.point("Specify side to offset", base=pick, jig=preview2)
            if t.kind != "point":
                return
            side = 1.0 if (t.value[0] - p[0]) * n[0] + (t.value[1] - p[1]) * n[1] >= 0 else -1.0
            _add_xline(ctx, [p[0] + side * dist * n[0], p[1] + side * dist * n[1]], u)


@executes("xline")
def xline_exec(ctx, args):
    made = []
    if "vertex" in args:
        v = _pt(args["vertex"])
        a = _pt(args["start"])
        for b in args.get("ends") or [args.get("end")]:
            u = _bisector(v, a, _pt(b))
            if u is None:
                raise CommandError("Value must be positive and nonzero.")
            made.append(_add_xline(ctx, v, u))
        return {"handles": made}
    if "handle" in args:
        ent = ctx.d.get(int(args["handle"]))
        pick = _pt(args.get("pick") or [0.0, 0.0])
        found = _line_of(ent, pick) if ent is not None else None
        if found is None:
            raise CommandError(LINE_MESSAGE)
        p, u = found
        if args.get("through") is not None:
            return {"handles": [_add_xline(ctx, _pt(args["through"]), u)]}
        dist = float(args.get("distance", 0.0))
        if dist < 0:
            raise CommandError("Requires a positive number.")
        n = [-u[1], u[0]]
        side = _pt(args.get("side") or [p[0] + n[0], p[1] + n[1]])
        sg = 1.0 if (side[0] - p[0]) * n[0] + (side[1] - p[1]) * n[1] >= 0 else -1.0
        return {"handles": [_add_xline(ctx, [p[0] + sg * dist * n[0], p[1] + sg * dist * n[1]], u)]}
    base = _pt(args["base"])
    if args.get("hor") or args.get("ver"):
        u = [1.0, 0.0] if args.get("hor") else [0.0, 1.0]
        return {"handles": [_add_xline(ctx, base, u)]}
    if "angle" in args:
        a = math.radians(float(args["angle"]))
        return {"handles": [_add_xline(ctx, base, [math.cos(a), math.sin(a)])]}
    throughs = args.get("throughs") or ([args["through"]] if "through" in args else [])
    for t in throughs:
        u = _through_dir(base, _pt(t))
        if u is None:
            raise CommandError("Through point must differ from the base point.")
        made.append(_add_xline(ctx, base, u))
    if not made:
        raise CommandError("Give a through point, angle, hor or ver.")
    return {"handles": made}


@command("ray", group="draw", label="Ray", description="Semi-infinite ray from a start point through points.", menu="Draw > Ray")
def ray(ctx):
    r = yield ctx.point("Specify start point")
    if r.kind != "point":
        return
    base = r.value
    while True:
        def preview(p):
            u = _through_dir(base, p)
            return [_inf("ray", base, u)] if u else jig.rubber(base, p)

        t = yield ctx.point("Specify through point", base=base, jig=preview)
        if t.kind != "point":
            return
        u = _through_dir(base, t.value)
        if u is None:
            continue
        ctx.add(Ray(base=[base[0], base[1], 0.0], direction=_dir3(u)))


@executes("ray")
def ray_exec(ctx, args):
    base = _pt(args["base"])
    throughs = args.get("throughs") or ([args["through"]] if "through" in args else [])
    made = []
    for t in throughs:
        u = _through_dir(base, _pt(t))
        if u is None:
            raise CommandError("Through point must differ from the base point.")
        made.append(ctx.add(Ray(base=[base[0], base[1], 0.0], direction=_dir3(u))))
    if not made:
        raise CommandError("Give a through point.")
    return {"handles": made}


def _ask_points(ctx, steps):
    got = []
    for msg, rel in steps:
        base = got[rel] if rel is not None else None
        fn = None
        if base is not None:
            fn = (lambda p, b=base: jig.rubber(b, p))
        r = yield ctx.point(msg, base=base, jig=fn)
        if r.kind != "point":
            return None
        got.append(r.value)
    return got


@command("arc.sce", group="draw", label="Start, Center, End", description="Arc from start, centre, end.", menu="Draw > Arc > Start, Center, End")
def arc_sce(ctx):
    pts = yield from _ask_points(ctx, [("Specify start point of arc", None), ("Specify center point of arc", 0)])
    if pts:
        yield from flow_center_end(ctx, pts[0], pts[1], switches=False)


@command("arc.sca", group="draw", label="Start, Center, Angle", description="Arc from start, centre, included angle.", menu="Draw > Arc > Start, Center, Angle")
def arc_sca(ctx):
    pts = yield from _ask_points(ctx, [("Specify start point of arc", None), ("Specify center point of arc", 0)])
    if pts:
        yield from step_included(ctx, pts[1], pts[0])


@command("arc.scl", group="draw", label="Start, Center, Length", description="Arc from start, centre, chord length.", menu="Draw > Arc > Start, Center, Length")
def arc_scl(ctx):
    pts = yield from _ask_points(ctx, [("Specify start point of arc", None), ("Specify center point of arc", 0)])
    if pts:
        yield from step_chord(ctx, pts[1], pts[0])


@command("arc.sea", group="draw", label="Start, End, Angle", description="Arc from start, end, included angle.", menu="Draw > Arc > Start, End, Angle")
def arc_sea(ctx):
    pts = yield from _ask_points(ctx, [("Specify start point of arc", None), ("Specify end point of arc", 0)])
    if pts:
        yield from step_end_angle(ctx, pts[0], pts[1])


@command("arc.sed", group="draw", label="Start, End, Direction", description="Arc from start, end, tangent direction at start.", menu="Draw > Arc > Start, End, Direction")
def arc_sed(ctx):
    pts = yield from _ask_points(ctx, [("Specify start point of arc", None), ("Specify end point of arc", 0)])
    if pts:
        yield from step_direction(ctx, pts[0], pts[1])


@command("arc.ser", group="draw", label="Start, End, Radius", description="Arc from start, end, radius.", menu="Draw > Arc > Start, End, Radius")
def arc_ser(ctx):
    pts = yield from _ask_points(ctx, [("Specify start point of arc", None), ("Specify end point of arc", 0)])
    if pts:
        yield from step_radius(ctx, pts[0], pts[1])


@command("arc.cse", group="draw", label="Center, Start, End", description="Arc from centre, start, end.", menu="Draw > Arc > Center, Start, End")
def arc_cse(ctx):
    pts = yield from _ask_points(ctx, [("Specify center point of arc", None), ("Specify start point of arc", 0)])
    if pts:
        yield from flow_center_end(ctx, pts[1], pts[0], switches=False)


@command("arc.csa", group="draw", label="Center, Start, Angle", description="Arc from centre, start, included angle.", menu="Draw > Arc > Center, Start, Angle")
def arc_csa(ctx):
    pts = yield from _ask_points(ctx, [("Specify center point of arc", None), ("Specify start point of arc", 0)])
    if pts:
        yield from step_included(ctx, pts[0], pts[1])


@command("arc.csl", group="draw", label="Center, Start, Length", description="Arc from centre, start, chord length.", menu="Draw > Arc > Center, Start, Length")
def arc_csl(ctx):
    pts = yield from _ask_points(ctx, [("Specify center point of arc", None), ("Specify start point of arc", 0)])
    if pts:
        yield from step_chord(ctx, pts[0], pts[1])


@command("arc.continue", group="draw", label="Continue", description="Arc tangent to the last line or arc, from its end to a picked point.", menu="Draw > Arc > Continue")
def arc_continue(ctx):
    yield from flow_arc_continue(ctx)


@executes("arc")
def arc_exec(ctx, args):
    if "points" in args:
        a, b, c = (_pt(p) for p in args["points"])
        res = geom.arc_from_3pts(a, b, c)
        if res is None:
            raise CommandError("Invalid arc or circle for these values.")
        return {"handle": ctx.add(_make_arc(*res))}
    if "continue" in args:
        prev = None
        for e in ctx.d.entities(ctx.doc.current_space):
            if isinstance(e, (Line, Arc)):
                prev = e
        e_pt = _pt(args["end"])
        if args.get("start") is not None and args.get("direction") is not None:
            s = _pt(args["start"])
            phi = math.radians(float(args["direction"]))
        else:
            if prev is None:
                raise CommandError("No line or arc to continue.")
            if isinstance(prev, Line):
                s, phi = list(prev.end), geom.angle_of(prev.start, prev.end)
            else:
                s, phi = geom.polar(prev.center, prev.radius, prev.end_angle), prev.end_angle + math.pi / 2.0
        return {"handle": ctx.add(_arc_from_start_end_tangent(ctx, s, e_pt, phi))}
    if "center" in args and "radius" in args and ("start_angle" in args or "end_angle" in args):
        r = float(args["radius"])
        if r <= 0:
            raise CommandError("Invalid arc or circle for these values.")
        c = _pt(args["center"])
        return {"handle": ctx.add(_make_arc(c, r, math.radians(float(args.get("start_angle", 0.0))), math.radians(float(args.get("end_angle", 180.0)))))}
    if "start" in args and "center" in args:
        s, c = _pt(args["start"]), _pt(args["center"])
        if "end" in args:
            return {"handle": ctx.add(_arc_sce(ctx, s, c, _pt(args["end"])))}
        if "angle" in args:
            return {"handle": ctx.add(_arc_sca(ctx, s, c, math.radians(float(args["angle"]))))}
        if "length" in args:
            return {"handle": ctx.add(_arc_scl(ctx, s, c, float(args["length"])))}
    if "start" in args and "end" in args:
        s, e = _pt(args["start"]), _pt(args["end"])
        if "angle" in args:
            return {"handle": ctx.add(_arc_sea(ctx, s, e, math.radians(float(args["angle"]))))}
        if "direction" in args:
            return {"handle": ctx.add(_arc_from_start_end_tangent(ctx, s, e, math.radians(float(args["direction"]))))}
        if "radius" in args:
            return {"handle": ctx.add(_arc_ser(ctx, s, e, float(args["radius"])))}
    raise CommandError("Give three points, centre and radius with angles, or a start with centre or end and a value.")


@executes("pline")
def pline_exec(ctx, args):
    verts = []
    for v in args.get("vertices", []):
        if isinstance(v, dict):
            p = _pt(v["point"])
            bulge = float(v.get("bulge", 0.0))
            sw = float(v.get("startWidth", 0.0))
            ew = float(v.get("endWidth", sw))
        else:
            p = _pt(v)
            bulge = sw = ew = 0.0
        if sw < 0 or ew < 0:
            raise CommandError("Negative widths are refused.")
        if verts and ctx.same(verts[-1]["p"], p):
            continue
        verts.append({"p": [p[0], p[1]], "bulge": bulge, "sw": sw, "ew": ew})
    if len(verts) < 2:
        raise CommandError("A polyline needs at least two vertices.")
    const = float(args.get("width", 0.0))
    if const < 0:
        raise CommandError("Negative widths are refused.")
    if const > 0:
        for v in verts:
            v["sw"] = v["ew"] = const
    widths = {(v["sw"], v["ew"]) for v in verts[:-1]}
    cw = 0.0
    if len(widths) == 1:
        sw, ew = next(iter(widths))
        cw = sw if sw == ew else 0.0
    return {"handle": ctx.add(LwPolyline(vertices=verts, closed=bool(args.get("closed")), const_width=cw))}


@command("circle.cd", group="draw", label="Center, Diameter", description="Circle from centre and diameter.", menu="Draw > Circle > Center, Diameter")
def circle_cd(ctx):
    r = yield ctx.point("Specify center point for circle")
    if r.kind == "point":
        yield from flow_circle_radius(ctx, r.value, diameter=True)


@command("circle.2p", group="draw", label="2 Points", description="Circle from two diameter end points.", menu="Draw > Circle > 2 Points")
def circle_2p(ctx):
    yield from flow_circle_2p(ctx)


@command("circle.3p", group="draw", label="3 Points", description="Circle through three points.", menu="Draw > Circle > 3 Points")
def circle_3p(ctx):
    yield from flow_circle_3p(ctx)


def _prim_of(ctx, val):
    ent = ctx.d.get(int(val["handle"]))
    pick = _pt(val["point"])
    if ent is None:
        return None
    best = None
    for pc in snaps.pieces(ent):
        if pc[0] == "seg":
            d = _seg_dist(pick, pc[1], pc[2]) if pc[3] else abs((pick[0] - pc[1][0]) * (pc[2][1] - pc[1][1]) - (pick[1] - pc[1][1]) * (pc[2][0] - pc[1][0])) / max(geom.dist(pc[1], pc[2]), UNIT_MIN)
            u = _unit([pc[2][0] - pc[1][0], pc[2][1] - pc[1][1]])
            if u is None:
                continue
            cand = {"t": "L", "p": [pc[1][0], pc[1][1]], "d": u, "pick": pick}
        elif pc[0] in ("circle", "arc"):
            d = abs(geom.dist(pick, pc[1]) - pc[2])
            cand = {"t": "C", "c": [pc[1][0], pc[1][1]], "r": float(pc[2]), "pick": pick}
        else:
            continue
        if best is None or d < best[0]:
            best = (d, cand)
    return best[1] if best else None


def _tangent_point(prim, x, r):
    if prim["t"] == "L":
        p, d = prim["p"], prim["d"]
        t = (x[0] - p[0]) * d[0] + (x[1] - p[1]) * d[1]
        return [p[0] + t * d[0], p[1] + t * d[1]]
    c, big = prim["c"], prim["r"]
    u = _unit([x[0] - c[0], x[1] - c[1]])
    if u is None:
        return [c[0] + big, c[1]]
    a = [c[0] + big * u[0], c[1] + big * u[1]]
    b = [c[0] - big * u[0], c[1] - big * u[1]]
    return a if abs(geom.dist(a, x) - r) <= abs(geom.dist(b, x) - r) else b


def _offset_prims(prim, r):
    if prim["t"] == "L":
        d = prim["d"]
        n = [-d[1], d[0]]
        p = prim["p"]
        return [{"t": "L", "p": [p[0] + s * r * n[0], p[1] + s * r * n[1]], "d": d} for s in (1.0, -1.0)]
    out = [{"t": "C", "c": prim["c"], "r": prim["r"] + r}]
    if prim["r"] - r >= 0:
        out.append({"t": "C", "c": prim["c"], "r": prim["r"] - r})
    else:
        out.append({"t": "C", "c": prim["c"], "r": r - prim["r"]})
    return out


def _meet(a, b):
    if a["t"] == "L" and b["t"] == "L":
        cr = a["d"][0] * b["d"][1] - a["d"][1] * b["d"][0]
        if abs(cr) < 1e-12:
            return []
        w = [b["p"][0] - a["p"][0], b["p"][1] - a["p"][1]]
        t = (w[0] * b["d"][1] - w[1] * b["d"][0]) / cr
        return [[a["p"][0] + t * a["d"][0], a["p"][1] + t * a["d"][1]]]
    if a["t"] == "C" and b["t"] == "L":
        a, b = b, a
    if a["t"] == "L":
        c, r = b["c"], b["r"]
        d = a["d"]
        w = [a["p"][0] - c[0], a["p"][1] - c[1]]
        bq = w[0] * d[0] + w[1] * d[1]
        cq = w[0] * w[0] + w[1] * w[1] - r * r
        disc = bq * bq - cq
        if disc < -1e-9:
            return []
        s = math.sqrt(max(disc, 0.0))
        return [[a["p"][0] + (-bq + k * s) * d[0], a["p"][1] + (-bq + k * s) * d[1]] for k in ((1.0, -1.0) if s > 1e-9 else (1.0,))]
    c1, r1, c2, r2 = a["c"], a["r"], b["c"], b["r"]
    dd = geom.dist(c1, c2)
    if dd < 1e-12:
        return []
    x = (dd * dd + r1 * r1 - r2 * r2) / (2.0 * dd)
    h2 = r1 * r1 - x * x
    if h2 < -1e-9:
        return []
    h = math.sqrt(max(h2, 0.0))
    ux, uy = (c2[0] - c1[0]) / dd, (c2[1] - c1[1]) / dd
    mx, my = c1[0] + x * ux, c1[1] + x * uy
    pts = [[mx - h * uy, my + h * ux]]
    if h > 1e-9:
        pts.append([mx + h * uy, my - h * ux])
    return pts


def solve_ttr(a, b, r):
    out = []
    for oa in _offset_prims(a, r):
        for ob in _offset_prims(b, r):
            for x in _meet(oa, ob):
                out.append((x, r))
    return out


def _rref(rows, ncols):
    m = [list(r) for r in rows]
    piv = []
    ri = 0
    for c in range(ncols):
        if ri >= len(m):
            break
        best = max(range(ri, len(m)), key=lambda i: abs(m[i][c]))
        if abs(m[best][c]) < 1e-12:
            continue
        m[ri], m[best] = m[best], m[ri]
        pv = m[ri][c]
        m[ri] = [v / pv for v in m[ri]]
        for i in range(len(m)):
            if i != ri:
                f = m[i][c]
                if f:
                    m[i] = [p - f * q for p, q in zip(m[i], m[ri])]
        piv.append(c)
        ri += 1
    return m, piv


def _solve_signs(prims, signs):
    rows = []
    has_circle = False
    for pr, s in zip(prims, signs):
        if pr["t"] == "L":
            d = pr["d"]
            n = [-d[1], d[0]]
            rows.append([n[0], n[1], -s, 0.0, n[0] * pr["p"][0] + n[1] * pr["p"][1]])
        else:
            has_circle = True
            c, big = pr["c"], pr["r"]
            rows.append([-2.0 * c[0], -2.0 * c[1], -2.0 * s * big, 1.0, big * big - c[0] * c[0] - c[1] * c[1]])
    if not has_circle:
        m, piv = _rref([[r[0], r[1], r[2], r[4]] for r in rows], 3)
        if piv != [0, 1, 2]:
            return []
        return [(m[0][3], m[1][3], m[2][3])]
    m, piv = _rref(rows, 4)
    if len(piv) != 3:
        return []
    for row in m[len(piv):]:
        if abs(row[4]) > 1e-9:
            return []
    free = [c for c in range(4) if c not in piv][0]
    u0 = [0.0] * 4
    w = [0.0] * 4
    w[free] = 1.0
    for k, c in enumerate(piv):
        u0[c] = m[k][4]
        w[c] = -m[k][free]
    qa = -(w[0] * w[0] + w[1] * w[1] - w[2] * w[2])
    qb = w[3] - 2.0 * (u0[0] * w[0] + u0[1] * w[1] - u0[2] * w[2])
    qc = u0[3] - (u0[0] * u0[0] + u0[1] * u0[1] - u0[2] * u0[2])
    roots = []
    if abs(qa) < 1e-12:
        if abs(qb) > 1e-12:
            roots.append(-qc / qb)
    else:
        disc = qb * qb - 4.0 * qa * qc
        if disc >= -1e-12:
            sq = math.sqrt(max(disc, 0.0))
            roots.extend([(-qb + sq) / (2.0 * qa), (-qb - sq) / (2.0 * qa)])
    return [(u0[0] + t * w[0], u0[1] + t * w[1], u0[2] + t * w[2]) for t in roots]


def solve_ttt(prims):
    out = []
    for signs in itertools.product((1.0, -1.0), repeat=3):
        for x, y, r in _solve_signs(prims, signs):
            if r > 1e-9 and all(math.isfinite(v) for v in (x, y, r)):
                out.append(([x, y], r))
    return out


def _best(prims, cands):
    best = None
    for x, r in cands:
        score = sum(geom.dist(_tangent_point(pr, x, r), pr["pick"]) for pr in prims)
        if best is None or score < best[0]:
            best = (score, x, r)
    return best


def _tan_message(ctx):
    ctx.say("Select a line, circle, arc or polyline segment.")


def _pick_tangent(ctx, msg):
    while True:
        r = yield ctx.entity(msg)
        if r.kind != "entity":
            return None
        prim = _prim_of(ctx, r.value)
        if prim is None:
            _tan_message(ctx)
            continue
        return prim


def flow_ttr(ctx):
    prims = []
    for label in ("first", "second"):
        prim = yield from _pick_tangent(ctx, "Specify point on object for %s tangent of circle" % label)
        if prim is None:
            return
        prims.append(prim)
    last = float(ctx.d.header.get("CIRCLERAD", 0.0))
    base = prims[0]["pick"]

    def preview(p):
        r = geom.dist(base, p)
        best = _best(prims, solve_ttr(prims[0], prims[1], r)) if r > ctx.d.tolerances["absolute"] else None
        if best is None:
            return jig.rubber(base, p)
        return [jig.circle(best[1], best[2])]

    while True:
        rr = yield ctx.distance("Specify radius of circle", default=last if last > 0 else None, base=base, positive=True, jig=preview)
        v = dnum(rr, base) if rr.kind in ("number", "point") else None
        if v is None:
            return
        if v <= ctx.d.tolerances["absolute"]:
            ctx.say("Value must be positive and nonzero.")
            continue
        best = _best(prims, solve_ttr(prims[0], prims[1], v))
        if best is None:
            ctx.say("Circle does not exist.")
            continue
        _finish_circle(ctx, [best[1][0], best[1][1], 0.0], v)
        return


def flow_ttt(ctx):
    while True:
        prims = []
        for label in ("first", "second", "third"):
            prim = yield from _pick_tangent(ctx, "Specify %s point on circle: _tan to" % label)
            if prim is None:
                return
            prims.append(prim)
        best = _best(prims, solve_ttt(prims))
        if best is None:
            ctx.say("Circle does not exist.")
            continue
        _finish_circle(ctx, [best[1][0], best[1][1], 0.0], best[2])
        return


@command("circle.ttr", group="draw", label="Tan, Tan, Radius", description="Circle tangent to two objects with a given radius.", menu="Draw > Circle > Tan, Tan, Radius")
def circle_ttr(ctx):
    yield from flow_ttr(ctx)


@command("circle.ttt", group="draw", label="Tan, Tan, Tan", description="Circle tangent to three objects.", menu="Draw > Circle > Tan, Tan, Tan")
def circle_ttt(ctx):
    yield from flow_ttt(ctx)


def _prims_from_args(ctx, args, count):
    objs = args.get("objects") or []
    if len(objs) != count:
        raise CommandError("Give %d objects with a pick point each." % count)
    prims = []
    for o in objs:
        pr = _prim_of(ctx, o)
        if pr is None:
            raise CommandError("Select a line, circle, arc or polyline segment.")
        prims.append(pr)
    return prims


@executes("circle.ttr")
def circle_ttr_exec(ctx, args):
    prims = _prims_from_args(ctx, args, 2)
    r = float(args.get("radius", 0.0))
    if r <= 0:
        raise CommandError("Value must be positive and nonzero.")
    best = _best(prims, solve_ttr(prims[0], prims[1], r))
    if best is None:
        raise CommandError("Circle does not exist.")
    return {"handle": _finish_circle(ctx, [best[1][0], best[1][1], 0.0], r)}


@executes("circle.ttt")
def circle_ttt_exec(ctx, args):
    prims = _prims_from_args(ctx, args, 3)
    best = _best(prims, solve_ttt(prims))
    if best is None:
        raise CommandError("Circle does not exist.")
    return {"handle": _finish_circle(ctx, [best[1][0], best[1][1], 0.0], best[2])}


ISO_MAJOR = {0: 2.0 * math.pi / 3.0, 1: 0.0, 2: math.pi / 3.0}
ISO_RATIO = 1.0 / math.sqrt(3.0)
ISO_SCALE = math.sqrt(1.5)
MAX_ROTATION = math.radians(89.4)


def _ell_geom(c, major, ratio, a0=0.0, a1=geom.TAU):
    return {"type": "ellipse", "c": [c[0], c[1]], "major": [major[0], major[1]], "ratio": ratio, "a0": a0, "a1": a1}


def _axes_ellipse(c, first, d, pick=None):
    a = math.hypot(first[0], first[1])
    if a < UNIT_MIN or d < UNIT_MIN:
        return None
    if d > a:
        n = [-first[1] / a, first[0] / a]
        if pick is not None and (first[0] * (pick[1] - c[1]) - first[1] * (pick[0] - c[0])) < 0:
            n = [-n[0], -n[1]]
        return [n[0] * d, n[1] * d], a / d
    return [first[0], first[1]], d / a


def _param_of(alpha, ratio):
    return math.atan2(math.sin(alpha), ratio * math.cos(alpha))


def _add_ellipse(ctx, c, major, ratio, t0=0.0, t1=geom.TAU):
    if ratio <= 0 or ratio > 1 + 1e-12:
        raise CommandError("Invalid ellipse.")
    return ctx.add(Ellipse(center=[c[0], c[1], 0.0], major=[major[0], major[1], 0.0], ratio=min(ratio, 1.0), start_param=t0, end_param=t1))


def _ask_other_axis(ctx, c, first):
    while True:
        def preview(p):
            res = _axes_ellipse(c, first, geom.dist(c, p), p)
            return [_ell_geom(c, res[0], res[1])] + jig.rubber(c, p) if res else jig.rubber(c, p)

        d = yield ctx.distance("Specify distance to other axis", ["Rotation"], base=c, positive=True, jig=preview)
        if d.kind == "keyword":
            while True:
                q = yield ctx.angle("Specify rotation around major axis", absolute=False, jig=lambda p: jig.rubber(c, p))
                if q.kind != "number":
                    return None
                if q.value < 0 or q.value > MAX_ROTATION + 1e-12:
                    ctx.say("Requires an angle between 0 and 89.4 degrees.")
                    continue
                return [first[0], first[1]], math.cos(q.value)
        v = dnum(d, c) if d.kind in ("number", "point") else None
        if v is None:
            return None
        res = _axes_ellipse(c, first, v, d.value if d.kind == "point" else None)
        if res is None:
            ctx.say("Value must be positive and nonzero.")
            continue
        return res


def _ell_arc_preview(c, major, ratio, t0, p, mode):
    ref = math.atan2(major[1], major[0])
    alpha = geom.angle_of(c, p) - ref
    t1 = alpha if mode == "param" else _param_of(alpha, ratio)
    return [_ell_geom(c, major, ratio, t0, t1)] + jig.rubber(c, p)


def _flow_ell_arc(ctx, c, major, ratio):
    ref = math.atan2(major[1], major[0])
    mode = "angle"
    while True:
        if mode == "angle":
            s = yield ctx.angle("Specify start angle", ["Parameter"], base=c, absolute=False, jig=lambda p: [_ell_geom(c, major, ratio)] + jig.rubber(c, p))
        else:
            s = yield ctx.angle("Specify start parameter", ["Angle"], base=c, absolute=False, jig=lambda p: [_ell_geom(c, major, ratio)] + jig.rubber(c, p))
        if s.kind == "keyword":
            mode = "param" if s.value == "Parameter" else "angle"
            continue
        sv = anum(s, c, ref) if s.kind in ("number", "point") else None
        if sv is None:
            return
        break
    s_alpha = sv
    s_param = sv if mode == "param" else _param_of(sv, ratio)
    emode = mode
    while True:
        if emode == "angle":
            e = yield ctx.angle("Specify end angle", ["Parameter", "Included angle"], base=c, absolute=False, jig=lambda p: _ell_arc_preview(c, major, ratio, s_param, p, "angle"))
        else:
            e = yield ctx.angle("Specify end parameter", ["Angle", "Included angle"], base=c, absolute=False, jig=lambda p: _ell_arc_preview(c, major, ratio, s_param, p, "param"))
        if e.kind == "keyword" and e.value in ("Parameter", "Angle"):
            emode = "param" if e.value == "Parameter" else "angle"
            continue
        if e.kind == "keyword":
            inc = yield ctx.angle("Specify included angle for arc", default=math.pi, absolute=False, jig=lambda p: _ell_arc_preview(c, major, ratio, s_param, p, emode))
            if inc.kind != "number":
                return
            if abs(inc.value) < 1e-9:
                ctx.say("Invalid arc or circle for these values.")
                continue
            end_val = (s_alpha if emode == "angle" else s_param) + inc.value
        else:
            ev = anum(e, c, ref) if e.kind in ("number", "point") else None
            if ev is None:
                return
            end_val = ev
        t1 = end_val if emode == "param" else _param_of(end_val, ratio)
        _add_ellipse(ctx, c, major, ratio, geom.norm_angle(s_param), geom.norm_angle(t1))
        return


def _flow_ellipse_axes(ctx, arc, center=None):
    if center is None:
        msg = "Specify axis endpoint of elliptical arc" if arc else "Specify axis endpoint of ellipse"
        r = yield ctx.point(msg, ["Center"] if arc else ["Arc", "Center"] + (["Isocircle"] if int(ctx.var("SNAPSTYL") or 0) == 1 else []))
        if r.kind == "keyword":
            if r.value == "Arc":
                yield from _flow_ellipse_axes(ctx, True)
                return
            if r.value == "Isocircle":
                yield from _flow_isocircle(ctx)
                return
            c = yield ctx.point("Specify center of ellipse")
            if c.kind != "point":
                return
            yield from _flow_ellipse_axes(ctx, arc, c.value)
            return
        if r.kind != "point":
            return
        p1 = r.value
        p2r = yield ctx.point("Specify other endpoint of axis", base=p1, jig=lambda p: jig.rubber(p1, p))
        if p2r.kind != "point":
            return
        p2 = p2r.value
        c = geom.midpoint(p1, p2)
        first = [p2[0] - c[0], p2[1] - c[1]]
        if math.hypot(first[0], first[1]) < ctx.d.tolerances["absolute"]:
            ctx.say("Value must be positive and nonzero.")
            return
    else:
        c = center
        e = yield ctx.point("Specify endpoint of axis", base=c, jig=lambda p: jig.rubber(c, p))
        if e.kind != "point":
            return
        first = [e.value[0] - c[0], e.value[1] - c[1]]
        if math.hypot(first[0], first[1]) < ctx.d.tolerances["absolute"]:
            ctx.say("Value must be positive and nonzero.")
            return
    res = yield from _ask_other_axis(ctx, c, first)
    if res is None:
        return
    major, ratio = res
    if arc:
        yield from _flow_ell_arc(ctx, c, major, ratio)
    else:
        _add_ellipse(ctx, c, major, ratio)


def _flow_isocircle(ctx):
    c = yield ctx.point("Specify center point for isocircle")
    if c.kind != "point":
        return
    plane = int(ctx.var("SNAPISOPAIR") or 0)
    ang = ISO_MAJOR.get(plane, 0.0)
    diameter = False
    while True:
        def preview(p, f=0.5 if diameter else 1.0):
            r = geom.dist(c.value, p) * f
            if r < ctx.d.tolerances["absolute"]:
                return jig.rubber(c.value, p)
            a = r * ISO_SCALE
            return [_ell_geom(c.value, [a * math.cos(ang), a * math.sin(ang)], ISO_RATIO)] + jig.rubber(c.value, p)

        if diameter:
            q = yield ctx.distance("Specify diameter of isocircle", base=c.value, positive=True, jig=preview)
        else:
            q = yield ctx.distance("Specify radius of isocircle", ["Diameter"], base=c.value, positive=True, jig=preview)
        if q.kind == "keyword":
            diameter = True
            continue
        v = dnum(q, c.value) if q.kind in ("number", "point") else None
        if v is None:
            return
        r = v / 2.0 if diameter else v
        if r <= ctx.d.tolerances["absolute"]:
            ctx.say("Value must be positive and nonzero.")
            continue
        a = r * ISO_SCALE
        _add_ellipse(ctx, c.value, [a * math.cos(ang), a * math.sin(ang)], ISO_RATIO)
        return


@command("ellipse", aliases=("el",), group="draw", label="Ellipse", description="Ellipse or elliptical arc by axis end points or centre; Rotation, Parameter, Included angle, Isocircle.", menu="Draw > Ellipse > Center")
def ellipse(ctx):
    yield from _flow_ellipse_axes(ctx, False)


@command("ellipse.axis", group="draw", label="Axis, End", description="Ellipse from axis end points and half of the other axis.", menu="Draw > Ellipse > Axis, End")
def ellipse_axis(ctx):
    p1 = yield ctx.point("Specify axis endpoint of ellipse")
    if p1.kind != "point":
        return
    yield from _axis_from(ctx, p1.value, False)


def _axis_from(ctx, p1, arc):
    p2r = yield ctx.point("Specify other endpoint of axis", base=p1, jig=lambda p: jig.rubber(p1, p))
    if p2r.kind != "point":
        return
    c = geom.midpoint(p1, p2r.value)
    first = [p2r.value[0] - c[0], p2r.value[1] - c[1]]
    if math.hypot(first[0], first[1]) < ctx.d.tolerances["absolute"]:
        ctx.say("Value must be positive and nonzero.")
        return
    res = yield from _ask_other_axis(ctx, c, first)
    if res is None:
        return
    if arc:
        yield from _flow_ell_arc(ctx, c, res[0], res[1])
    else:
        _add_ellipse(ctx, c, res[0], res[1])


@command("ellipse.arc", group="draw", label="Elliptical Arc", description="Elliptical arc from ellipse plus start and end angles.", menu="Draw > Ellipse > Arc")
def ellipse_arc(ctx):
    yield from _flow_ellipse_axes(ctx, True)


@executes("ellipse", "ellipse.axis", "ellipse.arc")
def ellipse_exec(ctx, args):
    if "center" in args and "major" in args:
        c = _pt(args["center"])
        major = _pt(args["major"])
        ratio = float(args.get("ratio", 1.0))
        if not 0 < ratio <= 1 or math.hypot(major[0], major[1]) < ctx.d.tolerances["absolute"]:
            raise CommandError("Invalid ellipse.")
        if "start" not in args and "end" not in args:
            return {"handle": _add_ellipse(ctx, c, major, ratio)}
        t0 = math.radians(float(args.get("start", 0.0)))
        t1 = math.radians(float(args.get("end", 360.0)))
        return {"handle": _add_ellipse(ctx, c, major, ratio, geom.norm_angle(t0), geom.norm_angle(t1))}
    p1, p2 = _pt(args["p1"]), _pt(args["p2"])
    c = geom.midpoint(p1, p2)
    first = [p2[0] - c[0], p2[1] - c[1]]
    if args.get("p3") is not None:
        d = geom.dist(c, _pt(args["p3"]))
        pick = _pt(args["p3"])
    else:
        d = float(args.get("distance", 0.0))
        pick = None
    res = _axes_ellipse(c, first, d, pick)
    if res is None:
        raise CommandError("Value must be positive and nonzero.")
    major, ratio = res
    if "start" in args or "end" in args:
        s = math.radians(float(args.get("start", 0.0)))
        e = math.radians(float(args.get("end", 360.0)))
        t0, t1 = _param_of(s, ratio), _param_of(e, ratio)
        return {"handle": _add_ellipse(ctx, c, major, ratio, geom.norm_angle(t0), geom.norm_angle(t1))}
    return {"handle": _add_ellipse(ctx, c, major, ratio)}
