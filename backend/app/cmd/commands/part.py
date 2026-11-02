from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.param import store as S
from app.part import features_core, hook, rebuild, registry, store, tree
from app.part.registry import PartError
from app.solid.work import SolidError

FAILURES = (PartError, S.ParamError, SolidError, ValueError, KeyError)


def run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except FAILURES as err:
        raise CommandError(str(err.args[0]) if isinstance(err, KeyError) and err.args else str(err))


def find_feature(doc, ident):
    d = doc.drawing
    recs = store.records(d)
    key = str(ident or "").strip()
    if key in recs:
        return key
    hit = [r["id"] for r in recs.values() if r["label"].casefold() == key.casefold()]
    if len(hit) == 1:
        return hit[0]
    raise CommandError("There is no feature %s." % key)


def sketch_ref(doc, ident):
    fid = find_feature(doc, ident)
    rec = store.get(doc.drawing, fid)
    if rec["type"] != "sketch":
        raise CommandError("%s is not a sketch." % rec["label"])
    return {"sketch": {"id": fid}}


def brief(out):
    state = out.get("state") or {}
    text = "%s %s: %s" % (out.get("label", out.get("id", "")), state.get("status", ""), state.get("message", "") or "built")
    return {"id": out.get("id"), "message": text.strip(), "state": state}


def add_from(ctx, args, type_name, refs=None):
    params = dict(args.get("params") or {})
    for key in ("depth1", "depth2", "angle1", "angle2", "end1", "end2", "thin", "flip", "draft1", "draft2"):
        if key in args and key not in params:
            params[key] = args[key]
    out = run(tree.add_feature, ctx.doc, type_name, params, refs if refs is not None else args.get("refs"), args.get("label"), args.get("after"), bool(args.get("suppressed", False)))
    ctx.say(brief(out)["message"])
    return brief(out)


def sketch_feature(ctx, args, type_name):
    refs = dict(args.get("refs") or {})
    if "sketch" in args and "sketch" not in refs:
        refs.update(sketch_ref(ctx.doc, args["sketch"]))
    if "sketch" not in refs:
        raise CommandError("Give the sketch to use.")
    return add_from(ctx, args, type_name, refs)


@command("partsketch", group="solids", label="Part Sketch", description="Start a sketch feature on a plane and enter it.", menu="Draw > Modeling > Part Sketch")
def partsketch(ctx):
    name = yield ctx.word("Plane [XY/XZ/YZ]", ["XY", "XZ", "YZ"], "XY")
    plane = name.value if name.kind in ("keyword", "text") else "XY"
    out = run(tree.create_sketch, ctx.doc, None, str(plane).upper())
    run(tree.sketch_enter, ctx.doc, out["id"])
    ctx.say("Sketch %s started." % out["label"])


@executes("partsketch")
def partsketch_exec(ctx, args):
    out = run(tree.create_sketch, ctx.doc, args.get("name"), str(args.get("plane", "XY")).upper(), float(args.get("offset", 0.0)), args.get("face"), args.get("origin"), args.get("xdir"), args.get("after"), tuple(args.get("entities") or ()), args.get("source"))
    if args.get("enter", True):
        run(tree.sketch_enter, ctx.doc, out["id"])
    return {"id": out["id"], "message": "Sketch %s started." % out["label"]}


@command("partsketchdone", group="solids", label="Finish Part Sketch", description="Leave the sketch and return to the model.", menu="Draw > Modeling > Finish Part Sketch")
def partsketchdone(ctx):
    run(tree.sketch_exit, ctx.doc)
    ctx.say("Sketch closed.")


@executes("partsketchdone")
def partsketchdone_exec(ctx, args):
    return run(tree.sketch_exit, ctx.doc) or {"message": "Sketch closed."}


def ask_sketch_depth(ctx, label):
    sk = yield ctx.text("Sketch name", None)
    if sk.kind != "text":
        return None, None
    dist = yield ctx.distance(label, positive=True)
    if dist.kind != "value":
        return None, None
    return sk.value, dist.value


@command("featextrude", group="solids", label="Extrude Feature", description="Add a blind extrude feature from a sketch.", menu="Draw > Modeling > Extrude Feature")
def featextrude(ctx):
    sk, depth = yield from ask_sketch_depth(ctx, "Depth")
    if sk is None:
        return
    sketch_feature(ctx, {"sketch": sk, "depth1": depth}, "extrude")


