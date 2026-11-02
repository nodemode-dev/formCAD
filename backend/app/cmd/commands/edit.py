from app.cmd.context import CommandError
from app.cmd.registry import command, executes


def _echo(ctx, labels, verb="undone"):
    for label in labels:
        ctx.say("%s" % label)


@command("u", group="edit", label="Undo", description="Undo one step (Ctrl+Z).", menu="Edit > Undo", undoable=False, repeatable=False)
def u(ctx):
    labels = ctx.doc.do_undo(1)
    if not labels:
        ctx.say("Nothing to undo.")
    _echo(ctx, labels)
    yield from ()


@command("redo", group="edit", label="Redo", description="Redo one undone step (Ctrl+Shift+Z).", menu="Edit > Redo", undoable=False, repeatable=False)
def redo(ctx):
    labels = ctx.doc.do_redo(1)
    if not labels:
        ctx.say("Nothing to redo.")
    _echo(ctx, labels)
    yield from ()


@command("mredo", group="edit", label="Multiple Redo", description="Redo several or all undone steps.", menu="", undoable=False, repeatable=False)
def mredo(ctx):
    r = yield ctx.number("Enter the number of actions to redo", ["All"], default=None, integer=True, minimum=1)
    n = len(ctx.doc.undo.redo_stack)
    if r.kind == "number":
        n = min(n, r.value)
    elif r.kind == "keyword" or r.kind == "enter":
        pass
    else:
        return
    labels = ctx.doc.do_redo(n)
    if not labels:
        ctx.say("Nothing to redo.")
    _echo(ctx, labels)


@command("undo", group="edit", label="Undo", description="Undo with count, Auto, Control, BEgin, End, Mark, Back.", menu="", undoable=False, repeatable=False)
def undo(ctx):
    doc = ctx.doc
    um = doc.undo
    while True:
        if um.control == "none":
            opts = ["Control"]
        elif um.control == "one":
            opts = ["Control"]
        else:
            opts = ["Auto", "Control", "BEgin", "End", "Mark", "Back"]
        msg = "Enter the number of operations to undo" if um.control != "none" else "Enter an UNDO control option"
        r = yield ctx.number(msg, opts, default=1 if um.control != "none" else None, integer=True, minimum=1, default_text="1" if um.control != "none" else "")
        if r.kind == "enter":
            return
        if r.kind == "number":
            labels = doc.do_undo(r.value)
            if not labels:
                ctx.say("Nothing to undo.")
            _echo(ctx, labels)
            return
        k = r.value
        if k == "Auto":
            a = yield ctx.keyword("Enter UNDO Auto mode", ["ON", "OFF"], "ON" if um.auto else "OFF")
            if a.kind == "keyword":
                um.auto = a.value == "ON"
            return
        if k == "Control":
            c = yield ctx.keyword("Enter an UNDO control option", ["All", "None", "One", "Combine", "Layer"], "All")
            if c.kind != "keyword":
                return
            if c.value == "All":
                um.set_control("all")
                ctx.say("UNDO is fully enabled.")
            elif c.value == "None":
                um.set_control("none")
                ctx.say("Undo is turned off (UNDO Control None); UNDO Control All turns it on.")
            elif c.value == "One":
                um.set_control("one")
                ctx.say("UNDO is limited to one step.")
            elif c.value == "Combine":
                y = yield ctx.yesno("Combine zoom and pan commands?", "Yes" if um.combine_view else "No")
                if y.kind == "keyword":
                    um.combine_view = y.value == "Yes"
            else:
                y = yield ctx.yesno("Combine layer property changes?", "Yes" if um.combine_layer else "No")
                if y.kind == "keyword":
                    um.combine_layer = y.value == "Yes"
            return
        if k == "BEgin":
            um.begin_group()
            return
        if k == "End":
            um.end_group()
            return
        if k == "Mark":
            um.add_mark()
            ctx.say("Mark set.")
            return
        if k == "Back":
            n = um.undo_to_mark()
            if n is None:
                y = yield ctx.yesno("No mark: undo everything?", "Yes")
                if y.kind == "keyword" and y.value == "Yes":
                    labels = doc.do_undo(len(um.steps))
                    ctx.say("Everything has been undone")
                    _echo(ctx, labels)
                else:
                    ctx.say("Nothing undone")
                return
            labels = doc.do_undo(n)
            ctx.say("Back at the mark")
            _echo(ctx, labels)
            return


@executes("undo", "u")
def undo_exec(ctx, args):
    labels = ctx.doc.do_undo(int(args.get("steps", 1)))
    return {"undone": labels, "rev": ctx.doc.rev}


@executes("redo")
def redo_exec(ctx, args):
    labels = ctx.doc.do_redo(int(args.get("steps", 1)))
    return {"redone": labels, "rev": ctx.doc.rev}
