import math

from app.cmd import dim_support as DS
from app.cmd import jig
from app.cmd.context import CommandError
from app.cmd.draw_support import pick_entity, pick_point
from app.cmd.registry import command, executes
from app.dim import vec as V_
from app.doc import geom
from app.doc.entities import Arc, Circle, Line, LwPolyline

NOT_ROUND = "Object selected is not a circle or arc."


def round_info(ent, pick):
    if isinstance(ent, (Circle, Arc)):
        return list(ent.center), float(ent.radius), ent
    if isinstance(ent, LwPolyline):
        i = DS.seg_nearest(ent, pick)
        if i is None:
            return None
        n = len(ent.vertices)
        v0, v1 = ent.vertices[i], ent.vertices[(i + 1) % n]
        arc = geom.bulge_to_arc(v0["p"], v1["p"], float(v0.get("bulge", 0.0) or 0.0))
        if arc is None:
            return None
        return list(arc[0]), float(arc[1]), None
    return None


def _radial(ctx, kind, c, r, loc, st, obj, jog=None):
    u = V_.unit(V_.sub(V_.xy(loc), V_.xy(c)))
    ang = V_.ang_of(u)
    P = [c[0] + u[0] * r, c[1] + u[1] * r, 0.0]
    hints = {}
    if kind == "diameter":
        F = [c[0] - u[0] * r, c[1] - u[1] * r, 0.0]
        e = DS.new_dimension(ctx, "diameter", def_point=F, p15=P, text_point=loc, text_moved=True)
        if obj is not None:
            hints = {"def_point": {"h": obj.handle, "t": "ang", "a": ang + math.pi}, "p15": {"h": obj.handle, "t": "ang", "a": ang}}
    else:
        e = DS.new_dimension(ctx, "jogged" if jog else "radius", def_point=c, p15=P, text_point=loc, text_moved=True)
        if obj is not None:
            hints = {"def_point": {"h": obj.handle, "t": "center"}, "p15": {"h": obj.handle, "t": "ang", "a": ang}}
        if jog:
            e.marks["jog_center"] = [jog[0][0], jog[0][1]]
            if jog[1] is not None:
                e.marks["jog_point"] = [jog[1][0], jog[1][1]]
    DS.apply_state(e, st)
    return e, hints


def _pick_round(ctx, msg):
    while True:
        r = yield ctx.entity(msg)
        if r.kind != "entity":
            return None
        ent = pick_entity(ctx, r.value)
        info = round_info(ent, pick_point(r.value)) if ent is not None else None
        if info is None:
            ctx.say(NOT_ROUND)
            continue
        return info


def _run_radial(ctx, kind):
    info = yield from _pick_round(ctx, "Select arc or circle")
    if info is None:
        return
    c, r, obj = info
    st = {}

    def build(p, s):
        if geom.dist(p, c) < geom.EPS:
            return None
        return _radial(ctx, kind, c, r, p, s, obj)[0]

    res = yield from DS.location_prompt(ctx, "Specify dimension line location", [], st, build)
    if res.kind != "point":
        return
    if geom.dist(res.value, c) < geom.EPS:
        ctx.say("The location must differ from the center.")
        return
    e, hints = _radial(ctx, kind, c, r, res.value, st, obj)
    h = DS.commit_dimension(ctx, e, hints)
    if st.get("override") is not None:
        DS.echo_text(ctx, ctx.d.get(h))


@command("dimradius", aliases=("dra", "dimrad"), group="annotate", label="Radius", description="Radius dimension of a circle or arc.", menu="Dimension > Radius")
def dimradius(ctx):
    yield from _run_radial(ctx, "radius")


@command("dimdiameter", aliases=("ddi", "dimdia"), group="annotate", label="Diameter", description="Diameter dimension of a circle or arc.", menu="Dimension > Diameter")
def dimdiameter(ctx):
    yield from _run_radial(ctx, "diameter")


@command("dimjogged", aliases=("djo", "jog"), group="annotate", label="Jogged", description="Jogged radius dimension with an overridden centre and a jog.", menu="Dimension > Jogged")
def dimjogged(ctx):
    info = yield from _pick_round(ctx, "Select arc or circle")
    if info is None:
        return
    c, r, obj = info
    o = yield ctx.point("Specify center location override", jig=lambda p: [jig.line(c, p)])
    if o.kind != "point":
        return
    st = {}

    def build(p, s):
        if geom.dist(p, c) < geom.EPS:
            return None
        return _radial(ctx, "radius", c, r, p, s, obj, (o.value, None))[0]

    res = yield from DS.location_prompt(ctx, "Specify dimension line location", [], st, build)
    if res.kind != "point":
        return
    P = V_.add(V_.xy(c), V_.mul(V_.unit(V_.sub(V_.xy(res.value), V_.xy(c))), r))
    j = yield ctx.point("Specify jog location", base=[P[0], P[1], 0.0], default_text="halfway", jig=lambda p: DS.preview(ctx, _radial(ctx, "radius", c, r, res.value, st, obj, (o.value, p))[0]))
    jp = j.value if j.kind == "point" else None
    if j.kind not in ("point", "enter"):
        return
    e, hints = _radial(ctx, "radius", c, r, res.value, st, obj, (o.value, jp))
    DS.commit_dimension(ctx, e, hints)


