import fnmatch
import os

from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.doc import container, layouts, papers, viewports, vpmax
from app.doc.model import Drawing, SPACE_MODEL, layout_space

LAYOUT_OPTS = ["Copy", "Delete", "New", "Template", "Rename", "SAveas", "Set", "?"]
SETUP_OPTS = ["Device", "Paper", "Orientation", "Margins", "Area", "Scale", "Fit", "Center", "STyle", "Lineweights", "Display", "Transparency", "Offset", "eXit"]
TEMPLATE_EXT = ".fcad"


def add_viewport(ctx, space: str, rect, clip=None, fit: bool = True):
    vp = viewports.make(ctx.doc, space, rect[0], rect[1], rect[2], rect[3], clip=clip, fit=fit)
    ctx.stamp(vp)
    vp.annotation_scales = []
    ctx.d.add_entity(vp, space)
    return vp


def printable_rect(d, name: str) -> list:
    return layouts.printable_units(d, layouts.page_setup(d, name))


def new_layout(ctx, name: str = "", setup=None) -> dict:
    try:
        rec = layouts.create(ctx.d, name, setup)
        add_viewport(ctx, layout_space(rec["name"]), printable_rect(ctx.d, rec["name"]))
    except (layouts.LayoutError, viewports.ViewportError, ValueError) as err:
        raise CommandError(str(err))
    return rec


def current_layout_name(ctx) -> str:
    return "" if ctx.doc.tab == SPACE_MODEL else layouts.tab_label(ctx.doc)


def match(ctx, text: str) -> list:
    t = str(text).strip()
    rec = layouts.find(ctx.d, t)
    if rec is not None:
        return [rec["name"]]
    if any(c in t for c in "*?"):
        return [n for n in layouts.names(ctx.d) if fnmatch.fnmatchcase(n.casefold(), t.casefold())]
    return []


def save_template(ctx, name: str, path: str) -> str:
    rec = layouts.find(ctx.d, name)
    if rec is None:
        raise CommandError('Layout "%s" not found.' % name)
    target = str(path).strip()
    if not target:
        raise CommandError("A file name is required.")
    ext = os.path.splitext(target)[1].lower()
    if ext == "":
        target += TEMPLATE_EXT
    elif ext != TEMPLATE_EXT:
        raise CommandError("A layout template is saved as a %s file." % TEMPLATE_EXT)
    clone = Drawing.from_dict(ctx.d.to_dict())
    keep = layout_space(rec["name"])
    for space in list(clone.spaces):
        if space == keep or space.startswith("block:"):
            continue
        for h in list(clone.spaces[space]):
            clone.ents.pop(h, None)
        if space == SPACE_MODEL:
            clone.spaces[space] = []
        else:
            clone.spaces.pop(space, None)
    for other in list(clone.tables["layouts"].values()):
        if other["name"].casefold() != rec["name"].casefold():
            clone.tables["layouts"].drop(other["name"])
    for r in clone.tables["layouts"].values():
        r["tab_order"] = 1
    try:
        return container.save(target, clone, rec["name"], ctx.doc.created, False, "drawing")
    except container.ContainerError as err:
        raise CommandError(err.message)


def do(ctx, action: str, args: dict) -> dict:
    d = ctx.d
    a = action.lower()
    if a == "new":
        rec = new_layout(ctx, str(args.get("name", "")), args.get("pagesetup"))
        ctx.say('Layout "%s" created.' % rec["name"])
        return {"name": rec["name"]}
    if a == "copy":
        src = str(args.get("name") or current_layout_name(ctx))
        try:
            rec = layouts.copy_layout(d, src, str(args.get("to", "")))
        except layouts.LayoutError as err:
            raise CommandError(str(err))
        ctx.say('Layout "%s" copied to "%s".' % (src, rec["name"]))
        return {"name": rec["name"]}
    if a == "delete":
        hits = match(ctx, str(args.get("name", "")))
        if not hits:
            raise CommandError('No layout matches "%s".' % args.get("name", ""))
        gone = []
        for n in hits:
            try:
                gone.append(layouts.delete(d, n))
            except layouts.LayoutError as err:
                ctx.say(str(err))
                break
        if not gone:
            raise CommandError("The last layout cannot be deleted.")
        for n in gone:
            ctx.say('Layout "%s" deleted.' % n)
        return {"deleted": gone}
    if a == "rename":
        try:
            rec = layouts.rename(d, str(args.get("name", "")), str(args.get("to", "")))
        except layouts.LayoutError as err:
            raise CommandError(str(err))
        ctx.say('Layout renamed to "%s".' % rec["name"])
        if ctx.doc.tab != SPACE_MODEL and ctx.doc.tab not in d.spaces and str(args.get("name", "")).casefold() == ctx.doc.tab.split(":", 1)[1].casefold():
            ctx.doc.tab = layout_space(rec["name"])
        return {"name": rec["name"]}
    if a == "set":
        try:
            layouts.switch(ctx.doc, str(args.get("name", "Model")))
        except layouts.LayoutError as err:
            raise CommandError(str(err))
        label = layouts.tab_label(ctx.doc)
        ctx.say("Active Layout: %s" % label)
        return {"name": label}
    if a == "saveas":
        dest = save_template(ctx, str(args.get("name") or current_layout_name(ctx)), str(args.get("path", "")))
        ctx.say("Layout saved to %s." % dest)
        return {"path": dest}
    if a == "move":
        try:
            order = layouts.move(d, str(args.get("name", "")), int(args.get("index", 0)))
        except (layouts.LayoutError, TypeError, ValueError) as err:
            raise CommandError(str(err))
        return {"order": order}
    if a in ("list", "?"):
        rows = layouts.listing(ctx.doc)
        for r in rows:
            ctx.say("Layout: %s" % r["name"])
        return {"layouts": rows}
    if a == "template":
        raise CommandError("LAYOUT Template is not available yet.")
    raise CommandError("Unknown layout action %s." % action)


