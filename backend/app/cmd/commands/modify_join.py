import math

from app.cmd import jig
from app.cmd.commands.modify import LOCKED_MSG, targets
from app.cmd.commands.modify_trim import replace_entity, unpack
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.doc import curveops as co
from app.doc import geom, nurbs
from app.doc.entities import Arc, Circle, Ellipse, Line

TAU = geom.TAU
JOIN_TOL = 1e-6
JOINABLE = ("line", "arc", "ellipse", "lwpolyline", "spline")
LENGTHENABLE = ("line", "arc", "ellipse", "lwpolyline", "spline")
NOT_CONNECTED = "Objects are not connected."
TOO_FEW = "Select at least two objects to join."
PART_MSG = "Only part of a polyline connects; join it whole or explode it first."


def _line_dist(ln, p):
    if ln.L <= 0:
        return geom.dist(ln.p0, p)
    return abs(ln.dx * (p[1] - ln.p0[1]) - ln.dy * (p[0] - ln.p0[0])) / ln.L


def _merge_lines(src, others, tol):
    base = co.path_of(src).segs[0]
    ts = [0.0, base.L]
    used = []
    ux, uy = base.dx / base.L, base.dy / base.L
    for e in others:
        if e.kind != "line":
            continue
        q = co.path_of(e).segs[0]
        if _line_dist(base, q.p0) <= tol and _line_dist(base, q.p1) <= tol:
            for p in (q.p0, q.p1):
                ts.append((p[0] - base.p0[0]) * ux + (p[1] - base.p0[1]) * uy)
            used.append(e)
    if not used:
        return None, []
    a, b = min(ts), max(ts)
    z = base.p0[2]
    new = Line(start=[base.p0[0] + ux * a, base.p0[1] + uy * a, z], end=[base.p0[0] + ux * b, base.p0[1] + uy * b, z])
    return co.entity_props(src, new), used


def _arc_merge_math(a0, s0, other, tol_ang):
    A, S = a0, s0
    for B, T in other:
        os_ = (B - A) % TAU
        ob = (A - B) % TAU
        if os_ <= S + tol_ang:
            S = max(S, os_ + T)
        elif ob <= T + tol_ang:
            S = max(T, ob + S)
            A = B
        else:
            app = os_ + T
            pre = ob + S
            if app <= pre:
                S = app
            else:
                A = B
                S = pre
        if S >= TAU - tol_ang:
            return A, TAU
    return A, S


def _merge_arcs(src, others, tol):
    used = []
    spans = []
    for e in others:
        if e.kind != "arc":
            continue
        if geom.dist(e.center, src.center) <= tol and abs(e.radius - src.radius) <= tol:
            spans.append((e.start_angle, geom.ccw_sweep(e.start_angle, e.end_angle)))
            used.append(e)
    if not used:
        return None, []
    A, S = _arc_merge_math(src.start_angle, geom.ccw_sweep(src.start_angle, src.end_angle), spans, tol / max(src.radius, tol))
    if S >= TAU - 1e-12:
        new = Circle(center=list(src.center), radius=src.radius)
    else:
        new = Arc(center=list(src.center), radius=src.radius, start_angle=geom.norm_angle(A), end_angle=geom.norm_angle(A + S))
    return co.entity_props(src, new), used


def _same_ellipse(a, b, tol):
    if geom.dist(a.center, b.center) > tol:
        return False
    if abs(a.ratio - b.ratio) > 1e-9:
        return False
    return abs(a.major[0] - b.major[0]) <= tol and abs(a.major[1] - b.major[1]) <= tol


def _merge_ellipses(src, others, tol):
    used = []
    spans = []
    for e in others:
        if e.kind == "ellipse" and _same_ellipse(src, e, tol):
            if abs(e.end_param - e.start_param) >= TAU - 1e-12:
                continue
            spans.append((e.start_param, geom.ccw_sweep(e.start_param, e.end_param)))
            used.append(e)
    if not used:
        return None, []
    A, S = _arc_merge_math(src.start_param, geom.ccw_sweep(src.start_param, src.end_param), spans, 1e-9)
    if S >= TAU - 1e-12:
        new = Ellipse(center=list(src.center), major=list(src.major), ratio=src.ratio, start_param=0.0, end_param=TAU)
    else:
        new = Ellipse(center=list(src.center), major=list(src.major), ratio=src.ratio, start_param=geom.norm_angle(A), end_param=geom.norm_angle(A + S))
    return co.entity_props(src, new), used