@executes("featextrude")
def featextrude_exec(ctx, args):
    return sketch_feature(ctx, args, "extrude")


@command("featcut", group="solids", label="Extruded Cut", description="Add a cut-extrude feature from a sketch.", menu="Draw > Modeling > Extruded Cut")
def featcut(ctx):
    sk, depth = yield from ask_sketch_depth(ctx, "Depth")
    if sk is None:
        return
    sketch_feature(ctx, {"sketch": sk, "depth1": depth}, "extrude_cut")


@executes("featcut")
def featcut_exec(ctx, args):
    return sketch_feature(ctx, args, "extrude_cut")


@command("featrevolve", group="solids", label="Revolve Feature", description="Add a revolve feature from a sketch and its axis.", menu="Draw > Modeling > Revolve Feature")
def featrevolve(ctx):
    sk = yield ctx.text("Sketch name", None)
    if sk.kind != "text":
        return
    sketch_feature(ctx, {"sketch": sk.value}, "revolve")


@executes("featrevolve")
def featrevolve_exec(ctx, args):
    return sketch_feature(ctx, args, "revolve")


@command("featrevolvecut", group="solids", label="Revolved Cut", description="Add a revolve-cut feature from a sketch and its axis.", menu="Draw > Modeling > Revolved Cut")
def featrevolvecut(ctx):
    sk = yield ctx.text("Sketch name", None)
    if sk.kind != "text":
        return
    sketch_feature(ctx, {"sketch": sk.value}, "revolve_cut")


@executes("featrevolvecut")
def featrevolvecut_exec(ctx, args):
    return sketch_feature(ctx, args, "revolve_cut")


@command("featadd", group="solids", label="Add Feature", description="Add a feature of any registered type by name.", menu="Draw > Modeling > Add Feature")
def featadd(ctx):
    kinds = [t["type"] for t in registry.listing()]
    k = yield ctx.word("Feature type", kinds, None)
    if k.kind not in ("keyword", "text"):
        return
    add_from(ctx, {}, str(k.value))


@executes("featadd")
def featadd_exec(ctx, args):
    name = str(args.get("type") or "")
    if not name:
        raise CommandError("Give the feature type.")
    return add_from(ctx, args, name)


@command("features", aliases=("featurelist",), group="solids", label="Feature List", description="List the feature tree with each state.", menu="Tools > Inquiry > Feature List", undoable=False)
def features(ctx):
    out = run(tree.listing, ctx.doc)
    for f in out["features"]:
        ctx.say("%s  %s  %s  %s" % (f["id"], f["label"], f["type"], f["state"]["status"]))
    if not out["features"]:
        ctx.say("The part has no features.")


@executes("features")
def features_exec(ctx, args):
    return run(tree.listing, ctx.doc)


@command("featedit", group="solids", label="Edit Feature", description="Change one parameter of a feature.", menu="Modify > Edit Feature")
def featedit(ctx):
    fid = yield ctx.text("Feature id or name", None)
    if fid.kind != "text":
        return
    key = yield ctx.text("Parameter", None)
    if key.kind != "text":
        return
    val = yield ctx.number("Value")
    if val.kind != "value":
        return
    out = run(tree.edit_feature, ctx.doc, find_feature(ctx.doc, fid.value), None, {str(key.value): val.value})
    ctx.say(brief(out)["message"])


@executes("featedit")
def featedit_exec(ctx, args):
    fid = find_feature(ctx.doc, args.get("id", args.get("feature")))
    out = run(tree.edit_feature, ctx.doc, fid, args.get("label"), args.get("params"), args.get("refs"), args.get("suppressed"))
    return brief(out)


@command("featdelete", group="solids", label="Delete Feature", description="Delete a feature that no other feature uses.", menu="Modify > Delete Feature")
def featdelete(ctx):
    fid = yield ctx.text("Feature id or name", None)
    if fid.kind != "text":
        return
    run(tree.delete_feature, ctx.doc, find_feature(ctx.doc, fid.value))
    ctx.say("Feature deleted.")


@executes("featdelete")
def featdelete_exec(ctx, args):
    run(tree.delete_feature, ctx.doc, find_feature(ctx.doc, args.get("id", args.get("feature"))), bool(args.get("cascade", False)), bool(args.get("sketch", False)))
    return {"message": "Feature deleted."}


