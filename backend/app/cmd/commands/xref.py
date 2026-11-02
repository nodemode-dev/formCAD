import math

from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.doc import xclip, xref
from app.doc.blocktools import EditError
from app.doc.entities import Insert
from app.doc.service import service

XREF_OPTS = ["?", "Bind", "Detach", "Path", "Unload", "Reload", "Overlay", "Attach"]


def _table(ctx, rows):
    ctx.say("%-24s%-9s%-13s%s" % ("Xref name", "Type", "Status", "Path"))
    for r in rows:
        ctx.say("%-24s%-9s%-13s%s" % (r["name"], r["type"], r["status"], r["path"]))
    ctx.say("Total xref(s): %d" % len(rows))


def _picked(ctx, spec):
    names = xref.match(ctx.d, spec)
    if not names:
        ctx.say('No xref matches "%s".' % spec)
    return names


def _scale_of(raw):
    if raw is None:
        return [1.0, 1.0, 1.0]
    if isinstance(raw, (int, float)):
        vals = [float(raw)]
    elif isinstance(raw, str):
        vals = [float(t) for t in raw.replace(" ", "").split(",") if t]
    else:
        vals = [float(v) for v in raw]
    if not vals or len(vals) > 3 or any(abs(v) < 1e-12 or not math.isfinite(v) for v in vals):
        raise EditError("Requires a non-zero number.")
    if len(vals) == 1:
        return [vals[0], vals[0], vals[0]]
    if len(vals) == 2:
        return [vals[0], vals[1], abs(vals[0])]
    return vals


def _place(ctx, name, point, scale, rotation):
    ins = Insert(block=name, position=[float(point[0]), float(point[1]), 0.0], scale=_scale_of(scale), rotation=float(rotation))
    return ctx.add(ins)


def _attach_flow(ctx, overlay):
    p = yield ctx.text("Enter path of the file to attach")
    if p.kind != "text":
        return
    path = p.value.strip()
    import os

    resolved, st, why = xref.resolve(path, ctx.doc.path, True)
    if resolved is None:
        ctx.say('Cannot find file "%s".' % path if st == "notfound" else "%s: %s" % (path, why))
        return
    stem = os.path.splitext(os.path.basename(resolved))[0]
    n = yield ctx.text("Enter xref name", stem)
    if n.kind not in ("text", "enter"):
        return
    name = n.value.strip() if n.kind == "text" else stem
    t = yield ctx.keyword("Enter reference type", ["Attach", "Overlay"], "Overlay" if overlay else "Attach")
    if t.kind not in ("keyword", "text"):
        return
    over = str(t.value).lower().startswith("o")
    try:
        res = xref.attach(ctx.doc, path, name, over)
    except EditError as err:
        ctx.say(str(err))
        return
    for line in res["notes"]:
        ctx.say(line)
    pt = yield ctx.point("Specify insertion point", default=[0.0, 0.0, 0.0])
    if pt.kind not in ("point", "text"):
        return
    point = pt.value if pt.kind == "point" else [0.0, 0.0]
    while True:
        s = yield ctx.text("Specify scale factor (number or X,Y)", "1")
        if s.kind not in ("text", "enter"):
            return
        try:
            scale = _scale_of(s.value if s.kind == "text" else 1.0)
            break
        except (EditError, ValueError) as err:
            ctx.say(str(err) if isinstance(err, EditError) else "Requires a number.")
    a = yield ctx.angle("Specify rotation angle", default=0.0)
    if a.kind not in ("number", "text"):
        return
    rot = a.value if a.kind == "number" else 0.0
    _place(ctx, res["name"], point, scale, rot)
    ctx.say('Xref "%s" %s.' % (res["name"], "reused" if res["reused"] else "attached"))


@command("xattach", aliases=("xa",), group="block", label="Attach External Reference", description="Attach another drawing as an external reference.", menu="Insert > DWG Reference...")
def xattach(ctx):
    yield from _attach_flow(ctx, False)


@executes("xattach")
def xattach_exec(ctx, args):
    path = str(args.get("path", "")).strip()
    if not path:
        raise CommandError("Give the path of the file to attach.")
    over = bool(args.get("overlay")) or str(args.get("type", "")).lower().startswith("o")
    try:
        res = xref.attach(ctx.doc, path, str(args.get("name", "")).strip(), over)
        for line in res["notes"]:
            ctx.say(line)
        h = 0
        if args.get("place", True):
            h = _place(ctx, res["name"], args.get("point", [0.0, 0.0]), args.get("scale"), math.radians(float(args.get("rotation", 0.0))))
    except (EditError, ValueError) as err:
        raise CommandError(str(err))
    return {**res, "insert": h}


def _bind_flow(ctx, names, mode):
    for nm in names:
        try:
            res = xref.bind(ctx.doc, nm, mode)
        except EditError as err:
            ctx.say(str(err))
            continue
        ctx.say('Xref "%s" bound (%d symbol(s)).' % (res["name"], res["symbols"]))


