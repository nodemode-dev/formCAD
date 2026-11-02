import math

from app.cmd import grips, jig
from app.cmd.commands.modify import LOCKED_MSG
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.doc import curveops as co
from app.doc import geom
from app.doc.entities import entity_from_dict

TRIMMABLE = ("line", "arc", "circle", "ellipse", "lwpolyline", "polyline3d", "spline")
EXTENDABLE = ("line", "arc", "ellipse", "lwpolyline", "polyline3d", "spline")
OFFSETTABLE = ("line", "circle", "arc", "ellipse", "lwpolyline", "spline", "xline", "ray")
BREAKABLE = ("line", "arc", "circle", "ellipse", "lwpolyline", "polyline3d", "spline")
NO_INTERSECT_TRIM = "Object does not intersect a cutting edge."
NO_INTERSECT_EXTEND = "Object does not intersect an edge."
MAX_FENCE_POINTS = 10000


def big_of(ctx) -> float:
    box = ctx.d.extents()
    if not box:
        return co.BIG_DEFAULT
    return max(co.BIG_DEFAULT, 1e3 * math.hypot(box[2] - box[0], box[3] - box[1]))


def unpack(value):
    h = int(value["handle"])
    pt = [float(value["point"][0]), float(value["point"][1]), 0.0]
    return h, pt, bool(value.get("shift"))


def reposition(ctx, handle, owner, index):
    lst = ctx.d.spaces[owner]
    if handle in lst:
        lst.remove(handle)
    lst.insert(max(0, min(index, len(lst))), handle)


def replace_entity(ctx, old, new):
    d = ctx.d
    if type(new) is type(old):
        grips._assign(d.modify(old.handle), new)
        return old.handle
    lst = d.spaces[old.owner]
    idx = lst.index(old.handle) if old.handle in lst else len(lst)
    owner, handle = old.owner, old.handle
    d.erase_entity(handle)
    d.add_entity(new, owner, handle=handle)
    reposition(ctx, handle, owner, idx)
    return handle


def add_after(ctx, new, after_handle, owner) -> int:
    d = ctx.d
    lst = d.spaces[owner]
    idx = lst.index(after_handle) + 1 if after_handle in lst else len(lst)
    h = d.add_entity(new, owner)
    reposition(ctx, h, owner, idx)
    return h


def snap_rows(ctx, handles):
    rows = []
    for h in handles:
        e = ctx.d.get(h)
        if e is None:
            continue
        lst = ctx.d.spaces[e.owner]
        rows.append({"data": e.to_dict(), "index": lst.index(h) if h in lst else len(lst)})
    return rows


def restore_rows(ctx, rows, created):
    d = ctx.d
    for h in created:
        if d.get(h) is not None:
            d.erase_entity(h)
    for r in rows:
        ent = entity_from_dict(r["data"])
        cur = d.get(ent.handle)
        if cur is not None:
            replace_entity(ctx, cur, ent)
        elif d.restore_entity(ent):
            reposition(ctx, ent.handle, ent.owner, r["index"])


def edge_entities(ctx, handles=None):
    if handles is None:
        ents = list(ctx.visible_entities())
    else:
        ents = []
        for h in handles:
            e = ctx.d.get(h)
            if e is not None and ctx.d.visible(e):
                ents.append(e)
    return [e for e in ents if e.kind in co.CURVE_KINDS]


def _cut_list(path, hits, tol):
    out = []
    n = path.n
    sp, ep = path.start_point(), path.end_point()
    for s, p in hits:
        if path.closed:
            s = s % n
            if n - s < 1e-12:
                s = 0.0
        elif geom.dist(p, sp) <= tol or geom.dist(p, ep) <= tol:
            continue
        out.append(s)
    return co.dedupe_params(out, 1e-9)


