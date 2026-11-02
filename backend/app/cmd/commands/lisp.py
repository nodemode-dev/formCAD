from app.cmd.context import CommandError
from app.cmd.registry import command, executes


def _lisp():
    from app import lisp

    return lisp


def _report(runner, res: dict) -> None:
    if res.get("error"):
        runner._fail(res["error"])
        return
    runner.log("Loaded %s." % res.get("file", ""))
    if res.get("commands"):
        runner.log("Commands defined: %s" % ", ".join(c.upper() for c in res["commands"]))


@command("appload", aliases=("ap",), group="lisp", label="Load Application", description="Load a LISP file into the drawing and remember it by name for LOAD.", menu="Tools > Load Application...", undoable=False, repeatable=False)
def appload_cmd(ctx):
    r = yield ctx.text("Enter name of LISP file to load")
    if r.kind != "text":
        return None
    path = str(r.value).strip()
    if not path:
        return None
    runner = ctx.runner
    doc = ctx.doc

    def go():
        _report(runner, _lisp().appload(doc, path))

    runner.later.append(go)
    return None


@executes("appload")
def appload_exec(ctx, args):
    paths = args.get("paths")
    if paths is None:
        paths = [args.get("path") or ""]
    if args.get("text") is not None:
        res = _lisp().evaluate(ctx.doc, str(args["text"]))
        return {"file": "", "loaded": not res.error, "commands": _lisp().get_session(ctx.doc).commands(),"value": res.value, "lines": res.lines, "error": res.error}
    out = [_lisp().appload(ctx.doc, str(p)) for p in paths]
    bad = next((o for o in out if o["error"]), None)
    if bad is not None:
        raise CommandError(bad["error"])
    return out[0] if len(out) == 1 and "paths" not in args else {"files": out}


@command("lisp", group="lisp", label="LISP Expression", description="Evaluate a LISP expression typed at the prompt.", menu="", undoable=False, repeatable=False)
def lisp_cmd(ctx):
    r = yield ctx.text("Enter LISP expression")
    if r.kind != "text":
        return None
    text = str(r.value).strip()
    runner = ctx.runner
    if not text:
        return None
    from app.lisp import hooks

    def go():
        hooks.run_line(runner, text if text[0] in "(!" else "(" + text + ")")

    runner.later.append(go)
    return None


@executes("lisp")
def lisp_exec(ctx, args):
    lisp = _lisp()
    action = args.get("action")
    if action == "loaded":
        return {"loaded": list(lisp.get_session(ctx.doc).loaded)}
    if action == "commands":
        return {"commands": lisp.get_session(ctx.doc).commands()}
    code = args.get("code")
    if not isinstance(code, str):
        raise CommandError("code must be a string.")
    answers = args.get("answers")
    if answers is not None and not isinstance(answers, list):
        raise CommandError("answers must be a list.")
    res = lisp.evaluate(ctx.doc, code, answers)
    if res.error:
        ctx.runner.error = res.error
    return res.as_dict()
