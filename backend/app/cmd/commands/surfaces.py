import math

from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.solid import surfwork as sw
from app.solid import work
from app.solid.work import SolidError

BOOL_OPS = {"fuse": "UNION", "cut": "SUBTRACT", "common": "INTERSECT"}
OP_WORDS = {"union": "fuse", "add": "fuse", "fuse": "fuse", "subtract": "cut", "cut": "cut", "intersect": "common", "common": "common"}
GROUP = "solids"


def guard(fn, *a, **k):
    try:
        return fn(*a, **k)
    except SolidError as err:
        raise CommandError(str(err))


def handles_of(args, key="handles") -> list:
    value = args.get(key)
    if value is None and key == "handles" and args.get("handle") is not None:
        value = [args["handle"]]
    if isinstance(value, (int, str)):
        value = [value]
    return [int(h) for h in value or []]


def positive(value, what):
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise CommandError("%s must be a number." % what)
    if not math.isfinite(v) or v <= 0:
        raise CommandError("%s must be positive and finite." % what)
    return v


def bounded(args, key, default, low, high, what):
    raw = args.get(key, default)
    try:
        v = int(raw)
    except (TypeError, ValueError):
        raise CommandError("%s must be a whole number from %d to %d." % (what, low, high))
    if not low <= v <= high:
        raise CommandError("%s must be from %d to %d; %s is out of range." % (what, low, high, raw))
    return v


def to_mm(ctx, value, what, minimum_positive=True):
    v = positive(value, what) if minimum_positive else float(value)
    return v * sw.scale(ctx.d)


def keep_report(ctx, report):
    ctx.mem["surface_report"] = sw.compact(report or {})
    ctx.mem["surface_seq"] = ctx.mem.get("surface_seq", 0) + 1


def announce(ctx, label, res):
    rep = res.get("report") or {}
    ctx.say("%s: %s." % (label, sw.surface_label(res.get("summary") or {})))
    line = sw.audit_line(rep)
    if line:
        ctx.say(line)
    keep_report(ctx, rep)


def curve_args(ctx, args, key="handles", edges_key="edges") -> list:
    found = sw.curves_of(ctx.d, handles_of(args, key), args.get(edges_key))
    if not found:
        raise CommandError("Give the curves in %s or edge references in %s." % (key, edges_key))
    return found


def sub_edges(ctx, args, key="edges") -> list:
    given = args.get(key)
    if given:
        return list(given)
    return list(ctx.doc.subselection.get("edges") or [])


def sub_faces(ctx, args, key="faces") -> list:
    given = args.get(key)
    if given:
        return list(given)
    return list(ctx.doc.subselection.get("faces") or [])


def curve_pick(ctx, message, minimum=1):
    sel = yield ctx.select(message)
    if sel.kind != "selection":
        return None
    handles = [int(h) for h in sel.value]
    if len(handles) < minimum:
        ctx.say("Select at least %d curve(s)." % minimum)
        return None
    return handles


def ask_style(ctx, message, options, default):
    r = yield ctx.keyword(message, options, default=default)
    if r.kind == "keyword":
        return r.value
    return default if r.kind in ("none", "enter") or r.from_default else None


@command("srfloft", aliases=("surfloft",), group=GROUP, label="Loft Surface", description="Surface through two or more curves in the order they are selected.", menu="Draw > Modeling > Surface > Loft")
def srfloft_cmd(ctx):
    handles = yield from curve_pick(ctx, "Select curves in order", 2)
    if not handles:
        return
    style = yield from ask_style(ctx, "Style", ["Normal", "Ruled", "Closed"], "Normal")
    if style is None:
        return
    do_loft(ctx, {"handles": handles, "ruled": style == "Ruled", "closed": style == "Closed"})


def do_loft(ctx, args):
    curves = curve_args(ctx, args, "handles", "edges")
    res = guard(sw.call, ctx.d, "surf_loft", {"sections": curves, "ruled": bool(args.get("ruled")), "closed": bool(args.get("closed")), "smooth": bool(args.get("smooth", not args.get("ruled"))), "max_degree": int(args.get("max_degree", 8))})
    body = guard(sw.add_result, ctx, res, "Loft surface", "loft")
    announce(ctx, "SRFLOFT", res)
    return {"handle": body.handle, "report": res["report"]}


@executes("srfloft")
def srfloft_exec(ctx, args):
    return do_loft(ctx, args)


@command("srfsweep", aliases=("surfsweep",), group=GROUP, label="Sweep Surface", description="Surface of profile curves along one rail, or between two rails with a scaling law.", menu="Draw > Modeling > Surface > Sweep")
def srfsweep_cmd(ctx):
    rail = yield ctx.select("Select the rail curve", pick_one=True)
    if rail.kind != "selection" or not rail.value:
        return
    prof = yield from curve_pick(ctx, "Select profile curves")
    if not prof:
        return
    second = yield ctx.select("Select the second rail or press Enter for one rail", pick_one=True)
    rails = [int(h) for h in second.value] if second.kind == "selection" else []
    do_sweep(ctx, {"rail": int(rail.value[0]), "profiles": prof, "rail2": rails[0] if rails else None})


