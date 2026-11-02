import copy

from app.cmd import props_flow as PF
from app.cmd.context import CommandError
from app.cmd.prompts import Prompt
from app.cmd.registry import command, executes
from app.doc import geom
from app.doc import props as P


def _handles(ctx, args):
    raw = args.get("handles")
    if raw is None:
        raw = list(ctx.doc.selection)
    return [int(h) for h in raw]


def _ents(ctx, handles):
    out = [ctx.d.get(int(h)) for h in handles]
    return [e for e in out if e is not None]


def _fail(err):
    raise CommandError(str(err))


@command("properties", aliases=("pr", "props", "ch"), group="modify", label="Properties", description="Report the properties of the selection.", menu="Modify > Properties", undoable=False, repeatable=False)
def properties(ctx):
    s = yield ctx.select("Select objects")
    if s.kind != "selection" or not s.value:
        return
    info = P.inspect(ctx.d, s.value)
    for e in _ents(ctx, s.value):
        ctx.say("%s  Handle = %X  Layer: %s  Color: %s  Linetype: %s" % (e.kind.upper(), e.handle, e.layer, P.color_text(e.color), e.linetype))
    for kind, rec in info["kinds"].items():
        for name, p in rec["props"].items():
            ctx.say("  %s %s: %s" % (kind, name, "varies" if p["varies"] else p["value"]))


@executes("properties")
def properties_exec(ctx, args):
    return P.inspect(ctx.d, _handles(ctx, args))


@command("properties.set", group="modify", label="Set Properties", description="Set properties and geometry fields on objects.", menu="")
def properties_set(ctx):
    s = yield ctx.select("Select objects")
    if s.kind != "selection" or not s.value:
        return
    ents = _ents(ctx, s.value)
    yield from PF.chprop_loop(ctx, ents)


@executes("properties.set")
def properties_set_exec(ctx, args):
    handles = _handles(ctx, args)
    ents = _ents(ctx, handles)
    skip = bool(args.get("skip_locked", False))
    locked = 0
    if skip:
        ents, locked = PF.editable_split(ctx, handles)
    try:
        n = P.apply_changes(ctx.d, ents, PF.check_args(args), args.get("kind"))
    except P.PropError as err:
        _fail(err)
    return {"changed": n, "locked": locked}


@command("chprop", group="modify", label="Change Properties", description="Change colour, layer, linetype, scale, lineweight, thickness or transparency.", menu="")
def chprop(ctx):
    s = yield ctx.select("Select objects")
    if s.kind != "selection" or not s.value:
        return
    ents, locked = PF.editable_split(ctx, s.value)
    PF.say_locked(ctx, locked)
    if not ents:
        return
    yield from PF.chprop_loop(ctx, ents)


@executes("chprop")
def chprop_exec(ctx, args):
    handles = _handles(ctx, args)
    ents, locked = PF.editable_split(ctx, handles)
    try:
        n = P.apply_changes(ctx.d, ents, PF.check_args(args))
    except P.PropError as err:
        _fail(err)
    return {"changed": n, "locked": locked}


def _set_z(lst, z):
    out = list(lst)
    while len(out) < 3:
        out.append(0.0)
    out[2] = z
    return out


def _z(p):
    return p[2] if len(p) > 2 else 0.0


def _same(vals):
    return all(abs(v - vals[0]) < 1e-12 for v in vals)


def set_elevation(ctx, e, z):
    k = e.kind
    if k == "line":
        if not _same([_z(e.start), _z(e.end)]):
            return "differs"
        e.start, e.end = _set_z(e.start, z), _set_z(e.end, z)
    elif k == "polyline3d":
        if not e.points or not _same([_z(p) for p in e.points]):
            return "differs"
        e.points = [_set_z(p, z) for p in e.points]
    elif k == "solid":
        if not e.corners or not _same([_z(p) for p in e.corners]):
            return "differs"
        e.corners = [_set_z(p, z) for p in e.corners]
    elif k in ("point", "text", "mtext", "insert", "attdef"):
        e.position = _set_z(e.position, z)
        if k == "text" and e.align_point is not None:
            e.align_point = _set_z(e.align_point, z)
    elif k in ("circle", "arc", "ellipse"):
        e.center = _set_z(e.center, z)
    elif k == "lwpolyline":
        e.elevation = z
    elif k == "hatch":
        e.elevation = z
        if e.associative:
            e.associative = False
            return "detached"
    else:
        return "skip"
    return "ok"


