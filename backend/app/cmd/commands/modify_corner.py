import math

from app.cmd import edit_ledger as L, jig, snaps
from app.cmd.context import CommandError
from app.cmd.draw_support import add_like, pick_entity, pick_point
from app.cmd.registry import command, executes
from app.doc import cornerops as K, geom, nurbs, polyedit
from app.doc.entities import Arc, Ellipse, Line, LwPolyline, Spline

LOCKED = "The object is on a locked layer."
CHAM_LARGE = "The chamfer distance is too large."
EPS = 1e-9


def _clone(e):
    return type(e).from_dict(e.to_dict())


def _verb(kind):
    return "fillet" if kind == "fillet" else "chamfer"


def _message(kind, err):
    text = str(err)
    if kind == "chamfer" and text == K.TOO_LARGE:
        return CHAM_LARGE
    return text


def _ready(ctx, ent):
    if ent is None:
        raise CommandError("*Invalid selection*")
    if ctx.locked(ent):
        raise CommandError(LOCKED)
    return ent


def _cut_entity(e, pc, foot, ref, q):
    c = _clone(e)
    if isinstance(e, Line):
        s, en = K.cut_line(e.start, e.end, foot, ref, q)
        if s is not None:
            c.start = s
        if en is not None:
            c.end = en
        return c
    if isinstance(e, Arc):
        a0, a1 = K.cut_arc(e.start_angle, e.end_angle, e.center, foot, ref, q)
        if a0 is not None:
            c.start_angle = a0
        if a1 is not None:
            c.end_angle = a1
        return c
    if isinstance(e, Ellipse):
        full = abs(e.end_param - e.start_param) >= geom.TAU - 1e-12 or abs(e.end_param - e.start_param) < 1e-12
        if full:
            return None
        s, en = K.cut_ellipse(e, foot, ref, q)
        if s is not None:
            c.start_param = s
        if en is not None:
            c.end_param = en
        return c
    if isinstance(e, Spline):
        if e.closed:
            return None
        curve = K.cut_spline(e, pc["curve"], foot, ref, q)
        c.degree, c.knots = curve.degree, list(curve.knots)
        c.control_points = [list(p) for p in curve.ctrl]
        c.weights = list(curve.weights) if curve.weights else []
        c.fit_points = []
        c.start_tangent = c.end_tangent = None
        return c
    return None


def _connector(kind, a, b, bulge):
    if kind == "chamfer" or abs(bulge) < geom.TINY_BULGE:
        return Line(start=[a[0], a[1], 0.0], end=[b[0], b[1], 0.0])
    arc = geom.bulge_to_arc(a, b, bulge)
    center, r, a0, a1, _ccw = arc
    return Arc(center=[center[0], center[1], 0.0], radius=r, start_angle=a0, end_angle=a1)


def _chamfer_dists(w1, w2, p):
    if "length" in p:
        return p["length"], K.angle_distance(w1, w2, p["length"], p["angle"])
    return p["d1"], p["d2"]


