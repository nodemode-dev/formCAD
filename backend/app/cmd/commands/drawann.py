import math

from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.doc import geom
from app.drawann import glyphs, ops, settings, titleblock, viewops, viewsrc
from app.doc import blockdefs


def fail(err):
    return CommandError(str(err))


def editable(ctx, handle, kinds):
    e = ctx.d.get(int(handle)) if handle not in (None, "") else None
    if e is None or e.kind not in kinds:
        raise CommandError("The object is not a %s." % "/".join(kinds))
    if ctx.locked(e):
        raise CommandError("The object is on a locked layer.")
    return e


def guarded(fn):
    def run(ctx, args):
        try:
            return fn(ctx, args)
        except (ops.AnnError, settings.SettingsError, titleblock.TitleError, viewsrc.ViewError, glyphs.GlyphError, ValueError, KeyError, TypeError) as err:
            raise fail(err)

    run.__name__ = fn.__name__
    return run


def ask_point(ctx, msg, **kw):
    r = yield ctx.point(msg, **kw)
    return r.value if r.kind == "point" else None


@command("gdtframe", aliases=("gdt", "tolframe"), group="annotation", label="Geometric Tolerance Frame", description="Place a geometric tolerance frame: characteristic, tolerance zone, material condition and up to three datum references.", menu="Dimension > Geometric Tolerance Frame")
def gdtframe(ctx):
    mem = ctx.mem.setdefault("gdt", {"char": "position", "tolerance": "0.1", "datums": "A"})
    r = yield ctx.text("Enter characteristic (%s)" % ", ".join(glyphs.CHARACTERISTICS), mem["char"])
    if r.kind != "text":
        return
    try:
        key = glyphs.key_of(r.value)
    except glyphs.GlyphError as err:
        ctx.say(str(err))
        return
    t = yield ctx.text("Enter tolerance value", mem["tolerance"])
    if t.kind != "text":
        return
    dt = yield ctx.text("Enter datum references separated by spaces", mem["datums"])
    if dt.kind != "text":
        return
    p = yield from ask_point(ctx, "Specify frame position")
    if p is None:
        return
    args = {"char": key, "tolerance": str(t.value), "datums": [x for x in str(dt.value).replace(",", " ").split() if x not in ("-", "none")], "point": [p[0], p[1]]}
    try:
        ctx.add(ops.new_frame(ctx.d, args))
    except ops.AnnError as err:
        ctx.say(str(err))
        return
    mem.update({"char": key, "tolerance": str(t.value), "datums": str(dt.value)})


@executes("gdtframe")
@guarded
def gdtframe_exec(ctx, args):
    e = ops.new_frame(ctx.d, args)
    h = ctx.add(e)
    return {"created": h, "char": e.char, "datums": e.datums}


@command("gdtedit", group="annotation", label="Edit Geometric Tolerance Frame", description="Change the fields of a geometric tolerance frame.", menu="", repeatable=False)
def gdtedit(ctx):
    r = yield ctx.entity("Select a geometric tolerance frame")
    if r.kind != "entity":
        return
    e = ctx.d.get(r.value["handle"])
    if e is None or e.kind != "gdtframe":
        ctx.say("That object is not a geometric tolerance frame.")
        return
    t = yield ctx.text("Enter tolerance value", e.tolerance)
    if t.kind != "text":
        return
    ent = ctx.d.modify(e.handle)
    ent.tolerance = str(t.value)


@executes("gdtedit")
@guarded
def gdtedit_exec(ctx, args):
    e = editable(ctx, args.get("handle"), ("gdtframe",))
    ent = ctx.d.modify(e.handle)
    ops.apply_frame(ctx.d, ent, {k: v for k, v in args.items() if k not in ("handle", "point", "position")})
    if args.get("point") is not None or args.get("position") is not None:
        ent.position = ops.pt(args.get("point", args.get("position")))
    return {"handle": ent.handle, "char": ent.char}


