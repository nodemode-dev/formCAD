import json

from app.cam.limits import CamError
from app.cmd import barred
from app.cmd.context import CommandError
from app.cmd.registry import COMMANDS, command, executes
from app.core import outputs
from app.cutting import records, service
from app.cutting.shapes import CutError
from app.probing import cycles as probe_cycles
from app.turning import millturn
from app.turning import profile as turn_profile

FAILURES = (CamError, CutError, outputs.OutputRefused, ValueError, KeyError, TypeError)


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


def turn_profile_now(args):
    spec = args.get("profile")
    if isinstance(spec, str):
        spec = json.loads(spec)
    if not isinstance(spec, dict):
        raise CommandError("Give profile, an object with a pts list of z and d points.")
    prof = run(turn_profile.build, spec)
    pts = prof["pts"]
    return {"points": len(pts), "monotonic": turn_profile.check_direction(prof), "max_diameter": 2 * max(r for _, r in pts), "length": pts[0][0] - pts[-1][0]}


@command("camturnprofile", group="solids", label="Check Turning Profile", description="Check a turning profile given as z and diameter points and report its length and largest diameter.", menu="Manufacture > Check Turning Profile", undoable=False)
def camturnprofile_cmd(ctx):
    t = yield ctx.text("Enter the profile as text, for example {\"units\": \"diameter\", \"pts\": [{\"z\": 0, \"d\": 20}, {\"z\": -30, \"d\": 20}]}")
    if t.kind != "text":
        return
    try:
        out = turn_profile_now({"profile": str(t.value)})
    except json.JSONDecodeError:
        raise CommandError("The profile text is not valid JSON.")
    ctx.say("CAMTURNPROFILE: %d points, length %g mm, largest diameter %g mm." % (out["points"], out["length"], out["max_diameter"]))
    return out


@executes("camturnprofile")
def camturnprofile_exec(ctx, args):
    try:
        return turn_profile_now(dict(args))
    except json.JSONDecodeError:
        raise CommandError("The profile text is not valid JSON.")


def probe_now(args):
    kind = str(args.get("kind") or "")
    built = run(probe_cycles.build, kind, args.get("params") or {})
    return {"kind": kind, "moves": len(built["moves"]), "outputs": sorted(built["outputs"])}


@command("camprobe", group="solids", label="Probing Cycle", description="Build a probing cycle and report its moves and the parameters it stores.", menu="Manufacture > Probing Cycle", undoable=False)
def camprobe_cmd(ctx):
    k = yield ctx.keyword("Cycle [surface/edge/bore/boss/width/corner/skew]", list(probe_cycles.KINDS), "surface")
    if k.kind != "keyword":
        return
    out = probe_now({"kind": str(k.value).lower()})
    ctx.say("CAMPROBE: %s cycle, %d moves." % (out["kind"], out["moves"]))
    return out


@executes("camprobe")
def camprobe_exec(ctx, args):
    return probe_now(dict(args))


def machine_now(ctx, args):
    raw = dict(args)
    mid = raw.pop("id", None)
    rec = run(millturn.put_machine, ctx.d, None if mid in (None, "", "new") else str(mid), raw)
    return {"id": rec["id"], "name": rec["label"]}


@command("cammachine", group="solids", label="Mill-Turn Machine", description="Add a mill-turn machine record.", menu="Manufacture > Mill-Turn Machine")
def cammachine_cmd(ctx):
    t = yield ctx.text("Machine name", "Mill-turn")
    if t.kind != "text":
        return
    out = machine_now(ctx, {"name": str(t.value)})
    ctx.say("CAMMACHINE: machine %s added." % out["id"])
    return out


@executes("cammachine")
def cammachine_exec(ctx, args):
    return machine_now(ctx, args)
