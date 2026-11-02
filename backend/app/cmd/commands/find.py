from app.cmd.context import CommandError
from app.cmd.prompts import Prompt
from app.cmd.registry import command, executes
from app.doc import find as F


def run_find(ctx, text, replacement, match_case, whole_word):
    try:
        rx = F.pattern(text, match_case, whole_word)
    except F.FindError as err:
        raise CommandError(str(err))
    space = ctx.doc.current_space
    if replacement is None:
        rows = F.scan(ctx.d, space, rx)
        total = sum(r["hits"] for r in rows)
        ctx.doc.selection = [r["handle"] for r in rows]
        ctx.doc.announce("selection")
        for r in rows:
            ctx.say("%X  %s  %d" % (r["handle"], r["kind"], r["hits"]))
        ctx.say("%d match%s in %d object%s." % (total, "" if total == 1 else "es", len(rows), "" if len(rows) == 1 else "s"))
        return {"matches": rows, "total": total, "selected": [r["handle"] for r in rows]}
    out = F.replace(ctx.d, space, rx, str(replacement))
    ctx.say("%d replacement%s in %d object%s." % (out["hits"], "" if out["hits"] == 1 else "s", out["replaced"], "" if out["replaced"] == 1 else "s"))
    out["total"] = out["hits"]
    return out


@command("find", group="edit", label="Find", description="Find and replace text across text-bearing objects.", menu="Edit > Find...", undoable=True)
def find(ctx):
    t = yield Prompt("Enter text to find", ("text",), [], None, "", free_text=True)
    if t.kind != "text":
        return
    rep = yield Prompt("Enter replacement text, or press Enter to only find", ("text",), [], None, "", free_text=True)
    case = yield ctx.yesno("Match case?", "No")
    if case.kind != "keyword":
        return
    word = yield ctx.yesno("Find whole words only?", "No")
    if word.kind != "keyword":
        return
    run_find(ctx, t.value, rep.value if rep.kind == "text" else None, case.value == "Yes", word.value == "Yes")


@executes("find")
def find_exec(ctx, args):
    return run_find(ctx, args.get("text"), args.get("replace"), bool(args.get("match_case", False)), bool(args.get("whole_word", False)))
