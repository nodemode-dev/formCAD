import copy
import math
import os

from app.cmd import jig
from app.cmd.context import CommandError
from app.cmd.draw_support import pick_entity
from app.cmd.registry import command, executes
from app.doc import geom
from app.doc import tablecalc as calc
from app.doc import tableops as O
from app.doc import tables as T
from app.doc.kinds.table import MAX_COLS, MAX_ROWS, TableObject

MAX_LINK_BYTES = 8 * 1024 * 1024
BAD_NAME_CHARS = '<>/\\":;?*|,=`'
CELL_FIELDS = ("text_style", "text_height", "text_color", "fill", "alignment", "margin_h", "margin_v", "format", "precision", "merge_across")


def fail(err: Exception):
    return CommandError(str(err))


def table_of(ctx, handle):
    e = ctx.d.get(int(handle)) if handle is not None else None
    if e is None or e.kind != "table":
        raise CommandError("The object is not a table.")
    if ctx.locked(e):
        raise CommandError("The table is on a locked layer.")
    return e


def editable_table(ctx, handle) -> TableObject:
    table_of(ctx, handle)
    return ctx.d.modify(int(handle))


def style_for(ctx):
    rec = O.style_rec(ctx.d, str(ctx.var("CTABLESTYLE")))
    if rec is None:
        raise CommandError("No table style is defined.")
    return rec


def outline(t, at):
    w, h = t.width(), t.height()
    x, y = at[0], at[1]
    return [jig.poly([[x, y, 0.0], [x + w, y, 0.0], [x + w, y - h, 0.0], [x, y - h, 0.0]], True)]


def make_table(ctx, cols, rows, at, style=None, col_width=None, row_height=None) -> TableObject:
    st = O.style_rec(ctx.d, style) if style else style_for(ctx)
    try:
        t = O.build(ctx.d, st["name"], rows, cols, at, col_width, row_height)
    except O.TableError as err:
        raise fail(err)
    return t


def ask_count(ctx, msg, default, hi):
    while True:
        r = yield ctx.number(msg, default=default)
        if r.kind != "number":
            return None
        v = r.value
        if v != int(v) or not 1 <= v <= hi:
            ctx.say("Requires an integer between 1 and %d." % hi)
            continue
        return int(v)


@command("table", aliases=("tb",), group="annotation", label="Table", description="Create a table from columns, data rows and an insertion point.", menu="Draw > Table...")
def table_cmd(ctx):
    mem = ctx.mem.setdefault("table", {"cols": 5, "rows": 1})
    cols = yield from ask_count(ctx, "Enter number of columns", mem["cols"], MAX_COLS)
    if cols is None:
        return
    rows = yield from ask_count(ctx, "Enter number of data rows", mem["rows"], MAX_ROWS)
    if rows is None:
        return
    proto = make_table(ctx, cols, rows, [0.0, 0.0])
    p = yield ctx.point("Specify insertion point", jig=lambda q: outline(proto, q))
    if p.kind != "point":
        return
    mem["cols"], mem["rows"] = cols, rows
    t = make_table(ctx, cols, rows, p.value)
    ctx.add(t)


def apply_cells(ctx, t, cells):
    if isinstance(cells, dict):
        items = [(k, v) for k, v in cells.items()]
    else:
        items = [((c[0], c[1]), c[2]) if len(c) == 3 else (c[0], c[1]) for c in cells]
    for key, text in items:
        r, c = O.parse_cell_ref(key)
        O.set_cell(ctx.d, t, r, c, text)


@executes("table")
def table_exec(ctx, args):
    cols = int(args.get("cols", args.get("columns", 5)))
    rows = int(args.get("rows", 1))
    at = geom.as_pt(args.get("point", [0.0, 0.0]))
    t = make_table(ctx, cols, rows, at, args.get("style"), args.get("col_width"), args.get("row_height"))
    try:
        if args.get("cells"):
            apply_cells(ctx, t, args["cells"])
        O.ensure_heights(ctx.d, t)
        O.recalc(ctx.d, t)
    except O.TableError as err:
        raise fail(err)
    h = ctx.add(t)
    return {"handle": h, "rows": t.rows(), "cols": t.cols(), "style": t.style}


