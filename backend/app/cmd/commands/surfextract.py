import math

from app.cmd.commands.surfaces import GROUP, ask_style, guard, handles_of, keep_report
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.doc.kinds.nurbscurve import NurbsCurve
from app.nurbs3d import service
from app.solid import surfwork as sw
from app.solid import work

AXES = {"x": [1.0, 0.0, 0.0], "y": [0.0, 1.0, 0.0], "z": [0.0, 0.0, 1.0], "top": [0.0, 0.0, -1.0], "bottom": [0.0, 0.0, 1.0], "front": [0.0, 1.0, 0.0], "back": [0.0, -1.0, 0.0], "right": [-1.0, 0.0, 0.0], "left": [1.0, 0.0, 0.0]}
ISO_NAMES = {"u": "constant U", "v": "constant V"}


def vector_of(value, default="z") -> list:
    raw = default if value is None else value
    if isinstance(raw, str):
        word = raw.strip().lower()
        sign = -1.0 if word.startswith("-") else 1.0
        axis = AXES.get(word.lstrip("+-"))
        if axis is None:
            raise CommandError("The direction is three numbers, or one of x, y, z, top, bottom, front, back, right, left.")
        return [sign * c for c in axis]
    try:
        v = [float(c) for c in raw]
    except (TypeError, ValueError):
        raise CommandError("The direction needs three numbers.")
    if len(v) == 2:
        v.append(0.0)
    if len(v) != 3 or not all(math.isfinite(c) for c in v) or math.sqrt(sum(c * c for c in v)) <= 1e-12:
        raise CommandError("The direction needs three finite numbers that are not all zero.")
    return v


def point_of(value, what) -> list:
    try:
        q = [float(c) for c in value]
    except (TypeError, ValueError):
        raise CommandError("%s needs three numbers." % what)
    if len(q) == 2:
        q.append(0.0)
    if len(q) != 3 or not all(math.isfinite(c) for c in q):
        raise CommandError("%s needs three finite numbers." % what)
    return q


def sorted_handles(ctx, args) -> tuple:
    curves, bodies = handles_of(args, "curves"), handles_of(args, "targets")
    for h in handles_of(args):
        ent = ctx.d.get(h)
        if ent is None:
            raise CommandError("Object %s does not exist." % h)
        (bodies if ent.kind == "solidbody" else curves).append(h)
    return curves, bodies


def targets_of(ctx, args, bodies) -> tuple:
    d = ctx.d
    names, out = [], []
    for h in bodies:
        body = guard(sw.body_of, d, h)
        out.append({"id": guard(work.worker_id, d, body)})
        names.append(body.handle)
    by_body = {}
    for ref in args.get("faces") or []:
        body, face = guard(sw.face_ref, d, ref)
        if body.handle not in names:
            by_body.setdefault(body.handle, {"id": face["id"], "faces": []})["faces"].append(face["index"])
    out.extend(by_body.values())
    names.extend(by_body)
    if not out:
        raise CommandError("Give the surfaces or solids in targets, or face references in faces.")
    return out, names


def sources_of(ctx, args, curves) -> list:
    specs = guard(sw.curves_of, ctx.d, curves, args.get("edges"))
    if not specs:
        raise CommandError("Give the curves in curves, or edge references in edges.")
    return specs


def source_name(curves, index):
    return curves[index] if index is not None and 0 <= index < len(curves) else None


def add_curves(ctx, res, name, op, extra_of) -> list:
    made = []
    for item in res.get("curves") or []:
        got = service.from_mm(ctx.d, item)
        e = NurbsCurve(name=name(item) if callable(name) else name)
        e.set_record(got["curve"])
        e.audit = service.audit_of(got)
        e.source = {"op": op, **extra_of(item)}
        made.append(ctx.add(e))
    return made


def verdict(rep) -> str:
    return "within" if rep.get("within_tolerance") else "above"


