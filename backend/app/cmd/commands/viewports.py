import math

from app.cmd import jig
from app.cmd.commands.layouts import add_viewport, printable_rect, require_layout
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.cmd.prompts import Input
from app.doc import geom, layouts, viewports
from app.doc.model import SPACE_MODEL
from app.doc.tables import LINEWEIGHTS, new_layer
from app.sysvars import registry as sv

MVIEW_OPTS = ["ON", "OFF", "Fit", "Lock", "Object", "Polygonal", "Restore", "2", "3", "4"]
MAX_POLY = 1000
VPL_OPTS = ["?", "Freeze", "Thaw", "Reset", "Newfrz", "Vpvisdflt", "Color", "LType", "LWeight", "TRansparency", "PLotstyle"]
VPL_SCOPE = ["All", "Select", "Current", "Except current"]


def rect_jig(a):
    def show(p):
        return [jig.poly([[a[0], a[1], 0.0], [p[0], a[1], 0.0], [p[0], p[1], 0.0], [a[0], p[1], 0.0]], True)]

    return show


def only_viewports(ctx, handles) -> list:
    out = []
    for h in handles:
        e = ctx.d.get(int(h))
        if e is not None and e.kind == "viewport" and e.owner == ctx.doc.tab:
            out.append(e)
    return out


def add_all(ctx, rects, restore=None, clips=None) -> list:
    space = ctx.doc.tab
    made = []
    for i, rect in enumerate(rects):
        try:
            vp = add_viewport(ctx, space, rect, clip=clips[i] if clips else None, fit=restore is None)
        except viewports.ViewportError as err:
            raise CommandError(str(err))
        if restore is not None:
            tile = restore[i]
            vp.view_center = [float(tile["center"][0]), float(tile["center"][1]), 0.0]
            vp.scale = viewports.clamp_scale(float(tile["height"]) / vp.height)
        made.append(vp)
    return made


def tiles_rects(rec, region) -> tuple:
    x0, y0, x1, y1 = region
    w, h = x1 - x0, y1 - y0
    rects, tiles = [], []
    for t in rec.get("tiles", []):
        ll, ur = t.get("lower_left"), t.get("upper_right")
        if not ll or not ur or ur[0] <= ll[0] or ur[1] <= ll[1] or not t.get("height") or t["height"] <= 0:
            continue
        rects.append((x0 + w * ll[0], y0 + h * ll[1], x0 + w * ur[0], y0 + h * ur[1]))
        tiles.append(t)
    return rects, tiles


def corner_or_fit(ctx):
    p = ctx.point("Specify first corner", ["Fit"])
    p.default = "Fit"
    p.default_text = "Fit"
    r = yield p
    if r.kind == "keyword" or r.kind == "enter":
        return printable_rect(ctx.d, layouts.tab_label(ctx.doc))
    if r.kind != "point":
        return None
    o = yield ctx.point("Specify opposite corner", base=r.value, rect=True, jig=rect_jig(r.value))
    if o.kind != "point":
        return None
    return [r.value[0], r.value[1], o.value[0], o.value[1]]


def bulge_for(prev, a, b) -> float:
    if prev is None:
        return 0.0
    t = geom.angle_of(prev, a)
    chord = geom.angle_of(a, b)
    alpha = (chord - t + math.pi) % (2 * math.pi) - math.pi
    return math.tan(alpha / 2.0)