@command("datumsym", aliases=("datum",), group="annotation", label="Datum Feature Symbol", description="Place a datum feature symbol with its triangle on a feature.", menu="Dimension > Datum Feature Symbol")
def datumsym(ctx):
    mem = ctx.mem.setdefault("datum", {"letter": "A"})
    r = yield ctx.text("Enter datum letter", mem["letter"])
    if r.kind != "text":
        return
    tip = yield from ask_point(ctx, "Specify the point on the feature")
    if tip is None:
        return
    p = yield from ask_point(ctx, "Specify the symbol position", base=tip)
    if p is None:
        return
    try:
        ctx.add(ops.new_datum(ctx.d, {"letter": str(r.value), "point": [p[0], p[1]], "tip": [tip[0], tip[1]]}))
    except ops.AnnError as err:
        ctx.say(str(err))
        return
    mem["letter"] = str(r.value)


@executes("datumsym")
@guarded
def datumsym_exec(ctx, args):
    e = ops.new_datum(ctx.d, args)
    return {"created": ctx.add(e), "letter": e.letter}


@command("balloon", group="annotation", label="Balloon", description="Place a balloon with an item number and a leader to a part edge.", menu="Dimension > Balloon")
def balloon(ctx):
    mem = ctx.mem.setdefault("balloon", {"n": 1})
    tip = yield from ask_point(ctx, "Specify the point on the part")
    if tip is None:
        return
    p = yield from ask_point(ctx, "Specify the balloon position", base=tip)
    if p is None:
        return
    r = yield ctx.text("Enter item number", str(mem["n"]))
    if r.kind != "text":
        return
    try:
        ctx.add(ops.new_balloon(ctx.d, {"text": str(r.value), "point": [p[0], p[1]], "tip": [tip[0], tip[1]]}))
    except ops.AnnError as err:
        ctx.say(str(err))
        return
    mem["n"] = int(str(r.value)) + 1 if str(r.value).isdigit() else mem["n"]


@executes("balloon")
@guarded
def balloon_exec(ctx, args):
    e = ops.new_balloon(ctx.d, args)
    return {"created": ctx.add(e), "text": e.text}


@command("finishmark", aliases=("surfacefinish",), group="annotation", label="Surface Finish Mark", description="Place a simple surface finish mark carrying a value.", menu="Dimension > Surface Finish Mark")
def finishmark(ctx):
    mem = ctx.mem.setdefault("finish", {"value": "Ra 3.2"})
    r = yield ctx.text("Enter the surface finish value", mem["value"])
    if r.kind != "text":
        return
    p = yield from ask_point(ctx, "Specify the mark position")
    if p is None:
        return
    try:
        ctx.add(ops.new_finish(ctx.d, {"value": str(r.value), "point": [p[0], p[1]]}))
    except ops.AnnError as err:
        ctx.say(str(err))
        return
    mem["value"] = str(r.value)


@executes("finishmark")
@guarded
def finishmark_exec(ctx, args):
    e = ops.new_finish(ctx.d, args)
    return {"created": ctx.add(e), "value": e.value}


@command("centermark", aliases=("cmark",), group="annotation", label="Center Mark", description="Place a center mark on a circle or a center line between two points.", menu="Dimension > Center Mark")
def centermark(ctx):
    c = yield from ask_point(ctx, "Specify the center")
    if c is None:
        return
    r = yield ctx.distance("Specify the radius", base=c, positive=True)
    if r.kind not in ("number", "distance", "point"):
        return
    rad = r.value if r.kind != "point" else geom.dist(c, r.value)
    try:
        ctx.add(ops.new_centermark(ctx.d, {"center": [c[0], c[1]], "radius": rad}))
    except ops.AnnError as err:
        ctx.say(str(err))


@executes("centermark")
@guarded
def centermark_exec(ctx, args):
    e = ops.new_centermark(ctx.d, args)
    return {"created": ctx.add(e), "mode": e.mode}


