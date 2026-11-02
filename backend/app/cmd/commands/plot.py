import base64
import os

from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.doc import layouts as L
from app.doc import papers
from app.doc.model import SPACE_MODEL
from app.output import devices, plot, plotstyle, request as R, styleops


def current_name(ctx) -> str:
    return "Model" if ctx.doc.tab == SPACE_MODEL else L.tab_label(ctx.doc)


def base_name(ctx) -> str:
    stem = os.path.splitext(os.path.basename(ctx.doc.path))[0] if ctx.doc.path else str(ctx.doc.name or "Drawing")
    return stem or "Drawing"


def folder(ctx) -> str:
    return os.path.dirname(os.path.abspath(ctx.doc.path)) if ctx.doc.path else os.path.expanduser("~")


def default_path(ctx, layout: str, ext: str) -> str:
    suffix = "" if ext != "pdf" or layout == "" else "-" + layout
    return os.path.join(folder(ctx), "%s%s.%s" % (base_name(ctx), suffix, ext))


def pack(res: dict) -> dict:
    out = {"output": res["output"], "size": res["size"], "pages": res["pages"], "device": res.get("device", "")}
    if res.get("path"):
        out["path"] = res["path"]
    else:
        out["data_b64"] = base64.b64encode(res["data"]).decode("ascii")
    return out


def run_plot(ctx, raw: dict, output=None, svg=False) -> dict:
    try:
        if svg:
            res = plot.export_svg(ctx.doc, raw)
        else:
            res = plot.run(ctx.doc, raw, output)
    except R.PlotError as err:
        raise CommandError(str(err))
    except OSError as err:
        raise CommandError("Could not write the file: %s" % err)
    except ValueError as err:
        raise CommandError(str(err))
    return res


def echo(ctx, res: dict) -> None:
    names = ", ".join(p["name"] for p in res["pages"])
    if res.get("path"):
        ctx.say("Plotted %s to %s." % (names, res["path"]))
    else:
        ctx.say("Plotted %s: %d bytes." % (names, res["size"]))


def ask_path(ctx, layout: str, ext: str):
    r = yield ctx.text("Enter output file name", default_path(ctx, layout, ext))
    if r.kind == "enter":
        return default_path(ctx, layout, ext)
    if r.kind != "text":
        return None
    return str(r.value).strip()


@command("plot", aliases=("print",), group="output", label="Plot", description="Plot the current layout, or model space, to a file.", menu="File > Print...", undoable=False, repeatable=False)
def plot_cmd(ctx):
    name = current_name(ctx)
    path = yield from ask_path(ctx, name, "pdf")
    if not path:
        return
    res = run_plot(ctx, {"layout": name, "path": path})
    echo(ctx, res)


@executes("plot")
def plot_exec(ctx, args):
    raw = dict(args)
    if "layouts" not in raw and "sheets" not in raw:
        raw.setdefault("layout", current_name(ctx))
    res = run_plot(ctx, raw)
    echo(ctx, res)
    return pack(res)