@command("layout", aliases=("lo", "-layout"), group="layout", label="Layout", description="New, copy, delete, rename, save and switch layouts.", menu="Insert > Layout", repeatable=True)
def layout(ctx):
    while True:
        cur = layouts.tab_label(ctx.doc) if ctx.doc.tab != SPACE_MODEL else "Model"
        r = yield ctx.keyword("Enter layout option", LAYOUT_OPTS, "Set")
        if r.kind != "keyword":
            return
        k = r.value
        if k == "New":
            n = yield ctx.text("Enter name of new layout", layouts.first_free(ctx.d))
            if n.kind != "text":
                return
            try:
                do(ctx, "new", {"name": str(n.value)})
            except CommandError as err:
                ctx.say(str(err))
                continue
            return
        if k == "Copy":
            n = yield ctx.text("Enter name of layout to copy", current_layout_name(ctx) or layouts.names(ctx.d)[0])
            if n.kind != "text":
                return
            src = layouts.find(ctx.d, str(n.value))
            if src is None:
                ctx.say('No layout matches "%s".' % n.value)
                continue
            m = yield ctx.text("Enter layout name for copy", layouts.copy_name(ctx.d, src["name"]))
            if m.kind != "text":
                return
            try:
                do(ctx, "copy", {"name": src["name"], "to": str(m.value)})
            except CommandError as err:
                ctx.say(str(err))
                continue
            return
        if k == "Delete":
            n = yield ctx.text("Enter name of layout to delete", current_layout_name(ctx) or None)
            if n.kind != "text":
                return
            try:
                do(ctx, "delete", {"name": str(n.value)})
            except CommandError as err:
                ctx.say(str(err))
                continue
            return
        if k == "Rename":
            o = yield ctx.text("Enter old layout name", current_layout_name(ctx) or None)
            if o.kind != "text":
                return
            if layouts.find(ctx.d, str(o.value)) is None:
                ctx.say('No layout matches "%s".' % o.value)
                continue
            n = yield ctx.text("Enter new layout name")
            if n.kind != "text":
                return
            try:
                do(ctx, "rename", {"name": str(o.value), "to": str(n.value)})
            except CommandError as err:
                ctx.say(str(err))
                continue
            return
        if k == "SAveas":
            o = yield ctx.text("Enter name of layout to save as a template", current_layout_name(ctx) or layouts.names(ctx.d)[0])
            if o.kind != "text":
                return
            if layouts.find(ctx.d, str(o.value)) is None:
                ctx.say('No layout matches "%s".' % o.value)
                continue
            f = yield ctx.text("Enter template file name")
            if f.kind != "text":
                return
            try:
                do(ctx, "saveas", {"name": str(o.value), "path": str(f.value)})
            except CommandError as err:
                ctx.say(str(err))
                continue
            return
        if k == "Set":
            n = yield ctx.text("Enter layout to make current", cur)
            if n.kind != "text":
                return
            try:
                do(ctx, "set", {"name": str(n.value)})
            except CommandError as err:
                ctx.say(str(err))
                continue
            return
        if k == "Template":
            ctx.say("LAYOUT Template is not available yet.")
            continue
        if k == "?":
            n = yield ctx.text("Enter layout name(s) to list", "*")
            if n.kind != "text":
                return
            hits = match(ctx, str(n.value)) if str(n.value).strip() not in ("*", "") else layouts.names(ctx.d)
            if not hits:
                ctx.say('No layout matches "%s".' % n.value)
                continue
            for h in hits:
                ctx.say("Layout: %s" % h)
            return


@executes("layout")
def layout_exec(ctx, args):
    return do(ctx, str(args.get("action", "list")), args)