@command("centermarks", group="annotation", label="Center Marks For View", description="Add center marks to the circles and center lines to the cylinders of a drawing view.", menu="", repeatable=False)
def centermarks(ctx):
    r = yield ctx.entity("Select a drawing view")
    if r.kind != "entity":
        return
    out = centermarks_exec(ctx, {"view": r.value["handle"]})
    ctx.say("%d center mark(s) added." % len(out["created"]))


@executes("centermarks")
@guarded
def centermarks_exec(ctx, args):
    view = viewsrc.need(ctx.d, args.get("view"))
    st = settings.get(ctx.d)
    if args.get("replace", True):
        for e in [x for x in ctx.d.entities(ctx.doc.current_space) if x.kind == "centermark" and x.view == view.handle]:
            ctx.d.erase_entity(e.handle)
    made = [ctx.add(e) for e in viewops.centermarks(ctx.d, view, st, bool(args.get("arcs")))]
    return {"created": made}


@command("sectionhatch", group="annotation", label="Section Hatching", description="Hatch the cut faces of a section view with the hatch engine.", menu="", repeatable=False)
def sectionhatch(ctx):
    r = yield ctx.entity("Select a section view")
    if r.kind != "entity":
        return
    out = sectionhatch_exec(ctx, {"view": r.value["handle"]})
    ctx.say("%d hatch(es) added." % len(out["created"]))


@executes("sectionhatch")
@guarded
def sectionhatch_exec(ctx, args):
    view = viewsrc.need(ctx.d, args.get("view"))
    st = settings.get(ctx.d)
    if args.get("pattern"):
        st["hatch_pattern"] = str(args["pattern"])
    if args.get("scale"):
        st["hatch_scale"] = ops.num(args["scale"], "The pattern scale", 0.01, 1000.0)
    for e in [x for x in ctx.d.entities(ctx.doc.current_space) if x.kind == "hatch" and x.extra.get("section_view") == view.handle]:
        ctx.d.erase_entity(e.handle)
    made = [ctx.add(e) for e in viewops.section_hatches(ctx.d, view, st)]
    return {"created": made}


@command("gdtstyle", group="settings", label="Annotation Settings", description="Compartment order, balloon size, center mark and BOM column settings for drawing annotation.", menu="", repeatable=False)
def gdtstyle(ctx):
    ctx.say("Annotation settings are available through the programmatic form: gdtstyle with the setting names.")
    yield from ()


@executes("gdtstyle")
@guarded
def gdtstyle_exec(ctx, args):
    changes = {k: v for k, v in args.items() if k not in ("reset",)}
    if args.get("reset"):
        ctx.d.set_header(settings.KEY, {})
    cur = settings.put(ctx.d, changes) if changes else settings.get(ctx.d)
    return {"settings": cur}


@command("docprops", group="settings", label="Document Properties", description="Title, drawn by, date, revision and the other title block data of the document.", menu="", repeatable=False)
def docprops(ctx):
    ctx.say("Document properties are available through the programmatic form: docprops with the property names.")
    yield from ()


@executes("docprops")
@guarded
def docprops_exec(ctx, args):
    changes = {k: v for k, v in args.items()}
    cur = titleblock.put_props(ctx.d, changes) if changes else titleblock.props(ctx.d)
    return {"properties": cur}


def scale_of_main(ctx, layout):
    for v in viewsrc.views(ctx.d, "layout:" + layout):
        prov = viewsrc.provider_for(v)
        if hasattr(prov, "scale_text"):
            t = prov.scale_text(ctx.d, v)
            if t:
                return t
    for e in ctx.d.entities("layout:" + layout):
        if e.kind == "viewport":
            from app.doc import layouts as L

            return L.scale_text_of(1.0 / e.scale) if e.scale else ""
    return ""


@command("titleblock", group="annotation", label="Title Block", description="Insert the title block and fill its attributes from the document properties.", menu="", repeatable=False)
def titleblock_cmd(ctx):
    p = yield from ask_point(ctx, "Specify the title block insertion point")
    if p is None:
        return
    titleblock_exec(ctx, {"point": [p[0], p[1]]})


def current_layout(ctx):
    sp = ctx.doc.current_space
    if not sp.startswith("layout:"):
        raise CommandError("Switch to a layout first.")
    return sp[7:]


