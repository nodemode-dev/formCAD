import math

from app.cmd import dim_support as DS
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.dim import vars as DV
from app.dim import vec as V_
from app.doc import geom
from app.doc.entities import Arc, Circle, Line, LwPolyline, Point

MODES = ("Continuous", "Staggered", "Baseline", "Ordinate", "Radius", "Diameter")
MAX_DIMS = 2000


def collect(ctx, handles, round_only=False):
    pts = []
    rounds = []
    for h in handles:
        e = ctx.d.get(h)
        if e is None or e.kind == "dimension":
            continue
        if isinstance(e, (Circle, Arc)):
            rounds.append(e)
            if not round_only:
                pts.append((float(e.center[0]), float(e.center[1])))
        elif round_only:
            continue
        elif isinstance(e, Line):
            pts += [(float(e.start[0]), float(e.start[1])), (float(e.end[0]), float(e.end[1]))]
        elif isinstance(e, LwPolyline):
            pts += [(float(v["p"][0]), float(v["p"][1])) for v in e.vertices]
        elif isinstance(e, Point):
            pts.append((float(e.position[0]), float(e.position[1])))
    return pts, rounds


def dedupe(pts, tol=1e-9):
    out = []
    for p in pts:
        if all(abs(p[0] - q[0]) > tol or abs(p[1] - q[1]) > tol for q in out):
            out.append(p)
    return out


def _step(ctx):
    V = DV.resolve(ctx.d, DS.current_style(ctx), {})
    return float(V["DIMDLI"]) * DV.scale_of(ctx.d, V)


def build(ctx, mode, pts, rounds, pos, datum=None, orient=None):
    out = []
    if mode in ("Radius", "Diameter"):
        step = _step(ctx)
        for e in rounds:
            c = V_.xy(e.center)
            u = V_.unit(V_.sub(V_.xy(pos), c))
            loc = [c[0] + u[0] * (e.radius + max(step, e.radius * 0.5)), c[1] + u[1] * (e.radius + max(step, e.radius * 0.5)), 0.0]
            from app.cmd.commands.dim_round import _radial

            dim, hints = _radial(ctx, "radius" if mode == "Radius" else "diameter", list(e.center), float(e.radius), loc, {}, e)
            out.append((dim, hints))
        return out
    if len(pts) < 2 and mode != "Ordinate":
        return out
    pts = dedupe(pts)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    a, b = (min(xs), min(ys)), (max(xs), max(ys))
    rot = orient if orient is not None else DS.default_orientation(a, b, pos)
    vertical = abs(rot - math.pi / 2.0) < 1e-9
    key = (lambda p: p[1]) if vertical else (lambda p: p[0])
    srt = sorted(pts, key=key)
    uniq = []
    for p in srt:
        if not uniq or abs(key(p) - key(uniq[-1])) > 1e-9:
            uniq.append(p)
    step = _step(ctx)
    axis = 0 if vertical else 1
    side = 1.0 if pos[axis] >= (a[axis] + b[axis]) / 2.0 else -1.0
    nvec = (side, 0.0) if vertical else (0.0, side)

    def loc_at(k):
        return [pos[0] + nvec[0] * step * k, pos[1] + nvec[1] * step * k, 0.0]

    if mode == "Ordinate":
        seen = []
        for p in dedupe(pts):
            if any(abs(key(p) - k) <= 1e-9 for k in seen):
                continue
            seen.append(key(p))
            if vertical:
                end = [pos[0], p[1], 0.0]
                kind = "y"
            else:
                end = [p[0], pos[1], 0.0]
                kind = "x"
            if geom.dist(end, p) < geom.EPS:
                continue
            e = DS.new_dimension(ctx, "ordinate", def_point=[datum[0], datum[1], 0.0] if datum else [0.0, 0.0, 0.0], p13=[p[0], p[1], 0.0], p14=end)
            e.marks["ordinate"] = kind
            out.append((e, None))
        return out
    if mode == "Baseline":
        base = uniq[0] if datum is None else min(uniq, key=lambda p: V_.dist(p, datum))
        k = 0
        for p in uniq:
            if p is base:
                continue
            k += 1
            out.append((DS.new_dimension(ctx, "linear", p13=[base[0], base[1], 0.0], p14=[p[0], p[1], 0.0], def_point=loc_at(k - 1), rotation=rot), None))
        return out
    for i in range(len(uniq) - 1):
        p, q = uniq[i], uniq[i + 1]
        row = (i % 2) if mode == "Staggered" else 0
        out.append((DS.new_dimension(ctx, "linear", p13=[p[0], p[1], 0.0], p14=[q[0], q[1], 0.0], def_point=loc_at(row), rotation=rot), None))
    return out


