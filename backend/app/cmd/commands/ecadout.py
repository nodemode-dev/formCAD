from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.ecadout import files, interop, link
from app.ecadout import view as V
from app.pcb.store import PcbRecordError
from app.solid.work import SolidError

GROUP = "solids"
ERRORS = (V.OutputError, PcbRecordError, SolidError, interop.kicad.KicadError)


def run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ERRORS as err:
        raise CommandError(str(err))


def need_out(args):
    if not args.get("out"):
        raise CommandError("Give out, the file or folder to write.")
    return str(args["out"])


@command("gerberexport", group=GROUP, label="Export Fabrication Files", description="Write the Gerber layers and the drill files of the board to a folder or a zip file.", menu="Electronics > Export Fabrication Files", undoable=False)
def gerberexport(ctx):
    f = yield ctx.text("Enter the folder or zip file name to write")
    if f.kind != "text":
        return
    res = run(files.export_gerber, ctx.doc, f.value.strip(), f.value.strip().lower().endswith(".zip"))
    ctx.say("Wrote %d files: %d layers and %d drill files." % (len(res["files"]), len(res["layers"]), len(res["drills"])))


@executes("gerberexport")
def gerberexport_exec(ctx, args):
    return run(files.export_gerber, ctx.doc, need_out(args), bool(args.get("zip")), args.get("options"))


@command("drillexport", group=GROUP, label="Export Drill Files", description="Write the Excellon drill files of the board, one per plating and layer span.", menu="Electronics > Export Drill Files", undoable=False)
def drillexport(ctx):
    f = yield ctx.text("Enter the folder or file name to write")
    if f.kind != "text":
        return
    res = run(files.export_drill, ctx.doc, f.value.strip())
    ctx.say("Wrote %d drill files." % len(res["drills"]))


@executes("drillexport")
def drillexport_exec(ctx, args):
    return run(files.export_drill, ctx.doc, need_out(args), args.get("options"))


@command("idfexport", group=GROUP, label="Export Board Exchange File", description="Write the board outline, holes and component placement as an IDF 3.0 board file and library file.", menu="Electronics > Export IDF", undoable=False)
def idfexport(ctx):
    f = yield ctx.text("Enter the folder or file name to write")
    if f.kind != "text":
        return
    res = run(files.export_idf, ctx.doc, f.value.strip())
    ctx.say("Wrote %s and %s." % (res["board"], res["library"]))


@executes("idfexport")
def idfexport_exec(ctx, args):
    return run(files.export_idf, ctx.doc, need_out(args), args.get("options"))


@command("boardstep", group=GROUP, label="Export Board Solid", description="Write the 3D board body and its component bodies to a solid model file.", menu="Electronics > Export Board Solid", undoable=False)
def boardstep(ctx):
    f = yield ctx.text("Enter the name of the solid model file to write")
    if f.kind != "text":
        return
    res = run(files.export_step, ctx.doc, f.value.strip())
    ctx.say("Wrote %s." % res["file"])


@executes("boardstep")
def boardstep_exec(ctx, args):
    return run(files.export_step, ctx.doc, need_out(args), args.get("options"))


@command("ecadsync", group=GROUP, label="Sync Board Outline", description="Pull the board outline and mounting holes from the linked enclosure part face.", menu="Electronics > Sync Outline")
def ecadsync(ctx):
    res = run(link.sync_from_part, ctx.doc, None, False)
    ctx.say("Outline synced: %d points, %d cutouts, %d holes." % (res["outline_points"], res["cutouts"], res["holes"]))


@executes("ecadsync")
def ecadsync_exec(ctx, args):
    return run(link.sync_from_part, ctx.doc, args.get("ref"), False)


@command("ecadpush", group=GROUP, label="Send Outline To Part", description="Write the board outline into a sketch of the linked enclosure part.", menu="Electronics > Send Outline To Part", undoable=False)
def ecadpush(ctx):
    res = run(link.push_to_part, ctx.doc, (files.link_header(ctx.d).get("outline_ref") or {}).get("doc") or "")
    ctx.say("Sketch %s %s with %d loops." % (res["sketch"], res["action"], res["loops"]))


@executes("ecadpush")
def ecadpush_exec(ctx, args):
    target = args.get("doc") or (files.link_header(ctx.d).get("outline_ref") or {}).get("doc")
    if not target:
        raise CommandError("Give doc, the part document.")
    return run(link.push_to_part, ctx.doc, str(target), float(args.get("plane_z", 0.0)))