def fmt_vec(v) -> str:
    return ",".join("%.4g" % c for c in v)


def missed_line(ctx, label, rep, curves):
    missed = rep.get("missed") or []
    if missed:
        named = [str(source_name(curves, i)) for i in missed if source_name(curves, i) is not None]
        ctx.say("%s: %d source curve(s) did not reach the surface%s." % (label, len(missed), (": " + ", ".join(named)) if named else ""))


def do_project(ctx, args):
    curves, bodies = sorted_handles(ctx, args)
    specs = sources_of(ctx, args, curves)
    targets, names = targets_of(ctx, args, bodies)
    vec = vector_of(args.get("direction"))
    res = guard(sw.call, ctx.d, "surf_project", {"targets": targets, "curves": specs, "direction": vec, "join": bool(args.get("join", True)), "exact": bool(args.get("exact", False))})
    rep = res["report"]
    if not res["curves"]:
        raise CommandError("CRVPROJECT: none of the %d curve(s) meets the surface along the direction %s, so nothing was made. Check the direction, or move the curves over the surface." % (rep["sources"], fmt_vec(rep["direction"])))
    made = add_curves(ctx, res, "Projected curve", "project", lambda it: {"from": source_name(curves, it.get("source")), "on": names, "direction": rep["direction"]})
    ctx.say("CRVPROJECT: %d curve(s) made from %d source curve(s) on %d object(s) along %s." % (len(made), rep["sources"], len(names), fmt_vec(rep["direction"])))
    ctx.say("Largest distance from the surface %.3g mm at %d samples per curve, %s the tolerance %.3g mm; largest drift off the direction %.3g mm." % (rep["max_deviation"], rep["samples_per_curve"], verdict(rep), rep["tol"], rep["max_direction_error"]))
    missed_line(ctx, "CRVPROJECT", rep, curves)
    keep_report(ctx, rep)
    return {"handles": made, "count": len(made), "report": rep}


def do_pull(ctx, args):
    curves, bodies = sorted_handles(ctx, args)
    specs = sources_of(ctx, args, curves)
    targets, names = targets_of(ctx, args, bodies)
    params = {"targets": targets, "curves": specs, "join": bool(args.get("join", True))}
    if args.get("max_distance") is not None:
        try:
            limit = float(args["max_distance"])
        except (TypeError, ValueError):
            raise CommandError("The largest pull distance must be a number.")
        if not math.isfinite(limit) or limit <= 0:
            raise CommandError("The largest pull distance must be positive.")
        params["max_distance"] = limit * sw.scale(ctx.d)
    res = guard(sw.call, ctx.d, "surf_pull", params)
    rep = res["report"]
    if not res["curves"]:
        raise CommandError("CRVPULL: no point of the %d curve(s) has a closest point inside the surface along its normal, so nothing was made. The curves lie beyond the surface edges%s." % (rep["sources"], " or farther than the largest pull distance" if "max_distance" in params else ""))
    made = add_curves(ctx, res, "Pulled curve", "pull", lambda it: {"from": source_name(curves, it.get("source")), "on": names})
    ctx.say("CRVPULL: %d curve(s) made from %d source curve(s) on %d object(s), pulled up to %.4g mm along the surface normals." % (len(made), rep["sources"], len(names), rep["max_pull_distance"]))
    ctx.say("Largest distance from the surface %.3g mm at %d samples per curve and from the closest points %.3g mm, %s the tolerance %.3g mm; largest angle to the normal %.3g rad." % (rep["max_deviation"], rep["samples_per_curve"], rep["max_pull_error"], verdict(rep), rep["tol"], rep["max_normal_angle"]))
    missed_line(ctx, "CRVPULL", rep, curves)
    keep_report(ctx, rep)
    return {"handles": made, "count": len(made), "report": rep}


