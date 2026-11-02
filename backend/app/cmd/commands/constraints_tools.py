from app.cmd import constraint_flow as F
from app.cmd.context import CommandError
from app.cmd.prompts import Prompt
from app.cmd.registry import command, executes
from app.param import infer, marks, ops, settings
from app.param import store as S
from app.param import units as U


def guard(ctx, fn, *a, **k):
    try:
        return fn(ctx.d, *a, **k)
    except (S.ParamError, ValueError) as err:
        F.fail(ctx, err)


def run_auto(ctx, handles, args):
    res = guard(ctx, infer.autoconstrain, handles, args.get("distance_tol"), args.get("angle_tol"), args.get("types"))
    ctx.say("%d constraint(s) applied to %d object(s)." % (res["applied"], res["objects"]))
    return res


@command("autoconstrain", group="constraints", label="Auto-constrain", description="Add the relations that nearly satisfied geometry already meets.", menu="Parametric > Auto Constrain")
def autoconstrain(ctx):
    r = yield ctx.select("Select objects")
    handles = F.selection_handles(ctx, r)
    if not handles:
        return
    run_auto(ctx, handles, {})


@executes("autoconstrain")
def autoconstrain_exec(ctx, args):
    handles = [int(h) for h in args.get("handles", [])] or list(ctx.doc.selection)
    return run_auto(ctx, handles, args)


def run_delete(ctx, handles, ids, dangling=False):
    if dangling:
        ids = list(ids) + [r["id"] for r in S.constraints(ctx.d) if r.get("dangling")]
    if handles:
        ids = list(ids) + [r["id"] for r in ops.constraints_of(ctx.d, handles)]
    ids = sorted(set(ids))
    if not ids:
        ctx.say("0 constraint(s) removed.")
        return {"removed": [], "count": 0}
    res = guard(ctx, ops.remove_constraints, ids)
    ctx.say("%d constraint(s) removed." % res["count"])
    return res


@command("delconstraint", group="constraints", label="Delete constraints", description="Remove the constraints from the selected objects.", menu="Parametric > Delete Constraints")
def delconstraint(ctx):
    r = yield ctx.select("Select objects")
    run_delete(ctx, F.selection_handles(ctx, r), [])


@executes("delconstraint")
def delconstraint_exec(ctx, args):
    handles = [int(h) for h in args.get("handles", [])]
    ids = [int(i) for i in args.get("ids", [])]
    if not handles and not ids and not args.get("dangling"):
        handles = list(ctx.doc.selection)
    return run_delete(ctx, handles, ids, bool(args.get("dangling")))


def list_lines(ctx):
    rows = ops.listing(ctx.d)["parameters"]
    if not rows:
        ctx.say("No parameters.")
    for r in rows:
        shown = r["shown"]
        ctx.say("%s = %s (%s)" % (r["name"], r["expr"] or "0", shown))
    return rows


def param_action(ctx, args):
    act = str(args.get("action") or "list").lower()
    d = ctx.d
    if act == "list":
        return {"parameters": ops.listing(d)}
    if act == "set":
        res = guard(ctx, ops.set_parameter, str(args.get("name") or ""), args.get("expr", ""), args.get("unit"), args.get("comment"))
        ctx.say("%s = %s" % (res["name"], U.format_value(res["value"], 4)))
        return res
    if act == "delete":
        res = guard(ctx, ops.delete_parameter, str(args.get("name") or ""))
        ctx.say("%s deleted." % res["name"])
        return res
    if act == "rename":
        res = guard(ctx, ops.rename_parameter, str(args.get("name") or ""), str(args.get("new") or ""))
        ctx.say("%s renamed to %s." % (res["old"], res["new"]))
        return res
    if act == "driving":
        return guard(ctx, ops.set_driving, str(args.get("name") or ""), bool(args.get("driving", True)))
    raise CommandError("Unknown parameters action.")


@command("parameters", aliases=("par",), group="constraints", label="Parameters", description="List, set, rename and delete parameters.", menu="Parametric > Parameters Manager")
def parameters(ctx):
    r = yield ctx.keyword("Enter an option", ["List", "Set", "Delete", "Rename"], default="List")
    if r.kind not in ("keyword", "text"):
        return
    act = str(r.value).lower()
    if act == "list":
        list_lines(ctx)
        return
    n = yield ctx.text("Enter parameter name")
    if n.kind != "text":
        return
    if act == "set":
        e = yield Prompt("Enter value or expression", ("text",), [], None, "", free_text=True)
        if e.kind != "text":
            return
        param_action(ctx, {"action": "set", "name": n.value, "expr": e.value})
    elif act == "delete":
        param_action(ctx, {"action": "delete", "name": n.value})
    else:
        e = yield ctx.text("Enter new name")
        if e.kind != "text":
            return
        param_action(ctx, {"action": "rename", "name": n.value, "new": e.value})


@executes("parameters")
def parameters_exec(ctx, args):
    return param_action(ctx, args)


@command("parametersclose", group="constraints", label="Close Parameters Manager", description="Close the Parameters Manager window.", menu="", undoable=False, repeatable=False)
def parametersclose(ctx):
    ctx.say("Parameters Manager closed.")
    return
    yield


@executes("parametersclose")
def parametersclose_exec(ctx, args):
    return {"closed": True}


def bar_action(ctx, which, args):
    act = str(args.get("action") or "data").lower()
    d = ctx.d
    handles = [int(h) for h in args.get("handles", [])]
    if act == "data":
        data = marks.compute(ctx.doc)
        return {"glyphs": {str(h): v for h, v in data["glyphs"].items()}, "dims": {str(h): v for h, v in data["dims"].items()}, "settings": S.settings(d)}
    if act in ("show", "hide"):
        if not handles:
            handles = list(ctx.doc.selection)
        cfg = guard(ctx, settings.show_hide, which, handles, act == "show")
    elif act in ("showall", "hideall"):
        cfg = guard(ctx, settings.show_all, which, act == "showall")
    else:
        raise CommandError("Unknown option.")
    ctx.say("%s %s." % ("Constraint bars" if which == "bars" else "Dynamic dimensions", act))
    return {"settings": cfg}


