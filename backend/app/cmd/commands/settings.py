import fnmatch
import math
import re

from app.cmd import units
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.doc import geom
from app.doc.tables import LINEWEIGHTS, new_layer
from app.sysvars import registry as sv

BAD_NAME = set('<>/\\":;?*|=`')


@command("setvar", aliases=("set",), group="settings", label="Set Variable", description="Read or set a system variable.", menu="", transparent=True)
def setvar(ctx):
    r = yield ctx.word("Enter variable name", ["?"])
    if r.kind == "keyword":
        for entry in sv.listing(ctx.doc):
            ctx.say("%-24s%s" % (entry["name"], sv.format_value(entry["value"])))
        return
    if r.kind != "text":
        return
    name = r.value.strip().upper()
    if not sv.known(name) and name not in ctx.d.header:
        ctx.say("Unknown variable %s. Type SETVAR ? to list variables." % name)
        return
    vd = sv.BY_NAME[name] if name in sv.BY_NAME else None
    if vd is not None and sv.is_readonly(vd):
        ctx.say("%s = %s (read only)" % (name, sv.format_value(sv.get_var(ctx.doc, name))))
        return
    cur = sv.format_value(sv.get_var(ctx.doc, name))
    while True:
        v = yield ctx.text("Enter new value for %s" % name, cur)
        if v.kind == "enter":
            return
        try:
            sv.set_var(ctx.doc, name, v.value)
            return
        except sv.SysvarError as err:
            ctx.say(str(err))


@executes("setvar")
def setvar_exec(ctx, args):
    try:
        val = sv.set_var(ctx.doc, str(args.get("name", "")), args.get("value"))
    except sv.SysvarError as err:
        raise CommandError(str(err))
    return {"name": str(args.get("name", "")).upper(), "value": val}


@command("getvar", group="settings", label="Get Variable", description="Read a system variable.", menu="", transparent=True, undoable=False)
def getvar(ctx):
    r = yield ctx.word("Enter variable name")
    if r.kind != "text":
        return
    try:
        val = sv.get_var(ctx.doc, r.value)
    except sv.SysvarError as err:
        raise CommandError(str(err))
    ctx.say("%s = %s" % (r.value.upper(), sv.format_value(val)))


@command("sysvars", group="settings", label="System Variables", description="List all system variables and values.", menu="", undoable=False, repeatable=False)
def sysvars(ctx):
    for entry in sv.listing(ctx.doc):
        ctx.say("%-24s%s" % (entry["name"], sv.format_value(entry["value"])))
    yield from ()


def _valid_layer_name(name: str) -> bool:
    return bool(name) and not any(c in BAD_NAME for c in name) and len(name) <= 255


def _pick_layers(ctx, spec: str) -> list:
    out = []
    table = ctx.d.tables["layers"]
    for raw in spec.split(","):
        nm = raw.strip()
        if not nm:
            continue
        if any(c in nm for c in "*?"):
            hits = [r["name"] for r in table.values() if fnmatch.fnmatchcase(r["name"].casefold(), nm.casefold())]
            if not hits:
                ctx.say('Cannot find layer "%s".' % nm)
            out.extend(h for h in hits if h not in out)
        else:
            rec = table.get(nm)
            if rec is None:
                ctx.say('Cannot find layer "%s".' % nm)
            elif rec["name"] not in out:
                out.append(rec["name"])
    return out


def _layer_state(rec) -> str:
    bits = ["On" if rec["on"] else "Off", "Frozen" if rec["frozen"] else "Thawed", "Locked" if rec["locked"] else "Unlocked"]
    return " ".join(bits)


def _lw_text(v: int) -> str:
    if v == -3:
        return "Default"
    if v == -2:
        return "ByBlock"
    if v == -1:
        return "ByLayer"
    return "%.2f mm" % (v / 100.0)