def do_sweep(ctx, args):
    d = ctx.d
    rail_edges = args.get("rail_edge")
    rail = sw.curves_of(d, [args["rail"]] if args.get("rail") is not None else [], [rail_edges] if rail_edges else [])
    if not rail:
        raise CommandError("Give the rail as rail (a curve handle) or rail_edge.")
    r2 = args.get("rail2")
    r2e = args.get("rail2_edge")
    rail2 = sw.curves_of(d, [r2] if r2 is not None else [], [r2e] if r2e else [])
    profiles = sw.curves_of(d, handles_of(args, "profiles"), args.get("profile_edges"))
    if not profiles:
        raise CommandError("Give the profile curves in profiles.")
    params = {"rail": rail[0], "profiles": profiles, "frame": str(args.get("frame", "freeform")), "corner": str(args.get("corner", "right")), "correct": bool(args.get("correct", False))}
    if args.get("axis") is not None:
        params["axis"] = [float(v) for v in args["axis"]]
    if rail2:
        params["rail2"] = rail2[0]
    res = guard(sw.call, d, "surf_sweep", params)
    body = guard(sw.add_result, ctx, res, "Sweep surface", "sweep")
    announce(ctx, "SRFSWEEP", res)
    dev = res["report"].get("rail_deviation")
    if dev:
        limit = res["report"]["tol"]
        ctx.say("Distance of the surface from the rails: %s mm (%s the tolerance)." % (", ".join("%.3g" % v for v in dev), "above" if max(dev) > limit else "within"))
    return {"handle": body.handle, "report": res["report"]}


@executes("srfsweep")
def srfsweep_exec(ctx, args):
    return do_sweep(ctx, args)


@command("srfnetwork", aliases=("surfnetwork",), group=GROUP, label="Network Surface", description="Surface through a network of curves across each other.", menu="Draw > Modeling > Surface > Network")
def srfnetwork_cmd(ctx):
    u = yield from curve_pick(ctx, "Select the curves in the first direction", 2)
    if not u:
        return
    v = yield from curve_pick(ctx, "Select the curves in the second direction", 2)
    if not v:
        return
    do_network(ctx, {"u": u, "v": v})


def do_network(ctx, args):
    us = sw.curves_of(ctx.d, handles_of(args, "u"), args.get("u_edges"))
    vs = sw.curves_of(ctx.d, handles_of(args, "v"), args.get("v_edges"))
    if len(us) < 2 or len(vs) < 2:
        raise CommandError("A network needs at least two curves in each direction.")
    res = guard(sw.call, ctx.d, "surf_network", {"u": us, "v": vs, "degree": bounded(args, "degree", 3, 1, 8, "The degree"), "points": bounded(args, "points", 20, 2, 2000, "The point count"), "iterations": bounded(args, "iterations", 3, 1, 10, "The iteration count")})
    body = guard(sw.add_result, ctx, res, "Network surface", "network")
    announce(ctx, "SRFNETWORK", res)
    rep = res["report"]
    ctx.say("Largest distance of the surface from the curves: %.3g mm (%s)." % (rep.get("curve_deviation", 0.0), "within" if rep.get("within_tolerance") else "above the tolerance"))
    return {"handle": body.handle, "report": rep}


@executes("srfnetwork")
def srfnetwork_exec(ctx, args):
    return do_network(ctx, args)


@command("srfpatch", aliases=("surfpatch",), group=GROUP, label="Patch Surface", description="Fitted surface across curves and points, optionally matching a neighbouring surface at an edge.", menu="Draw > Modeling > Surface > Patch")
def srfpatch_cmd(ctx):
    handles = yield from curve_pick(ctx, "Select boundary curves")
    if not handles:
        return
    do_patch(ctx, {"curves": handles})


def do_patch(ctx, args):
    d = ctx.d
    s = sw.scale(d)
    curves = sw.curves_of(d, handles_of(args, "curves"), args.get("curve_edges"))
    supports = []
    for item in args.get("supports") or []:
        side = guard(sw.side_of, d, item)
        supports.append({"face": side["face"], "edge": side["edge"], "order": str(item.get("order", "g1"))})
    points = [sw.p3(q, s) for q in args.get("points") or []]
    if not (curves or points or supports):
        raise CommandError("Give curves, points or supports for the patch.")
    params = {"curves": curves, "points": points, "supports": supports, "degree": bounded(args, "degree", 3, 1, 8, "The degree"), "samples": bounded(args, "samples", 15, 2, 2000, "The sample count"), "iterations": bounded(args, "iterations", 3, 1, 10, "The iteration count"), "segments": bounded(args, "segments", 9, 1, 64, "The segment count"), "order": str(args.get("order", "g0"))}
    res = guard(sw.call, d, "surf_patch", params)
    body = guard(sw.add_result, ctx, res, "Patch surface", "patch")
    announce(ctx, "SRFPATCH", res)
    rep = res["report"]
    ctx.say("Fit errors: G0 %.3g mm, G1 %.3g rad." % (rep.get("g0_error", 0.0), rep.get("g1_error", 0.0)))
    return {"handle": body.handle, "report": rep}


@executes("srfpatch")
def srfpatch_exec(ctx, args):
    return do_patch(ctx, args)


@command("srfextrude", aliases=("surfextrude",), group=GROUP, label="Extrude Curve", description="Surface swept straight from a curve.", menu="Draw > Modeling > Surface > Extrude Curve")
def srfextrude_cmd(ctx):
    handles = yield from curve_pick(ctx, "Select curves to extrude")
    if not handles:
        return
    h = yield ctx.distance("Specify height", positive=False)
    if h.kind != "number":
        return
    cap = yield from ask_style(ctx, "Cap the ends", ["No", "Yes"], "No")
    if cap is None:
        return
    do_extrude(ctx, {"handles": handles, "height": h.value, "cap": cap == "Yes"})


