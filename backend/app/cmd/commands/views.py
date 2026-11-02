from app.cmd.context import CommandError
from app.cmd.registry import COMMANDS, command, executes
from app.doc import geom
from app.doc import layerops as LO
from app.doc import viewops as VO

VIEW_OPTS = ["?", "Delete", "Orthographic", "Restore", "Save", "sEttings", "Window"]
VPORT_OPTS = ["Save", "Restore", "Delete", "Join", "SIngle", "?", "1", "2", "3", "4"]
ARRANGE_3 = ["Horizontal", "Vertical", "Above", "Below", "Left", "Right"]


def guard(fn):
    def run(ctx, args):
        try:
            return fn(ctx, args)
        except (VO.ViewError, LO.LayerError) as err:
            if ctx.doc.in_tx():
                ctx.doc.rollback()
            raise CommandError(str(err))

    run.__name__ = fn.__name__
    return run


def list_views(ctx, spec: str) -> None:
    pats = [s.strip() for s in spec.split(",") if s.strip()] or ["*"]
    rows = [r for r in VO.list_views(ctx.d) if any(LO.name_matches(p, r["name"], False) for p in pats)]
    if not rows:
        ctx.say("No matching views found.")
        return
    ctx.say("View name                 Space")
    for r in rows:
        ctx.say("%-25s %s" % (r["name"], r["space"]))


def say_restore(ctx, res) -> None:
    for note in res["notes"]:
        ctx.say(note)
    ctx.say('View "%s" restored.' % res["name"])


def say_save(ctx, rec, replaced) -> None:
    ctx.say('View "%s" %s.' % (rec["name"], "replaced" if replaced else "saved"))


@command("view", aliases=("v",), group="view", label="Named Views", description="Save, restore, list and delete named views.", menu="View > Named Views...")
def view_cmd(ctx):
    d, doc = ctx.d, ctx.doc
    while True:
        r = yield ctx.keyword("Enter an option", VIEW_OPTS)
        if r.kind != "keyword":
            return
        k = r.value
        try:
            if k == "?":
                n = yield ctx.text("Enter view name(s) to list", "*")
                if n.kind == "text":
                    list_views(ctx, n.value)
            elif k == "Delete":
                n = yield ctx.text("Enter view name(s) to delete")
                if n.kind != "text":
                    continue
                gone = VO.delete_views(d, n.value)
                ctx.say("%d view(s) deleted." % len(gone) if gone else "No matching views found.")
            elif k == "Orthographic":
                ctx.say("Orthographic views are not available.")
            elif k == "Restore":
                n = yield ctx.text("Enter view name to restore")
                if n.kind == "text":
                    say_restore(ctx, VO.restore_view(doc, n.value))
            elif k == "Save":
                n = yield ctx.text("Enter view name to save")
                if n.kind == "text":
                    rec, replaced = VO.save_view(doc, n.value)
                    say_save(ctx, rec, replaced)
            elif k == "sEttings":
                cur = "Yes" if VO.view_session(doc)["snapshot"] else "No"
                y = yield ctx.keyword("Save a layer snapshot with each view", ["Yes", "No"], cur)
                if y.kind == "keyword":
                    VO.view_session(doc)["snapshot"] = y.value == "Yes"
            elif k == "Window":
                a = yield ctx.point("Specify first corner")
                if a.kind != "point":
                    continue
                b = yield ctx.point("Specify opposite corner", base=a.value, rect=True)
                if b.kind != "point":
                    continue
                n = yield ctx.text("Enter view name to save")
                if n.kind == "text":
                    rec, replaced = VO.save_view(doc, n.value, (a.value, b.value))
                    say_save(ctx, rec, replaced)
        except (VO.ViewError, LO.LayerError) as err:
            ctx.say(str(err))
        LO.prune_noop(doc)


@command("-view", aliases=("-v",), group="view", label="Named Views (command line)", description="Command line named view options.", menu="")
def view_typed(ctx):
    yield from view_cmd(ctx)


