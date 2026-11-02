import math

from app.cmd.context import CommandError
from app.cmd.prompts import Prompt
from app.cmd.registry import command, executes
from app.doc import count as K
from app.doc import measure as M
from app.doc import queries as Q
from app.doc.model import SPACE_MODEL
from app.sysvars import registry as sv

NAMES = {"lwpolyline": "POLYLINE", "insert": "BLOCK REFERENCE", "mtext": "MTEXT", "polyline3d": "3D POLYLINE", "xline": "XLINE"}


def xyz(ctx, p) -> str:
    z = p[2] if len(p) > 2 else 0.0
    return "X=%s  Y=%s  Z=%s" % (ctx.fd(p[0]), ctx.fd(p[1]), ctx.fd(z))


def space_line(ctx, e) -> str:
    return "Space: Model space" if e.owner == SPACE_MODEL else ("Space: Paper space" if e.owner.startswith("layout:") else "Space: Block %s" % e.owner.split(":", 1)[-1])


def describe(ctx, e) -> list:
    k = e.kind
    out = ['%-16s Layer: "%s"' % (NAMES.get(k, k.upper()), e.layer), space_line(ctx, e), "Handle = %X" % e.handle]
    if k == "line":
        dx, dy = e.end[0] - e.start[0], e.end[1] - e.start[1]
        out += ["from point, " + xyz(ctx, e.start), "  to point, " + xyz(ctx, e.end), "Length = %s,  Angle in XY Plane = %s" % (ctx.fd(math.hypot(dx, dy)), ctx.fa(math.atan2(dy, dx) % math.tau)), "Delta X = %s,  Delta Y = %s,  Delta Z = %s" % (ctx.fd(dx), ctx.fd(dy), ctx.fd(0.0))]
    elif k == "circle":
        out += ["center point, " + xyz(ctx, e.center), "radius %s" % ctx.fd(e.radius), "circumference %s" % ctx.fd(math.tau * e.radius), "area %s" % ctx.fd(math.pi * e.radius**2)]
    elif k == "arc":
        sweep = (e.end_angle - e.start_angle) % math.tau
        out += ["center point, " + xyz(ctx, e.center), "radius %s" % ctx.fd(e.radius), "start angle %s" % ctx.fa(e.start_angle), "end angle %s" % ctx.fa(e.end_angle), "length %s" % ctx.fd(e.radius * sweep)]
    elif k == "lwpolyline":
        out.append("Closed" if e.closed else "Open")
        out.append("Constant width %s" % ctx.fd(e.const_width))
        area, perim = M.polygon_measure(e.vertices, bool(e.closed))
        if e.closed:
            out += ["area %s" % ctx.fd(area), "perimeter %s" % ctx.fd(perim)]
        else:
            out.append("length %s" % ctx.fd(perim))
        out.append("elevation %s" % ctx.fd(e.elevation))
        for v in e.vertices:
            out.append("at point, " + xyz(ctx, v["p"]))
    elif k == "ellipse":
        a = math.hypot(e.major[0], e.major[1])
        out += ["center point, " + xyz(ctx, e.center), "major radius %s" % ctx.fd(a), "minor radius %s" % ctx.fd(a * e.ratio)]
    elif k == "text":
        out += ["Style = %s" % e.style, "insertion point, " + xyz(ctx, e.position), "height %s" % ctx.fd(e.height), "text %s" % e.text, "rotation angle %s" % ctx.fa(e.rotation % math.tau)]
    elif k == "mtext":
        out += ["Style = %s" % e.style, "insertion point, " + xyz(ctx, e.position), "height %s" % ctx.fd(e.height), "width %s" % ctx.fd(e.width), "contents %s" % Q.plain_text(e.contents)]
    elif k == "insert":
        out += ["block name: %s" % e.block, "insertion point, " + xyz(ctx, e.position), "X scale factor %s" % ctx.fd(e.scale[0]), "Y scale factor %s" % ctx.fd(e.scale[1]), "rotation angle %s" % ctx.fa(e.rotation % math.tau)]
        for a in e.attributes or []:
            out.append("attribute %s = %s" % (a.get("tag", ""), a.get("value", "")))
    elif k == "point":
        out.append("at point, " + xyz(ctx, e.position))
    else:
        g = Q.geometry(e)
        for key, val in g.items():
            out.append("%s %s" % (key.replace("_", " "), val))
    return out