@command("-plot", group="output", label="Plot (command line)", description="Plot with every setting asked on the command line.", undoable=False, repeatable=False)
def plot_line(ctx):
    d = ctx.d
    cur = current_name(ctx)
    n = yield ctx.text("Enter layout name or ? to list", cur)
    if n.kind == "enter":
        name = cur
    elif n.kind == "text":
        name = str(n.value).strip()
    else:
        return
    if name == "?":
        ctx.say("Model")
        for ln in L.names(d):
            ctx.say(ln)
        return
    if not R.layout_exists(d, name):
        ctx.say('No layout matches "%s".' % name)
        return
    model = name.casefold() == "model"
    raw = {"layout": name}
    dev_in = yield ctx.text("Enter output device name, ? to list, or None", "FormCAD PDF")
    if dev_in.kind == "text":
        if str(dev_in.value).strip() == "?":
            for dv in devices.listing():
                ctx.say("%s (%s)" % (dv["name"], dv["output"]))
            return
        raw["device"] = str(dev_in.value).strip()
    dev = devices.find(raw.get("device", "")) or devices.default_for("pdf")
    if raw.get("device") and devices.find(raw["device"]) is None and raw["device"].casefold() != "none":
        ctx.say('Device "%s" is not known.' % raw["device"])
        return
    p = yield ctx.text("Enter paper name or width,height in millimetres, or ? to list", dev["paper"])
    if p.kind == "text":
        t = str(p.value).strip()
        if t == "?":
            for rec in papers.listing():
                ctx.say(rec["name"])
            return
        rec = papers.lookup(t)
        if rec is None:
            ctx.say('Paper "%s" is not known.' % t)
            return
        raw["paper"] = rec["name"]
    o = yield ctx.keyword("Enter orientation", ["Landscape", "Portrait"], "Landscape")
    if o.kind == "keyword":
        raw["landscape"] = o.value == "Landscape"
    if model:
        a = yield ctx.keyword("Enter plot area", ["Display", "Extents", "Limits", "Window"], "Extents")
        if a.kind == "keyword":
            raw["area"] = a.value.lower()
            if raw["area"] == "window":
                c1 = yield ctx.point("Specify first corner of the plot window")
                if c1.kind != "point":
                    return
                c2 = yield ctx.point("Specify opposite corner", base=c1.value, rect=True)
                if c2.kind != "point":
                    return
                raw["window"] = [c1.value[0], c1.value[1], c2.value[0], c2.value[1]]
        s = yield ctx.text("Enter plot scale (paper units to drawing units) or Fit", "Fit")
    else:
        s = yield ctx.text("Enter plot scale (paper units to drawing units) or Fit", "1:1")
    if s.kind == "text":
        t = str(s.value).strip()
        if t.casefold() == "fit":
            raw["fit"] = True
        else:
            raw["scale"] = t
            raw["fit"] = False
    elif s.kind == "enter" and model:
        raw["fit"] = True
    if model:
        c = yield ctx.yesno("Center the plot", "Yes")
        if c.kind == "keyword":
            raw["center"] = c.value == "Yes"
    st = yield ctx.text("Enter plot style table name or None", "None" if model else (L.page_setup(d, name)["style_table"] or "None"))
    if st.kind == "text":
        raw["style_table"] = "" if str(st.value).strip().casefold() == "none" else str(st.value).strip()
    lw = yield ctx.yesno("Plot with lineweights", "Yes")
    if lw.kind == "keyword":
        raw["lineweights"] = lw.value == "Yes"
    path = yield from ask_path(ctx, name, dev["output"] if not raw.get("device") else (devices.find(raw["device"]) or dev)["output"])
    if not path:
        return
    raw["path"] = path
    res = run_plot(ctx, raw)
    echo(ctx, res)


@executes("-plot")
def plot_line_exec(ctx, args):
    return plot_exec(ctx, args)


@command("exportpdf", group="output", label="Export to PDF", description="Write the current layout, or model space, as a PDF file.", menu="File > Export > PDF...", undoable=False, repeatable=False)
def exportpdf(ctx):
    name = current_name(ctx)
    path = yield from ask_path(ctx, name, "pdf")
    if not path:
        return
    echo(ctx, run_plot(ctx, {"layout": name, "path": path}, "pdf"))


@executes("exportpdf")
def exportpdf_exec(ctx, args):
    raw = dict(args)
    if "layouts" not in raw and "sheets" not in raw:
        raw.setdefault("layout", current_name(ctx))
    res = run_plot(ctx, raw, "pdf")
    echo(ctx, res)
    return pack(res)