def collect_cuts(ctx, ent, path, edge_ents, ext_mode):
    tol = ctx.d.tolerances["absolute"]
    big = big_of(ctx)
    box = path.bbox()
    hits = []
    for e in edge_ents:
        if e.handle == ent.handle:
            continue
        if not ext_mode:
            b = e.bounds()
            if b is not None and co.boxes_apart(b, box, tol + 1e-9):
                continue
        q = co.path_of_safe(e) if e.kind not in ("ray", "xline") else co.path_of(e, big)
        if q is None:
            continue
        for s, _sb, p in co.path_hits(path, q, False, ext_mode, tol):
            hits.append((s, p))
    if path.n > 1:
        for sa, sb, p in co.path_hits(path, path, False, False, tol, same=True):
            hits.append((sa, p))
            hits.append((sb, p))
    return _cut_list(path, hits, tol)


def kind_label(ent) -> str:
    return {"lwpolyline": "Polyline", "polyline3d": "Polyline", "circle": "Circle", "ellipse": "Ellipse", "spline": "Spline"}.get(ent.kind, "Object")


def trim_entity(ctx, ent, pick, edge_ents, ext_mode, quick):
    if ent.kind not in TRIMMABLE:
        raise CommandError("Cannot trim that object.")
    path = co.path_of(ent)
    if path is None:
        raise CommandError("Cannot trim that object.")
    cuts = collect_cuts(ctx, ent, path, edge_ents, ext_mode)
    if not cuts:
        if quick:
            return []
        raise CommandError(NO_INTERSECT_TRIM)
    n = path.n
    sp = path.closest(pick)[0]
    pieces = []
    if path.closed:
        if len(cuts) < 2:
            raise CommandError("%s must intersect cutting edges at two or more points." % kind_label(ent))
        sp = sp % n
        lo_i = max([i for i, c in enumerate(cuts) if c <= sp], default=len(cuts) - 1)
        lo = cuts[lo_i]
        hi = cuts[(lo_i + 1) % len(cuts)]
        pieces.append(path.slice(hi, lo))
    else:
        lows = [c for c in cuts if c < sp]
        highs = [c for c in cuts if c >= sp]
        if lows:
            pieces.append(path.slice(0.0, max(lows)))
        if highs:
            pieces.append(path.slice(min(highs), float(n)))
    out = []
    for segs in pieces:
        if not segs:
            continue
        e = co.build_entity(ent, segs, False)
        if e is None or not e.valid():
            continue
        out.append(e)
    return out


def extend_entity(ctx, ent, pick, edge_ents, ext_mode):
    if ent.kind not in EXTENDABLE:
        raise CommandError("Cannot extend that object.")
    path = co.path_of(ent)
    if path is None:
        raise CommandError("Cannot extend that object.")
    if path.closed:
        raise CommandError("Cannot extend a closed %s." % kind_label(ent).lower())
    tol = ctx.d.tolerances["absolute"]
    big = big_of(ctx)
    at_end = geom.dist(pick, path.end_point()) <= geom.dist(pick, path.start_point())
    work = path if at_end else path.reversed()
    ext = co.extension_seg(work, True, big)
    if ext is None:
        raise CommandError(NO_INTERSECT_EXTEND)
    extp = co.CurvePath([ext], False)
    ext_len = ext.length()
    best = None
    for e in edge_ents:
        if e.handle == ent.handle:
            continue
        q = co.path_of_safe(e) if e.kind not in ("ray", "xline") else co.path_of(e, big)
        if q is None:
            continue
        for s, _sb, p in co.path_hits(extp, q, False, ext_mode, tol):
            if s * ext_len <= max(tol * 10.0, 1e-7):
                continue
            if best is None or s < best[0]:
                best = (s, p)
    if best is None:
        raise CommandError(NO_INTERSECT_EXTEND)
    s, hit = best
    last = work.segs[-1]
    if last.kind == "spline":
        dist = geom.dist(last.pt(1.0), hit)
        curve = co.spline_piece(path.segs[0])
        newc = co.extend_straight(curve, at_end, dist)
        return co.entity_props(ent, co.spline_entity(newc, False))
    if last.kind == "line":
        new_last = co.LineSegment(last.p0, [hit[0], hit[1], last.p1[2]], last.sw, last.ew)
    elif last.kind == "arc":
        new_last = co.ArcSegment(last.c, last.r, last.a0, last.sweep + ext.sweep * s, last.sw, last.ew)
    else:
        new_last = co.EllipseSegment(last.c, last.ux, last.uy, last.ratio, last.t0, last.sweep + ext.sweep * s)
    segs = list(work.segs[:-1]) + [new_last]
    if not at_end:
        segs = co.CurvePath(segs, False).reversed().segs
    res = co.build_entity(ent, segs, False)
    if res is None or not res.valid():
        raise CommandError(NO_INTERSECT_EXTEND)
    return res