@command("dimcenter", aliases=("dce",), group="annotate", label="Center Mark", description="Centre mark of a circle or arc sized by the dimension style.", menu="Dimension > Center Mark")
def dimcenter(ctx):
    info = yield from _pick_round(ctx, "Select arc or circle")
    if info is None:
        return
    c, r, obj = info
    e = DS.new_dimension(ctx, "center", def_point=c, p15=c, text_point=c)
    e.marks["radius"] = r
    DS.commit_dimension(ctx, e, {"p15": {"h": obj.handle, "t": "center"}} if obj is not None else None)


def _exec_round(ctx, args, kind):
    ent = ctx.d.get(int(args["handle"]))
    info = round_info(ent, args.get("pick", [0.0, 0.0])) if ent is not None else None
    if info is None:
        raise CommandError(NOT_ROUND)
    c, r, obj = info
    loc = geom.as_pt(args["location"])
    if geom.dist(loc, c) < geom.EPS:
        raise CommandError("The location must differ from the center.")
    st = {}
    if args.get("text") is not None:
        st["override"] = str(args["text"])
    jog = None
    if args.get("jog_center") is not None:
        jog = (geom.as_pt(args["jog_center"]), geom.as_pt(args["jog_point"]) if args.get("jog_point") is not None else None)
    e, hints = _radial(ctx, kind, c, r, loc, st, obj, jog)
    h = DS.commit_dimension(ctx, e, hints)
    return {"created": h, "measurement": ctx.d.get(h).measurement}


@executes("dimradius")
def dimradius_exec(ctx, args):
    return _exec_round(ctx, args, "radius")


@executes("dimdiameter")
def dimdiameter_exec(ctx, args):
    return _exec_round(ctx, args, "diameter")


@executes("dimjogged")
def dimjogged_exec(ctx, args):
    if args.get("jog_center") is None:
        raise CommandError("Give jog_center.")
    return _exec_round(ctx, args, "radius")


@executes("dimcenter")
def dimcenter_exec(ctx, args):
    ent = ctx.d.get(int(args["handle"]))
    info = round_info(ent, args.get("pick", [0.0, 0.0])) if ent is not None else None
    if info is None:
        raise CommandError(NOT_ROUND)
    c, r, obj = info
    e = DS.new_dimension(ctx, "center", def_point=c, p15=c, text_point=c)
    e.marks["radius"] = r
    h = DS.commit_dimension(ctx, e, {"p15": {"h": obj.handle, "t": "center"}} if obj is not None else None)
    return {"created": h}


def line_points(ent, pick):
    if isinstance(ent, Line):
        return list(ent.start), list(ent.end), ({"h": ent.handle, "t": "start"}, {"h": ent.handle, "t": "end"})
    if isinstance(ent, LwPolyline):
        i = DS.seg_nearest(ent, pick)
        if i is None:
            return None
        n = len(ent.vertices)
        v0, v1 = ent.vertices[i], ent.vertices[(i + 1) % n]
        if abs(float(v0.get("bulge", 0.0) or 0.0)) > 1e-12:
            return None
        return list(v0["p"]), list(v1["p"]), ({"h": ent.handle, "t": "vertex", "i": i}, {"h": ent.handle, "t": "vertex", "i": (i + 1) % n})
    return None


