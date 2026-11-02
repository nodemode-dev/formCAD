import copy
import math

from app.cmd import edit_ledger as L, jig
from app.cmd.commands.draw_splines import curve_shape
from app.cmd.commands.modify_corner import menu
from app.cmd.context import CommandError
from app.cmd.draw_support import add_like, pick_entity
from app.cmd.registry import command, executes
from app.doc import geom, nurbs, polyedit, splineedit
from app.doc.entities import BASE_FIELDS, Arc, Line, LwPolyline, Spline

LOCKED = "The object is on a locked layer."
NOT_POLY = "Object selected is not a polyline."
NOT_SPLINE = "Object selected is not a spline."
EPS = 1e-9


def _live(ctx, handle):
    return ctx.d.get(handle)


def _check_ready(ctx, ent):
    if ent is None:
        raise CommandError("*Invalid selection*")
    if ctx.locked(ent):
        raise CommandError(LOCKED)
    return ent


def _marker(p, size):
    return [jig.line([p[0] - size, p[1] - size], [p[0] + size, p[1] + size]), jig.line([p[0] - size, p[1] + size], [p[0] + size, p[1] - size])]


def _msize(ctx):
    return float(ctx.doc.view.get("height", 100.0)) * 0.015


def to_polyline(ctx, led, ent):
    verts, closed = polyedit.pieces_of(ent)
    if verts is None:
        raise CommandError(NOT_POLY)
    if isinstance(ent, LwPolyline):
        return ent
    L.touch(ctx, led, ent)
    new = LwPolyline(vertices=verts, closed=False)
    for name in BASE_FIELDS:
        setattr(new, name, copy.deepcopy(getattr(ent, name)))
    ctx.d.ents[ent.handle] = new
    return new


def normalize_width(ent):
    n = len(ent.vertices)
    segs = ent.vertices if ent.closed else ent.vertices[:-1]
    pairs = {(round(v.get("sw", 0.0), 9), round(v.get("ew", 0.0), 9)) for v in segs}
    if len(pairs) == 1:
        sw, ew = next(iter(pairs))
        ent.const_width = sw if sw == ew else 0.0
    else:
        ent.const_width = 0.0


def op_close(ctx, led, ent, close):
    if bool(ent.closed) == close:
        return False
    if close and len(ent.vertices) < 3:
        raise CommandError("A polyline needs at least three vertices to close.")
    L.touch(ctx, led, ent)
    ent.closed = close
    return True


def op_width(ctx, led, ent, w):
    if w < 0:
        raise CommandError("Requires a positive number.")
    L.touch(ctx, led, ent)
    for v in ent.vertices:
        v["sw"] = float(w)
        v["ew"] = float(w)
    ent.const_width = float(w)


def op_reverse(ctx, led, ent):
    L.touch(ctx, led, ent)
    ent.vertices = polyedit.reverse_vertices(ent.vertices, ent.closed)


def op_ltgen(ctx, led, ent):
    L.touch(ctx, led, ent)
    ent.linetype_gen = not bool(ent.linetype_gen)
    return ent.linetype_gen


def _keep_frame(ent):
    if "frame" not in ent.extra:
        ent.extra = {**ent.extra, "frame": copy.deepcopy(ent.vertices)}


def op_fit(ctx, led, ent):
    L.touch(ctx, led, ent)
    try:
        verts = polyedit.fit_biarcs(ent.vertices if "frame" not in ent.extra else ent.extra["frame"], ent.closed)
    except ValueError as err:
        raise CommandError(str(err))
    _keep_frame(ent)
    ent.extra = {**ent.extra, "curve": "fit"}
    ent.vertices = verts
    normalize_width(ent)


def op_spline(ctx, led, ent):
    L.touch(ctx, led, ent)
    segs = int(ctx.d.header.get("SPLINESEGS", 8))
    frame = ent.extra["frame"] if "frame" in ent.extra else ent.vertices
    try:
        verts = polyedit.spline_vertices(frame, ent.closed, segs)
    except ValueError as err:
        raise CommandError(str(err))
    _keep_frame(ent)
    ent.extra = {**ent.extra, "curve": "spline"}
    ent.vertices = verts
    normalize_width(ent)


def op_decurve(ctx, led, ent):
    L.touch(ctx, led, ent)
    if "frame" in ent.extra:
        ent.vertices = copy.deepcopy(ent.extra["frame"])
        rest = {k: v for k, v in ent.extra.items() if k not in ("frame", "curve")}
        ent.extra = rest
    else:
        for v in ent.vertices:
            v["bulge"] = 0.0
    normalize_width(ent)


def op_join(ctx, led, ent, cands, fuzz):
    if ent.closed:
        raise CommandError("Closed polylines cannot be joined.")
    items = []
    for c in cands:
        if c.handle == ent.handle or ctx.locked(c):
            continue
        vs, closed = polyedit.pieces_of(c)
        if vs is None:
            continue
        items.append((c, vs, closed))
    chain, used = polyedit.join_chain(ent.vertices, [(c.handle, vs, cl) for c, vs, cl in items], fuzz)
    if not used:
        return 0
    L.touch(ctx, led, ent)
    ent.vertices = chain
    added = len(used)
    for c, _vs, _cl in items:
        if c.handle in used:
            L.drop(ctx, led, c)
    normalize_width(ent)
    ent.extra = {k: v for k, v in ent.extra.items() if k not in ("frame", "curve")}
    return added


def _sel_pass(ctx, handles):
    out = []
    for h in handles:
        e = ctx.d.get(h)
        if e is not None and not ctx.locked(e):
            out.append(e)
    return out


