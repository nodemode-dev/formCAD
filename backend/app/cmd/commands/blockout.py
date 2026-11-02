import os

from app.cmd.commands.attributes import ask_line
from app.cmd.commands.blocks import ask_yes, _boolean
from app.cmd.commands.modify import _erase, targets
from app.cmd.commands.tables import make_table
from app.cmd.context import CommandError
from app.cmd.prompts import Prompt
from app.cmd.registry import command, executes
from app.doc import blockdefs, blockio, dataextract, geom, purge, tableops

PURGE_WORDS = ["All", "Blocks", "Dimstyles", "Groups", "LAyers", "LTypes", "MLeaderstyles", "MLinestyles", "Tablestyles", "Textstyles", "Zero-length geometry", "Empty text objects"]
PURGE_KEYS = {"All": "all", "Blocks": "blocks", "Dimstyles": "dimstyles", "Groups": "groups", "LAyers": "layers", "LTypes": "linetypes", "MLeaderstyles": "mleaderstyles", "MLinestyles": "mlinestyles", "Tablestyles": "tablestyles", "Textstyles": "textstyles", "Zero-length geometry": "zerolength", "Empty text objects": "emptytext"}


def purge_flow(ctx):
    r = yield Prompt("Enter type of unused objects to purge", ("keyword",), list(PURGE_WORDS), "All", "All", hint="bare")
    if r.kind != "keyword":
        return
    cat = PURGE_KEYS[r.value]
    spec = yield from ask_line(ctx, "Enter name(s) to purge", "*")
    if spec is None:
        return
    verify = yield from ask_yes(ctx, "Verify each name to be purged?", "Yes")
    picks = []

    def ask(c, n):
        return (c, n) in picks

    if verify:
        for c in (list(purge.ALL_ORDER) if cat == "all" else [cat]):
            if c in purge.NOTHING:
                continue
            for n in purge.listing(ctx.d, c, spec or "*"):
                ok = yield from ask_yes(ctx, 'Purge %s "%s"?' % (purge.LABELS[c], n), "No")
                if ok:
                    picks.append((c, n))
    run_purge(ctx, cat, spec or "*", ask if verify else None)


def run_purge(ctx, cat: str, spec: str, pick=None) -> dict:
    try:
        res = purge.run(ctx.d, cat, spec, pick)
    except (purge.PurgeError, blockdefs.BlockError) as err:
        raise CommandError(str(err))
    for line in res["lines"]:
        ctx.say(line)
    return res


@command("purge", aliases=("pu",), group="file", label="Purge", description="Remove unreferenced blocks, layers, linetypes, styles and groups.", menu="File > Drawing Utilities > Purge...")
def purge_cmd(ctx):
    yield from purge_flow(ctx)


@command("-purge", aliases=("-pu",), group="file", label="Purge (command line)", description="Command-line purge with per-name confirmation.", menu="")
def purge_dash(ctx):
    yield from purge_flow(ctx)


@executes("purge", "-purge")
def purge_exec(ctx, args):
    try:
        cat = purge.canonical(args.get("type", "all"))
    except purge.PurgeError as err:
        raise CommandError(str(err))
    res = run_purge(ctx, cat, str(args.get("name", "*") or "*"))
    return {"purged": res["purged"], "count": res["count"]}


CONVERT_WORDS = {"retain": "Retain", "convert": "Convert", "delete": "Delete"}


def check_dest(ctx, path: str, replace: bool) -> str:
    try:
        dest = blockio.output_path(path)
    except blockio.BlockIOError as err:
        raise CommandError(str(err))
    if os.path.exists(dest) and not replace:
        raise CommandError("%s already exists." % os.path.basename(dest))
    return dest


def wblock_write(ctx, dest: str, source: str, handles, base, block, precision: int, convert: str) -> dict:
    d = ctx.d
    try:
        if source == "objects":
            live = [h for h in handles if d.get(h) is not None]
            if not live:
                ctx.say("No objects selected.")
                return {"written": None, "objects": 0}
            out = blockio.build_from_objects(d, live, base)
        elif source == "block":
            out = blockio.build_from_block(d, block)
        else:
            out = blockio.build_whole(d)
        written = blockio.write(out, dest, "", precision)
    except blockio.BlockIOError as err:
        raise CommandError(str(err))
    count = len(handles) if source == "objects" else 0
    if source == "objects" and convert == "delete":
        _erase(ctx, [h for h in handles if d.get(h) is not None])
    ctx.say("Written to %s." % written)
    return {"written": written, "objects": count}


def wblock_flow(ctx, dash: bool):
    ctx.say("Current settings: Object conversion=Delete")
    while True:
        text = yield from ask_line(ctx, "Enter name of output file")
        if not text:
            return
        try:
            dest = blockio.output_path(text)
        except blockio.BlockIOError as err:
            ctx.say(str(err))
            continue
        if os.path.exists(dest) and not (yield from ask_yes(ctx, "%s already exists. Do you want to replace it?" % os.path.basename(dest), "No")):
            continue
        break
    precision = 16
    if dest.lower().endswith((".dxf", ".dwg")):
        ctx.say("Current DXF settings: precision=%d, objects only" % precision)
        got = yield ctx.number("Enter decimal places of accuracy (0 to 16)", default=16, integer=True, minimum=0, maximum=16)
        if got.kind == "number":
            precision = int(got.value)
    source = None
    block = None
    while source is None:
        r = yield ctx.text("Enter name of existing block or [= (block=output file)/* (whole drawing)]", "")
        if r.kind == "enter" or (r.kind == "text" and not str(r.value).strip()):
            source = "objects"
        elif r.kind == "text":
            t = str(r.value).strip()
            if t == "*":
                source = "all"
            else:
                nm = os.path.splitext(os.path.basename(dest))[0] if t == "=" else t
                rec = blockdefs.lookup(ctx.d, nm)
                if rec is None:
                    ctx.say('Block "%s" not found.' % nm)
                    continue
                block, source = rec["name"], "block"
        else:
            return
    handles, base = [], [0.0, 0.0, 0.0]
    if source == "objects":
        while True:
            b = yield ctx.point("Specify insertion base point", ["mOde"], default=[0.0, 0.0, 0.0])
            if b.kind == "keyword":
                continue
            if b.kind != "point":
                return
            base = b.value
            break
        s = yield ctx.select("Select objects")
        if s.kind != "selection" or not s.value:
            ctx.say("No objects selected.")
            return
        handles = list(s.value)
    wblock_write(ctx, dest, source, handles, base, block, precision, "delete")