@executes("titleblock")
@guarded
def titleblock_exec(ctx, args):
    d = ctx.d
    layout = args.get("layout") or current_layout(ctx)
    if blockdefs.lookup(d, titleblock.BLOCK) is None:
        titleblock.build_block(d)
    tags = titleblock.tags_of(d)
    vals = titleblock.values_for(d, layout, args.get("scale") or scale_of_main(ctx, layout), getattr(ctx.doc, "title", "") or "")
    if "SHEETS" not in tags and "SHEET" in tags:
        vals["SHEET"] = "%s of %s" % (vals["SHEET"], vals["SHEETS"])
    vals = {k: v for k, v in vals.items() if k in tags}
    for k, v in (args.get("values") or {}).items():
        if k in tags:
            vals[k] = str(v)
    existing = [e for e in d.entities("layout:" + layout) if e.kind == "insert" and e.block.upper() == titleblock.BLOCK]
    if existing and not args.get("point"):
        ent = d.modify(existing[0].handle)
        for a in ent.attributes:
            if a["tag"] in vals:
                a["value"] = vals[a["tag"]]
        return {"handle": ent.handle, "filled": sorted(vals), "updated": True}
    at = ops.pt(args.get("point", [0.0, 0.0]))
    rec = blockdefs.lookup(d, titleblock.BLOCK)
    ins = blockdefs.new_insert(d, rec["name"], at, attributes=vals)
    h = ctx.add(ins)
    return {"handle": h, "filled": sorted(vals), "updated": False}


def bom_rows(ctx, source):
    from app.drawann import bom

    if not isinstance(source, dict):
        raise CommandError("Give a BOM source: rows, path, self or view.")
    if source.get("rows"):
        return bom.from_rows(source["rows"])
    if source.get("path"):
        from app.assembly import parts

        try:
            lp = parts.load(str(source["path"]))
        except Exception as err:
            raise CommandError("The assembly could not be read: %s" % err)

        class Shim:
            drawing = lp.drawing
            path = lp.path

        return bom.collect(Shim)
    if source.get("self"):
        return bom.collect(ctx.doc)
    if source.get("view") not in (None, ""):
        view = viewsrc.need(ctx.d, source["view"])
        prov = viewsrc.provider_for(view)
        if hasattr(prov, "bom_rows"):
            return bom.from_rows(prov.bom_rows(ctx.d, view))
        if not (getattr(view, "source", None) or {}).get("doc"):
            return bom.collect(ctx.doc)
        raise CommandError("That view has no model to take a BOM from.")
    raise CommandError("Give a BOM source: rows, path, self or view.")


def fill_bom(ctx, t, rows, columns, title):
    from app.doc import tableops as O
    from app.drawann import bom

    st = settings.get(ctx.d)
    th = st["bom_text_height"]
    body = bom.cells(rows, columns)
    t.col_widths = bom.widths(rows, columns, th)
    t.text_height = th
    need = len(body) + int(t.title) + int(t.header)
    while len(t.cells) < need:
        t.cells.append([O.new_cell_blank() if hasattr(O, "new_cell_blank") else dict(t.cells[0][0], text="", formula="", span=[1, 1]) for _ in columns])
        t.row_heights.append(st["bom_row_height"])
        t.row_styles.append("")
    del t.cells[need:], t.row_heights[need:], t.row_styles[need:]
    r0 = 0
    if t.title:
        O.set_cell(ctx.d, t, 0, 0, title)
        r0 = 1
    if t.header:
        for c, name in enumerate(columns):
            O.set_cell(ctx.d, t, r0, c, settings.COLUMN_TITLES[name], "text")
        r0 += 1
    for r, row in enumerate(body):
        for c, v in enumerate(row):
            O.set_cell(ctx.d, t, r0 + r, c, v, "text")
    for r in range(len(t.row_heights)):
        t.row_heights[r] = max(t.row_heights[r], st["bom_row_height"])
    O.ensure_heights(ctx.d, t)


