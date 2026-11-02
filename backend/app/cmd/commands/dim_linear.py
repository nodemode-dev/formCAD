import math

from app.cmd import dim_support as DS
from app.cmd import jig
from app.cmd.context import CommandError
from app.cmd.draw_support import pick_entity, pick_point
from app.cmd.registry import command, executes
from app.dim import vars as DV
from app.doc import geom
from app.doc.entities import Circle

NO_BASE = "No linear dimension to continue. Create one with DIMLINEAR first."


def _make_linear(ctx, a, b, loc, st, forced, aligned, circle=None):
    if aligned:
        rot = 0.0
    elif forced is not None:
        rot = forced
    else:
        rot = DS.default_orientation(a, b, loc)
        if circle is not None and abs(rot - math.pi / 2.0) < 1e-9:
            c, r = circle.center, circle.radius
            a, b = [c[0], c[1] - r], [c[0], c[1] + r]
    e = DS.new_dimension(ctx, "aligned" if aligned else "linear", p13=a, p14=b, def_point=loc, rotation=rot)
    DS.apply_state(e, st)
    return e


def _run_linear(ctx, aligned):
    st = {}
    forced = None
    hints = {}
    circle = None
    p1 = yield ctx.point("Specify first extension line origin", default_text="select object")
    if p1.kind == "enter":
        while True:
            r = yield ctx.entity("Select object to dimension")
            if r.kind != "entity":
                return
            ent = pick_entity(ctx, r.value)
            res = DS.object_origins(ent, pick_point(r.value)) if ent is not None else None
            if res is None:
                ctx.say("Object cannot be dimensioned this way." if ent is not None else "*Invalid selection*")
                continue
            a, b, hints = res
            circle = ent if isinstance(ent, Circle) else None
            break
    elif p1.kind == "point":
        a = p1.value
        p2 = yield ctx.point("Specify second extension line origin", base=a, jig=lambda p: [jig.line(a, p)])
        if p2.kind != "point":
            return
        b = p2.value
    else:
        return
    if aligned and geom.dist(a, b) < geom.EPS:
        ctx.say("The two points must be different.")
        return
    while True:
        extras = [] if (aligned or forced is not None) else ["Horizontal", "Vertical", "Rotated"]
        r = yield from DS.location_prompt(ctx, "Specify dimension line location", extras, st, lambda p, s: _make_linear(ctx, a, b, p, s, forced, aligned, circle))
        if r.kind == "keyword":
            if r.value == "Horizontal":
                forced = 0.0
            elif r.value == "Vertical":
                forced = math.pi / 2.0
            elif r.value == "Rotated":
                ang = yield ctx.angle("Specify angle of dimension line", default=0.0)
                if ang.kind == "number":
                    forced = float(ang.value)
            continue
        break
    if r.kind != "point":
        return
    e = _make_linear(ctx, a, b, r.value, st, forced, aligned, circle)
    h = DS.commit_dimension(ctx, e, hints)
    if st.get("override") is not None:
        DS.echo_text(ctx, ctx.d.get(h))


@command("dimlinear", aliases=("dli", "dimlin"), group="annotate", label="Linear", description="Horizontal, vertical or rotated linear dimension from two origins or an object.", menu="Dimension > Linear")
def dimlinear(ctx):
    yield from _run_linear(ctx, False)


@command("dim", group="annotate", label="Dimension", description="Smart dimension entry; behaves as the linear dimension prompts.", menu="")
def dim(ctx):
    yield from _run_linear(ctx, False)


@command("dimaligned", aliases=("dal", "dimali"), group="annotate", label="Aligned", description="Dimension parallel to the line through two origins.", menu="Dimension > Aligned")
def dimaligned(ctx):
    yield from _run_linear(ctx, True)


def _exec_linear(ctx, args, aligned):
    a = geom.as_pt(args["p13"] if "p13" in args else args["from"])
    b = geom.as_pt(args["p14"] if "p14" in args else args["to"])
    loc = geom.as_pt(args["location"] if "location" in args else args["def_point"])
    if aligned and geom.dist(a, b) < geom.EPS:
        raise CommandError("The two points must be different.")
    forced = None
    o = str(args.get("orientation", "")).lower()
    if o in ("h", "horizontal"):
        forced = 0.0
    elif o in ("v", "vertical"):
        forced = math.pi / 2.0
    if "rotation" in args:
        forced = math.radians(float(args["rotation"]))
    st = {}
    if args.get("text") is not None:
        st["override"] = str(args["text"])
    if args.get("text_angle") is not None:
        st["text_angle"] = math.radians(float(args["text_angle"]))
    e = _make_linear(ctx, a, b, loc, st, forced, aligned)
    h = DS.commit_dimension(ctx, e)
    return {"created": h, "measurement": ctx.d.get(h).measurement}


@executes("dimlinear", "dim")
def dimlinear_exec(ctx, args):
    return _exec_linear(ctx, args, False)