def apply_result(ctx, ent, results):
    d = ctx.d
    owner = ent.owner
    created = []
    if not results:
        d.erase_entity(ent.handle)
        return created, [ent.handle]
    replace_entity(ctx, ent, results[0])
    prev = ent.handle
    for extra in results[1:]:
        prev = add_after(ctx, extra, prev, owner)
        created.append(prev)
    return created, []


class EditLog:
    def __init__(self, ctx):
        self.ctx = ctx
        self.rows = []

    def push(self, rows, created):
        self.rows.append((rows, created))

    def undo(self) -> bool:
        if not self.rows:
            return False
        rows, created = self.rows.pop()
        restore_rows(self.ctx, rows, created)
        return True


def run_edit(ctx, log, ent, pick, edges, ext_mode, quick, trimming):
    if ctx.locked(ent):
        raise CommandError(LOCKED_MSG)
    if trimming:
        results = trim_entity(ctx, ent, pick, edges, ext_mode, quick)
    else:
        results = [extend_entity(ctx, ent, pick, edges, ext_mode)]
    rows = snap_rows(ctx, [ent.handle])
    created, erased = apply_result(ctx, ent, results)
    if log is not None:
        log.push(rows, created)
    return created, erased


def fence_points(ctx, ent, pts):
    path = co.path_of_safe(ent)
    chain = co.polyline_path(pts, False)
    if path is None or chain is None:
        return []
    out = []
    for _s, _sb, p in co.path_hits(path, chain):
        if not any(geom.dist(p, q) <= 1e-9 for q in out):
            out.append(p)
    return out


def repeat_at(ctx, log, handle, points, edges, ext_mode, quick, trimming):
    cur = [handle]
    count = 0
    for pt in points:
        best = None
        for h in cur:
            e = ctx.d.get(h)
            path = co.path_of_safe(e) if e is not None else None
            if path is None:
                continue
            dd = path.closest(pt)[2]
            if best is None or dd < best[0]:
                best = (dd, e)
        if best is None or best[0] > 1e-6:
            continue
        try:
            created, erased = run_edit(ctx, log, best[1], pt, edges, ext_mode, quick, trimming)
        except CommandError as err:
            ctx.say(str(err))
            continue
        count += 1
        cur = [h for h in cur if ctx.d.get(h) is not None] + created
    return count


def crossing_targets(ctx, rect, kinds):
    out = []
    xs = [p[0] for p in rect]
    ys = [p[1] for p in rect]
    box = (min(xs), min(ys), max(xs), max(ys))
    for e in ctx.visible_entities():
        if e.kind not in kinds or ctx.locked(e):
            continue
        b = e.bounds()
        if b is not None and not geom.boxes_overlap(b, box):
            continue
        if co.hit_by_polygon(e, rect, "cross"):
            out.append(e)
    return out


def rect_of(a, b):
    return [[a[0], a[1]], [b[0], a[1]], [b[0], b[1]], [a[0], b[1]]]


def kw(ctx, msg, options, default):
    p = ctx.keyword(msg, options, default)
    p.hint = "bare"
    return p


def sel_edges(ctx, text):
    s = yield ctx.select(text)
    if s.kind != "selection":
        return None
    return list(s.value) if s.value else None


def _read_mode(ctx):
    return int(ctx.d.header.get("TRIMEXTENDMODE", 1)) == 1