@command("wblock", aliases=("w",), group="file", label="Write Block", description="Write objects, a block or the whole drawing to a file.", menu="File > Export > Write Block...")
def wblock_cmd(ctx):
    yield from wblock_flow(ctx, False)


@command("-wblock", aliases=("-w",), group="file", label="Write Block (command line)", description="Command-line WBLOCK; the objects are always erased.", menu="")
def wblock_dash(ctx):
    yield from wblock_flow(ctx, True)


@executes("wblock", "-wblock")
def wblock_exec(ctx, args):
    path = args.get("file")
    if not path:
        raise CommandError("A file name is required.")
    dest = check_dest(ctx, str(path), _boolean(args.get("replace", False)))
    precision = int(args.get("precision", 16))
    if not 0 <= precision <= 16:
        raise CommandError("Requires an integer between 0 and 16.")
    block = args.get("block")
    source = "block" if block and block != "*" else ("all" if block == "*" else "objects")
    handles, base = [], geom.as_pt(args["base"]) if args.get("base") is not None else [0.0, 0.0, 0.0]
    if source == "block":
        if block == "=":
            block = os.path.splitext(os.path.basename(dest))[0]
        rec = blockdefs.lookup(ctx.d, str(block))
        if rec is None:
            raise CommandError('Block "%s" not found.' % block)
        block = rec["name"]
    if source == "objects":
        handles = targets(ctx, args)
    convert = str(args.get("convert", "delete")).lower()
    if convert not in CONVERT_WORDS:
        raise CommandError("Conversion must be retain, convert or delete.")
    return wblock_write(ctx, dest, source, handles, base, block, precision, convert)


def extract_flow(ctx):
    spec = yield from ask_line(ctx, "Enter block names to extract", "*")
    if spec is None:
        return
    combine = yield from ask_yes(ctx, "Combine identical rows and show a Count column?", "Yes")
    r = yield ctx.keyword("Output to [Table/File/Both]", ["Table", "File", "Both"], "File")
    if r.kind != "keyword":
        return
    point = None
    if r.value in ("Table", "Both"):
        p = yield ctx.point("Specify table insertion point")
        if p.kind != "point":
            return
        point = p.value
    path = None
    if r.value in ("File", "Both"):
        stem = os.path.splitext(os.path.basename(ctx.doc.path or "Drawing1"))[0]
        path = yield from ask_line(ctx, "Enter output file name", stem + ".csv")
        if not path:
            return
    do_extract(ctx, spec or "*", combine, r.value.lower(), point, path)


def do_extract(ctx, spec: str, combine: bool, output: str, point, path) -> dict:
    inserts = dataextract.collect(ctx.d, spec, ctx.doc.current_space)
    head, body = dataextract.table_rows(ctx.d, inserts, combine)
    ctx.say("%d row(s) extracted." % len(body))
    res = {"columns": head, "rows": body, "references": len(inserts)}
    try:
        if output in ("table", "both"):
            if not body:
                raise CommandError("There is nothing to extract.")
            dataextract.check_table(head, body)
            t = make_table(ctx, len(head), len(body), point)
            first = int(t.title) + int(t.header)
            if t.title:
                tableops.set_cell(ctx.d, t, 0, 0, "Extracted data")
            for c, h in enumerate(head):
                tableops.set_cell(ctx.d, t, int(t.title), c, h)
            for r, row in enumerate(body):
                for c, v in enumerate(row):
                    tableops.set_cell(ctx.d, t, first + r, c, v)
            res["table"] = ctx.add(t)
        if output in ("file", "both"):
            res["file"] = dataextract.write_file(path, head, body)
            ctx.say("Written to %s." % res["file"])
    except dataextract.ExtractError as err:
        raise CommandError(str(err))
    except tableops.TableError as err:
        raise CommandError(str(err))
    return res


@command("dataextraction", aliases=("dx", "eattext"), group="file", label="Data Extraction", description="Extract block reference attributes to a table or a CSV file.", menu="Tools > Data Extraction...")
def extract_cmd(ctx):
    yield from extract_flow(ctx)


@executes("dataextraction")
def extract_exec(ctx, args):
    output = str(args.get("output", "file")).lower()
    if output not in ("table", "file", "both"):
        raise CommandError("Output must be table, file or both.")
    point = geom.as_pt(args["point"]) if args.get("point") is not None else [0.0, 0.0, 0.0]
    if output != "table" and not args.get("file"):
        raise CommandError("A file name is required.")
    return do_extract(ctx, str(args.get("blocks", "*") or "*"), args.get("combine", True) is not False, output, point, args.get("file"))
