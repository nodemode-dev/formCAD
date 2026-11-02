from app.cmd.registry import command, executes


@command("lispconsole", aliases=("vlide", "lispide"), group="macro", label="LISP Console", description="Open the LISP Console; without the interface it only says so.", menu="", undoable=False, repeatable=False)
def lisp_console(ctx):
    ctx.say("The LISP Console opens in the interface; type LISP at the prompt to evaluate an expression here.")
    yield from ()


@executes("lispconsole")
def lisp_console_exec(ctx, args):
    return {"panel": "lispconsole"}


@command("macrorecorder", aliases=("macros",), group="macro", label="Macro Recorder", description="Open the Macro Recorder; without the interface use MACRORECORD.", menu="", undoable=False, repeatable=False)
def macro_recorder(ctx):
    ctx.say("The Macro Recorder opens in the interface; MACRORECORD starts recording here.")
    yield from ()


@executes("macrorecorder")
def macro_recorder_exec(ctx, args):
    return {"panel": "macrorecorder"}