def cell_prompt(ctx, t, r, c):
    cell = t.cells[r][c]
    return "Enter text for cell %s (=formula)" % calc.cell_name(r, c), (cell.get("formula") or cell.get("text") or None)


@command("tabledit", group="annotation", label="Edit Table Cell", description="Edit the text or formula of a picked table cell.", menu="")
def tabledit(ctx):
    p = yield ctx.entity("Pick a table cell")
    if p.kind != "entity":
        return
    ent = pick_entity(ctx, p.value)
    if ent is None or ent.kind != "table":
        ctx.say("No table cell there.")
        return
    table_of(ctx, ent.handle)
    at = p.value.get("point") or [0, 0]
    got = O.cell_at(ent, at)
    if got is None:
        ctx.say("No table cell there.")
        return
    msg, default = cell_prompt(ctx, ent, *got)
    r = yield ctx.text(msg, default=default)
    if r.kind == "enter":
        return
    t = ctx.d.modify(ent.handle)
    try:
        O.set_cell(ctx.d, t, got[0], got[1], r.value if r.kind == "text" else "")
        O.ensure_heights(ctx.d, t)
        O.recalc(ctx.d, t)
    except O.TableError as err:
        raise fail(err)


@executes("tabledit")
def tabledit_exec(ctx, args):
    t = editable_table(ctx, args.get("handle"))
    try:
        if "point" in args:
            got = O.cell_at(t, geom.as_pt(args["point"]))
            if got is None:
                raise CommandError("No table cell there.")
            r, c = got
        else:
            r, c = O.parse_cell_ref(args.get("cell"))
        cell = O.set_cell(ctx.d, t, r, c, args.get("text", ""), args.get("type"), args.get("format"))
        O.ensure_heights(ctx.d, t)
        errors = O.recalc(ctx.d, t)
    except O.TableError as err:
        raise fail(err)
    return {"text": cell["text"], "formula": cell.get("formula", ""), "errors": errors}


def default_csv_name(ctx) -> str:
    base = os.path.splitext(ctx.doc.path)[0] if ctx.doc.path else os.path.join(os.getcwd(), ctx.doc.name)
    return base + ".csv"


def write_csv(t, path: str, sep: str) -> str:
    text = O.export_csv(t, sep)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    return text


@command("tableexport", group="annotation", label="Export Table", description="Write a table to a CSV file.", menu="")
def tableexport(ctx):
    s = yield ctx.select("Select a table", pick_one=True)
    if s.kind != "selection":
        return
    found = [ctx.d.get(h) for h in s.value if ctx.d.get(h) is not None and ctx.d.get(h).kind == "table"]
    if not found:
        ctx.say("The object is not a table.")
        return
    sep = ","
    default = default_csv_name(ctx)
    while True:
        r = yield ctx.word("Enter file name", ["Separator"], default)
        if r.kind == "keyword":
            k = yield ctx.keyword("Enter separator", ["Comma", "Semicolon", "Tab"], "Comma")
            if k.kind == "keyword":
                sep = {"Comma": ",", "Semicolon": ";", "Tab": "\t"}[k.value]
            continue
        path = default if r.kind == "enter" else str(r.value).strip()
        break
    try:
        write_csv(found[0], path, sep)
    except (OSError, O.TableError) as err:
        raise CommandError("Could not write %s: %s" % (path, err))
    ctx.say("Table exported to %s." % path)


@executes("tableexport")
def tableexport_exec(ctx, args):
    t = table_of(ctx, args.get("handle"))
    sep = {"comma": ",", "semicolon": ";", "tab": "\t"}.get(str(args.get("separator", "comma")).lower(), args.get("separator", ","))
    try:
        text = O.export_csv(t, sep)
    except O.TableError as err:
        raise fail(err)
    path = args.get("path")
    if path:
        try:
            with open(str(path), "w", encoding="utf-8", newline="") as fh:
                fh.write(text)
        except OSError as err:
            raise CommandError("Could not write %s: %s" % (path, err))
        ctx.say("Table exported to %s." % path)
    return {"csv": text, "path": path}


