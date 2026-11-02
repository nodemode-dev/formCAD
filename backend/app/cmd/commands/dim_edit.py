import copy
import math

from app.cmd import dim_support as DS
from app.cmd.context import CommandError
from app.cmd.draw_support import pick_entity
from app.cmd.registry import command, executes
from app.dim import assoc, crossings, regen
from app.dim import vars as DV
from app.dim import vec as V_
from app.doc import geom

NOT_DIM = "Object selected is not a dimension."


def _dims(ctx, handles):
    return DS.selectable_dimensions(ctx, handles)


def _refresh(ctx, e):
    regen.refresh(ctx.doc, e, None)


def _pick_dim(ctx, msg, kinds=None, extra=()):
    while True:
        pr = ctx.entity(msg, list(extra))
        r = yield pr
        if r.kind != "entity":
            return r
        ent = pick_entity(ctx, r.value)
        if ent is None or ent.kind != "dimension":
            ctx.say(NOT_DIM)
            continue
        if kinds and ent.dim_type not in kinds:
            ctx.say("Select a linear or aligned dimension.")
            continue
        if ctx.locked(ent):
            ctx.say("The dimension is on a locked layer.")
            continue
        return r, ent


def _apply_edit(ctx, mode, value, handles):
    n = 0
    for dim in _dims(ctx, handles):
        e = ctx.d.modify(dim.handle)
        if mode == "home":
            e.text_moved = False
            e.marks.pop("text_angle", None)
            e.marks.pop("jog_text", None)
        elif mode == "new":
            e.text_override = "" if value in ("<>", None) else str(value)
        elif mode == "rotate":
            e.marks["text_angle"] = float(value)
        elif mode == "oblique":
            if e.dim_type not in ("linear", "aligned"):
                continue
            if value is None:
                e.marks.pop("oblique", None)
            else:
                e.marks["oblique"] = float(value)
        e.marks = dict(e.marks)
        _refresh(ctx, e)
        n += 1
    return n


def _edit_text_move(ctx, dim, mode, value=None):
    e = ctx.d.modify(dim.handle)
    ov = dict(e.overrides)
    if mode == "home":
        e.text_moved = False
        e.marks.pop("text_angle", None)
        ov.pop("DIMJUST", None)
    elif mode in ("left", "right", "center"):
        e.text_moved = False
        ov["DIMJUST"] = {"left": 1, "right": 2, "center": 0}[mode]
    elif mode == "angle":
        e.marks["text_angle"] = float(value)
    elif mode == "point":
        p = [value[0], value[1], 0.0]
        e.text_point = p
        e.text_moved = True
        V = DV.resolve(ctx.d, e.style, e.overrides)
        if int(V.get("DIMTMOVE", 0)) == 0:
            if e.dim_type in ("linear", "aligned"):
                e.def_point = list(p)
            elif e.dim_type in ("angular", "angular3", "arc"):
                c = _angular_centre(e)
                if c is not None:
                    rad = V_.dist(V_.xy(p), c)
                    u = V_.unit(V_.sub(V_.xy(e.def_point), c))
                    e.def_point = [c[0] + u[0] * rad, c[1] + u[1] * rad, 0.0]
    e.overrides = ov
    e.marks = dict(e.marks)
    _refresh(ctx, e)
    return e


def _angular_centre(e):
    from app.dim import sectors

    if e.dim_type == "angular":
        s = sectors.two_lines(e)
        return s["vertex"] if s else None
    return V_.xy(e.p15)


def _run_tedit(ctx, preset=None):
    got = yield from _pick_dim(ctx, "Select dimension")
    if not isinstance(got, tuple):
        return
    _r, dim = got
    if preset in ("home", "left", "right", "center"):
        _edit_text_move(ctx, dim, preset)
        return
    if preset == "angle":
        a = yield ctx.angle("Specify angle for dimension text", default=0.0)
        if a.kind == "number":
            _edit_text_move(ctx, dim, "angle", a.value)
        return

    def jg(p):
        tmp = copy.deepcopy(dim)
        tmp.handle = 0
        tmp.text_point = [p[0], p[1], 0.0]
        tmp.text_moved = True
        return DS.preview(ctx, tmp)

    pr = ctx.point("Specify new location for dimension text", ["Left", "Right", "Center", "Home", "Angle"])
    pr.jig = jg
    r = yield pr
    if r.kind == "point":
        _edit_text_move(ctx, dim, "point", r.value)
    elif r.kind == "keyword":
        if r.value == "Angle":
            a = yield ctx.angle("Specify angle for dimension text", default=0.0)
            if a.kind == "number":
                _edit_text_move(ctx, dim, "angle", a.value)
        else:
            _edit_text_move(ctx, dim, r.value.lower())