def make_bar(name, aliases, which, label):
    @command(name, aliases=aliases, group="constraints", label=label, description="Show or hide %s." % label.lower(), menu="Parametric > %s" % label)
    def run(ctx):
        r = yield ctx.keyword("Enter an option", ["Show", "Hide", "ShowAll", "HideAll"], default="ShowAll")
        if r.kind not in ("keyword", "text"):
            return
        act = str(r.value).lower()
        if act in ("show", "hide"):
            s = yield ctx.select("Select objects")
            bar_action(ctx, which, {"action": act, "handles": F.selection_handles(ctx, s)})
        else:
            bar_action(ctx, which, {"action": act})

    executes(name)(lambda ctx, args: bar_action(ctx, which, args))


make_bar("constraintbar", (), "bars", "Constraint bars")
make_bar("dcdisplay", (), "dims", "Dynamic dimensions")


def settings_action(ctx, args):
    changes = {k: v for k, v in args.items() if k in ("infer", "distance_tol", "angle_tol", "auto_types", "bars", "dims", "bar_transparency")}
    if changes:
        cfg = guard(ctx, settings.update, changes)
        if "infer" in changes:
            ctx.setvar("CONSTRAINTINFER", int(cfg["infer"]))
        ctx.say("Constraint settings updated.")
    else:
        cfg = S.settings(ctx.d)
        cfg["infer"] = int(ctx.var("CONSTRAINTINFER"))
    return {"settings": cfg}


@command("constraintsettings", aliases=("csettings",), group="constraints", label="Constraint settings", description="Tolerances, inference, bar and dimension display.", menu="Parametric > Constraint Settings")
def constraintsettings(ctx):
    r = yield ctx.keyword("Enter a setting", ["Infer", "Distance", "Angle", "Types", "Bars", "Dimensions", "Transparency", "Done"], default="Done")
    while r.kind in ("keyword", "text") and str(r.value) != "Done":
        key = str(r.value)
        if key == "Infer":
            v = yield ctx.number("Enter 1 to infer constraints while drawing", integer=True, minimum=0, maximum=1, default=int(ctx.var("CONSTRAINTINFER")))
            if v.kind == "number":
                settings_action(ctx, {"infer": v.value})
        elif key in ("Distance", "Angle"):
            v = yield ctx.number("Enter %s tolerance" % key.lower(), positive=True, default=S.settings(ctx.d)["distance_tol" if key == "Distance" else "angle_tol"])
            if v.kind == "number":
                settings_action(ctx, {"distance_tol" if key == "Distance" else "angle_tol": v.value})
        elif key == "Types":
            v = yield ctx.text("Enter types separated by commas", default=",".join(S.settings(ctx.d)["auto_types"]))
            if v.kind == "text":
                settings_action(ctx, {"auto_types": [t.strip() for t in str(v.value).split(",") if t.strip()]})
        elif key in ("Bars", "Dimensions"):
            v = yield ctx.keyword("Show %s for all objects?" % ("constraint bars" if key == "Bars" else "dynamic dimensions"), ["all", "none"], default="all")
            if v.kind == "keyword":
                settings_action(ctx, {"bars" if key == "Bars" else "dims": v.value})
        elif key == "Transparency":
            v = yield ctx.number("Enter bar transparency percent", integer=True, minimum=0, maximum=90, default=S.settings(ctx.d)["bar_transparency"])
            if v.kind == "number":
                settings_action(ctx, {"bar_transparency": v.value})
        r = yield ctx.keyword("Enter a setting", ["Infer", "Distance", "Angle", "Types", "Bars", "Dimensions", "Transparency", "Done"], default="Done")


@executes("constraintsettings")
def constraintsettings_exec(ctx, args):
    return settings_action(ctx, args)


@command("constraintinfer", group="constraints", label="Infer constraints", description="Turn constraint inference while drawing on or off.", menu="", undoable=False)
def constraintinfer(ctx):
    cur = int(ctx.var("CONSTRAINTINFER"))
    v = yield ctx.number("Enter new value for CONSTRAINTINFER", integer=True, minimum=0, maximum=1, default=cur)
    if v.kind != "number":
        return
    ctx.setvar("CONSTRAINTINFER", int(v.value))
    ctx.say("CONSTRAINTINFER = %d" % int(v.value))


@executes("constraintinfer")
def constraintinfer_exec(ctx, args):
    if "value" in args:
        v = int(args["value"])
        if v not in (0, 1):
            raise CommandError("Requires an integer between 0 and 1.")
        ctx.setvar("CONSTRAINTINFER", v)
    return {"value": int(ctx.var("CONSTRAINTINFER"))}


@command("constraintstatus", aliases=("dofstatus",), group="constraints", label="Constraint status", description="Degrees of freedom and defined state.", menu="Parametric > Inspect Constraints", undoable=False, repeatable=False)
def constraintstatus(ctx):
    res = status_action(ctx, {"handles": list(ctx.doc.selection)})
    ctx.say("Degrees of freedom: %d, %s." % (res["dof"], res["status"]))
    return
    yield


def status_action(ctx, args):
    handles = [int(h) for h in args.get("handles", [])]
    return guard(ctx, ops.status, args.get("sketch") or None, handles or None)


@executes("constraintstatus")
def constraintstatus_exec(ctx, args):
    return status_action(ctx, args)