def drawing_folder(ctx) -> str:
    return os.path.dirname(os.path.abspath(ctx.doc.path)) if ctx.doc.path else ""


def resolve_link(path: str, folder: str) -> str:
    p = os.path.expanduser(path)
    if os.path.isabs(p):
        if os.path.isfile(p) or not folder:
            return os.path.abspath(p)
        beside = os.path.join(folder, os.path.basename(p.replace("\\", "/")))
        return beside if os.path.isfile(beside) else os.path.abspath(p)
    if folder:
        return os.path.abspath(os.path.join(folder, p))
    return os.path.abspath(p)


def stored_link(full: str, folder: str) -> str:
    if folder:
        rel = os.path.relpath(full, folder)
        if not rel.startswith("..") and not os.path.isabs(rel):
            return rel.replace(os.sep, "/")
    return full


def read_link(path: str, folder: str = ""):
    full = resolve_link(path, folder)
    if not os.path.isfile(full):
        raise CommandError("The file %s was not found." % path)
    if os.path.getsize(full) > MAX_LINK_BYTES:
        raise CommandError("The file is larger than 8 MB.")
    with open(full, "r", encoding="utf-8-sig", newline="") as fh:
        text = fh.read()
    return full, O.parse_delimited(text, O.detect_sep(full, text))


def apply_link(ctx, t, path: str, start_row=None) -> None:
    folder = drawing_folder(ctx)
    full, rows = read_link(path, folder)
    start = (1 if t.title else 0) if start_row is None else int(start_row)
    if start < 0:
        raise CommandError("Requires a positive row.")
    if not rows:
        raise CommandError("The file holds no rows.")
    old_cols = t.cols()
    title_wide = [r for r in range(min(start, t.rows())) if t.cells[r][0].get("span", [1, 1])[1] >= old_cols and old_cols > 1]
    try:
        O.fill_from_rows(ctx.d, t, rows, start)
    except O.TableError as err:
        raise fail(err)
    for r in title_wide:
        if r < start:
            t.cells[r][0]["span"] = [t.cells[r][0]["span"][0], t.cols()]
    t.link = {"path": stored_link(full, folder), "start_row": start}


@command("datalink", group="annotation", label="Data Link", description="Fill a table from a CSV or delimited text file and keep the link.", menu="")
def datalink(ctx):
    s = yield ctx.select("Select a table", pick_one=True)
    if s.kind != "selection":
        return
    found = [h for h in s.value if ctx.d.get(h) is not None and ctx.d.get(h).kind == "table"]
    if not found:
        ctx.say("The object is not a table.")
        return
    t = editable_table(ctx, found[0])
    f = yield ctx.word("Enter data file name")
    if f.kind != "text":
        return
    start = (1 if t.title else 0)
    r = yield ctx.number("Enter starting row", default=start + 1, integer=True, positive=True)
    row = start if r.kind != "number" else int(r.value) - 1
    apply_link(ctx, t, str(f.value).strip(), row)
    ctx.say("Table linked to %s." % t.link["path"])


@executes("datalink")
def datalink_exec(ctx, args):
    t = editable_table(ctx, args.get("handle"))
    apply_link(ctx, t, str(args.get("path", "")), args.get("start_row"))
    return {"rows": t.rows(), "cols": t.cols(), "link": t.link}


def update_links(ctx, handles=None) -> tuple:
    done, problems = 0, []
    for e in list(ctx.d.ents.values()):
        if e.kind != "table" or not e.link or (handles is not None and e.handle not in handles):
            continue
        if ctx.locked(e):
            continue
        t = ctx.d.modify(e.handle)
        try:
            apply_link(ctx, t, t.link["path"], t.link.get("start_row"))
            done += 1
        except CommandError as err:
            problems.append("%s: %s" % (e.handle, err))
    ctx.say("%d data link(s) updated." % done)
    for p in problems:
        ctx.say(p)
    return done, problems