@command("dimtedit", aliases=("dimted",), group="annotate", label="Dimension Text Edit", description="Move or justify dimension text (Left, Right, Center, Home, Angle).", menu="")
def dimtedit(ctx):
    yield from _run_tedit(ctx)


@command("dimtedit.home", group="annotate", label="Home", description="Return dimension text to its default position.", menu="Dimension > Align Text > Home")
def dimtedit_home(ctx):
    yield from _run_tedit(ctx, "home")


@command("dimtedit.left", group="annotate", label="Left", description="Left-justify dimension text.", menu="Dimension > Align Text > Left")
def dimtedit_left(ctx):
    yield from _run_tedit(ctx, "left")


@command("dimtedit.center", group="annotate", label="Center", description="Centre dimension text.", menu="Dimension > Align Text > Center")
def dimtedit_center(ctx):
    yield from _run_tedit(ctx, "center")


@command("dimtedit.right", group="annotate", label="Right", description="Right-justify dimension text.", menu="Dimension > Align Text > Right")
def dimtedit_right(ctx):
    yield from _run_tedit(ctx, "right")


@command("dimtedit.angle", group="annotate", label="Angle", description="Rotate dimension text to an angle.", menu="Dimension > Align Text > Angle")
def dimtedit_angle(ctx):
    yield from _run_tedit(ctx, "angle")


@executes("dimtedit", "dimtedit.home", "dimtedit.left", "dimtedit.center", "dimtedit.right", "dimtedit.angle")
def dimtedit_exec(ctx, args):
    dim = ctx.d.get(int(args["handle"]))
    if dim is None or dim.kind != "dimension":
        raise CommandError(NOT_DIM)
    if ctx.locked(dim):
        raise CommandError("The dimension is on a locked layer.")
    mode = str(args.get("mode", "point")).lower()
    if mode == "point":
        _edit_text_move(ctx, dim, "point", geom.as_pt(args["point"]))
    elif mode == "angle":
        _edit_text_move(ctx, dim, "angle", math.radians(float(args["angle"])))
    elif mode in ("home", "left", "right", "center"):
        _edit_text_move(ctx, dim, mode)
    else:
        raise CommandError("Mode must be point, home, left, right, center or angle.")
    return {"changed": 1}


@command("dimedit", aliases=("ded", "dimed"), group="annotate", label="Dimension Edit", description="Home, New text, Rotate text or Oblique extension lines on dimensions.", menu="")
def dimedit(ctx):
    pr = ctx.keyword("Enter type of dimension editing", ["Home", "New", "Rotate", "Oblique"], "Home")
    pr.hint = "bare"
    r = yield pr
    if r.kind not in ("keyword", "enter"):
        return
    mode = (r.value if r.kind == "keyword" else "Home").lower()
    value = None
    if mode == "new":
        t = yield ctx.text("Enter new dimension text <>")
        value = t.value if t.kind == "text" else "<>"
    elif mode == "rotate":
        a = yield ctx.angle("Specify angle for dimension text", default=0.0)
        if a.kind != "number":
            return
        value = a.value
    elif mode == "oblique":
        a = yield ctx.angle("Enter obliquing angle (press ENTER for none)")
        value = a.value if a.kind == "number" else None
    s = yield ctx.select("Select objects")
    if s.kind != "selection" or not s.value:
        return
    n = _apply_edit(ctx, mode, value, s.value)
    ctx.say("%d dimension(s) changed." % n if n else "No dimensions selected.")