@command("list", aliases=("li", "ls"), group="inquiry", label="List", description="List the properties of selected objects.", menu="Tools > Inquiry > List", undoable=False, repeatable=False)
def list_cmd(ctx):
    r = yield ctx.select("Select objects")
    if r.kind != "selection" or not r.value:
        return
    shown = 0
    for h in r.value[:200]:
        e = ctx.d.get(h)
        if e is None:
            continue
        for ln in describe(ctx, e):
            ctx.say(ln)
        shown += 1
    if len(r.value) > 200:
        ctx.say("... and %d more objects." % (len(r.value) - 200))


@executes("list")
def list_exec(ctx, args):
    handles = args.get("handles") or ctx.doc.selection
    out = []
    for h in handles[:1000]:
        e = ctx.d.get(int(h))
        if e is None:
            continue
        lines = describe(ctx, e)
        for ln in lines:
            ctx.say(ln)
        out.append({"handle": e.handle, "type": e.kind, "lines": lines})
    if not out:
        raise CommandError("No objects to list.")
    return {"objects": out}


def status_lines(ctx) -> list:
    d, doc = ctx.d, ctx.doc
    h = d.header
    box = d.extents(doc.current_space)
    lo = h.get("LIMMIN", [0.0, 0.0])
    hi = h.get("LIMMAX", [0.0, 0.0])
    on = "On" if h.get("LIMCHECK", 0) else "Off"
    clr = sv.color_text(h.get("CECOLOR", 256)).upper()
    ltype = str(h.get("CELTYPE", "ByLayer")).upper()
    out = [
        "%d objects in %s" % (len(d.ents), doc.name),
        "Model space limits are X: %s  Y: %s  (%s)" % (ctx.fd(lo[0]), ctx.fd(lo[1]), on),
        "                       X: %s  Y: %s" % (ctx.fd(hi[0]), ctx.fd(hi[1])),
    ]
    if box:
        out += ["Model space uses     X: %s  Y: %s" % (ctx.fd(box[0]), ctx.fd(box[1])), "                       X: %s  Y: %s" % (ctx.fd(box[2]), ctx.fd(box[3]))]
    else:
        out.append("Model space uses     nothing")
    out += ['Current layer: "%s"' % d.current_layer(), "Current color: %s" % clr, "Current linetype: %s" % ltype]
    return out


@command("status", group="inquiry", label="Status", description="Show object count, limits, extents and the current layer, colour and linetype.", menu="Tools > Inquiry > Status", transparent=True, undoable=False, repeatable=False)
def status_cmd(ctx):
    for ln in status_lines(ctx):
        ctx.say(ln)


@executes("status")
def status_exec(ctx, args):
    lines = status_lines(ctx)
    for ln in lines:
        ctx.say(ln)
    d, doc = ctx.d, ctx.doc
    box = d.extents(doc.current_space)
    return {"objects": len(d.ents), "title": doc.name, "limits": [d.header.get("LIMMIN"), d.header.get("LIMMAX")], "limits_on": bool(d.header.get("LIMCHECK", 0)), "extents": list(box) if box else None, "layer": d.current_layer(), "color": d.header.get("CECOLOR", 256), "linetype": d.header.get("CELTYPE", "ByLayer"), "lines": lines}


def time_info(ctx) -> dict:
    doc = ctx.doc
    return {"revision": doc.rev, "edits": len(doc.undo.steps), "redo": len(doc.undo.redo_stack), "created": doc.created, "modified": doc.modified}