def _pair(kind, e1, q1, e2, q2, p, trim):
    verb = _verb(kind)
    if kind == "chamfer" and not (isinstance(e1, Line) and isinstance(e2, Line)):
        raise CommandError("Chamfer works on lines and straight polyline segments only.")
    p1, p2 = K.piece_of(e1), K.piece_of(e2)
    if p1 is None or p2 is None:
        raise CommandError("Cannot %s that object." % verb)
    if e1.handle == e2.handle:
        raise CommandError("Cannot %s an object to itself." % verb)
    try:
        if kind == "fillet":
            res = K.solve(p1, p2, q1, q2, p["r"])
            made = None
            if res["center"] is not None:
                c, r, a0, a1 = K.fillet_arc(res)
                made = Arc(center=[c[0], c[1], 0.0], radius=r, start_angle=a0, end_angle=a1)
        else:
            pre = K.solve_chamfer_lines(p1, p2, q1, q2, 0.0, 0.0)
            d1, d2 = _chamfer_dists(pre["w1"], pre["w2"], p)
            res = K.solve_chamfer_lines(p1, p2, q1, q2, d1, d2)
            res.update({"f1": res["c1"], "f2": res["c2"], "ref1": res["x"], "ref2": res["x"]})
            made = Line(start=[res["c1"][0], res["c1"][1], 0.0], end=[res["c2"][0], res["c2"][1], 0.0]) if d1 > EPS or d2 > EPS else None
        out = {"set": {}, "new": [made] if made is not None else [], "drop": [], "src": e1}
        if trim:
            for e, pc, foot, ref, q in ((e1, p1, res["f1"], res["ref1"], q1), (e2, p2, res["f2"], res["ref2"], q2)):
                c = _cut_entity(e, pc, foot, ref, q)
                if c is not None:
                    out["set"][e.handle] = c
    except ValueError as err:
        raise CommandError(_message(kind, err))
    return out


def _seg_len(poly, i):
    n = len(poly.vertices)
    return math.dist(poly.vertices[i]["p"], poly.vertices[(i + 1) % n]["p"])


def _straight(poly, i):
    return abs(poly.vertices[i].get("bulge", 0.0) or 0.0) < geom.TINY_BULGE


def _dedupe(verts, closed):
    out = [v for k, v in enumerate(verts) if not (k + 1 < len(verts) and math.dist(v["p"], verts[k + 1]["p"]) < 1e-9)]
    if closed and len(out) > 1 and math.dist(out[-1]["p"], out[0]["p"]) < 1e-9:
        out.pop()
    return out


def _rounded(poly, cuts):
    src = poly.vertices
    n = len(src)
    out = []
    tail = None
    for k, v in enumerate(src):
        cut = cuts.get(k)
        if cut is None:
            out.append(dict(v, p=list(v["p"])))
            continue
        A, B, bulge = cut
        prev = src[(k - 1) % n]
        pw = prev.get("ew", 0.0)
        a = {"p": [A[0], A[1]], "bulge": bulge, "sw": pw, "ew": pw}
        b = dict(v, p=[B[0], B[1]])
        if k == 0 and poly.closed:
            out.append(b)
            tail = a
        else:
            out.extend([a, b])
    if tail is not None:
        out.append(tail)
    return _dedupe(out, poly.closed)


def _corner_params(kind, p, w1, w2):
    if kind == "fillet":
        return p["r"], p["r"]
    return _chamfer_dists(w1, w2, p)


def _corner_at(poly, k, kind, p, swapped=False):
    n = len(poly.vertices)
    v = poly.vertices
    prev, cur, nxt = v[(k - 1) % n]["p"], v[k]["p"], v[(k + 1) % n]["p"]
    din = K.unit(K.sub(cur, prev))
    dout = K.unit(K.sub(nxt, cur))
    if din is None or dout is None:
        raise CommandError("Cannot %s a zero length segment." % _verb(kind))
    w1, w2 = ([dout, [-din[0], -din[1]]] if swapped else [[-din[0], -din[1]], dout])
    try:
        a, b = _corner_params(kind, p, w1, w2)
    except ValueError as err:
        raise CommandError(str(err))
    if swapped:
        a, b = b, a
    cut = K.corner_cut(prev, cur, nxt, kind, a, b)
    if cut is None:
        raise CommandError("Lines are parallel.")
    if cut["ta"] > _seg_len(poly, (k - 1) % n) + EPS or cut["tb"] > _seg_len(poly, k) + EPS:
        raise CommandError(_message(kind, K.TOO_LARGE))
    return cut


def _need_straight(poly, idxs, kind):
    for i in idxs:
        if not _straight(poly, i % len(poly.vertices)):
            raise CommandError("Only straight polyline segments can be %s." % ("filleted" if kind == "fillet" else "chamfered"))