@command("dimedit.oblique", group="annotate", label="Oblique", description="Oblique extension lines on selected dimensions.", menu="Dimension > Oblique")
def dimedit_oblique(ctx):
    s = yield ctx.select("Select objects")
    if s.kind != "selection" or not s.value:
        return
    a = yield ctx.angle("Enter obliquing angle (press ENTER for none)")
    n = _apply_edit(ctx, "oblique", a.value if a.kind == "number" else None, s.value)
    ctx.say("%d dimension(s) changed." % n if n else "No dimensions selected.")


@executes("dimedit", "dimedit.oblique")
def dimedit_exec(ctx, args):
    mode = str(args.get("mode", "home")).lower()
    handles = [int(h) for h in args.get("handles", [])]
    value = None
    if mode == "new":
        value = args.get("text", "<>")
    elif mode == "rotate":
        value = math.radians(float(args["angle"]))
    elif mode == "oblique":
        value = math.radians(float(args["angle"])) if args.get("angle") is not None else None
    elif mode != "home":
        raise CommandError("Mode must be home, new, rotate or oblique.")
    return {"changed": _apply_edit(ctx, mode, value, handles)}


def _set_overrides(ctx, handles, values, clear, text=None):
    n = 0
    for dim in _dims(ctx, handles):
        e = ctx.d.modify(dim.handle)
        ov = {} if clear else dict(e.overrides)
        for k, v in (values or {}).items():
            ov[k] = v
        e.overrides = ov
        if text is not None:
            e.text_override = str(text)
        _refresh(ctx, e)
        n += 1
    return n


def _validate_all(ctx, values):
    out = {}
    bad = []
    for k, v in values.items():
        try:
            out[DV.clean_name(k)] = DV.validate(ctx.doc, k, v)
        except KeyError:
            bad.append(k)
        except ValueError as err:
            raise CommandError(str(err))
    if bad:
        raise CommandError("Unknown dimension variable: %s." % ", ".join(str(b) for b in bad))
    return out


@command("dimoverride", aliases=("dov", "dimover"), group="annotate", label="Dimension Override", description="Override dimension variables on selected dimensions, or clear overrides.", menu="")
def dimoverride(ctx):
    values = {}
    clear = False
    while True:
        r = yield ctx.word("Enter dimension variable name to override", ["Clear overrides"])
        if r.kind == "enter":
            break
        if r.kind == "keyword" and r.value == "Clear overrides":
            clear = True
            break
        if r.kind != "text":
            return
        name = DV.clean_name(r.value)
        if not DV.known(name):
            ctx.say('Unknown dimension variable "%s".' % r.value)
            continue
        cur = DV.resolve(ctx.d, DS.current_style(ctx), {}).get(name)
        while True:
            v = yield ctx.text("Enter new value for dimension variable %s <%s>" % (name, DV.format_value(cur)))
            if v.kind != "text":
                break
            try:
                values[name] = DV.validate(ctx.doc, name, v.value)
                break
            except ValueError as err:
                ctx.say(str(err))
    s = yield ctx.select("Select objects")
    if s.kind != "selection" or not s.value:
        return
    n = _set_overrides(ctx, s.value, values, clear)
    ctx.say("%d dimension(s) changed." % n)


@executes("dimoverride")
def dimoverride_exec(ctx, args):
    handles = [int(h) for h in args.get("handles", [])]
    clear = bool(args.get("clear"))
    values = _validate_all(ctx, args.get("overrides", {}))
    n = _set_overrides(ctx, handles, values, clear, args.get("text"))
    return {"changed": n}


@command("dimstyle.update", group="annotate", label="Update", description="Apply the current dimension style to selected dimensions.", menu="Dimension > Update")
def dimstyle_update(ctx):
    s = yield ctx.select("Select objects")
    if s.kind != "selection" or not s.value:
        return
    n = _update(ctx, s.value)
    ctx.say("%d dimension(s) updated." % n)


def _update(ctx, handles):
    cur = DS.current_style(ctx)
    n = 0
    for dim in _dims(ctx, handles):
        e = ctx.d.modify(dim.handle)
        e.style = cur
        e.overrides = {}
        _refresh(ctx, e)
        n += 1
    return n


