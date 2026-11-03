import math

import numpy as np

from app.cmd.context import CommandError
from app.cmd.draw_support import inherit, pick_entity, pick_point
from app.cmd.registry import command, executes
from app.doc.kinds.nurbscurve import NurbsCurve
from app.nurbs3d import service
from app.nurbs3d.blend import level_of
from app.nurbs3d.form import FormError, NurbsForm
from app.nurbs3d.service import CurveError

KNOT_KINDS = ("chord", "centripetal", "uniform")
STYLES = ("line", "arc", "smooth")
LEVEL_NAMES = ("G0", "G1", "G2", "G3")
MAX_CV_DEGREE = 24


def guard(fn, *a, **k):
    try:
        return fn(*a, **k)
    except (CurveError, FormError) as err:
        raise CommandError(str(err))


def xyz(p):
    return [float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 0.0]


def curve_of(ctx, handle, allow_locked=False):
    try:
        e = ctx.d.get(int(handle))
    except (TypeError, ValueError):
        e = None
    if e is None or e.kind != "nurbscurve":
        raise CommandError("Handle %s is not a NURBS curve." % handle)
    if not allow_locked and ctx.locked(e):
        raise CommandError("The curve is on a locked layer.")
    return e


def arg_curve(ctx, args, key="handle"):
    if args.get(key) is None:
        raise CommandError("Give the handle of a NURBS curve as %s." % key)
    return curve_of(ctx, args[key])


def arg_end(ctx, e, args, key="end", point_key="point"):
    which = args.get(key)
    if which in ("start", "end"):
        return which
    if args.get(point_key) is not None:
        return service.end_near(service.form_of(e), args[point_key])
    raise CommandError("Give %s as start or end." % key)


def new_curve(ctx, rec, audit, source, name="Curve", like=None):
    e = NurbsCurve(name=name)
    e.set_record(rec)
    e.audit = audit
    e.source = source
    if like is not None:
        inherit(like, e)
    return ctx.add(e)


def put(ctx, e, rec, audit, source=None, copy=False):
    if copy:
        return new_curve(ctx, rec, audit, source or e.source, e.name, e)
    rev = ctx.d.modify(e.handle)
    service.apply(rev, rec, audit, source)
    return e.handle


def pole_note(rec):
    return "%d poles, degree %d" % (len(rec["poles"]), rec["degree"])


def say_audit(ctx, label, rec, audit):
    parts = ["%s: %s" % (label, pole_note(rec))]
    if audit.get("deviation") is not None:
        parts.append("deviation %s" % ctx.fd(audit["deviation"]))
    if audit.get("exceeds"):
        parts.append("stored tolerance %s exceeds the document tolerance" % ctx.fd(max(audit.get("vertex_max", 0.0), audit.get("edge_max", 0.0))))
    ctx.say(", ".join(parts) + ".")


def select_curve(ctx, msg="Select a NURBS curve"):
    while True:
        r = yield ctx.entity(msg)
        if r.kind != "entity":
            return None
        e = pick_entity(ctx, r.value)
        if e is None or e.kind != "nurbscurve":
            ctx.say("That object is not a NURBS curve.")
            continue
        if ctx.locked(e):
            ctx.say("That curve is on a locked layer.")
            continue
        return e, pick_point(r.value)


def cv_record(d, points, degree, weights, periodic):
    if len(points) < 2:
        raise CommandError("A curve needs at least two points.")
    if not 1 <= int(degree) <= MAX_CV_DEGREE:
        raise CommandError("The degree must be from 1 to %d." % MAX_CV_DEGREE)
    pts = [xyz(p) for p in points]
    if weights and len(weights) != len(pts):
        raise CommandError("Give one weight per point.")
    if weights and min(float(w) for w in weights) <= 0:
        raise CommandError("Weights must be positive.")
    if periodic:
        if len(pts) < 3:
            raise CommandError("A periodic curve needs at least three points.")
        deg = max(1, min(int(degree), len(pts) - 1))
    else:
        deg = max(1, min(int(degree), len(pts) - 1))
    return guard(NurbsForm.from_points, pts, deg, weights, periodic)


def add_cv(ctx, points, degree=3, weights=None, periodic=False):
    form = cv_record(ctx.d, points, degree, weights, periodic)
    rec, audit = guard(service.checked_record, ctx.d, form)
    h = new_curve(ctx, rec, audit, {"op": "control_points", "degree": int(degree)})
    ctx.say("CRV: %s." % pole_note(rec))
    return h