@command("-xref", aliases=("-xr",), group="block", label="External Reference Options", description="Command-line xref manager: list, bind, detach, path, unload, reload, overlay, attach.", menu="")
def xref_typed(ctx):
    r = yield ctx.keyword("Enter an option", XREF_OPTS, "Attach")
    if r.kind not in ("keyword", "text"):
        return
    k = str(r.value)
    kl = k.lower()
    if kl == "?":
        n = yield ctx.text("Enter xref(s) to list", "*")
        spec = n.value if n.kind == "text" else "*"
        names = _picked(ctx, spec)
        _table(ctx, [x for x in xref.listing(ctx.d) if x["name"] in names and not x["nested"]])
        return
    if kl in ("attach", "overlay"):
        yield from _attach_flow(ctx, kl == "overlay")
        return
    n = yield ctx.text("Enter xref(s) to %s" % kl, "*")
    if n.kind not in ("text", "enter"):
        return
    names = _picked(ctx, n.value if n.kind == "text" else "*")
    if not names:
        return
    if kl == "bind":
        t = yield ctx.keyword("Enter bind type", ["Bind", "Insert"], "Bind")
        if t.kind not in ("keyword", "text"):
            return
        _bind_flow(ctx, names, str(t.value).lower().startswith("i"))
        return
    for nm in names:
        try:
            if kl == "detach":
                xref.detach(ctx.doc, nm)
                ctx.say('Xref "%s" detached.' % nm)
            elif kl == "unload":
                xref.unload(ctx.doc, nm)
                ctx.say('Xref "%s" unloaded.' % nm)
            elif kl == "reload":
                res = xref.reload(ctx.doc, nm)
                for line in res["notes"]:
                    ctx.say(line)
            elif kl == "path":
                p = yield ctx.text('Enter new path for "%s"' % nm)
                if p.kind != "text":
                    return
                res = xref.set_path(ctx.doc, nm, p.value)
                for line in res["notes"]:
                    ctx.say(line)
        except EditError as err:
            ctx.say(str(err))


@executes("-xref")
def xref_exec(ctx, args):
    action = str(args.get("action", "list")).lower()
    d = ctx.d
    try:
        if action == "list":
            rows = xref.listing(d)
            names = xref.match(d, args.get("name", "*"))
            rows = [x for x in rows if x["name"] in names or x["nested"]]
            if args.get("say"):
                _table(ctx, [x for x in rows if not x["nested"]])
            return {"xrefs": rows}
        if action in ("attach", "overlay"):
            return xattach_exec(ctx, {**args, "overlay": action == "overlay"})
        if action == "reload_all":
            out = []
            for nm in xref.match(d, "*"):
                out.append(xref.reload(ctx.doc, nm))
            for res in out:
                for line in res["notes"]:
                    ctx.say(line)
            return {"reloaded": [o["name"] for o in out], "results": out}
        names = xref.match(d, args.get("name", ""))
        if not names:
            raise EditError('No xref matches "%s".' % args.get("name", ""))
        out = []
        for nm in names:
            if action == "detach":
                out.append(xref.detach(ctx.doc, nm))
            elif action == "unload":
                out.append(xref.unload(ctx.doc, nm))
            elif action == "reload":
                res = xref.reload(ctx.doc, nm)
                for line in res["notes"]:
                    ctx.say(line)
                out.append(res)
            elif action == "bind":
                out.append(xref.bind(ctx.doc, nm, str(args.get("mode", "bind")).lower().startswith("i")))
            elif action == "path":
                res = xref.set_path(ctx.doc, nm, str(args.get("path", "")))
                for line in res["notes"]:
                    ctx.say(line)
                out.append(res)
            elif action == "type":
                out.append(xref.set_type(ctx.doc, nm, bool(args.get("overlay")) or str(args.get("type", "")).lower().startswith("o")))
            else:
                raise EditError("Action is list, attach, overlay, detach, unload, reload, reload_all, bind, path or type.")
        return {"results": out}
    except EditError as err:
        raise CommandError(str(err))


@command("xref", aliases=("xr", "externalreferences"), group="block", label="External References", description="List external references with their status; the palette shows the same list.", menu="Window > Reference Manager", undoable=False)
def xref_palette(ctx):
    rows = [x for x in xref.listing(ctx.d) if not x["nested"]]
    if not rows:
        ctx.say("No external references are attached.")
    else:
        _table(ctx, rows)
    yield from ()


@executes("xref")
def xref_palette_exec(ctx, args):
    return {"xrefs": xref.listing(ctx.d)}