def _poly_result(kind, poly, verts, extra_new, trim, connectors):
    out = {"set": {}, "new": list(extra_new), "drop": [], "src": poly}
    if trim:
        c = _clone(poly)
        c.vertices = verts
        out["set"][poly.handle] = c
    else:
        out["new"].extend(connectors)
    return out


def _same_poly(kind, poly, q1, q2, p, trim):
    n = len(poly.vertices)
    i, j = K.nearest_segment(poly, q1), K.nearest_segment(poly, q2)
    verb = _verb(kind)
    if i == j:
        raise CommandError("Cannot %s an object to itself." % verb)
    closed = poly.closed
    fwd = (j - i) % n if closed else j - i
    bwd = (i - j) % n if closed else i - j
    if fwd == 1 or bwd == 1:
        swapped = fwd != 1
        k = j if not swapped else i
        _need_straight(poly, (k - 1, k), kind)
        cut = _corner_at(poly, k, kind, p, swapped)
        verts = _rounded(poly, {k: (cut["A"], cut["B"], cut["bulge"])})
        return _poly_result(kind, poly, verts, [], trim, [_connector(kind, cut["A"], cut["B"], cut["bulge"])])
    if fwd == 2 or bwd == 2:
        swapped = fwd != 2
        first = j if swapped else i
        if not closed and first + 3 > n - 1:
            raise CommandError("Cannot %s those segments." % verb)
        return _between(kind, poly, first, p, trim, swapped)
    raise CommandError("Select two segments that are adjacent or have one segment between them.")


def _between(kind, poly, i, p, trim, swapped):
    n = len(poly.vertices)
    v = poly.vertices
    vi, v1, v2, v3 = (v[(i + t) % n]["p"] for t in range(4))
    _need_straight(poly, (i, i + 2), kind)
    x = K.line_intersection(vi, v1, v2, v3)
    if x is None:
        raise CommandError("Lines are parallel.")
    u1, u2 = K.unit(K.sub(v1, vi)), K.unit(K.sub(v3, v2))
    if K.dot(K.sub(x, vi), u1) <= EPS or K.dot(K.sub(v3, x), u2) <= EPS:
        raise CommandError("Cannot %s those segments." % _verb(kind))
    w1, w2 = ([u2, [-u1[0], -u1[1]]] if swapped else [[-u1[0], -u1[1]], u2])
    try:
        a, b = _corner_params(kind, p, w1, w2)
    except ValueError as err:
        raise CommandError(str(err))
    if swapped:
        a, b = b, a
    cut = K.corner_cut(vi, x, v3, kind, a, b)
    if cut is None:
        raise CommandError("Lines are parallel.")
    if K.dot(K.sub(cut["A"], vi), u1) <= EPS or K.dot(K.sub(v3, cut["B"]), u2) <= EPS:
        raise CommandError(_message(kind, K.TOO_LARGE))
    verts = [dict(t, p=list(t["p"])) for t in v]
    ia, ib = (i + 1) % n, (i + 2) % n
    pw = v[i].get("ew", 0.0)
    verts[ia] = {"p": [cut["A"][0], cut["A"][1]], "bulge": cut["bulge"], "sw": pw, "ew": pw}
    verts[ib] = dict(v[ib], p=[cut["B"][0], cut["B"][1]])
    verts = _dedupe(verts, poly.closed)
    return _poly_result(kind, poly, verts, [], trim, [_connector(kind, cut["A"], cut["B"], cut["bulge"])])