class JoinPiece:
    def __init__(self, ent):
        self.ent = ent
        self.path = co.path_of(ent)
        self.segs = list(self.path.segs)

    def start(self):
        return self.segs[0].pt(0.0)

    def end(self):
        return self.segs[-1].pt(1.0)

    def oriented(self, forward):
        return list(self.segs) if forward else [s.rev() for s in reversed(self.segs)]


def _chain(src_segs, pieces, tol):
    chain = list(src_segs)
    used = []
    changed = True
    while changed:
        changed = False
        for pc in pieces:
            if pc in used:
                continue
            ce, cs = chain[-1].pt(1.0), chain[0].pt(0.0)
            if geom.dist(pc.start(), ce) <= tol:
                chain = chain + pc.oriented(True)
            elif geom.dist(pc.end(), ce) <= tol:
                chain = chain + pc.oriented(False)
            elif geom.dist(pc.end(), cs) <= tol:
                chain = pc.oriented(True) + chain
            elif geom.dist(pc.start(), cs) <= tol:
                chain = pc.oriented(False) + chain
            else:
                continue
            used.append(pc)
            changed = True
    return chain, used


def _interior_touch(ents, tol) -> bool:
    for e in ents:
        if e.kind != "lwpolyline":
            continue
        verts = [v["p"] for v in e.vertices]
        for p in verts[1:-1]:
            for o in ents:
                if o is e:
                    continue
                path = co.path_of_safe(o)
                if path is None or path.closed:
                    continue
                if geom.dist(p, path.start_point()) <= tol or geom.dist(p, path.end_point()) <= tol:
                    return True
    return False


def label_of(ent) -> str:
    return {"lwpolyline": "polyline", "spline": "spline", "line": "line", "arc": "arc", "circle": "circle", "ellipse": "ellipse"}.get(ent.kind, ent.kind)


def join_entities(ctx, ents, tol, close=False):
    open_ents = []
    for e in ents:
        if e.kind not in JOINABLE:
            raise CommandError("Cannot join that object.")
        p = co.path_of_safe(e)
        if p is None or p.closed:
            continue
        open_ents.append(e)
    if not open_ents:
        raise CommandError("Select open objects to join.")
    src = open_ents[0]
    others = open_ents[1:]
    if close:
        if src.kind == "arc":
            new = Circle(center=list(src.center), radius=src.radius)
            ctx.say("The arc is now a circle.")
            return replace_pair(ctx, src, co.entity_props(src, new), [])
        if src.kind == "ellipse":
            new = Ellipse(center=list(src.center), major=list(src.major), ratio=src.ratio, start_param=0.0, end_param=TAU)
            ctx.say("The elliptical arc is now an ellipse.")
            return replace_pair(ctx, src, co.entity_props(src, new), [])
        raise CommandError("Only an arc or an elliptical arc can be closed.")
    if not others:
        raise CommandError(TOO_FEW)
    current = src
    used = []
    if src.kind == "line":
        merged, taken = _merge_lines(src, others, tol)
    elif src.kind == "arc":
        merged, taken = _merge_arcs(src, others, tol)
    elif src.kind == "ellipse":
        merged, taken = _merge_ellipses(src, others, tol)
    else:
        merged, taken = None, []
    if merged is not None:
        current = merged
        used.extend(taken)
        merged.handle = src.handle
        merged.owner = src.owner
    rest = [e for e in others if e not in used]
    chain_used = []
    result = current
    if rest:
        pieces = [JoinPiece(e) for e in rest]
        base = JoinPiece(current)
        chain, chain_used = _chain(base.segs, pieces, tol)
        if chain_used:
            closed = len(chain) >= 2 and geom.dist(chain[-1].pt(1.0), chain[0].pt(0.0)) <= tol and all(s.kind in ("line", "arc") for s in chain)
            built = co.build_entity(src, chain, closed)
            if built is None or not built.valid():
                raise CommandError("The objects cannot be joined.")
            result = built
            used.extend(p.ent for p in chain_used)
    if not used:
        if _interior_touch(open_ents, tol):
            raise CommandError(PART_MSG)
        raise CommandError(NOT_CONNECTED)
    result.handle = src.handle
    result.owner = src.owner
    left = [e for e in others if e not in used]
    if left and _interior_touch(open_ents, tol):
        ctx.say(PART_MSG)
    elif left:
        ctx.say("%d object(s) were not connected." % len(left))
    ctx.say("%d object(s) joined into %s %s." % (len(used) + 1, "an" if label_of(result)[0] in "aeiou" else "a", label_of(result)))
    return replace_pair(ctx, src, result, used)