@executes("dimstyle.update")
def dimstyle_update_exec(ctx, args):
    return {"updated": _update(ctx, [int(h) for h in args.get("handles", [])])}


def _spacing(ctx, base, others, value):
    th = float(base.rotation) if base.dim_type == "linear" else V_.ang_of(V_.sub(V_.xy(base.p14), V_.xy(base.p13)))
    n = (-math.sin(th), math.cos(th))
    D0 = V_.xy(base.def_point)
    if value is None:
        value = float(DV.of(ctx.d, base).get("DIMDLI", 0.0)) * DS.style_scale(ctx, base)
    rows = []
    for e in others:
        if e.handle == base.handle or e.dim_type not in ("linear", "aligned"):
            continue
        th2 = float(e.rotation) if e.dim_type == "linear" else V_.ang_of(V_.sub(V_.xy(e.p14), V_.xy(e.p13)))
        if abs(math.sin(th2 - th)) > 1e-6:
            continue
        s = V_.dot(V_.sub(V_.xy(e.def_point), D0), n)
        rows.append((s, e))
    pos = sorted([r for r in rows if r[0] >= 0], key=lambda r: r[0])
    neg = sorted([r for r in rows if r[0] < 0], key=lambda r: -r[0])
    count = 0
    for k, (s, e) in enumerate(pos, 1):
        count += _move_line(ctx, e, n, (value * k) - s)
    for k, (s, e) in enumerate(neg, 1):
        count += _move_line(ctx, e, n, (-value * k) - s)
    return count


def _move_line(ctx, e, n, delta):
    ent = ctx.d.modify(e.handle)
    D = ent.def_point
    ent.def_point = [D[0] + n[0] * delta, D[1] + n[1] * delta, 0.0]
    if ent.text_moved and ent.text_point:
        T = ent.text_point
        ent.text_point = [T[0] + n[0] * delta, T[1] + n[1] * delta, 0.0]
    _refresh(ctx, ent)
    return 1


@command("dimspace", group="annotate", label="Dimension Space", description="Equal spacing of parallel linear dimensions from a base dimension.", menu="Dimension > Dimension Space")
def dimspace(ctx):
    got = yield from _pick_dim(ctx, "Select base dimension", ("linear", "aligned"))
    if not isinstance(got, tuple):
        return
    _r, base = got
    s = yield ctx.select("Select dimensions to space")
    if s.kind != "selection" or not s.value:
        return
    value = None
    while True:
        pr = ctx.number("Enter value", ["Auto"], default="Auto", default_text="Auto")
        v = yield pr
        if v.kind == "keyword" or v.kind == "enter" or (v.kind == "text" and str(v.value).lower().startswith("a")):
            break
        if v.kind == "number":
            if v.value < 0:
                ctx.say("Requires a non-negative number or Auto.")
                continue
            value = float(v.value)
            break
        return
    n = _spacing(ctx, base, _dims(ctx, s.value), value)
    ctx.say("%d dimension(s) spaced." % n)


@executes("dimspace")
def dimspace_exec(ctx, args):
    base = ctx.d.get(int(args["base"]))
    if base is None or base.kind != "dimension" or base.dim_type not in ("linear", "aligned"):
        raise CommandError("Select a linear dimension.")
    value = args.get("value")
    if isinstance(value, str) and value.lower() == "auto":
        value = None
    if value is not None and float(value) < 0:
        raise CommandError("Requires a non-negative number or Auto.")
    n = _spacing(ctx, base, _dims(ctx, [int(h) for h in args.get("handles", [])]), None if value is None else float(value))
    return {"spaced": n}


def _jog_default(ctx, e):
    out, _V, _S = regen.generate(ctx.doc, e)
    a1, w, L = out.notes.get("a1"), out.notes.get("w"), out.notes.get("L")
    if a1 is None:
        return None
    tc = out.text_center
    t_text = V_.dot(V_.sub(tc, a1), w) if tc is not None else L / 2.0
    t = max(0.0, min(L, t_text / 2.0))
    return [a1[0] + w[0] * t, a1[1] + w[1] * t]