def poly_loop(ctx):
    s = yield ctx.point("Specify start point")
    if s.kind != "point":
        return None
    verts = [{"p": [s.value[0], s.value[1]], "bulge": 0.0}]
    arc_mode = False

    def show(p):
        pts = [[v["p"][0], v["p"][1], v["bulge"]] for v in verts] + [[p[0], p[1], 0.0]]
        return [jig.poly(pts, False)]

    while True:
        last = verts[-1]["p"]
        if arc_mode:
            r = yield ctx.point("Specify endpoint of arc", ["Line", "Close", "Undo"], base=last, jig=show)
        else:
            r = yield ctx.point("Specify next point", ["Arc", "Close", "Undo"], base=last, jig=show)
        if r.kind == "enter":
            r = Input("keyword", "Close")
        if r.kind == "keyword":
            k = r.value
            if k == "Arc":
                arc_mode = True
            elif k == "Line":
                arc_mode = False
            elif k == "Undo":
                if len(verts) > 1:
                    verts.pop()
                    if verts:
                        verts[-1]["bulge"] = 0.0
                else:
                    ctx.say("Nothing to undo.")
            elif k == "Close":
                if len(verts) < 3:
                    ctx.say("A polygonal viewport needs at least three points.")
                    continue
                return verts
            continue
        if r.kind != "point":
            return None
        if len(verts) >= MAX_POLY:
            ctx.say("The outline has too many vertices.")
            continue
        p = [r.value[0], r.value[1]]
        if geom.dist(p, last) < geom.EPS:
            continue
        prev = verts[-2]["p"] if len(verts) > 1 else None
        verts[-1]["bulge"] = bulge_for(prev, last, p) if arc_mode else 0.0
        verts.append({"p": p, "bulge": 0.0})


def build_polygon(ctx, verts):
    try:
        probe = viewports.make(ctx.doc, ctx.doc.tab, 0.0, 0.0, 1.0, 1.0, fit=False)
        viewports.apply_clip(probe, verts)
    except viewports.ViewportError as err:
        raise CommandError(str(err))
    return probe


def create_from_clip(ctx, verts) -> object:
    probe = build_polygon(ctx, verts)
    vp = add_viewport(ctx, ctx.doc.tab, [probe.center[0] - probe.width / 2, probe.center[1] - probe.height / 2, probe.center[0] + probe.width / 2, probe.center[1] + probe.height / 2], clip=probe.clip)
    return vp


def set_on(ctx, handles, value: bool) -> int:
    n = 0
    for vp in only_viewports(ctx, handles):
        ent = ctx.d.modify(vp.handle)
        ent.on = value
        if not value and ctx.doc.active_vp == vp.handle:
            ctx.doc.active_vp = 0
        n += 1
    return n


def set_lock(ctx, handles, value: bool) -> int:
    n = 0
    for vp in only_viewports(ctx, handles):
        ctx.d.modify(vp.handle).locked = value
        n += 1
    return n


def arrangement_rects(ctx, count, how, rect) -> list:
    x0, x1 = sorted((rect[0], rect[2]))
    y0, y1 = sorted((rect[1], rect[3]))
    return viewports.arrangement(count, how, x0, y0, x1, y1)


def done_created(ctx, made, restored=None) -> None:
    if restored:
        ctx.say('%d viewport(s) created from configuration "%s".' % (len(made), restored))
    else:
        ctx.say("%d viewport(s) created, zoomed to the model extents." % len(made))