def replace_pair(ctx, src, result, removed):
    replace_entity(ctx, src, result)
    for e in removed:
        if ctx.d.get(e.handle) is not None:
            ctx.d.erase_entity(e.handle)
    return {"handle": src.handle, "removed": [e.handle for e in removed], "kind": result.kind}


def _unlocked(ctx, handles):
    out = []
    for h in handles:
        e = ctx.d.get(h)
        if e is not None and not ctx.locked(e):
            out.append(e)
    return out


@command("join", aliases=("j",), group="modify", label="Join", description="Merge connected lines, arcs, polylines, splines, elliptical arcs; close a single arc.", menu="Modify > Join")
def join(ctx):
    s = yield ctx.select("Select source object or multiple objects to join at once")
    if s.kind != "selection" or not s.value:
        return
    ents = _unlocked(ctx, s.value)
    if not ents:
        ctx.say(LOCKED_MSG)
        return
    tol = JOIN_TOL
    close = False
    if len(ents) == 1:
        e = ents[0]
        if e.kind in ("arc", "ellipse"):
            while True:
                r = yield ctx.entity("Select arcs to join to source", ["cLose"])
                if r.kind == "entity":
                    h, _pt, _sh = unpack(r.value)
                    x = ctx.d.get(h)
                    if x is not None and x not in ents and not ctx.locked(x):
                        ents.append(x)
                    continue
                if r.kind == "keyword":
                    close = True
                break
        else:
            s2 = yield ctx.select("Select objects to join to source")
            if s2.kind == "selection":
                for x in _unlocked(ctx, s2.value):
                    if x not in ents:
                        ents.append(x)
    try:
        join_entities(ctx, ents, tol, close)
    except CommandError as err:
        ctx.say(str(err))


@executes("join")
def join_exec(ctx, args):
    handles = targets(ctx, args)
    ents = _unlocked(ctx, handles)
    if not ents:
        raise CommandError(LOCKED_MSG if handles else TOO_FEW)
    tol = float(args.get("tolerance", JOIN_TOL))
    return join_entities(ctx, ents, tol, bool(args.get("close")))


def _lengthen_check(ent):
    if ent.kind not in LENGTHENABLE:
        raise CommandError("Cannot lengthen that object.")
    path = co.path_of(ent)
    if path is None:
        raise CommandError("Cannot lengthen that object.")
    if path.closed:
        raise CommandError("Cannot lengthen a closed %s." % {"ellipse": "ellipse", "spline": "spline"}.get(ent.kind, "object"))
    return path


def current_report(ctx, ent):
    path = co.path_of_safe(ent)
    if path is None or ent.kind in ("circle",):
        ctx.say("Cannot measure that object.")
        return
    ctx.say("Current length: %s" % ctx.fd(path.total))
    if ent.kind == "arc":
        ctx.say("Included angle: %s" % ctx.fa(geom.ccw_sweep(ent.start_angle, ent.end_angle)))


NEG_MSG = "Lengthening would make the object zero length or negative."