def do_extrude(ctx, args):
    d = ctx.d
    s = sw.scale(d)
    if args.get("vector") is not None:
        v = [float(c) * s for c in args["vector"]]
        v += [0.0] * (3 - len(v))
    else:
        v = [0.0, 0.0, float(args.get("height", 0)) * s]
    if math.hypot(*v) <= 1e-9:
        raise CommandError("Give a height or a vector that is not zero.")
    curves = curve_args(ctx, args, "handles", "edges")
    made = []
    for spec in curves:
        res = guard(sw.call, d, "surf_extrude", {"curve": spec, "vector": v, "cap": bool(args.get("cap"))})
        body = guard(sw.add_result, ctx, res, "Extruded surface", "extrude_curve")
        announce(ctx, "SRFEXTRUDE", res)
        made.append((body.handle, res["report"]))
    return {"handles": [h for h, _r in made], "report": made[-1][1]}


@executes("srfextrude")
def srfextrude_exec(ctx, args):
    return do_extrude(ctx, args)


@command("srfrevolve", aliases=("surfrevolve",), group=GROUP, label="Revolve Curve", description="Surface turned from a curve about an axis.", menu="Draw > Modeling > Surface > Revolve Curve")
def srfrevolve_cmd(ctx):
    handles = yield from curve_pick(ctx, "Select curves to revolve")
    if not handles:
        return
    a = yield ctx.point("Specify the start of the axis")
    if a.kind != "point":
        return
    b = yield ctx.point("Specify the end of the axis", base=a.value)
    if b.kind != "point":
        return
    deg = yield ctx.number("Specify the angle in degrees <360>", default=360.0)
    if deg.kind != "number":
        return
    do_revolve(ctx, {"handles": handles, "axis": [list(a.value), list(b.value)], "degrees": deg.value})


def do_revolve(ctx, args):
    d = ctx.d
    s = sw.scale(d)
    axis = args.get("axis")
    if not axis or len(axis) != 2:
        raise CommandError("Give axis as two points.")
    curves = curve_args(ctx, args, "handles", "edges")
    made = []
    for spec in curves:
        res = guard(sw.call, d, "surf_revolve", {"curve": spec, "axis": [sw.p3(axis[0], s), sw.p3(axis[1], s)], "degrees": float(args.get("degrees", 360.0))})
        body = guard(sw.add_result, ctx, res, "Revolved surface", "revolve_curve")
        announce(ctx, "SRFREVOLVE", res)
        made.append((body.handle, res["report"]))
    return {"handles": [h for h, _r in made], "report": made[-1][1]}


@executes("srfrevolve")
def srfrevolve_exec(ctx, args):
    return do_revolve(ctx, args)


@command("srfplanar", aliases=("surfplanar",), group=GROUP, label="Planar Surface", description="Flat surface inside closed planar curves; inner curves become holes.", menu="Draw > Modeling > Surface > Planar")
def srfplanar_cmd(ctx):
    handles = yield from curve_pick(ctx, "Select closed planar curves")
    if not handles:
        return
    do_planar(ctx, {"handles": handles})


def do_planar(ctx, args):
    curves = curve_args(ctx, args, "handles", "edges")
    res = guard(sw.call, ctx.d, "surf_planar", {"curves": curves})
    body = guard(sw.add_result, ctx, res, "Planar surface", "planar")
    announce(ctx, "SRFPLANAR", res)
    return {"handle": body.handle, "report": res["report"]}


@executes("srfplanar")
def srfplanar_exec(ctx, args):
    return do_planar(ctx, args)


@command("srfedge", aliases=("surfedge",), group=GROUP, label="Surface from Edge Curves", description="Surface filling two, three or four edge curves.", menu="Draw > Modeling > Surface > Edge Curves")
def srfedge_cmd(ctx):
    handles = yield from curve_pick(ctx, "Select two to four edge curves", 2)
    if not handles:
        return
    do_edge(ctx, {"handles": handles})


def do_edge(ctx, args):
    curves = curve_args(ctx, args, "handles", "edges")
    if not 2 <= len(curves) <= 4:
        raise CommandError("Give two, three or four edge curves.")
    res = guard(sw.call, ctx.d, "surf_edge", {"curves": curves, "style": str(args.get("style", "curved"))})
    body = guard(sw.add_result, ctx, res, "Edge surface", "edge_surface")
    announce(ctx, "SRFEDGE", res)
    return {"handle": body.handle, "report": res["report"]}


@executes("srfedge")
def srfedge_exec(ctx, args):
    return do_edge(ctx, args)


def two_sides(ctx, args, first="a", second="b"):
    a, b = args.get(first), args.get(second)
    if not a or not b:
        edges = list(ctx.doc.subselection.get("edges") or [])
        faces = list(ctx.doc.subselection.get("faces") or [])
        if len(edges) < 2:
            raise CommandError("Select two surface edges first, one on each surface, or give %s and %s." % (first, second))
        a = a or {"body": edges[0]["body"], "edge": edges[0]["edge"]}
        b = b or {"body": edges[1]["body"], "edge": edges[1]["edge"]}
        for ref in (a, b):
            for f in faces:
                if f["body"] == ref["body"] and "face" not in ref:
                    ref["face"] = f["face"]
    return guard(sw.side_of, ctx.d, a), guard(sw.side_of, ctx.d, b)


@command("srfblend", aliases=("surfblend",), group=GROUP, label="Blend Surface", description="Surface joining two surface edges with G0, G1 or G2 continuity at each end; select the two edges first.", menu="Draw > Modeling > Surface > Blend")
def srfblend_cmd(ctx):
    two_sides(ctx, {})
    c = yield from ask_style(ctx, "Continuity", ["G0", "G1", "G2"], "G2")
    if c is None:
        return
    do_blend(ctx, {"continuity": int(c[1])})