@command("datalinkupdate", group="annotation", label="Update Data Links", description="Re-read the linked files of tables.", menu="")
def datalinkupdate(ctx):
    update_links(ctx)
    yield from ()


@executes("datalinkupdate")
def datalinkupdate_exec(ctx, args):
    handles = [int(h) for h in args["handles"]] if args.get("handles") else None
    done, problems = update_links(ctx, handles)
    return {"updated": done, "errors": problems}


def parts_message(ctx, t) -> int:
    n = len(t.parts())
    ctx.say("Table in %d part(s)." % n)
    return n


@command("tablebreak", group="annotation", label="Table Breaks", description="Break a table into parts of a maximum height.", menu="")
def tablebreak(ctx):
    s = yield ctx.select("Select a table", pick_one=True)
    if s.kind != "selection":
        return
    found = [h for h in s.value if ctx.d.get(h) is not None and ctx.d.get(h).kind == "table"]
    if not found:
        ctx.say("The object is not a table.")
        return
    t = editable_table(ctx, found[0])
    r = yield ctx.distance("Enter maximum part height", ["Off"], positive=True)
    try:
        if r.kind == "keyword":
            O.set_breaks(t, {"enabled": False})
        elif r.kind == "number":
            O.set_breaks(t, {"enabled": True, "max_height": float(r.value)})
        elif r.kind == "point":
            O.set_breaks(t, {"enabled": True, "max_height": abs(t.position[1] - r.value[1])})
        else:
            return
    except O.TableError as err:
        raise fail(err)
    parts_message(ctx, t)


@executes("tablebreak")
def tablebreak_exec(ctx, args):
    t = editable_table(ctx, args.get("handle"))
    spec = {k: args[k] for k in ("enabled", "direction", "max_height", "spacing", "repeat_top", "repeat_bottom", "heights", "offsets") if k in args}
    if "max_height" in spec and "enabled" not in spec:
        spec["enabled"] = True
    try:
        n = O.set_breaks(t, spec)
    except O.TableError as err:
        raise fail(err)
    ctx.say("Table in %d part(s)." % n)
    return {"parts": n}


def table_op_command(name, label, op, description):
    def stub(ctx):
        ctx.say("%s is available through the table editor and the programmatic form." % label)
        yield from ()

    command(name, group="annotation", label=label, description=description, menu="", repeatable=False)(stub)

    def run(ctx, args):
        t = editable_table(ctx, args.get("handle"))
        spec = dict(args)
        spec["op"] = op
        try:
            res = O.apply_op(ctx.d, t, spec)
            O.ensure_heights(ctx.d, t)
            errors = O.recalc(ctx.d, t)
        except (O.TableError, ValueError, KeyError, TypeError) as err:
            raise CommandError(str(err) if not isinstance(err, KeyError) else "Missing argument %s." % err)
        return {"rows": t.rows(), "cols": t.cols(), "errors": errors, "result": res if isinstance(res, (int, float, bool, str)) else None}

    executes(name)(run)


for _name, _label, _op, _desc in (
    ("table.setcell", "Set Table Cell", "set", "Set a cell text or formula."),
    ("table.insertrow", "Insert Row", "insertrow", "Insert a table row."),
    ("table.deleterow", "Delete Row", "deleterow", "Delete a table row."),
    ("table.insertcolumn", "Insert Column", "insertcol", "Insert a table column."),
    ("table.deletecolumn", "Delete Column", "deletecol", "Delete a table column."),
    ("table.merge", "Merge Cells", "merge", "Merge a range of cells."),
    ("table.unmerge", "Unmerge Cells", "unmerge", "Unmerge a merged cell."),
    ("table.cellstyle", "Set Table Cell Style", "cellstyle", "Apply a named cell style to a cell, row or range."),
    ("table.colwidth", "Column Width", "colwidth", "Set a column width."),
    ("table.rowheight", "Row Height", "rowheight", "Set a row height."),
    ("table.align", "Cell Alignment", "align", "Set the alignment of a range of cells."),
    ("table.border", "Cell Borders", "border", "Set borders of a range of cells."),
    ("table.format", "Cell Format", "format", "Set the data format of a range of cells."),
    ("table.fill", "Cell Fill", "fill", "Set the fill colour of a range of cells."),
    ("table.textheight", "Cell Text Height", "textheight", "Set the text height of a range of cells."),
):
    table_op_command(_name, _label, _op, _desc)