def _variant(action: str, label: str, description: str):
    @command("layout." + action, group="layout", label=label, description=description, menu="", repeatable=False)
    def run(ctx):
        ctx.say("Use the LAYOUT command or pass the arguments programmatically.")
        yield from ()

    @executes("layout." + action)
    def run_exec(ctx, args):
        return do(ctx, action, args)

    return run


for _a, _l, _d in (("new", "New Layout", "Create a layout."), ("copy", "Copy Layout", "Copy a layout."), ("delete", "Delete Layout", "Delete a layout."), ("rename", "Rename Layout", "Rename a layout."), ("saveas", "Save Layout as Template", "Save a layout as a template."), ("set", "Switch Layout", "Switch the current tab."), ("list", "List Layouts", "List the layouts."), ("move", "Move Layout", "Move a layout tab.")):
    _variant(_a, _l, _d)


def report(ctx, name: str) -> dict:
    ps = layouts.page_setup(ctx.d, name)
    w, h = layouts.sheet_size(ps)
    ctx.say("%s: %s, %.2f x %.2f mm, %s, margins %s, area %s, scale %s%s, plot style table %s" % (name, ps["paper"], w, h, "landscape" if ps["landscape"] else "portrait", "/".join("%g" % m for m in ps["margins"]), ps["plot_area"], ps["scale_text"], " (fit)" if ps["fit"] else "", ps["style_table"] or "none"))
    return ps


def setup_do(ctx, name: str, changes: dict) -> dict:
    try:
        if changes:
            layouts.set_page_setup(ctx.d, name, changes)
    except layouts.LayoutError as err:
        raise CommandError(str(err))
    return report(ctx, layouts.find(ctx.d, name)["name"])


@command("pagesetup", group="layout", label="Page Setup", description="Report or change the page setup of layouts.", menu="File > Page Setup Manager...")
def pagesetup(ctx):
    for n in layouts.names(ctx.d):
        report(ctx, n)
    n = yield ctx.text("Enter layout name to change", current_layout_name(ctx) or None)
    if n.kind != "text":
        return
    rec = layouts.find(ctx.d, str(n.value))
    if rec is None:
        ctx.say('No layout matches "%s".' % n.value)
        return
    name = rec["name"]
    while True:
        o = yield ctx.keyword("Enter a setting to change", SETUP_OPTS, "eXit")
        if o.kind != "keyword" or o.value == "eXit":
            return
        k = o.value
        change = None
        if k == "Device":
            v = yield ctx.text("Enter plotter name or None", layouts.page_setup(ctx.d, name)["device"])
            change = {"device": v.value} if v.kind == "text" else None
        elif k == "Paper":
            v = yield ctx.text("Enter paper name or width,height in millimetres", layouts.page_setup(ctx.d, name)["paper"])
            if v.kind == "text":
                rec2 = papers.lookup(str(v.value))
                change = {"paper": str(v.value)} if rec2 is not None else None
                if rec2 is None:
                    ctx.say('Paper "%s" is not known.' % v.value)
        elif k == "Orientation":
            v = yield ctx.keyword("Enter orientation", ["Landscape", "Portrait"], "Landscape" if layouts.page_setup(ctx.d, name)["landscape"] else "Portrait")
            change = {"orientation": v.value} if v.kind == "keyword" else None
        elif k == "Margins":
            v = yield ctx.text("Enter margins left,bottom,right,top in millimetres", ",".join("%g" % m for m in layouts.page_setup(ctx.d, name)["margins"]))
            if v.kind == "text":
                try:
                    change = {"margins": [float(x) for x in str(v.value).replace(" ", "").split(",")]}
                except ValueError:
                    ctx.say("Margins are four numbers: left, bottom, right, top.")
        elif k == "Area":
            v = yield ctx.keyword("Enter plot area", ["Layout", "Extents", "Display", "Window", "Limits"], "Layout")
            change = {"plot_area": v.value} if v.kind == "keyword" else None
        elif k == "Scale":
            v = yield ctx.text("Enter plot scale (paper units to drawing units)", layouts.page_setup(ctx.d, name)["scale_text"])
            change = {"scale": v.value} if v.kind == "text" else None
        elif k in ("Fit", "Center", "Lineweights", "Display", "Transparency"):
            key = {"Fit": "fit", "Center": "center", "Lineweights": "plot_lineweights", "Display": "display_styles", "Transparency": "transparency"}[k]
            v = yield ctx.yesno("%s" % ("Fit to paper" if k == "Fit" else "Center the plot" if k == "Center" else "Plot lineweights" if k == "Lineweights" else "Display plot styles" if k == "Display" else "Plot transparency"), "Yes" if layouts.page_setup(ctx.d, name)[key] else "No")
            change = {key: v.value == "Yes"} if v.kind == "keyword" else None
        elif k == "STyle":
            v = yield ctx.text("Enter plot style table name or None", layouts.page_setup(ctx.d, name)["style_table"] or "None")
            if v.kind == "text":
                change = {"style_table": "" if str(v.value).strip().casefold() == "none" else str(v.value)}
        elif k == "Offset":
            v = yield ctx.text("Enter plot offset x,y in millimetres", ",".join("%g" % x for x in layouts.page_setup(ctx.d, name)["offset"]))
            if v.kind == "text":
                try:
                    change = {"offset": [float(x) for x in str(v.value).replace(" ", "").split(",")]}
                except ValueError:
                    ctx.say("The offset is two numbers in millimetres.")
        if change:
            try:
                setup_do(ctx, name, change)
            except CommandError as err:
                ctx.say(str(err))