@command("crv", aliases=("crvcv",), group="draw", label="Curve by Control Points", description="NURBS curve from control points with degree, weights and a periodic option.", menu="Draw > Curve > Control Points")
def crv_cmd(ctx):
    degree = int(ctx.mem.get("crv_degree", 3))
    while True:
        first = yield ctx.point("Specify first control point", ["Degree"])
        if first.kind == "keyword":
            d = yield ctx.number("Enter degree", default=degree, integer=True, minimum=1, maximum=MAX_CV_DEGREE)
            if d.kind == "number":
                degree = int(d.value)
                ctx.mem["crv_degree"] = degree
            continue
        break
    if first.kind != "point":
        return
    pts, wts = [xyz(first.value)], [1.0]
    pending = 1.0
    periodic = False
    while True:
        opts = ["Undo", "Degree", "Weight"]
        if len(pts) >= 3:
            opts.append("Close")
        r = yield ctx.point("Specify next control point", opts, base=pts[-1])
        if r.kind == "enter":
            break
        if r.kind == "point":
            pts.append(xyz(r.value))
            wts.append(pending)
            pending = 1.0
            continue
        if r.kind != "keyword":
            return
        if r.value == "Undo":
            if len(pts) > 1:
                pts.pop()
                wts.pop()
        elif r.value == "Close":
            periodic = True
            break
        elif r.value == "Degree":
            d = yield ctx.number("Enter degree", default=degree, integer=True, minimum=1, maximum=MAX_CV_DEGREE)
            if d.kind == "number":
                degree = int(d.value)
                ctx.mem["crv_degree"] = degree
        else:
            w = yield ctx.number("Weight of the next point", default=1.0, positive=True)
            if w.kind == "number":
                pending = float(w.value)
    if len(pts) < 2:
        return
    use_w = wts if any(abs(w - 1.0) > 1e-12 for w in wts) else None
    add_cv(ctx, pts, degree, use_w, periodic)


@executes("crv")
def crv_exec(ctx, args):
    pts = args.get("points") or args.get("control_points")
    if not pts:
        raise CommandError("Give points as a list of [x, y, z].")
    return {"handle": add_cv(ctx, pts, int(args.get("degree", 3)), args.get("weights"), bool(args.get("periodic", False)))}


def interp_params(ctx, points, periodic, kind, t0, t1, tangents=None, flags=None):
    if len(points) < (3 if periodic else 2):
        raise CommandError("Interpolation needs %d points or more." % (3 if periodic else 2))
    if kind not in KNOT_KINDS:
        raise CommandError("Knots are chord, centripetal or uniform.")
    params = {"points": [xyz(p) for p in points], "periodic": bool(periodic), "param": kind}
    if tangents:
        params["tangents"] = [xyz(t) if t is not None else None for t in tangents]
        params["tangent_flags"] = list(flags) if flags else [t is not None for t in tangents]
    else:
        if t0 is not None:
            params["start_tangent"] = xyz(t0)
        if t1 is not None:
            params["end_tangent"] = xyz(t1)
    return params


def add_interp(ctx, points, periodic=False, kind="chord", t0=None, t1=None, tangents=None, flags=None):
    if not service.have_kernel():
        raise CommandError("No kernel is installed.")
    params = interp_params(ctx, points, periodic, kind, t0, t1, tangents, flags)
    res = guard(service.make_through, ctx.d, params)
    src = {"op": "interpolate", "points": params["points"], "periodic": bool(periodic), "param": kind}
    for key in ("start_tangent", "end_tangent", "tangents", "tangent_flags"):
        if key in params:
            src[key] = params[key]
    h = new_curve(ctx, res["record"], res["audit"], src)
    say_audit(ctx, "CRVINTERP", res["record"], res["audit"])
    return h


@command("crvinterp", aliases=("crvthrough",), group="draw", label="Curve through Points", description="NURBS curve through points with optional end tangents, closed form and knot spacing.", menu="Draw > Curve > Interpolate Points")
def crvinterp_cmd(ctx):
    kind = str(ctx.mem.get("crvinterp_kind", "chord"))
    first = yield ctx.point("Specify first point", ["Knots"])
    while first.kind == "keyword":
        k = yield ctx.keyword("Knot spacing", ["Chord", "Centripetal", "Uniform"], kind.title())
        if k.kind in ("keyword", "enter"):
            kind = (k.value if k.kind == "keyword" else kind).lower()
            ctx.mem["crvinterp_kind"] = kind
        first = yield ctx.point("Specify first point", ["Knots"])
    if first.kind != "point":
        return
    pts = [xyz(first.value)]
    t0 = t1 = None
    periodic = False
    while True:
        opts = ["Undo", "Knots"]
        if len(pts) >= 2:
            opts += ["StartTangent", "EndTangent"]
        if len(pts) >= 3:
            opts.append("Close")
        r = yield ctx.point("Specify next point", opts, base=pts[-1])
        if r.kind == "enter":
            break
        if r.kind == "point":
            pts.append(xyz(r.value))
            continue
        if r.kind != "keyword":
            return
        if r.value == "Undo":
            if len(pts) > 1:
                pts.pop()
        elif r.value == "Close":
            periodic = True
            break
        elif r.value == "Knots":
            k = yield ctx.keyword("Knot spacing", ["Chord", "Centripetal", "Uniform"], kind.title())
            if k.kind in ("keyword", "enter"):
                kind = (k.value if k.kind == "keyword" else kind).lower()
                ctx.mem["crvinterp_kind"] = kind
        else:
            at_start = r.value == "StartTangent"
            anchor = pts[0] if at_start else pts[-1]
            t = yield ctx.point("Specify the %s tangent direction" % ("start" if at_start else "end"), base=anchor)
            if t.kind == "point":
                v = [t.value[i] - anchor[i] if i < len(t.value) else 0.0 for i in range(3)]
                if math.hypot(*v) <= ctx.d.tolerances["absolute"]:
                    ctx.say("A tangent needs a direction.")
                    continue
                if at_start:
                    t0 = v
                else:
                    t1 = v
    if len(pts) < 2:
        return
    add_interp(ctx, pts, periodic, kind, None if periodic else t0, None if periodic else t1)