def _angular_dim(ctx, form, data, loc, st):
    if form == "lines":
        (a, b), (c, d), hints = data
        e = DS.new_dimension(ctx, "angular", p13=a, p14=b, p15=c, p16=d, def_point=loc)
        if st.get("quad") is not None:
            e.marks["sector_pt"] = [st["quad"][0], st["quad"][1]]
        hh = {"p13": hints[0][0], "p14": hints[0][1], "p15": hints[1][0], "p16": hints[1][1]}
    else:
        centre, a, b, obj, fixed_ccw = data
        e = DS.new_dimension(ctx, "angular3", p13=a, p14=b, p15=centre, def_point=loc)
        a1 = V_.ang_of(V_.sub(V_.xy(a), V_.xy(centre)))
        a2 = V_.ang_of(V_.sub(V_.xy(b), V_.xy(centre)))
        if fixed_ccw is not None:
            e.marks["ccw"] = fixed_ccw
        else:
            probe = st.get("quad") if st.get("quad") is not None else loc
            phi = V_.ang_of(V_.sub(V_.xy(probe), V_.xy(centre)))
            e.marks["ccw"] = V_.ccw(a1, phi) <= V_.ccw(a1, a2) + 1e-12
        hh = {}
        if obj is not None:
            hh["p15"] = {"h": obj.handle, "t": "center"}
            if isinstance(obj, Arc):
                hh["p13"] = {"h": obj.handle, "t": "start"}
                hh["p14"] = {"h": obj.handle, "t": "end"}
    DS.apply_state(e, st)
    return e, hh


@command("dimangular", aliases=("dan", "dimang"), group="annotate", label="Angular", description="Angle between two lines, at an arc or circle, or three points.", menu="Dimension > Angular")
def dimangular(ctx):
    data = None
    form = None
    while data is None:
        pr = ctx.entity("Select arc, circle, line")
        pr.default_text = "specify vertex"
        r = yield pr
        if r.kind == "enter":
            v = yield ctx.point("Specify angle vertex")
            if v.kind != "point":
                return
            p1 = yield ctx.point("Specify first angle endpoint", base=v.value, jig=lambda p, vv=v.value: [jig.line(vv, p)])
            if p1.kind != "point":
                return
            p2 = yield ctx.point("Specify second angle endpoint", base=v.value, jig=lambda p, vv=v.value, pp=p1.value: [jig.line(vv, pp), jig.line(vv, p)])
            if p2.kind != "point":
                return
            if geom.dist(v.value, p1.value) < geom.EPS or geom.dist(v.value, p2.value) < geom.EPS:
                ctx.say("The endpoints must differ from the vertex.")
                return
            form, data = "three", (v.value, p1.value, p2.value, None, None)
            break
        if r.kind != "entity":
            return
        ent = pick_entity(ctx, r.value)
        pick = pick_point(r.value)
        if isinstance(ent, Arc):
            a, b = DS.arc_ends(ent)
            form, data = "three", (list(ent.center), [a[0], a[1], 0.0], [b[0], b[1], 0.0], ent, True)
        elif isinstance(ent, Circle):
            c = list(ent.center)
            u = V_.unit(V_.sub(V_.xy(pick), V_.xy(c)))
            p1 = [c[0] + u[0] * ent.radius, c[1] + u[1] * ent.radius, 0.0]
            e2 = yield ctx.point("Specify second angle endpoint", base=c, jig=lambda p, cc=c: [jig.line(cc, p)])
            if e2.kind != "point":
                return
            u2 = V_.unit(V_.sub(V_.xy(e2.value), V_.xy(c)))
            p2 = [c[0] + u2[0] * ent.radius, c[1] + u2[1] * ent.radius, 0.0]
            form, data = "three", (c, p1, p2, ent, None)
        else:
            lp = line_points(ent, pick) if ent is not None else None
            if lp is None:
                ctx.say("Select an arc, circle or line." if ent is not None else "*Invalid selection*")
                continue
            while True:
                r2 = yield ctx.entity("Select second line")
                if r2.kind != "entity":
                    return
                ent2 = pick_entity(ctx, r2.value)
                lp2 = line_points(ent2, pick_point(r2.value)) if ent2 is not None else None
                if lp2 is None:
                    ctx.say("Select a line.")
                    continue
                d1 = V_.sub(V_.xy(lp[1]), V_.xy(lp[0]))
                d2 = V_.sub(V_.xy(lp2[1]), V_.xy(lp2[0]))
                if abs(V_.cross(V_.unit(d1), V_.unit(d2))) < 1e-9:
                    ctx.say("The lines are parallel.")
                    continue
                break
            form, data = "lines", ((lp[0], lp[1]), (lp2[0], lp2[1]), (lp[2], lp2[2]))
    st = {}
    while True:
        def build(p, s):
            if form == "three" and geom.dist(p, data[0]) < geom.EPS:
                return None
            return _angular_dim(ctx, form, data, p, s)[0]

        res = yield from DS.location_prompt(ctx, "Specify dimension arc line location", ["Quadrant"], st, build)
        if res.kind == "keyword" and res.value == "Quadrant":
            q = yield ctx.point("Specify quadrant")
            if q.kind == "point":
                st["quad"] = q.value
            continue
        break
    if res.kind != "point":
        return
    e, hh = _angular_dim(ctx, form, data, res.value, st)
    h = DS.commit_dimension(ctx, e, hh)
    if st.get("override") is not None:
        DS.echo_text(ctx, ctx.d.get(h))


