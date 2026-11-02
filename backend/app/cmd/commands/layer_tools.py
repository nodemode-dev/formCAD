from app.cmd import layer_flow as LF
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.doc import layerops as LO

MENU = "Format > Layer Tools > "


def guard(fn):
    def run(ctx, args):
        try:
            return fn(ctx, args)
        except LO.LayerError as err:
            if ctx.doc.in_tx():
                ctx.doc.rollback()
            raise CommandError(str(err))

    run.__name__ = fn.__name__
    return run


def plural(n: int, word: str) -> str:
    return "%d %s" % (n, word if n == 1 else word + "s")


def arg_handles(args) -> list:
    if "handles" in args:
        return [int(h) for h in args["handles"]]
    if args.get("handle") is not None:
        return [int(args["handle"])]
    return []


def arg_layers(ctx, args) -> list:
    d = ctx.d
    names = []
    raw = args.get("layers") or args.get("names") or ([args["layer"]] if args.get("layer") else [])
    for n in raw:
        names.append(LO.get(d, n)["name"])
    for nm in LO.layers_of(d, arg_handles(args)):
        if nm not in names:
            names.append(nm)
    if not names:
        raise LO.LayerError("Give objects (handle or handles) or layers (layers).")
    return names


def pick_layers(ctx, msg, single=True, multi_layers=False):
    p = ctx.select(msg.replace(" or [Name]", ""), pick_one=single)
    p.options = ["Name"]
    r = yield p
    if r.kind == "selection":
        if not r.value:
            return None
        return LO.layers_of(ctx.d, r.value)
    if r.kind == "keyword":
        n = yield ctx.text("Enter layer name(s)")
        if n.kind != "text":
            return None
        names = LF.names_in(ctx, n.value)
        if not names:
            return None
        return names if multi_layers else names[:1]
    return None


def pick_handles(ctx, msg):
    s = yield ctx.select(msg)
    if s.kind == "selection" and s.value:
        return list(s.value)
    return None


@command("laymcur", group="format", label="Make Object's Layer Current", description="Make the layer of a picked object current.", menu=MENU + "Make Object's Layer Current")
def laymcur(ctx):
    s = yield ctx.select("Select object whose layer will become current", pick_one=True)
    if s.kind != "selection" or not s.value:
        return
    names = LO.layers_of(ctx.d, s.value)
    LO.push_prev(ctx.doc)
    try:
        nm = LO.set_current(ctx.d, names[0])
    except LO.LayerError as err:
        ctx.say(str(err))
        return
    ctx.say("%s is now the current layer." % nm)


@executes("laymcur")
@guard
def laymcur_exec(ctx, args):
    names = arg_layers(ctx, args)
    LO.push_prev(ctx.doc)
    nm = LO.set_current(ctx.d, names[0])
    LO.prune_noop(ctx.doc)
    return {"current": nm}


def report_move(ctx, res) -> None:
    ctx.say('%s changed to layer "%s".' % (plural(res["moved"], "object"), res["layer"]))
    if res["locked"]:
        ctx.say("%s on locked layers %s not changed." % (plural(res["locked"], "object"), "was" if res["locked"] == 1 else "were"))


@command("laycur", group="format", label="Change to Current Layer", description="Move objects to the current layer.", menu=MENU + "Change to Current Layer")
def laycur(ctx):
    hs = yield from pick_handles(ctx, "Select objects to be changed to the current layer")
    if hs:
        report_move(ctx, LO.move_objects(ctx.d, hs, ctx.d.current_layer()))


@executes("laycur")
@guard
def laycur_exec(ctx, args):
    hs = arg_handles(args)
    if not hs:
        raise LO.LayerError("Give the objects to change (handles).")
    return LO.move_objects(ctx.d, hs, ctx.d.current_layer())


@command("laymch", group="format", label="Layer Match", description="Move objects to the layer of a destination object.", menu=MENU + "Layer Match")
def laymch(ctx):
    hs = yield from pick_handles(ctx, "Select objects to be changed")
    if not hs:
        return
    names = yield from pick_layers(ctx, "Select object on destination layer or [Name]")
    if names:
        try:
            report_move(ctx, LO.move_objects(ctx.d, hs, names[0]))
        except LO.LayerError as err:
            ctx.say(str(err))