def _with_line(kind, poly, qp, line, ql, p, trim, poly_first):
    verb = _verb(kind)
    if not isinstance(line, Line):
        raise CommandError("Cannot %s that object." % verb)
    if poly.closed:
        raise CommandError("Select an end segment of an open polyline.")
    n = len(poly.vertices)
    i = K.nearest_segment(poly, qp)
    if i not in (0, n - 2):
        raise CommandError("Select an end segment of an open polyline.")
    pl = K.piece_of(line)
    verts = polyedit.clone_verts(poly.vertices)
    flipped = False
    if i == 0 and n > 2 or (n == 2 and math.dist(qp, verts[0]["p"]) < math.dist(qp, verts[1]["p"])):
        verts = polyedit.reverse_vertices(verts, False)
        flipped = True
    if abs(verts[-2].get("bulge", 0.0) or 0.0) > geom.TINY_BULGE:
        raise CommandError("Only straight polyline segments can be %s." % ("filleted" if kind == "fillet" else "chamfered"))
    vp, vl = verts[-2]["p"], verts[-1]["p"]
    seg = {"t": "line", "a": vp[:2], "b": vl[:2]}
    x = K.intersections(seg, pl, qp)
    if not x:
        raise CommandError("Lines are parallel.")
    x = x[0]
    u = K.unit(K.sub(vl, vp))
    if K.dot(K.sub(x, vp), u) <= EPS:
        raise CommandError("The objects do not intersect.")
    w2 = K._dir_from(pl, x, ql[:2])
    far = max((pl["a"], pl["b"]), key=lambda t: K.dot(K.sub(t, x), w2))
    w1 = [-u[0], -u[1]]
    wa, wb = (w1, w2) if poly_first else (w2, w1)
    try:
        a, b = _corner_params(kind, p, wa, wb)
    except ValueError as err:
        raise CommandError(str(err))
    ta, tb = (a, b) if poly_first else (b, a)
    cut = K.corner_cut(vp, x, far, kind, ta, tb)
    if cut is None:
        raise CommandError("Lines are parallel.")
    if K.dot(K.sub(cut["A"], vp), u) <= EPS or K.dot(K.sub(far, cut["B"]), w2) <= EPS:
        raise CommandError(_message(kind, K.TOO_LARGE))
    pw = verts[-2].get("ew", 0.0)
    head = verts[:-1]
    head.append({"p": [cut["A"][0], cut["A"][1]], "bulge": cut["bulge"], "sw": pw, "ew": pw})
    head.append(polyedit.vertex(cut["B"], 0.0, pw, pw))
    head.append(polyedit.vertex(far, 0.0, pw, pw))
    if flipped:
        head = polyedit.reverse_vertices(head, False)
    head = _dedupe(head, False)
    out = {"set": {}, "new": [], "drop": [], "src": poly}
    if trim:
        c = _clone(poly)
        c.vertices = head
        out["set"][poly.handle] = c
        out["drop"].append(line.handle)
    else:
        out["new"].append(_connector(kind, cut["A"], cut["B"], cut["bulge"]))
    return out


def corner_result(ctx, kind, e1, q1, e2, q2, p, trim):
    q1, q2 = [q1[0], q1[1]], [q2[0], q2[1]]
    if isinstance(e1, LwPolyline) and isinstance(e2, LwPolyline):
        if e1.handle != e2.handle:
            raise CommandError("Cannot %s segments of different polylines." % _verb(kind))
        return _same_poly(kind, e1, q1, q2, p, trim)
    if isinstance(e1, LwPolyline):
        return _with_line(kind, e1, q1, e2, q2, p, trim, True)
    if isinstance(e2, LwPolyline):
        return _with_line(kind, e2, q2, e1, q1, p, trim, False)
    return _pair(kind, e1, q1, e2, q2, p, trim)


def polyline_corners(ctx, kind, poly, p, trim):
    n = len(poly.vertices)
    cuts = {}
    used = {}
    count = 0
    ks = range(n) if poly.closed else range(1, n - 1)
    for k in ks:
        sa, sb = (k - 1) % n, k
        if not (_straight(poly, sa) and _straight(poly, sb)):
            continue
        try:
            cut = _corner_at(poly, k, kind, p)
        except CommandError:
            continue
        if cut["ta"] < EPS and cut["tb"] < EPS:
            continue
        if used.get(sa, 0.0) + cut["ta"] > _seg_len(poly, sa) + EPS or used.get(sb, 0.0) + cut["tb"] > _seg_len(poly, sb) + EPS:
            continue
        used[sa] = used.get(sa, 0.0) + cut["ta"]
        used[sb] = used.get(sb, 0.0) + cut["tb"]
        cuts[k] = (cut["A"], cut["B"], cut["bulge"])
        count += 1
    out = {"set": {}, "new": [], "drop": [], "src": poly, "count": count}
    if count:
        if trim:
            c = _clone(poly)
            c.vertices = _rounded(poly, cuts)
            out["set"][poly.handle] = c
        else:
            out["new"] = [_connector(kind, cut[0], cut[1], cut[2]) for cut in cuts.values()]
    return out