def _break_session(ctx, led, ent, a, b):
    parts = polyedit.break_between(ent.vertices, ent.closed, a, b)
    if not parts:
        raise CommandError("Nothing remains after the break.")
    L.touch(ctx, led, ent)
    first = parts[0]
    ent.vertices = first
    ent.closed = False
    made = []
    for extra in parts[1:]:
        clone = LwPolyline(vertices=extra, closed=False, const_width=ent.const_width, elevation=ent.elevation, linetype_gen=ent.linetype_gen)
        made.append(L.made(led, add_like(ctx, clone, ent)))
    return made


def _vertex_session(ctx, h):
    led = L.new()
    idx = 0
    size = _msize(ctx)
    while True:
        ent = _live(ctx, h)
        if ent is None or not isinstance(ent, LwPolyline):
            break
        n = len(ent.vertices)
        idx = max(0, min(idx, n - 1))
        p = ent.vertices[idx]["p"]
        opts = ["Next", "Previous", "Break", "Insert", "Move", "Regen", "Straighten", "Tangent", "Width", "eXit"]
        pr = menu(ctx, "Enter a vertex editing option", opts, "Next")
        pr.jig = lambda cursor, p=p: _marker(p, size)
        r = yield pr
        if r.kind == "enter":
            break
        if r.kind != "keyword":
            break
        w = r.value
        if w == "eXit":
            break
        if w == "Next":
            idx = (idx + 1) % n if ent.closed else min(idx + 1, n - 1)
        elif w == "Previous":
            idx = (idx - 1) % n if ent.closed else max(idx - 1, 0)
        elif w == "Regen":
            continue
        elif w == "Move":
            pt = yield ctx.point("Specify new location for marked vertex", base=p, jig=lambda c, e=ent, i=idx: _poly_jig(e, "move", i, c))
            if pt.kind == "point":
                L.touch(ctx, led, ent)
                ent.vertices[idx]["p"] = [pt.value[0], pt.value[1]]
        elif w == "Insert":
            pt = yield ctx.point("Specify location for new vertex", base=p, jig=lambda c, e=ent, i=idx: _poly_jig(e, "insert", i, c))
            if pt.kind == "point":
                _insert_vertex(ctx, led, ent, idx, pt.value)
        elif w == "Tangent":
            t = yield ctx.angle("Specify direction of vertex tangent", base=p)
            if t.kind in ("number", "point"):
                ang = t.value if t.kind == "number" else geom.angle_of(p, t.value)
                L.touch(ctx, led, ent)
                ent.vertices[idx]["tg"] = geom.norm_angle(ang)
        elif w == "Width":
            cur = ent.vertices[idx].get("sw", 0.0)
            s = yield ctx.number("Specify starting width for next segment", default=cur, minimum=0, default_text=ctx.fd(cur))
            if s.kind != "number":
                continue
            e2 = yield ctx.number("Specify ending width for next segment", default=s.value, minimum=0, default_text=ctx.fd(s.value))
            if e2.kind != "number":
                continue
            L.touch(ctx, led, ent)
            ent.vertices[idx]["sw"] = float(s.value)
            ent.vertices[idx]["ew"] = float(e2.value)
            normalize_width(ent)
        elif w in ("Break", "Straighten"):
            idx2 = idx
            done = False
            while not done:
                q = ent.vertices[idx2]["p"]
                pr2 = menu(ctx, "Enter an option", ["Next", "Previous", "Go", "eXit"], "Next")
                pr2.jig = lambda cursor, q=q, p=p: _marker(p, size) + _marker(q, size)
                r2 = yield pr2
                if r2.kind == "enter" or (r2.kind == "keyword" and r2.value == "Next"):
                    idx2 = (idx2 + 1) % n if ent.closed else min(idx2 + 1, n - 1)
                elif r2.kind == "keyword" and r2.value == "Previous":
                    idx2 = (idx2 - 1) % n if ent.closed else max(idx2 - 1, 0)
                elif r2.kind == "keyword" and r2.value == "Go":
                    try:
                        if w == "Straighten":
                            L.touch(ctx, led, ent)
                            ent.vertices = polyedit.straighten(ent.vertices, ent.closed, idx, idx2)
                        else:
                            _break_session(ctx, led, ent, idx, idx2)
                    except CommandError as err:
                        ctx.say(str(err))
                    done = True
                else:
                    done = True
    if not L.empty(led):
        ent = _live(ctx, h)
        if ent is not None:
            normalize_width(ent)
    return led


def _insert_vertex(ctx, led, ent, idx, pt):
    L.touch(ctx, led, ent)
    cur = ent.vertices[idx]
    new = polyedit.vertex(pt, 0.0, cur.get("ew", 0.0), cur.get("ew", 0.0))
    cur["bulge"] = 0.0
    ent.vertices.insert(idx + 1, new)


def _poly_jig(ent, mode, idx, cursor):
    verts = copy.deepcopy(ent.vertices)
    if mode == "move":
        verts[idx]["p"] = [cursor[0], cursor[1]]
    else:
        verts[idx]["bulge"] = 0.0
        verts.insert(idx + 1, polyedit.vertex(cursor))
    return [jig.poly(verts, ent.closed)]


def _menu_options(ents, multi):
    any_open = any(not e.closed for e in ents)
    any_closed = any(e.closed for e in ents)
    opts = (["Close"] if any_open else []) + (["Open"] if any_closed else []) + ["Join", "Width"]
    if not multi:
        opts.append("Edit vertex")
    return opts + ["Fit", "Spline", "Decurve", "Ltype gen", "Reverse", "Undo"]