@command("mview", aliases=("mv",), group="layout", label="Layout Viewports", description="Create and manage layout viewports.", menu="View > Viewports")
def mview(ctx):
    require_layout(ctx)
    p = ctx.point("Specify corner of viewport", MVIEW_OPTS)
    p.default = "Fit"
    p.default_text = "Fit"
    r = yield p
    if r.kind == "point":
        o = yield ctx.point("Specify opposite corner", base=r.value, rect=True, jig=rect_jig(r.value))
        if o.kind != "point":
            return
        done_created(ctx, add_all(ctx, [(r.value[0], r.value[1], o.value[0], o.value[1])]))
        return
    if r.kind != "keyword":
        return
    k = r.value
    if k == "Fit":
        done_created(ctx, add_all(ctx, [printable_rect(ctx.d, layouts.tab_label(ctx.doc))]))
        return
    if k in ("ON", "OFF"):
        s = yield ctx.select("Select objects")
        if s.kind != "selection":
            return
        vps = only_viewports(ctx, s.value)
        set_on(ctx, [v.handle for v in vps], k == "ON")
        ctx.say("%d viewport(s) selected." % len(vps))
        return
    if k == "Lock":
        v = yield ctx.keyword("Lock the view of viewports?", ["ON", "OFF"])
        if v.kind != "keyword":
            return
        s = yield ctx.select("Select objects")
        if s.kind != "selection":
            return
        vps = only_viewports(ctx, s.value)
        set_lock(ctx, [x.handle for x in vps], v.value == "ON")
        ctx.say("%d viewport(s) selected." % len(vps))
        return
    if k == "Object":
        e = yield ctx.entity("Select object to clip viewport")
        if e.kind != "entity":
            return
        ent = ctx.d.get(int(e.value["handle"]))
        if ent is None:
            ctx.say("Nothing selected.")
            return
        try:
            verts = viewports.clip_from_entity(ent)
        except viewports.ViewportError as err:
            ctx.say(str(err))
            return
        vp = create_from_clip(ctx, verts)
        ctx.d.erase_entity(ent.handle)
        done_created(ctx, [vp])
        return
    if k == "Polygonal":
        verts = yield from poly_loop(ctx)
        if verts is None:
            return
        done_created(ctx, [create_from_clip(ctx, verts)])
        return
    if k == "Restore":
        while True:
            n = yield ctx.text("Enter viewport configuration name or [?]", "*Active")
            if n.kind != "text":
                return
            name = str(n.value).strip()
            if name == "?":
                for rec in ctx.d.tables["vports"].values():
                    ctx.say("Configuration: %s" % rec["name"])
                continue
            rec = ctx.d.tables["vports"].get(name)
            if rec is None:
                ctx.say('Could not find viewport configuration "%s".' % name)
                continue
            break
        region = yield from corner_or_fit(ctx)
        if region is None:
            return
        x0, x1 = sorted((region[0], region[2]))
        y0, y1 = sorted((region[1], region[3]))
        rects, tiles = tiles_rects(rec, (x0, y0, x1, y1))
        if not rects:
            ctx.say("The configuration has no usable tiles.")
            return
        done_created(ctx, add_all(ctx, rects, restore=tiles), rec["name"])
        return
    count = int(k)
    how = None
    if count == 2:
        h = yield ctx.keyword("Enter viewport arrangement", ["Horizontal", "Vertical"], "Vertical")
    else:
        opts = ["Horizontal", "Vertical", "Above", "Below", "Left", "Right"] + (["Equal"] if count == 4 else [])
        h = yield ctx.keyword("Enter viewport arrangement", opts, "Right")
    if h.kind != "keyword":
        return
    how = h.value
    region = yield from corner_or_fit(ctx)
    if region is None:
        return
    done_created(ctx, add_all(ctx, arrangement_rects(ctx, count, how, region)))


@executes("mview")
def mview_exec(ctx, args):
    require_layout(ctx)
    d = ctx.d
    name = layouts.tab_label(ctx.doc)
    fit_rect = printable_rect(d, name)
    if "on" in args or "off" in args:
        on = [int(h) for h in args.get("on", [])]
        off = [int(h) for h in args.get("off", [])]
        n = set_on(ctx, on, True) + set_on(ctx, off, False)
        return {"changed": n}
    if "lock" in args:
        spec = args["lock"]
        n = set_lock(ctx, [int(h) for h in spec.get("handles", [])], bool(spec.get("value", True)))
        return {"changed": n}
    made = []
    if "object" in args:
        ent = d.get(int(args["object"]))
        if ent is None:
            raise CommandError("Nothing selected.")
        try:
            verts = viewports.clip_from_entity(ent)
        except viewports.ViewportError as err:
            raise CommandError(str(err))
        made = [create_from_clip(ctx, verts)]
        d.erase_entity(ent.handle)
    elif "polygon" in args:
        pts = args["polygon"]
        bulges = args.get("bulges") or [0.0] * len(pts)
        if len(pts) < 3 or len(pts) > MAX_POLY:
            raise CommandError("A polygonal viewport needs three or more points.")
        made = [create_from_clip(ctx, [{"p": [float(p[0]), float(p[1])], "bulge": float(b)} for p, b in zip(pts, bulges)])]
    elif "restore" in args:
        rec = d.tables["vports"].get(str(args["restore"]))
        if rec is None:
            raise CommandError('Could not find viewport configuration "%s".' % args["restore"])
        region = args.get("corners") or fit_rect
        c = [float(region[0][0]), float(region[0][1]), float(region[1][0]), float(region[1][1])] if isinstance(region[0], (list, tuple)) else region
        rects, tiles = tiles_rects(rec, (min(c[0], c[2]), min(c[1], c[3]), max(c[0], c[2]), max(c[1], c[3])))
        made = add_all(ctx, rects, restore=tiles)
    else:
        corners = args.get("corners")
        if corners:
            c = [float(corners[0][0]), float(corners[0][1]), float(corners[1][0]), float(corners[1][1])]
        else:
            c = fit_rect
        count = int(args.get("count", 1))
        if count not in (1, 2, 3, 4):
            raise CommandError("The count is 1, 2, 3 or 4.")
        made = add_all(ctx, arrangement_rects(ctx, count, str(args.get("arrangement", "")), c))
    done_created(ctx, made)
    return {"created": [v.handle for v in made]}