@command("time", group="inquiry", label="Time", description="Show the drawing revision number and the number of recorded edits.", menu="Tools > Inquiry > Time", transparent=True, undoable=False, repeatable=False)
def time_cmd(ctx):
    t = time_info(ctx)
    ctx.say("Drawing revision: %d" % t["revision"])
    ctx.say("Recorded edits: %d" % t["edits"])
    ctx.say("Created: %s" % t["created"])
    ctx.say("Last changed: %s" % t["modified"])


@executes("time")
def time_exec(ctx, args):
    t = time_info(ctx)
    ctx.say("Drawing revision: %d; recorded edits: %d." % (t["revision"], t["edits"]))
    return t


def scope_for(ctx, scope: str):
    d = ctx.d
    low = (scope or "current").strip().lower()
    if low == "selection":
        return [], list(ctx.doc.selection), "the selection"
    spaces = K.space_names(d, scope, ctx.doc.current_space)
    if not spaces:
        raise CommandError('There is no space named "%s".' % scope)
    return spaces, None, K.scope_label(d, scope, ctx.doc.current_space)


def print_counts(ctx, res, label) -> None:
    rows = res.rows()
    if not rows:
        ctx.say("No block references in %s." % label)
    else:
        ctx.say("Block references in %s:" % label)
        for r in rows:
            ctx.say("  %s: %d%s" % (r["name"], r["count"], " (%d nested)" % r["nested"] if r["nested"] else ""))
        ctx.say("  Total: %d" % res.total())
    if res.capped:
        ctx.say("The count stopped at the work limit; the numbers are incomplete.")
    if res.deep:
        ctx.say("Blocks nested deeper than %d levels were not followed." % K.MAX_DEPTH)


def pack(res, label) -> dict:
    return {"scope": label, "blocks": res.rows(), "total": res.total(), "capped": res.capped, "deep": res.deep}


def listing(ctx, scope):
    spaces, handles, label = scope_for(ctx, scope)
    res = K.count_blocks(ctx.d, spaces, handles)
    print_counts(ctx, res, label)
    return pack(res, label)


def count_like(ctx, handle, scope):
    spaces, handles, label = scope_for(ctx, scope)
    sample = ctx.d.get(int(handle))
    if sample is None:
        raise CommandError("No such object.")
    if sample.kind == "insert":
        res = K.count_blocks(ctx.d, spaces, handles)
        name = K.report_name(ctx.d, sample.block)
        n, k = res.direct.get(name, 0), res.nested.get(name, 0)
        ctx.say("Block %s: %d in %s%s." % (name, n, label, " (%d nested)" % k if k else ""))
        match = K.count_like(ctx.d, spaces, sample, handles)
        out = {"scope": label, "block": name, "count": n, "nested": k}
    else:
        match = K.count_like(ctx.d, spaces, sample, handles)
        ctx.say("%d %s object%s shaped like the picked one in %s." % (len(match), sample.kind, "" if len(match) == 1 else "s", label))
        out = {"scope": label, "type": sample.kind, "count": len(match)}
    if len(match) > K.MAX_HIGHLIGHT:
        ctx.say("Only the first %d are highlighted." % K.MAX_HIGHLIGHT)
    ctx.doc.selection = match[: K.MAX_HIGHLIGHT]
    ctx.doc.announce("selection")
    out["handles"] = match[:1000]
    return out


def count_block_named(ctx, name, scope):
    spaces, handles, label = scope_for(ctx, scope)
    res = K.count_blocks(ctx.d, spaces, handles)
    key = next((n for n in res.names() if n.casefold() == name.casefold()), None)
    if key is None:
        ctx.say("No block references in %s." % label)
        return {"scope": label, "block": name, "count": 0, "nested": 0}
    ctx.say("Block %s: %d in %s%s." % (key, res.direct.get(key, 0), label, " (%d nested)" % res.nested[key] if res.nested.get(key) else ""))
    return {"scope": label, "block": key, "count": res.direct.get(key, 0), "nested": res.nested.get(key, 0)}


