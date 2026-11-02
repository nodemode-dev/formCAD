from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.doc import annotation as A


def _ratio_text(rec) -> str:
    def g(v):
        return ("%g" % v)

    return "%s:%s" % (g(rec["paper"]), g(rec["drawing"]))


def _scale_lines(ctx) -> list:
    cur = A.current_name(ctx.d)
    return ["%s  (%s)%s" % (r["name"], _ratio_text(r), "  current" if r["name"].casefold() == cur.casefold() else "") for r in ctx.d.tables["scales"].values()]


def scale_action(ctx, action: str, a: dict) -> dict:
    d = ctx.d
    try:
        if action == "list":
            return {"scales": [{"name": r["name"], "paper": r["paper"], "drawing": r["drawing"], "factor": A.factor(d, r["name"])} for r in d.tables["scales"].values()], "current": A.current_name(d)}
        if action == "add":
            name = str(a.get("name", "")).strip()
            if "ratio" in a:
                got = A.parse_ratio(str(a["ratio"]))
                if got is None:
                    raise CommandError("Requires a scale ratio such as 1:50.")
                paper, drawing = got
            else:
                paper, drawing = float(a.get("paper", 0)), float(a.get("drawing", 0))
            return {"scale": A.add_scale(d, name, paper, drawing)}
        if action == "delete":
            A.delete_scale(d, str(a.get("name", "")))
            return {"deleted": str(a.get("name", ""))}
        if action == "reset":
            return {"count": A.reset_scales(d, a.get("metric"))}
    except A.AnnotationError as err:
        raise CommandError(str(err))
    raise CommandError("Unknown scale list action: %s." % action)


@command("scalelistedit", aliases=("-scalelistedit",), group="annotation", label="Scale List", description="Edit the drawing scale list: add, delete, reset, list.", menu="Format > Scale List...")
def scalelistedit(ctx):
    while True:
        r = yield ctx.keyword("Enter option", ["?", "Add", "Delete", "Reset", "Exit"], "Exit")
        if r.kind != "keyword" or r.value == "Exit":
            return
        try:
            if r.value == "?":
                for line in _scale_lines(ctx):
                    ctx.say(line)
            elif r.value == "Add":
                n = yield ctx.word("Enter name for new scale")
                if n.kind != "text":
                    continue
                if ctx.d.tables["scales"].has(str(n.value).strip()):
                    ctx.say("The scale name %s already exists." % str(n.value).strip())
                    continue
                q = yield ctx.word("Enter scale ratio (paper units:drawing units)", default="1:1")
                text = str(q.value) if q.kind == "text" else "1:1"
                scale_action(ctx, "add", {"name": n.value, "ratio": text})
                ctx.say("Scale %s added." % str(n.value).strip())
            elif r.value == "Delete":
                n = yield ctx.word("Enter name of scale to delete")
                if n.kind != "text":
                    continue
                scale_action(ctx, "delete", {"name": n.value})
                ctx.say("Scale %s deleted." % str(n.value).strip())
            else:
                m = yield ctx.keyword("Reset the list to the default [Metric/Imperial]", ["Metric", "Imperial"], "Metric" if ctx.d.metric else "Imperial")
                if m.kind != "keyword":
                    continue
                count = scale_action(ctx, "reset", {"metric": m.value == "Metric"})["count"]
                ctx.say("Scale list reset: %d scales." % count)
        except CommandError as err:
            ctx.say(str(err))


@executes("scalelistedit")
def scalelistedit_exec(ctx, args):
    return scale_action(ctx, str(args.get("action", "list")).lower(), args)


def _eligible(ctx, handles):
    out = []
    total = 0
    for h in handles:
        e = ctx.d.get(int(h))
        if e is None:
            continue
        total += 1
        if not ctx.locked(e):
            out.append(e)
    return out, total


def apply_scale(ctx, handles, action: str, name: str) -> dict:
    d = ctx.d
    if action not in ("add", "delete"):
        raise CommandError("Give add or delete.")
    rec = A.get_scale(d, name)
    if rec is None:
        raise CommandError("Scale %s is not in the list." % name)
    ents, total = _eligible(ctx, handles)
    changed = plain = only = 0
    for e in ents:
        if not A.capable(e) or not e.annotation_scales:
            plain += 1
            continue
        ent = d.modify(e.handle)
        if action == "add":
            if A.add_scale_to(ent, rec["name"]):
                changed += 1
        else:
            res = A.remove_scale_from(ent, rec["name"])
            if res == "removed":
                changed += 1
            elif res == "only":
                only += 1
    ctx.say("%d of %d object(s) changed, %d not annotative, %d scale(s) kept as an object's only scale." % (changed, total, plain, only))
    return {"changed": changed, "total": total, "notAnnotative": plain, "kept": only}