def clip_viewport(ctx, vp, verts) -> None:
    ent = ctx.d.modify(vp.handle)
    try:
        viewports.apply_clip(ent, verts)
    except viewports.ViewportError as err:
        raise CommandError(str(err))


@command("vpclip", group="layout", label="Clip Viewport", description="Clip a layout viewport to an object or polygon, or remove the clip.", menu="Modify > Clipping > Viewport")
def vpclip(ctx):
    require_layout(ctx)
    s = yield ctx.select("Select viewport to clip", pick_one=True)
    if s.kind != "selection":
        return
    vps = only_viewports(ctx, s.value)
    if not vps:
        ctx.say("Select a viewport.")
        return
    vp = vps[0]
    r = yield ctx.entity("Select clipping object", ["Polygonal", "Delete"])
    if r.kind == "keyword" and r.value == "Delete":
        if not vp.clip:
            ctx.say("The viewport is not clipped.")
            return
        viewports.clear_clip(ctx.d.modify(vp.handle))
        ctx.say("The viewport clip was removed.")
        return
    if r.kind == "keyword" and r.value == "Polygonal":
        verts = yield from poly_loop(ctx)
        if verts is None:
            return
        clip_viewport(ctx, vp, verts)
        return
    if r.kind != "entity":
        return
    ent = ctx.d.get(int(r.value["handle"]))
    if ent is None or ent.handle == vp.handle:
        ctx.say("Select a closed polyline, circle, ellipse or spline.")
        return
    try:
        verts = viewports.clip_from_entity(ent)
    except viewports.ViewportError as err:
        ctx.say(str(err))
        return
    clip_viewport(ctx, vp, verts)
    ctx.d.erase_entity(ent.handle)


@executes("vpclip")
def vpclip_exec(ctx, args):
    require_layout(ctx)
    vp = only_viewports(ctx, [args.get("handle", 0)])
    if not vp:
        raise CommandError("Select a viewport.")
    vp = vp[0]
    if args.get("delete"):
        if not vp.clip:
            raise CommandError("The viewport is not clipped.")
        viewports.clear_clip(ctx.d.modify(vp.handle))
        return {"clipped": False}
    if "polygon" in args:
        pts = args["polygon"]
        bulges = args.get("bulges") or [0.0] * len(pts)
        verts = [{"p": [float(p[0]), float(p[1])], "bulge": float(b)} for p, b in zip(pts, bulges)]
        if len(verts) < 3 or len(verts) > MAX_POLY:
            raise CommandError("A polygon needs three or more points.")
        clip_viewport(ctx, vp, verts)
        return {"clipped": True}
    ent = ctx.d.get(int(args.get("object", 0)))
    if ent is None or ent.handle == vp.handle:
        raise CommandError("Select a closed polyline, circle, ellipse or spline.")
    try:
        verts = viewports.clip_from_entity(ent)
    except viewports.ViewportError as err:
        raise CommandError(str(err))
    clip_viewport(ctx, vp, verts)
    ctx.d.erase_entity(ent.handle)
    return {"clipped": True}