FORMULA_FUNCS = {"sum": "SUM", "average": "AVERAGE", "count": "COUNT", "min": "MIN", "max": "MAX"}


def formula_text(t, r, c, args) -> str:
    kind = str(args.get("function", "equation")).lower()
    if kind in FORMULA_FUNCS:
        if args.get("range"):
            rng = str(args["range"])
        else:
            first = (1 if t.title else 0) + (1 if t.header else 0)
            if r <= first:
                raise CommandError("There are no cells above to use as the range.")
            rng = "%s:%s" % (calc.cell_name(first, c), calc.cell_name(r - 1, c))
        return "=%s(%s)" % (FORMULA_FUNCS[kind], rng)
    if kind == "cell":
        return "=" + str(args.get("cell_ref", args.get("reference", "")))
    eq = str(args.get("equation", args.get("text", "")))
    return eq if eq.lstrip().startswith("=") else "=" + eq


@command("table.formula", group="annotation", label="Insert Table Formula", description="Insert a Sum, Average, Count, Min, Max, cell or equation formula.", menu="", repeatable=False)
def table_formula_stub(ctx):
    ctx.say("Insert Table Formula is available through the table editor and the programmatic form.")
    yield from ()


@executes("table.formula")
def table_formula_exec(ctx, args):
    t = editable_table(ctx, args.get("handle"))
    r, c = O.parse_cell_ref(args.get("cell"))
    O._check(t, r, c)
    text = formula_text(t, r, c, args)
    try:
        O.set_cell(ctx.d, t, r, c, text)
        errors = O.recalc(ctx.d, t)
    except O.TableError as err:
        raise fail(err)
    cell = t.cells[r][c]
    return {"formula": cell["formula"], "text": cell["text"], "errors": errors}


@command("table.recalc", group="annotation", label="Recalculate Table Formulas", description="Recalculate the formulas of one or all tables.", menu="", repeatable=False)
def table_recalc_stub(ctx):
    n = recalc_all(ctx, None)
    ctx.say("%d table(s) recalculated." % n)
    yield from ()


def recalc_all(ctx, handles):
    n = 0
    for e in list(ctx.d.ents.values()):
        if e.kind == "table" and (handles is None or e.handle in handles) and not ctx.locked(e):
            t = ctx.d.modify(e.handle)
            O.ensure_heights(ctx.d, t)
            O.recalc(ctx.d, t)
            n += 1
    return n


@executes("table.recalc")
def table_recalc_exec(ctx, args):
    handles = {int(h) for h in args["handles"]} if args.get("handles") else None
    return {"recalculated": recalc_all(ctx, handles)}


def valid_name(name: str) -> bool:
    n = str(name).strip()
    return 0 < len(n) <= 255 and not any(c in BAD_NAME_CHARS for c in n)


def styles_in_use(ctx) -> set:
    return {e.style.casefold() for e in ctx.d.ents.values() if e.kind == "table"}


def expand_borders(spec: dict) -> dict:
    out = {}
    for edge, val in spec.items():
        keys = {"outside": ("top", "bottom", "left", "right"), "all": T_BORDERS}.get(edge, (edge,))
        for k in keys:
            if k not in T_BORDERS:
                raise CommandError("Unknown border: %s." % edge)
            out[k] = val
    return out


T_BORDERS = ("top", "inside_h", "bottom", "left", "inside_v", "right")