@executes("crvinterp")
def crvinterp_exec(ctx, args):
    pts = args.get("points")
    if not pts:
        raise CommandError("Give points as a list of [x, y, z].")
    return {"handle": add_interp(ctx, pts, bool(args.get("periodic", False)), str(args.get("knots", "chord")), args.get("start_tangent"), args.get("end_tangent"), args.get("tangents"), args.get("tangent_flags"))}


def run_fit(ctx, e, tol, dmin, dmax, copy):
    if not 1 <= dmin <= dmax <= 25:
        raise CommandError("The degree range is from 1 to 25 with the minimum not above the maximum.")
    form = service.form_of(e)
    res = guard(service.worker, ctx.d, "curve_refit", {"curve": form.to_record(), "tol": tol, "deg_min": dmin, "deg_max": dmax})
    audit = service.audit_of(res)
    audit["within"] = bool(res.get("within"))
    h = put(ctx, e, res["curve"], audit, {"op": "fit", "tolerance": tol}, copy)
    say_audit(ctx, "CRVFIT", res["curve"], audit)
    if not res.get("within"):
        ctx.say("The fit stayed %s from the original, over the tolerance %s." % (ctx.fd(res["deviation"]), ctx.fd(tol)))
    return {"handle": h, "poles": len(res["curve"]["poles"]), "degree": res["curve"]["degree"], "deviation": res["deviation"], "within": bool(res.get("within"))}


@command("crvfit", group="modify", label="Fit Curve", description="Refit a curve within a tolerance, with fewer poles where the shape allows.", menu="Modify > Curve > Fit")
def crvfit_cmd(ctx):
    got = yield from select_curve(ctx)
    if not got:
        return
    e, _q = got
    tol = service.fit_tolerance(ctx.d)
    dmin, dmax, copy = 3, 8, False
    while True:
        r = yield ctx.keyword("Fit within %s, degree %d to %d" % (ctx.fd(tol), dmin, dmax), ["Tolerance", "MinDegree", "MaxDegree", "Copy", "Accept"], "Accept")
        if r.kind == "enter" or (r.kind == "keyword" and r.value == "Accept"):
            break
        if r.kind != "keyword":
            return
        if r.value == "Copy":
            copy = not copy
            ctx.say("Keep the input: %s." % ("Yes" if copy else "No"))
        elif r.value == "Tolerance":
            v = yield ctx.number("Specify fit tolerance", default=tol, positive=True)
            if v.kind == "number":
                tol = float(v.value)
        else:
            lo = r.value == "MinDegree"
            v = yield ctx.number("Enter the %s degree" % ("minimum" if lo else "maximum"), default=dmin if lo else dmax, integer=True, minimum=1, maximum=25)
            if v.kind == "number":
                if lo:
                    dmin = int(v.value)
                else:
                    dmax = int(v.value)
    run_fit(ctx, e, tol, dmin, max(dmax, dmin), copy)


@executes("crvfit")
def crvfit_exec(ctx, args):
    e = arg_curve(ctx, args)
    return run_fit(ctx, e, service.fit_tolerance(ctx.d, args.get("tolerance")), int(args.get("deg_min", 3)), int(args.get("deg_max", 8)), bool(args.get("copy", False)))


def run_rebuild(ctx, e, count, degree, keep_tangents, copy):
    form = service.form_of(e)
    res = guard(service.worker, ctx.d, "curve_rebuild", {"curve": form.to_record(), "count": int(count), "degree": int(degree), "keep_tangents": bool(keep_tangents)}, service.LONG)
    audit = service.audit_of(res)
    h = put(ctx, e, res["curve"], audit, {"op": "rebuild", "count": int(count), "degree": int(degree)}, copy)
    say_audit(ctx, "CRVREBUILD", res["curve"], audit)
    return {"handle": h, "poles": len(res["curve"]["poles"]), "degree": res["curve"]["degree"], "deviation": res["deviation"]}


