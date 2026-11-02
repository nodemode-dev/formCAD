import math

from app.cmd import jig
from app.cmd.context import CommandError
from app.cmd.draw_support import inherit
from app.cmd.registry import command, executes
from app.doc import geom, nurbs
from app.doc.entities import LwPolyline, Polyline3d, Spline
from app.doc.kinds.helix import MAX_TURNS, Helix

KNOT_NAMES = ("Chord", "Square root", "Uniform")
MAX_DEGREE = 10


def curve_shape(curve, fit=None) -> dict:
    return {"type": "spline", "degree": curve.degree, "knots": list(curve.knots), "ctrl": [[p[0], p[1]] for p in curve.ctrl], "weights": list(curve.weights) if curve.weights else None, "fit": [[p[0], p[1]] for p in fit] if fit else None, "closed": curve.closed}


def _unit(a):
    return [math.cos(a), math.sin(a), 0.0]


def fit_entity(pts, kind, closed, t0, t1, tol) -> Spline:
    try:
        curve, flat = nurbs.fit(pts, kind, closed, t0, t1, tol)
    except ValueError as err:
        raise CommandError(str(err))
    return Spline(degree=curve.degree, knots=list(curve.knots), control_points=[list(p) for p in curve.ctrl], weights=[], fit_points=[list(p) for p in flat], closed=curve.closed, fit_method=kind, start_tangent=t0, end_tangent=t1, fit_tolerance=float(tol))


def cv_entity(pts, degree, closed) -> Spline:
    clean = [list(p) + [0.0] * (3 - len(p)) for p in pts]
    if len({(round(p[0], 9), round(p[1], 9)) for p in clean}) < 2:
        raise CommandError("A spline needs at least two distinct points.")
    if closed and len(clean) < 3:
        raise CommandError("A closed spline needs at least three points.")
    curve = nurbs.from_control_points(clean, max(1, min(int(degree), MAX_DEGREE)), closed)
    return Spline(degree=curve.degree, knots=list(curve.knots), control_points=[list(p) for p in curve.ctrl], weights=[], fit_points=[], closed=closed, fit_method=0)


def _preview_fit(pts, kind):
    if len(pts) < 2:
        return []
    try:
        curve, flat = nurbs.fit(pts, kind)
    except Exception:
        return [jig.line(pts[0], pts[-1])]
    return [curve_shape(curve)]


def _preview_cv(pts, degree):
    if len(pts) < 2:
        return []
    c = nurbs.from_control_points(pts, degree)
    return [curve_shape(c)] + [jig.line(a, b) for a, b in zip(pts, pts[1:])]


def convert_polyline(ctx, ent):
    if isinstance(ent, LwPolyline):
        if any(abs(v.get("bulge", 0.0) or 0.0) > 1e-12 for v in ent.vertices):
            raise CommandError("Polylines with arc segments cannot be converted to splines.")
        pts = [[v["p"][0], v["p"][1], 0.0] for v in ent.vertices]
        closed = bool(ent.closed)
    elif isinstance(ent, Polyline3d):
        pts = [list(p) for p in ent.points]
        closed = bool(ent.closed)
    else:
        raise CommandError("Select a polyline.")
    sp = fit_entity(pts, int(ctx.var("SPLKNOTS")), closed, None, None, 0.0)
    inherit(ent, sp)
    ctx.d.erase_entity(ent.handle)
    return ctx.add(sp)


def _convert_handles(ctx, handles) -> tuple:
    made, skipped = [], 0
    for e in ctx.editable(handles):
        try:
            made.append(convert_polyline(ctx, e))
        except CommandError as err:
            skipped += 1
            ctx.say(str(err))
    return made, skipped