def pick_columns(ctx, args):
    cols = args.get("columns") or settings.get(ctx.d)["bom_columns"]
    return settings.check_columns(cols)


@command("bomtable", group="annotation", label="BOM Table", description="Place a bill of materials table built from the assembly data; it can be updated when the assembly changes.", menu="")
def bomtable(ctx):
    p = yield from ask_point(ctx, "Specify the BOM table insertion point")
    if p is None:
        return
    try:
        bomtable_exec(ctx, {"point": [p[0], p[1]], "source": {"self": True}})
    except CommandError as err:
        ctx.say(str(err))


@executes("bomtable")
@guarded
def bomtable_exec(ctx, args):
    from app.doc import tableops as O

    source = args.get("source") or ({"rows": args["rows"]} if args.get("rows") else {"self": True})
    rows = bom_rows(ctx, source)
    cols = pick_columns(ctx, args)
    title = str(args.get("title", "PARTS LIST"))[:80]
    at = ops.pt(args.get("point", [0.0, 0.0]))
    from app.cmd.commands.tables import make_table

    t = make_table(ctx, len(cols), max(len(rows), 1), at, args.get("style"))
    fill_bom(ctx, t, rows, cols, title)
    t.extra = {"bom": {"source": source, "columns": cols, "title": title}}
    h = ctx.add(t)
    return {"created": h, "rows": len(rows), "items": [r["item"] for r in rows]}


@command("bomupdate", group="annotation", label="Update BOM Tables", description="Rebuild the BOM tables from the current assembly data.", menu="", repeatable=False)
def bomupdate(ctx):
    out = bomupdate_exec(ctx, {})
    ctx.say("%d BOM table(s) updated." % out["updated"])
    yield from ()


@executes("bomupdate")
@guarded
def bomupdate_exec(ctx, args):
    want = {int(h) for h in args["handles"]} if args.get("handles") else None
    n = 0
    for e in list(ctx.d.ents.values()):
        if e.kind != "table" or "bom" not in (e.extra or {}) or (want is not None and e.handle not in want) or ctx.locked(e):
            continue
        meta = e.extra["bom"]
        rows = bom_rows(ctx, meta["source"])
        t = ctx.d.modify(e.handle)
        fill_bom(ctx, t, rows, meta["columns"], meta["title"])
        n += 1
    return {"updated": n}


@command("bomexport", group="output", label="Export BOM", description="Write a BOM table to a CSV file.", menu="", undoable=False, repeatable=False)
def bomexport(ctx):
    r = yield ctx.text("Enter the BOM table file name")
    if r.kind != "text":
        return
    from app.cmd import barred

    why = barred.args_refusal(ctx.runner, bomexport.spec, {"path": str(r.value)})
    if why:
        raise CommandError(why)
    try:
        out = bomexport_exec(ctx, {"path": str(r.value)})
    except CommandError as err:
        ctx.say(str(err))
        return
    ctx.say("BOM written to %s." % out["path"])


@executes("bomexport")
@guarded
def bomexport_exec(ctx, args):
    import csv

    from app.assembly.bom import cell
    from app.core import outputs

    try:
        path = outputs.checked(args.get("path"), (".csv",), ".csv")
    except outputs.OutputRefused as err:
        raise CommandError(str(err))
    tabs = [e for e in ctx.d.ents.values() if e.kind == "table" and "bom" in (e.extra or {})]
    if args.get("handle"):
        tabs = [t for t in tabs if t.handle == int(args["handle"])]
    if not tabs:
        raise CommandError("There is no BOM table.")
    t = tabs[0]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        for row in t.cells:
            w.writerow([cell(c.get("text", "")) for c in row])
    return {"path": path, "rows": len(t.cells)}


@command("autoballoon", group="annotation", label="Auto Balloons", description="Place a balloon for every BOM item on the parts of a drawing view.", menu="", repeatable=False)
def autoballoon(ctx):
    r = yield ctx.entity("Select a drawing view")
    if r.kind != "entity":
        return
    try:
        out = autoballoon_exec(ctx, {"view": r.value["handle"]})
    except CommandError as err:
        ctx.say(str(err))
        return
    ctx.say("%d balloon(s) placed." % len(out["created"]))