def scope_viewports(ctx, scope: str, handles=None) -> list:
    d = ctx.d
    allv = [v for v in viewports.of_space(d, ctx.doc.tab)]
    s = str(scope).strip().casefold()
    if handles:
        return only_viewports(ctx, handles)
    if s == "all":
        return allv
    cur = ctx.doc.active_vp
    if s == "current":
        got = [v for v in allv if v.handle == cur]
        if not got:
            raise CommandError("There is no current viewport.")
        return got
    if s in ("except current", "except"):
        return [v for v in allv if v.handle != cur]
    raise CommandError("Choose All, Select, Current or Except current.")


def parse_lw(text):
    t = str(text).strip().casefold()
    if t in ("bylayer", "by layer", ""):
        return None
    if t in ("default",):
        return -3
    try:
        v = float(t.replace("mm", ""))
    except ValueError:
        raise CommandError("Enter a lineweight in millimetres such as 0.35.")
    snapped = min(LINEWEIGHTS, key=lambda w: abs(w - v * 100.0))
    if abs(snapped - v * 100.0) > 3.0:
        raise CommandError("That is not a standard lineweight.")
    return snapped


def vplayer_do(ctx, option: str, layers: str, scope: str, handles=None, value=None) -> dict:
    d = ctx.d
    o = option.casefold()
    if o in ("newfrz",):
        made = []
        for raw in str(layers).split(","):
            nm = raw.strip()
            if not nm:
                continue
            if d.tables["layers"].has(nm):
                ctx.say('Layer "%s" already exists.' % nm)
                continue
            if any(c in nm for c in '<>/\\":;?*|=`') or len(nm) > 255:
                raise CommandError('"%s" is not a valid layer name.' % nm)
            d.table_set("layers", new_layer(nm, new_vp_freeze=True))
            made.append(nm)
        for space in [s for s in d.spaces if s.startswith("layout:")]:
            for vp in viewports.of_space(d, space):
                ent = d.modify(vp.handle)
                for nm in made:
                    viewports.freeze(ent, nm)
        return {"created": made}
    found, missing = viewports.match_layers(d, layers)
    for nm in missing:
        ctx.say('Cannot find layer "%s".' % nm)
    if not found:
        raise CommandError("No layer found.")
    if o == "vpvisdflt":
        frozen = str(value).strip().casefold() in ("frozen", "freeze", "f", "true", "yes")
        for nm in found:
            d.modify_record("layers", nm)["new_vp_freeze"] = frozen
        return {"layers": found, "frozen": frozen}
    vps = scope_viewports(ctx, scope, handles)
    if not vps:
        raise CommandError("No viewport selected.")
    changed = 0
    for vp in vps:
        ent = d.modify(vp.handle)
        for nm in found:
            if o == "freeze":
                changed += viewports.freeze(ent, nm)
            elif o == "thaw":
                changed += viewports.thaw(ent, nm)
            elif o == "reset":
                want = bool(d.tables["layers"].get(nm).get("new_vp_freeze"))
                changed += viewports.freeze(ent, nm) if want else viewports.thaw(ent, nm)
                if viewports.clear_overrides(ent, nm):
                    changed += 1
            elif o == "color":
                if str(value).strip().casefold() in ("bylayer", "by layer"):
                    viewports.set_override(ent, nm, "color", None)
                else:
                    try:
                        viewports.set_override(ent, nm, "color", sv.parse_color(value))
                    except sv.SysvarError as err:
                        raise CommandError(str(err))
                changed += 1
            elif o == "ltype":
                if str(value).strip().casefold() in ("bylayer", "by layer"):
                    viewports.set_override(ent, nm, "linetype", None)
                else:
                    lt = d.table_get("linetypes", str(value))
                    if lt is None:
                        raise CommandError('Linetype "%s" is not loaded.' % value)
                    viewports.set_override(ent, nm, "linetype", lt["name"])
                changed += 1
            elif o == "lweight":
                viewports.set_override(ent, nm, "lineweight", parse_lw(value))
                changed += 1
            elif o == "transparency":
                if str(value).strip().casefold() in ("bylayer", "by layer"):
                    viewports.set_override(ent, nm, "transparency", None)
                else:
                    try:
                        t = float(value)
                    except (TypeError, ValueError):
                        raise CommandError("Transparency is a number from 0 to 90.")
                    if not 0 <= t <= 90:
                        raise CommandError("Transparency is a number from 0 to 90.")
                    viewports.set_override(ent, nm, "transparency", t)
                changed += 1
            elif o == "plotstyle":
                viewports.set_override(ent, nm, "plot_style", None if str(value).strip().casefold() in ("bylayer", "") else str(value))
                changed += 1
            else:
                raise CommandError("Unknown VPLAYER option %s." % option)
    return {"layers": found, "viewports": [v.handle for v in vps], "changed": changed}