def commit(ctx, led, res):
    d = ctx.d
    for h, clone in res["set"].items():
        old = d.get(h)
        L.touch(ctx, led, old)
        d.ents[h] = clone
    for h in res["drop"]:
        ent = d.get(h)
        if ent is not None:
            L.drop(ctx, led, ent)
    made = []
    for ent in res["new"]:
        made.append(L.made(led, add_like(ctx, ent, res["src"])))
    return made


def preview_shapes(ctx, res):
    ents = list(res["new"]) + list(res["set"].values())
    return jig.entity_items(ents, ctx.d)


def _trim_default(ctx) -> bool:
    return bool(int(ctx.d.header.get("TRIMMODE", 1)))


def _fillet_params(ctx, r=None):
    return {"r": float(ctx.d.header.get("FILLETRAD", 0.0)) if r is None else float(r)}


def _chamfer_params(ctx):
    h = ctx.d.header
    if int(h.get("CHAMMODE", 0)) == 1:
        return {"length": float(h.get("CHAMFERC", 0.0)), "angle": float(h.get("CHAMFERD", 0.0))}
    return {"d1": float(h.get("CHAMFERA", 0.0)), "d2": float(h.get("CHAMFERB", 0.0))}


def _zero(kind):
    return {"r": 0.0} if kind == "fillet" else {"d1": 0.0, "d2": 0.0}


def _hover_entity(ctx, p):
    ents = list(ctx.visible_entities())
    aperture = float(ctx.doc.view.get("height", 100.0)) * 0.02
    return snaps.nearest_curve(ents, [p[0], p[1], 0.0], aperture)


def _second_jig(ctx, kind, first, q1, params_fn, trim_fn):
    def run(cursor):
        e2 = _hover_entity(ctx, cursor)
        if e2 is None:
            return []
        try:
            res = corner_result(ctx, kind, first, q1, e2, cursor, params_fn(), trim_fn())
        except CommandError:
            return []
        return preview_shapes(ctx, res)

    return run


def _setting_line(ctx, kind):
    trim = "TRIM" if _trim_default(ctx) else "NOTRIM"
    if kind == "fillet":
        return "Current settings: Mode = %s, Radius = %s" % (trim, ctx.fd(float(ctx.d.header.get("FILLETRAD", 0.0))))
    h = ctx.d.header
    if int(h.get("CHAMMODE", 0)) == 1:
        return "(%s mode) Current chamfer Length = %s, Angle = %s" % (trim, ctx.fd(float(h.get("CHAMFERC", 0.0))), ctx.fa(float(h.get("CHAMFERD", 0.0))))
    return "(%s mode) Current chamfer Dist1 = %s, Dist2 = %s" % (trim, ctx.fd(float(h.get("CHAMFERA", 0.0))), ctx.fd(float(h.get("CHAMFERB", 0.0))))


def _ask_radius(ctx):
    cur = float(ctx.d.header.get("FILLETRAD", 0.0))
    while True:
        r = yield ctx.number("Specify fillet radius", default=cur, default_text=ctx.fd(cur))
        if r.kind != "number":
            return None
        if r.value < 0:
            ctx.say("The fillet radius must be zero or more.")
            continue
        ctx.d.set_header("FILLETRAD", float(r.value))
        return r.value