@executes("laymch")
@guard
def laymch_exec(ctx, args):
    hs = arg_handles(args)
    if not hs:
        raise LO.LayerError("Give the objects to change (handles).")
    dest = args.get("target") or args.get("layer")
    if dest is None and args.get("destination") is not None:
        dest = LO.layers_of(ctx.d, [int(args["destination"])])[0]
    if dest is None:
        raise LO.LayerError("Give the destination layer (layer) or an object on it (destination).")
    return LO.move_objects(ctx.d, hs, dest)


@command("layiso", group="format", label="Isolate Layer", description="Keep the layers of picked objects and turn all others off.", menu=MENU + "Isolate Layer")
def layiso(ctx):
    names = yield from pick_layers(ctx, "Select objects on the layers to be isolated or [Name]", single=False, multi_layers=True)
    if not names:
        return
    try:
        kept = LO.isolate(ctx.doc, names)
    except LO.LayerError as err:
        ctx.say(str(err))
        return
    ctx.say("Layer(s) %s have been isolated." % ", ".join(kept))


@executes("layiso")
@guard
def layiso_exec(ctx, args):
    kept = LO.isolate(ctx.doc, arg_layers(ctx, args))
    return {"kept": kept}


@command("layuniso", group="format", label="Unisolate Layers", description="Restore the layers changed by the last isolate.", menu=MENU + "Unisolate Layers")
def layuniso(ctx):
    try:
        LO.unisolate(ctx.doc)
    except LO.LayerError as err:
        ctx.say(str(err))
        return
    ctx.say("Isolated layers restored.")
    yield from ()


@executes("layuniso")
@guard
def layuniso_exec(ctx, args):
    return {"changed": LO.unisolate(ctx.doc)}


def loop_tool(name, label, field, value, verb, done, protect_current, ask_off=False):
    def run(ctx):
        d = ctx.d
        LO.push_prev(ctx.doc)
        while True:
            names = yield from pick_layers(ctx, "Select object on layer to %s or [Name]" % verb)
            if not names:
                return
            for nm in names:
                if nm.casefold() == d.current_layer().casefold():
                    if ask_off:
                        y = yield ctx.yesno('Really want layer "%s" (the CURRENT layer) off?' % nm, "No")
                        if y.kind != "keyword" or y.value != "Yes":
                            continue
                    elif protect_current:
                        ctx.say('Layer "%s" is the current layer and stays thawed.' % nm)
                        continue
                if d.layer(nm)[field] == value:
                    ctx.say('Layer "%s" is already %s.' % (nm, done))
                    continue
                LO.set_props(d, [nm], {field: value})
                ctx.say('Layer "%s" has been %s.' % (nm, done))

    run.__name__ = name

    def run_exec(ctx, args):
        names = arg_layers(ctx, args)
        LO.push_prev(ctx.doc)
        res = LO.set_props(ctx.d, names, {field: value})
        return {"changed": res["changed"], "skipped": res["skipped"]}

    command(name, group="format", label=label, description="%s the layer of a picked object." % label, menu=MENU + label)(run)
    executes(name)(guard(run_exec))


loop_tool("layoff", "Layer Off", "on", False, "turn off", "turned off", False, True)
loop_tool("layfrz", "Layer Freeze", "frozen", True, "freeze", "frozen", True)
loop_tool("laylck", "Layer Lock", "locked", True, "lock", "locked", False)
loop_tool("layulk", "Layer Unlock", "locked", False, "unlock", "unlocked", False)


@command("layon", group="format", label="Turn All Layers On", description="Turn every layer on.", menu=MENU + "Turn All Layers On")
def layon(ctx):
    LO.push_prev(ctx.doc)
    n = LO.all_on(ctx.d)
    ctx.say("All layers are on." if n else "All layers were already on.")
    yield from ()


@executes("layon")
@guard
def layon_exec(ctx, args):
    LO.push_prev(ctx.doc)
    return {"changed": LO.all_on(ctx.d)}