@command("dimjogline", aliases=("djl",), group="annotate", label="Jog Line", description="Add or remove a jog symbol on a linear or aligned dimension line.", menu="Dimension > Jogged Linear")
def dimjogline(ctx):
    got = yield from _pick_dim(ctx, "Select dimension to add jog", ("linear", "aligned"), ["Remove"])
    if not isinstance(got, tuple):
        if got.kind == "keyword" and got.value == "Remove":
            g2 = yield from _pick_dim(ctx, "Select jog to remove", ("linear", "aligned"))
            if isinstance(g2, tuple):
                _clear_jog(ctx, g2[1])
        return
    _r, dim = got
    default = _jog_default(ctx, dim)

    def jg(p):
        tmp = copy.deepcopy(dim)
        tmp.handle = 0
        tmp.marks = dict(tmp.marks, jog=[p[0], p[1]])
        return DS.preview(ctx, tmp)

    pr = ctx.point("Specify jog location (or press ENTER)")
    pr.jig = jg
    r = yield pr
    if r.kind == "point":
        _set_jog(ctx, dim, [r.value[0], r.value[1]])
    elif r.kind == "enter" and default is not None:
        _set_jog(ctx, dim, default)


def _set_jog(ctx, dim, p):
    e = ctx.d.modify(dim.handle)
    e.marks = dict(e.marks, jog=[p[0], p[1]])
    _refresh(ctx, e)


def _clear_jog(ctx, dim):
    e = ctx.d.modify(dim.handle)
    m = dict(e.marks)
    m.pop("jog", None)
    e.marks = m
    _refresh(ctx, e)


@executes("dimjogline")
def dimjogline_exec(ctx, args):
    dim = ctx.d.get(int(args["handle"]))
    if dim is None or dim.kind != "dimension" or dim.dim_type not in ("linear", "aligned"):
        raise CommandError("Select a linear dimension.")
    if args.get("remove"):
        _clear_jog(ctx, dim)
        return {"changed": 1}
    p = args.get("point")
    if p is None:
        p = _jog_default(ctx, dim)
        if p is None:
            raise CommandError("The jog position could not be found.")
    _set_jog(ctx, dim, [float(p[0]), float(p[1])])
    return {"changed": 1}


MAX_EXAMINED = 2000
MAX_BREAKS = 50


def _auto_breaks(ctx, dim, only=None):
    out, V, S = regen.generate(ctx.doc, dim)
    size = max(float(V["DIMASZ"]) * S, 1e-9) if float(V["DIMASZ"]) > 0 else float(V["DIMTXT"]) * S * 0.5
    segs = [(p, q, role) for p, q, role in out.segs if role in ("dim", "ext1", "ext2")]
    pts = []
    examined = 0
    for ent in ctx.d.entities(ctx.doc.current_space):
        if ent.kind in ("dimension", "text", "mtext") or not ctx.d.visible(ent):
            continue
        if only is not None and ent.handle != only:
            continue
        examined += 1
        if examined > MAX_EXAMINED:
            break
        for sh in crossings.shapes_of(ent):
            for p, q, role in segs:
                for h in crossings.seg_hits(p, q, sh):
                    pts.append((h, role))
    uniq = []
    for h, role in pts:
        if all(V_.dist(h, u[0]) > size * 0.25 for u in uniq):
            uniq.append((h, role))
        if len(uniq) >= MAX_BREAKS:
            break
    return [{"p": [h[0], h[1]], "size": size, "auto": True, "on": role} for h, role in uniq]


def _manual_break(ctx, dim, p1, p2):
    out, V, S = regen.generate(ctx.doc, dim)
    size = V_.dist(p1, p2)
    mid = V_.mul(V_.add(p1, p2), 0.5)
    best = None
    for p, q, role in out.segs:
        if role not in ("dim", "ext1", "ext2"):
            continue
        d = V_.sub(q, p)
        ln = V_.length(d)
        if ln < 1e-12:
            continue
        t = max(0.0, min(ln, V_.dot(V_.sub(mid, p), d) / ln))
        c = V_.add(p, V_.mul(d, t / ln))
        dd = V_.dist(c, mid)
        if best is None or dd < best[0]:
            best = (dd, c, role)
    if best is None:
        return None
    return {"p": [best[1][0], best[1][1]], "size": size, "auto": False, "on": best[2]}