@command("xbind", aliases=("xb", "-xbind", "-xb"), group="block", label="Bind Xref Symbols", description="Bind dependent symbols of an external reference into the drawing.", menu="")
def xbind(ctx):
    t = yield ctx.keyword("Enter symbol type to bind", ["Block", "Dimstyle", "LAyer", "LType", "Style"])
    if t.kind != "keyword":
        return
    n = yield ctx.text("Enter dependent %s name(s)" % t.value.lower())
    if n.kind != "text":
        return
    try:
        res = xref.xbind(ctx.doc, t.value, n.value)
    except EditError as err:
        ctx.say(str(err))
        return
    ctx.say("%d symbol(s) bound." % res["bound"])


@executes("xbind")
def xbind_exec(ctx, args):
    try:
        res = xref.xbind(ctx.doc, str(args.get("type", "")), str(args.get("names", args.get("name", ""))))
    except EditError as err:
        raise CommandError(str(err))
    ctx.say("%d symbol(s) bound." % res["bound"])
    return res


def _open(ctx, name):
    rec = xref.find(ctx.d, name)
    path = rec["xref"].get("resolved") or ""
    if not path:
        raise EditError('The file of xref "%s" was not found.' % rec["name"])
    doc = service.open(path)
    ctx.say('Opened "%s".' % path)
    return {"id": doc.id, "path": path}


@command("xopen", group="block", label="Open Xref", description="Open the drawing an external reference points at.", menu="Tools > Open Xref", undoable=False)
def xopen(ctx):
    n = yield ctx.text("Enter xref name")
    if n.kind != "text":
        return
    try:
        _open(ctx, n.value.strip())
    except EditError as err:
        ctx.say(str(err))


@executes("xopen")
def xopen_exec(ctx, args):
    try:
        return _open(ctx, str(args.get("name", "")).strip())
    except EditError as err:
        raise CommandError(str(err))


XCLIP_OPTS = ["ON", "OFF", "Delete", "Generate polyline", "New boundary"]


@command("xclip", aliases=("xc",), group="block", label="Clip Reference", description="Clip an external reference or block to a boundary.", menu="Modify > Clip > Xref")
def xclip_cmd(ctx):
    s = yield ctx.entity("Select reference to clip")
    if s.kind != "entity":
        return
    handle = int(s.value["handle"])
    o = yield ctx.keyword("Enter clipping option", XCLIP_OPTS, "New boundary")
    if o.kind not in ("keyword", "text"):
        return
    k = str(o.value).lower()
    try:
        if k == "on":
            xclip.set_on(ctx.doc, handle, True)
        elif k == "off":
            xclip.set_on(ctx.doc, handle, False)
        elif k == "delete":
            xclip.delete(ctx.doc, handle)
        elif k.startswith("g"):
            xclip.generate(ctx, handle)
        else:
            m = yield ctx.keyword("Specify clipping boundary", ["Select polyline", "Polygonal", "Rectangular", "Invert clip"], "Rectangular")
            if m.kind not in ("keyword", "text"):
                return
            mk = str(m.value).lower()
            invert = mk.startswith("i")
            if invert:
                m = yield ctx.keyword("Specify clipping boundary", ["Select polyline", "Polygonal", "Rectangular"], "Rectangular")
                mk = str(m.value).lower()
            if mk.startswith("s"):
                p = yield ctx.entity("Select a closed polyline")
                if p.kind != "entity":
                    return
                pts = xclip.polygon_of(ctx.d.get(int(p.value["handle"])))
            elif mk.startswith("r"):
                a = yield ctx.point("Specify first corner")
                if a.kind != "point":
                    return
                b = yield ctx.point("Specify opposite corner", base=a.value, rect=True)
                if b.kind != "point":
                    return
                pts = xclip.rect_points(a.value, b.value)
            else:
                pts = []
                while True:
                    p = yield ctx.point("Specify polygon point" if len(pts) < 3 else "Specify next polygon point or press Enter to close", base=pts[-1] if pts else None)
                    if p.kind == "point":
                        pts.append([p.value[0], p.value[1]])
                        continue
                    break
            xclip.set_new(ctx.doc, handle, pts, invert)
    except EditError as err:
        ctx.say(str(err))
        return
    ctx.say("Clip boundary updated.")


@executes("xclip")
def xclip_exec(ctx, args):
    h = args.get("handle")
    if h is None:
        raise CommandError("Give the handle of the reference.")
    action = str(args.get("action", "new")).lower()
    try:
        if action in ("on", "off"):
            return xclip.set_on(ctx.doc, h, action == "on")
        if action == "delete":
            return xclip.delete(ctx.doc, h)
        if action.startswith("gen"):
            return xclip.generate(ctx, h)
        if args.get("polyline") is not None:
            pts = xclip.polygon_of(ctx.d.get(int(args["polyline"])))
        elif args.get("rect"):
            pts = xclip.rect_points(args["rect"][0], args["rect"][1])
        else:
            pts = args.get("points", [])
        return xclip.set_new(ctx.doc, h, pts, bool(args.get("invert")))
    except EditError as err:
        raise CommandError(str(err))