def do_blend(ctx, args):
    d = ctx.d
    sa, sb = two_sides(ctx, args)
    params = {"a": sw.side_params(sa), "b": sw.side_params(sb), "method": str(args.get("method", "auto")), "flip": bool(args.get("flip", False))}
    for key in ("continuity", "continuity_a", "continuity_b"):
        if args.get(key) is not None:
            params[key] = int(args[key])
    for key in ("influence", "influence_a", "influence_b"):
        if args.get(key) is not None:
            params[key] = positive(args[key], "Influence")
    res = guard(sw.call, d, "surf_blend", params)
    body = guard(sw.add_result, ctx, res, "Blend surface", "blend", {"seams": [sa["body"].handle, sb["body"].handle]})
    announce(ctx, "SRFBLEND", res)
    rep = res["report"]
    for name, seam in (("A", rep["seams"]["a"]), ("B", rep["seams"]["b"])):
        ctx.say("Seam %s: %s." % (name, sw.seam_line(seam)))
    ctx.say("Built by the %s method; requested %s, achieved %s." % (rep.get("method"), "/".join(str(v) for v in rep["requested"]), "/".join(rep["achieved"]).upper()))
    return {"handle": body.handle, "report": rep}


@executes("srfblend")
def srfblend_exec(ctx, args):
    return do_blend(ctx, args)


@command("srfmatch", aliases=("surfmatch",), group=GROUP, label="Match Surface", description="Move the edge rows of a surface to meet another surface edge with G0, G1 or G2; select the moving edge first, then the target edge.", menu="Draw > Modeling > Surface > Match")
def srfmatch_cmd(ctx):
    two_sides(ctx, {})
    c = yield from ask_style(ctx, "Continuity", ["G0", "G1", "G2"], "G2")
    if c is None:
        return
    do_match(ctx, {"continuity": int(c[1])})


def do_match(ctx, args):
    d = ctx.d
    moving, target = two_sides(ctx, args, "moving", "target")
    params = {"moving": sw.side_params(moving), "target": sw.side_params(target), "continuity": int(args.get("continuity", 2)), "correspondence": str(args.get("correspondence", "parameter")), "refine": bool(args.get("refine", True))}
    res = guard(sw.call, d, "surf_match", params)
    if isinstance(res.get("report", {}).get("seam"), dict):
        res["report"]["seam"]["bodies"] = [moving["body"].handle, target["body"].handle]
    body, in_place = guard(sw.edit_surface, ctx, moving["body"], res, "match")
    announce(ctx, "SRFMATCH", res)
    rep = res["report"]
    ctx.say("Seam: %s. Requested G%d, achieved %s; edge rows moved with %d refinement(s)." % (sw.seam_line(rep["seam"]), rep["requested"], rep["achieved"].upper(), rep["refinements"]))
    if not in_place:
        ctx.say("The moving surface belongs to a body with several faces, so the matched face is a new surface.")
    return {"handle": body.handle, "in_place": in_place, "report": rep}


@executes("srfmatch")
def srfmatch_exec(ctx, args):
    return do_match(ctx, args)


@command("srfextend", aliases=("surfextend",), group=GROUP, label="Extend Surface", description="Continue a surface past one of its edges; select the edge first.", menu="Draw > Modeling > Surface > Extend")
def srfextend_cmd(ctx):
    edges = list(ctx.doc.subselection.get("edges") or [])
    if not edges:
        ctx.say("Select the surface edge to extend first.")
        return
    n = yield ctx.distance("Specify the extension length", positive=True)
    if n.kind != "number":
        return
    do_extend(ctx, {"edge": {"body": edges[0]["body"], "edge": edges[0]["edge"]}, "length": n.value})


def do_extend(ctx, args):
    d = ctx.d
    ref = args.get("edge") or (list(ctx.doc.subselection.get("edges") or [None])[0])
    if not ref:
        raise CommandError("Give edge as {body, edge}.")
    side = guard(sw.side_of, d, ref)
    length = to_mm(ctx, args.get("length"), "The extension length")
    res = guard(sw.call, d, "surf_extend", {**sw.side_params(side), "length": length, "continuity": str(args.get("continuity", "g2"))})
    body, in_place = guard(sw.edit_surface, ctx, side["body"], res, "extend")
    announce(ctx, "SRFEXTEND", res)
    return {"handle": body.handle, "in_place": in_place, "report": res["report"]}


@executes("srfextend")
def srfextend_exec(ctx, args):
    return do_extend(ctx, args)


@command("srfoffset", aliases=("surfoffset",), group=GROUP, label="Offset Surface", description="Copy a surface at a distance along its normals.", menu="Draw > Modeling > Surface > Offset")
def srfoffset_cmd(ctx):
    sel = yield ctx.select("Select a surface", pick_one=True)
    if sel.kind != "selection" or not sel.value:
        return
    n = yield ctx.distance("Specify the offset distance", positive=False)
    if n.kind != "number":
        return
    do_offset(ctx, {"handle": int(sel.value[0]), "distance": n.value})


def do_offset(ctx, args):
    d = ctx.d
    handles = handles_of(args)
    if not handles:
        raise CommandError("Give the handle of a surface.")
    body = guard(sw.body_of, d, handles[0])
    dist = float(args.get("distance", 0)) * sw.scale(d)
    res = guard(sw.call, d, "surf_offset", {"id": guard(work.worker_id, d, body), "distance": dist, "join": str(args.get("join", "arc"))})
    made = guard(sw.add_result, ctx, res, "Offset surface", "offset")
    announce(ctx, "SRFOFFSET", res)
    return {"handle": made.handle, "report": res["report"]}