def clean_cell_style(ctx, cs: dict) -> dict:
    if ctx.d.table_get("textstyles", str(cs.get("text_style", "Standard"))) is None:
        raise CommandError("Text style %s does not exist." % cs.get("text_style"))
    for k in ("text_height", "margin_h", "margin_v"):
        v = cs.get(k)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or v < 0:
            raise CommandError("%s must be zero or more." % k.replace("_", " ").capitalize())
        cs[k] = float(v)
    if not isinstance(cs.get("alignment"), int) or not 1 <= cs["alignment"] <= 9:
        raise CommandError("The alignment is 1 to 9.")
    if cs.get("format") not in O.FORMAT_KINDS:
        raise CommandError("The format must be one of %s." % ", ".join(O.FORMAT_KINDS))
    if not isinstance(cs.get("precision"), int) or not 0 <= cs["precision"] <= 8:
        raise CommandError("The precision must be 0 to 8.")
    cs["merge_across"] = bool(cs.get("merge_across"))
    return cs


def apply_cell_style(ctx, rec: dict, spec: dict) -> None:
    name = str(spec.get("name", "")).strip()
    if not valid_name(name):
        raise CommandError("Invalid cell style name.")
    cs = next((c for c in rec["cell_styles"] if c["name"].casefold() == name.casefold()), None)
    if cs is None:
        if len(rec["cell_styles"]) >= O.MAX_CELL_STYLES:
            raise CommandError("A table style holds at most %d cell styles." % O.MAX_CELL_STYLES)
        base = next(c for c in rec["cell_styles"] if c["name"] == "Data")
        cs = copy.deepcopy(base)
        cs["name"] = name
        cs["merge_across"] = False
        rec["cell_styles"].append(cs)
    for k in CELL_FIELDS:
        if k in spec:
            cs[k] = spec[k]
    for edge, val in expand_borders(spec.get("borders", {})).items():
        cur = dict(cs["borders"].get(edge) or {"visible": True, "color": 0, "lineweight": -2})
        cur.update(val)
        cs["borders"][edge] = cur
    clean_cell_style(ctx, cs)


def clean_table_style(rec: dict) -> dict:
    for k in ("text_height", "margin"):
        v = rec.get(k)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or v < 0:
            raise CommandError("%s must be zero or more." % k.replace("_", " ").capitalize())
        rec[k] = float(v)
    rec["title_row"] = bool(rec.get("title_row"))
    rec["header_row"] = bool(rec.get("header_row"))
    return rec


def style_action(ctx, action: str, a: dict) -> dict:
    d = ctx.d
    if action == "list":
        return {"styles": [r["name"] for r in d.tables["tablestyles"].values()], "current": str(ctx.var("CTABLESTYLE"))}
    name = str(a.get("name", "")).strip()
    if action in ("create", "new"):
        if not valid_name(name):
            raise CommandError("Invalid style name: up to 255 characters, none of %s." % " ".join(BAD_NAME_CHARS))
        if d.table_get("tablestyles", name) is not None:
            raise CommandError("Style %s already exists." % name)
        rec = T.new_tablestyle(d.metric, name)
        rec = fill_style(ctx, rec, a)
        d.table_set("tablestyles", rec)
        if a.get("current", True):
            ctx.setvar("CTABLESTYLE", rec["name"])
        return {"style": rec}
    rec0 = d.table_get("tablestyles", name)
    if rec0 is None:
        raise CommandError("Style %s does not exist." % name)
    if action == "current":
        ctx.setvar("CTABLESTYLE", rec0["name"])
        return {"style": rec0}
    if action == "modify":
        rec = fill_style(ctx, copy.deepcopy(rec0), a)
        d.table_set("tablestyles", rec)
        O.recalc_users(d, rec["name"])
        return {"style": rec}
    to = str(a.get("to", "")).strip()
    if action == "copy":
        if not valid_name(to) or d.table_get("tablestyles", to) is not None:
            raise CommandError("Invalid or duplicate style name.")
        rec = copy.deepcopy(rec0)
        rec["name"] = to
        d.table_set("tablestyles", rec)
        return {"style": rec}
    if action == "rename":
        if rec0["name"].casefold() == "standard":
            raise CommandError("The Standard style cannot be renamed.")
        if not valid_name(to) or d.table_get("tablestyles", to) is not None:
            raise CommandError("Invalid or duplicate style name.")
        rec = copy.deepcopy(rec0)
        rec["name"] = to
        d.table_remove("tablestyles", rec0["name"])
        d.table_set("tablestyles", rec)
        for e in list(d.ents.values()):
            if e.kind == "table" and e.style.casefold() == rec0["name"].casefold():
                d.modify(e.handle).style = to
        if str(ctx.var("CTABLESTYLE")).casefold() == rec0["name"].casefold():
            ctx.setvar("CTABLESTYLE", to)
        return {"style": rec}
    if action == "delete":
        if rec0["name"].casefold() == "standard":
            raise CommandError("The Standard style cannot be deleted.")
        if rec0["name"].casefold() == str(ctx.var("CTABLESTYLE")).casefold():
            raise CommandError("The current style cannot be deleted.")
        if rec0["name"].casefold() in styles_in_use(ctx):
            raise CommandError("Style %s is used by existing tables and cannot be deleted." % rec0["name"])
        d.table_remove("tablestyles", rec0["name"])
        return {"deleted": rec0["name"]}
    if action == "deletecellstyle":
        cname = str(a.get("cell_style", "")).strip()
        if cname in ("Title", "Header", "Data"):
            raise CommandError("The %s cell style cannot be deleted." % cname)
        rec = copy.deepcopy(rec0)
        before = len(rec["cell_styles"])
        rec["cell_styles"] = [c for c in rec["cell_styles"] if c["name"].casefold() != cname.casefold()]
        if len(rec["cell_styles"]) == before:
            raise CommandError("The cell style %s does not exist." % cname)
        d.table_set("tablestyles", rec)
        O.recalc_users(d, rec["name"])
        return {"style": rec}
    raise CommandError("Unknown TABLESTYLE action: %s." % action)