@command("crvrebuild", group="modify", label="Rebuild Curve", description="Rebuild a curve with a chosen number of poles and degree.", menu="Modify > Curve > Rebuild")
def crvrebuild_cmd(ctx):
    got = yield from select_curve(ctx)
    if not got:
        return
    e, _q = got
    count, degree, keep, copy = max(len(e.poles), e.degree + 1), min(max(e.degree, 1), 5), False, False
    while True:
        r = yield ctx.keyword("Rebuild to %d points, degree %d" % (count, degree), ["Count", "Degree", "KeepTangents", "Copy", "Accept"], "Accept")
        if r.kind == "enter" or (r.kind == "keyword" and r.value == "Accept"):
            break
        if r.kind != "keyword":
            return
        if r.value == "Copy":
            copy = not copy
            ctx.say("Keep the input: %s." % ("Yes" if copy else "No"))
        elif r.value == "Count":
            v = yield ctx.number("Enter the point count", default=count, integer=True, minimum=2, maximum=5000)
            if v.kind == "number":
                count = int(v.value)
        elif r.value == "KeepTangents":
            keep = not keep
            ctx.say("Keep end tangents: %s." % ("Yes" if keep else "No"))
        else:
            v = yield ctx.number("Enter degree", default=degree, integer=True, minimum=1, maximum=25)
            if v.kind == "number":
                degree = int(v.value)
    run_rebuild(ctx, e, count, degree, keep, copy)


@executes("crvrebuild")
def crvrebuild_exec(ctx, args):
    e = arg_curve(ctx, args)
    return run_rebuild(ctx, e, args.get("count", len(e.poles)), args.get("degree", e.degree), args.get("keep_tangents", False), bool(args.get("copy", False)))


def run_degree(ctx, e, degree, copy):
    form = service.form_of(e)
    res = guard(service.worker, ctx.d, "curve_degree", {"curve": form.to_record(), "degree": int(degree)}, service.LONG)
    audit = service.audit_of(res)
    h = put(ctx, e, res["curve"], audit, {"op": "degree", "degree": int(degree)}, copy)
    say_audit(ctx, "CRVDEGREE", res["curve"], audit)
    return {"handle": h, "poles": len(res["curve"]["poles"]), "degree": res["curve"]["degree"], "deviation": res.get("deviation", 0.0)}


@command("crvdegree", group="modify", label="Change Curve Degree", description="Raise a curve's degree exactly or lower it within the document tolerance.", menu="Modify > Curve > Change Degree")
def crvdegree_cmd(ctx):
    got = yield from select_curve(ctx)
    if not got:
        return
    e, _q = got
    r = yield ctx.number("New degree <%d>" % e.degree, default=e.degree, integer=True, minimum=1, maximum=25)
    if r.kind in ("number", "enter"):
        run_degree(ctx, e, e.degree if r.kind == "enter" else int(r.value), False)


@executes("crvdegree")
def crvdegree_exec(ctx, args):
    return run_degree(ctx, arg_curve(ctx, args), args.get("degree", 3), bool(args.get("copy", False)))


def run_knot(ctx, e, mode, u, mult):
    form = service.form_of(e)
    if mode == "insert":
        try:
            form.insert_knot(float(u), int(mult))
        except FormError as err:
            raise CommandError(str(err))
        rec, audit = guard(service.checked_record, ctx.d, form)
        service.apply(ctx.d.modify(e.handle), rec, audit)
        ctx.say("CRVKNOT: knot inserted at %.6g; %d poles." % (float(u), len(rec["poles"])))
        return {"handle": e.handle, "poles": len(rec["poles"])}
    res = guard(service.worker, ctx.d, "curve_knot_remove", {"curve": form.to_record(), "u": float(u), "mult": int(mult)})
    if not res.get("removed"):
        raise CommandError("That knot cannot be removed without moving the curve by more than the tolerance.")
    audit = service.audit_of(res)
    service.apply(ctx.d.modify(e.handle), res["curve"], audit)
    ctx.say("CRVKNOT: knot removed; %d poles, deviation %s." % (len(res["curve"]["poles"]), ctx.fd(res["deviation"])))
    return {"handle": e.handle, "poles": len(res["curve"]["poles"]), "deviation": res["deviation"]}


@command("crvknot", group="modify", label="Insert or Remove Knot", description="Insert a knot at a picked point, or remove one within the document tolerance.", menu="Modify > Curve > Knots")
def crvknot_cmd(ctx):
    got = yield from select_curve(ctx)
    if not got:
        return
    e, _q = got
    mode = "insert"
    while True:
        msg = "Pick a point on the curve to %s a knot" % ("insert" if mode == "insert" else "remove")
        r = yield ctx.point(msg, ["Insert", "Remove"])
        if r.kind == "enter":
            return
        if r.kind == "keyword":
            mode = r.value.lower()
            continue
        if r.kind != "point":
            return
        e = ctx.d.get(e.handle)
        form = service.form_of(e)
        u = service.param_near(form, r.value)
        if mode == "remove":
            interior = [k for k in form.knots[1:-1]]
            if not interior:
                ctx.say("The curve has no interior knot.")
                continue
            u = min(interior, key=lambda k: abs(k - u))
            run_knot(ctx, e, "remove", u, max(form.mults[form.knots.index(u)] - 1, 0))
        else:
            run_knot(ctx, e, "insert", u, 1)