def vplayer_list(ctx, vp) -> list:
    ctx.say("Layers currently frozen in viewport %d:" % vp.vp_id)
    for n in vp.frozen:
        ctx.say(n)
    return list(vp.frozen)


@command("vplayer", group="layout", label="Viewport Layers", description="Freeze, thaw and reset layers per viewport; set new viewport defaults.", menu="")
def vplayer(ctx):
    require_layout(ctx)
    while True:
        o = yield ctx.keyword("Enter an option", VPL_OPTS)
        if o.kind != "keyword":
            return
        k = o.value
        if k == "?":
            s = yield ctx.select("Select a viewport", pick_one=True)
            if s.kind != "selection":
                return
            vps = only_viewports(ctx, s.value)
            if not vps:
                ctx.say("Select a viewport.")
                continue
            vplayer_list(ctx, vps[0])
            continue
        if k == "Newfrz":
            n = yield ctx.text("Enter name(s) of new layers frozen in all viewports")
            if n.kind != "text":
                return
            try:
                vplayer_do(ctx, "newfrz", str(n.value), "all")
            except CommandError as err:
                ctx.say(str(err))
            continue
        verb = {"Freeze": "freeze", "Thaw": "thaw", "Reset": "reset", "Vpvisdflt": "set default visibility of", "Color": "change", "LType": "change", "LWeight": "change", "TRansparency": "change", "PLotstyle": "change"}[k]
        value = None
        if k in ("Color", "LType", "LWeight", "TRansparency", "PLotstyle"):
            label = {"Color": "color (index, name or r,g,b; BYLAYER removes)", "LType": "linetype (BYLAYER removes)", "LWeight": "lineweight in millimetres (BYLAYER removes)", "TRansparency": "transparency 0 to 90 (BYLAYER removes)", "PLotstyle": "plot style name (BYLAYER removes)"}[k]
            v = yield ctx.text("Enter %s" % label)
            if v.kind != "text":
                return
            value = str(v.value)
        n = yield ctx.text("Enter layer name(s) to %s" % verb)
        if n.kind != "text":
            return
        if k == "Vpvisdflt":
            v = yield ctx.keyword("Enter a default viewport visibility option", ["Frozen", "Thawed"], "Thawed")
            if v.kind != "keyword":
                return
            try:
                vplayer_do(ctx, "vpvisdflt", str(n.value), "all", value=v.value)
            except CommandError as err:
                ctx.say(str(err))
            continue
        sc = yield ctx.keyword("Enter an option", VPL_SCOPE, "Current")
        if sc.kind != "keyword":
            return
        handles = None
        if sc.value == "Select":
            s = yield ctx.select("Select viewports")
            if s.kind != "selection":
                return
            handles = [v.handle for v in only_viewports(ctx, s.value)]
            if not handles:
                ctx.say("Select viewports.")
                continue
        try:
            res = vplayer_do(ctx, k.casefold(), str(n.value), sc.value, handles, value)
            ctx.say("%d change(s) in %d viewport(s)." % (res["changed"], len(res["viewports"])))
        except CommandError as err:
            ctx.say(str(err))