@command("laythw", group="format", label="Thaw All Layers", description="Thaw every layer.", menu=MENU + "Thaw All Layers")
def laythw(ctx):
    LO.push_prev(ctx.doc)
    n = LO.thaw_all(ctx.d)
    ctx.say("All layers are thawed." if n else "All layers were already thawed.")
    yield from ()


@executes("laythw")
@guard
def laythw_exec(ctx, args):
    LO.push_prev(ctx.doc)
    return {"changed": LO.thaw_all(ctx.d)}


@command("layerp", group="format", label="Previous Layer", description="Restore the layer settings from before the last layer change.", menu=MENU + "Previous Layer")
def layerp(ctx):
    try:
        LO.restore_prev(ctx.doc)
    except LO.LayerError as err:
        ctx.say(str(err))
        return
    ctx.say("Previous layer settings restored.")
    yield from ()


@executes("layerp")
@guard
def layerp_exec(ctx, args):
    return {"changed": LO.restore_prev(ctx.doc)}


def merge_summary(ctx, srcs, tgt):
    ctx.say("******** WARNING ********")
    ctx.say('You are about to merge layers "%s" into layer "%s".' % ('", "'.join(srcs), tgt))


@command("laymrg", group="format", label="Layer Merge", description="Merge layers into a target layer and delete the sources.", menu=MENU + "Layer Merge")
def laymrg(ctx):
    d = ctx.d
    srcs = yield from pick_layers(ctx, "Select objects on the layers to merge or [Name]", single=False, multi_layers=True)
    if not srcs:
        return
    tgt = yield from pick_layers(ctx, "Select object on target layer or [Name]")
    if not tgt:
        return
    srcs = [s for s in srcs if s.casefold() != tgt[0].casefold()]
    if not srcs:
        ctx.say("A layer cannot be merged into itself.")
        return
    merge_summary(ctx, srcs, tgt[0])
    y = yield ctx.yesno("Do you wish to continue?", "No")
    if y.kind != "keyword" or y.value != "Yes":
        return
    LO.push_prev(ctx.doc)
    try:
        res = LO.merge_layers(d, srcs, tgt[0])
    except LO.LayerError as err:
        ctx.say(str(err))
        return
    for s in res["merged"]:
        ctx.say('Merged "%s" into "%s": %s moved.' % (s, res["target"], plural(res["moved"], "object")))


@executes("laymrg")
@guard
def laymrg_exec(ctx, args):
    srcs = arg_layers(ctx, {k: v for k, v in args.items() if k not in ("target",)})
    tgt = args.get("target")
    if tgt is None:
        raise LO.LayerError("Give the target layer (target).")
    LO.push_prev(ctx.doc)
    return LO.merge_layers(ctx.d, srcs, tgt)


@command("laydel", group="format", label="Layer Delete", description="Delete layers and every object on them.", menu=MENU + "Layer Delete")
def laydel(ctx):
    d = ctx.d
    names = yield from pick_layers(ctx, "Select objects on the layers to delete or [Name]", single=False, multi_layers=True)
    if not names:
        return
    use = LO.usage(d)
    for nm in names:
        why = LO.delete_check(d, nm, use, True)
        if why:
            ctx.say(why)
            return
    ctx.say("******** WARNING ********")
    for nm in names:
        ctx.say('You are about to delete layer "%s" and every object on it from this drawing.' % nm)
    y = yield ctx.yesno("Do you wish to continue?", "No")
    if y.kind != "keyword" or y.value != "Yes":
        return
    LO.push_prev(ctx.doc)
    try:
        res = LO.delete_layers(d, names, True)
    except LO.LayerError as err:
        ctx.say(str(err))
        return
    for nm in res["deleted"]:
        ctx.say('Deleted layer "%s".' % nm)
    ctx.say("Deleted %s." % plural(res["objects"], "object"))


@executes("laydel")
@guard
def laydel_exec(ctx, args):
    names = arg_layers(ctx, args)
    LO.push_prev(ctx.doc)
    res = LO.delete_layers(ctx.d, names, bool(args.get("objects", True)))
    if res["refused"] and not res["deleted"]:
        raise LO.LayerError(res["refused"][0]["reason"])
    return res