@executes("crvknot")
def crvknot_exec(ctx, args):
    e = arg_curve(ctx, args)
    mode = str(args.get("mode", "insert")).lower()
    if mode not in ("insert", "remove"):
        raise CommandError("mode is insert or remove.")
    if args.get("u") is None:
        raise CommandError("Give the knot parameter as u.")
    return run_knot(ctx, e, mode, args["u"], int(args.get("mult", 1 if mode == "insert" else 0)))


def run_simplify(ctx, e, tol):
    form = service.form_of(e)
    res = guard(service.worker, ctx.d, "curve_simplify", {"curve": form.to_record(), "tol": tol}, service.LONG)
    audit = service.audit_of(res)
    service.apply(ctx.d.modify(e.handle), res["curve"], audit)
    ctx.say("CRVSIMPLIFY: %d knots removed; %d poles, deviation %s." % (res.get("removed", 0), len(res["curve"]["poles"]), ctx.fd(res["deviation"])))
    return {"handle": e.handle, "removed": res.get("removed", 0), "poles": len(res["curve"]["poles"]), "deviation": res["deviation"]}


@command("crvsimplify", group="modify", label="Simplify Curve", description="Remove every knot that can go without moving the curve past the tolerance.", menu="Modify > Curve > Simplify")
def crvsimplify_cmd(ctx):
    got = yield from select_curve(ctx)
    if not got:
        return
    e, _q = got
    tol = service.fit_tolerance(ctx.d)
    r = yield ctx.number("Tolerance <%s>" % ctx.fd(tol), default=tol, positive=True)
    if r.kind in ("number", "enter"):
        run_simplify(ctx, e, tol if r.kind == "enter" else float(r.value))


@executes("crvsimplify")
def crvsimplify_exec(ctx, args):
    return run_simplify(ctx, arg_curve(ctx, args), service.fit_tolerance(ctx.d, args.get("tolerance")))


def run_periodic(ctx, e, periodic):
    form = service.form_of(e)
    res = guard(service.worker, ctx.d, "curve_periodic", {"curve": form.to_record(), "periodic": bool(periodic)})
    audit = service.audit_of(res)
    service.apply(ctx.d.modify(e.handle), res["curve"], audit)
    ctx.say("CRVPERIODIC: the curve is now %s." % ("periodic" if res["curve"]["periodic"] else "non-periodic"))
    return {"handle": e.handle, "periodic": res["curve"]["periodic"]}


@command("crvperiodic", group="modify", label="Make Periodic or Not", description="Turn a smooth closed curve into a periodic one, or a periodic curve into an ordinary closed one.", menu="Modify > Curve > Periodic")
def crvperiodic_cmd(ctx):
    got = yield from select_curve(ctx)
    if not got:
        return
    e, _q = got
    default = "NonPeriodic" if e.periodic else "Periodic"
    r = yield ctx.keyword("Make the curve", ["Periodic", "NonPeriodic"], default)
    if r.kind in ("keyword", "enter"):
        run_periodic(ctx, e, (r.value if r.kind == "keyword" else default) == "Periodic")


@executes("crvperiodic")
def crvperiodic_exec(ctx, args):
    return run_periodic(ctx, arg_curve(ctx, args), bool(args.get("periodic", True)))


def run_reverse(ctx, e):
    form = service.form_of(e)
    service.apply(ctx.d.modify(e.handle), form.reversed().to_record(), e.audit)
    ctx.say("CRVREVERSE: direction reversed.")
    return {"handle": e.handle}


@command("crvreverse", group="modify", label="Reverse Curve", description="Reverse the direction of NURBS curves.", menu="Modify > Curve > Reverse")
def crvreverse_cmd(ctx):
    sel = yield ctx.select("Select NURBS curves to reverse")
    if sel.kind != "selection":
        return
    made = 0
    for e in ctx.editable(sel.value):
        if e.kind == "nurbscurve":
            run_reverse(ctx, e)
            made += 1
    if not made:
        ctx.say("Select NURBS curves.")


@executes("crvreverse")
def crvreverse_exec(ctx, args):
    handles = [int(h) for h in args.get("handles") or ([args["handle"]] if args.get("handle") is not None else [])]
    if not handles:
        raise CommandError("Give handles.")
    return {"handles": [run_reverse(ctx, curve_of(ctx, h))["handle"] for h in handles]}


