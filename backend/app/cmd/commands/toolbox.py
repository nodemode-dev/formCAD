import re

from app.cmd import barred
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.solid.work import SolidError
from app.toolbox import gens, insert, inspection, library, mbd

GROUP = "toolbox"
FAILURES = insert.ERRORS + inspection.ERRORS + mbd.ERRORS + (SolidError,)
REF_RE = re.compile(r"^\s*([A-Za-z0-9_]+)\s*:\s*[fF]\s*(\d+)\s*$")


def run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except FAILURES as err:
        raise CommandError(str(err))


def ref_of(value):
    if value in (None, ""):
        return None
    if isinstance(value, dict):
        return value
    m = REF_RE.match(str(value))
    if not m:
        raise CommandError("A face reads like C1:f6 (component, then face number).")
    return {"comp": m.group(1).upper(), "face": int(m.group(2))}


def sizes_of(text: str) -> dict:
    out = {}
    for part in re.split(r"[\s,;]+", str(text or "").strip()):
        if not part:
            continue
        if "=" not in part:
            raise CommandError("Sizes read like d=6 length=20.")
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip()
    return out


@command("toolboxinsert", aliases=("fastener",), group=GROUP, label="Insert Toolbox Part", description="Insert a fastener, washer, nut, pin, bearing or structural shape from entered sizes into an assembly and mate it to a hole and a seat face.", menu="")
def insert_cmd(ctx):
    words = [k.title().replace("_", "") for k in gens.KINDS]
    k = yield ctx.keyword("Kind [%s]" % "/".join(words), words, words[0])
    if k.kind != "keyword":
        return
    kind = next(key for key in gens.KINDS if key.title().replace("_", "") == k.value)
    t = yield ctx.text("Enter the sizes like d=6 length=20")
    if t.kind != "text":
        return
    h = yield ctx.text("Enter the hole face like C1:f6")
    if h.kind != "text":
        return
    s = yield ctx.text("Enter the seat face like C1:f2")
    if s.kind != "text":
        return
    return insert_run(ctx, {"kind": kind, "params": sizes_of(t.value), "hole": h.value, "seat": s.value})


def insert_run(ctx, args):
    if barred.caller(ctx.runner) == "agent" and not args.get("folder"):
        raise CommandError("TOOLBOXINSERT needs folder, a granted folder for the part files, when run by an outside agent.")
    src = args.get("source") or {"kind": args.get("kind"), "params": args.get("params") or {}, "family": args.get("family"), "row": args.get("row")}
    out = run(insert.one, ctx.doc, src, ref_of(args.get("hole")), ref_of(args.get("seat")), args.get("at"), args.get("folder"), args.get("label"), float(args.get("offset") or 0.0), bool(args.get("flip", False)), bool(args.get("mates", True)), args.get("extra"))
    ctx.say("TOOLBOXINSERT: %s as %s, %d mate(s)." % (out["designation"], out["component"], len(out["mates"])))
    return out


@executes("toolboxinsert")
def insert_exec(ctx, args):
    return insert_run(ctx, args)


@command("toolboximport", group=GROUP, label="Import Size Table", description="Read the user's own size table (a CSV file) into a toolbox library family.", menu="")
def import_cmd(ctx):
    t = yield ctx.text("Enter the size table file name")
    if t.kind != "text" or not t.value:
        return
    f = yield ctx.text("Enter the family id")
    if f.kind != "text" or not f.value:
        return
    words = [k.title().replace("_", "") for k in gens.KINDS]
    k = yield ctx.keyword("Kind", words, words[0])
    if k.kind != "keyword":
        return
    kind = next(key for key in gens.KINDS if key.title().replace("_", "") == k.value)
    return import_run(ctx, {"file": t.value, "family": f.value, "kind": kind})


def import_run(ctx, args):
    path = args.get("file") or args.get("path")
    if not path:
        raise CommandError("Give file, the size table file name.")
    who = barred.caller(ctx.runner)
    out = run(library.import_csv, path, str(args.get("family") or ""), str(args.get("kind") or ""), str(args.get("label") or ""), args.get("mapping"), str(args.get("unit") or ""), str(args.get("source") or ""), bool(args.get("replace", False)), who, ctx.runner)
    ctx.say("TOOLBOXIMPORT: %d size(s) added to %s, %d skipped." % (out["added"], out["family"], out["skipped"]))
    return out


@executes("toolboximport")
def import_exec(ctx, args):
    return import_run(ctx, args)


@command("inspection", aliases=("inspect",), group=GROUP, label="Inspection", description="Numbered inspection characteristics from PMI and drawing dimensions: collect, add, edit, remove, renumber, balloons, form, results.", menu="")
def inspection_cmd(ctx):
    ctx.say("INSPECTION: pass an action (collect, add, edit, remove, renumber, balloons, form, results) programmatically.")
    yield from ()


@executes("inspection")
def inspection_exec(ctx, args):
    action = str(args.get("action") or "")
    d = ctx.doc.drawing
    who = barred.caller(ctx.runner)
    if action == "collect":
        out = run(inspection.collect, d, who)
    elif action == "add":
        out = run(inspection.add_manual, d, args, who)
    elif action == "edit":
        out = run(inspection.edit, d, args.get("id"), args.get("changes") or {})
    elif action == "remove":
        out = run(inspection.remove, d, args.get("id"))
    elif action == "renumber":
        out = run(inspection.renumber, d, args.get("order"))
    elif action == "balloons":
        out = run(inspection.balloons, d)
    elif action == "form":
        out = run(inspection.set_form, d, args)
    elif action == "results":
        if not args.get("file"):
            raise CommandError("Give file, the results table.")
        out = run(inspection.import_results, d, args["file"], who, ctx.runner)
    else:
        raise CommandError("action is collect, add, edit, remove, renumber, balloons, form or results.")
    ctx.say("INSPECTION %s: done." % action)
    return out


@command("inspectionexport", group=GROUP, label="Export Inspection Report", description="Write the first-article style inspection report as an HTML or CSV file.", menu="")
def export_cmd(ctx):
    t = yield ctx.text("Enter the output file name (.html or .csv)")
    if t.kind != "text" or not t.value:
        return
    return export_run(ctx, {"file": t.value})


def export_run(ctx, args):
    path = args.get("file") or args.get("path")
    if not path:
        raise CommandError("Give file, the output file name.")
    out = run(inspection.export, ctx.doc, path, args.get("kind") or "")
    ctx.say("INSPECTIONEXPORT: wrote %s (%d rows)." % (out["path"], out["rows"]))
    return out


@executes("inspectionexport")
def export_exec(ctx, args):
    return export_run(ctx, args)


@command("mbdview", group=GROUP, label="MBD View", description="Save a named view that shows chosen PMI items: add, edit, remove, assign.", menu="")
def mbd_cmd(ctx):
    ctx.say("MBDVIEW: pass an action (add, edit, remove, assign) programmatically.")
    yield from ()


@executes("mbdview")
def mbd_exec(ctx, args):
    action = str(args.get("action") or "")
    d = ctx.doc.drawing
    if action == "add":
        out = run(mbd.add_view, d, args)
    elif action == "edit":
        out = run(mbd.edit_view, d, args.get("view"), args.get("changes") or {})
    elif action == "remove":
        out = run(mbd.remove_view, d, args.get("view"))
    elif action == "assign":
        out = run(mbd.assign, d, args.get("view"), str(args.get("rule") or "facing"))
    else:
        raise CommandError("action is add, edit, remove or assign.")
    ctx.say("MBDVIEW %s: done." % action)
    return out