@executes("srfoffset")
def srfoffset_exec(ctx, args):
    return do_offset(ctx, args)


def split_pieces(ctx, body, res):
    d = ctx.d
    pieces = res["pieces"]
    names = []
    first = True
    for i, piece in enumerate(pieces):
        extra = {"piece": i + 1, "area": piece.get("area")}
        info = {"report": {**res["report"], "audit": piece.get("audit")}, "summary": piece["summary"], "id": piece["id"]}
        if first:
            target = d.modify(body.handle)
            work.apply_result(d, target, piece["id"], piece["summary"], {**sw.source_for("split", info, extra), "from": [body.name]}, None, body.lineage)
            names.append(target.handle)
            first = False
        else:
            made = sw.add_result(ctx, info, "%s %d" % (body.name or "Surface", i + 1), "split", extra)
            names.append(made.handle)
    return names


def do_split(ctx, args, trim):
    d = ctx.d
    handles = handles_of(args)
    if not handles:
        raise CommandError("Give the handle of the surface.")
    body = guard(sw.body_of, d, handles[0])
    s = sw.scale(d)
    params = {"id": guard(work.worker_id, d, body)}
    cutters = guard(sw.curves_of, d, handles_of(args, "curves"), args.get("curve_edges"))
    if cutters:
        params["tool_curves"] = cutters
        params["direction"] = [float(v) for v in (args.get("direction") or [0, 0, 1])]
    tool_bodies = [guard(sw.body_of, d, h) for h in handles_of(args, "tools")]
    if tool_bodies:
        params["tools"] = [guard(work.worker_id, d, t) for t in tool_bodies]
    if not cutters and not tool_bodies:
        raise CommandError("Give curves (with a direction) or tools to cut with.")
    if trim:
        keep = args.get("remove_points")
        if not keep:
            raise CommandError("Give remove_points: a point on each piece to remove.")
        params["remove_points"] = [sw.p3(q, s) for q in keep]
    res = guard(sw.call, d, "surf_split", params)
    if trim:
        edited, in_place = guard(sw.edit_surface, ctx, body, res, "trim")
        announce(ctx, "SRFTRIM", res)
        return {"handle": edited.handle, "report": res["report"]}
    made = guard(split_pieces, ctx, body, res)
    ctx.say("SRFSPLIT: %d pieces." % len(made))
    keep_report(ctx, res["report"])
    return {"handles": made, "report": res["report"]}


@command("srfsplit", aliases=("surfsplit",), group=GROUP, label="Split Surface", description="Cut a surface into pieces with curves projected along a direction, or with other surfaces.", menu="Modify > 3D Operations > Split Surface")
def srfsplit_cmd(ctx):
    sel = yield ctx.select("Select the surface to split", pick_one=True)
    if sel.kind != "selection" or not sel.value:
        return
    cut = yield from curve_pick(ctx, "Select the cutting curves")
    if not cut:
        return
    do_split(ctx, {"handle": int(sel.value[0]), "curves": cut}, False)


@executes("srfsplit")
def srfsplit_exec(ctx, args):
    return do_split(ctx, args, False)


@command("srftrim", aliases=("surftrim",), group=GROUP, label="Trim Surface", description="Cut a surface with curves and keep the pieces you do not point at.", menu="Modify > 3D Operations > Trim Surface")
def srftrim_cmd(ctx):
    sel = yield ctx.select("Select the surface to trim", pick_one=True)
    if sel.kind != "selection" or not sel.value:
        return
    cut = yield from curve_pick(ctx, "Select the cutting curves")
    if not cut:
        return
    p = yield ctx.point("Specify a point on the part to remove")
    if p.kind != "point":
        return
    do_split(ctx, {"handle": int(sel.value[0]), "curves": cut, "remove_points": [list(p.value)]}, True)


@executes("srftrim")
def srftrim_exec(ctx, args):
    return do_split(ctx, args, True)


@command("srfjoin", aliases=("surfjoin", "sew"), group=GROUP, label="Join Surfaces", description="Sew surfaces along matching edges into one polysurface, closed into a solid when it has no free edge.", menu="Modify > 3D Operations > Join Surfaces")
def srfjoin_cmd(ctx):
    sel = yield ctx.select("Select surfaces to join")
    if sel.kind != "selection":
        return
    do_join(ctx, {"handles": [int(h) for h in sel.value]})


def do_join(ctx, args):
    d = ctx.d
    bodies = [guard(sw.body_of, d, h) for h in handles_of(args)]
    if len(bodies) < 2:
        raise CommandError("Select at least two surfaces to join.")
    wids = [guard(work.worker_id, d, b) for b in bodies]
    res = guard(sw.call, d, "surf_join", {"ids": wids, "solid": bool(args.get("solid", True)), "non_manifold": bool(args.get("non_manifold", False))})
    target = guard(sw.merge_bodies, ctx, bodies, res, "join")
    rep = res["report"]
    announce(ctx, "SRFJOIN", res)
    ctx.say("%d free edge(s), %d shared by more than two faces; %s." % (rep.get("free_edges", 0), rep.get("multiple_edges", 0), "closed into a solid" if rep.get("closed_solid") else "left as a polysurface"))
    return {"handle": target.handle, "report": rep}


@executes("srfjoin")
def srfjoin_exec(ctx, args):
    return do_join(ctx, args)


def boolean_payload(ctx, rep, message=None):
    keep_report(ctx, rep)
    text = message or rep.get("message") or "The boolean operation failed."
    ctx.say(text)
    return {"ok": False, "message": text, "report": rep}