def _trim_extend(ctx, is_trim):
    log = EditLog(ctx)
    quick = _read_mode(ctx)
    edge_handles = None
    if is_trim and not quick:
        edge_handles = yield from sel_edges(ctx, "Select objects or <select all>")
    if not is_trim:
        edge_handles = yield from sel_edges(ctx, "Select objects or <select all>")
    msg = "Select object to trim or shift-select to extend" if is_trim else "Select object to extend or shift-select to trim"
    kinds = TRIMMABLE if is_trim else EXTENDABLE
    while True:
        quick = _read_mode(ctx)
        opts = ["cuTting edges"] if is_trim else ["Boundary edges"]
        opts += ["Fence", "Crossing", "mOde", "Project"]
        if (not is_trim) or not quick:
            opts += ["Edge"]
        if is_trim:
            opts += ["eRase"]
        opts += ["Undo"]
        r = yield ctx.entity(msg, opts)
        ext_mode = int(ctx.d.header.get("EDGEMODE", 0)) == 1
        if r.kind == "entity":
            h, pt, shift = unpack(r.value)
            ent = ctx.d.get(h)
            if ent is None:
                continue
            edges = edge_entities(ctx, edge_handles)
            try:
                run_edit(ctx, log, ent, pt, edges, ext_mode, quick if is_trim else False, is_trim != shift)
            except CommandError as err:
                ctx.say(str(err))
            continue
        if r.kind != "keyword":
            return
        word = r.value
        if word in ("cuTting edges", "Boundary edges"):
            edge_handles = yield from sel_edges(ctx, "Select objects or <select all>")
        elif word == "Undo":
            if not log.undo():
                ctx.say("Nothing to undo.")
        elif word == "mOde":
            m = yield kw(ctx, "Enter a trimming mode option" if is_trim else "Enter an extension mode option", ["Quick", "Standard"], "Quick" if quick else "Standard")
            if m.kind == "keyword":
                ctx.d.set_header("TRIMEXTENDMODE", 1 if m.value == "Quick" else 0)
                if m.value == "Standard" and is_trim:
                    edge_handles = yield from sel_edges(ctx, "Select objects or <select all>")
                elif m.value == "Quick" and is_trim:
                    edge_handles = None
        elif word == "Project":
            cur = ["None", "Ucs", "View"][max(0, min(2, int(ctx.d.header.get("PROJMODE", 1))))]
            m = yield kw(ctx, "Enter a projection option", ["None", "Ucs", "View"], cur)
            if m.kind == "keyword":
                ctx.d.set_header("PROJMODE", ["None", "Ucs", "View"].index(m.value))
        elif word == "Edge":
            m = yield kw(ctx, "Enter an implied edge extension mode", ["Extend", "No extend"], "Extend" if ext_mode else "No extend")
            if m.kind == "keyword":
                ctx.d.set_header("EDGEMODE", 1 if m.value == "Extend" else 0)
        elif word == "eRase":
            while True:
                s = yield ctx.select("Select objects to erase or <exit>")
                if s.kind != "selection" or not s.value:
                    break
                rows = snap_rows(ctx, s.value)
                from app.cmd.commands.modify import _erase

                n = _erase(ctx, s.value)
                if n:
                    log.push(rows, [])
        elif word == "Fence":
            pts = []
            first = yield ctx.point("Specify first fence point")
            if first.kind != "point":
                continue
            pts.append(first.value)
            while True:
                nxt = yield ctx.point("Specify next fence point", ["Undo"], base=pts[-1], jig=lambda q: [jig.poly([[p[0], p[1]] for p in pts] + [[q[0], q[1]]])])
                if nxt.kind == "keyword":
                    if len(pts) > 1:
                        pts.pop()
                    continue
                if nxt.kind != "point" or len(pts) >= MAX_FENCE_POINTS:
                    break
                pts.append(nxt.value)
            if len(pts) < 2:
                continue
            edges = edge_entities(ctx, edge_handles)
            total = 0
            for e in [x for x in ctx.visible_entities() if x.kind in kinds and not ctx.locked(x)]:
                points = fence_points(ctx, e, pts)
                if points:
                    total += repeat_at(ctx, log, e.handle, points, edges, ext_mode, quick if is_trim else False, is_trim)
            if not total:
                ctx.say("No objects found.")
        elif word == "Crossing":
            a = yield ctx.point("Specify first corner")
            if a.kind != "point":
                continue
            b = yield ctx.point("Specify opposite corner", rect=True, base=a.value, jig=lambda q: [jig.poly(rect_of(a.value, q), True)])
            if b.kind != "point":
                continue
            edges = edge_entities(ctx, edge_handles)
            total = 0
            for e in crossing_targets(ctx, rect_of(a.value, b.value), kinds):
                path = co.path_of_safe(e)
                if path is None:
                    continue
                pt = path.closest(a.value)[1]
                try:
                    run_edit(ctx, log, e, pt, edges, ext_mode, quick if is_trim else False, is_trim)
                    total += 1
                except CommandError as err:
                    ctx.say(str(err))
            if not total:
                ctx.say("No objects found.")