def _spline(ctx, cv_start):
    if cv_start:
        ctx.setvar("SPLMETHOD", 1)
    while True:
        cv = int(ctx.var("SPLMETHOD")) == 1
        kind = int(ctx.var("SPLKNOTS"))
        degree = int(ctx.var("SPLDEGREE"))
        if cv:
            ctx.say("Current settings: Method=CV Degree=%d" % degree)
        else:
            ctx.say("Current settings: Method=Fit Knots=%s" % KNOT_NAMES[kind])
        first = yield ctx.point("Specify first point", ["Method", "Degree" if cv else "Knots", "Object"])
        if first.kind == "keyword":
            if first.value == "Method":
                m = yield ctx.keyword("Enter spline creation method", ["Fit", "CV"], "CV" if cv else "Fit")
                if m.kind in ("keyword", "enter"):
                    ctx.setvar("SPLMETHOD", 1 if (m.value if m.kind == "keyword" else ("CV" if cv else "Fit")) == "CV" else 0)
                continue
            if first.value == "Knots":
                k = yield ctx.keyword("Enter knot parameterization", list(KNOT_NAMES), KNOT_NAMES[kind])
                if k.kind in ("keyword", "enter"):
                    name = k.value if k.kind == "keyword" else KNOT_NAMES[kind]
                    ctx.setvar("SPLKNOTS", KNOT_NAMES.index(name))
                continue
            if first.value == "Degree":
                d = yield ctx.number("Enter degree", default=degree, integer=True, minimum=1, maximum=MAX_DEGREE)
                if d.kind in ("number", "enter"):
                    ctx.setvar("SPLDEGREE", degree if d.kind == "enter" else int(d.value))
                continue
            s = yield ctx.select("Select objects to convert to splines")
            if s.kind == "selection" and s.value:
                made, skipped = _convert_handles(ctx, s.value)
                ctx.say("%d spline%s created." % (len(made), "" if len(made) == 1 else "s"))
            return
        if first.kind != "point":
            return
        pts = [first.value]
        t0 = t1 = None
        tol = 0.0
        closed = False
        while True:
            opts = [] if cv else ["start Tangency", "end Tangency", "toLerance"]
            opts.append("Undo")
            if len(pts) >= 3:
                opts.append("Close")
            if cv:
                shape = lambda p: _preview_cv(pts + [p], degree)
            else:
                shape = lambda p: _preview_fit(pts + [p], kind)
            r = yield ctx.point("Enter next point", opts, base=pts[-1], jig=shape)
            if r.kind == "enter":
                break
            if r.kind == "point":
                pts.append(r.value)
                continue
            if r.kind != "keyword":
                return
            if r.value == "Undo":
                if len(pts) > 1:
                    pts.pop()
                continue
            if r.value == "Close":
                closed = True
                break
            if r.value == "toLerance":
                tv = yield ctx.number("Specify fit tolerance", default=tol, minimum=0)
                if tv.kind == "number":
                    tol = float(tv.value)
                continue
            which = r.value
            anchor = pts[0] if which.startswith("start") else pts[-1]
            a = yield ctx.angle("Specify %s tangent" % ("start" if which.startswith("start") else "end"), base=anchor)
            if a.kind in ("number", "point"):
                if a.kind == "point" and ctx.same(a.value, anchor):
                    ctx.say("A tangent needs a direction.")
                    continue
                ang = a.value if a.kind == "number" else geom.angle_of(anchor, a.value)
                if which.startswith("start"):
                    t0 = _unit(ang)
                else:
                    t1 = _unit(ang)
        if len(pts) < 2:
            return
        sp = cv_entity(pts, degree, closed) if cv else fit_entity(pts, kind, closed, None if closed else t0, None if closed else t1, 0.0 if closed else tol)
        ctx.add(sp)
        return


@command("spline", aliases=("spl",), group="draw", label="Spline", description="Fit-point spline with knots, tangents, tolerance, close; Object converts a polyline; Method CV.", menu="Draw > Spline > Fit Points")
def spline_cmd(ctx):
    yield from _spline(ctx, False)


@command("spline.cv", group="draw", label="Control Vertices", description="Spline by control vertices with degree 1 to 10.", menu="Draw > Spline > Control Vertices")
def spline_cv(ctx):
    yield from _spline(ctx, True)


def _spline_exec(ctx, args, cv_default):
    if "handles" in args or args.get("object") or args.get("selection"):
        handles = [int(h) for h in args.get("handles", [])] or list(ctx.doc.selection)
        made, skipped = _convert_handles(ctx, handles)
        if not made:
            raise CommandError("No polyline could be converted.")
        return {"handles": made, "skipped": skipped}
    closed = bool(args.get("closed", False))
    if "control" in args or "control_points" in args or cv_default:
        pts = [geom.as_pt(p) for p in args.get("control", args.get("control_points", args.get("points", [])))]
        deg = int(args.get("degree", 3))
        if not 1 <= deg <= MAX_DEGREE:
            raise CommandError("The degree must be from 1 to %d." % MAX_DEGREE)
        return {"handle": ctx.add(cv_entity(pts, deg, closed))}
    pts = [geom.as_pt(p) for p in args.get("fit", args.get("points", []))]
    knots = args.get("knots", "chord")
    kind = {"chord": 0, "sqrt": 1, "square root": 1, "uniform": 2, 0: 0, 1: 1, 2: 2}.get(knots.lower() if isinstance(knots, str) else knots)
    if kind is None:
        raise CommandError("Knots must be chord, sqrt or uniform.")
    t0 = _dir(args.get("start_tangent"))
    t1 = _dir(args.get("end_tangent"))
    tol = float(args.get("tolerance", 0.0))
    if tol < 0:
        raise CommandError("The fit tolerance must not be negative.")
    return {"handle": ctx.add(fit_entity(pts, kind, closed, None if closed else t0, None if closed else t1, 0.0 if closed else tol))}


def _dir(v):
    if v is None:
        return None
    p = geom.as_pt(v)
    if math.hypot(p[0], p[1]) < geom.EPS:
        raise CommandError("A tangent needs a nonzero direction.")
    return p


@executes("spline")
def spline_exec(ctx, args):
    return _spline_exec(ctx, args, False)


@executes("spline.cv")
def spline_cv_exec(ctx, args):
    return _spline_exec(ctx, args, True)


def make_helix(center, base, top, height, turns, ccw, start) -> Helix:
    h = Helix(center=list(center), base_radius=float(base), top_radius=float(top), height=float(height), turns=float(turns), start_angle=float(start), ccw=bool(ccw))
    h.rebuild()
    return h