def _edit_loop(ctx, handles, multi):
    stack = []
    while True:
        ents = [e for e in (_live(ctx, h) for h in handles) if isinstance(e, LwPolyline)]
        if not ents:
            return
        r = yield menu(ctx, "Enter an option", _menu_options(ents, multi))
        if r.kind != "keyword":
            return
        w = r.value
        led = L.new()
        if w == "Undo":
            if stack:
                L.rollback(ctx, stack.pop())
            else:
                ctx.say("Nothing to undo.")
            continue
        try:
            if w in ("Close", "Open"):
                for e in ents:
                    try:
                        op_close(ctx, led, e, w == "Close")
                    except CommandError as err:
                        if not multi:
                            raise
                        ctx.say(str(err))
            elif w == "Width":
                v = yield ctx.number("Specify new width for all segments" if multi else "Specify new width for all segments", minimum=0)
                if v.kind != "number":
                    continue
                for e in ents:
                    op_width(ctx, led, e, v.value)
            elif w == "Fit":
                for e in ents:
                    op_fit(ctx, led, e)
            elif w == "Spline":
                for e in ents:
                    op_spline(ctx, led, e)
            elif w == "Decurve":
                for e in ents:
                    op_decurve(ctx, led, e)
            elif w == "Ltype gen":
                for e in ents:
                    op_ltgen(ctx, led, e)
            elif w == "Reverse":
                for e in ents:
                    op_reverse(ctx, led, e)
            elif w == "Join":
                fuzz = 0.0
                if multi:
                    f = yield ctx.number("Enter fuzz distance", default=float(ctx.mem.get("pedit_fuzz", 0.0)), minimum=0, default_text=ctx.fd(float(ctx.mem.get("pedit_fuzz", 0.0))))
                    if f.kind != "number":
                        continue
                    fuzz = float(f.value)
                    ctx.mem["pedit_fuzz"] = fuzz
                s = yield ctx.select("Select objects to join")
                if s.kind != "selection" or not s.value:
                    continue
                total = 0
                cands = [ctx.d.get(x) for x in s.value if ctx.d.get(x) is not None]
                for e in ents:
                    if e.handle in ctx.d.ents:
                        total += op_join(ctx, led, e, [c for c in cands if c.handle in ctx.d.ents], fuzz)
                ctx.say("%d segment%s added to polyline" % (total, "" if total == 1 else "s"))
            elif w == "Edit vertex":
                sub = yield from _vertex_session(ctx, ents[0].handle)
                if not L.empty(sub):
                    stack.append(sub)
                continue
        except CommandError as err:
            L.rollback(ctx, led)
            ctx.say(str(err))
            continue
        if not L.empty(led):
            stack.append(led)


def _convert_prompt(ctx, ent, led):
    ctx.say(NOT_POLY)
    r = yield ctx.yesno("Do you want to turn it into one?", "Yes")
    if r.kind == "enter" or (r.kind == "keyword" and r.value == "Yes"):
        to_polyline(ctx, led, ent)
        return True
    return False


@command("pedit", aliases=("pe",), group="modify", label="Polyline", description="Edit polylines: close, join, width, fit, spline, decurve, reverse, vertex editing, multiple.", menu="Modify > Object > Polyline")
def pedit(ctx):
    pre = [h for h in ctx.doc.selection if h in ctx.d.ents]
    ctx.doc.selection = []
    if len(pre) > 1:
        multi = True
        chosen = pre
    elif len(pre) == 1:
        multi = False
        chosen = pre
    else:
        multi = False
        chosen = []
    conv = L.new()
    if not chosen:
        while True:
            r = yield ctx.entity("Select polyline", ["Multiple"])
            if r.kind == "keyword":
                s = yield ctx.select("Select objects")
                if s.kind != "selection" or not s.value:
                    return
                chosen = list(s.value)
                multi = True
                break
            if r.kind != "entity":
                return
            ent = pick_entity(ctx, r.value)
            try:
                _check_ready(ctx, ent)
            except CommandError as err:
                ctx.say(str(err))
                continue
            if isinstance(ent, LwPolyline):
                chosen = [ent.handle]
                break
            if isinstance(ent, (Line, Arc)):
                ok = yield from _convert_prompt(ctx, ent, conv)
                if ok:
                    chosen = [ent.handle]
                    break
                continue
            ctx.say(NOT_POLY)
    if multi:
        ents = _sel_pass(ctx, chosen)
        need = [e for e in ents if isinstance(e, (Line, Arc))]
        if need:
            r = yield ctx.yesno("Convert Lines and Arcs to polylines?", "Yes")
            if r.kind == "enter" or (r.kind == "keyword" and r.value == "Yes"):
                for e in need:
                    to_polyline(ctx, conv, e)
        chosen = [e.handle for e in ents if isinstance(ctx.d.get(e.handle), LwPolyline)]
    else:
        chosen = [h for h in chosen if ctx.d.get(h) is not None and not ctx.locked(ctx.d.get(h))]
        if chosen and not isinstance(ctx.d.get(chosen[0]), LwPolyline):
            to_polyline(ctx, conv, ctx.d.get(chosen[0]))
    if not chosen:
        ctx.say("Nothing selected that can be edited.")
        return
    yield from _edit_loop(ctx, chosen, multi)