def _change_line(ctx, e, pt):
    near_start = geom.dist(e.start, pt) <= geom.dist(e.end, pt)
    other = e.end if near_start else e.start
    q = [pt[0], pt[1], _z(other)]
    if int(ctx.var("ORTHOMODE")):
        if abs(pt[0] - other[0]) >= abs(pt[1] - other[1]):
            q[1] = other[1]
        else:
            q[0] = other[0]
    if near_start:
        e.start = q
    else:
        e.end = q
    return geom.dist(e.start, e.end) > geom.EPS


def _style_fixed(ctx, e) -> bool:
    rec = ctx.d.table_get("textstyles", e.style)
    return bool(rec and float(rec.get("height", 0.0)) > 0)


def _ask_point(ctx, msg, base=None):
    r = yield Prompt(msg, ("point",), [], None, "no change", base)
    return r.value if r.kind == "point" else None


def _change_text(ctx, e, placed):
    if not placed:
        p = yield from _ask_point(ctx, "Specify new text insertion point" if e.kind != "attdef" else "Specify new text insertion point")
        if p is not None:
            _place_text(e, p)
    while True:
        r = yield Prompt("Enter new text style", ("text",), [], None, e.style)
        if r.kind != "text":
            break
        rec = ctx.d.table_get("textstyles", r.value.strip())
        if rec is None:
            ctx.say('Style "%s" not defined - use STYLE command.' % r.value.strip())
            continue
        e.style = rec["name"]
        break
    halign = getattr(e, "halign", 0)
    fixed = _style_fixed(ctx, e)
    if not fixed and halign != 3:
        r = yield Prompt("Specify new height", ("number",), [], None, ctx.fd(e.height), positive=True)
        if r.kind == "number":
            e.height = r.value
    if halign not in (3, 5):
        r = yield ctx.angle("Specify new rotation angle", default=e.rotation, absolute=False)
        if r.kind == "number":
            e.rotation = r.value
    if e.kind == "text":
        r = yield Prompt("Enter new text", ("text",), [], None, e.text, free_text=True)
        if r.kind == "text":
            e.text = r.value
    elif e.kind == "mtext":
        r = yield Prompt("Enter new text", ("text",), [], None, e.contents[:40], free_text=True)
        if r.kind == "text":
            e.contents = r.value
    else:
        for name, label in (("tag", "Enter new tag"), ("prompt", "Enter new prompt"), ("default", "Enter new default value")):
            r = yield Prompt(label, ("text",), [], None, getattr(e, name), free_text=True)
            if r.kind == "text":
                setattr(e, name, r.value)


def _place_text(e, p):
    anchor = e.align_point if getattr(e, "align_point", None) is not None else e.position
    d = [p[0] - anchor[0], p[1] - anchor[1], 0.0]
    e.move_by(d)


def _change_insert(ctx, e, placed):
    if not placed:
        p = yield from _ask_point(ctx, "Specify new block insertion point")
        if p is not None:
            e.move_by([p[0] - e.position[0], p[1] - e.position[1], 0.0])
    r = yield ctx.angle("Specify new block rotation angle", default=e.rotation, absolute=False)
    if r.kind == "number":
        e.rotation = r.value


def _change_circle(ctx, e, pt):
    if pt is not None:
        rad = geom.dist(e.center, pt)
        if rad > geom.EPS:
            e.radius = rad
        return
    r = yield Prompt("Specify new circle radius", ("distance",), [], None, "no change", positive=True)
    if r.kind == "number":
        e.radius = r.value


def _elev_flow(ctx, ents):
    r = yield Prompt("Specify new elevation", ("number",), [], None, "no change")
    if r.kind != "number":
        return
    differing = detached = 0
    for e in ents:
        live = ctx.d.modify(e.handle)
        res = set_elevation(ctx, live, r.value)
        if res == "differs":
            differing += 1
        elif res == "detached":
            detached += 1
    if differing:
        ctx.say("Cannot change elevation of objects with differing Z coordinates.")
    if detached:
        ctx.say("Hatch boundary associativity removed.")