@command("trim", aliases=("tr",), group="modify", label="Trim", description="Trim objects to cutting edges (Quick or Standard mode, Fence, Crossing, Project, Edge, Erase).", menu="Modify > Trim")
def trim(ctx):
    return _trim_extend(ctx, True)


@command("extend", aliases=("ex",), group="modify", label="Extend", description="Extend objects to boundary edges (same options as trim).", menu="Modify > Extend")
def extend(ctx):
    return _trim_extend(ctx, False)


def _exec_edit(ctx, args, trimming):
    ext_mode = str(args.get("edgeMode", "extend" if int(ctx.d.header.get("EDGEMODE", 0)) == 1 else "none")).lower() == "extend"
    quick = str(args.get("mode", "quick" if _read_mode(ctx) else "standard")).lower() != "standard"
    handles = args.get("edges")
    edges = edge_entities(ctx, [int(h) for h in handles] if handles is not None else None)
    kinds = TRIMMABLE if trimming else EXTENDABLE
    changed = 0
    created_all = []
    erased_all = []

    def one(ent, pt):
        nonlocal changed
        created, erased = run_edit(ctx, None, ent, pt, edges, ext_mode, quick if trimming else False, trimming)
        created_all.extend(created)
        erased_all.extend(erased)
        changed += 1

    if "handle" in args:
        ent = ctx.d.get(int(args["handle"]))
        if ent is None:
            raise CommandError("No objects found.")
        pick = geom.as_pt(args["pick"]) if "pick" in args else None
        if pick is None:
            raise CommandError("Give a pick point.")
        one(ent, pick)
    elif "fence" in args:
        pts = [geom.as_pt(p) for p in args["fence"]]
        if not 2 <= len(pts) <= MAX_FENCE_POINTS:
            raise CommandError("A fence needs 2 to 10000 points.")
        for e in [x for x in ctx.visible_entities() if x.kind in kinds and not ctx.locked(x)]:
            points = fence_points(ctx, e, pts)
            if points:
                changed += repeat_at(ctx, None, e.handle, points, edges, ext_mode, quick if trimming else False, trimming)
    elif "crossing" in args:
        a, b = geom.as_pt(args["crossing"][0]), geom.as_pt(args["crossing"][1])
        for e in crossing_targets(ctx, rect_of(a, b), kinds):
            path = co.path_of_safe(e)
            if path is None:
                continue
            try:
                one(e, path.closest(a)[1])
            except CommandError:
                continue
    else:
        raise CommandError("Give handle and pick, fence or crossing.")
    if not changed:
        raise CommandError("No objects found.")
    return {"changed": changed, "created": created_all, "erased": erased_all}


@executes("trim")
def trim_exec(ctx, args):
    return _exec_edit(ctx, args, True)


@executes("extend")
def extend_exec(ctx, args):
    return _exec_edit(ctx, args, False)


