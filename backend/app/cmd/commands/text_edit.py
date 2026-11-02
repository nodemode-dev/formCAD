from app.cmd.commands import text_common as tc
from app.cmd.context import CommandError
from app.cmd.draw_support import pick_entity
from app.cmd.registry import command, executes

FIELDS = {"text": "text", "mtext": "contents", "attdef": "default", "dimension": "text_override"}
NOT_TEXT = "Select a text, mtext, attribute definition or dimension."


def _limit(kind):
    return tc.MAX_CONTENTS if kind == "mtext" else tc.MAX_TEXT


def _clean(kind, value):
    v = tc.check_text(value, _limit(kind))
    if kind != "mtext":
        v = v.replace("\r", "").replace("\n", " ")
    return v


def _apply(ctx, ent, value):
    field = FIELDS[ent.kind]
    old = getattr(ent, field)
    rec = ctx.d.modify(ent.handle)
    setattr(rec, field, _clean(ent.kind, value))
    return old


@command("textedit", aliases=("ed", "ddedit"), group="modify", label="Edit Text...", description="Edit text, multiline text, attribute definition or dimension text.", menu="Modify > Object > Edit Text...")
def textedit(ctx):
    mode = ctx.mem.get("textedit_mode", "Multiple")
    ctx.say("Current settings: Edit mode = %s" % mode)
    done = []
    while True:
        r = yield ctx.entity("Select an annotation object", ["Undo", "Mode"])
        if r.kind == "keyword" and r.value == "Undo":
            if not done:
                ctx.say("Nothing to undo.")
                continue
            h, kind, old = done.pop()
            ent = ctx.d.get(h)
            if ent is not None:
                setattr(ctx.d.modify(h), FIELDS[kind], old)
            ctx.say("Last text edit undone.")
            continue
        if r.kind == "keyword" and r.value == "Mode":
            p = ctx.keyword("Enter an edit mode", ["Single", "Multiple"], mode)
            p.hint = "bare"
            m = yield p
            if m.kind == "keyword":
                mode = m.value
                ctx.mem["textedit_mode"] = mode
            continue
        if r.kind != "entity":
            return
        ent = pick_entity(ctx, r.value)
        if ent is None or ent.kind not in FIELDS:
            ctx.say(NOT_TEXT)
            continue
        if ctx.locked(ent):
            ctx.say("That object is on a locked layer.")
            continue
        old = getattr(ent, FIELDS[ent.kind])
        t = yield ctx.text("Enter new text", tc.first_line(old))
        if t.kind != "text":
            continue
        if not t.from_default:
            try:
                prev = _apply(ctx, ent, t.value)
            except CommandError as err:
                ctx.say(str(err))
                continue
            done.append((ent.handle, ent.kind, prev))
        if mode == "Single":
            return


@executes("textedit")
def textedit_exec(ctx, args):
    ent = ctx.d.get(int(args.get("handle", 0)))
    if ent is None or ent.kind not in FIELDS:
        raise CommandError(NOT_TEXT)
    if ctx.locked(ent):
        raise CommandError("That object is on a locked layer.")
    if not isinstance(args.get("text"), str):
        raise CommandError("Text is required.")
    _apply(ctx, ent, args["text"])
    return {"handle": ent.handle, "text": getattr(ctx.d.get(ent.handle), FIELDS[ent.kind])}
