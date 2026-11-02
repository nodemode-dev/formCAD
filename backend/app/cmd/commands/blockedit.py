from app.cmd.context import CommandError
from app.cmd.prompts import Prompt
from app.cmd.registry import command, executes
from app.doc import blockedit as BE
from app.doc import refedit as RE
from app.doc.blocktools import EditError

ENTERED = 'Block Editor: editing "%s". BSAVE saves it into the drawing; BCLOSE closes the editor.'


def _say_list(ctx):
    names = [r["name"] for r in BE.listing(ctx.d)]
    ctx.say("Defined blocks: %s" % ", ".join(names) if names else "Defined blocks: (none)")


def _source_of(ctx, handle) -> str:
    e = ctx.d.get(int(handle))
    if e is None or e.kind != "insert":
        raise EditError("Select a block reference.")
    base = (e.extra or {}).get("dyn", {}).get("base") if isinstance(e.extra, dict) else None
    return base or e.block


def _enter(ctx, name):
    info = BE.open_editor(ctx.doc, name, True)
    ctx.say(ENTERED % info["name"])
    if info["dynamic"]:
        ctx.say("This is a dynamic block: its parameters and actions are kept but can't be edited yet.")
    if info["new"]:
        ctx.say('Block "%s" does not exist yet; BSAVE will create it.' % info["name"])
    return info


@command("bedit", aliases=("be", "-bedit"), group="block", label="Block Editor", description="Open a block definition for editing in the block editor.", menu="Tools > Block Editor")
def bedit(ctx):
    d = ctx.d
    name = ""
    while True:
        r = yield Prompt("Enter block name or select a block reference", ("entity", "text"), ["?"])
        if r.kind == "keyword":
            _say_list(ctx)
            continue
        try:
            if r.kind == "entity":
                name = _source_of(ctx, r.value["handle"])
            elif r.kind == "text":
                name = r.value.strip()
            else:
                return
            if name.casefold() != BE.CURRENT.casefold():
                BE.check_target(d, name)
        except EditError as err:
            ctx.say(str(err))
            return
        break
    cur = BE.current(d)
    if cur is not None:
        if cur["edit"]["source"].casefold() == name.casefold():
            ctx.say('Block "%s" is already open in the Block Editor.' % cur["edit"]["source"])
            return
        save = False
        if BE.dirty(d, cur):
            a = yield ctx.keyword('Save changes to block "%s"?' % cur["edit"]["source"], ["Yes", "No"], "Yes")
            if a.kind not in ("keyword", "text"):
                return
            save = str(a.value).lower().startswith("y")
        try:
            BE.close_editor(ctx.doc, save)
        except EditError as err:
            ctx.say(str(err))
            return
    try:
        _enter(ctx, name)
    except EditError as err:
        ctx.say(str(err))


@executes("bedit")
def bedit_exec(ctx, args):
    d = ctx.d
    if args.get("handle") is not None:
        name = _source_of(ctx, args["handle"])
    else:
        name = str(args.get("name", "")).strip()
    cur = BE.current(d)
    try:
        if cur is not None:
            if cur["edit"]["source"].casefold() == name.casefold():
                return BE.info(d, cur)
            if BE.dirty(d, cur) and args.get("save") is None:
                raise EditError('Block "%s" has unsaved changes; give save true or false.' % cur["edit"]["source"])
            BE.close_editor(ctx.doc, bool(args.get("save")))
        if args.get("create") is False and name.casefold() != BE.CURRENT.casefold() and not d.tables["blocks"].has(name):
            raise EditError('Block "%s" not found.' % name)
        return _enter(ctx, name)
    except EditError as err:
        raise CommandError(str(err))


@command("bsave", group="block", label="Save Block", description="Write the block editor contents back into the block definition.", menu="")
def bsave(ctx):
    try:
        res = BE.save_editor(ctx.doc)
    except EditError as err:
        ctx.say(str(err))
        return
    ctx.say('Block "%s" saved.' % res["saved"])
    yield from ()


