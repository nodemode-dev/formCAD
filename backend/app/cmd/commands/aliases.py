from app.cmd import aliasfile
from app.cmd.context import CommandError
from app.cmd.registry import command, executes


def guard(fn, *a):
    try:
        return fn(*a)
    except aliasfile.AliasError as err:
        raise CommandError(str(err))


def report(ctx, res: dict) -> dict:
    ctx.say(res.get("message", ""))
    for w in res.get("warnings", []):
        ctx.say(w)
    return res


def do_list(ctx) -> dict:
    data = aliasfile.listing()
    if data["file"]:
        ctx.say("Alias file: %s" % data["file"])
    else:
        ctx.say("No command alias file is loaded.")
    for e in data["user"]:
        ctx.say("%s  %s" % (e["alias"].upper(), e["command"].upper()))
    ctx.say("%d user alias%s, %d built in." % (len(data["user"]), "" if len(data["user"]) == 1 else "es", len(data["builtin"])))
    return {"file": data["file"], "user": data["user"], "builtIn": len(data["builtin"])}


def run_action(ctx, action, args):
    a = action.lower()
    if a == "load":
        return report(ctx, guard(aliasfile.load, str(args.get("path", ""))))
    if a == "reinit":
        return report(ctx, guard(aliasfile.reinit))
    if a == "clear":
        return report(ctx, guard(aliasfile.clear))
    if a == "set":
        res = guard(aliasfile.set_one, str(args.get("alias", "")), str(args.get("command", "")))
        ctx.say("%s now starts %s." % (res["alias"].upper(), res["command"].upper()))
        return res
    if a == "remove":
        res = guard(aliasfile.remove_one, str(args.get("alias", "")))
        ctx.say("%s removed." % res["alias"].upper())
        return res
    if a == "save":
        full = guard(aliasfile.save, str(args.get("path", "")))
        ctx.say("Aliases saved to %s." % full)
        return {"path": full}
    if a == "list":
        return do_list(ctx)
    raise CommandError("Unknown alias action %s." % action)


@command("aliasedit", group="settings", label="Edit Command Aliases", description="Load, clear, set or remove command aliases.", menu="Tools > Customize > Edit Command Aliases...", undoable=False, repeatable=False)
def aliasedit_cmd(ctx):
    r = yield ctx.keyword("Alias editor option", ["Load", "Clear", "Set", "Remove", "List", "Save"], "List")
    if r.kind not in ("keyword", "enter"):
        return
    opt = r.value if r.kind == "keyword" else "List"
    args = {}
    if opt in ("Load", "Save"):
        t = yield ctx.text("Enter name of alias file")
        if t.kind != "text":
            return
        args["path"] = str(t.value).strip()
    elif opt == "Set":
        t = yield ctx.text("Enter alias")
        if t.kind != "text":
            return
        c = yield ctx.text("Enter command the alias starts")
        if c.kind != "text":
            return
        args = {"alias": str(t.value).strip(), "command": str(c.value).strip()}
    elif opt == "Remove":
        t = yield ctx.text("Enter alias to remove")
        if t.kind != "text":
            return
        args["alias"] = str(t.value).strip()
    run_action(ctx, opt, args)


@executes("aliasedit")
def aliasedit_exec(ctx, args):
    return run_action(ctx, str(args.get("action", "list")), args)


@command("reinit", group="settings", label="Reinitialize", description="Read the last loaded command alias file again.", undoable=False, repeatable=False)
def reinit_cmd(ctx):
    report(ctx, guard(aliasfile.reinit))


@executes("reinit")
def reinit_exec(ctx, args):
    return report(ctx, guard(aliasfile.reinit))