@command("pngout", group="output", label="Export PNG", description="Write the current layout, or model space, as a PNG image.", menu="File > Export > PNG...", undoable=False, repeatable=False)
def pngout(ctx):
    name = current_name(ctx)
    path = yield from ask_path(ctx, name, "png")
    if not path:
        return
    dpi = yield ctx.number("Enter resolution in dots per inch", default=300, minimum=50, maximum=2400)
    if dpi.kind not in ("number", "enter"):
        return
    echo(ctx, run_plot(ctx, {"layout": name, "path": path, "dpi": dpi.value if dpi.kind == "number" else 300}, "png"))


@executes("pngout")
def pngout_exec(ctx, args):
    raw = dict(args)
    if "layouts" not in raw and "sheets" not in raw:
        raw.setdefault("layout", current_name(ctx))
    res = run_plot(ctx, raw, "png")
    echo(ctx, res)
    return pack(res)


@command("svgout", group="output", label="Export SVG", description="Write model space or a layout as an SVG file.", menu="File > Export > SVG...", undoable=False, repeatable=False)
def svgout(ctx):
    name = current_name(ctx)
    raw = {"layout": name}
    a = yield ctx.keyword("Enter area to export", ["Extents", "Window"], "Extents")
    if a.kind == "keyword" and a.value == "Window":
        c1 = yield ctx.point("Specify first corner of the export window")
        if c1.kind != "point":
            return
        c2 = yield ctx.point("Specify opposite corner", base=c1.value, rect=True)
        if c2.kind != "point":
            return
        raw["area"] = "window"
        raw["window"] = [c1.value[0], c1.value[1], c2.value[0], c2.value[1]]
    path = yield from ask_path(ctx, name, "svg")
    if not path:
        return
    raw["path"] = path
    echo(ctx, run_plot(ctx, raw, svg=True))


@executes("svgout")
def svgout_exec(ctx, args):
    raw = dict(args)
    raw.setdefault("layout", current_name(ctx))
    res = run_plot(ctx, raw, svg=True)
    echo(ctx, res)
    return pack(res)


@command("publish", group="output", label="Publish", description="Plot several layouts into one PDF file.", menu="File > Publish...", undoable=False, repeatable=False)
def publish(ctx):
    names = ["Model"] + L.names(ctx.d)
    for n in names:
        ctx.say(n)
    r = yield ctx.text("Enter layout names separated by commas, or * for all", ",".join(L.names(ctx.d)) or "Model")
    if r.kind == "enter":
        picked = L.names(ctx.d) or ["Model"]
    elif r.kind == "text":
        t = str(r.value).strip()
        picked = names if t == "*" else [x.strip() for x in t.split(",") if x.strip()]
    else:
        return
    for n in picked:
        if not R.layout_exists(ctx.d, n):
            ctx.say('No layout matches "%s".' % n)
            return
    path = yield from ask_path(ctx, "", "pdf")
    if not path:
        return
    echo(ctx, run_plot(ctx, {"layouts": picked, "path": path}, "pdf"))


@executes("publish")
def publish_exec(ctx, args):
    raw = dict(args)
    if "layouts" not in raw and "sheets" not in raw:
        raw["layouts"] = ["Model"] + L.names(ctx.d) if raw.pop("all", False) else (L.names(ctx.d) or ["Model"])
    res = run_plot(ctx, raw, "pdf")
    echo(ctx, res)
    return pack(res)


@command("preview", aliases=("pre",), group="output", label="Plot Preview", description="Render the plot of the current layout as a preview image.", menu="File > Plot Preview", undoable=False, repeatable=False)
def preview(ctx):
    name = current_name(ctx)
    try:
        res = plot.preview(ctx.doc, {"layout": name})
    except (R.PlotError, ValueError) as err:
        raise CommandError(str(err))
    ctx.say("Preview of %s: %d x %d pixels at %.0f dpi." % (name, res["width"], res["height"], res["dpi"]))


@executes("preview")
def preview_exec(ctx, args):
    raw = dict(args)
    raw.setdefault("layout", current_name(ctx))
    try:
        res = plot.preview(ctx.doc, raw)
    except (R.PlotError, ValueError) as err:
        raise CommandError(str(err))
    return {"width": res["width"], "height": res["height"], "dpi": res["dpi"], "sheet": res["sheet"], "png_b64": base64.b64encode(res["data"]).decode("ascii")}