def _targets(ctx, args):
    hs = args.get("handles")
    if hs is None:
        hs = [args["handle"]] if "handle" in args else list(ctx.doc.selection)
    ents = []
    for h in hs:
        e = ctx.d.get(int(h))
        _check_ready(ctx, e)
        ents.append(e)
    if not ents:
        raise CommandError("Select polyline.")
    return ents


@executes("pedit")
def pedit_exec(ctx, args):
    ents = _targets(ctx, args)
    led = L.new()
    conv = bool(args.get("convert", True))
    polys = []
    for e in ents:
        if isinstance(e, (Line, Arc)):
            if not conv:
                continue
            polys.append(to_polyline(ctx, led, e))
        elif isinstance(e, LwPolyline):
            polys.append(e)
        else:
            raise CommandError(NOT_POLY)
    opt = str(args.get("option", "")).lower().replace(" ", "")
    result = {"polylines": [e.handle for e in polys]}
    if opt in ("", "convert"):
        return result
    for e in polys:
        if opt == "close":
            op_close(ctx, led, e, True)
        elif opt == "open":
            op_close(ctx, led, e, False)
        elif opt == "width":
            op_width(ctx, led, e, float(args.get("width", 0.0)))
        elif opt == "fit":
            tg = args.get("tangents")
            if tg:
                L.touch(ctx, led, e)
                for i, a in enumerate(tg):
                    if a is not None and i < len(e.vertices):
                        e.vertices[i]["tg"] = math.radians(float(a))
            op_fit(ctx, led, e)
        elif opt == "spline":
            op_spline(ctx, led, e)
        elif opt == "decurve":
            op_decurve(ctx, led, e)
        elif opt == "reverse":
            op_reverse(ctx, led, e)
        elif opt in ("ltypegen", "ltgen"):
            op_ltgen(ctx, led, e)
        elif opt == "join":
            others = [ctx.d.get(int(h)) for h in args.get("others", [])]
            result["added"] = result.get("added", 0) + op_join(ctx, led, e, [o for o in others if o is not None], float(args.get("fuzz", 0.0)))
        elif opt == "vertex":
            result.update(_vertex_exec(ctx, led, e, args))
        else:
            raise CommandError("Invalid option keyword.")
    return result


def _vertex_exec(ctx, led, ent, args):
    act = str(args.get("action", "")).lower()
    n = len(ent.vertices)
    i = int(args.get("index", 0))
    if not 0 <= i < n:
        raise CommandError("Invalid vertex.")
    j = int(args["index2"]) if "index2" in args else i
    if not 0 <= j < n:
        raise CommandError("Invalid vertex.")
    if act == "move":
        L.touch(ctx, led, ent)
        ent.vertices[i]["p"] = [float(args["target"][0]), float(args["target"][1])]
    elif act == "insert":
        _insert_vertex(ctx, led, ent, i, args["target"])
    elif act == "straighten":
        L.touch(ctx, led, ent)
        ent.vertices = polyedit.straighten(ent.vertices, ent.closed, i, j)
    elif act == "break":
        return {"created": _break_session(ctx, led, ent, i, j)}
    elif act == "width":
        w = args.get("widths") or [0.0, 0.0]
        L.touch(ctx, led, ent)
        ent.vertices[i]["sw"] = float(w[0])
        ent.vertices[i]["ew"] = float(w[1] if len(w) > 1 else w[0])
        normalize_width(ent)
    elif act == "tangent":
        L.touch(ctx, led, ent)
        ent.vertices[i]["tg"] = geom.norm_angle(math.radians(float(args.get("angle", 0.0))))
    elif act != "regen":
        raise CommandError("Invalid option keyword.")
    return {}


def curve_of(ent):
    c = nurbs.Curve(int(ent.degree), [float(k) for k in ent.knots], [list(p) for p in ent.control_points], [float(w) for w in ent.weights] if ent.weights else [], bool(ent.closed))
    if not c.valid():
        raise CommandError("The spline is not valid.")
    return c


def assign_curve(ent, curve, keep_fit):
    ent.degree = curve.degree
    ent.knots = list(curve.knots)
    ent.control_points = [list(p) + [0.0] * (3 - len(p)) for p in curve.ctrl]
    uniform = not curve.weights or all(abs(w - 1.0) < 1e-12 for w in curve.weights)
    ent.weights = [] if uniform else list(curve.weights)
    ent.closed = bool(curve.closed)
    if not keep_fit:
        ent.fit_points = []
        ent.start_tangent = ent.end_tangent = None
        ent.fit_tolerance = 0.0


def refit(ent):
    pts = [list(p) for p in ent.fit_points]
    try:
        curve, _flat = nurbs.fit(pts, ent.fit_method if ent.fit_method in (0, 1, 2) else 0, bool(ent.closed), None if ent.closed else ent.start_tangent, None if ent.closed else ent.end_tangent, ent.fit_tolerance)
    except ValueError as err:
        raise CommandError(str(err))
    assign_curve(ent, curve, True)


def _min_fit(ent):
    return 3 if ent.closed else 2


def sp_close(ctx, led, ent, close):
    if bool(ent.closed) == close:
        return False
    L.touch(ctx, led, ent)
    if ent.fit_points:
        if close and len({(round(p[0], 9), round(p[1], 9)) for p in ent.fit_points}) < 3:
            raise CommandError("The spline needs at least 3 fit points to close.")
        ent.closed = close
        if close:
            ent.start_tangent = ent.end_tangent = None
        refit(ent)
        return True
    c = curve_of(ent)
    if close:
        pts = [list(p) for p in c.ctrl]
        if len(pts) < 3:
            raise CommandError("The spline needs at least 3 control vertices to close.")
        assign_curve(ent, nurbs.from_control_points(pts, ent.degree, True, c.weights or None), False)
    else:
        uniq = c.ctrl[: len(c.ctrl) - c.degree]
        w = c.weights[: len(uniq)] if c.weights else None
        assign_curve(ent, nurbs.from_control_points(uniq, ent.degree, False, w), False)
    return True


