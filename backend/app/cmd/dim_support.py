import copy
import json
import math

from app.cmd.context import CommandError
from app.cmd.draw_support import with_jig
from app.dim import assoc, regen
from app.dim import vars as DV
from app.dim.vec import ang_of, dot, sub
from app.doc import geom
from app.doc.entities import Arc, Circle, Dimension, Line, LwPolyline


def current_style(ctx) -> str:
    name = ctx.d.header.get("DIMSTYLE", "Standard")
    rec = ctx.d.table_get("dimstyles", name)
    return rec["name"] if rec else "Standard"


def new_dimension(ctx, dim_type, **fields) -> Dimension:
    e = Dimension(dim_type=dim_type, style=current_style(ctx))
    for k, v in fields.items():
        setattr(e, k, v)
    for name in ("def_point", "text_point", "p13", "p14", "p15", "p16"):
        v = getattr(e, name)
        if v is not None:
            setattr(e, name, [float(v[0]), float(v[1]), 0.0])
    e.marks = dict(e.marks or {})
    return e


def commit_dimension(ctx, e, assoc_hints=None) -> int:
    ctx.stamp(e)
    regen.refresh(ctx.doc, e, None)
    try:
        h = ctx.d.add_entity(e, ctx.doc.current_space)
    except ValueError as err:
        raise CommandError(str(err))
    ent = ctx.d.modify(h)
    if int(ctx.d.header.get("DIMASSOC", 2)) != 0:
        assoc.attach(ctx.d, ent, ctx.doc.current_space, assoc_hints)
    ctx.mem["dim_last"] = h
    return h


def preview(ctx, e) -> list:
    from app.display.state import make_entry

    try:
        ctx.stamp(e)
        rctx = regen.make_context(ctx.doc)
        regen.refresh(ctx.doc, e, rctx)
        entry = make_entry(e, rctx, 0, 0)
        if entry is None:
            return []
        it = json.loads(entry.js)
    except Exception:
        return []
    it["h"] = None
    it["jig"] = True
    it["grips"] = []
    return [it]


def object_ok(ent, kinds) -> bool:
    return ent is not None and isinstance(ent, kinds)


def seg_nearest(poly: LwPolyline, p):
    best = None
    n = len(poly.vertices)
    cnt = n if poly.closed else n - 1
    for i in range(max(cnt, 0)):
        a = poly.vertices[i]["p"]
        b = poly.vertices[(i + 1) % n]["p"]
        dx, dy = b[0] - a[0], b[1] - a[1]
        den = dx * dx + dy * dy
        t = 0.0 if den < 1e-18 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / den))
        q = (a[0] + dx * t, a[1] + dy * t)
        dd = math.hypot(p[0] - q[0], p[1] - q[1])
        if best is None or dd < best[0]:
            best = (dd, i)
    return best[1] if best else None


def arc_ends(ent):
    return geom.polar(ent.center, ent.radius, ent.start_angle), geom.polar(ent.center, ent.radius, ent.end_angle)


def object_origins(ent, pick):
    if isinstance(ent, Line):
        return [ent.start[0], ent.start[1]], [ent.end[0], ent.end[1]], {"p13": {"h": ent.handle, "t": "start"}, "p14": {"h": ent.handle, "t": "end"}}
    if isinstance(ent, Arc):
        a, b = arc_ends(ent)
        return [a[0], a[1]], [b[0], b[1]], {"p13": {"h": ent.handle, "t": "start"}, "p14": {"h": ent.handle, "t": "end"}}
    if isinstance(ent, LwPolyline):
        i = seg_nearest(ent, pick)
        if i is None:
            return None
        n = len(ent.vertices)
        a = ent.vertices[i]["p"]
        b = ent.vertices[(i + 1) % n]["p"]
        return [a[0], a[1]], [b[0], b[1]], {"p13": {"h": ent.handle, "t": "vertex", "i": i}, "p14": {"h": ent.handle, "t": "vertex", "i": (i + 1) % n}}
    if isinstance(ent, Circle):
        c, r = ent.center, ent.radius
        return [c[0] - r, c[1]], [c[0] + r, c[1]], {}
    return None