def menu(ctx, msg, options, default=None):
    p = ctx.keyword(msg, options, default)
    p.hint = "bare"
    return p


def _ask_trim(ctx):
    cur = "Trim" if _trim_default(ctx) else "No trim"
    t = yield menu(ctx, "Enter Trim mode option", ["Trim", "No trim"], cur)
    if t.kind == "keyword":
        ctx.d.set_header("TRIMMODE", 1 if t.value == "Trim" else 0)


def _ask_distances(ctx):
    h = ctx.d.header
    cur = float(h.get("CHAMFERA", 0.0))
    a = yield ctx.number("Specify first chamfer distance", default=cur, minimum=0, default_text=ctx.fd(cur))
    if a.kind != "number":
        return
    b = yield ctx.number("Specify second chamfer distance", default=a.value, minimum=0, default_text=ctx.fd(a.value))
    if b.kind != "number":
        return
    ctx.d.set_header("CHAMFERA", float(a.value))
    ctx.d.set_header("CHAMFERB", float(b.value))
    ctx.d.set_header("CHAMMODE", 0)


def _ask_angle_mode(ctx):
    h = ctx.d.header
    cur = float(h.get("CHAMFERC", 0.0))
    a = yield ctx.number("Specify chamfer length on the first line", default=cur, minimum=0, default_text=ctx.fd(cur))
    if a.kind != "number":
        return
    while True:
        b = yield ctx.angle("Specify chamfer angle from the first line", default=float(h.get("CHAMFERD", 0.0)), absolute=False)
        if b.kind != "number":
            return
        if not 0.0 <= b.value <= math.pi:
            ctx.say("The angle must be between 0 and 180 degrees.")
            continue
        break
    ctx.d.set_header("CHAMFERC", float(a.value))
    ctx.d.set_header("CHAMFERD", float(b.value))
    ctx.d.set_header("CHAMMODE", 1)


def _pick_ready(ctx, inp):
    ent = pick_entity(ctx, inp.value)
    _ready(ctx, ent)
    return ent, pick_point(inp.value)


def _corner_command(ctx, kind):
    verb = _verb(kind)
    stack = []
    ctx.say(_setting_line(ctx, kind))
    multiple = False
    first_options = ["Undo", "Polyline", "Radius", "Trim", "Multiple"] if kind == "fillet" else ["Undo", "Polyline", "Distance", "Angle", "Trim", "mEthod", "Multiple"]
    params_fn = (lambda: _fillet_params(ctx)) if kind == "fillet" else (lambda: _chamfer_params(ctx))
    while True:
        prompt = ctx.entity("Select first object" if kind == "fillet" else "Select first line", first_options)
        r1 = yield prompt
        if r1.kind == "keyword":
            w = r1.value
            if w == "Undo":
                if stack:
                    L.rollback(ctx, stack.pop())
                else:
                    ctx.say("Nothing to undo.")
            elif w == "Multiple":
                multiple = True
            elif w == "Trim":
                yield from _ask_trim(ctx)
            elif w == "Radius":
                yield from _ask_radius(ctx)
            elif w == "Distance":
                yield from _ask_distances(ctx)
            elif w == "Angle":
                yield from _ask_angle_mode(ctx)
            elif w == "mEthod":
                cur = "Angle" if int(ctx.d.header.get("CHAMMODE", 0)) == 1 else "Distance"
                m = yield menu(ctx, "Enter trim method", ["Distance", "Angle"], cur)
                if m.kind == "keyword":
                    ctx.d.set_header("CHAMMODE", 1 if m.value == "Angle" else 0)
            elif w == "Polyline":
                s = yield ctx.entity("Select 2D polyline")
                if s.kind != "entity":
                    continue
                try:
                    poly, _q = _pick_ready(ctx, s)
                except CommandError as err:
                    ctx.say(str(err))
                    continue
                if not isinstance(poly, LwPolyline):
                    ctx.say("Select a 2D polyline.")
                    continue
                res = polyline_corners(ctx, kind, poly, params_fn(), _trim_default(ctx))
                led = L.new()
                commit(ctx, led, res)
                stack.append(led)
                ctx.say("%d lines were %s" % (res["count"], "filleted" if kind == "fillet" else "chamfered"))
                if not multiple:
                    return
            continue
        if r1.kind != "entity":
            return
        try:
            e1, q1 = _pick_ready(ctx, r1)
            if kind == "chamfer" and not isinstance(e1, (Line, LwPolyline)):
                raise CommandError("Chamfer works on lines and straight polyline segments only.")
            if kind == "fillet" and K.piece_of(e1) is None and not isinstance(e1, LwPolyline):
                raise CommandError("Cannot fillet that object.")
        except CommandError as err:
            ctx.say(str(err))
            continue
        while True:
            p2 = ctx.entity("Select second object or shift-select to apply corner" if kind == "fillet" else "Select second line or shift-select to apply corner", ["Radius"] if kind == "fillet" else [])
            p2.jig = _second_jig(ctx, kind, e1, q1, params_fn, lambda: _trim_default(ctx))
            r2 = yield p2
            if r2.kind == "keyword" and r2.value == "Radius":
                yield from _ask_radius(ctx)
                continue
            break
        if r2.kind != "entity":
            if not multiple:
                return
            continue
        try:
            e2, q2 = _pick_ready(ctx, r2)
            params = _zero(kind) if r2.value.get("shift") else params_fn()
            res = corner_result(ctx, kind, e1, q1, e2, q2, params, _trim_default(ctx))
        except CommandError as err:
            ctx.say(str(err))
            if not multiple:
                return
            continue
        led = L.new()
        commit(ctx, led, res)
        stack.append(led)
        if not multiple:
            return