def _list_layers(ctx, spec: str) -> None:
    names = _pick_layers(ctx, spec if spec else "*")
    ctx.say("Layer name                State          Color  Linetype     Lineweight")
    for n in sorted(names, key=str.casefold):
        rec = ctx.d.layer(n)
        ctx.say("%-25s %-14s %-6s %-12s %s" % (rec["name"], _layer_state(rec), sv.color_text(rec["color"]), rec["linetype"], _lw_text(rec["lineweight"])))
    ctx.say("Current layer: %s" % ctx.d.current_layer())


LAYER_OPTS = ["?", "Make", "Set", "New", "Rename", "ON", "OFF", "Color", "Ltype", "LWeight", "TRansparency", "Plot", "Freeze", "Thaw", "LOck", "Unlock", "stAte", "Description", "rEconcile", "MAterial"]


def _apply(ctx, names, fn):
    for n in names:
        rec = ctx.d.modify_record("layers", n)
        fn(rec)


@command("layer", aliases=("la", "layers"), group="format", label="Layer", description="Layer manager; typed option loop to make, set, create, rename and change layers.", menu="Format > Layer...")
def layer(ctx):
    d = ctx.d
    while True:
        r = yield ctx.keyword("Enter an option", LAYER_OPTS)
        if r.kind != "keyword":
            return
        k = r.value
        cur = d.current_layer()
        if k == "?":
            n = yield ctx.text("Enter layer name(s) to list", "*")
            if n.kind in ("text", "enter"):
                _list_layers(ctx, n.value if n.kind == "text" else "*")
        elif k == "Make":
            n = yield ctx.text("Enter name for new layer (becomes the current layer)", cur)
            if n.kind != "text":
                continue
            name = n.value.strip()
            rec = d.layer(name)
            if rec is None:
                if not _valid_layer_name(name):
                    ctx.say("Invalid layer name.")
                    continue
                d.table_set("layers", new_layer(name))
                rec = d.layer(name)
            d.set_header("CLAYER", rec["name"])
        elif k == "Set":
            n = yield ctx.text("Enter layer name to make current", cur)
            if n.kind != "text":
                continue
            rec = d.layer(n.value.strip())
            if rec is None:
                ctx.say('Cannot find layer "%s".' % n.value.strip())
                continue
            d.set_header("CLAYER", rec["name"])
        elif k == "New":
            n = yield ctx.text("Enter name list for new layer(s)")
            if n.kind != "text":
                continue
            for nm in [x.strip() for x in n.value.split(",") if x.strip()]:
                if not _valid_layer_name(nm):
                    ctx.say('Invalid layer name "%s".' % nm)
                elif d.layer(nm) is not None:
                    ctx.say('Layer "%s" already exists.' % nm)
                else:
                    d.table_set("layers", new_layer(nm))
        elif k == "Rename":
            o = yield ctx.text("Enter old layer name")
            if o.kind != "text":
                continue
            rec = d.layer(o.value.strip())
            if rec is None:
                ctx.say('Cannot find layer "%s".' % o.value.strip())
                continue
            if rec["name"].casefold() in ("0", "defpoints") or "|" in rec["name"]:
                ctx.say('Layer "%s" cannot be renamed.' % rec["name"])
                continue
            n = yield ctx.text("Enter new layer name")
            if n.kind != "text":
                continue
            new = n.value.strip()
            if not _valid_layer_name(new):
                ctx.say("Invalid layer name.")
                continue
            if d.layer(new) is not None and new.casefold() != rec["name"].casefold():
                ctx.say('Layer "%s" already exists.' % new)
                continue
            old = rec["name"]
            moved = dict(rec)
            moved["name"] = new
            d.table_remove("layers", old)
            d.table_set("layers", moved)
            for h, e in list(d.ents.items()):
                if e.layer.casefold() == old.casefold():
                    d.modify(h).layer = new
            if str(d.header.get("CLAYER", "0")).casefold() == old.casefold():
                d.set_header("CLAYER", new)
        elif k in ("ON", "OFF", "Freeze", "Thaw", "LOck", "Unlock"):
            verbs = {"ON": "turn on", "OFF": "turn off", "Freeze": "freeze", "Thaw": "thaw", "LOck": "lock", "Unlock": "unlock"}
            n = yield ctx.text("Enter layer name(s) to %s" % verbs[k], cur)
            if n.kind not in ("text", "enter"):
                continue
            names = _pick_layers(ctx, n.value if n.kind == "text" else cur)
            for nm in names:
                if nm.casefold() == cur.casefold():
                    if k == "OFF":
                        y = yield ctx.yesno('Really want layer "%s" (the CURRENT layer) off?' % nm, "No")
                        if y.kind != "keyword" or y.value != "Yes":
                            continue
                    elif k == "Freeze":
                        ctx.say('Cannot freeze layer "%s". It is the CURRENT layer.' % nm)
                        continue
                field, val = {"ON": ("on", True), "OFF": ("on", False), "Freeze": ("frozen", True), "Thaw": ("frozen", False), "LOck": ("locked", True), "Unlock": ("locked", False)}[k]
                d.modify_record("layers", nm)[field] = val
        elif k == "Color":
            c = yield ctx.word("Enter color name or number (1-255) [Truecolor]", [], None)
            if c.kind != "text":
                continue
            try:
                if c.value.strip().lower() in ("t", "truecolor"):
                    rgb = yield ctx.text("Red, Green, Blue")
                    if rgb.kind != "text":
                        continue
                    color = sv.parse_color(rgb.value)
                else:
                    color = sv.parse_color(c.value)
                if color in (0, 256):
                    raise sv.SysvarError("bad")
            except sv.SysvarError:
                ctx.say("Invalid color.")
                continue
            n = yield ctx.text("Enter name list of layer(s) for color %s" % sv.color_text(color), cur)
            if n.kind in ("text", "enter"):
                _apply(ctx, _pick_layers(ctx, n.value if n.kind == "text" else cur), lambda rec: rec.__setitem__("color", color))
        elif k == "Ltype":
            lt = yield ctx.text("Enter a loaded linetype name or [?]", "Continuous")
            if lt.kind != "text" and lt.kind != "enter":
                continue
            name = lt.value if lt.kind == "text" else "Continuous"
            if name.strip() == "?":
                for rec in d.tables["linetypes"].values():
                    ctx.say("%-14s %s" % (rec["name"], rec["description"]))
                continue
            rec = d.tables["linetypes"].get(name.strip())
            if rec is None or rec["name"].casefold() in ("bylayer", "byblock"):
                ctx.say('Linetype "%s" is not loaded. Load it with the LINETYPE command.' % name.strip())
                continue
            n = yield ctx.text("Enter name list of layer(s) for linetype %s" % rec["name"], cur)
            if n.kind in ("text", "enter"):
                lname = rec["name"]
                _apply(ctx, _pick_layers(ctx, n.value if n.kind == "text" else cur), lambda x: x.__setitem__("linetype", lname))
        elif k == "LWeight":
            w = yield ctx.number("Enter lineweight (0.0mm - 2.11mm)", minimum=0.0, maximum=2.11)
            if w.kind != "number":
                continue
            hundredths = min(LINEWEIGHTS, key=lambda x: abs(x - w.value * 100.0))
            n = yield ctx.text("Enter name list of layer(s) for lineweight %s" % _lw_text(hundredths), cur)
            if n.kind in ("text", "enter"):
                _apply(ctx, _pick_layers(ctx, n.value if n.kind == "text" else cur), lambda x: x.__setitem__("lineweight", hundredths))
        elif k == "TRansparency":
            t = yield ctx.number("Enter transparency value (0-90)", integer=True, minimum=0, maximum=90)
            if t.kind != "number":
                continue
            n = yield ctx.text("Enter name list of layer(s) for transparency %d" % t.value, cur)
            if n.kind in ("text", "enter"):
                tv = t.value
                _apply(ctx, _pick_layers(ctx, n.value if n.kind == "text" else cur), lambda x: x.__setitem__("transparency", tv))
        elif k == "Plot":
            p = yield ctx.keyword("Enter a plotting preference", ["Plot", "No"], "Plot")
            if p.kind != "keyword":
                continue
            n = yield ctx.text("Enter name list of layer(s) for plotting preference", cur)
            if n.kind in ("text", "enter"):
                flag = p.value == "Plot"
                _apply(ctx, _pick_layers(ctx, n.value if n.kind == "text" else cur), lambda x: x.__setitem__("plot", flag))
        elif k == "Description":
            t = yield ctx.text("Enter layer description")
            if t.kind != "text":
                continue
            n = yield ctx.text("Enter name list of layer(s) for description", cur)
            if n.kind in ("text", "enter"):
                desc = t.value
                _apply(ctx, _pick_layers(ctx, n.value if n.kind == "text" else cur), lambda x: x.__setitem__("description", desc))
        else:
            ctx.say("%s is not available yet." % k)