def _exec_angular(ctx, args):
    loc = geom.as_pt(args["location"])
    st = {}
    if args.get("text") is not None:
        st["override"] = str(args["text"])
    if args.get("quadrant") is not None:
        st["quad"] = geom.as_pt(args["quadrant"])
    if "vertex" in args:
        v = geom.as_pt(args["vertex"])
        data = (v, geom.as_pt(args["p1"]), geom.as_pt(args["p2"]), None, None)
        form = "three"
    elif "handle2" in args:
        e1 = ctx.d.get(int(args["handle"]))
        e2 = ctx.d.get(int(args["handle2"]))
        l1 = line_points(e1, args.get("pick", [0.0, 0.0])) if e1 is not None else None
        l2 = line_points(e2, args.get("pick2", [0.0, 0.0])) if e2 is not None else None
        if l1 is None or l2 is None:
            raise CommandError("Select a line.")
        if abs(V_.cross(V_.unit(V_.sub(V_.xy(l1[1]), V_.xy(l1[0]))), V_.unit(V_.sub(V_.xy(l2[1]), V_.xy(l2[0]))))) < 1e-9:
            raise CommandError("The lines are parallel.")
        form, data = "lines", ((l1[0], l1[1]), (l2[0], l2[1]), (l1[2], l2[2]))
    else:
        ent = ctx.d.get(int(args["handle"]))
        if isinstance(ent, Arc):
            a, b = DS.arc_ends(ent)
            form, data = "three", (list(ent.center), [a[0], a[1], 0.0], [b[0], b[1], 0.0], ent, True)
        elif isinstance(ent, Circle):
            c = list(ent.center)
            u = V_.unit(V_.sub(V_.xy(geom.as_pt(args["pick"])), V_.xy(c)))
            u2 = V_.unit(V_.sub(V_.xy(geom.as_pt(args["p2"])), V_.xy(c)))
            form, data = "three", (c, [c[0] + u[0] * ent.radius, c[1] + u[1] * ent.radius, 0.0], [c[0] + u2[0] * ent.radius, c[1] + u2[1] * ent.radius, 0.0], ent, None)
        else:
            raise CommandError("Select an arc, circle or line.")
    e, hh = _angular_dim(ctx, form, data, loc, st)
    h = DS.commit_dimension(ctx, e, hh)
    return {"created": h, "measurement": ctx.d.get(h).measurement}


@executes("dimangular")
def dimangular_exec(ctx, args):
    return _exec_angular(ctx, args)


def _arc_dim(ctx, ent, a, b, loc, st, whole):
    c = list(ent.center)
    e = DS.new_dimension(ctx, "arc", p13=a, p14=b, p15=c, def_point=loc)
    if not whole:
        e.marks["partial"] = True
    DS.apply_state(e, st)
    hints = {"p15": {"h": ent.handle, "t": "center"}}
    if whole:
        hints["p13"] = {"h": ent.handle, "t": "start"}
        hints["p14"] = {"h": ent.handle, "t": "end"}
    return e, hints


def _clamp_on_arc(ent, p):
    ang = V_.ang_of(V_.sub(V_.xy(p), V_.xy(ent.center)))
    s = geom.ccw_sweep(ent.start_angle, ent.end_angle)
    off = V_.ccw(ent.start_angle, ang)
    if off > s:
        off = s if (off - s) < (2 * math.pi - off) else 0.0
    q = geom.polar(ent.center, ent.radius, ent.start_angle + off)
    return [q[0], q[1], 0.0]


