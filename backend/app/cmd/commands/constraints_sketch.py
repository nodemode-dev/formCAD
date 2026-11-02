from app.cmd import constraint_flow as F
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.param import sketch as K
from app.param import store as S

ACTIONS = ("New", "List", "Add", "Remove", "Construction", "Delete", "Rename", "Status")


def next_name(d) -> str:
    n = 1
    while S.get_sketch(d, "Sketch%d" % n) is not None:
        n += 1
    return "Sketch%d" % n


def act(ctx, args):
    a = str(args.get("action") or "list").lower()
    d = ctx.d
    name = args.get("name")
    handles = [int(h) for h in args.get("handles", [])]
    if a in ("add", "remove", "construction", "delete", "rename", "status") and not name:
        raise CommandError("Name the sketch.")
    if a == "new":
        res = F.guard_call(ctx, K.create, name or next_name(d), args.get("plane", "XY"), handles or list(ctx.doc.selection), args.get("origin"))
        ctx.say("Sketch %s created: %s, %d degree(s) of freedom." % (res["name"], res["status"], res["dof"]))
        return res
    if a == "list":
        rows = K.listing(d)
        for r in rows:
            ctx.say("%s on %s: %d object(s), %s, %d degree(s) of freedom" % (r["name"], r["plane"], r["entities"], r["status"], r["dof"]))
        if not rows:
            ctx.say("No sketches.")
        return {"sketches": rows}
    if a == "add":
        return F.guard_call(ctx, K.add_entities, name, handles or list(ctx.doc.selection))
    if a == "remove":
        return F.guard_call(ctx, K.remove_entities, name, handles or list(ctx.doc.selection))
    if a == "construction":
        return F.guard_call(ctx, K.set_construction, name, handles or list(ctx.doc.selection), bool(args.get("flag", True)))
    if a == "delete":
        res = F.guard_call(ctx, K.delete, name)
        ctx.say("Sketch %s deleted with %d constraint(s)." % (name, res["constraints"]))
        return res
    if a == "rename":
        return F.guard_call(ctx, K.rename, name, str(args.get("new") or ""))
    if a == "status":
        res = F.guard_call(ctx, K.info, name)
        ctx.say("%s: %s, %d degree(s) of freedom." % (name, res["status"], res["dof"]))
        return res
    raise CommandError("Unknown sketch action.")


@command("sketch", group="constraints", label="Sketch", description="Create and manage parametric sketches.", menu="Parametric > Sketch")
def sketch(ctx):
    r = yield ctx.keyword("Enter a sketch option", list(ACTIONS), default="List")
    if r.kind not in ("keyword", "text"):
        return
    a = str(r.value).lower()
    if a == "list":
        act(ctx, {"action": "list"})
        return
    n = yield ctx.text("Enter sketch name", default=next_name(ctx.d) if a == "new" else None)
    if n.kind != "text":
        return
    args = {"action": a, "name": n.value}
    if a == "new":
        p = yield ctx.keyword("Enter sketch plane", ["XY", "XZ", "YZ"], default="XY")
        if p.kind != "keyword":
            return
        args["plane"] = p.value
    if a in ("new", "add", "remove", "construction"):
        s = yield ctx.select("Select objects")
        args["handles"] = F.selection_handles(ctx, s)
    if a == "construction":
        f = yield ctx.yesno("Make the objects construction geometry?", "Yes")
        args["flag"] = f.kind == "keyword" and f.value == "Yes"
    if a == "rename":
        e = yield ctx.text("Enter new name")
        if e.kind != "text":
            return
        args["new"] = e.value
    act(ctx, args)


@executes("sketch")
def sketch_exec(ctx, args):
    return act(ctx, args)


@command("sketchstatus", group="constraints", label="Sketch status", description="Defined state and remaining degrees of freedom of a sketch.", menu="Parametric > Sketch Status", undoable=False, repeatable=False)
def sketchstatus(ctx):
    n = yield ctx.text("Enter sketch name")
    if n.kind != "text":
        return
    act(ctx, {"action": "status", "name": n.value})


@executes("sketchstatus")
def sketchstatus_exec(ctx, args):
    return act(ctx, {"action": "status", "name": args.get("name")})