@executes("layer")
def layer_exec(ctx, args):
    d = ctx.d
    name = str(args.get("name", "")).strip()
    if not name:
        raise CommandError("A layer name is required.")
    rec = d.layer(name)
    if rec is None:
        if not _valid_layer_name(name):
            raise CommandError("Invalid layer name.")
        d.table_set("layers", new_layer(name))
        rec = d.layer(name)
    rec = d.modify_record("layers", rec["name"])
    if "color" in args:
        try:
            color = sv.parse_color(args["color"])
        except sv.SysvarError:
            raise CommandError("Invalid color.")
        if color in (0, 256):
            raise CommandError("Invalid color.")
        rec["color"] = color
    for key in ("on", "frozen", "locked", "plot"):
        if key in args:
            rec[key] = bool(args[key])
    if "linetype" in args:
        lt = d.tables["linetypes"].get(str(args["linetype"]))
        if lt is None:
            raise CommandError('Linetype "%s" is not loaded.' % args["linetype"])
        rec["linetype"] = lt["name"]
    if "lineweight" in args:
        rec["lineweight"] = min(LINEWEIGHTS, key=lambda x: abs(x - float(args["lineweight"]) * 100.0))
    if "transparency" in args:
        rec["transparency"] = max(0, min(90, int(args["transparency"])))
    if "description" in args:
        rec["description"] = str(args["description"])
    if args.get("make") or args.get("current"):
        d.set_header("CLAYER", rec["name"])
    return {"layer": rec["name"]}