def sp_reverse(ctx, led, ent):
    L.touch(ctx, led, ent)
    c = splineedit.reverse_curve(curve_of(ent))
    fit = list(reversed(ent.fit_points))
    t0, t1 = ent.start_tangent, ent.end_tangent
    assign_curve(ent, c, True)
    ent.fit_points = fit
    ent.start_tangent = [-t1[0], -t1[1], -t1[2] if len(t1) > 2 else 0.0] if t1 else None
    ent.end_tangent = [-t0[0], -t0[1], -t0[2] if len(t0) > 2 else 0.0] if t0 else None


def sp_polyline(ctx, led, ent, precision):
    if not 1 <= precision <= 99:
        raise CommandError("Requires an integer between 1 and 99.")
    c = curve_of(ent)
    spans = max(len(nurbs.spans(c)) - 1, 1)
    count = int(precision) * spans
    lo, hi = c.domain()
    pts = [nurbs.point_at(c, lo + (hi - lo) * k / count) for k in range(count + (0 if ent.closed else 1))]
    L.touch(ctx, led, ent)
    new = LwPolyline(vertices=[polyedit.vertex(p) for p in pts], closed=bool(ent.closed))
    for name in BASE_FIELDS:
        setattr(new, name, copy.deepcopy(getattr(ent, name)))
    ctx.d.ents[ent.handle] = new
    return new


def sp_join(ctx, led, ent, others):
    if ent.closed:
        raise CommandError("Cannot join to a closed spline.")
    items = []
    for o in others:
        if o.handle == ent.handle or ctx.locked(o):
            continue
        c = _any_curve(o)
        if c is not None:
            items.append((o, c))
    chain = curve_of(ent)
    used = []
    tol = 1e-6
    progress = True
    left = list(items)
    while progress and left:
        progress = False
        for item in list(left):
            o, c = item
            s, e = splineedit.ends(c)
            hs, he = splineedit.ends(chain)
            cand = None
            if math.dist(he, s) <= tol:
                cand = ("tail", c)
            elif math.dist(he, e) <= tol:
                cand = ("tail", splineedit.reverse_curve(c))
            elif math.dist(hs, e) <= tol:
                cand = ("head", c)
            elif math.dist(hs, s) <= tol:
                cand = ("head", splineedit.reverse_curve(c))
            if cand is None:
                continue
            deg = max(chain.degree, cand[1].degree)
            a = splineedit.elevate(chain, deg - chain.degree) if chain.degree < deg else chain
            b = splineedit.elevate(cand[1], deg - cand[1].degree) if cand[1].degree < deg else cand[1]
            chain = splineedit.join_curves(a, b) if cand[0] == "tail" else splineedit.join_curves(b, a)
            used.append(o)
            left.remove(item)
            progress = True
            break
    if not used:
        raise CommandError("No open curves connect to the end of the spline.")
    L.touch(ctx, led, ent)
    assign_curve(ent, chain, False)
    for o in used:
        L.drop(ctx, led, o)
    return len(used)


def _any_curve(o):
    if isinstance(o, Spline):
        if o.closed:
            return None
        try:
            return curve_of(o)
        except CommandError:
            return None
    if isinstance(o, Line):
        return splineedit.line_curve(o.start, o.end)
    if isinstance(o, Arc):
        return splineedit.arc_curve(o.center, o.radius, o.start_angle, geom.ccw_sweep(o.start_angle, o.end_angle))
    if isinstance(o, LwPolyline) and not o.closed and len(o.vertices) >= 2:
        return splineedit.polyline_curve(o.vertices, False)
    return None


def fd_add(ctx, led, ent, index, pt, before):
    pts = [list(p) for p in ent.fit_points]
    n = len(pts)
    if not 0 <= index < n:
        raise CommandError("Invalid fit point.")
    at = index if before else index + 1
    pts.insert(at, [float(pt[0]), float(pt[1]), 0.0])
    L.touch(ctx, led, ent)
    ent.fit_points = pts
    refit(ent)


def fd_delete(ctx, led, ent, index):
    pts = [list(p) for p in ent.fit_points]
    if not 0 <= index < len(pts):
        raise CommandError("Invalid fit point.")
    drop = {index}
    if index + 1 < len(pts) and math.dist(pts[index][:2], pts[index + 1][:2]) < 1e-9:
        drop.add(index + 1)
    elif index > 0 and math.dist(pts[index][:2], pts[index - 1][:2]) < 1e-9:
        drop.add(index - 1)
    rest = [p for i, p in enumerate(pts) if i not in drop]
    distinct = len({(round(p[0], 9), round(p[1], 9)) for p in rest})
    if distinct < _min_fit(ent):
        raise CommandError("The spline needs at least %d fit points." % _min_fit(ent))
    L.touch(ctx, led, ent)
    ent.fit_points = rest
    refit(ent)


def fd_kink(ctx, led, ent, pt):
    c = curve_of(ent)
    u = nurbs.closest_param(c, [pt[0], pt[1], 0.0])
    q = nurbs.point_at(c, u)
    params = [nurbs.closest_param(c, p) for p in ent.fit_points]
    at = 0
    for i, pu in enumerate(params):
        if pu <= u + 1e-12:
            at = i + 1
    pts = [list(p) for p in ent.fit_points]
    pts[at:at] = [list(q), list(q)]
    L.touch(ctx, led, ent)
    ent.fit_points = pts
    refit(ent)