@executes("vplayer")
def vplayer_exec(ctx, args):
    require_layout(ctx)
    opt = str(args.get("option", "list")).casefold()
    if opt in ("list", "?"):
        vps = only_viewports(ctx, [args.get("handle", 0)])
        if not vps:
            raise CommandError("Select a viewport.")
        return {"frozen": vplayer_list(ctx, vps[0])}
    names = args.get("layers", "")
    if isinstance(names, list):
        names = ",".join(str(n) for n in names)
    handles = [int(h) for h in args.get("viewports", [])] if isinstance(args.get("viewports"), list) else None
    scope = "select" if handles else str(args.get("scope", "current"))
    return vplayer_do(ctx, opt, str(names), scope, handles, args.get("value"))


def viewport_set(ctx, vp, args: dict) -> None:
    d = ctx.d
    ent = d.modify(vp.handle)
    if "scale" in args or "scaleText" in args:
        raw = args.get("scaleText", args.get("scale"))
        try:
            viewports.set_scale(ent, viewports.parse_scale(d, raw), d)
        except viewports.ViewportError as err:
            raise CommandError(str(err))
    if "locked" in args and not args["locked"]:
        ent.locked = False
    if "on" in args:
        ent.on = bool(args["on"])
        if not ent.on and ctx.doc.active_vp == ent.handle:
            ctx.doc.active_vp = 0
    if args.get("zoomExtents"):
        try:
            viewports.zoom_extents(ctx.doc, ent)
        except viewports.ViewportError as err:
            raise CommandError(str(err))
    if "viewCenter" in args or "viewHeight" in args:
        c = args.get("viewCenter", ent.view_center)
        try:
            if "viewHeight" in args:
                viewports.set_view(ent, c, float(args["viewHeight"]))
            elif ent.locked:
                raise viewports.ViewportError("The viewport is locked.")
            else:
                viewports.pan_view(ent, c)
        except (viewports.ViewportError, TypeError, ValueError) as err:
            raise CommandError(str(err))
    if "center" in args:
        c = args["center"]
        ent.move_by([float(c[0]) - ent.center[0], float(c[1]) - ent.center[1]])
    if "size" in args:
        w, h = float(args["size"][0]), float(args["size"][1])
        if w <= geom.EPS or h <= geom.EPS:
            raise CommandError("The viewport has no size.")
        ent.width, ent.height = w, h
    if "annoScale" in args:
        name = str(args["annoScale"])
        if name and not d.tables["scales"].has(name):
            raise CommandError('Annotation scale "%s" is not defined.' % name)
        ent.anno_scale = d.tables["scales"].get(name)["name"] if name else ""
    if "layer" in args:
        nm = str(args["layer"])
        if not d.tables["layers"].has(nm):
            raise CommandError('Layer "%s" not found.' % nm)
        ent.layer = d.tables["layers"].get(nm)["name"]
    if args.get("locked"):
        ent.locked = True


@command("viewport.set", group="layout", label="Viewport Properties", description="Set the scale, lock, view, annotation scale and display of layout viewports.", menu="", repeatable=False)
def viewport_set_cmd(ctx):
    ctx.say("Pass the viewport properties programmatically.")
    yield from ()


@executes("viewport.set")
def viewport_set_exec(ctx, args):
    handles = args.get("handles", [args.get("handle", 0)])
    vps = [e for e in (ctx.d.get(int(h)) for h in handles) if e is not None and e.kind == "viewport"]
    if not vps:
        raise CommandError("Select a viewport.")
    for vp in vps:
        viewport_set(ctx, vp, args)
    return {"viewports": [viewports.info(ctx.d, ctx.d.get(v.handle)) for v in vps]}


@command("viewport.list", group="layout", label="List Viewports", description="List the viewports of a layout.", menu="", undoable=False, repeatable=False)
def viewport_list_cmd(ctx):
    ctx.say("Pass the layout programmatically.")
    yield from ()


@executes("viewport.list")
def viewport_list_exec(ctx, args):
    name = args.get("layout") or (layouts.tab_label(ctx.doc) if ctx.doc.tab != SPACE_MODEL else "")
    if layouts.find(ctx.d, name) is None:
        raise CommandError('Layout "%s" not found.' % name)
    return {"viewports": [viewports.info(ctx.d, v) for v in viewports.of_layout(ctx.d, layouts.find(ctx.d, name)["name"])]}