@executes("bsave")
def bsave_exec(ctx, args):
    try:
        res = BE.save_editor(ctx.doc)
    except EditError as err:
        raise CommandError(str(err))
    ctx.say('Block "%s" saved.' % res["saved"])
    return res


@command("bsaveas", group="block", label="Save Block As", description="Save the block editor contents under a new block name.", menu="")
def bsaveas(ctx):
    d = ctx.d
    if BE.current(d) is None:
        ctx.say("The block editor is not open.")
        return
    while True:
        n = yield ctx.word("Enter new block name")
        if n.kind != "text":
            return
        name = n.value.strip()
        existing = d.table_get("blocks", name)
        redefine = False
        if existing is not None:
            a = yield ctx.yesno('Block "%s" already exists. Redefine it?' % existing["name"], "No")
            if a.kind not in ("keyword", "text") or not str(a.value).lower().startswith("y"):
                continue
            redefine = True
        try:
            res = BE.save_editor(ctx.doc, name, redefine)
        except EditError as err:
            ctx.say(str(err))
            continue
        ctx.say('Block "%s" saved. The editor now edits "%s".' % (res["saved"], res["saved"]))
        return


@executes("bsaveas")
def bsaveas_exec(ctx, args):
    try:
        res = BE.save_editor(ctx.doc, str(args.get("name", "")).strip(), bool(args.get("redefine")))
    except EditError as err:
        raise CommandError(str(err))
    ctx.say('Block "%s" saved.' % res["saved"])
    return res


@command("bclose", group="block", label="Close Block Editor", description="Close the block editor and return to the drawing.", menu="")
def bclose(ctx):
    d = ctx.d
    cur = BE.current(d)
    if cur is None:
        ctx.say("The block editor is not open.")
        return
    save = False
    if BE.dirty(d, cur):
        a = yield ctx.keyword('Save changes to block "%s"?' % cur["edit"]["source"], ["Yes", "No"], "Yes")
        if a.kind not in ("keyword", "text"):
            return
        save = str(a.value).lower().startswith("y")
    try:
        BE.close_editor(ctx.doc, save)
    except EditError as err:
        ctx.say(str(err))
        return
    ctx.say("Block Editor closed.")


@executes("bclose")
def bclose_exec(ctx, args):
    d = ctx.d
    cur = BE.current(d)
    if cur is None:
        raise CommandError("The block editor is not open.")
    save = args.get("save")
    if BE.dirty(d, cur) and save is None:
        raise CommandError('Block "%s" has unsaved changes; give save true or false.' % cur["edit"]["source"])
    try:
        res = BE.close_editor(ctx.doc, bool(save))
    except EditError as err:
        raise CommandError(str(err))
    ctx.say("Block Editor closed.")
    return res


@command("bdescription", group="block", label="Block Description", description="Set the description of the block being edited.", menu="")
def bdescription(ctx):
    if BE.current(ctx.d) is None:
        ctx.say("The block editor is not open.")
        return
    t = yield ctx.text("Enter block description", BE.current(ctx.d).get("description", ""))
    if t.kind in ("text", "enter"):
        BE.set_description(ctx.doc, t.value if t.kind == "text" else "")


@executes("bdescription")
def bdescription_exec(ctx, args):
    try:
        BE.set_description(ctx.doc, str(args.get("text", "")))
    except EditError as err:
        raise CommandError(str(err))
    return {"description": str(args.get("text", ""))[:255]}


def _ref_info(ctx, res):
    ctx.say('Reference edit of block "%s": %d object(s) in the working set.' % (res["block"], res["working"]))