@executes("view", "-view")
@guard
def view_exec(ctx, args):
    d, doc = ctx.d, ctx.doc
    action = str(args.get("action", "list")).lower()
    name = args.get("name", "")
    if action == "list":
        return {"views": VO.list_views(d)}
    if action == "save":
        rec, replaced = VO.save_view(doc, name, None, args.get("snapshot"))
        return {"view": rec["name"], "replaced": replaced}
    if action == "window":
        rec, replaced = VO.save_view(doc, name, (geom.as_pt(args["p1"]), geom.as_pt(args["p2"])), args.get("snapshot"))
        return {"view": rec["name"], "replaced": replaced}
    if action == "restore":
        res = VO.restore_view(doc, name)
        LO.prune_noop(doc)
        return res
    if action == "delete":
        gone = VO.delete_views(d, args.get("names") or name)
        return {"deleted": gone}
    if action == "settings":
        if "snapshot" in args:
            VO.view_session(doc)["snapshot"] = bool(args["snapshot"])
        return {"snapshot": VO.view_session(doc)["snapshot"]}
    raise VO.ViewError("Unknown view action %s." % action)


@command("pan", aliases=("p",), group="view", label="Pan", description="Pan the view by a displacement or in a direction.", menu="View > Pan", transparent=True, undoable=False, repeatable=False)
def pan(ctx):
    p = ctx.point("Specify base point or displacement", ["Left", "Right", "Up", "Down"], default_text="real time")
    r = yield p
    doc = ctx.doc
    try:
        if r.kind == "enter":
            doc.request_view("realtime-pan")
            ctx.say("Realtime pan is performed on the canvas.")
        elif r.kind == "keyword":
            VO.pan_step(doc, r.value)
        elif r.kind == "point":
            s = yield ctx.point("Specify second point", base=r.value, default_text="use first point as displacement")
            if s.kind == "point":
                VO.pan_by(doc, s.value[0] - r.value[0], s.value[1] - r.value[1])
            elif s.kind == "enter":
                VO.pan_by(doc, r.value[0], r.value[1])
    except VO.ViewError as err:
        ctx.say(str(err))


@executes("pan")
@guard
def pan_exec(ctx, args):
    doc = ctx.doc
    if args.get("direction"):
        if str(args["direction"]).lower() not in ("left", "right", "up", "down"):
            raise VO.ViewError("Choose left, right, up or down.")
        VO.pan_step(doc, str(args["direction"]))
    elif "p1" in args and "p2" in args:
        a, b = geom.as_pt(args["p1"]), geom.as_pt(args["p2"])
        VO.pan_by(doc, b[0] - a[0], b[1] - a[1])
    elif "dx" in args or "dy" in args:
        VO.pan_by(doc, float(args.get("dx", 0.0)), float(args.get("dy", 0.0)))
    else:
        raise VO.ViewError("Give a direction, p1 and p2, or dx and dy.")
    return {"view": dict(doc.view)}


@command("redraw", aliases=("r",), group="view", label="Redraw", description="Refresh the display.", menu="View > Redraw", transparent=True, undoable=False, repeatable=False)
def redraw(ctx):
    ctx.doc.bump("redraw")
    yield from ()


@executes("redraw")
def redraw_exec(ctx, args):
    return {"rev": ctx.doc.bump("redraw")}


def regen_run(ctx, everywhere):
    n = VO.regen(ctx.doc, everywhere)
    ctx.say("Regenerating model." if ctx.doc.current_space == "model" else "Regenerating layout.")
    if n:
        ctx.say("%d table(s) recalculated." % n)


@command("regen", aliases=("re",), group="view", label="Regen", description="Regenerate the display and recalculate table formulas.", menu="View > Regen", transparent=True)
def regen(ctx):
    regen_run(ctx, False)
    yield from ()


@command("regenall", aliases=("rea",), group="view", label="Regen All", description="Regenerate the display of every space and recalculate every table.", menu="View > Regen All", transparent=True)
def regenall(ctx):
    regen_run(ctx, True)
    yield from ()


@executes("regen")
def regen_exec(ctx, args):
    return {"tables": VO.regen(ctx.doc, False)}


@executes("regenall")
def regenall_exec(ctx, args):
    return {"tables": VO.regen(ctx.doc, True)}


def tile_lines(ctx) -> None:
    info = VO.describe_tiles(ctx.doc)
    ctx.say("Current viewport: %d" % info["current"])
    for t in info["tiles"]:
        ctx.say("%s%d: (%.4f, %.4f) to (%.4f, %.4f)" % ("*" if t["current"] else " ", t["index"], t["lowerLeft"][0], t["lowerLeft"][1], t["upperRight"][0], t["upperRight"][1]))
    if info["configs"]:
        ctx.say("Saved configurations: %s" % ", ".join(info["configs"]))
    else:
        ctx.say("No saved viewport configurations.")