def fd_move(ctx, led, ent, index, pt):
    if not 0 <= index < len(ent.fit_points):
        raise CommandError("Invalid fit point.")
    L.touch(ctx, led, ent)
    ent.fit_points[index] = [float(pt[0]), float(pt[1]), 0.0]
    refit(ent)


def fd_purge(ctx, led, ent):
    L.touch(ctx, led, ent)
    ent.fit_points = []
    ent.start_tangent = ent.end_tangent = None
    ent.fit_tolerance = 0.0


def fd_tangents(ctx, led, ent, start, end):
    if ent.closed:
        raise CommandError("A closed spline has no end tangents.")
    L.touch(ctx, led, ent)
    ent.start_tangent = start
    ent.end_tangent = end
    refit(ent)


def fd_tolerance(ctx, led, ent, tol):
    if tol < 0:
        raise CommandError("Requires a positive number.")
    L.touch(ctx, led, ent)
    ent.fit_tolerance = float(tol)
    refit(ent)


def cv_add(ctx, led, ent, pt):
    c = curve_of(ent)
    u = nurbs.closest_param(c, [pt[0], pt[1], 0.0])
    try:
        nc = splineedit.insert_control(c, u)
    except ValueError as err:
        raise CommandError(str(err))
    L.touch(ctx, led, ent)
    assign_curve(ent, nc, False)


def cv_delete(ctx, led, ent, index):
    c = curve_of(ent)
    try:
        nc = splineedit.delete_control(c, index)
    except ValueError as err:
        raise CommandError(str(err))
    L.touch(ctx, led, ent)
    assign_curve(ent, nc, False)


def cv_elevate(ctx, led, ent, order):
    c = curve_of(ent)
    cur = c.degree + 1
    if order <= cur or order > splineedit.MAX_DEGREE + 1:
        raise CommandError("Requires an order between %d and %d." % (cur + 1, splineedit.MAX_DEGREE + 1))
    try:
        nc = splineedit.elevate(c, order - cur)
    except ValueError as err:
        raise CommandError(str(err))
    L.touch(ctx, led, ent)
    nc = splineedit.tidy(nc)
    assign_curve(ent, nc, False)


def cv_move(ctx, led, ent, index, pt):
    if not 0 <= index < len(ent.control_points):
        raise CommandError("Invalid control vertex.")
    L.touch(ctx, led, ent)
    z = ent.control_points[index][2] if len(ent.control_points[index]) > 2 else 0.0
    for k in _twins(ent, index):
        ent.control_points[k] = [float(pt[0]), float(pt[1]), z]
    ent.fit_points = []
    ent.start_tangent = ent.end_tangent = None
    ent.fit_tolerance = 0.0


def _twins(ent, index):
    n = len(ent.control_points)
    if not ent.closed:
        return [index]
    uniq = n - ent.degree
    base = index if index < uniq else index - uniq
    out = [base]
    if base < ent.degree and base + uniq < n:
        out.append(base + uniq)
    return out


def cv_weight(ctx, led, ent, index, weight):
    if weight <= 0:
        raise CommandError("Requires a positive number.")
    if not 0 <= index < len(ent.control_points):
        raise CommandError("Invalid control vertex.")
    L.touch(ctx, led, ent)
    ws = list(ent.weights) if ent.weights else [1.0] * len(ent.control_points)
    for k in _twins(ent, index):
        ws[k] = float(weight)
    ent.weights = ws
    ent.fit_points = []
    ent.start_tangent = ent.end_tangent = None
    ent.fit_tolerance = 0.0


def _nearest(points, pt):
    return min(range(len(points)), key=lambda i: math.dist(points[i][:2], (pt[0], pt[1])))


def _sp_preview(ent, mutate):
    clone = Spline.from_dict(ent.to_dict())
    try:
        mutate(clone)
        c = curve_of(clone)
    except (CommandError, ValueError):
        return []
    return [curve_shape(c, clone.fit_points)]


def _move_loop(ctx, led, h, kind):
    idx = 0
    while True:
        ent = _live(ctx, h)
        pts = ent.fit_points if kind == "fit" else ent.control_points
        idx = max(0, min(idx, len(pts) - 1))
        p = pts[idx]

        def shape(cursor, ent=ent, idx=idx):
            def mut(c):
                if kind == "fit":
                    c.fit_points[idx] = [cursor[0], cursor[1], 0.0]
                    refit(c)
                else:
                    c.control_points[idx] = [cursor[0], cursor[1], 0.0]

            return _sp_preview(ent, mut) + _marker(pts[idx], _msize(ctx))

        pr = ctx.point("Specify new location", ["Next", "Previous", "Select point", "eXit"], base=p, default_text="N", jig=shape)
        r = yield pr
        if r.kind == "enter" or (r.kind == "keyword" and r.value == "Next"):
            idx = (idx + 1) % len(pts)
        elif r.kind == "keyword" and r.value == "Previous":
            idx = (idx - 1) % len(pts)
        elif r.kind == "keyword" and r.value == "Select point":
            s = yield ctx.point("Select point")
            if s.kind == "point":
                idx = _nearest(pts, s.value)
        elif r.kind == "point":
            try:
                (fd_move if kind == "fit" else cv_move)(ctx, led, ent, idx, r.value)
            except CommandError as err:
                ctx.say(str(err))
        else:
            return