@command("refedit", group="block", label="Edit Reference In-Place", description="Edit a block reference in place using a working set.", menu="Tools > Xref and Block In-place Editing > Edit Reference In-Place")
def refedit(ctx):
    d = ctx.d
    if RE.current(d) is not None:
        ctx.say("A reference is already being edited; finish with REFCLOSE.")
        return
    r = yield ctx.entity("Select reference")
    if r.kind != "entity":
        return
    try:
        RE.check_reference(ctx.doc, d.get(int(r.value["handle"])))
    except EditError as err:
        ctx.say(str(err))
        return
    a = yield ctx.keyword("Edit which objects", ["All", "Select"], "All")
    if a.kind not in ("keyword", "text"):
        return
    try:
        res = RE.open_edit(ctx.doc, int(r.value["handle"]), None)
    except EditError as err:
        ctx.say(str(err))
        return
    if str(a.value).lower().startswith("s"):
        s = yield ctx.select("Select objects to edit")
        if s.kind != "selection":
            return
        keep = set(s.value)
        RE.fade(ctx.doc, [h for h in RE.listing(d) if h not in keep])
        res = RE.status(d)
    _ref_info(ctx, res)


@executes("refedit")
def refedit_exec(ctx, args):
    handle = args.get("handle")
    if handle is None:
        raise CommandError("Give the handle of a block reference.")
    try:
        res = RE.open_edit(ctx.doc, int(handle), args.get("objects"))
    except EditError as err:
        raise CommandError(str(err))
    _ref_info(ctx, res)
    return res


@command("refset", group="block", label="Add or Remove Working Set Objects", description="Add objects to or remove objects from the working set of a reference edit.", menu="Tools > Xref and Block In-place Editing > Add to Working Set")
def refset(ctx):
    d = ctx.d
    if RE.current(d) is None:
        ctx.say("No reference is being edited.")
        return
    o = yield ctx.keyword("Enter an option", ["Add", "Remove"], "Add")
    if o.kind not in ("keyword", "text"):
        return
    s = yield ctx.select("Select objects")
    if s.kind != "selection" or not s.value:
        ctx.say("%d object(s) in the working set." % len(RE.listing(d)))
        return
    try:
        n = RE.ws_add(ctx.doc, s.value) if str(o.value).lower().startswith("a") else RE.ws_remove(ctx.doc, s.value)
    except EditError as err:
        ctx.say(str(err))
        return
    ctx.say("%d object(s) %s. %d object(s) in the working set." % (n, "added" if str(o.value).lower().startswith("a") else "removed", len(RE.listing(d))))


@executes("refset")
def refset_exec(ctx, args):
    d = ctx.d
    action = str(args.get("action", "list")).lower()
    handles = [int(h) for h in args.get("handles", [])]
    try:
        if action == "add":
            n = RE.ws_add(ctx.doc, handles)
        elif action == "remove":
            n = RE.ws_remove(ctx.doc, handles)
        elif action == "list":
            n = 0
        else:
            raise EditError("Action is add, remove or list.")
    except EditError as err:
        raise CommandError(str(err))
    ws = RE.listing(d)
    ctx.say("%d object(s) in the working set." % len(ws))
    return {"changed": n, "working": ws}


@command("refclose", group="block", label="Close Reference Edit", description="Save or discard the changes of an in-place reference edit.", menu="Tools > Xref and Block In-place Editing > Save Reference Edits")
def refclose(ctx):
    d = ctx.d
    if RE.current(d) is None:
        ctx.say("No reference is being edited.")
        return
    p = ctx.keyword("Enter option", ["Save", "Discard"], "Save")
    p.hint = "bare"
    o = yield p
    if o.kind not in ("keyword", "text"):
        return
    try:
        res = RE.close_edit(ctx.doc, str(o.value).lower().startswith("s"))
    except EditError as err:
        ctx.say(str(err))
        return
    ctx.say('Reference changes saved to block "%s".' % res["block"] if res["saved"] else "Reference changes discarded.")


@executes("refclose")
def refclose_exec(ctx, args):
    save = args.get("save", True)
    if isinstance(save, str):
        save = save.lower().startswith("s") or save.lower() == "true"
    try:
        res = RE.close_edit(ctx.doc, bool(save))
    except EditError as err:
        raise CommandError(str(err))
    ctx.say('Reference changes saved to block "%s".' % res["block"] if res["saved"] else "Reference changes discarded.")
    return res