def do_contour(ctx, args):
    d = ctx.d
    s = sw.scale(d)
    _curves, bodies = sorted_handles(ctx, args)
    targets, names = targets_of(ctx, args, bodies)
    params = {"targets": targets, "direction": vector_of(args.get("direction")), "base": sw.p3(point_of(args.get("base") or [0, 0, 0], "The base point"), s), "join": bool(args.get("join", True)), "exact": bool(args.get("exact", False))}
    if args.get("spacing") is not None:
        try:
            spacing = float(args["spacing"])
        except (TypeError, ValueError):
            raise CommandError("The spacing must be a number.")
        if not math.isfinite(spacing) or spacing <= 0:
            raise CommandError("The spacing must be positive.")
        params["spacing"] = spacing * s
    if args.get("count") is not None:
        try:
            params["count"] = int(args["count"])
        except (TypeError, ValueError):
            raise CommandError("The count must be a whole number.")
    if "spacing" not in params and "count" not in params:
        raise CommandError("Give a spacing between the planes, or a count of planes.")
    res = guard(sw.call, d, "surf_contour", params)
    rep = res["report"]
    lo, hi = rep["extent"]
    if not res["curves"]:
        raise CommandError("SRFCONTOUR: none of the %d plane(s) cuts the object, so nothing was made. The object runs from %.4g to %.4g mm from the base point along %s; the planes were placed from %.4g to %.4g mm." % (rep["plane_count"], lo, hi, fmt_vec(rep["direction"]), rep["planes"][0]["offset"] if rep["planes"] else 0.0, rep["planes"][-1]["offset"] if rep["planes"] else 0.0))
    made = add_curves(ctx, res, "Contour curve", "contour", lambda it: {"on": names, "plane": it.get("plane"), "offset": it.get("offset"), "direction": rep["direction"]})
    empty = rep.get("empty_planes") or []
    ctx.say("SRFCONTOUR: %d curve(s) on %d of %d plane(s) spaced %.6g mm along %s, from %.6g to %.6g mm from the base point." % (len(made), rep["plane_count"] - len(empty), rep["plane_count"], rep["spacing"], fmt_vec(rep["direction"]), rep["planes"][0]["offset"], rep["planes"][-1]["offset"]))
    ctx.say("Largest distance from the planes %.3g mm and from the object %.3g mm at %d samples per curve, %s the tolerance %.3g mm." % (rep["max_plane_distance"], rep["max_deviation"], rep["samples_per_curve"], verdict(rep), rep["tol"]))
    if empty:
        ctx.say("SRFCONTOUR: %d plane(s) did not cut the object." % len(empty))
    keep_report(ctx, rep)
    return {"handles": made, "count": len(made), "report": rep}


def iso_face(ctx, args) -> tuple:
    d = ctx.d
    handles = handles_of(args)
    picked = list(ctx.doc.subselection.get("faces") or [])
    if handles:
        body = guard(sw.body_of, d, handles[0])
        if args.get("face") is not None or args.get("face_index") is not None:
            return guard(sw.face_ref, d, {"body": body.handle, "face": args.get("face"), "face_index": args.get("face_index")})
        mine = [f for f in picked if f["body"] == body.handle]
        if mine:
            return guard(sw.face_ref, d, {"body": body.handle, "face": mine[0]["face"]})
        return body, {"id": guard(work.worker_id, d, body)}
    if picked:
        return guard(sw.face_ref, d, {"body": picked[0]["body"], "face": picked[0]["face"]})
    raise CommandError("Give the handle of a surface, or select a face first.")


def number_list(value, what) -> list:
    raw = value if isinstance(value, (list, tuple)) else [value]
    try:
        out = [float(c) for c in raw]
    except (TypeError, ValueError):
        raise CommandError("%s must be a number or a list of numbers." % what)
    if not out or not all(math.isfinite(c) for c in out):
        raise CommandError("%s must be finite." % what)
    return out