def _fit_menu(ctx, h, stack):
    while True:
        ent = _live(ctx, h)
        if not ent.fit_points:
            return
        opts = ["Add", "Open" if ent.closed else "Close", "Delete", "Kink", "Move", "Purge", "Tangents", "toLerance", "eXit"]
        r = yield menu(ctx, "Enter a fit data option", opts, "eXit")
        if r.kind != "keyword" or r.value == "eXit":
            return
        w = r.value
        led = L.new()
        try:
            if w in ("Close", "Open"):
                sp_close(ctx, led, ent, w == "Close")
            elif w == "Purge":
                fd_purge(ctx, led, ent)
            elif w == "toLerance":
                cur = float(ent.fit_tolerance)
                t = yield ctx.number("Enter fit tolerance", default=cur, minimum=0, default_text=ctx.fd(cur))
                if t.kind == "number":
                    fd_tolerance(ctx, led, ent, t.value)
            elif w == "Tangents":
                if ent.closed:
                    ctx.say("A closed spline has no end tangents.")
                    continue
                s = yield ctx.point("Specify start tangent", ["System default"], base=ent.fit_points[0])
                if s.kind == "keyword":
                    t0 = None
                elif s.kind == "point":
                    t0 = _dir(ent.fit_points[0], s.value)
                else:
                    continue
                e = yield ctx.point("Specify end tangent", ["System default"], base=ent.fit_points[-1])
                if e.kind == "keyword":
                    t1 = None
                elif e.kind == "point":
                    t1 = _dir(ent.fit_points[-1], e.value)
                else:
                    continue
                fd_tangents(ctx, led, ent, t0, t1)
            elif w == "Delete":
                s = yield ctx.point("Select fit point", base=None)
                if s.kind == "point":
                    fd_delete(ctx, led, ent, _nearest(ent.fit_points, s.value))
            elif w == "Add":
                s = yield ctx.point("Select fit point")
                if s.kind != "point":
                    continue
                idx = _nearest(ent.fit_points, s.value)
                before = False
                while True:
                    pr = ctx.point("Specify new fit point", ["After", "Before"], base=ent.fit_points[idx], default_text="After", jig=lambda cursor, e=ent, i=idx, b=lambda: before: _sp_preview(e, lambda c: _add_to_clone(c, i, cursor, b())))
                    n = yield pr
                    if n.kind == "keyword":
                        before = n.value == "Before"
                        continue
                    if n.kind == "point":
                        fd_add(ctx, led, ent, idx, n.value, before)
                    break
            elif w == "Kink":
                s = yield ctx.point("Specify location for kink", jig=lambda cursor, e=ent: _sp_preview(e, lambda c: _kink_clone(c, cursor)))
                if s.kind == "point":
                    fd_kink(ctx, led, ent, s.value)
            elif w == "Move":
                yield from _move_loop(ctx, led, h, "fit")
        except CommandError as err:
            ctx.say(str(err))
            L.rollback(ctx, led)
            continue
        if not L.empty(led):
            stack.append(led)


def _add_to_clone(c, idx, pt, before):
    at = idx if before else idx + 1
    c.fit_points.insert(at, [pt[0], pt[1], 0.0])
    refit(c)


def _kink_clone(c, pt):
    cv = curve_of(c)
    q = nurbs.point_at(cv, nurbs.closest_param(cv, [pt[0], pt[1], 0.0]))
    params = [nurbs.closest_param(cv, p) for p in c.fit_points]
    u = nurbs.closest_param(cv, q)
    at = 0
    for i, pu in enumerate(params):
        if pu <= u + 1e-12:
            at = i + 1
    c.fit_points[at:at] = [list(q), list(q)]
    refit(c)


def _dir(frm, to):
    d = [to[0] - frm[0], to[1] - frm[1], 0.0]
    n = math.hypot(d[0], d[1])
    if n < EPS:
        raise CommandError("Invalid tangent.")
    return [d[0] / n, d[1] / n, 0.0]


def _vertex_menu(ctx, h, stack):
    while True:
        ent = _live(ctx, h)
        r = yield menu(ctx, "Enter a vertex editing option", ["Add", "Delete", "Elevate order", "Move", "Weight", "eXit"], "eXit")
        if r.kind != "keyword" or r.value == "eXit":
            return
        w = r.value
        led = L.new()
        try:
            if w == "Add":
                s = yield ctx.point("Specify a point on the spline")
                if s.kind == "point":
                    cv_add(ctx, led, ent, s.value)
            elif w == "Delete":
                s = yield ctx.point("Specify control vertex")
                if s.kind == "point":
                    cv_delete(ctx, led, ent, _nearest(ent.control_points, s.value))
            elif w == "Elevate order":
                cur = ent.degree + 1
                while True:
                    o = yield ctx.number("Enter new order", default=cur + 1, integer=True, default_text=str(cur + 1))
                    if o.kind != "number":
                        break
                    try:
                        cv_elevate(ctx, led, ent, int(o.value))
                        break
                    except CommandError as err:
                        ctx.say(str(err))
            elif w == "Move":
                yield from _move_loop(ctx, led, h, "ctrl")
            elif w == "Weight":
                s = yield ctx.point("Specify control vertex")
                if s.kind != "point":
                    continue
                i = _nearest(ent.control_points, s.value)
                cw = ent.weights[i] if ent.weights else 1.0
                v = yield ctx.number("Enter new weight", default=cw, default_text="%g" % cw)
                if v.kind == "number":
                    cv_weight(ctx, led, ent, i, v.value)
        except CommandError as err:
            ctx.say(str(err))
            L.rollback(ctx, led)
            continue
        if not L.empty(led):
            stack.append(led)