@executes("dimaligned")
def dimaligned_exec(ctx, args):
    return _exec_linear(ctx, args, True)


def _chain_dim(ctx, base, a, b, loc, copy_from):
    th = float(base.rotation) if base.dim_type == "linear" else math.atan2(base.p14[1] - base.p13[1], base.p14[0] - base.p13[0])
    e = DS.new_dimension(ctx, "linear", p13=a, p14=b, def_point=loc, rotation=th)
    DS.clone_settings(copy_from, e)
    return e


def _near_end(dim, pick):
    p13, p14 = dim.p13, dim.p14
    return (list(p13), list(p14)) if geom.dist(p13, pick) <= geom.dist(p14, pick) else (list(p14), list(p13))


def _run_chain(ctx, baseline):
    base = DS.last_linear(ctx)
    if base is None:
        ctx.say(NO_BASE)
        return
    state = {"base": base, "created": []}

    def reset(src, pick=None):
        state["base"] = src
        if baseline:
            first, _other = _near_end(src, pick) if pick else (list(src.p13), list(src.p14))
            state["origin"] = first
            state["prev_def"] = list(src.def_point)
            state["side"] = DS.side_of(src)
        else:
            if pick:
                _near, far = _near_end(src, pick)
                state["origin"] = _near
            else:
                state["origin"] = list(src.p14)
            state["prev_def"] = list(src.def_point)
            state["side"] = DS.side_of(src)

    reset(base)

    def make(p):
        src = state["base"]
        if baseline:
            step = float(DV.of(ctx.d, src).get("DIMDLI", 0.0)) * DS.style_scale(ctx, src)
            pd = state["prev_def"]
            s = state["side"]
            loc = [pd[0] + s[0] * step, pd[1] + s[1] * step, 0.0]
        else:
            loc = list(state["prev_def"])
        return _chain_dim(ctx, src, state["origin"], p, loc, src)

    while True:
        pr = ctx.point("Specify a second extension line origin", ["Undo", "Select"], default="Select", default_text="Select", base=state["origin"])
        pr.jig = lambda p: DS.preview(ctx, make(p))
        r = yield pr
        if r.kind == "keyword" and r.value == "Undo":
            if state["created"]:
                h, prev = state["created"].pop()
                ctx.d.erase_entity(h)
                state["origin"], state["prev_def"] = prev
            else:
                ctx.say("Nothing to undo.")
            continue
        if r.kind == "keyword" and r.value == "Select":
            while True:
                s = yield ctx.entity("Select base dimension")
                if s.kind != "entity":
                    return
                ent = pick_entity(ctx, s.value)
                if ent is None or ent.kind != "dimension" or ent.dim_type not in ("linear", "aligned"):
                    ctx.say("Select a linear dimension.")
                    continue
                reset(ent, pick_point(s.value))
                break
            continue
        if r.kind != "point":
            return
        prev_state = (list(state["origin"]), list(state["prev_def"]))
        e = make(r.value)
        h = DS.commit_dimension(ctx, e)
        state["created"].append((h, prev_state))
        if baseline:
            state["prev_def"] = list(e.def_point)
        else:
            state["origin"] = list(r.value)


@command("dimcontinue", aliases=("dco", "dimcont"), group="annotate", label="Continue", description="Chain a new dimension from the last linear dimension second origin.", menu="Dimension > Continue")
def dimcontinue(ctx):
    yield from _run_chain(ctx, False)


@command("dimbaseline", aliases=("dba", "dimbase"), group="annotate", label="Baseline", description="Stack a new dimension from the last linear dimension first origin.", menu="Dimension > Baseline")
def dimbaseline(ctx):
    yield from _run_chain(ctx, True)


def _exec_chain(ctx, args, baseline):
    src = DS.last_linear(ctx, int(args["base"]) if "base" in args else None)
    if src is None:
        raise CommandError(NO_BASE)
    pts = [geom.as_pt(p) for p in args.get("points", [])]
    if not pts or len(pts) > 5000:
        raise CommandError("Give 1 to 5000 points.")
    origin = list(src.p13) if baseline else list(src.p14)
    pd = list(src.def_point)
    side = DS.side_of(src)
    step = float(DV.of(ctx.d, src).get("DIMDLI", 0.0)) * DS.style_scale(ctx, src)
    made = []
    for p in pts:
        loc = [pd[0] + side[0] * step, pd[1] + side[1] * step, 0.0] if baseline else list(pd)
        e = _chain_dim(ctx, src, origin, p, loc, src)
        made.append(DS.commit_dimension(ctx, e))
        if baseline:
            pd = loc
        else:
            origin = p
    return {"created": made}


@executes("dimcontinue")
def dimcontinue_exec(ctx, args):
    return _exec_chain(ctx, args, False)


@executes("dimbaseline")
def dimbaseline_exec(ctx, args):
    return _exec_chain(ctx, args, True)