def _helix_shape(center, base, top, height, turns, ccw, start):
    try:
        return [curve_shape(make_helix(center, base, top, height, turns, ccw, start).curve())]
    except Exception:
        return []


@command("helix", group="draw", label="Helix", description="Spiral or cone helix with turns, height, twist.", menu="Draw > Helix")
def helix(ctx):
    turns = float(ctx.var("HELIXTURNS"))
    ccw = int(ctx.var("HELIXTWIST")) == 0
    ctx.say("Number of turns = %.4f Twist=%s" % (turns, "CCW" if ccw else "CW"))
    c = yield ctx.point("Specify center point of base")
    if c.kind != "point":
        return
    center = c.value
    start = 0.0
    base_default = float(ctx.var("HELIXBASE"))
    r = yield ctx.distance("Specify base radius", ["Diameter"], default=base_default, base=center, positive=True, jig=lambda p: jig.circle_radius(center, p))
    if r.kind == "keyword":
        d = yield ctx.distance("Specify base diameter", default=base_default * 2.0, base=center, positive=True, jig=lambda p: jig.circle_radius(center, p, 0.5))
        if d.kind != "number":
            return
        base = d.value / 2.0
    elif r.kind == "point":
        base = geom.dist(center, r.value)
        start = geom.angle_of(center, r.value)
        if base < ctx.d.tolerances["absolute"]:
            raise CommandError("Value must be positive and nonzero.")
    elif r.kind == "number":
        base = r.value
    else:
        base = base_default
    top_default = base
    t = yield ctx.distance("Specify top radius", ["Diameter"], default=top_default, base=center, nonneg=True, jig=lambda p: jig.circle_radius(center, p))
    if t.kind == "keyword":
        d = yield ctx.distance("Specify top diameter", default=top_default * 2.0, base=center, nonneg=True, jig=lambda p: jig.circle_radius(center, p, 0.5))
        if d.kind != "number":
            return
        top = d.value / 2.0
    elif t.kind == "point":
        top = geom.dist(center, t.value)
    elif t.kind == "number":
        top = t.value
    else:
        top = top_default
    height = float(ctx.var("HELIXHEIGHT"))
    while True:
        h = yield ctx.distance("Specify helix height", ["Axis endpoint", "Turns", "turn Height", "tWist"], default=height, base=center, jig=lambda p: _helix_shape(center, base, top, geom.dist(center, p) or height, turns, ccw, start))
        if h.kind == "keyword":
            if h.value == "Axis endpoint":
                a = yield ctx.point("Specify axis endpoint", base=center, jig=lambda p: [jig.line(center, p)] + _helix_shape(center, base, top, geom.dist(center, p) or height, turns, ccw, start))
                if a.kind == "point":
                    height = geom.dist(center, a.value)
                    if a.value[2] and abs(a.value[2]) > geom.EPS:
                        height = math.copysign(math.sqrt(height * height + a.value[2] ** 2), a.value[2])
                    break
                continue
            if h.value == "Turns":
                n = yield ctx.number("Enter number of turns", default=turns, minimum=1, maximum=MAX_TURNS)
                if n.kind == "number":
                    turns = float(n.value)
                continue
            if h.value == "turn Height":
                th = yield ctx.distance("Specify distance between turns", default=height / turns, base=center)
                if th.kind == "number" and th.value != 0:
                    height = th.value * turns
                continue
            w = yield ctx.keyword("Enter twist direction", ["CCW", "CW"], "CCW" if ccw else "CW")
            if w.kind == "keyword":
                ccw = w.value == "CCW"
            continue
        if h.kind == "point":
            height = geom.dist(center, h.value)
        elif h.kind == "number":
            height = h.value
        elif h.kind != "enter":
            return
        break
    _finish_helix(ctx, center, base, top, height, turns, ccw, start)


def _finish_helix(ctx, center, base, top, height, turns, ccw, start):
    if not (base > geom.EPS) or top < 0 or abs(height) <= geom.EPS or not (0 < turns <= MAX_TURNS):
        raise CommandError("Invalid helix values.")
    ctx.ensure_finite(base, top, height, turns, start)
    h = make_helix(center, base, top, height, turns, ccw, start)
    handle = ctx.add(h)
    ctx.setvar("HELIXTURNS", float(turns))
    ctx.setvar("HELIXTWIST", 0 if ccw else 1)
    ctx.setvar("HELIXBASE", float(base))
    ctx.setvar("HELIXTOP", float(top))
    ctx.setvar("HELIXHEIGHT", float(height))
    return handle


@executes("helix")
def helix_exec(ctx, args):
    center = geom.as_pt(args.get("center", [0.0, 0.0, 0.0]))
    base = float(args.get("base_radius", args.get("radius", 1.0)))
    top = float(args.get("top_radius", base))
    height = float(args.get("height", 1.0))
    turns = float(args.get("turns", 3.0))
    ccw = bool(args.get("ccw", True))
    start = math.radians(float(args.get("start_angle", 0.0)))
    return {"handle": _finish_helix(ctx, center, base, top, height, turns, ccw, start)}