def lengthen_entity(ctx, ent, at_end, delta=None, delta_angle=None):
    path = _lengthen_check(ent)
    tol = ctx.d.tolerances["absolute"]
    k = ent.kind
    if k == "line":
        if delta_angle is not None:
            raise CommandError("The Angle option applies to arcs only.")
        seg = path.segs[0]
        new_len = seg.L + delta
        if new_len < -tol:
            raise CommandError(NEG_MSG)
        if new_len <= tol:
            raise CommandError("Zero-length line.")
        ux, uy = seg.dx / seg.L, seg.dy / seg.L
        if at_end:
            ns = co.LineSegment(seg.p0, [seg.p0[0] + ux * new_len, seg.p0[1] + uy * new_len, seg.p1[2]])
        else:
            ns = co.LineSegment([seg.p1[0] - ux * new_len, seg.p1[1] - uy * new_len, seg.p0[2]], seg.p1)
        return co.build_entity(ent, [ns], False)
    if k == "arc":
        seg = path.segs[0]
        ds = delta_angle if delta_angle is not None else delta / seg.r
        new_sweep = seg.sweep + ds
        if seg.r * new_sweep < -tol:
            raise CommandError(NEG_MSG)
        if new_sweep <= tol / seg.r or new_sweep >= TAU - 1e-9:
            raise CommandError("The new arc would be zero length or a full circle.")
        if at_end:
            ns = co.ArcSegment(seg.c, seg.r, seg.a0, new_sweep)
        else:
            ns = co.ArcSegment(seg.c, seg.r, seg.a0 - ds, new_sweep)
        return co.build_entity(ent, [ns], False)
    if delta_angle is not None:
        raise CommandError("The Angle option applies to arcs only.")
    if k == "lwpolyline":
        work = path if at_end else path.reversed()
        last = work.segs[-1]
        if last.kind != "line":
            raise CommandError("Cannot lengthen a polyline whose end segment is an arc.")
        new_len = last.L + delta
        if new_len < -tol:
            raise CommandError(NEG_MSG)
        if new_len <= tol:
            raise CommandError("Zero-length line.")
        ux, uy = last.dx / last.L, last.dy / last.L
        ns = co.LineSegment(last.p0, [last.p0[0] + ux * new_len, last.p0[1] + uy * new_len, last.p1[2]], last.sw, last.ew)
        segs = list(work.segs[:-1]) + [ns]
        if not at_end:
            segs = co.CurvePath(segs, False).reversed().segs
        return co.build_entity(ent, segs, False)
    if k == "ellipse":
        seg = path.segs[0]
        work = seg if at_end else seg.rev()
        total = work.length()
        new_len = total + delta
        if new_len < -tol:
            raise CommandError(NEG_MSG)
        if new_len <= tol:
            raise CommandError("The new arc would be zero length or a full circle.")
        if delta < 0:
            lo, hi = 0.0, 1.0
            for _ in range(80):
                mid = (lo + hi) / 2.0
                if work.length(0.0, mid) < new_len:
                    lo = mid
                else:
                    hi = mid
            nw = work.sub(0.0, (lo + hi) / 2.0)
        else:
            ext = co.extension_seg(co.CurvePath([work], False), True)
            if ext is None:
                raise CommandError("The new arc would be zero length or a full circle.")
            lo, hi = 0.0, 1.0
            extra = delta
            if ext.length() <= extra:
                raise CommandError("The new arc would be zero length or a full circle.")
            for _ in range(80):
                mid = (lo + hi) / 2.0
                if ext.length(0.0, mid) < extra:
                    lo = mid
                else:
                    hi = mid
            nw = co.EllipseSegment(work.c, work.ux, work.uy, work.ratio, work.t0, work.sweep + ext.sweep * (lo + hi) / 2.0)
        if nw.sa >= TAU - 1e-9:
            raise CommandError("The new arc would be zero length or a full circle.")
        if not at_end:
            nw = nw.rev()
        return co.build_entity(ent, [nw], False)
    curve = co.spline_piece(path.segs[0])
    if delta < 0:
        lo, hi = curve.domain()
        if curve_len_check(curve, delta, tol):
            raise CommandError(NEG_MSG)
        if at_end:
            t = co.t_at_length(curve, hi, delta)
            nc = co.sub_curve(curve, lo, t)
        else:
            t = co.t_at_length(curve, lo, -delta)
            nc = co.sub_curve(curve, t, hi)
    else:
        nc = co.extend_straight(curve, at_end, delta)
    return co.entity_props(ent, co.spline_entity(nc, False))


