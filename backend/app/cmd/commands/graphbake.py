from app.cmd.commands.graph import FAILURES, pick, run
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.graph import bake, model, session


@command("graphbake", aliases=("bakegraph",), group="tools", label="Bake Graph", description="Turn the previewed results of a graph into bodies, surfaces, curves and points of this document in one undoable step.", menu="Tools > Bake Graph", repeatable=False)
def graphbake_cmd(ctx):
    out = graphbake_exec(ctx, {})
    ctx.say(out["message"])
    return out


@executes("graphbake")
def graphbake_exec(ctx, args):
    rec = pick(ctx, args.get("graph") or args.get("name_of_graph"))
    sess = run(session.of, ctx.doc, rec["id"])
    if sess.busy():
        sess.wait(600.0)
    sess.request(0)
    if not sess.wait(600.0):
        raise CommandError("The graph did not finish solving in time.")
    options = dict(args.get("options") or {})
    for key in ("layer", "colour", "name", "drafting", "replace", "ports", "selected"):
        if args.get(key) is not None:
            options[key] = args[key]
    try:
        out = bake.bake(ctx.doc, sess.graph, {"options": options, "nodes": args.get("nodes")})
    except FAILURES as err:
        raise CommandError(err.message if isinstance(err, model.GraphRefused) else str(err))
    return out