def say_boolean(ctx, rep):
    bad = [a for a in rep.get("arguments", []) if not a.get("valid", True)]
    for a in bad:
        ctx.say("An argument is not a valid shape: %s." % ", ".join(sorted({s for item in a.get("invalid", []) for s in item.get("statuses", [])})) or "see the report")
    found = rep.get("analysis", {})
    total = sum(len(v) for v in found.values() if isinstance(v, list))
    if total:
        ctx.say("The argument check found %d problem(s): %s." % (total, ", ".join("%s %d" % (k.replace("_", " "), len(v)) for k, v in found.items() if isinstance(v, list) and v)))
    if rep.get("fuzzy_used") is not None:
        ctx.say("Fuzzy value used: %.3g mm%s." % (rep["fuzzy_used"], "; inputs were repaired first" if rep.get("repaired") else ""))
    if rep.get("warnings"):
        ctx.say("The kernel reported warnings: %s." % "; ".join(rep["warnings"]))


def do_boolean(ctx, args, op=None, check_only=False):
    d = ctx.d
    op = OP_WORDS.get(str(op or args.get("op") or "").lower())
    if not op:
        raise CommandError("op is union, subtract or intersect.")
    base_handles = handles_of(args, "base")
    tool_handles = handles_of(args, "tools")
    if not base_handles or not tool_handles:
        raise CommandError("Give base (the shape to keep) and tools.")
    base = guard(sw.body_of, d, base_handles[0])
    tools = [guard(sw.body_of, d, h) for h in tool_handles if h != base.handle]
    if not tools:
        raise CommandError("Give at least one tool different from the base.")
    s = sw.scale(d)
    params = {"op": op, "base": guard(work.worker_id, d, base), "tools": [guard(work.worker_id, d, t) for t in tools], "retry": bool(args.get("retry", True)), "check_only": bool(check_only or args.get("check_only"))}
    if args.get("fuzzy") is not None:
        params["fuzzy"] = float(args["fuzzy"]) * s
    if args.get("max_fuzzy") is not None:
        params["max_fuzzy"] = float(args["max_fuzzy"]) * s
    if args.get("unify") is not None:
        params["unify"] = bool(args["unify"])
    res = guard(sw.call, d, "bool_diag", params)
    rep = res["report"]
    say_boolean(ctx, rep)
    if params["check_only"]:
        keep_report(ctx, rep)
        ctx.say("%s check: %s." % (BOOL_OPS[op], "no problems found" if rep.get("ok") else "problems found"))
        return {"ok": bool(rep.get("ok")), "report": sw.compact(rep)}
    if res.get("id") is None:
        return boolean_payload(ctx, sw.compact(rep))
    if not rep.get("ok"):
        return boolean_payload(ctx, sw.compact(rep), "The result is not a valid shape (%s); nothing was changed." % ", ".join(sorted({s2 for item in rep.get("result", {}).get("invalid", []) for s2 in item.get("statuses", [])})))
    inputs = (res.get("history") or {}).get("inputs") or []
    sources = [base] + tools
    parts = [(b.face_ids, b.edge_ids, inputs[i] if i < len(inputs) else {}) for i, b in enumerate(sources)] if inputs else None
    keep = dict(base.lineage)
    for t in tools:
        keep.update(t.lineage)
    target = d.modify(base.handle)
    has_solid = bool((res["summary"] or {}).get("solids"))
    src = {**sw.source_for("bool_" + op, res), "from": [b.name for b in sources], "surface": not has_solid}
    work.apply_result(d, target, res["id"], res["summary"], src, parts, keep)
    if not args.get("keep_tools"):
        for t in tools:
            d.erase_entity(t.handle)
    announce(ctx, BOOL_OPS[op], res)
    return {"ok": True, "handle": target.handle, "report": sw.compact(rep)}


def boolean_command(ctx, op):
    sel = yield ctx.select("Select the shape to keep, then the tools")
    if sel.kind != "selection":
        return
    handles = [int(h) for h in sel.value]
    if len(handles) < 2:
        ctx.say("Select at least two solids or surfaces.")
        return
    do_boolean(ctx, {"base": handles[0], "tools": handles[1:]}, op)


@command("boolop", aliases=("boolean",), group=GROUP, label="Boolean with Diagnostics", description="Union, subtract or intersect solids and surfaces; checks the arguments first and reports what went wrong.", menu="Modify > Solid Editing > Boolean")
def boolop_cmd(ctx):
    r = yield ctx.keyword("Operation [Union/Subtract/Intersect]", ["Union", "Subtract", "Intersect"], default="Union")
    if r.kind != "keyword":
        return
    yield from boolean_command(ctx, r.value.lower())


@executes("boolop")
def boolop_exec(ctx, args):
    return do_boolean(ctx, args)


@command("boolcheck", group=GROUP, label="Check Boolean", description="Check solids and surfaces for the problems that make a boolean fail, without changing anything.", menu="Modify > Solid Editing > Check Boolean", undoable=False)
def boolcheck_cmd(ctx):
    sel = yield ctx.select("Select the shape to keep, then the tools")
    if sel.kind != "selection":
        return
    handles = [int(h) for h in sel.value]
    if len(handles) < 2:
        ctx.say("Select at least two solids or surfaces.")
        return
    do_boolean(ctx, {"base": handles[0], "tools": handles[1:], "op": "union"}, check_only=True)


@executes("boolcheck")
def boolcheck_exec(ctx, args):
    return do_boolean(ctx, {**args, "op": args.get("op") or "union"}, check_only=True)