def run_sub(ctx, e, u0, u1, copy):
    form = service.form_of(e)
    lo, hi = form.domain()
    a, b = sorted((float(u0), float(u1)))
    if not (lo <= a < b <= hi) and not form.periodic:
        raise CommandError("The two parameters must lie on the curve and differ.")
    res = guard(service.worker, ctx.d, "curve_trim", {"curve": form.to_record(), "u0": a, "u1": b})
    audit = service.audit_of(res)
    h = put(ctx, e, res["curve"], audit, {"op": "subcurve", "u0": a, "u1": b}, copy)
    ctx.say("CRVSUB: sub-curve with %d poles." % len(res["curve"]["poles"]))
    return {"handle": h, "poles": len(res["curve"]["poles"])}


@command("crvsub", group="modify", label="Sub-curve", description="Keep the part of a curve between two picked points.", menu="Modify > Curve > Sub-curve")
def crvsub_cmd(ctx):
    got = yield from select_curve(ctx)
    if not got:
        return
    e, _q = got
    p0 = yield ctx.point("Specify the first point on the curve")
    if p0.kind != "point":
        return
    p1 = yield ctx.point("Specify the second point on the curve")
    if p1.kind != "point":
        return
    form = service.form_of(e)
    run_sub(ctx, e, service.param_near(form, p0.value), service.param_near(form, p1.value), False)


@executes("crvsub")
def crvsub_exec(ctx, args):
    e = arg_curve(ctx, args)
    form = service.form_of(e)
    if args.get("u0") is not None and args.get("u1") is not None:
        u0, u1 = args["u0"], args["u1"]
    elif args.get("p0") is not None and args.get("p1") is not None:
        u0, u1 = service.param_near(form, args["p0"]), service.param_near(form, args["p1"])
    else:
        raise CommandError("Give u0 and u1, or p0 and p1.")
    return run_sub(ctx, e, u0, u1, bool(args.get("copy", False)))


def run_blend(ctx, ea, end_a, eb, end_b, cont_a, cont_b, fa, fb):
    if ea.handle == eb.handle and end_a == end_b:
        raise CommandError("Pick two different curve ends.")
    res = guard(service.do_blend, ctx.d, service.form_of(ea), end_a, service.form_of(eb), end_b, cont_a, cont_b, fa, fb)
    src = {"op": "blend", "from": [ea.handle, end_a, level_of(cont_a)], "to": [eb.handle, end_b, level_of(cont_b)], "factors": [float(fa), float(fb)]}
    h = new_curve(ctx, res["record"], res["audit"], src, "Blend", ea)
    ctx.say("CRVBLEND: G%d to G%d blend of degree %d." % (level_of(cont_a), level_of(cont_b), res["record"]["degree"]))
    return h


@command("crvblend", group="draw", label="Blend Curve", description="Curve between two curve ends with position, tangent, curvature or curvature-change continuity at each end.", menu="Draw > Curve > Blend")
def crvblend_cmd(ctx):
    got = yield from select_curve(ctx, "Select the first curve near its end")
    if not got:
        return
    ea, qa = got
    got = yield from select_curve(ctx, "Select the second curve near its end")
    if not got:
        return
    eb, qb = got
    end_a = service.end_near(service.form_of(ea), qa)
    end_b = service.end_near(service.form_of(eb), qb)
    ca = int(ctx.mem.get("crvblend_a", 2))
    cb = int(ctx.mem.get("crvblend_b", 2))
    fa = fb = 1.0
    while True:
        r = yield ctx.keyword("Blend G%d to G%d, factors %.3g and %.3g" % (ca, cb, fa, fb), ["FirstContinuity", "SecondContinuity", "FirstShape", "SecondShape", "Accept"], "Accept")
        if r.kind == "enter" or (r.kind == "keyword" and r.value == "Accept"):
            break
        if r.kind != "keyword":
            return
        if r.value.endswith("Continuity"):
            c = yield ctx.keyword("Continuity", list(LEVEL_NAMES), "G%d" % (ca if r.value.startswith("First") else cb))
            if c.kind == "keyword":
                if r.value.startswith("First"):
                    ca = level_of(c.value)
                    ctx.mem["crvblend_a"] = ca
                else:
                    cb = level_of(c.value)
                    ctx.mem["crvblend_b"] = cb
        else:
            v = yield ctx.number("Shape factor", default=fa if r.value.startswith("First") else fb, positive=True)
            if v.kind == "number":
                if r.value.startswith("First"):
                    fa = float(v.value)
                else:
                    fb = float(v.value)
    run_blend(ctx, ea, end_a, eb, end_b, ca, cb, fa, fb)


@executes("crvblend")
def crvblend_exec(ctx, args):
    ea, eb = arg_curve(ctx, args, "first"), arg_curve(ctx, args, "second")
    end_a = arg_end(ctx, ea, args, "first_end", "first_point")
    end_b = arg_end(ctx, eb, args, "second_end", "second_point")
    h = run_blend(ctx, ea, end_a, eb, end_b, args.get("first_continuity", args.get("continuity", 2)), args.get("second_continuity", args.get("continuity", 2)), args.get("first_factor", 1.0), args.get("second_factor", 1.0))
    return {"handle": h}