def do_isocurve(ctx, args):
    d = ctx.d
    body, face = iso_face(ctx, args)
    which = str(args.get("direction", "both")).lower()
    if which not in ("u", "v", "both"):
        raise CommandError("The direction is u, v or both.")
    params = {"face": face, "direction": which}
    if args.get("knots"):
        params["knots"] = True
    elif args.get("point") is not None:
        params["point"] = sw.p3(point_of(args["point"], "The point"), sw.scale(d))
    else:
        for key in ("u", "v"):
            if args.get(key) is not None:
                params[key] = number_list(args[key], "The %s parameter" % key.upper())
        if "u" not in params and "v" not in params:
            raise CommandError("Give a point on the surface, a u or v parameter, or knots to extract every isocurve at the knots.")
        params["normalized"] = bool(args.get("normalized", False))
    res = guard(sw.call, d, "surf_isocurve", params)
    rep = res["report"]
    if not res["curves"]:
        raise CommandError("SRFISOCURVE: no isocurve crosses the face at the asked parameter(s), so nothing was made. The trimmed face spans U %.6g to %.6g and V %.6g to %.6g." % tuple(rep["uv_range"]))
    made = add_curves(ctx, res, lambda it: "Isocurve %s" % it["dir"].upper(), "isocurve", lambda it: {"from": body.handle, "face": rep["face"], "dir": it["dir"], "param": it["param"], "range": it["range"]})
    rng = rep["uv_range"]
    ctx.say("SRFISOCURVE: %d curve(s) on face %d of %s: %d at constant U and %d at constant V (U %.6g to %.6g, V %.6g to %.6g)." % (len(made), rep["face"] + 1, body.name or "the surface", rep["u_curves"], rep["v_curves"], rng[0], rng[1], rng[2], rng[3]))
    if rep.get("mode") == "point":
        ctx.say("The point is %.3g mm from the surface, at U %.6g, V %.6g." % (rep["point_distance"], rep["uv"][0], rep["uv"][1]))
    elif rep.get("mode") == "parameter":
        ctx.say("Parameters: %s." % ", ".join("%s = %.6g" % (ISO_NAMES[c["dir"]], c["param"]) for c in res["curves"][:12]))
    ctx.say("Largest distance from the surface %.3g mm and largest parameter error %.3g, %s the tolerance %.3g mm." % (rep["max_deviation"], rep["max_param_error"], verdict(rep), rep["tol"]))
    if rep.get("empty"):
        ctx.say("SRFISOCURVE: %d asked isocurve(s) lie outside the trimmed face." % len(rep["empty"]))
    keep_report(ctx, rep)
    return {"handles": made, "count": len(made), "report": rep, "curves": [{"handle": h, "dir": c["dir"], "param": c["param"], "range": c["range"]} for h, c in zip(made, res["curves"])]}


def pick_handles(ctx, message):
    sel = yield ctx.select(message)
    if sel.kind != "selection" or not sel.value:
        return None
    return [int(h) for h in sel.value]


def split_kinds(ctx, handles) -> tuple:
    curves, bodies = [], []
    for h in handles:
        ent = ctx.d.get(h)
        if ent is not None:
            (bodies if ent.kind == "solidbody" else curves).append(h)
    return curves, bodies


def pick_sources(ctx, verb):
    first = yield from pick_handles(ctx, "Select the curves to %s" % verb)
    if not first:
        return None
    curves, bodies = split_kinds(ctx, first)
    if not curves:
        ctx.say("Select at least one curve.")
        return None
    if not bodies:
        second = yield from pick_handles(ctx, "Select the surfaces or solids to %s onto" % verb)
        if not second:
            return None
        bodies = split_kinds(ctx, second)[1]
        if not bodies:
            ctx.say("Select at least one surface or solid.")
            return None
    return curves, bodies