@command("count", group="inquiry", label="Count", description="Count block references or objects shaped like a picked one.", menu="Tools > Inquiry > Count", undoable=False, repeatable=False)
def count_cmd(ctx):
    mem = ctx.mem.setdefault("count", {"scope": "current"})
    while True:
        r = yield Prompt("Select object to count or [List/Spaces] <List>", ("select",), ["List", "Spaces"], "List", "List", select=True)
        if r.kind == "keyword" and r.value == "Spaces":
            s = yield ctx.word("Enter space (Current, Model, All, Selection or a layout name)", ["Current", "Model", "All", "Selection"], mem["scope"].title())
            if s.kind in ("keyword", "text"):
                mem["scope"] = str(s.value).lower()
            continue
        if r.kind == "keyword" or (r.kind == "selection" and not r.value):
            listing(ctx, mem["scope"])
            return
        if r.kind == "selection":
            if len(r.value) > 1:
                ctx.doc.selection = list(r.value)
                listing(ctx, "selection")
            else:
                count_like(ctx, r.value[0], mem["scope"])
            return
        return


@executes("count")
def count_exec(ctx, args):
    scope = str(args.get("scope", "current"))
    if args.get("block"):
        return count_block_named(ctx, str(args["block"]), scope)
    if args.get("handle") is not None:
        return count_like(ctx, args["handle"], scope)
    return listing(ctx, scope)


@command("countlist", group="inquiry", label="Count List", description="List the block references counted in all spaces.", menu="Tools > Inquiry > Count List", undoable=False, repeatable=False)
def countlist_cmd(ctx):
    listing(ctx, "all")


@executes("countlist")
def countlist_exec(ctx, args):
    return listing(ctx, str(args.get("scope", "all")))


def make_count_table(ctx, scope, at):
    from app.cmd.commands import tables as TB
    from app.doc import tableops as O

    spaces, handles, label = scope_for(ctx, scope)
    res = K.count_blocks(ctx.d, spaces, handles)
    rows = res.rows()
    if not rows:
        raise CommandError("There are no block references in %s to put in a table." % label)
    data = [["Name", "Count"]] + [[r["name"], str(r["count"] + r["nested"])] for r in rows]
    t = TB.make_table(ctx, 2, len(data), at)
    try:
        O.fill_from_rows(ctx.d, t, data, 0)
    except O.TableError as err:
        raise CommandError(str(err))
    h = ctx.add(t)
    ctx.say("Table of %d block%s inserted." % (len(rows), "" if len(rows) == 1 else "s"))
    return {"handle": h, "blocks": len(rows), "scope": label}


@command("counttable", group="inquiry", label="Count Table", description="Insert a table of block counts.", menu="Tools > Inquiry > Count Table", undoable=True, repeatable=False)
def counttable_cmd(ctx):
    p = yield ctx.point("Specify insertion point")
    if p.kind != "point":
        return
    make_count_table(ctx, "all", p.value)


@executes("counttable")
def counttable_exec(ctx, args):
    return make_count_table(ctx, str(args.get("scope", "all")), list(args.get("point", [0.0, 0.0])))


def run_query(fn):
    def call(*a, **kw):
        try:
            return fn(*a, **kw)
        except ValueError as err:
            raise CommandError(str(err))

    return call


@command("inspectdrawing", group="inquiry", label="Inspect Drawing", description="Summarise the drawing for a program: title, path, counts, extents, layers.", undoable=False, repeatable=False)
def inspect_cmd(ctx):
    r = Q.inspect_drawing(ctx.doc)
    ctx.say("%s: %d objects, %d layers." % (r["title"], r["objects"], r["layer_count"]))


@executes("inspectdrawing")
def inspect_exec(ctx, args):
    return Q.inspect_drawing(ctx.doc, args.get("limit", Q.DEFAULT_LIMIT))


