from app.cmd import macro
from app.cmd.context import CommandError
from app.cmd.registry import command, executes


def guard(fn, *a):
    try:
        return fn(*a)
    except macro.MacroError as err:
        raise CommandError(str(err))


def do_record(ctx, name=""):
    rec = guard(macro.start, ctx.runner, name)
    ctx.say("Recording macro %s." % rec.name)
    return {"recording": rec.name}


def do_stop(ctx):
    rec = guard(macro.stop, ctx.runner)
    ctx.say("Macro %s recorded: %d steps." % (rec.name, len(rec.events)))
    return {"name": rec.name, "steps": len(rec.events), "lines": [e["line"] for e in rec.events]}


def do_play(ctx, source=""):
    name = guard(macro.play, ctx.runner, source)
    ctx.say("Playing macro %s." % name)
    return {"playing": name}


def do_save(ctx, path, fmt=""):
    full = guard(macro.save, ctx.runner, path, fmt)
    ctx.say("Macro saved to %s." % full)
    return {"path": full}


@command("macrorecord", aliases=("recordmacro",), group="macro", label="Record Macro", description="Start recording typed input and canvas picks.", menu="Tools > Macro > Record", undoable=False, repeatable=False)
def record_cmd(ctx):
    r = yield ctx.text("Name for the macro", "macro")
    if r.kind in ("text", "enter"):
        do_record(ctx, str(r.value) if r.kind == "text" else "macro")


@executes("macrorecord")
def record_exec(ctx, args):
    return do_record(ctx, str(args.get("name", "") or ""))


@command("macrostop", group="macro", label="Stop Recording", description="Stop recording the macro.", menu="Tools > Macro > Stop", undoable=False, repeatable=False)
def stop_cmd(ctx):
    do_stop(ctx)


@executes("macrostop")
def stop_exec(ctx, args):
    return do_stop(ctx)


@command("macroplay", group="macro", label="Play Macro", description="Play the last recorded macro or a macro file.", menu="Tools > Macro > Play", undoable=False, repeatable=False)
def play_cmd(ctx):
    r = yield ctx.text("Macro file or Last", "Last")
    if r.kind in ("text", "enter"):
        do_play(ctx, str(r.value) if r.kind == "text" else "last")


@executes("macroplay")
def play_exec(ctx, args):
    return do_play(ctx, str(args.get("path", "") or "last"))


@command("macrosave", group="macro", label="Save Macro", description="Save the recorded macro as a .scr script or a .py Python macro.", menu="Tools > Macro > Save...", undoable=False, repeatable=False)
def save_cmd(ctx):
    r = yield ctx.text("File name for the macro (.scr or .py)")
    if r.kind == "text":
        do_save(ctx, str(r.value))


@executes("macrosave")
def save_exec(ctx, args):
    return do_save(ctx, str(args.get("path", "")), str(args.get("format", "") or ""))