def through_distance(ent, pt, tol):
    if ent.kind in ("circle", "arc"):
        return abs(geom.dist(ent.center, pt) - ent.radius)
    if ent.kind in ("line", "xline", "ray"):
        if ent.kind == "line":
            a, b = ent.start, ent.end
            dx, dy = b[0] - a[0], b[1] - a[1]
        else:
            a = ent.base
            dx, dy = ent.direction[0], ent.direction[1]
        ln = math.hypot(dx, dy)
        if ln <= 0:
            return 0.0
        return abs(dx * (pt[1] - a[1]) - dy * (pt[0] - a[0])) / ln
    path = co.path_of_safe(ent)
    return path.closest(pt)[2] if path is not None else 0.0


def make_offset(ctx, src, dist, side, through):
    tol = ctx.d.tolerances["absolute"]
    if through:
        dist = through_distance(src, side, tol)
    if not dist > tol:
        raise CommandError("Requires a positive distance.")
    new = co.offset_entity(src, dist, side, tol, big_of(ctx))
    if new is None or not new.valid():
        raise CommandError("Cannot offset to that side by that distance.")
    if int(ctx.d.header.get("OFFSETLAYER", 0)) == 1:
        new.layer = ctx.d.current_layer()
    else:
        new.layer = src.layer
    return new


def _offset_jig(ctx, src, dist, through):
    def fn(q):
        try:
            new = make_offset(ctx, src, dist, q, through)
        except (CommandError, ValueError):
            return []
        return jig.entity_items([new], ctx.d)

    return fn


def _check_offsettable(ctx, ent):
    if ent is None or ent.kind not in OFFSETTABLE:
        raise CommandError("cannot offset that object")
    if ctx.locked(ent):
        raise CommandError(LOCKED_MSG)


@command("offset", aliases=("o",), group="modify", label="Offset", description="Parallel copies of curves at a distance or through a point.", menu="Modify > Offset")
def offset(ctx):
    h = ctx.d.header
    last = float(h.get("OFFSETDIST", -1.0))
    through = last < 0
    dist = last if last > 0 else 0.0
    while True:
        p = ctx.distance("Specify offset distance", ["Through", "Erase", "Layer"], default=(None if through else last))
        if through:
            p.default = "Through"
            p.default_text = "Through"
        r = yield p
        if r.kind == "keyword":
            if r.value == "Through":
                through = True
                break
            if r.value == "Erase":
                a = yield ctx.yesno("Erase source object after offsetting?", "Yes" if int(h.get("OFFSETERASE", 0)) else "No")
                if a.kind == "keyword":
                    ctx.d.set_header("OFFSETERASE", 1 if a.value == "Yes" else 0)
                continue
            if r.value == "Layer":
                a = yield kw(ctx, "Enter layer option for offset objects", ["Current", "Source"], "Current" if int(h.get("OFFSETLAYER", 0)) else "Source")
                if a.kind == "keyword":
                    ctx.d.set_header("OFFSETLAYER", 1 if a.value == "Current" else 0)
                continue
        if r.kind == "number" or r.kind == "point":
            if r.kind == "point":
                q = yield ctx.point("Specify second point", base=r.value, jig=lambda c, a=r.value: [jig.line(a, c)])
                if q.kind != "point":
                    return
                v = geom.dist(r.value, q.value)
            else:
                v = r.value
            if not v > ctx.d.tolerances["absolute"]:
                ctx.say("Requires a positive distance.")
                continue
            dist = v
            through = False
            break
        return
    ctx.d.set_header("OFFSETDIST", -1.0 if through else dist)
    pre = None
    sel = ctx.runner.current_selection()
    if len(sel) == 1:
        e = ctx.d.get(sel[0])
        if e is not None and e.kind in OFFSETTABLE and not ctx.locked(e):
            pre = e
            ctx.doc.selection = []
    history = []
    cur = pre
    origin = pre.handle if pre is not None else None
    multi = False
    while True:
        if cur is None:
            multi = False
            o = ctx.entity("Select object to offset", ["Exit", "Undo"])
            o.default = "Exit"
            o.default_text = "Exit"
            r = yield o
            if r.kind == "keyword" and r.value == "Undo":
                if history:
                    rec = history.pop()
                    restore_rows(ctx, rec["rows"], [rec["created"]])
                else:
                    ctx.say("Nothing to undo.")
                continue
            if r.kind != "entity":
                return
            ent = ctx.d.get(int(r.value["handle"]))
            try:
                _check_offsettable(ctx, ent)
            except CommandError as err:
                ctx.say(str(err))
                continue
            cur = ent
            origin = ent.handle
        src = cur
        opts = ["Exit", "Undo"] if multi else ["Exit", "Multiple", "Undo"]
        if multi:
            sp = ctx.point("Specify point on side to offset" if not through else "Specify through point", opts, jig=_offset_jig(ctx, src, dist, through))
            sp.default_text = "next object"
        else:
            sp = ctx.point("Specify point on side to offset" if not through else "Specify through point", opts, default="Exit", default_text="exit", jig=_offset_jig(ctx, src, dist, through))
        r = yield sp
        if r.kind == "keyword" and r.value == "Exit":
            return
        if r.kind == "keyword" and r.value == "Multiple":
            multi = True
            continue
        if r.kind == "keyword" and r.value == "Undo":
            if history:
                rec = history.pop()
                restore_rows(ctx, rec["rows"], [rec["created"]])
                cur = ctx.d.get(rec["source"]) or cur
            else:
                ctx.say("Nothing to undo.")
            continue
        if r.kind == "enter":
            if multi:
                cur = None
                continue
            return
        if r.kind != "point":
            return
        try:
            new = make_offset(ctx, src, dist, r.value, through)
        except CommandError as err:
            ctx.say(str(err))
            continue
        nh = ctx.d.add_entity(new, src.owner)
        erased_rows = []
        if int(h.get("OFFSETERASE", 0)) and src.handle == origin and ctx.d.get(src.handle) is not None:
            erased_rows = snap_rows(ctx, [src.handle])
            ctx.d.erase_entity(src.handle)
        history.append({"created": nh, "rows": erased_rows, "source": src.handle})
        cur = ctx.d.get(nh) if multi else None