def _store_breaks(ctx, dim, add=None, remove=False):
    e = ctx.d.modify(dim.handle)
    m = dict(e.marks)
    if remove:
        m.pop("breaks", None)
    elif add:
        cur = [b for b in m.get("breaks", []) if b.get("auto") is False] if add and all(a.get("auto") for a in add) else list(m.get("breaks", []))
        m["breaks"] = cur + add
    e.marks = m
    _refresh(ctx, e)


@command("dimbreak", group="annotate", label="Dimension Break", description="Add or remove dimension line breaks where crossing other objects.", menu="Dimension > Dimension Break")
def dimbreak(ctx):
    multiple = False
    targets = []
    pr = ctx.entity("Select dimension to add/remove break", ["Multiple"])
    r = yield pr
    if r.kind == "keyword" and r.value == "Multiple":
        s = yield ctx.select("Select dimensions")
        if s.kind != "selection" or not s.value:
            return
        targets = _dims(ctx, s.value)
        multiple = True
    elif r.kind == "entity":
        ent = pick_entity(ctx, r.value)
        if ent is None or ent.kind != "dimension":
            ctx.say(NOT_DIM)
            return
        targets = [ent] if not ctx.locked(ent) else []
    else:
        return
    if not targets:
        ctx.say("No dimensions selected.")
        return
    while True:
        pr = ctx.entity("Select object to break dimension", ["Auto", "Manual", "Remove"])
        pr.default = "Auto"
        pr.default_text = "Auto"
        o = yield pr
        if o.kind == "keyword" and o.value == "Manual" and not multiple:
            p1 = yield ctx.point("Specify first break point")
            if p1.kind != "point":
                return
            p2 = yield ctx.point("Specify second break point", base=p1.value)
            if p2.kind != "point":
                return
            b = _manual_break(ctx, targets[0], p1.value, p2.value)
            if b is not None:
                _store_breaks(ctx, targets[0], [b])
            return
        if o.kind == "keyword" and o.value == "Remove":
            for t in targets:
                _store_breaks(ctx, t, remove=True)
            return
        if o.kind in ("enter",) or (o.kind == "keyword" and o.value == "Auto"):
            for t in targets:
                _store_breaks(ctx, t, _auto_breaks(ctx, t))
            return
        if o.kind == "entity":
            ent = pick_entity(ctx, o.value)
            if ent is None or ent.kind in ("dimension", "text", "mtext"):
                ctx.say("Select an object other than a dimension or text.")
                continue
            for t in targets:
                _store_breaks(ctx, t, _auto_breaks(ctx, t, ent.handle))
            return
        return


@executes("dimbreak")
def dimbreak_exec(ctx, args):
    handles = [int(h) for h in args.get("handles", [])]
    mode = str(args.get("mode", "auto")).lower()
    n = 0
    for dim in _dims(ctx, handles):
        if mode == "remove":
            _store_breaks(ctx, dim, remove=True)
        elif mode == "manual":
            b = _manual_break(ctx, dim, geom.as_pt(args["p1"]), geom.as_pt(args["p2"]))
            if b is None:
                continue
            _store_breaks(ctx, dim, [b])
        elif mode == "auto":
            only = int(args["object"]) if args.get("object") is not None else None
            _store_breaks(ctx, dim, _auto_breaks(ctx, dim, only))
        else:
            raise CommandError("Mode must be auto, manual or remove.")
        n += 1
    return {"changed": n}


def _inspect_apply(ctx, handles, shape, label, rate):
    n = 0
    for dim in _dims(ctx, handles):
        e = ctx.d.modify(dim.handle)
        m = dict(e.marks)
        if shape == "remove":
            m.pop("inspect", None)
        else:
            m["inspect"] = {"shape": shape, "label": label or "", "rate": rate or ""}
        e.marks = m
        _refresh(ctx, e)
        n += 1
    return n