@command("queryentities", group="inquiry", label="Query Entities", description="Find objects by type, layer, selection or window.", undoable=False, repeatable=False)
def queryentities_cmd(ctx):
    r = run_query(Q.query_entities)(ctx.doc, limit=20)
    ctx.say("%d objects match; first %d listed." % (r["matched"], r["returned"]))
    for e in r["entities"]:
        ctx.say("%X  %s  %s" % (e["handle"], e["type"], e["layer"]))


@executes("queryentities")
def queryentities_exec(ctx, args):
    a = args
    return run_query(Q.query_entities)(ctx.doc, a.get("types"), a.get("layers"), bool(a.get("selection", False)), a.get("window"), bool(a.get("crossing", True)), a.get("limit", Q.DEFAULT_LIMIT), a.get("offset", 0), a.get("space"))


@command("querytexts", group="inquiry", label="Query Texts", description="Read the text of text, multiline text, attributes and multileaders.", undoable=False, repeatable=False)
def querytexts_cmd(ctx):
    r = run_query(Q.query_texts)(ctx.doc, limit=20)
    ctx.say("%d texts found." % r["matched"])
    for t in r["texts"]:
        ctx.say("%X  %s  %s" % (t["handle"], t["type"], t["text"].replace("\n", " ")))


@executes("querytexts")
def querytexts_exec(ctx, args):
    a = args
    return run_query(Q.query_texts)(ctx.doc, a.get("contains", ""), a.get("layer", ""), a.get("window"), a.get("limit", Q.DEFAULT_LIMIT), a.get("space"))


@command("analyzeshapes", group="inquiry", label="Analyze Shapes", description="Perimeter, area, centroid, winding and flaws of every closed shape.", undoable=False, repeatable=False)
def analyzeshapes_cmd(ctx):
    r = run_query(Q.analyze_shapes)(ctx.doc, limit=20)
    ctx.say("%d closed shapes analysed." % r["matched"])
    for s in r["shapes"]:
        ctx.say("%X  %s  area %s  perimeter %s" % (s["handle"], s["type"], ctx.fd(s["area"]), ctx.fd(s["perimeter"])))


@executes("analyzeshapes")
def analyzeshapes_exec(ctx, args):
    a = args
    return run_query(Q.analyze_shapes)(ctx.doc, a.get("types"), a.get("layers"), a.get("window"), bool(a.get("crossing", True)), a.get("limit", Q.DEFAULT_LIMIT), a.get("offset", 0), a.get("space"))


@command("impliedloops", group="inquiry", label="Implied Loops", description="Find closed loops and gaps among loose lines and arcs.", undoable=False, repeatable=False)
def impliedloops_cmd(ctx):
    r = Q.implied_loops(ctx.doc)
    ctx.say("%d closed loops, %d open chains, %d junctions." % (len(r["loops"]), len(r["chains"]), len(r["junctions"])))
    if r["state"] == "capped":
        ctx.say("Too many line ends to compare; nothing was analysed.")


@executes("impliedloops")
def impliedloops_exec(ctx, args):
    return run_query(Q.implied_loops)(ctx.doc, args.get("tolerance"), args.get("max_pairs", Q.DEFAULT_PAIRS), args.get("space"))


@command("analyzeusage", group="inquiry", label="Analyze Usage", description="Where layers, blocks, text styles and linetypes are used.", undoable=False, repeatable=False)
def analyzeusage_cmd(ctx):
    r = Q.analyze_usage(ctx.doc)
    for cat, v in r["usage"].items():
        ctx.say("%s: %d (%s)" % (cat, v["total"], ", ".join("%d %s" % (n, s) for s, n in sorted(v["summary"].items()))))


@executes("analyzeusage")
def analyzeusage_exec(ctx, args):
    return run_query(Q.analyze_usage)(ctx.doc, args.get("type", "all"), args.get("limit", Q.DEFAULT_LIMIT), args.get("offset", 0))