def report_table(ctx, t):
    ctx.say("%s (%s, %d styles)%s" % (t["name"], "colour-dependent" if t["kind"] == "color" else "named", t["count"], " built in" if t["builtin"] else (" stored in the drawing" if t["stored"] else (" file " + t["file"] if t["file"] else ""))))


@command("stylesmanager", aliases=("stylesmgr",), group="output", label="Plot Style Manager", description="List, create, copy, edit, load and save plot style tables.", menu="File > Plot Style Manager...", repeatable=False)
def stylesmanager(ctx):
    for t in plotstyle.listing(ctx.d):
        report_table(ctx, t)
    while True:
        o = yield ctx.keyword("Enter an option", ["List", "Get", "New", "Copy", "Delete", "Style", "Add", "Remove", "Load", "Save", "Use", "eXit"], "eXit")
        if o.kind != "keyword" or o.value == "eXit":
            return
        k = o.value
        try:
            if k == "List":
                for t in plotstyle.listing(ctx.d):
                    report_table(ctx, t)
            elif k == "Get":
                n = yield ctx.text("Enter plot style table name")
                if n.kind == "text":
                    t = styleops.apply(ctx.doc, "get", {"name": n.value})
                    for st in t["styles"][:40]:
                        ctx.say("%s color=%s gray=%s screen=%d lw=%s" % (st["name"], st["color"], st["grayscale"], st["screening"], st["lineweight"]))
            elif k == "New":
                kd = yield ctx.keyword("Enter table type", ["Colour", "Named"], "Named")
                n = yield ctx.text("Enter name of the new table")
                if kd.kind == "keyword" and n.kind == "text":
                    styleops.apply(ctx.doc, "create", {"kind": "color" if kd.value == "Colour" else "named", "name": n.value})
                    ctx.say("Plot style table %s created." % n.value)
            elif k == "Copy":
                n = yield ctx.text("Enter name of the table to copy")
                m = yield ctx.text("Enter name for the copy")
                if n.kind == "text" and m.kind in ("text", "enter"):
                    styleops.apply(ctx.doc, "copy", {"name": n.value, "to": m.value if m.kind == "text" else ""})
            elif k == "Delete":
                n = yield ctx.text("Enter name of the table to delete")
                if n.kind == "text":
                    styleops.apply(ctx.doc, "delete", {"name": n.value})
            elif k in ("Style", "Add", "Remove"):
                t = yield ctx.text("Enter plot style table name")
                s = yield ctx.text("Enter plot style name")
                if t.kind != "text" or s.kind != "text":
                    continue
                fields = {}
                if k == "Style":
                    for label, key in (("Enter screening 0 to 100", "screening"), ("Enter lineweight in millimetres or None", "lineweight"), ("Enter colour as r,g,b or Object", "color")):
                        v = yield ctx.text(label)
                        if v.kind != "text":
                            continue
                        tv = str(v.value).strip()
                        if key == "screening":
                            fields[key] = float(tv)
                        elif key == "lineweight":
                            fields[key] = None if tv.casefold() == "none" else float(tv)
                        else:
                            fields[key] = None if tv.casefold() == "object" else [int(x) for x in tv.split(",")]
                styleops.apply(ctx.doc, {"Style": "setstyle", "Add": "addstyle", "Remove": "removestyle"}[k], {"table": t.value, "style": s.value, "fields": fields})
            elif k == "Load":
                p = yield ctx.text("Enter plot style file name")
                if p.kind == "text":
                    styleops.apply(ctx.doc, "load", {"path": p.value})
            elif k == "Save":
                n = yield ctx.text("Enter plot style table name")
                if n.kind == "text":
                    r = styleops.apply(ctx.doc, "save", {"name": n.value})
                    ctx.say("Saved to %s." % r["path"])
            elif k == "Use":
                lay = yield ctx.text("Enter layout name", current_name(ctx))
                n = yield ctx.text("Enter plot style table name or None")
                if lay.kind in ("text", "enter") and n.kind == "text":
                    styleops.apply(ctx.doc, "use", {"layout": lay.value if lay.kind == "text" else current_name(ctx), "name": n.value})
        except (plotstyle.StyleError, L.LayoutError, ValueError, OSError) as err:
            ctx.say(str(err))