@command("objectscale", aliases=("-objectscale",), group="annotation", label="Add/Delete Scales", description="Add or delete annotation scales of annotative objects.", menu="Modify > Annotative Object Scale > Add/Delete Scales...")
def objectscale(ctx):
    s = yield ctx.select("Select annotative objects")
    if s.kind != "selection" or not s.value:
        return
    r = yield ctx.keyword("Enter an option", ["Add", "Delete", "?"], "Add")
    if r.kind != "keyword":
        return
    if r.value == "?":
        for line in _scale_lines(ctx):
            ctx.say(line)
        return
    cur = A.current_name(ctx.d)
    if r.value == "Add":
        n = yield ctx.word("Enter named scale to add", default=cur)
    else:
        n = yield ctx.word("Enter named scale to delete", default=cur)
    name = cur if n.kind == "enter" else str(n.value).strip()
    apply_scale(ctx, s.value, r.value.lower(), name)


@executes("objectscale")
def objectscale_exec(ctx, args):
    handles = [int(h) for h in args.get("handles", ctx.doc.selection)]
    return apply_scale(ctx, handles, str(args.get("action", "add")).lower(), str(args.get("scale") or A.current_name(ctx.d)))


@command("aiobjectscaleadd", group="annotation", label="Add Current Scale", description="Add the current annotation scale to annotative objects.", menu="Modify > Annotative Object Scale > Add Current Scale")
def scale_add_current(ctx):
    s = yield ctx.select("Select annotative objects")
    if s.kind != "selection" or not s.value:
        return
    apply_scale(ctx, s.value, "add", A.current_name(ctx.d))


@executes("aiobjectscaleadd")
def scale_add_current_exec(ctx, args):
    return apply_scale(ctx, [int(h) for h in args.get("handles", ctx.doc.selection)], "add", A.current_name(ctx.d))


@command("aiobjectscaleremove", group="annotation", label="Delete Current Scale", description="Remove the current annotation scale from annotative objects.", menu="Modify > Annotative Object Scale > Delete Current Scale")
def scale_remove_current(ctx):
    s = yield ctx.select("Select annotative objects")
    if s.kind != "selection" or not s.value:
        return
    apply_scale(ctx, s.value, "delete", A.current_name(ctx.d))


@executes("aiobjectscaleremove")
def scale_remove_current_exec(ctx, args):
    return apply_scale(ctx, [int(h) for h in args.get("handles", ctx.doc.selection)], "delete", A.current_name(ctx.d))


def sync_positions(ctx, handles) -> int:
    ents, _total = _eligible(ctx, handles)
    n = 0
    for e in ents:
        if not A.capable(e) or not e.annotation_scales:
            continue
        A.reset_positions(ctx.d, e.handle)
        n += 1
    ctx.say("%d annotative object(s) synchronized" % n)
    return n


@command("annoreset", group="annotation", label="Synchronize Multiple-scale Positions", description="Return every scale of annotative objects to the shared position.", menu="Modify > Annotative Object Scale > Synchronize Multiple-scale Positions")
def annoreset(ctx):
    s = yield ctx.select("Select annotative objects")
    if s.kind != "selection" or not s.value:
        return
    sync_positions(ctx, s.value)


@executes("annoreset")
def annoreset_exec(ctx, args):
    return {"synchronized": sync_positions(ctx, [int(h) for h in args.get("handles", ctx.doc.selection)])}


def update_objects(ctx, handles) -> int:
    ents, _total = _eligible(ctx, handles)
    n = 0
    for e in ents:
        if not A.capable(e) or e.kind == "hatch":
            continue
        ent = ctx.d.modify(e.handle)
        if A.update_annotative(ctx.d, ent):
            n += 1
    ctx.say("%d object(s) updated" % n)
    return n


@command("annoupdate", group="annotation", label="Update Annotative Objects", description="Make objects annotative or not to match their style or block.", menu="")
def annoupdate(ctx):
    s = yield ctx.select("Select objects")
    if s.kind != "selection" or not s.value:
        return
    update_objects(ctx, s.value)


@executes("annoupdate")
def annoupdate_exec(ctx, args):
    return {"updated": update_objects(ctx, [int(h) for h in args.get("handles", ctx.doc.selection)])}


@command("annotationvisibility", group="annotation", label="Annotation Visibility", description="Toggle whether annotative objects show at every scale.", menu="View > Show Annotative Objects")
def annotation_visibility(ctx):
    now = 0 if int(ctx.var("ANNOALLVISIBLE")) else 1
    ctx.setvar("ANNOALLVISIBLE", now)
    ctx.say("Annotative objects show at %s." % ("all scales" if now else "the current scale only"))
    yield from ()


@executes("annotationvisibility")
def annotation_visibility_exec(ctx, args):
    now = int(args["value"]) if "value" in args else (0 if int(ctx.var("ANNOALLVISIBLE")) else 1)
    ctx.setvar("ANNOALLVISIBLE", now)
    return {"ANNOALLVISIBLE": now}
