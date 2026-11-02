from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.doc import rename as R

TYPE_OPTS = ["Block", "Dimstyle", "LAyer", "LType", "MLeaderstyle", "Style", "TAblestyle", "View", "Ucs"]
TYPE_KEY = {"Block": "block", "Dimstyle": "dimstyle", "LAyer": "layer", "LType": "linetype", "MLeaderstyle": "mleaderstyle", "Style": "textstyle", "TAblestyle": "tablestyle", "View": "view", "Ucs": "ucs"}
TYPE_LABEL = {"block": "block", "dimstyle": "dimstyle", "layer": "layer", "linetype": "linetype", "mleaderstyle": "multileader style", "textstyle": "text style", "tablestyle": "table style", "view": "view", "ucs": "UCS"}


def _word(text) -> str:
    return str(text).strip().split(" ")[0]


@command("rename", aliases=("ren", "-rename"), group="format", label="Rename", description="Rename layers, linetypes, styles, blocks, views and UCSs.", menu="Format > Rename...")
def rename(ctx):
    t = yield ctx.keyword("Enter object type to rename", TYPE_OPTS)
    if t.kind != "keyword":
        return
    kind = TYPE_KEY[t.value]
    label = TYPE_LABEL[kind]
    while True:
        o = yield ctx.word("Enter old %s name" % label)
        if o.kind != "text":
            return
        old = _word(o.value)
        table = R.KINDS[kind][0]
        if ctx.d.table_get(table, old) is None:
            ctx.say('Cannot find %s "%s".' % (label, old))
            continue
        break
    while True:
        n = yield ctx.word("Enter new %s name" % label)
        if n.kind != "text":
            return
        new = _word(n.value)
        try:
            res = R.rename(ctx.d, kind, old, new)
        except R.RenameError as err:
            ctx.say(str(err))
            if "already exists" in str(err) or "not a valid" in str(err):
                continue
            return
        ctx.say('%s "%s" renamed to "%s".' % (label.capitalize(), res["old"], res["new"]))
        return


@executes("rename")
def rename_exec(ctx, args):
    try:
        return R.rename(ctx.d, args.get("type", ""), str(args.get("old", "")), str(args.get("new", "")))
    except R.RenameError as err:
        raise CommandError(str(err))