@executes("offset")
def offset_exec(ctx, args):
    src = ctx.d.get(int(args["handle"])) if "handle" in args else None
    _check_offsettable(ctx, src)
    through = "through" in args
    dist = 0.0 if through else float(args.get("distance", 0.0))
    if not through and not dist > ctx.d.tolerances["absolute"]:
        raise CommandError("Requires a positive distance.")
    erase = bool(args.get("erase", int(ctx.d.header.get("OFFSETERASE", 0))))
    layer = str(args.get("layer", "current" if int(ctx.d.header.get("OFFSETLAYER", 0)) else "source")).lower()
    old = ctx.d.header.get("OFFSETLAYER", 0)
    ctx.d.set_header("OFFSETLAYER", 1 if layer == "current" else 0)
    sides = [args["through"]] if through else [args["side"]] if "side" in args else []
    sides += list(args.get("multiple", []))
    if not sides:
        raise CommandError("Give side or through.")
    created = []
    cur = src
    try:
        for pt in sides:
            new = make_offset(ctx, cur, dist, geom.as_pt(pt), through)
            nh = ctx.d.add_entity(new, src.owner)
            created.append(nh)
            cur = ctx.d.get(nh)
    finally:
        ctx.d.set_header("OFFSETLAYER", old)
    if erase:
        ctx.d.erase_entity(src.handle)
    return {"created": created}