def default_orientation(a, b, loc) -> float:
    xmin, xmax = min(a[0], b[0]), max(a[0], b[0])
    ymin, ymax = min(a[1], b[1]), max(a[1], b[1])
    if xmin <= loc[0] <= xmax:
        return 0.0
    if ymin <= loc[1] <= ymax:
        return math.pi / 2.0
    dx = max(xmin - loc[0], loc[0] - xmax)
    dy = max(ymin - loc[1], loc[1] - ymax)
    return math.pi / 2.0 if dx > dy else 0.0


def echo_text(ctx, e) -> None:
    ctx.say("Dimension text = %s" % regen.measurement_text(ctx.doc, e))


def ask_text(ctx):
    r = yield ctx.text("Enter dimension text <>")
    if r.kind == "text":
        return str(r.value)
    return None


def ask_mtext(ctx):
    r = yield ctx.text("Enter first line of dimension text <>")
    if r.kind != "text":
        return None
    lines = [str(r.value)]
    while True:
        r = yield ctx.text("Enter next line of dimension text or press Enter to finish")
        if r.kind != "text" or not str(r.value):
            break
        lines.append(str(r.value))
    return "\\P".join(lines)


def ask_text_angle(ctx):
    r = yield ctx.angle("Specify angle of dimension text", default=0.0)
    if r.kind == "number":
        return float(r.value)
    return None


def location_prompt(ctx, msg, extras, state, builder, default_text=""):
    while True:
        opts = ["Mtext", "Text", "Angle"] + list(extras)
        pr = ctx.point(msg, opts, default_text=default_text)

        def jg(p, _st=state):
            e = builder(p, _st)
            return preview(ctx, e) if e is not None else []

        with_jig(pr, jg)
        r = yield pr
        if r.kind == "keyword" and r.value in ("Mtext", "Text"):
            t = yield from (ask_mtext(ctx) if r.value == "Mtext" else ask_text(ctx))
            if t is not None:
                state["override"] = t
            continue
        if r.kind == "keyword" and r.value == "Angle":
            a = yield from ask_text_angle(ctx)
            if a is not None:
                state["text_angle"] = a
            continue
        return r


def apply_state(e, state):
    if state.get("override") is not None:
        e.text_override = state["override"]
    if state.get("text_angle") is not None:
        e.marks["text_angle"] = state["text_angle"]


def selectable_dimensions(ctx, handles):
    out = []
    for h in handles:
        e = ctx.d.get(h)
        if e is not None and e.kind == "dimension" and not ctx.locked(e):
            out.append(e)
    return out


def last_linear(ctx, base_handle=None):
    d = ctx.d
    if base_handle is not None:
        e = d.get(base_handle)
        if e is not None and e.kind == "dimension" and e.dim_type in ("linear", "aligned"):
            return e
    h = ctx.mem.get("dim_last")
    e = d.get(h) if h is not None else None
    if e is not None and e.kind == "dimension" and e.dim_type in ("linear", "aligned") and e.owner == ctx.doc.current_space:
        return e
    for ent in reversed(list(d.entities(ctx.doc.current_space))):
        if ent.kind == "dimension" and ent.dim_type in ("linear", "aligned"):
            return ent
    return None


def side_of(e):
    a, b = e.p13, e.p14
    th = float(e.rotation) if e.dim_type == "linear" else ang_of(sub((b[0], b[1]), (a[0], a[1])))
    n = (-math.sin(th), math.cos(th))
    mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
    s = dot(sub((e.def_point[0], e.def_point[1]), mid), n)
    return n if s >= 0 else (-n[0], -n[1])


def style_scale(ctx, e) -> float:
    return DV.scale_of(ctx.d, DV.of(ctx.d, e))


def clone_settings(src, dst):
    dst.style = src.style
    dst.overrides = copy.deepcopy(src.overrides)
    dst.layer = src.layer