@command("diminspect", group="annotate", label="Inspection", description="Add or remove an inspection frame (label, shape, rate) on dimensions.", menu="Dimension > Inspection")
def diminspect(ctx):
    s = yield ctx.select("Select dimensions")
    if s.kind != "selection" or not s.value:
        return
    pr = ctx.keyword("Enter inspection shape", ["Round", "Angular", "None", "Remove"], "Round")
    pr.hint = "bare"
    r = yield pr
    if r.kind not in ("keyword", "enter"):
        return
    shape = (r.value if r.kind == "keyword" else "Round").lower()
    label = rate = ""
    if shape != "remove":
        lt = yield ctx.text("Enter label (press ENTER for none)")
        label = str(lt.value) if lt.kind == "text" else ""
        rt = yield ctx.text("Enter inspection rate <100%>")
        rate = str(rt.value) if rt.kind == "text" else "100%"
        if rate and not rate.endswith("%"):
            rate += "%"
    n = _inspect_apply(ctx, s.value, shape, label, rate)
    ctx.say("%d dimension(s) changed." % n if n else "No dimensions selected.")


@executes("diminspect")
def diminspect_exec(ctx, args):
    shape = str(args.get("shape", "round")).lower()
    if shape not in ("round", "angular", "none", "remove"):
        raise CommandError("Shape must be round, angular, none or remove.")
    rate = str(args.get("rate", "100%"))
    if rate and not rate.endswith("%"):
        rate += "%"
    return {"changed": _inspect_apply(ctx, [int(h) for h in args.get("handles", [])], shape, str(args.get("label", "")), rate)}


@command("dimdisassociate", aliases=("dda",), group="annotate", label="Disassociate", description="Detach dimensions from their objects.", menu="Dimension > Disassociate")
def dimdisassociate(ctx):
    s = yield ctx.select("Select dimensions")
    if s.kind != "selection" or not s.value:
        return
    n = _disassociate(ctx, s.value)
    ctx.say("%d disassociated." % n)


def _disassociate(ctx, handles):
    n = 0
    for dim in _dims(ctx, handles):
        if not dim.associativity:
            continue
        e = ctx.d.modify(dim.handle)
        assoc.detach(e)
        n += 1
    return n


@executes("dimdisassociate")
def dimdisassociate_exec(ctx, args):
    return {"disassociated": _disassociate(ctx, [int(h) for h in args.get("handles", [])])}


@command("dimreassociate", aliases=("dre",), group="annotate", label="Reassociate", description="Attach definition points to the objects found under them.", menu="Dimension > Reassociate")
def dimreassociate(ctx):
    s = yield ctx.select("Select dimensions")
    if s.kind != "selection" or not s.value:
        return
    n, m = _reassociate(ctx, s.value)
    ctx.say("%d of %d dimension(s) associated." % (n, m))


def _reassociate(ctx, handles):
    dims = _dims(ctx, handles)
    n = 0
    for dim in dims:
        e = ctx.d.modify(dim.handle)
        got, _total = assoc.reassociate(ctx.d, e)
        if got:
            n += 1
    return n, len(dims)


@executes("dimreassociate")
def dimreassociate_exec(ctx, args):
    n, m = _reassociate(ctx, [int(h) for h in args.get("handles", [])])
    return {"associated": n, "total": m}


@command("dimregen", group="annotate", label="Regenerate Dimensions", description="Rebuild the drawn geometry and measured values of every dimension.", menu="Dimension > Regenerate")
def dimregen(ctx):
    n = _regen_all(ctx)
    ctx.say("%d dimension(s) regenerated." % n)
    yield from ()


def _regen_all(ctx, handles=None):
    n = 0
    for e in list(ctx.d.entities(ctx.doc.current_space)):
        if e.kind != "dimension" or ctx.locked(e):
            continue
        if handles is not None and e.handle not in handles:
            continue
        ent = ctx.d.modify(e.handle)
        ent.marks = {k: v for k, v in ent.marks.items() if k != "regen"}
        _refresh(ctx, ent)
        n += 1
    return n


@executes("dimregen")
def dimregen_exec(ctx, args):
    hs = {int(h) for h in args["handles"]} if args.get("handles") else None
    return {"regenerated": _regen_all(ctx, hs)}