@command("fillet", aliases=("f",), group="modify", label="Fillet", description="Round the corner of two objects or a polyline with a radius.", menu="Modify > Fillet")
def fillet(ctx):
    yield from _corner_command(ctx, "fillet")


@command("chamfer", aliases=("cha",), group="modify", label="Chamfer", description="Bevel the corner of two lines or a polyline by distances or length and angle.", menu="Modify > Chamfer")
def chamfer(ctx):
    yield from _corner_command(ctx, "chamfer")


def _arg_pick(ctx, args, key):
    val = args.get(key)
    if not isinstance(val, dict):
        raise CommandError("Give %s as {handle, point}." % key)
    ent = pick_entity(ctx, val)
    _ready(ctx, ent)
    return ent, pick_point(val)


def _exec_corner(ctx, args, kind):
    trim = bool(args["trim"]) if "trim" in args else _trim_default(ctx)
    if kind == "fillet":
        r = float(args["radius"]) if "radius" in args else float(ctx.d.header.get("FILLETRAD", 0.0))
        if r < 0:
            raise CommandError("The fillet radius must be zero or more.")
        params = {"r": r}
    elif "length" in args:
        ang = math.radians(float(args.get("angle", 0.0)))
        if float(args["length"]) < 0 or not 0.0 <= ang <= math.pi:
            raise CommandError("Requires a positive number.")
        params = {"length": float(args["length"]), "angle": ang}
    else:
        d1 = float(args["d1"]) if "d1" in args else float(ctx.d.header.get("CHAMFERA", 0.0))
        d2 = float(args["d2"]) if "d2" in args else (d1 if "d1" in args else float(ctx.d.header.get("CHAMFERB", 0.0)))
        if d1 < 0 or d2 < 0:
            raise CommandError("Requires a positive number.")
        params = {"d1": d1, "d2": d2}
    led = L.new()
    if args.get("polyline"):
        poly = ctx.d.get(int(args.get("handle", 0)))
        _ready(ctx, poly)
        if not isinstance(poly, LwPolyline):
            raise CommandError("Select a 2D polyline.")
        res = polyline_corners(ctx, kind, poly, params, trim)
        made = commit(ctx, led, res)
        return {"count": res["count"], "created": made}
    e1, q1 = _arg_pick(ctx, args, "first")
    e2, q2 = _arg_pick(ctx, args, "second")
    if args.get("shift"):
        params = _zero(kind)
    res = corner_result(ctx, kind, e1, q1, e2, q2, params, trim)
    made = commit(ctx, led, res)
    return {"created": made, "modified": sorted(res["set"]), "erased": res["drop"]}