@executes("pagesetup")
def pagesetup_exec(ctx, args):
    name = str(args.get("layout") or current_layout_name(ctx) or "")
    if layouts.find(ctx.d, name) is None:
        raise CommandError('Layout "%s" not found.' % name)
    changes = {k: v for k, v in args.items() if k != "layout"}
    return setup_do(ctx, name, changes)


def require_layout(ctx) -> None:
    if ctx.doc.tab == SPACE_MODEL:
        raise CommandError("** Command not allowed in Model Tab **")


def pick_active(ctx, handle=None, point=None):
    d = ctx.d
    space = ctx.doc.tab
    vps = [v for v in viewports.of_space(d, space) if v.on and d.layer_visible(v.layer)]
    if handle is not None:
        for v in vps:
            if v.handle == int(handle):
                return v
        raise CommandError("There are no active model space viewports.")
    if point is not None:
        hit = [v for v in vps if v.contains(point)]
        if hit:
            return hit[-1]
    last = int(getattr(ctx.doc, "last_vp", 0) or 0)
    for v in vps:
        if v.handle == last:
            return v
    if vps:
        return vps[0]
    raise CommandError("There are no active model space viewports.")


def enter_model(ctx, handle=None, point=None) -> dict:
    require_layout(ctx)
    if ctx.doc.vp_max:
        vpmax.minimize(ctx.doc, True)
    vp = pick_active(ctx, handle, point)
    ctx.doc.active_vp = vp.handle
    ctx.doc.last_vp = vp.handle
    layouts.announce(ctx.doc)
    ctx.say("Model space through viewport %d." % vp.vp_id)
    return {"viewport": vp.handle, "id": vp.vp_id}


def leave_model(ctx) -> dict:
    require_layout(ctx)
    if ctx.doc.vp_max:
        vpmax.minimize(ctx.doc, True)
    ctx.doc.active_vp = 0
    layouts.announce(ctx.doc)
    ctx.say("Paper space.")
    return {"viewport": 0}


@command("mspace", aliases=("ms",), group="layout", label="Model Space", description="Work in model space through a layout viewport.", menu="", undoable=False)
def mspace(ctx):
    enter_model(ctx)
    yield from ()


@executes("mspace")
def mspace_exec(ctx, args):
    return enter_model(ctx, args.get("handle"), args.get("point"))


@command("pspace", aliases=("ps",), group="layout", label="Paper Space", description="Return to paper space.", menu="", undoable=False)
def pspace(ctx):
    leave_model(ctx)
    yield from ()


@executes("pspace")
def pspace_exec(ctx, args):
    return leave_model(ctx)


@command("vpmax", group="layout", label="Maximise Viewport", description="Fill the drawing area with the active viewport.", menu="", undoable=False)
def vpmax_cmd(ctx):
    require_layout(ctx)
    vp = ctx.d.ents.get(ctx.doc.active_vp) if ctx.doc.active_vp else None
    if vp is None:
        vp = pick_active(ctx)
    try:
        vpmax.maximize(ctx.doc, vp.handle)
    except viewports.ViewportError as err:
        raise CommandError(str(err))
    ctx.say("Viewport %d maximised." % vp.vp_id)
    yield from ()


@executes("vpmax")
def vpmax_exec(ctx, args):
    require_layout(ctx)
    vp = pick_active(ctx, args.get("handle"))
    try:
        return vpmax.maximize(ctx.doc, vp.handle)
    except viewports.ViewportError as err:
        raise CommandError(str(err))


@command("vpmin", group="layout", label="Restore Viewport", description="Return a maximised viewport to the layout.", menu="")
def vpmin_cmd(ctx):
    require_layout(ctx)
    if not vpmax.minimize(ctx.doc, True):
        ctx.say("No viewport is maximised.")
    yield from ()


@executes("vpmin")
def vpmin_exec(ctx, args):
    require_layout(ctx)
    return {"restored": vpmax.minimize(ctx.doc, bool(args.get("keep", True)))}