@command("change", aliases=("-ch",), group="modify", label="Change", description="Change points and properties of lines, circles, text and blocks.", menu="")
def change(ctx):
    s = yield ctx.select("Select objects")
    if s.kind != "selection" or not s.value:
        return
    ents, locked = PF.editable_split(ctx, s.value)
    PF.say_locked(ctx, locked)
    if not ents:
        return
    r = yield Prompt("Specify change point", ("point",), ["Properties"], None, "")
    if r.kind == "keyword":
        yield from PF.chprop_loop(ctx, ents, ["Elev"], {"Elev": _elev_flow})
        return
    pt = r.value if r.kind == "point" else None
    single = len(ents) == 1
    if pt is not None and not single:
        ctx.say("Change point ignored")
    changed = 0
    for src in ents:
        e = ctx.d.modify(src.handle)
        k = e.kind
        if k == "line":
            if pt is not None and _change_line(ctx, e, pt):
                changed += 1
        elif k == "circle":
            before = e.radius
            yield from _change_circle(ctx, e, pt if (pt is not None and single) else None)
            changed += 1 if e.radius != before else 0
        elif k in ("text", "mtext", "attdef"):
            placed = pt is not None and single
            if placed:
                _place_text(e, pt)
            yield from _change_text(ctx, e, placed)
            changed += 1
        elif k == "insert":
            placed = pt is not None and single
            if placed:
                e.move_by([pt[0] - e.position[0], pt[1] - e.position[1], 0.0])
            yield from _change_insert(ctx, e, placed)
            changed += 1
    if not changed and not any(e.kind in ("line", "circle", "text", "mtext", "attdef", "insert") for e in ents):
        ctx.say("No changeable object selected")


@executes("change")
def change_exec(ctx, args):
    ents, locked = PF.editable_split(ctx, _handles(ctx, args))
    out = {"changed": 0, "ignored": 0, "differing_z": 0, "detached_hatches": 0, "locked": locked}
    pt = geom.as_pt(args["point"]) if args.get("point") is not None else None
    elev = args.get("elevation")
    if elev is not None:
        elev = P.finite("elevation", elev)
    if pt is None and elev is None:
        raise CommandError("Give a point or an elevation.")
    single = len(ents) == 1
    for src in ents:
        e = ctx.d.modify(src.handle)
        done = False
        if pt is not None:
            if e.kind == "line":
                done = _change_line(ctx, e, pt)
            elif e.kind == "circle" and single:
                rad = geom.dist(e.center, pt)
                if rad > geom.EPS:
                    e.radius = rad
                    done = True
            elif e.kind in ("text", "mtext", "attdef") and single:
                _place_text(e, pt)
                done = True
            elif e.kind == "insert" and single:
                e.move_by([pt[0] - e.position[0], pt[1] - e.position[1], 0.0])
                done = True
            elif e.kind in ("circle", "text", "mtext", "attdef", "insert"):
                out["ignored"] += 1
        if elev is not None:
            res = set_elevation(ctx, e, elev)
            if res == "ok":
                done = True
            elif res == "differs":
                out["differing_z"] += 1
            elif res == "detached":
                out["detached_hatches"] += 1
                done = True
        if done:
            out["changed"] += 1
    if not out["changed"] and not out["ignored"] and not out["differing_z"] and not out["detached_hatches"]:
        raise CommandError("No changeable object selected")
    return out


MATCH_KEYS = ("color", "layer", "linetype", "ltscale", "lineweight", "transparency", "thickness", "plotstyle", "dimension", "text", "hatch", "polyline", "viewport", "table", "multileader")
MATCH_OPTS = ["Color", "Layer", "LType", "LtScale", "LWeight", "Transparency", "Thickness", "PlotStyle", "Dimension", "Text", "Hatch", "Polyline", "Viewport", "Table", "Multileader", "Done"]
MATCH_WORD = {"Color": "color", "Layer": "layer", "LType": "linetype", "LtScale": "ltscale", "LWeight": "lineweight", "Transparency": "transparency", "Thickness": "thickness", "PlotStyle": "plotstyle", "Dimension": "dimension", "Text": "text", "Hatch": "hatch", "Polyline": "polyline", "Viewport": "viewport", "Table": "table", "Multileader": "multileader"}
TEXT_KINDS = ("text", "mtext", "attdef")
EXTRA_COPY = {"table": ("style", "table_style"), "mleader": ("style", "arrow_size", "landing_gap", "dogleg", "leader_type"), "viewport": ("display_locked", "scale")}


def match_settings(ctx) -> dict:
    cur = ctx.mem.get("matchprop")
    if cur is None:
        cur = {k: True for k in MATCH_KEYS}
        ctx.mem["matchprop"] = cur
    return cur


def settings_line(cur) -> str:
    return "Current active settings: " + " ".join(k for k in MATCH_KEYS if cur.get(k))