@command("dimarc", aliases=("dar",), group="annotate", label="Arc Length", description="Arc length dimension, whole arc or a partial span.", menu="Dimension > Arc Length")
def dimarc(ctx):
    while True:
        r = yield ctx.entity("Select arc or polyline arc segment")
        if r.kind != "entity":
            return
        ent = pick_entity(ctx, r.value)
        if isinstance(ent, Arc):
            break
        ctx.say("Select an arc.")
    a, b = DS.arc_ends(ent)
    a, b = [a[0], a[1], 0.0], [b[0], b[1], 0.0]
    whole = True
    st = {}
    while True:
        def build(p, s):
            if geom.dist(p, ent.center) < geom.EPS:
                return None
            return _arc_dim(ctx, ent, a, b, p, s, whole)[0]

        res = yield from DS.location_prompt(ctx, "Specify arc length dimension location", ["Partial"], st, build)
        if res.kind == "keyword" and res.value == "Partial":
            p1 = yield ctx.point("Specify first point for arc length dimension")
            if p1.kind != "point":
                continue
            p2 = yield ctx.point("Specify second point for arc length dimension")
            if p2.kind != "point":
                continue
            q1, q2 = _clamp_on_arc(ent, p1.value), _clamp_on_arc(ent, p2.value)
            if geom.dist(q1, q2) < geom.EPS:
                ctx.say("The two points must be different.")
                continue
            if V_.ccw(ent.start_angle, V_.ang_of(V_.sub(V_.xy(q1), V_.xy(ent.center)))) > V_.ccw(ent.start_angle, V_.ang_of(V_.sub(V_.xy(q2), V_.xy(ent.center)))):
                q1, q2 = q2, q1
            a, b, whole = q1, q2, False
            continue
        break
    if res.kind != "point":
        return
    e, hints = _arc_dim(ctx, ent, a, b, res.value, st, whole)
    h = DS.commit_dimension(ctx, e, hints)
    if st.get("override") is not None:
        DS.echo_text(ctx, ctx.d.get(h))


@executes("dimarc")
def dimarc_exec(ctx, args):
    ent = ctx.d.get(int(args["handle"]))
    if not isinstance(ent, Arc):
        raise CommandError("Select an arc.")
    loc = geom.as_pt(args["location"])
    a, b = DS.arc_ends(ent)
    a, b = [a[0], a[1], 0.0], [b[0], b[1], 0.0]
    whole = True
    if args.get("p1") is not None:
        q1, q2 = _clamp_on_arc(ent, geom.as_pt(args["p1"])), _clamp_on_arc(ent, geom.as_pt(args["p2"]))
        if geom.dist(q1, q2) < geom.EPS:
            raise CommandError("The two points must be different.")
        if V_.ccw(ent.start_angle, V_.ang_of(V_.sub(V_.xy(q1), V_.xy(ent.center)))) > V_.ccw(ent.start_angle, V_.ang_of(V_.sub(V_.xy(q2), V_.xy(ent.center)))):
            q1, q2 = q2, q1
        a, b, whole = q1, q2, False
    st = {}
    if args.get("text") is not None:
        st["override"] = str(args["text"])
    e, hints = _arc_dim(ctx, ent, a, b, loc, st, whole)
    h = DS.commit_dimension(ctx, e, hints)
    return {"created": h, "measurement": ctx.d.get(h).measurement}


def _ordinate(ctx, feature, end, kind, st):
    k = kind
    if k is None:
        k = "x" if abs(end[1] - feature[1]) >= abs(end[0] - feature[0]) else "y"
    e = DS.new_dimension(ctx, "ordinate", def_point=[0.0, 0.0, 0.0], p13=feature, p14=end)
    e.marks["ordinate"] = k
    DS.apply_state(e, st)
    return e


@command("dimordinate", aliases=("dor", "dimord"), group="annotate", label="Ordinate", description="Ordinate dimension (X or Y datum) from a feature point with a leader.", menu="Dimension > Ordinate")
def dimordinate(ctx):
    f = yield ctx.point("Specify feature location")
    if f.kind != "point":
        return
    st = {}
    kind = None
    while True:
        def build(p, s):
            if geom.dist(p, f.value) < geom.EPS:
                return None
            return _ordinate(ctx, f.value, p, kind, s)

        res = yield from DS.location_prompt(ctx, "Specify leader endpoint", ["Xdatum", "Ydatum"], st, build)
        if res.kind == "keyword":
            kind = "x" if res.value == "Xdatum" else "y"
            continue
        break
    if res.kind != "point" or geom.dist(res.value, f.value) < geom.EPS:
        return
    e = _ordinate(ctx, f.value, res.value, kind, st)
    h = DS.commit_dimension(ctx, e)
    if st.get("override") is not None:
        DS.echo_text(ctx, ctx.d.get(h))


@executes("dimordinate")
def dimordinate_exec(ctx, args):
    f = geom.as_pt(args["feature"])
    end = geom.as_pt(args["leader"])
    if geom.dist(f, end) < geom.EPS:
        raise CommandError("The leader endpoint must differ from the feature.")
    kind = None
    t = str(args.get("type", "")).lower()
    if t in ("x", "xdatum"):
        kind = "x"
    elif t in ("y", "ydatum"):
        kind = "y"
    st = {}
    if args.get("text") is not None:
        st["override"] = str(args["text"])
    e = _ordinate(ctx, f, end, kind, st)
    h = DS.commit_dimension(ctx, e)
    return {"created": h, "measurement": ctx.d.get(h).measurement}