@command("laywalk", group="format", label="Layer Walk", description="Show the objects of chosen layers one set at a time.", menu=MENU + "Layer Walk")
def laywalk(ctx):
    d = ctx.d
    saved = LO.snap_layers(d)
    LO.push_prev(ctx.doc)

    def show(names):
        keep = {n.casefold() for n in names}
        for rec in list(d.tables["layers"].values()):
            want = rec["name"].casefold() in keep
            if rec["on"] != want:
                d.modify_record("layers", rec["name"])["on"] = want

    while True:
        r = yield ctx.text("Enter layer name(s) to show or [All/Keep/Exit]", "Exit")
        if r.kind != "text":
            break
        word = r.value.strip()
        if word.lower() in ("exit", "x", ""):
            break
        if word.lower() == "keep":
            return
        if word.lower() == "all":
            show([x["name"] for x in d.tables["layers"].values()])
            continue
        names = LF.names_in(ctx, word)
        if names:
            show(names)
            ctx.say("Showing %s." % ", ".join(names))
    for row in saved["layers"]:
        rec = d.layer(row["name"])
        if rec is not None and rec["on"] != row["on"]:
            d.modify_record("layers", rec["name"])["on"] = row["on"]
    LO.prune_noop(ctx.doc)


@executes("laywalk")
@guard
def laywalk_exec(ctx, args):
    d = ctx.d
    names = arg_layers(ctx, args)
    keep = {n.casefold() for n in names}
    if not args.get("keep"):
        return {"showing": names, "changed": 0}
    LO.push_prev(ctx.doc)
    n = 0
    for rec in list(d.tables["layers"].values()):
        want = rec["name"].casefold() in keep
        if rec["on"] != want:
            d.modify_record("layers", rec["name"])["on"] = want
            n += 1
    return {"showing": names, "changed": n}


@command("copytolayer", group="format", label="Copy Objects to Layer", description="Copy objects to another layer.", menu=MENU + "Copy Objects to New Layer")
def copytolayer(ctx):
    d = ctx.d
    hs = yield from pick_handles(ctx, "Select objects to copy")
    if not hs:
        return
    names = yield from pick_layers(ctx, "Select object on destination layer or [Name]")
    if not names:
        return
    base = yield ctx.point("Specify base point or displacement", default_text="same location")
    disp = [0.0, 0.0]
    if base.kind == "point":
        sec = yield ctx.point("Specify second point of displacement <use first point as displacement>", base=base.value)
        if sec.kind == "point":
            disp = [sec.value[0] - base.value[0], sec.value[1] - base.value[1]]
        else:
            disp = [base.value[0], base.value[1]]
    try:
        n = copy_to(ctx, hs, names[0], disp)
    except LO.LayerError as err:
        ctx.say(str(err))
        return
    ctx.say('%s copied to layer "%s".' % (plural(n, "object"), names[0]))


def copy_to(ctx, handles, layer, disp) -> int:
    d = ctx.d
    tgt = LO.get(d, layer)
    n = 0
    for h in handles:
        e = d.get(int(h))
        if e is None:
            continue
        c = e.copy_as_new()
        c.layer = tgt["name"]
        if disp[0] or disp[1]:
            c.move_by([disp[0], disp[1], 0.0])
        try:
            d.add_entity(c, e.owner)
        except ValueError as err:
            raise LO.LayerError(str(err))
        n += 1
    return n


@executes("copytolayer")
@guard
def copytolayer_exec(ctx, args):
    hs = arg_handles(args)
    if not hs:
        raise LO.LayerError("Give the objects to copy (handles).")
    disp = args.get("displacement") or [0.0, 0.0]
    n = copy_to(ctx, hs, args.get("layer", ""), [float(disp[0]), float(disp[1])])
    return {"copied": n}


@command("layerstate", group="format", label="Layer States", description="Save, restore, edit, rename, delete, import and export layer states.", menu="Format > Layer States Manager...")
def layerstate(ctx):
    yield from LF.state_loop(ctx)


@command("-layer", aliases=("-la",), group="format", label="Layer (command line)", description="Command line layer options.", menu="")
def layer_typed(ctx):
    from app.cmd.commands.settings import layer

    yield from layer(ctx)