def edge_group(ctx, args):
    refs = sub_edges(ctx, args)
    if not refs:
        raise CommandError("Select the edges first, or give edges as a list of {body, edge}.")
    owner = refs[0]["body"]
    if any(r["body"] != owner for r in refs):
        raise CommandError("Pick edges of one body at a time.")
    body = guard(sw.body_of, ctx.d, owner)
    indices = [guard(sw.index_of, body.edge_ids, r.get("edge"), "edge") if r.get("edge_index") is None else int(r["edge_index"]) for r in refs]
    return body, indices


def treat(ctx, args, method, label, params):
    d = ctx.d
    body, indices = edge_group(ctx, args)
    wid = guard(work.worker_id, d, body)
    res = guard(sw.call, d, method, {"id": wid, "edges": indices, **params})
    rep = res["report"]
    if not rep.get("valid", True):
        raise CommandError("The %s produced an invalid shape; nothing was changed." % label)
    target = guard(sw.replace_result, ctx, body, res, method)
    announce(ctx, label.upper(), res)
    return {"handle": target.handle, "report": sw.compact(rep)}


def radius_args(ctx, args):
    s = sw.scale(ctx.d)
    params = {}
    if args.get("radii"):
        params["radii"] = [[float(p), float(r) * s] for p, r in args["radii"]]
        params["radius"] = params["radii"][0][1]
    else:
        params["radius"] = to_mm(ctx, args.get("radius"), "The radius")
        if args.get("radius2") is not None:
            params["radius2"] = to_mm(ctx, args["radius2"], "The second radius")
    return params


def fillet_do(ctx, args, continuity):
    params = radius_args(ctx, args)
    params["continuity"] = str(args.get("continuity", continuity)).lower()
    return treat(ctx, args, "fillet_edge", "fillet edge" if continuity == "g1" else "blend edge", params)


def ask_edge_radius(ctx, name):
    if not ctx.doc.subselection.get("edges"):
        ctx.say("Select the edges first.")
        return None
    r = yield ctx.distance("Specify the radius", positive=True)
    return r.value if r.kind == "number" else None


@command("filletedge", group=GROUP, label="Fillet Edge", description="Round selected solid or surface edges with a tangent fillet; give one radius or a second radius to vary along the edge.", menu="Modify > Solid Editing > Fillet Edge")
def filletedge_cmd(ctx):
    r = yield from ask_edge_radius(ctx, "FILLETEDGE")
    if r is not None:
        fillet_do(ctx, {"radius": r}, "g1")


@executes("filletedge")
def filletedge_exec(ctx, args):
    return fillet_do(ctx, args, "g1")


@command("blendedge", group=GROUP, label="Blend Edge", description="Round selected edges with a curvature-continuous blend.", menu="Modify > Solid Editing > Blend Edge")
def blendedge_cmd(ctx):
    r = yield from ask_edge_radius(ctx, "BLENDEDGE")
    if r is not None:
        fillet_do(ctx, {"radius": r}, "g2")


@executes("blendedge")
def blendedge_exec(ctx, args):
    return fillet_do(ctx, args, "g2")


def chamfer_do(ctx, args):
    s = sw.scale(ctx.d)
    params = {"distance": to_mm(ctx, args.get("distance"), "The distance")}
    if args.get("distance2") is not None:
        params["distance2"] = to_mm(ctx, args["distance2"], "The second distance")
    if args.get("angle") is not None:
        ang = float(args["angle"])
        if not 0 < ang < 90:
            raise CommandError("The angle is between 0 and 90 degrees.")
        params["angle"] = ang
    if "distance2" in params and "angle" in params:
        raise CommandError("Give a second distance or an angle, not both.")
    _ = s
    return treat(ctx, args, "chamfer_edge", "chamfer edge", params)


@command("chamferedge", group=GROUP, label="Chamfer Edge", description="Bevel selected solid or surface edges by a distance, two distances, or a distance and an angle.", menu="Modify > Solid Editing > Chamfer Edge")
def chamferedge_cmd(ctx):
    r = yield from ask_edge_radius(ctx, "CHAMFEREDGE")
    if r is not None:
        chamfer_do(ctx, {"distance": r})


@executes("chamferedge")
def chamferedge_exec(ctx, args):
    return chamfer_do(ctx, args)


@command("seamcheck", aliases=("surfcont",), group="inquiry", label="Seam Continuity", description="Measure position, tangent and curvature continuity along the seam between two surface edges; select the two edges first.", menu="Tools > Inquiry > Seam Continuity", undoable=False)
def seamcheck_cmd(ctx):
    do_seam(ctx, {})
    yield from ()


def do_seam(ctx, args):
    sa, sb = two_sides(ctx, args)
    params = {"a": sw.side_params(sa), "b": sw.side_params(sb), "samples": bounded(args, "samples", 41, 2, 2000, "The sample count")}
    if args.get("curvature_relative") is not None:
        params["curvature_relative"] = positive(args["curvature_relative"], "The curvature tolerance")
    res = guard(sw.call, ctx.d, "surf_continuity", params)
    rep = res["report"]
    rep["bodies"] = [sa["body"].handle, sb["body"].handle]
    ctx.say("SEAMCHECK: %s." % sw.seam_line(rep))
    t = rep.get("tolerance") or {}
    ctx.say("Against position %.3g mm, angle %.3g rad, curvature %.3g: G0 %s, G1 %s, G2 %s. G3 is not measured." % (t.get("length", 0.0), t.get("angle", 0.0), t.get("curvature", 0.0), "yes" if rep.get("g0") else "no", "yes" if rep.get("g1") else "no", "yes" if rep.get("g2") else "no"))
    off = rep.get("edge_offset")
    if off is not None and off > max(10.0 * float(t.get("length", 0.0)), 1e-6):
        ctx.say("Warning: the second edge lies %.3g mm from the first, so it is not the seam; the report measures the first edge against the second surface. Pick the edge that meets the first." % off)
    keep_report(ctx, rep)
    return {"report": sw.compact(rep)}