@executes("autoballoon")
@guarded
def autoballoon_exec(ctx, args):
    view = viewsrc.need(ctx.d, args.get("view"))
    st = settings.get(ctx.d)
    if args.get("table"):
        t = ctx.d.get(int(args["table"]))
        if t is None or "bom" not in (t.extra or {}):
            raise CommandError("The object is not a BOM table.")
        rows = bom_rows(ctx, t.extra["bom"]["source"])
    else:
        rows = bom_rows(ctx, args.get("source") or {"view": view.handle})
    if args.get("diameter"):
        st["balloon_diameter"] = ops.num(args["diameter"], "The diameter", 0.5, 200.0)
    if args.get("replace", True):
        for e in [x for x in ctx.d.entities(ctx.doc.current_space) if x.kind == "balloon" and x.tip_link.get("h") == view.handle]:
            ctx.d.erase_entity(e.handle)
    plans = viewops.balloon_plan(ctx.d, view, rows, st)
    made = []
    for pl in plans:
        b = viewops.make_balloon(pl, args.get("end", ""))
        if args.get("diameter"):
            b.diameter = st["balloon_diameter"]
        made.append(ctx.add(b))
    placed = {p["row"]["item"] for p in plans}
    return {"created": made, "missing": [r["item"] for r in rows if r["item"] not in placed]}


def view_link(ctx, view, raw):
    if not isinstance(raw, dict) or "e" not in raw:
        raise CommandError("A feature is {e: edge, t: start|end|mid|center|ang}.")
    link = {"h": view.handle, "e": str(raw["e"]), "t": str(raw.get("t", "end"))}
    if "a" in raw:
        link["a"] = float(raw["a"])
    if viewsrc.point(ctx.d, link) is None:
        raise CommandError("That edge point is not in the view.")
    return link


def end_of(ctx, view, raw):
    if isinstance(raw, dict) and "point" in raw:
        p = ops.pt(raw["point"], "point")
        return None, (p[0], p[1])
    link = view_link(ctx, view, raw)
    return link, viewsrc.point(ctx.d, link)


@command("viewdim", group="annotation", label="Dimension View Geometry", description="Dimension edges or vertices of a drawing view; the dimension follows the view when the model changes.", menu="")
def viewdim(ctx):
    ctx.say("Dimension View Geometry is available through the programmatic form: viewdim with view, kind and the edge points.")
    yield from ()