def fill_style(ctx, rec: dict, a: dict) -> dict:
    if "text_height" in a:
        h = a["text_height"]
        rec["text_height"] = h
        for cs in rec["cell_styles"]:
            if isinstance(h, (int, float)):
                cs["text_height"] = float(h) * (1.4 if cs["name"] == "Title" else 1.0)
    if "margin" in a:
        rec["margin"] = a["margin"]
        for cs in rec["cell_styles"]:
            cs["margin_h"] = cs["margin_v"] = a["margin"]
    for k in ("title_row", "header_row"):
        if k in a:
            rec[k] = bool(a[k])
    clean_table_style(rec)
    for spec in ([a["cell_style"]] if isinstance(a.get("cell_style"), dict) else []) + list(a.get("cell_styles", [])):
        apply_cell_style(ctx, rec, spec)
    for cs in rec["cell_styles"]:
        clean_cell_style(ctx, cs)
    return rec


TABLE_WORDS = ["Text height", "Margin", "Title row", "Header row", "Cell style", "eXit"]
CELL_WORDS = ["Text style", "Height", "Color", "Fill", "Align", "HMargin", "Vmargin", "FOrmat", "Precision", "Border", "Merge across", "eXit"]


def ask_cell_style(ctx, rec):
    n = yield ctx.word("Enter cell style name of table style %s" % rec["name"], default="Data")
    cname = "Data" if n.kind == "enter" else str(n.value).strip()
    spec = {"name": cname}
    while True:
        r = yield ctx.keyword("Enter an option", CELL_WORDS, "eXit")
        if r.kind != "keyword" or r.value == "eXit":
            return spec
        w = r.value
        if w in ("Height", "HMargin", "Vmargin"):
            key = {"Height": "text_height", "HMargin": "margin_h", "Vmargin": "margin_v"}[w]
            v = yield ctx.number("Specify %s" % w.lower(), minimum=0)
            if v.kind == "number":
                spec[key] = float(v.value)
        elif w == "Precision":
            v = yield ctx.number("Specify precision (0 to 8)", integer=True, minimum=0, maximum=8)
            if v.kind == "number":
                spec["precision"] = int(v.value)
        elif w == "Align":
            v = yield ctx.number("Specify alignment (1 to 9)", integer=True, minimum=1, maximum=9)
            if v.kind == "number":
                spec["alignment"] = int(v.value)
        elif w == "FOrmat":
            v = yield ctx.keyword("Enter data format", ["General", "Decimal", "Percent", "Text"], "General")
            if v.kind == "keyword":
                spec["format"] = v.value.lower()
        elif w in ("Text style", "Color", "Fill"):
            v = yield ctx.word("Enter %s" % w.lower())
            if v.kind == "text":
                key = {"Text style": "text_style", "Color": "text_color", "Fill": "fill"}[w]
                val = str(v.value).strip()
                if w == "Color":
                    val = int(val) if val.isdigit() else val
                if w == "Fill" and val.lower() == "none":
                    val = None
                spec[key] = val
        elif w == "Merge across":
            v = yield ctx.yesno("Merge across new rows?", "No")
            if v.kind == "keyword":
                spec["merge_across"] = v.value == "Yes"
        else:
            e = yield ctx.keyword("Enter border", ["Top", "Bottom", "Left", "Right", "Inside_h", "Inside_v", "Outside", "All"], "All")
            if e.kind != "keyword":
                continue
            vis = yield ctx.yesno("Visible?", "Yes")
            spec.setdefault("borders", {})[e.value.lower()] = {"visible": vis.kind != "keyword" or vis.value == "Yes"}


