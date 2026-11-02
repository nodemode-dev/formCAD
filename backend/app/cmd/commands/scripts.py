from app.cmd import script
from app.cmd.context import CommandError
from app.cmd.registry import command, executes


def begin(ctx, path, data=None, repeat=False, times=None):
    runner = ctx.runner
    try:
        if data is not None:
            name, lines = "inline script", script.split_lines(str(data))
        else:
            name, lines = script.read_file(path)
        sc = script.start(runner, name, lines, repeat, times)
    except script.ScriptError as err:
        raise CommandError(str(err))
    return {"script": sc.name, "lines": len(sc.lines)}


def ask(ctx):
    r = yield ctx.text("Enter name of script file")
    if r.kind != "text":
        return None
    return str(r.value).strip() or None


@command("script", aliases=("scr",), group="script", label="Run Script", description="Run a script file: each line is typed input.", menu="Tools > Run Script...", undoable=False, repeatable=False)
def script_cmd(ctx):
    if ctx.runner.script is not None:
        raise CommandError(script.NESTED)
    path = yield from ask(ctx)
    if path:
        begin(ctx, path)


@executes("script")
def script_exec(ctx, args):
    times = args.get("times")
    return begin(ctx, args.get("path", ""), args.get("data"), False, int(times) if times else None)


@command("rscript", group="script", label="Repeat Script", description="Run a script file again and again until it is cancelled.", menu="Tools > Run Script > Repeat", undoable=False, repeatable=False)
def rscript_cmd(ctx):
    if ctx.runner.script is not None:
        raise CommandError(script.NESTED)
    path = yield from ask(ctx)
    if path:
        begin(ctx, path, None, True)


@executes("rscript")
def rscript_exec(ctx, args):
    times = args.get("times")
    return begin(ctx, args.get("path", ""), args.get("data"), True, int(times) if times else None)


@command("delay", group="script", label="Delay", description="Pause the running script for a number of milliseconds.", transparent=True, undoable=False, repeatable=False)
def delay_cmd(ctx):
    r = yield ctx.number("Enter delay time in milliseconds", integer=True, minimum=1, maximum=32767)
    if r.kind != "number":
        return
    if not script.delay(ctx.runner, int(r.value)):
        ctx.say("DELAY only pauses a running script.")


@executes("delay")
def delay_exec(ctx, args):
    ms = int(args.get("ms", 0))
    if ms < 1 or ms > 32767:
        raise CommandError("The delay is 1 to 32767 milliseconds.")
    return {"waiting": script.delay(ctx.runner, ms)}


@command("resume", group="script", label="Resume Script", description="Continue a script that was paused or stopped by an error.", undoable=False, repeatable=False)
def resume_cmd(ctx):
    if not script.resume(ctx.runner):
        ctx.say("No script is paused.")
    return None


@executes("resume")
def resume_exec(ctx, args):
    return {"resumed": script.resume(ctx.runner)}