@executes("viewdim")
@guarded
def viewdim_exec(ctx, args):
    import math

    from app.cmd import dim_support as DS

    view = viewsrc.need(ctx.d, args.get("view"))
    kind = str(args.get("kind", "linear")).lower()
    loc = ops.pt(args.get("location"), "location")
    st = {}
    if args.get("text") is not None:
        st["override"] = str(args["text"])
    if kind in ("linear", "aligned"):
        la, a = end_of(ctx, view, args.get("a"))
        lb, b = end_of(ctx, view, args.get("b"))
        a3, b3 = [a[0], a[1], 0.0], [b[0], b[1], 0.0]
        if math.hypot(b[0] - a[0], b[1] - a[1]) < 1e-9:
            raise CommandError("The two points must be different.")
        if kind == "aligned":
            rot = 0.0
        else:
            o = str(args.get("orientation", "")).lower()
            rot = 0.0 if o in ("h", "horizontal") else (math.pi / 2.0 if o in ("v", "vertical") else DS.default_orientation(a3, b3, loc))
        e = DS.new_dimension(ctx, kind, p13=a3, p14=b3, def_point=loc, rotation=rot)
        DS.apply_state(e, st)
        hints = {k: v for k, v in (("p13", la), ("p14", lb)) if v}
    elif kind in ("radius", "diameter"):
        ed = viewsrc.edge(ctx.d, view, str(args.get("edge", "")))
        if ed is None or ed["type"] not in ("circle", "arc"):
            raise CommandError("The edge is not a circle or an arc.")
        c, r = ed["c"], float(ed["r"])
        n = math.hypot(loc[0] - c[0], loc[1] - c[1])
        if n < 1e-9:
            raise CommandError("The location must differ from the center.")
        ux, uy = (loc[0] - c[0]) / n, (loc[1] - c[1]) / n
        ang = math.atan2(uy, ux)
        P = [c[0] + ux * r, c[1] + uy * r, 0.0]
        eid = str(ed["id"])
        if kind == "diameter":
            F = [c[0] - ux * r, c[1] - uy * r, 0.0]
            e = DS.new_dimension(ctx, "diameter", def_point=F, p15=P, text_point=loc, text_moved=True)
            hints = {"def_point": {"h": view.handle, "e": eid, "t": "ang", "a": ang + math.pi}, "p15": {"h": view.handle, "e": eid, "t": "ang", "a": ang}}
        else:
            e = DS.new_dimension(ctx, "radius", def_point=[c[0], c[1], 0.0], p15=P, text_point=loc, text_moved=True)
            hints = {"def_point": {"h": view.handle, "e": eid, "t": "center"}, "p15": {"h": view.handle, "e": eid, "t": "ang", "a": ang}}
        DS.apply_state(e, st)
    else:
        raise CommandError("The kind is linear, aligned, radius or diameter.")
    if args.get("model_item"):
        e.marks["model_item"] = str(args["model_item"])
    k = viewsrc.provider_for(view).scale(ctx.d, view) if hasattr(viewsrc.provider_for(view), "scale") else 1.0
    if abs(k - 1.0) > 1e-9:
        from app.cmd.commands import dim_style

        name = "VIEW_%s" % ("%.6g" % k).replace(".", "_")
        dim_style.save_style(ctx, name, {"DIMLFAC": 1.0 / k}, source=dim_style.find_style(ctx, e.style))
        e.style = name
    h = DS.commit_dimension(ctx, e, hints)
    return {"created": h, "measurement": ctx.d.get(h).measurement, "linked": sorted(ctx.d.get(h).associativity)}


ROLE_ORDER = {"front": 0, "right": 1, "left": 1, "top": 2, "bottom": 2, "back": 3}


@command("modelitems", group="annotation", label="Model Items", description="Import the driving dimensions of a part onto the views where they are seen true size.", menu="", repeatable=False)
def modelitems(ctx):
    ctx.say("Model Items is available through the programmatic form: modelitems with the views.")
    yield from ()