@executes("stylesmanager")
def stylesmanager_exec(ctx, args):
    a = dict(args)
    action = a.pop("action", "list")
    try:
        return styleops.apply(ctx.doc, action, a)
    except (plotstyle.StyleError, L.LayoutError, OSError, ValueError) as err:
        raise CommandError(str(err))


@command("plotstyle", group="output", label="Plot Style", description="Set the plot style of objects, or the style for new objects.", menu="Format > Plot Style", repeatable=False)
def plotstyle_cmd(ctx):
    cur = str(ctx.d.header.get("CPLOTSTYLE", "ByLayer"))
    s = yield ctx.select("Select objects")
    if s.kind != "selection":
        names = {t["name"] for t in plotstyle.all_tables(ctx.d).values() if t["kind"] == "named"}
        ctx.say("Current plot style is %s." % cur)
        for t in plotstyle.all_tables(ctx.d).values():
            if t["kind"] == "named":
                ctx.say("%s: %s" % (t["name"], ", ".join(t["order"])))
        n = yield ctx.text("Enter plot style name for new objects", cur)
        if n.kind == "text":
            ctx.setvar("CPLOTSTYLE", plot_style_name(ctx, n.value))
        return
    n = yield ctx.text("Enter plot style name, ByLayer or ByBlock", "ByLayer")
    name = "ByLayer" if n.kind == "enter" else plot_style_name(ctx, n.value) if n.kind == "text" else None
    if name is None:
        return
    count = apply_style(ctx, ctx.editable(s.value), name)
    ctx.say("%d object(s) changed." % count)


def plot_style_name(ctx, text: str) -> str:
    t = str(text).strip()
    if t.casefold() == "bylayer":
        return "ByLayer"
    if t.casefold() == "byblock":
        return "ByBlock"
    for tb in plotstyle.all_tables(ctx.d).values():
        if tb["kind"] == "named" and t.casefold() in tb["styles"]:
            return tb["styles"][t.casefold()]["name"]
    raise CommandError('Plot style "%s" is not in any named table.' % t)


def apply_style(ctx, handles, name: str) -> int:
    n = 0
    for e in handles:
        ent = ctx.d.modify(e.handle)
        if ent.plot_style != name:
            ent.plot_style = name
            n += 1
    return n


@executes("plotstyle")
def plotstyle_exec(ctx, args):
    name = plot_style_name(ctx, args.get("style", "ByLayer"))
    hs = args.get("handles")
    if hs is None and args.get("handle") is not None:
        hs = [args["handle"]]
    if not hs:
        ctx.setvar("CPLOTSTYLE", name)
        return {"current": name}
    return {"changed": apply_style(ctx, ctx.editable([int(h) for h in hs]), name)}


@command("plottermanager", aliases=("plottermgr",), group="output", label="Plotter Manager", description="List output devices and add a device from a file.", menu="File > Plotter Manager...", undoable=False, repeatable=False)
def plottermanager(ctx):
    for dv in devices.listing():
        ctx.say("%s (%s, %d dpi, %d papers)" % (dv["name"], dv["output"], dv["resolution"], dv["papers"]))
    ctx.say("Device files are kept in %s." % devices.folder())


@executes("plottermanager")
def plottermanager_exec(ctx, args):
    if args.get("device"):
        try:
            path = devices.save_device(args["device"])
        except (devices.DeviceError, OSError) as err:
            raise CommandError(str(err))
        return {"path": path, "devices": devices.listing()}
    return {"devices": devices.listing()}