def curve_len_check(curve, delta, tol) -> bool:
    return co.curve_length(curve) + delta <= tol


def dynamic_entity(ctx, ent, at_end, pt):
    path = _lengthen_check(ent)
    k = ent.kind
    work = path if at_end else path.reversed()
    last = work.segs[-1]
    if k == "arc":
        seg = path.segs[0]
        ang = geom.angle_of(seg.c, pt)
        if at_end:
            new_sweep = geom.ccw_sweep(seg.a0, ang)
        else:
            new_sweep = geom.ccw_sweep(ang, seg.a0 + seg.sweep)
        return lengthen_entity(ctx, ent, at_end, delta_angle=new_sweep - seg.sweep)
    if k == "ellipse":
        seg = path.segs[0]
        t = seg.param_of_point(pt)
        new_sweep = geom.ccw_sweep(seg.t0, t) if at_end else geom.ccw_sweep(t, seg.t0 + seg.sweep)
        nw = co.EllipseSegment(seg.c, seg.ux, seg.uy, seg.ratio, seg.t0 if at_end else t, new_sweep)
        return co.build_entity(ent, [nw], False)
    if k == "spline":
        curve = co.spline_piece(path.segs[0])
        lo, hi = curve.domain()
        tan = last.tan_at(1.0)
        e = last.pt(1.0)
        proj = (pt[0] - e[0]) * tan[0] + (pt[1] - e[1]) * tan[1]
        if proj > 0:
            return lengthen_entity(ctx, ent, at_end, delta=proj)
        s, q, _d = path.closest(pt)
        cut = co.curve_length(curve, nurbs.closest_param(curve, pt), hi) if at_end else co.curve_length(curve, lo, nurbs.closest_param(curve, pt))
        return lengthen_entity(ctx, ent, at_end, delta=-cut)
    if last.kind != "line":
        raise CommandError("Cannot lengthen a polyline whose end segment is an arc.")
    e = last.pt(1.0)
    proj = (pt[0] - last.p0[0]) * last.dx / last.L + (pt[1] - last.p0[1]) * last.dy / last.L
    return lengthen_entity(ctx, ent, at_end, delta=proj - last.L)


def choose_end(ent, pick) -> bool:
    path = co.path_of(ent)
    return geom.dist(pick, path.end_point()) <= geom.dist(pick, path.start_point())


def _mem(ctx, key, default):
    return ctx.mem.get(key, default)


def _lengthen_commit(ctx, log, ent, new):
    if new is None or not new.valid():
        raise CommandError("The object cannot be lengthened that way.")
    from app.cmd.commands.modify_trim import snap_rows

    log.append(snap_rows(ctx, [ent.handle]))
    replace_entity(ctx, ent, new)


def _lengthen_delta(ctx, ent, at_end, mode, value, as_angle):
    path = _lengthen_check(ent)
    if mode == "delta":
        if as_angle:
            return lengthen_entity(ctx, ent, at_end, delta_angle=value)
        return lengthen_entity(ctx, ent, at_end, delta=value)
    if mode == "percent":
        if not value > 0:
            raise CommandError("Requires a positive number.")
        return lengthen_entity(ctx, ent, at_end, delta=path.total * (value / 100.0 - 1.0))
    if not value > 0:
        raise CommandError("Value must be positive and nonzero.")
    if as_angle:
        if ent.kind != "arc":
            raise CommandError("The Angle option applies to arcs only.")
        return lengthen_entity(ctx, ent, at_end, delta_angle=value - path.segs[0].sa)
    return lengthen_entity(ctx, ent, at_end, delta=value - path.total)