@executes("modelitems")
@guarded
def modelitems_exec(ctx, args):
    import math

    from app.drawann import modelitems as MI

    d = ctx.d
    st = settings.get(d)
    handles = args.get("views")
    vs = [viewsrc.need(d, h) for h in handles] if handles else [v for v in viewsrc.views(d, ctx.doc.current_space)]
    if not vs:
        raise CommandError("There is no drawing view in this space.")
    vs.sort(key=lambda v: ROLE_ORDER.get(viewsrc.provider_for(v).role(d, v), 9) if hasattr(viewsrc.provider_for(v), "role") else 9)
    off = ops.num(args.get("offset", 10.0), "The offset", 1.0, 500.0)
    want = set(str(x) for x in args["items"]) if args.get("items") else None
    done = {str(e.marks.get("model_item")) for e in d.ents.values() if e.kind == "dimension" and e.marks.get("model_item")}
    placed, offered = [], {}
    stack = {}
    seen_items = {}
    for v in vs:
        prov = viewsrc.provider_for(v)
        if not hasattr(prov, "project") or not hasattr(prov, "model_drawing"):
            continue
        dm = prov.model_drawing(d, v, getattr(ctx.doc, "path", "") or "")
        vdir = prov.direction(d, v)
        box = viewops.view_box(d, v)
        if dm is None or box is None:
            continue
        cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
        tol = max(d.tolerances["absolute"] * 10.0, 1e-3)
        for it in MI.items(dm):
            key = "%s@%s" % (it["id"], it["sketch"])
            if (want is not None and it["id"] not in want) or key in done or key in seen_items:
                continue
            offered[key] = {"item": it["id"], "label": it["label"]}
            if it["kind"] == "linear":
                dv = [it["b"][i] - it["a"][i] for i in range(3)]
                L = math.sqrt(sum(c * c for c in dv))
                if L < 1e-9 or abs(sum(dv[i] * vdir[i] for i in range(3))) / L > 0.02:
                    continue
                pa, pb = prov.project(d, v, it["a"]), prov.project(d, v, it["b"])
                if pa is None or pb is None or math.hypot(pb[0] - pa[0], pb[1] - pa[1]) < 1e-6:
                    continue
                la, lb = viewsrc.link_for_point(d, v, pa, tol), viewsrc.link_for_point(d, v, pb, tol)
                la = la or {"point": [pa[0], pa[1]]}
                lb = lb or {"point": [pb[0], pb[1]]}
                mx, my = (pa[0] + pb[0]) / 2.0, (pa[1] + pb[1]) / 2.0
                horiz = abs(pb[0] - pa[0]) >= abs(pb[1] - pa[1])
                if it.get("along"):
                    tip = prov.project(d, v, [it["a"][i] + it["along"][i] for i in range(3)])
                    if tip is None or math.hypot(tip[0] - pa[0], tip[1] - pa[1]) < 1e-9:
                        continue
                    horiz = abs(tip[0] - pa[0]) >= abs(tip[1] - pa[1])
                    if abs(pb[0] - pa[0] if horiz else pb[1] - pa[1]) < 1e-6:
                        continue
                k = stack.get((v.handle, horiz, my > cy if horiz else mx > cx), 0)
                stack[(v.handle, horiz, my > cy if horiz else mx > cx)] = k + 1
                if horiz:
                    sign = 1.0 if my >= cy else -1.0
                    loc = [mx, (box[3] if sign > 0 else box[1]) + sign * (off + 8.0 * k)]
                else:
                    sign = 1.0 if mx >= cx else -1.0
                    loc = [(box[2] if sign > 0 else box[0]) + sign * (off + 8.0 * k), my]
                r = viewdim_exec(ctx, {"view": v.handle, "kind": "linear", "a": la, "b": lb, "location": loc, "orientation": "h" if horiz else "v", "model_item": key})
                seen_items[key] = True
                placed.append({"item": it["id"], "label": it["label"], "view": v.handle, "dimension": r["created"], "measurement": r["measurement"]})
            else:
                if abs(sum(it["normal"][i] * vdir[i] for i in range(3))) < 0.999:
                    continue
                pc = prov.project(d, v, it["center"])
                if pc is None:
                    continue
                ed = None
                for e2 in viewsrc.edges(d, v):
                    if e2["type"] == "circle" and math.hypot(e2["c"][0] - pc[0], e2["c"][1] - pc[1]) <= tol * max(1.0, e2["r"]) and abs(e2["r"] - prov.scale(d, v) * it["radius"]) <= 1e-3 * e2["r"] + 1e-6:
                        ed = e2
                        break
                if ed is None:
                    continue
                dx = math.cos(math.radians(45.0 + 30.0 * stack.get((v.handle, "r"), 0)))
                dy = math.sin(math.radians(45.0 + 30.0 * stack.get((v.handle, "r"), 0)))
                stack[(v.handle, "r")] = stack.get((v.handle, "r"), 0) + 1
                loc = [ed["c"][0] + dx * ed["r"] * 2.0, ed["c"][1] + dy * ed["r"] * 2.0]
                r = viewdim_exec(ctx, {"view": v.handle, "kind": it["kind"], "edge": ed["id"], "location": loc, "model_item": key})
                seen_items[key] = True
                placed.append({"item": it["id"], "label": it["label"], "view": v.handle, "dimension": r["created"], "measurement": r["measurement"]})
    skipped = [row for key, row in offered.items() if key not in seen_items]
    return {"placed": placed, "skipped": skipped}