def noop_typed(ctx):
    ctx.say("Use the LAYER command, or call this form with parameters.")
    yield from ()


def variant(name, label, description, fn, undoable=True):
    command(name, group="format", label=label, description=description, menu="", undoable=undoable, repeatable=False)(noop_typed)
    executes(name)(guard(fn))


def v_apply(ctx, args):
    ops = args.get("ops")
    if not isinstance(ops, list) or not ops:
        raise LO.LayerError("Give a list of operations (ops).")
    return LO.apply_ops(ctx.doc, [o for o in ops if isinstance(o, dict)])


def v_one(op):
    def run(ctx, args):
        item = dict(args)
        item["op"] = op
        return LO.apply_ops(ctx.doc, [item])

    return run


def v_list(ctx, args):
    return LO.describe(ctx.doc, str(args.get("filter", "")), str(args.get("search", "")), str(args.get("sort", "name")), bool(args.get("desc")), args.get("viewport"))


def v_filter(ctx, args):
    d = ctx.d
    action = str(args.get("action", "set")).lower()
    if action == "set":
        rec = LO.set_filter(d, args.get("name", ""), args.get("kind"), args.get("expr"), args.get("layers"), args.get("parent"), args.get("add"), args.get("remove"))
        return {"filter": rec}
    if action == "delete":
        return {"deleted": LO.delete_filter(d, args.get("name", ""))}
    if action == "rename":
        return {"filter": LO.rename_filter(d, args.get("name", ""), args.get("to", ""))}
    if action == "list":
        return {"filters": LO.filter_list(d)}
    if action == "apply":
        return {"layers": LO.filtered(d, str(args.get("name", "All")))}
    raise LO.LayerError("Unknown filter action %s." % action)


def v_state(ctx, args):
    d = ctx.d
    action = str(args.get("action", "list")).lower()
    name = args.get("name", "")
    if action == "list":
        return {"states": LO.state_list(d)}
    if action == "save":
        LO.push_prev(ctx.doc)
        rec = LO.save_state(d, name, args.get("description", ""), bool(args.get("overwrite")))
        return {"state": rec["name"], "layers": len(rec["layers"])}
    if action == "restore":
        LO.push_prev(ctx.doc)
        return LO.restore_state(d, name, args.get("props"), bool(args.get("offMissing")), args.get("createMissing", True), args.get("restoreCurrent", True))
    if action == "edit":
        st = LO.edit_state(d, name, args.get("description"), args.get("layers"), args.get("add"), args.get("remove"), bool(args.get("update")), args.get("current"), args.get("rename"))
        return {"state": st["name"], "layers": len(st["layers"])}
    if action == "rename":
        st = LO.edit_state(d, name, rename=args.get("to", ""))
        return {"state": st["name"]}
    if action == "delete":
        return {"deleted": LO.delete_states(d, args.get("names") or name)}
    if action == "export":
        return LO.export_states(d, args.get("names") or ([name] if name else None), str(args.get("path", "")))
    if action == "import":
        return LO.import_states(d, args.get("data"), str(args.get("path", "")), args.get("names"), bool(args.get("overwrite")))
    raise LO.LayerError("Unknown layer state action %s." % action)


variant("layer.apply", "Layer Operations", "Apply a list of layer operations as one undo step.", v_apply)
variant("layer.new", "New Layer", "Create a layer.", v_one("new"))
variant("layer.set", "Set Layer Properties", "Set properties of one or more layers.", v_one("set"))
variant("layer.rename", "Rename Layer", "Rename a layer.", v_one("rename"))
variant("layer.delete", "Delete Layers", "Delete layers that hold no objects.", v_one("delete"))
variant("layer.current", "Make Layer Current", "Make a layer current.", v_one("current"))
variant("layer.merge", "Merge Layers", "Merge layers into a target layer.", v_one("merge"))
variant("layer.list", "List Layers", "List layers with every property and usage count.", v_list, False)
variant("layer.filter", "Layer Filters", "List, create, change, rename, delete or apply layer filters.", v_filter)
variant("layer.state", "Layer State", "Save, restore, edit, rename, delete, import or export layer states.", v_state)
