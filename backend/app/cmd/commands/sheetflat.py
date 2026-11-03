from app.cmd import barred
from app.cmd.context import CommandError
from app.cmd.registry import COMMANDS, command, executes
from app.sheetmetal import bend, flat, flatdxf
from app.solid.work import SolidError

FAILURES = (flat.FlatError, flatdxf.FlatDxfError, bend.BendError, SolidError, ValueError, KeyError)


def run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except FAILURES as err:
        raise CommandError(str(err.args[0]) if isinstance(err, KeyError) and err.args else str(err))


def toggle(d, args):
    changes = {}
    for key in ("on", "flip", "align", "fixed_face", "rule"):
        if key in args and args[key] is not None:
            changes[key] = args[key]
    if args.get("clear_fixed"):
        changes["fixed_face"] = None
    st = flat.set_state(d, **changes)
    out = {"state": st}
    if st["on"]:
        data = flat.compute(d)
        out["bends"] = len(data["bends"])
        out["length"] = data["length"]
        out["width"] = data["width"]
        out["warnings"] = data["warnings"]
    return out


@command("flatpattern", aliases=("flat", "unfold"), group="solids", label="Flat Pattern", description="Show or hide the flat pattern of a sheet metal part.", menu="Insert > Sheet Metal > Flat Pattern")
def flatpattern_cmd(ctx):
    k = yield ctx.keyword("Flat pattern [On/Off/Flip]", ["On", "Off", "Flip"], "On")
    word = (k.value if k.kind == "keyword" else "On").lower()
    args = {"on": word != "off"}
    if word == "flip":
        args["flip"] = not flat.state(ctx.d)["flip"]
    out = run(toggle, ctx.d, args)
    if out["state"]["on"]:
        ctx.say("FLATPATTERN: %d bends, blank %.4g by %.4g mm." % (out["bends"], out["length"], out["width"]))
    else:
        ctx.say("FLATPATTERN: folded view restored.")
    return out


@executes("flatpattern")
def flatpattern_exec(ctx, args):
    return run(toggle, ctx.d, args)


@command("flatexport", aliases=("flatdxf",), group="solids", label="Export Flat Pattern", description="Write the flat pattern of a sheet metal part to a DXF file.", menu="File > Export > Flat Pattern", undoable=False)
def flatexport_cmd(ctx):
    k = yield ctx.keyword("Profile [Bending/Cutting]", ["Bending", "Cutting"], "Bending")
    profile = (k.value if k.kind == "keyword" else "Bending").lower()
    t = yield ctx.text("Enter the flat pattern DXF file name")
    if t.kind != "text":
        return
    refused = barred.args_refusal(ctx.runner, COMMANDS["flatexport"], {"path": str(t.value)})
    if refused:
        raise CommandError(refused)
    res = run(lambda: flatdxf.export(flat.compute(ctx.d), str(t.value), profile))
    ctx.say("FLATEXPORT: wrote %s (%s)." % (res["path"], profile))
    return res


@executes("flatexport")
def flatexport_exec(ctx, args):
    path = args.get("path")
    if not path:
        raise CommandError("Give path.")
    handle = args.get("handle")
    return run(lambda: flatdxf.export(flat.compute(ctx.d, handle), str(path), str(args.get("profile") or "bending"), str(args.get("version") or "R2018"), bool(args.get("notes", False))))