def run_match(ctx, moving, which, target, target_end, cont, scale, refine, copy):
    if moving.handle == target.handle:
        raise CommandError("Pick two different curves.")
    res = guard(service.do_match, ctx.d, service.form_of(moving), which, service.form_of(target), target_end, cont, scale, refine)
    src = dict(moving.source)
    src["match"] = {"to": target.handle, "end": which, "target_end": target_end, "continuity": level_of(cont)}
    h = put(ctx, moving, res["record"], res["audit"], src, copy)
    ctx.say("CRVMATCH: matched to G%d%s." % (level_of(cont), "; %d knot(s) inserted" % res["audit"]["refined_knots"] if res["audit"].get("refined_knots") else ""))
    return {"handle": h, "refined_knots": res["audit"].get("refined_knots", 0)}


@command("crvmatch", group="modify", label="Match Curve", description="Change a curve end to meet another curve with position, tangent, curvature or curvature-change continuity.", menu="Modify > Curve > Match")
def crvmatch_cmd(ctx):
    got = yield from select_curve(ctx, "Select the curve to change near the end to match")
    if not got:
        return
    moving, qm = got
    got = yield from select_curve(ctx, "Select the curve to match to near its end")
    if not got:
        return
    target, qt = got
    which = service.end_near(service.form_of(moving), qm)
    t_end = service.end_near(service.form_of(target), qt)
    cont = int(ctx.mem.get("crvmatch_cont", 1))
    scale, refine, copy = 1.0, True, False
    while True:
        r = yield ctx.keyword("Match to G%d" % cont, ["Continuity", "Scale", "Refine", "Copy", "Accept"], "Accept")
        if r.kind == "enter" or (r.kind == "keyword" and r.value == "Accept"):
            break
        if r.kind != "keyword":
            return
        if r.value == "Continuity":
            c = yield ctx.keyword("Continuity", list(LEVEL_NAMES), "G%d" % cont)
            if c.kind == "keyword":
                cont = level_of(c.value)
                ctx.mem["crvmatch_cont"] = cont
        elif r.value == "Scale":
            v = yield ctx.number("Tangent length scale", default=scale, positive=True)
            if v.kind == "number":
                scale = float(v.value)
        elif r.value == "Refine":
            refine = not refine
            ctx.say("Refine by inserting knots: %s." % ("Yes" if refine else "No"))
        else:
            copy = not copy
            ctx.say("Keep the input: %s." % ("Yes" if copy else "No"))
    run_match(ctx, moving, which, target, t_end, cont, scale, refine, copy)


@executes("crvmatch")
def crvmatch_exec(ctx, args):
    moving, target = arg_curve(ctx, args, "handle"), arg_curve(ctx, args, "target")
    which = arg_end(ctx, moving, args, "end", "point")
    t_end = arg_end(ctx, target, args, "target_end", "target_point")
    return run_match(ctx, moving, which, target, t_end, args.get("continuity", 1), args.get("scale", 1.0), bool(args.get("refine", True)), bool(args.get("copy", False)))


def run_offset(ctx, e, distance, normal, tolerance=None):
    form = service.form_of(e)
    params = {"curve": form.to_record(), "distance": float(distance), "tol": service.fit_tolerance(ctx.d, tolerance)}
    if normal is not None:
        params["normal"] = xyz(normal)
    res = guard(service.worker, ctx.d, "curve_offset", params, service.LONG)
    audit = service.audit_of(res)
    audit["within"] = bool(res.get("within"))
    h = new_curve(ctx, res["curve"], audit, {"op": "offset", "of": e.handle, "distance": float(distance)}, "Offset", e)
    say_audit(ctx, "CRVOFFSET", res["curve"], audit)
    return {"handle": h, "poles": len(res["curve"]["poles"]), "deviation": res["deviation"], "within": bool(res.get("within"))}


@command("crvoffset", group="modify", label="Offset Curve", description="Offset a planar NURBS curve within its plane by a distance, to the side you pick.", menu="Modify > Curve > Offset")
def crvoffset_cmd(ctx):
    got = yield from select_curve(ctx)
    if not got:
        return
    e, _q = got
    dist = float(ctx.mem.get("crvoffset_dist", 1.0))
    r = yield ctx.distance("Offset distance <%s>" % ctx.fd(dist), default=dist, positive=True)
    if r.kind == "enter":
        pass
    elif r.kind == "distance" or r.kind == "number":
        dist = float(r.value)
    else:
        return
    ctx.mem["crvoffset_dist"] = dist
    side = yield ctx.point("Specify the side to offset to")
    if side.kind != "point":
        return
    sign = guard(offset_side, e, side.value)
    run_offset(ctx, e, sign * dist, None)