def ask_direction(ctx):
    r = yield from ask_style(ctx, "Direction", ["Top", "Front", "Right", "Vector"], "Top")
    if r is None:
        return None
    if r != "Vector":
        return AXES[r.lower()]
    a = yield ctx.point("Specify the start of the direction")
    if a.kind != "point":
        return None
    b = yield ctx.point("Specify the end of the direction", base=a.value)
    if b.kind != "point":
        return None
    pa, pb = point_of(a.value, "The start"), point_of(b.value, "The end")
    return [pb[i] - pa[i] for i in range(3)]


@command("crvproject", aliases=("projectcrv",), group=GROUP, label="Project Curves", description="Project curves onto surfaces or solids along a direction and keep the result as NURBS curves.", menu="Draw > Curve > Project onto Surface")
def crvproject_cmd(ctx):
    picked = yield from pick_sources(ctx, "project")
    if not picked:
        return
    vec = yield from ask_direction(ctx)
    if vec is None:
        return
    do_project(ctx, {"curves": picked[0], "targets": picked[1], "direction": vec})


@executes("crvproject")
def crvproject_exec(ctx, args):
    return do_project(ctx, args)


@command("crvpull", aliases=("pullcrv",), group=GROUP, label="Pull Curves", description="Pull curves onto surfaces or solids along the surface normals, to the closest points, and keep the result as NURBS curves.", menu="Draw > Curve > Pull onto Surface")
def crvpull_cmd(ctx):
    picked = yield from pick_sources(ctx, "pull")
    if not picked:
        return
    do_pull(ctx, {"curves": picked[0], "targets": picked[1]})


@executes("crvpull")
def crvpull_exec(ctx, args):
    return do_pull(ctx, args)


@command("srfcontour", aliases=("contourcrv",), group=GROUP, label="Contour Curves", description="Section curves of surfaces or solids on parallel planes from a base point along a direction, by spacing or by count.", menu="Draw > Curve > Contour")
def srfcontour_cmd(ctx):
    targets = yield from pick_handles(ctx, "Select the surfaces or solids to contour")
    if not targets:
        return
    a = yield ctx.point("Specify the base point")
    if a.kind != "point":
        return
    b = yield ctx.point("Specify a point in the direction across the planes", base=a.value)
    if b.kind != "point":
        return
    base, far = point_of(a.value, "The base point"), point_of(b.value, "The direction point")
    how = yield from ask_style(ctx, "Planes by", ["Spacing", "Count"], "Spacing")
    if how is None:
        return
    args = {"targets": targets, "base": base, "direction": [far[i] - base[i] for i in range(3)]}
    if how == "Count":
        n = yield ctx.number("Specify the number of planes", integer=True, minimum=1, maximum=1000)
        if n.kind != "number":
            return
        args["count"] = int(n.value)
    else:
        gap = yield ctx.distance("Specify the spacing between the planes", positive=True)
        if gap.kind != "number":
            return
        args["spacing"] = gap.value
    do_contour(ctx, args)


@executes("srfcontour")
def srfcontour_exec(ctx, args):
    return do_contour(ctx, args)


@command("srfisocurve", aliases=("isocurve", "extractisocurve"), group=GROUP, label="Extract Isocurves", description="Extract the constant U or constant V curve of a surface at a picked point or a parameter, or every isocurve at the surface knots.", menu="Draw > Curve > Extract Isocurve")
def srfisocurve_cmd(ctx):
    sel = yield ctx.select("Select a surface", pick_one=True)
    if sel.kind != "selection" or not sel.value:
        return
    which = yield from ask_style(ctx, "Direction", ["U", "V", "Both"], "Both")
    if which is None:
        return
    where = yield from ask_style(ctx, "Extract at", ["Point", "Knots"], "Point")
    if where is None:
        return
    args = {"handle": int(sel.value[0]), "direction": which.lower()}
    if where == "Knots":
        args["knots"] = True
    else:
        q = yield ctx.point("Specify a point on the surface")
        if q.kind != "point":
            return
        args["point"] = list(q.value)
    do_isocurve(ctx, args)


@executes("srfisocurve")
def srfisocurve_exec(ctx, args):
    return do_isocurve(ctx, args)