def normalise_settings(raw):
    if raw is None:
        return {k: True for k in MATCH_KEYS}
    if isinstance(raw, dict):
        out = {k: False for k in MATCH_KEYS}
        for k, v in raw.items():
            key = _setting_key(k)
            out[key] = bool(v)
        return out
    out = {k: False for k in MATCH_KEYS}
    for k in raw:
        out[_setting_key(k)] = True
    return out


def _setting_key(name):
    low = str(name).strip().lower().replace("_", "")
    low = {"ltype": "linetype", "lweight": "lineweight", "ltscale": "ltscale", "linetypescale": "ltscale", "mleader": "multileader"}.get(low, low)
    if low not in MATCH_KEYS:
        raise CommandError("Unknown setting: %s." % name)
    return low


def match_apply(ctx, src, dst, cur) -> bool:
    d = ctx.d
    live = d.modify(dst.handle)
    before = live.to_dict()
    if cur.get("color"):
        live.color = src.color
    if cur.get("layer"):
        live.layer = src.layer
    if cur.get("linetype"):
        live.linetype = src.linetype
    if cur.get("ltscale"):
        live.ltscale = src.ltscale
    if cur.get("lineweight"):
        live.lineweight = src.lineweight
    if cur.get("transparency"):
        live.transparency = src.transparency
    if cur.get("thickness"):
        live.thickness = src.thickness
    if cur.get("plotstyle"):
        live.plot_style = src.plot_style
    if cur.get("dimension") and src.kind == "dimension" and live.kind == "dimension":
        live.style = src.style
        live.overrides = copy.deepcopy(src.overrides)
    if cur.get("text") and src.kind in TEXT_KINDS and live.kind in TEXT_KINDS:
        live.style = src.style
        live.height = src.height
        for name in ("width_factor", "oblique"):
            if hasattr(src, name) and hasattr(live, name):
                setattr(live, name, getattr(src, name))
    if cur.get("hatch") and src.kind == "hatch" and live.kind == "hatch":
        for name in ("pattern", "pattern_scale", "pattern_angle", "gradient", "solid"):
            setattr(live, name, copy.deepcopy(getattr(src, name)))
    if cur.get("polyline") and src.kind == "lwpolyline" and live.kind == "lwpolyline":
        live.const_width = src.const_width
        live.linetype_gen = src.linetype_gen
    for key, kind in (("table", "table"), ("multileader", "mleader"), ("viewport", "viewport")):
        if cur.get(key) and src.kind == kind and live.kind == kind:
            for name in EXTRA_COPY[kind]:
                if hasattr(src, name) and hasattr(live, name):
                    setattr(live, name, copy.deepcopy(getattr(src, name)))
    return live.to_dict() != before


def _match_settings_flow(ctx, cur):
    ctx.say(settings_line(cur))
    while True:
        r = yield ctx.keyword("Enter a property to turn on or off", MATCH_OPTS, "Done")
        if r.kind != "keyword" or r.value == "Done":
            return
        key = MATCH_WORD[r.value]
        cur[key] = not cur.get(key)
        ctx.say(settings_line(cur))


@command("matchprop", aliases=("ma", "painter"), group="modify", label="Match Properties", description="Copy chosen properties from a source object to others.", menu="Modify > Match Properties")
def matchprop(ctx):
    cur = match_settings(ctx)
    ctx.say(settings_line(cur))
    s = yield ctx.select("Select source object", pick_one=True)
    if s.kind != "selection" or not s.value:
        return
    src = ctx.d.get(s.value[0])
    if src is None:
        return
    while True:
        p = ctx.select("Select destination object(s) or [Settings]")
        p.options = ["Settings"]
        r = yield p
        if r.kind == "keyword":
            yield from _match_settings_flow(ctx, cur)
            continue
        if r.kind != "selection" or not r.value:
            return
        done = 0
        for h in r.value:
            e = ctx.d.get(h)
            if e is None or e.handle == src.handle or ctx.locked(e):
                continue
            if match_apply(ctx, src, e, cur):
                done += 1
        ctx.say("%d objects changed." % done)


@executes("matchprop")
def matchprop_exec(ctx, args):
    src = ctx.d.get(int(args.get("source", 0)))
    if src is None:
        raise CommandError("Select source object.")
    cur = normalise_settings(args.get("properties"))
    targets = args.get("targets")
    if targets is None:
        targets = list(ctx.doc.selection)
    changed = skipped = 0
    for h in targets:
        e = ctx.d.get(int(h))
        if e is None or e.handle == src.handle or ctx.locked(e):
            skipped += 1
            continue
        if match_apply(ctx, src, e, cur):
            changed += 1
    return {"changed": changed, "skipped": skipped}