def break_pieces(ctx, ent, p1, p2):
    if ent.kind not in BREAKABLE:
        raise CommandError("Cannot break that object.")
    path = co.path_of(ent)
    if path is None:
        raise CommandError("Cannot break that object.")
    tol = ctx.d.tolerances["absolute"]
    s1, q1, _d1 = path.closest(p1)
    s2, q2, _d2 = path.closest(p2)
    n = path.n
    same = geom.dist(q1, q2) <= max(tol, 1e-9)
    if path.closed:
        if same:
            if ent.kind == "circle":
                raise CommandError("Arc cannot be full 360 degrees.")
            raise CommandError("Cannot break a closed %s at a single point." % kind_label(ent).lower())
        segs = path.slice(s2 % n, s1 % n)
        e = co.build_entity(ent, segs, False)
        return [e] if e is not None else []
    if s1 > s2:
        s1, s2 = s2, s1
    out = []
    if same:
        if s1 <= 1e-9 or n - s1 <= 1e-9:
            raise CommandError("Cannot break at an end point.")
        parts = [path.slice(0.0, s1), path.slice(s1, float(n))]
    else:
        parts = [path.slice(0.0, s1), path.slice(s2, float(n))]
    for segs in parts:
        if segs:
            e = co.build_entity(ent, segs, False)
            if e is not None and e.valid():
                out.append(e)
    return out


def apply_break(ctx, ent, pieces):
    d = ctx.d
    lst = d.spaces[ent.owner]
    idx = lst.index(ent.handle) if ent.handle in lst else len(lst)
    owner = ent.owner
    d.erase_entity(ent.handle)
    handles = []
    for k, p in enumerate(pieces):
        h = d.add_entity(p, owner)
        reposition(ctx, h, owner, idx + k)
        handles.append(h)
    return handles


def _break_flow(ctx, at_point):
    r = yield ctx.entity("Select object")
    if r.kind != "entity":
        return
    h, p1, _shift = unpack(r.value)
    ent = ctx.d.get(h)
    if ent is None:
        return
    if ctx.locked(ent):
        ctx.say(LOCKED_MSG)
        return
    if ent.kind not in BREAKABLE:
        ctx.say("Cannot break that object.")
        return
    ctx.set_last(p1)
    if at_point:
        bp = yield ctx.point("Specify break point", jig=lambda q: _break_jig(ctx, ent, q, q))
        if bp.kind != "point":
            return
        p1, p2 = bp.value, bp.value
    else:
        while True:
            q = yield ctx.point("Specify second break point", ["First point"], base=p1, jig=lambda c: _break_jig(ctx, ent, p1, c))
            if q.kind == "keyword":
                f = yield ctx.point("Specify first break point")
                if f.kind != "point":
                    return
                p1 = f.value
                ctx.set_last(p1)
                continue
            if q.kind != "point":
                return
            p2 = q.value
            break
    try:
        pieces = break_pieces(ctx, ent, p1, p2)
    except CommandError as err:
        ctx.say(str(err))
        return
    apply_break(ctx, ent, pieces)


def _break_jig(ctx, ent, p1, p2):
    try:
        pieces = break_pieces(ctx, ent, p1, p2)
    except CommandError:
        return []
    return jig.entity_items(pieces, ctx.d)


@command("break", aliases=("br",), group="modify", label="Break", description="Remove part of an object between two points.", menu="Modify > Break")
def break_cmd(ctx):
    return _break_flow(ctx, False)


@command("breakatpoint", group="modify", label="Break At Point", description="Split an object into two at a point.", menu="Modify > Break At Point")
def break_at_point(ctx):
    return _break_flow(ctx, True)


def _exec_break(ctx, args, at_point):
    ent = ctx.d.get(int(args["handle"])) if "handle" in args else None
    if ent is None:
        raise CommandError("Select object.")
    if ctx.locked(ent):
        raise CommandError(LOCKED_MSG)
    p1 = geom.as_pt(args.get("p1", args.get("point")))
    p2 = p1 if at_point or args.get("p2") is None else geom.as_pt(args["p2"])
    pieces = break_pieces(ctx, ent, p1, p2)
    return {"created": apply_break(ctx, ent, pieces)}


@executes("break")
def break_exec(ctx, args):
    return _exec_break(ctx, args, False)


@executes("breakatpoint")
def break_at_point_exec(ctx, args):
    return _exec_break(ctx, args, True)