def suppress_cmd(ctx, args, flag):
    out = run(tree.set_suppressed, ctx.doc, find_feature(ctx.doc, args.get("id", args.get("feature"))), flag)
    ctx.say(brief(out)["message"])
    return brief(out)


@command("featsuppress", group="solids", label="Suppress Feature", description="Hide a feature from the rebuild; later features that need it fail.", menu="Modify > Suppress Feature")
def featsuppress(ctx):
    fid = yield ctx.text("Feature id or name", None)
    if fid.kind == "text":
        suppress_cmd(ctx, {"id": fid.value}, True)


@executes("featsuppress")
def featsuppress_exec(ctx, args):
    return suppress_cmd(ctx, args, True)


@command("featunsuppress", group="solids", label="Unsuppress Feature", description="Bring a suppressed feature back into the rebuild.", menu="Modify > Unsuppress Feature")
def featunsuppress(ctx):
    fid = yield ctx.text("Feature id or name", None)
    if fid.kind == "text":
        suppress_cmd(ctx, {"id": fid.value}, False)


@executes("featunsuppress")
def featunsuppress_exec(ctx, args):
    return suppress_cmd(ctx, args, False)


@command("featrollback", group="solids", label="Rollback", description="Move the rollback bar to just after a feature; blank returns to the end.", menu="Modify > Rollback")
def featrollback(ctx):
    fid = yield ctx.text("Roll back to feature (blank for the end)", "")
    to = find_feature(ctx.doc, fid.value) if fid.kind == "text" and str(fid.value).strip() else None
    run(tree.set_rollback, ctx.doc, to)
    ctx.say("Rolled back to %s." % to if to else "Rollback bar at the end.")


@executes("featrollback")
def featrollback_exec(ctx, args):
    to = args.get("to", args.get("id"))
    run(tree.set_rollback, ctx.doc, find_feature(ctx.doc, to) if to else None)
    return {"message": "Rollback set."}


@command("featrebuild", aliases=("rebuildpart",), group="solids", label="Rebuild Part", description="Rebuild from the first changed feature.", menu="Modify > Rebuild Part")
def featrebuild(ctx):
    rep = run(rebuild.rebuild, ctx.doc, False, None)
    ctx.say("Rebuilt %d feature(s) in %.0f ms." % (len(rep["rebuilt"]), rep["ms"]))


@executes("featrebuild")
def featrebuild_exec(ctx, args):
    start = args.get("start")
    return run(rebuild.rebuild, ctx.doc, bool(args.get("force", False)), find_feature(ctx.doc, start) if start else None)


@command("featforcerebuild", group="solids", label="Force Rebuild", description="Rebuild every feature from the start and ignore cached results.", menu="Modify > Force Rebuild")
def featforcerebuild(ctx):
    rep = run(rebuild.rebuild, ctx.doc, True, None)
    ctx.say("Rebuilt %d feature(s) in %.0f ms." % (len(rep["rebuilt"]), rep["ms"]))


@executes("featforcerebuild")
def featforcerebuild_exec(ctx, args):
    return run(rebuild.rebuild, ctx.doc, True, None)


@command("partworkspace", group="solids", label="Workspace", description="Switch between the drafting and part workspaces.", menu="Tools > Workspace")
def partworkspace(ctx):
    w = yield ctx.keyword("Workspace [Drafting/Part]", ["Drafting", "Part"], "Part")
    ws = (w.value if w.kind == "keyword" else "Part").lower()
    run(tree.set_workspace, ctx.doc, ws)
    ctx.say("Workspace: %s." % ws)


@executes("partworkspace")
def partworkspace_exec(ctx, args):
    ws = str(args.get("workspace", "part")).lower()
    run(tree.set_workspace, ctx.doc, ws)
    return {"workspace": ws, "message": "Workspace: %s." % ws}


@command("partauto", group="solids", label="Auto Rebuild", description="Turn automatic rebuilding on or off.", menu="Tools > Auto Rebuild")
def partauto(ctx):
    w = yield ctx.keyword("Auto rebuild [On/Off]", ["On", "Off"], "On")
    run(tree.set_auto, ctx.doc, (w.value if w.kind == "keyword" else "On") == "On")
    ctx.say("Auto rebuild changed.")


@executes("partauto")
def partauto_exec(ctx, args):
    run(tree.set_auto, ctx.doc, bool(args.get("auto", True)))
    return {"message": "Auto rebuild changed."}
