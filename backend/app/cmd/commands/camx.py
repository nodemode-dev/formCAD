from app.cam.limits import CamError
from app.cmd import barred
from app.cmd.context import CommandError
from app.cmd.registry import COMMANDS, command, executes
from app.core import outputs
from app.cutting import records, service
from app.cutting.shapes import CutError

FAILURES = (CamError, CutError, outputs.OutputRefused, ValueError, KeyError)


def run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except FAILURES as err:
        raise CommandError(str(err.args[0]) if isinstance(err, KeyError) and err.args else str(err))


def nest_now(ctx, args):
    parts = service.build_parts(ctx.d, args)
    res = service.run_nest(parts, args, service.limits_agent())
    rec = records.put_nest(ctx.d, args.get("id"), service.nest_record(parts, args, res))
    return service.summary(rec)


@command("camprocess", group="solids", label="Cutting Process", description="Add a laser, plasma, waterjet or router cutting process record.", menu="Manufacture > Cutting Process")
def camprocess_cmd(ctx):
    k = yield ctx.keyword("Process [laser/plasma/waterjet/router]", ["laser", "plasma", "waterjet", "router"], "laser")
    if k.kind != "keyword":
        return
    rec = run(records.add_process, ctx.d, {"kind": str(k.value).lower()})
    ctx.say("CAMPROCESS: process %s added, kerf %g mm." % (rec["id"], rec["kerf"]))
    return {"id": rec["id"]}


@executes("camprocess")
def camprocess_exec(ctx, args):
    rec = run(records.add_process, ctx.d, dict(args))
    return {"id": rec["id"], "kerf": rec["kerf"]}


@command("camnest", group="solids", label="Nest Parts", description="Nest the flat patterns and closed outlines of the drawing onto sheets.", menu="Manufacture > Nest Parts")
def camnest_cmd(ctx):
    w = yield ctx.number("Sheet width in mm")
    h = yield ctx.number("Sheet height in mm")
    if w.kind != "number" or h.kind != "number":
        return
    args = {"from_flat": {"qty": 1}, "from_outlines": {"qty": 1}, "sheets": [{"width": float(w.value), "height": float(h.value)}], "kerf": 1.5, "clearance": 2.0, "seconds": 10.0, "restarts": 3}
    out = run(nest_now, ctx, args)
    ctx.say("CAMNEST: %d sheets, utilisation %.1f percent." % (out["sheet_count"], out["utilization"] * 100))
    return out


@executes("camnest")
def camnest_exec(ctx, args):
    return run(nest_now, ctx, dict(args))


@command("camnestexport", group="solids", label="Export Nest Cutting Code", description="Write the cutting code of a nest to files, one per sheet.", menu="Manufacture > Export Nest Code", undoable=False)
def camnestexport_cmd(ctx):
    t = yield ctx.text("Enter the cutting code file name")
    if t.kind != "text":
        return
    refused = barred.args_refusal(ctx.runner, COMMANDS["camnestexport"], {"path": str(t.value)})
    if refused:
        raise CommandError(refused)
    res = run(service.export, ctx.d, "FORMCAD", "N1", "P1", "cut_grbl_laser", str(t.value))
    ctx.say("CAMNESTEXPORT: wrote %d files." % len(res["files"]))
    return res


@executes("camnestexport")
def camnestexport_exec(ctx, args):
    if not args.get("path"):
        raise CommandError("Give path, the file to write.")
    return run(service.export, ctx.d, "FORMCAD", str(args.get("nest") or "N1"), args.get("process") or "P1", str(args.get("post") or "cut_grbl_laser"), str(args["path"]), args.get("sheet"), str(args.get("order") or "part"), (0.0, 0.0), args.get("options"))
