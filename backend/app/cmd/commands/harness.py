from app.cmd import barred
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.harness import service

GROUP = "harness"


def run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except service.ERRORS as err:
        raise CommandError(str(err))


@command("harness", aliases=("harnessedit",), group=GROUP, label="Harness", description="Build a wire harness: connectors with pins, clips, splices, segments routed through clips, wires and cables.", menu="")
def harness_cmd(ctx):
    ctx.say("HARNESS: pass an action (addnode, addsegment, addwire, addcable, edit, remove, settings, flatten, rotate, sheet, formboard) programmatically.")
    yield from ()


@executes("harness")
def harness_exec(ctx, args):
    action = str(args.get("action") or "")
    out = run(service.do, ctx.doc, action, args, barred.caller(ctx.runner))
    ctx.say("HARNESS %s: done." % action)
    return out


@command("harnessexport", group=GROUP, label="Export Harness Table", description="Write the wire list, from-to table, segment table or connector pin table as a CSV file.", menu="")
def export_cmd(ctx):
    k = yield ctx.keyword("Table", ["Wirelist", "Fromto", "Segments", "Connectors"], "Wirelist")
    if k.kind != "keyword":
        return
    t = yield ctx.text("Enter the output file name")
    if t.kind != "text" or not t.value:
        return
    return export_run(ctx, {"kind": str(k.value).lower(), "file": str(t.value)})


def export_run(ctx, args):
    path = args.get("file") or args.get("path")
    if not path:
        raise CommandError("Give file, the output file name.")
    out = run(service.export_csv, ctx.doc, args.get("kind") or "wirelist", path, args.get("sep") or ",")
    ctx.say("HARNESSEXPORT: wrote %s (%d rows)." % (out["path"], out["rows"]))
    return out


@executes("harnessexport")
def export_exec(ctx, args):
    return export_run(ctx, args)