def vports_loop(ctx):
    d, doc = ctx.d, ctx.doc
    r = yield ctx.keyword("Enter an option", VPORT_OPTS, "3")
    if r.kind == "enter":
        return
    if r.kind != "keyword":
        return
    k = r.value
    try:
        if k == "?":
            tile_lines(ctx)
        elif k == "Save":
            n = yield ctx.text("Enter name for new viewport configuration")
            if n.kind == "text":
                rec, replaced = VO.save_config(doc, n.value)
                ctx.say('Viewport configuration "%s" %s.' % (rec["name"], "replaced" if replaced else "saved"))
        elif k == "Restore":
            n = yield ctx.text("Enter name of viewport configuration to restore")
            if n.kind == "text":
                VO.restore_config(doc, n.value)
        elif k == "Delete":
            n = yield ctx.text("Enter name(s) of viewport configurations to delete")
            if n.kind == "text":
                gone = VO.delete_configs(d, n.value)
                ctx.say("%d viewport configuration(s) deleted." % len(gone) if gone else "No matching viewport configurations found.")
        elif k == "Join":
            cur = VO.current_index(doc) + 1
            a = yield ctx.number("Select dominant viewport <%d>" % cur, default=cur, integer=True, minimum=1)
            if a.kind not in ("number", "enter"):
                return
            dom = int(a.value) if a.kind == "number" else cur
            b = yield ctx.number("Select viewport to join", integer=True, minimum=1)
            if b.kind == "number":
                VO.join(doc, dom, int(b.value))
        elif k in ("SIngle", "1"):
            VO.single(doc)
        elif k in ("2", "3", "4"):
            n = int(k)
            if n == 2:
                o = yield ctx.keyword("Enter configuration option", ["Horizontal", "Vertical"], "Vertical")
            else:
                o = yield ctx.keyword("Enter configuration option", ARRANGE_3, "Right")
            if o.kind == "keyword":
                VO.arrange(doc, n, o.value)
    except (VO.ViewError, LO.LayerError) as err:
        ctx.say(str(err))


def vports_entry(ctx):
    if ctx.doc.current_space != "model":
        mv = COMMANDS.get("mview")
        if mv is not None:
            yield from mv.fn(ctx)
        else:
            ctx.say("Layout viewports are created with MVIEW.")
        return
    yield from vports_loop(ctx)


@command("vports", group="view", label="Viewports", description="Tiled model viewports; layout viewports when a layout is current.", menu="View > Viewports")
def vports(ctx):
    yield from vports_entry(ctx)


@command("-vports", group="view", label="Viewports (command line)", description="Command line tiled viewport options.", menu="")
def vports_typed(ctx):
    yield from vports_entry(ctx)


@executes("vports", "-vports")
@guard
def vports_exec(ctx, args):
    d, doc = ctx.d, ctx.doc
    opt = str(args.get("option", args.get("action", "list"))).lower()
    if doc.current_space != "model" and opt in ("1", "2", "3", "4", "restore"):
        from app.cmd.commands.viewports import mview_exec

        if opt == "restore":
            return mview_exec(ctx, {"restore": args.get("name", ""), "corners": args.get("corners")})
        return mview_exec(ctx, {"count": int(opt), "arrangement": str(args.get("orient", "")), "corners": args.get("corners")})
    if opt in ("list", "?"):
        return VO.describe_tiles(doc)
    if opt in ("1", "single"):
        return VO.single(doc)
    if opt in ("2", "3", "4"):
        return VO.arrange(doc, int(opt), str(args.get("orient", "")))
    if opt == "join":
        return VO.join(doc, int(args.get("dominant", VO.current_index(doc) + 1)), int(args.get("other", 0)))
    if opt == "save":
        rec, replaced = VO.save_config(doc, args.get("name", ""))
        return {"name": rec["name"], "replaced": replaced}
    if opt == "restore":
        return VO.restore_config(doc, args.get("name", ""))
    if opt == "delete":
        return {"deleted": VO.delete_configs(d, args.get("names") or args.get("name", ""))}
    if opt == "current":
        return VO.set_current_tile(doc, int(args.get("tile", 0)))
    raise VO.ViewError("Unknown viewport option %s." % opt)