@command("lengthen", aliases=("len",), group="modify", label="Lengthen", description="Change object length by delta, percent, total or dynamic.", menu="Modify > Lengthen")
def lengthen(ctx):
    from app.cmd.commands.modify_trim import restore_rows

    mode = None
    value = None
    as_angle = False
    while mode is None:
        p = ctx.entity("Select an object to measure", ["DElta", "Percent", "Total", "DYnamic"])
        p.default = "DYnamic"
        p.default_text = "DYnamic"
        r = yield p
        if r.kind == "entity":
            h, _pt, _s = unpack(r.value)
            e = ctx.d.get(h)
            if e is not None:
                current_report(ctx, e)
            continue
        if r.kind != "keyword":
            return
        mode = {"DElta": "delta", "Percent": "percent", "Total": "total", "DYnamic": "dynamic"}[r.value]
    if mode == "delta":
        while True:
            q = yield ctx.distance("Enter delta length", ["Angle"], default=_mem(ctx, "len_delta", 0.0))
            if q.kind == "keyword":
                a = yield ctx.angle("Enter delta angle", default=_mem(ctx, "len_delta_angle", 0.0), absolute=False)
                if a.kind != "number":
                    return
                value, as_angle = a.value, True
                ctx.mem["len_delta_angle"] = value
                break
            if q.kind == "number":
                value = q.value
                ctx.mem["len_delta"] = value
                break
            return
    elif mode == "percent":
        q = yield ctx.number("Enter percentage length", default=_mem(ctx, "len_pct", 100.0), positive=True, default_text=ctx.fd(_mem(ctx, "len_pct", 100.0)))
        if q.kind != "number":
            return
        value = q.value
        ctx.mem["len_pct"] = value
    elif mode == "total":
        while True:
            q = yield ctx.distance("Specify total length", ["Angle"], default=_mem(ctx, "len_total", 1.0), positive=True)
            if q.kind == "keyword":
                a = yield ctx.angle("Specify total angle", default=_mem(ctx, "len_total_angle", math.pi / 2.0), absolute=False)
                if a.kind != "number":
                    return
                value, as_angle = a.value, True
                ctx.mem["len_total_angle"] = value
                break
            if q.kind == "number":
                value = q.value
                ctx.mem["len_total"] = value
                break
            return
    log = []
    while True:
        r = yield ctx.entity("Select an object to change", ["Undo"])
        if r.kind == "keyword":
            if log:
                restore_rows(ctx, log.pop(), [])
            else:
                ctx.say("Nothing to undo.")
            continue
        if r.kind != "entity":
            return
        h, pick, _s = unpack(r.value)
        ent = ctx.d.get(h)
        if ent is None:
            continue
        if ctx.locked(ent):
            ctx.say(LOCKED_MSG)
            continue
        try:
            at_end = choose_end(ent, pick) if _lengthen_check(ent) else True
            if mode == "dynamic":
                q = yield ctx.point("Specify new end point", jig=lambda c, e=ent, a=at_end: _dyn_jig(ctx, e, a, c))
                if q.kind != "point":
                    continue
                new = dynamic_entity(ctx, ent, at_end, q.value)
            else:
                new = _lengthen_delta(ctx, ent, at_end, mode, value, as_angle)
            _lengthen_commit(ctx, log, ent, new)
        except CommandError as err:
            ctx.say(str(err))


def _dyn_jig(ctx, ent, at_end, pt):
    try:
        new = dynamic_entity(ctx, ent, at_end, pt)
    except (CommandError, ValueError, ZeroDivisionError):
        return []
    return jig.entity_items([new], ctx.d) if new is not None else []


@executes("lengthen")
def lengthen_exec(ctx, args):
    ent = ctx.d.get(int(args["handle"])) if "handle" in args else None
    if ent is None:
        raise CommandError("Select an object to change.")
    if ctx.locked(ent):
        raise CommandError(LOCKED_MSG)
    mode = str(args.get("mode", "delta")).lower()
    path = _lengthen_check(ent)
    pick = geom.as_pt(args["pick"]) if "pick" in args else path.end_point()
    at_end = choose_end(ent, pick)
    if mode == "dynamic":
        new = dynamic_entity(ctx, ent, at_end, geom.as_pt(args["to"]))
    elif mode in ("delta", "percent", "total"):
        value = float(args["value"])
        as_angle = bool(args.get("angle"))
        if as_angle:
            value = math.radians(value)
        new = _lengthen_delta(ctx, ent, at_end, mode, value, as_angle)
    else:
        raise CommandError("Mode must be delta, percent, total or dynamic.")
    if new is None or not new.valid():
        raise CommandError("The object cannot be lengthened that way.")
    replace_entity(ctx, ent, new)
    return {"handle": ent.handle}