@command("splinedit", aliases=("spe",), group="modify", label="Spline", description="Edit splines: fit data, control vertices, close, join, convert to polyline, reverse.", menu="Modify > Object > Spline")
def splinedit_cmd(ctx):
    pre = [h for h in ctx.doc.selection if isinstance(ctx.d.get(h), Spline)]
    ctx.doc.selection = []
    ent = None
    if pre:
        ent = ctx.d.get(pre[0])
    while ent is None:
        r = yield ctx.entity("Select spline")
        if r.kind != "entity":
            return
        cand = pick_entity(ctx, r.value)
        try:
            _check_ready(ctx, cand)
        except CommandError as err:
            ctx.say(str(err))
            continue
        if not isinstance(cand, Spline):
            ctx.say(NOT_SPLINE)
            continue
        ent = cand
    h = ent.handle
    stack = []
    while True:
        ent = _live(ctx, h)
        if not isinstance(ent, Spline):
            return
        opts = ["Open" if ent.closed else "Close"] + ([] if ent.closed else ["Join"]) + (["Fit data"] if ent.fit_points else []) + ["Edit vertex", "convert to Polyline", "Reverse", "Undo", "eXit"]
        r = yield menu(ctx, "Enter an option", opts, "eXit")
        if r.kind != "keyword" or r.value == "eXit":
            return
        w = r.value
        led = L.new()
        try:
            if w in ("Close", "Open"):
                sp_close(ctx, led, ent, w == "Close")
            elif w == "Reverse":
                sp_reverse(ctx, led, ent)
            elif w == "Undo":
                if stack:
                    L.rollback(ctx, stack.pop())
                else:
                    ctx.say("Nothing to undo.")
                continue
            elif w == "Fit data":
                yield from _fit_menu(ctx, h, stack)
                continue
            elif w == "Edit vertex":
                yield from _vertex_menu(ctx, h, stack)
                continue
            elif w == "convert to Polyline":
                p = yield ctx.number("Specify a precision", default=10, integer=True, minimum=1, maximum=99, default_text="10")
                if p.kind == "number":
                    sp_polyline(ctx, led, ent, int(p.value))
                    stack.append(led)
                    return
                continue
            elif w == "Join":
                s = yield ctx.select("Select objects to join")
                if s.kind != "selection" or not s.value:
                    continue
                n = sp_join(ctx, led, ent, [ctx.d.get(x) for x in s.value if ctx.d.get(x) is not None])
                ctx.say("%d object%s joined to the spline" % (n, "" if n == 1 else "s"))
        except CommandError as err:
            ctx.say(str(err))
            L.rollback(ctx, led)
            continue
        if not L.empty(led):
            stack.append(led)


@executes("splinedit")
def splinedit_exec(ctx, args):
    ent = ctx.d.get(int(args.get("handle", 0)))
    _check_ready(ctx, ent)
    if not isinstance(ent, Spline):
        raise CommandError(NOT_SPLINE)
    led = L.new()
    opt = str(args.get("option", "")).lower().replace(" ", "")
    pt = args.get("point")
    idx = int(args.get("index", 0))
    if opt == "close":
        sp_close(ctx, led, ent, True)
    elif opt == "open":
        sp_close(ctx, led, ent, False)
    elif opt == "reverse":
        sp_reverse(ctx, led, ent)
    elif opt == "polyline":
        new = sp_polyline(ctx, led, ent, int(args.get("precision", 10)))
        return {"vertices": len(new.vertices)}
    elif opt == "join":
        return {"joined": sp_join(ctx, led, ent, [ctx.d.get(int(x)) for x in args.get("others", []) if ctx.d.get(int(x)) is not None])}
    elif opt == "fit":
        act = str(args.get("action", "")).lower()
        if not ent.fit_points:
            raise CommandError("The spline has no fit data.")
        if act == "add":
            fd_add(ctx, led, ent, idx, pt, bool(args.get("before")))
        elif act == "delete":
            fd_delete(ctx, led, ent, idx)
        elif act == "kink":
            fd_kink(ctx, led, ent, pt)
        elif act == "move":
            fd_move(ctx, led, ent, idx, pt)
        elif act == "purge":
            fd_purge(ctx, led, ent)
        elif act == "tangents":
            t0 = _dir(ent.fit_points[0], args["start"]) if args.get("start") else None
            t1 = _dir(ent.fit_points[-1], args["end"]) if args.get("end") else None
            fd_tangents(ctx, led, ent, t0, t1)
        elif act == "tolerance":
            fd_tolerance(ctx, led, ent, float(args.get("tolerance", 0.0)))
        elif act == "close":
            sp_close(ctx, led, ent, True)
        elif act == "open":
            sp_close(ctx, led, ent, False)
        else:
            raise CommandError("Invalid option keyword.")
    elif opt == "vertex":
        act = str(args.get("action", "")).lower()
        if act == "add":
            cv_add(ctx, led, ent, pt)
        elif act == "delete":
            cv_delete(ctx, led, ent, idx)
        elif act == "elevate":
            cv_elevate(ctx, led, ent, int(args.get("order", ent.degree + 2)))
        elif act == "move":
            cv_move(ctx, led, ent, idx, pt)
        elif act == "weight":
            cv_weight(ctx, led, ent, idx, float(args.get("weight", 1.0)))
        else:
            raise CommandError("Invalid option keyword.")
    else:
        raise CommandError("Invalid option keyword.")
    return {"handle": ent.handle}