def ask_table_fields(ctx, rec):
    out = {}
    while True:
        r = yield ctx.keyword("Enter an option", TABLE_WORDS, "eXit")
        if r.kind != "keyword" or r.value == "eXit":
            return out
        if r.value in ("Text height", "Margin"):
            key = "text_height" if r.value == "Text height" else "margin"
            v = yield ctx.number("Specify %s" % r.value.lower(), minimum=0, default=rec.get(key))
            if v.kind == "number":
                out[key] = float(v.value)
        elif r.value in ("Title row", "Header row"):
            key = "title_row" if r.value == "Title row" else "header_row"
            v = yield ctx.yesno("%s?" % r.value, "Yes" if out.get(key, rec.get(key)) else "No")
            if v.kind == "keyword":
                out[key] = v.value == "Yes"
        else:
            spec = yield from ask_cell_style(ctx, rec)
            out.setdefault("cell_styles", []).append(spec)


@command("tablestyle", aliases=("ts",), group="format", label="Table Style...", description="Create or modify table styles.", menu="Format > Table Style...")
def tablestyle(ctx):
    r = yield ctx.keyword("Enter an option", ["?", "Current", "New", "Modify", "Copy", "Rename", "Delete"], "?")
    if r.kind == "enter":
        r.value = "?"
    elif r.kind != "keyword":
        return
    act = r.value
    if act == "?":
        cur = str(ctx.var("CTABLESTYLE"))
        for rec in ctx.d.tables["tablestyles"].values():
            ctx.say("%s - text %s, margin %s, title %s, header %s, %d cell styles%s" % (rec["name"], ctx.fd(rec["text_height"]), ctx.fd(rec["margin"]), "on" if rec["title_row"] else "off", "on" if rec["header_row"] else "off", len(rec["cell_styles"]), "  (current)" if rec["name"].casefold() == cur.casefold() else ""))
        return
    n = yield ctx.word("Enter style name" if act != "New" else "Enter name for new style", default=str(ctx.var("CTABLESTYLE")) if act != "New" else None)
    if n.kind != "text":
        return
    name = str(n.value).strip()
    if act in ("Current", "Delete"):
        style_action(ctx, act.lower(), {"name": name})
        return
    if act in ("Copy", "Rename"):
        t = yield ctx.word("Enter new style name")
        if t.kind == "text":
            style_action(ctx, act.lower(), {"name": name, "to": str(t.value).strip()})
        return
    rec = T.new_tablestyle(ctx.d.metric, name) if act == "New" else ctx.d.table_get("tablestyles", name)
    if rec is None:
        raise CommandError("Style %s does not exist." % name)
    fields = yield from ask_table_fields(ctx, rec)
    style_action(ctx, "create" if act == "New" else "modify", {"name": name, **fields})
    ctx.say("Table style %s %s." % (name, "created and made current" if act == "New" else "modified"))


@executes("tablestyle")
def tablestyle_exec(ctx, args):
    return style_action(ctx, str(args.get("action", "list")).lower(), args)