def offset_side(e, point) -> float:
    form = service.form_of(e)
    u = service.param_near(form, point)
    d = form.derivs(u, 1)
    pts = np.array(form.sample(8))
    c = pts.mean(axis=0)
    _u, s, vt = np.linalg.svd(pts - c)
    if s[-1] > 1e-7 * max(float(s[0]), 1e-300):
        raise FormError("The curve is not planar.")
    normal = vt[2]
    left = np.cross(normal, d[1])
    q = np.array([float(point[0]), float(point[1]), d[0][2]])
    side = float((q - d[0]) @ left)
    return 1.0 if side >= 0 else -1.0


@executes("crvoffset")
def crvoffset_exec(ctx, args):
    e = arg_curve(ctx, args)
    if args.get("distance") is None:
        raise CommandError("Give the offset distance.")
    dist = float(args["distance"])
    if args.get("side") is not None:
        dist = abs(dist) * guard(offset_side, e, args["side"])
    return run_offset(ctx, e, dist, args.get("normal"), args.get("tolerance"))


def run_extend(ctx, e, which, length, style, copy):
    if style not in STYLES:
        raise CommandError("Style is line, arc or smooth.")
    form = service.form_of(e)
    res = guard(service.worker, ctx.d, "curve_extend", {"curve": form.to_record(), "end": which, "length": float(length), "style": style})
    audit = service.audit_of(res)
    h = put(ctx, e, res["curve"], audit, {"op": "extend", "end": which, "length": float(length), "style": res.get("style_used", style)}, copy)
    ctx.say("CRVEXTEND: %s extension of %s%s." % (res.get("style_used", style), ctx.fd(float(length)), "" if res.get("style_used", style) == style else " (the end is straight, so a line was used)"))
    return {"handle": h, "style": res.get("style_used", style), "poles": len(res["curve"]["poles"])}


@command("crvextend", group="modify", label="Extend Curve", description="Extend a NURBS curve at one end by a length with a line, an arc or a smooth curve.", menu="Modify > Curve > Extend")
def crvextend_cmd(ctx):
    got = yield from select_curve(ctx, "Select the curve near the end to extend")
    if not got:
        return
    e, q = got
    which = service.end_near(service.form_of(e), q)
    style = str(ctx.mem.get("crvextend_style", "smooth"))
    length = float(ctx.mem.get("crvextend_len", 1.0))
    copy = False
    while True:
        r = yield ctx.keyword("Extend by %s with a %s curve" % (ctx.fd(length), style), ["Length", "Line", "Arc", "Smooth", "Copy", "Accept"], "Accept")
        if r.kind == "enter" or (r.kind == "keyword" and r.value == "Accept"):
            break
        if r.kind != "keyword":
            return
        if r.value == "Copy":
            copy = not copy
            ctx.say("Keep the input: %s." % ("Yes" if copy else "No"))
        elif r.value == "Length":
            v = yield ctx.distance("Specify the extension length", default=length, positive=True)
            if v.kind in ("distance", "number"):
                length = float(v.value)
                ctx.mem["crvextend_len"] = length
        else:
            style = r.value.lower()
            ctx.mem["crvextend_style"] = style
    run_extend(ctx, e, which, length, style, copy)


@executes("crvextend")
def crvextend_exec(ctx, args):
    e = arg_curve(ctx, args)
    return run_extend(ctx, e, arg_end(ctx, e, args), args.get("length", 0.0), str(args.get("style", "smooth")), bool(args.get("copy", False)))


def run_report(ctx, ea, end_a, eb, end_b):
    res = guard(service.measure, ctx.d, service.form_of(ea), end_a, service.form_of(eb), end_b)
    ctx.say("CRVCONT: %s. Position gap %.3e, tangent angle %.3e rad, curvature gap %.3e, third-derivative gap %.3e (relative)." % (res["level"], res["position_gap"], res["tangent_angle"], res["curvature_gap"], res["third_relative"]))
    return res


@command("crvcont", aliases=("crvreport",), group="inquiry", label="Curve Continuity Report", description="Measure position, tangent, curvature and curvature-change continuity where two curve ends meet.", menu="Tools > Inquiry > Curve Continuity", undoable=False)
def crvcont_cmd(ctx):
    got = yield from select_curve(ctx, "Select the first curve near the joint")
    if not got:
        return
    ea, qa = got
    got = yield from select_curve(ctx, "Select the second curve near the joint")
    if not got:
        return
    eb, qb = got
    run_report(ctx, ea, service.end_near(service.form_of(ea), qa), eb, service.end_near(service.form_of(eb), qb))


@executes("crvcont")
def crvcont_exec(ctx, args):
    ea, eb = arg_curve(ctx, args, "first"), arg_curve(ctx, args, "second")
    return run_report(ctx, ea, arg_end(ctx, ea, args, "first_end", "first_point"), eb, arg_end(ctx, eb, args, "second_end", "second_point"))