def _pick_box(ctx):
    return float(ctx.doc.view.get("height", 100.0)) * 0.02


@command("qdim", group="annotate", label="Quick Dimension", description="Quick dimensions of selected geometry: continuous, staggered, baseline, ordinate, radius, diameter.", menu="Dimension > Quick Dimension")
def qdim(ctx):
    s = yield ctx.select("Select geometry to dimension")
    if s.kind != "selection" or not s.value:
        return
    pts_all, rounds_all = collect(ctx, s.value)
    removed = []
    added = []
    datum = None
    mode = ctx.mem.get("qdim_mode", "Continuous")
    while True:
        pts = [p for p in dedupe(pts_all) if not any(V_.dist(p, r) < 1e-9 for r in removed)]
        pr = ctx.point("Specify dimension line position", list(MODES) + ["datumPoint", "Edit", "seTtings"], default=mode, default_text=mode)

        def jg(p, _m=mode):
            made = build(ctx, _m, pts, rounds_all, p, datum)[:40]
            out = []
            for dim, _h in made:
                out += DS.preview(ctx, dim)
            return out

        pr.jig = jg
        r = yield pr
        if r.kind == "keyword":
            v = r.value
            if v in MODES:
                mode = v
                continue
            if v == "datumPoint":
                q = yield ctx.point("Specify new datum point")
                if q.kind == "point":
                    datum = (q.value[0], q.value[1])
                continue
            if v == "seTtings":
                pa = ctx.keyword("Associative dimension priority", ["Endpoint", "Intersection"], ctx.mem.get("qdim_priority", "Endpoint"))
                pa.hint = "bare"
                a = yield pa
                if a.kind == "keyword":
                    ctx.mem["qdim_priority"] = a.value
                continue
            if v == "Edit":
                mode_edit = "remove"
                while True:
                    opts = ["Add", "eXit"] if mode_edit == "remove" else ["Remove", "eXit"]
                    q = yield ctx.point("Indicate dimension point to %s" % ("remove" if mode_edit == "remove" else "add"), opts)
                    if q.kind == "keyword":
                        if q.value == "Add":
                            mode_edit = "add"
                        elif q.value == "Remove":
                            mode_edit = "remove"
                        else:
                            break
                        continue
                    if q.kind != "point":
                        break
                    box = _pick_box(ctx)
                    if mode_edit == "remove":
                        cands = [p for p in pts if V_.dist(p, q.value) <= box]
                        if cands:
                            removed.append(min(cands, key=lambda p: V_.dist(p, q.value)))
                    else:
                        cands = [p for p in dedupe(pts_all) if any(V_.dist(p, rr) < 1e-9 for rr in removed) and V_.dist(p, q.value) <= box]
                        if cands:
                            hit = min(cands, key=lambda p: V_.dist(p, q.value))
                            removed[:] = [rr for rr in removed if V_.dist(rr, hit) >= 1e-9]
                continue
        if r.kind != "point":
            return
        ctx.mem["qdim_mode"] = mode
        made = build(ctx, mode, pts, rounds_all, r.value, datum)
        if mode in ("Radius", "Diameter") and not rounds_all:
            ctx.say("Radius and diameter modes need circles or arcs.")
            return
        count = 0
        for dim, hints in made[:MAX_DIMS]:
            DS.commit_dimension(ctx, dim, hints)
            count += 1
        ctx.say("%d dimension(s) created." % count)
        return


@executes("qdim")
def qdim_exec(ctx, args):
    handles = [int(h) for h in args.get("handles", [])]
    mode = str(args.get("mode", "continuous")).lower()
    names = {m.lower(): m for m in MODES}
    if mode not in names:
        raise CommandError("Mode must be one of: %s." % ", ".join(m.lower() for m in MODES))
    mode = names[mode]
    pts, rounds = collect(ctx, handles)
    if mode in ("Radius", "Diameter") and not rounds:
        raise CommandError("Radius and diameter modes need circles or arcs.")
    removed = [tuple(float(v) for v in p[:2]) for p in args.get("remove", [])]
    pts = [p for p in dedupe(pts) if not any(V_.dist(p, r) < 1e-9 for r in removed)]
    pos = geom.as_pt(args["position"])
    datum = tuple(float(v) for v in args["datum"][:2]) if args.get("datum") else None
    orient = None
    o = str(args.get("orientation", "")).lower()
    if o in ("h", "horizontal"):
        orient = 0.0
    elif o in ("v", "vertical"):
        orient = math.pi / 2.0
    made = build(ctx, mode, pts, rounds, pos, datum, orient)
    if not made:
        raise CommandError("Not enough geometry to dimension.")
    ids = [DS.commit_dimension(ctx, d, h) for d, h in made[:MAX_DIMS]]
    return {"created": ids, "count": len(ids)}