def _units_sample(ctx):
    for i, label in ((1, "Scientific"), (2, "Decimal"), (3, "Engineering"), (4, "Architectural"), (5, "Fractional")):
        ctx.say("%d. %-14s%s" % (i, label, units.format_distance(15.5, i, 4)))
    ctx.say("")
    for i, label in ((0, "Decimal degrees"), (1, "Deg/min/sec"), (2, "Grads"), (3, "Radians"), (4, "Surveyor's units")):
        ctx.say("%d. %-18s%s" % (i, label, units.format_angle(math.radians(45.0), i, 4 if i != 3 else 4)))


@command("units", aliases=("un",), group="format", label="Units...", description="Set length and angle units and precision.", menu="Format > Units...", transparent=False)
def units_cmd(ctx):
    d = ctx.d
    h = d.header
    ctx.say("Report formatting examples:")
    _units_sample(ctx)
    lu = yield ctx.number("Enter choice, 1 to 5 for linear units", default=int(h.get("LUNITS", 2)), integer=True, minimum=1, maximum=5)
    if lu.kind != "number":
        return
    if lu.value in (4, 5):
        den = yield ctx.number("Enter denominator of smallest fraction to display (1, 2, 4, 8, 16, 32, 64, 128, or 256)", default=2 ** min(8, int(h.get("LUPREC", 4))), integer=True, minimum=1, maximum=256)
        if den.kind != "number":
            return
        if den.value & (den.value - 1):
            raise CommandError("The denominator must be a power of two.")
        prec = den.value.bit_length() - 1
    else:
        pr = yield ctx.number("Enter number of digits to right of decimal point (0 to 8)", default=int(h.get("LUPREC", 4)), integer=True, minimum=0, maximum=8)
        if pr.kind != "number":
            return
        prec = pr.value
    au = yield ctx.number("Enter choice, 0 to 4 for angular units", default=int(h.get("AUNITS", 0)), integer=True, minimum=0, maximum=4)
    if au.kind != "number":
        return
    ap = yield ctx.number("Enter number of fractional places for display of angles (0 to 8)", default=int(h.get("AUPREC", 0)), integer=True, minimum=0, maximum=8)
    if ap.kind != "number":
        return
    base = yield ctx.angle("Enter direction for angle 0", default=float(h.get("ANGBASE", 0.0)), absolute=False)
    if base.kind != "number":
        return
    cw = yield ctx.yesno("Do you want angles measured clockwise?", "Yes" if h.get("ANGDIR", 0) else "No")
    if cw.kind != "keyword":
        return
    ctx.setvar("LUNITS", lu.value)
    ctx.setvar("LUPREC", prec)
    ctx.setvar("AUNITS", au.value)
    ctx.setvar("AUPREC", ap.value)
    ctx.setvar("ANGBASE", math.degrees(base.value))
    ctx.setvar("ANGDIR", 1 if cw.value == "Yes" else 0)


