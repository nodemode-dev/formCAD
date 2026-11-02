from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.doc import qselect as Q


def run_qselect(ctx, req):
    try:
        handles = Q.run(list(ctx.visible_entities()), list(ctx.doc.selection), req)
    except Q.QSelectError as err:
        raise CommandError(str(err))
    if not handles:
        ctx.say("No objects match the criteria.")
        return {"handles": [], "count": 0}
    ctx.doc.selection = handles
    ctx.doc.announce("selection")
    ctx.say("%d object%s selected." % (len(handles), "" if len(handles) == 1 else "s"))
    return {"handles": handles, "count": len(handles)}


@command("qselect", group="edit", label="Quick Select", description="Select objects by a property test.", menu="Edit > Quick Select...", undoable=False, repeatable=False)
def qselect(ctx):
    kind = yield ctx.word("Enter object type", default="Multiple")
    kind_text = str(kind.value) if kind.kind in ("text", "keyword") else "Multiple"
    kind_id = "" if kind_text.lower() == "multiple" else kind_text.lower()
    prop = yield ctx.word("Enter property name", default="Layer")
    if prop.kind not in ("text", "keyword"):
        return
    pid = str(prop.value).lower().replace(" ", "_")
    op = yield ctx.keyword("Enter operator", ["=", "<>", ">", "<", "*"], default="=")
    if op.kind not in ("keyword", "text"):
        return
    val = yield ctx.text("Enter value")
    if val.kind != "text":
        return
    how = yield ctx.keyword("Include in new selection set or exclude", ["Include", "Exclude"], default="Include")
    app = yield ctx.yesno("Append to current selection set?", "No")
    run_qselect(ctx, {
        "scope": "all", "kind": kind_id, "property": pid, "operator": str(op.value), "value": str(val.value),
        "how": "exclude" if how.kind == "keyword" and how.value == "Exclude" else "include",
        "append": app.kind == "keyword" and app.value == "Yes",
    })


@executes("qselect")
def qselect_exec(ctx, args):
    return run_qselect(ctx, args)