@executes("fillet")
def fillet_exec(ctx, args):
    return _exec_corner(ctx, args, "fillet")


@executes("chamfer")
def chamfer_exec(ctx, args):
    return _exec_corner(ctx, args, "chamfer")


def _open_curve(ctx, inp):
    ent, q = _pick_ready(ctx, inp)
    ends = K.end_data(ent)
    if ends is None:
        raise CommandError("Select an open curve.")
    key = min(("s", "e"), key=lambda k: math.dist(ends[k][0], q[:2]))
    return ent, ends[key]


def blend_spline(ctx, ent1, end1, ent2, end2, smooth):
    pa, ta, ka = end1
    pb, tb, kb = end2
    try:
        curve = K.blend_curve(list(pa), list(ta), ka, list(pb), list(tb), kb, smooth)
    except ValueError as err:
        raise CommandError(str(err))
    spl = Spline(degree=curve.degree, knots=list(curve.knots), control_points=[list(p) for p in curve.ctrl], weights=[], fit_points=[], closed=False, fit_method=0)
    return add_like(ctx, spl, ent1)


@command("blend", aliases=("blendcurves",), group="modify", label="Blend", description="Spline bridging the ends of two open curves.", menu="Modify > Blend")
def blend(ctx):
    smooth = ctx.mem.get("blend_smooth", False)
    while True:
        r1 = yield ctx.entity("Select first object", ["CONtinuity"])
        if r1.kind == "keyword":
            c = yield menu(ctx, "Enter continuity", ["Tangent", "Smooth"], "Smooth" if smooth else "Tangent")
            if c.kind == "keyword":
                smooth = c.value == "Smooth"
                ctx.mem["blend_smooth"] = smooth
            continue
        if r1.kind != "entity":
            return
        try:
            e1, end1 = _open_curve(ctx, r1)
        except CommandError as err:
            ctx.say(str(err))
            continue
        break

    def shape(cursor):
        e2 = _hover_entity(ctx, cursor)
        if e2 is None:
            return []
        ends = K.end_data(e2)
        if ends is None:
            return []
        key = min(("s", "e"), key=lambda k: math.dist(ends[k][0], cursor[:2]))
        try:
            curve = K.blend_curve(list(end1[0]), list(end1[1]), end1[2], list(ends[key][0]), list(ends[key][1]), ends[key][2], smooth)
        except ValueError:
            return []
        return [jig.poly([[p[0], p[1]] for p in nurbs.sample(curve, 12)])]

    while True:
        p2 = ctx.entity("Select second point")
        p2.jig = shape
        r2 = yield p2
        if r2.kind != "entity":
            return
        try:
            e2, end2 = _open_curve(ctx, r2)
            blend_spline(ctx, e1, end1, e2, end2, smooth)
        except CommandError as err:
            ctx.say(str(err))
            continue
        return


@executes("blend")
def blend_exec(ctx, args):
    e1, q1 = _arg_pick(ctx, args, "first")
    e2, q2 = _arg_pick(ctx, args, "second")
    smooth = str(args.get("continuity", "tangent")).lower().startswith("s")
    ends = []
    for e, q in ((e1, q1), (e2, q2)):
        data = K.end_data(e)
        if data is None:
            raise CommandError("Select an open curve.")
        ends.append(data[min(("s", "e"), key=lambda k: math.dist(data[k][0], q[:2]))])
    return {"created": [blend_spline(ctx, e1, ends[0], e2, ends[1], smooth)]}