command("-units", aliases=("-un",), group="format", label="Units", description="Command-line units settings.", menu="")(units_cmd)


@executes("units", "-units")
def units_exec(ctx, args):
    out = {}
    for key, var in (("lunits", "LUNITS"), ("luprec", "LUPREC"), ("aunits", "AUNITS"), ("auprec", "AUPREC"), ("angbase", "ANGBASE"), ("angdir", "ANGDIR"), ("insunits", "INSUNITS")):
        if key in args:
            out[var] = ctx.setvar(var, args[key])
    return out


def _view_box_fit(doc, box, margin):
    w = box[2] - box[0]
    h = box[3] - box[1]
    aspect = getattr(doc, "aspect", 1.6)
    height = max(h, w / aspect, 1e-6) * (1.0 + 2.0 * margin)
    return [(box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0], height


def _limits_box(d):
    lo = d.header.get("LIMMIN", [0.0, 0.0])
    hi = d.header.get("LIMMAX", [12.0, 9.0])
    return (lo[0], lo[1], hi[0], hi[1])


def _apply_view(ctx, mode, center, height, **extra):
    ctx.doc.set_view(center, height)
    ctx.doc.request_view(mode, center=list(center), height=height, **extra)
    ctx.say("Zoom %s" % mode.lower())


def _zoom_extents(ctx):
    box = ctx.d.extents(ctx.doc.current_space)
    if not box:
        box = _limits_box(ctx.d)
    center, height = _view_box_fit(ctx.doc, box, 0.05)
    _apply_view(ctx, "extents", center, height)


def _zoom_all(ctx):
    box = geom.union_bounds(ctx.d.extents(ctx.doc.current_space), _limits_box(ctx.d))
    center, height = _view_box_fit(ctx.doc, box, 0.02)
    _apply_view(ctx, "all", center, height)


def _zoom_scale(ctx, text):
    m = re.fullmatch(r"(\d*\.?\d+)(x|xp)?", text.strip().lower())
    if not m or float(m.group(1)) <= 0:
        raise CommandError("Requires a scale factor (n, nX or nXP).")
    n = float(m.group(1))
    if m.group(2):
        height = ctx.doc.view["height"] / n
    else:
        lim = _limits_box(ctx.d)
        height = (lim[3] - lim[1]) / n
    _apply_view(ctx, "scale", ctx.doc.view["center"], height, factor=n)


@command("zoom", aliases=("z",), group="view", label="Zoom", description="Zoom: window, scale, all, center, extents, previous, object.", menu="View > Zoom", transparent=True, undoable=False, repeatable=False)
def zoom(ctx):
    p = ctx.point("Specify corner of window, enter a scale factor (nX or nXP)", ["All", "Center", "Dynamic", "Extents", "Previous", "Scale", "Window", "Object"], default_text="real time")
    p.accepts = ("point", "number", "text")
    r = yield p
    if r.kind == "enter":
        ctx.doc.request_view("realtime")
        ctx.say("Realtime zoom is performed on the canvas.")
        return
    if r.kind == "number":
        _zoom_scale(ctx, str(r.value))
        return
    if r.kind == "text":
        _zoom_scale(ctx, r.value)
        return
    if r.kind == "point":
        o = yield ctx.point("Specify opposite corner", base=r.value, rect=True)
        if o.kind == "point":
            yield from _zoom_window(ctx, r.value, o.value)
        return
    if r.kind != "keyword":
        return
    k = r.value
    if k == "Extents":
        _zoom_extents(ctx)
    elif k == "All":
        _zoom_all(ctx)
    elif k == "Window":
        a = yield ctx.point("Specify first corner")
        if a.kind != "point":
            return
        b = yield ctx.point("Specify opposite corner", base=a.value, rect=True)
        if b.kind == "point":
            yield from _zoom_window(ctx, a.value, b.value)
    elif k == "Previous":
        hist = ctx.doc.view_history
        if not hist:
            ctx.say("No previous view saved.")
            return
        v = hist.pop()
        ctx.doc.view = dict(v)
        ctx.doc.request_view("previous", center=list(v["center"]), height=v["height"])
    elif k == "Center":
        c = yield ctx.point("Specify center point")
        if c.kind != "point":
            return
        cur = ctx.doc.view["height"]
        hgt = yield ctx.distance("Enter magnification or height", default=cur, positive=True)
        if hgt.kind == "number":
            _apply_view(ctx, "center", c.value, hgt.value)
        elif hgt.kind == "enter":
            _apply_view(ctx, "center", c.value, cur)
    elif k == "Scale":
        s = yield ctx.word("Enter a scale factor (nX or nXP)")
        if s.kind == "text":
            _zoom_scale(ctx, s.value)
    elif k == "Object":
        s = yield ctx.select("Select objects")
        if s.kind == "selection" and s.value:
            box = None
            for h in s.value:
                e = ctx.d.get(h)
                if e is not None:
                    box = geom.union_bounds(box, e.bounds())
            if box:
                center, height = _view_box_fit(ctx.doc, box, 0.05)
                _apply_view(ctx, "object", center, height)
    else:
        ctx.doc.request_view(k.lower())
        ctx.say("%s zoom is performed on the canvas." % k)


def _zoom_window(ctx, a, b):
    box = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
    if box[2] - box[0] < 1e-12 and box[3] - box[1] < 1e-12:
        raise CommandError("The window has no size.")
    center, height = _view_box_fit(ctx.doc, box, 0.0)
    _apply_view(ctx, "window", center, height)
    yield from ()


@executes("zoom")
def zoom_exec(ctx, args):
    mode = str(args.get("mode", "extents")).lower()
    if mode == "extents":
        _zoom_extents(ctx)
    elif mode == "all":
        _zoom_all(ctx)
    elif mode == "window":
        a, b = geom.as_pt(args["p1"]), geom.as_pt(args["p2"])
        for _ in _zoom_window(ctx, a, b):
            pass
    elif mode == "scale":
        _zoom_scale(ctx, str(args.get("factor", "1")))
    elif mode == "previous":
        hist = ctx.doc.view_history
        if not hist:
            raise CommandError("No previous view saved.")
        v = hist.pop()
        ctx.doc.view = dict(v)
        ctx.doc.request_view("previous", center=list(v["center"]), height=v["height"])
    else:
        raise CommandError("Unknown zoom mode.")
    return {"view": dict(ctx.doc.view), "request": ctx.doc.view_requests[-1] if ctx.doc.view_requests else None}


def _make_toggle(name, label, get, put, aliases=(), menu="", description=""):
    def run(ctx):
        cur = get(ctx)
        r = yield ctx.keyword("Enter mode", ["ON", "OFF"], "OFF" if cur else "ON")
        if r.kind != "keyword":
            return
        on = r.value == "ON"
        put(ctx, on)
        ctx.say("<%s %s>" % (label, "on" if on else "off"))

    def run_exec(ctx, args):
        state = args.get("state")
        cur = get(ctx)
        on = (not cur) if state is None else (str(state).lower() in ("on", "1", "true"))
        put(ctx, on)
        ctx.say("<%s %s>" % (label, "on" if on else "off"))
        return {"state": on}

    run.__name__ = name
    command(name, aliases=aliases, group="settings", label=label, description=description or "Toggle %s." % label.lower(), menu=menu, transparent=True, undoable=False, repeatable=False)(run)
    executes(name)(run_exec)


def _var_toggle(var):
    return (lambda ctx: bool(ctx.var(var))), (lambda ctx, on: ctx.setvar(var, 1 if on else 0))


def _bit_toggle(var, bit, inverted=False):
    def get(ctx):
        v = bool(int(ctx.var(var)) & bit)
        return (not v) if inverted else v

    def put(ctx, on):
        cur = int(ctx.var(var))
        want = (not on) if inverted else on
        ctx.setvar(var, (cur | bit) if want else (cur & ~bit))

    return get, put


def _ortho_put(ctx, on):
    ctx.setvar("ORTHOMODE", 1 if on else 0)
    if on:
        cur = int(ctx.var("AUTOSNAP"))
        ctx.setvar("AUTOSNAP", cur & ~8)


_g, _p = _var_toggle("ORTHOMODE")
_make_toggle("ortho", "Ortho", _g, _ortho_put, menu="", description="Constrain rubber-band points to horizontal or vertical (F8).")
_g, _p = _var_toggle("GRIDMODE")
_make_toggle("grid", "Grid", _g, _p, description="Toggle grid display (F7).")
_g, _p = _var_toggle("SNAPMODE")
_make_toggle("snap", "Snap", _g, _p, description="Toggle snap (F9).")
_g, _p = _bit_toggle("AUTOSNAP", 8)
_make_toggle("polar", "Polar", _g, _p, description="Toggle polar tracking (F10).")
_g, _p = _bit_toggle("AUTOSNAP", 16)
_make_toggle("otrack", "Otrack", _g, _p, description="Toggle object snap tracking (F11).")
_g, _p = _var_toggle("DYNMODE")
_make_toggle("dynmode", "Dynmode", _g, _p, description="Toggle dynamic input (F12).")
_g, _p = _bit_toggle("OSMODE", 16384, True)
_make_toggle("osnap", "Osnap", _g, _p, aliases=("os", "ddosnap"), description="Toggle running object snaps (F3).")
_g, _p = _var_toggle("LWDISPLAY")
_make_toggle("lwdisplay", "Lwdisplay", _g, _p, description="Show lineweights on screen.")


@command("id", group="inquiry", label="ID Point", description="Report the coordinates of a point and set LASTPOINT.", menu="Tools > Inquiry > ID Point", transparent=True, undoable=False, repeatable=False)
def id_point(ctx):
    r = yield ctx.point("Specify point")
    if r.kind == "point":
        p = r.value
        ctx.say("X = %s  Y = %s  Z = %s" % (ctx.fd(p[0]), ctx.fd(p[1]), ctx.fd(0.0)))


@command("dist", aliases=("di",), group="inquiry", label="Distance", description="Distance and angles between points.", menu="Tools > Inquiry > Distance", transparent=True, undoable=False, repeatable=False)
def dist_cmd(ctx):
    a = yield ctx.point("Specify first point")
    if a.kind != "point":
        return
    b = yield ctx.point("Specify second point", base=a.value)
    if b.kind != "point":
        return
    dx, dy = b.value[0] - a.value[0], b.value[1] - a.value[1]
    ang = math.atan2(dy, dx)
    ctx.say("Distance = %s,  Angle in XY Plane = %s,  Angle from XY Plane = %s" % (ctx.fd(math.hypot(dx, dy)), ctx.fa(ang), ctx.fa(0.0)))
    ctx.say("Delta X = %s,  Delta Y = %s,  Delta Z = %s" % (ctx.fd(dx), ctx.fd(dy), ctx.fd(0.0)))