@executes("seamcheck")
def seamcheck_exec(ctx, args):
    return do_seam(ctx, args)


@command("nakededges", aliases=("freeedges",), group="inquiry", label="Naked Edges", description="Find the edges of a surface that no neighbour shares, and the small edges and invalid parts of a shape.", menu="Tools > Inquiry > Naked Edges", undoable=False)
def nakededges_cmd(ctx):
    sel = yield ctx.select("Select a solid or surface", pick_one=True)
    if sel.kind != "selection" or not sel.value:
        return
    do_naked(ctx, {"handle": int(sel.value[0])})


def do_naked(ctx, args):
    handles = handles_of(args)
    if not handles:
        raise CommandError("Give the handle of a solid or surface.")
    body = guard(sw.body_of, ctx.d, handles[0])
    res = guard(sw.call, ctx.d, "surf_naked", {"id": guard(work.worker_id, ctx.d, body)}, work.SHORT)
    n = len(res["naked_edges"])
    ctx.say("NAKEDEDGES: %d naked edge polyline(s), %d small edge(s), %s." % (n, len(res.get("small_edges") or []), "valid" if res["check"].get("valid") else "not valid"))
    ctx.mem["surface_naked"] = sw.compact(res)
    ctx.mem["surface_seq"] = ctx.mem.get("surface_seq", 0) + 1
    return {"count": n, "naked_edges": res["naked_edges"], "small_edges": res.get("small_edges"), "check": res["check"], "audit": res.get("audit")}


@executes("nakededges")
def nakededges_exec(ctx, args):
    return do_naked(ctx, args)


@command("surfreport", group="inquiry", label="Surface Report", description="Show the stored construction report of a surface: method, errors, seams and the stored-tolerance audit.", menu="Tools > Inquiry > Surface Report", undoable=False)
def surfreport_cmd(ctx):
    sel = yield ctx.select("Select a solid or surface", pick_one=True)
    if sel.kind != "selection" or not sel.value:
        return
    do_report(ctx, {"handle": int(sel.value[0])})


def do_report(ctx, args):
    handles = handles_of(args)
    if not handles:
        raise CommandError("Give the handle of a solid or surface.")
    body = guard(sw.body_of, ctx.d, handles[0])
    rep = (body.source or {}).get("report")
    if not rep:
        raise CommandError("This body has no stored construction report.")
    ctx.say("SURFREPORT: %s, made by %s." % (sw.surface_label(body.summary), body.source.get("op")))
    line = sw.audit_line(rep)
    if line:
        ctx.say(line)
    for key in ("seams",):
        for name, seam in (rep.get(key) or {}).items():
            ctx.say("Seam %s: %s." % (name.upper(), sw.seam_line(seam)))
    if rep.get("seam"):
        ctx.say("Seam: %s." % sw.seam_line(rep["seam"]))
    return {"op": body.source.get("op"), "report": rep}


@executes("surfreport")
def surfreport_exec(ctx, args):
    return do_report(ctx, args)


@command("modeltol", aliases=("modeltolerance",), group="settings", label="Model Tolerance", description="Absolute and angular tolerance every surface, boolean and edge operation of this drawing is given.", menu="Tools > Model Tolerance...", undoable=False, repeatable=False)
def modeltol_cmd(ctx):
    show_tol(ctx)
    a = yield ctx.number("Specify the absolute tolerance in drawing units or press Enter to keep it", positive=True, default=None)
    if a.kind == "number":
        b = yield ctx.number("Specify the angular tolerance in radians or press Enter to keep it", positive=True, default=None)
        set_tol(ctx, {"absolute": a.value, "angular": b.value if b.kind == "number" else None})


def show_tol(ctx):
    t = sw.model_tolerance(ctx.d)
    ctx.say("MODELTOL: absolute %.3g mm (%s), angular %.3g rad (%s)." % (t["tol"], t["absolute_source"], t["angtol"], t["angular_source"]))
    return {"absolute_mm": t["tol"], "absolute_units": t["tol_units"], "angular": t["angtol"], "absolute_source": t["absolute_source"], "angular_source": t["angular_source"]}


def set_tol(ctx, args):
    d = ctx.d
    s = sw.scale(d)
    changed = {}
    if args.get("absolute") is not None:
        v = positive(args["absolute"], "The absolute tolerance")
        if v * s < sw.FLOOR_TOL or v * s > 1.0:
            raise CommandError("The absolute tolerance must be from %g mm to 1 mm." % sw.FLOOR_TOL)
        changed["absolute"] = v
    if args.get("angular") is not None:
        v = positive(args["angular"], "The angular tolerance")
        if v < sw.FLOOR_ANGLE or v > 0.1:
            raise CommandError("The angular tolerance must be from %g to 0.1 radian." % sw.FLOOR_ANGLE)
        changed["angular"] = v
    if changed:
        d.tolerances = {**d.tolerances, **changed}
        ctx.doc.state_id = next(ctx.doc._states)
        ctx.doc.announce("settings")
    return show_tol(ctx)


@executes("modeltol")
def modeltol_exec(ctx, args):
    return set_tol(ctx, args)
