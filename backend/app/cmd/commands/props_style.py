import fnmatch
import re

from app.cmd.context import CommandError
from app.cmd.props_flow import ask_triple
from app.cmd.prompts import Prompt
from app.cmd.registry import command, executes
from app.doc import props as P
from app.doc import tables as T
from app.sysvars import SysvarError

RESERVED = ("bylayer", "byblock", "continuous")


def _cecolor_text(v) -> str:
    if v == 256:
        return "BYLAYER"
    if v == 0:
        return "BYBLOCK"
    if isinstance(v, str) and v.startswith("#"):
        return "RGB:%d,%d,%d" % (int(v[1:3], 16), int(v[3:5], 16), int(v[5:7], 16))
    return str(v)


def _set_color(ctx, value) -> str:
    try:
        ctx.setvar("CECOLOR", value)
    except SysvarError as err:
        raise CommandError(str(err))
    return _cecolor_text(ctx.var("CECOLOR"))


@command("color", aliases=("col", "colour"), group="format", label="Color", description="Set the current colour for new objects.", menu="Format > Color...")
def color(ctx):
    cur = _cecolor_text(ctx.var("CECOLOR"))
    while True:
        r = yield Prompt("Enter default color for new objects", ("text",), ["Truecolor"], None, cur)
        if r.kind == "keyword":
            v = yield from ask_triple(ctx)
            if v is None:
                return
        elif r.kind == "text":
            try:
                v = P.parse_typed_color(r.value)
            except P.PropError as err:
                ctx.say(str(err))
                continue
        else:
            return
        ctx.say("Current color: %s" % _set_color(ctx, v))
        return


@executes("color")
def color_exec(ctx, args):
    v = args.get("color", args.get("value"))
    if v is None:
        raise CommandError("A colour is required.")
    try:
        parsed = P.parse_color(v)
    except P.PropError as err:
        raise CommandError(str(err))
    return {"color": _set_color(ctx, parsed)}


def _lw_set(ctx, hundredths) -> None:
    try:
        ctx.setvar("CELWEIGHT", hundredths)
    except SysvarError as err:
        raise CommandError(str(err))


def _lw_label(v) -> str:
    return str(P.lw_text(v))


@command("lweight", aliases=("lw", "lineweight"), group="format", label="Lineweight", description="Set the current lineweight for new objects.", menu="Format > Lineweight...")
def lweight(ctx):
    cur = int(ctx.var("CELWEIGHT"))
    while True:
        r = yield Prompt("Enter default lineweight for new objects", ("text",), ["ByLayer", "ByBlock", "Default"], None, _lw_label(cur))
        if r.kind == "keyword":
            v = r.value
        elif r.kind == "text":
            v = r.value.strip()
        else:
            return
        try:
            w, rounded = P.parse_lineweight(v)
        except P.PropError as err:
            ctx.say(str(err))
            continue
        if rounded:
            ctx.say("Lineweight rounded to nearest valid value of %s mm" % P.lw_text(w))
        _lw_set(ctx, w)
        return


@executes("lweight")
def lweight_exec(ctx, args):
    v = args.get("value", args.get("lineweight"))
    if v is None:
        raise CommandError("A lineweight is required.")
    try:
        w, rounded = P.parse_lineweight(v)
    except P.PropError as err:
        raise CommandError(str(err))
    _lw_set(ctx, w)
    return {"lineweight": P.lw_text(w), "hundredths": w, "rounded": rounded}


@command("ltscale", aliases=("lts",), group="format", label="Linetype Scale", description="Set the global linetype scale.", menu="")
def ltscale(ctx):
    cur = float(ctx.var("LTSCALE"))
    while True:
        r = yield Prompt("Enter new linetype scale factor", ("number",), [], cur, "%.4f" % cur)
        if r.kind != "number":
            return
        if r.value <= 0:
            ctx.say("Value must be positive and nonzero.")
            continue
        ctx.setvar("LTSCALE", r.value)
        return


@executes("ltscale")
def ltscale_exec(ctx, args):
    v = args.get("value", args.get("scale"))
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
        raise CommandError("Value must be positive and nonzero.")
    ctx.setvar("LTSCALE", float(v))
    return {"ltscale": float(v)}


@command("thickness", group="format", label="Thickness", description="Set the default thickness for new objects.", menu="Format > Thickness", transparent=True, undoable=False, repeatable=False)
def thickness(ctx):
    cur = float(ctx.var("THICKNESS"))
    r = yield Prompt("Enter new value for THICKNESS", ("number",), [], cur, "%.4f" % cur)
    if r.kind == "number":
        _set_thickness(ctx, r.value)


def _set_thickness(ctx, v) -> None:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or abs(v) > 1e12 or v != v:
        raise CommandError("thickness must be a finite number")
    ctx.setvar("THICKNESS", float(v))


@executes("thickness")
def thickness_exec(ctx, args):
    v = args.get("value", args.get("thickness"))
    _set_thickness(ctx, v)
    return {"thickness": float(v)}


def parse_lin(text: str) -> list:
    out = []
    cur = None
    for raw in str(text).splitlines():
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("*"):
            head = line[1:].split(",", 1)
            cur = {"name": head[0].strip(), "description": head[1].strip() if len(head) > 1 else "", "elements": [], "pattern_length": 0.0}
            out.append(cur)
        elif cur is not None and line[:1].upper() in ("A", "R", "U"):
            body = re.sub(r"\[[^\]]*\]", "", line)
            nums = [p for p in body.split(",")[1:] if p.strip()]
            els = []
            for p in nums:
                try:
                    els.append({"length": float(p)})
                except ValueError:
                    continue
            cur["elements"] = els
            cur["pattern_length"] = sum(abs(e["length"]) for e in els)
    return out


def library(ctx) -> list:
    return [r for r in T.standard_linetypes(ctx.d.metric) if r["name"].casefold() not in RESERVED]


def _names(spec) -> list:
    if isinstance(spec, (list, tuple)):
        return [str(s).strip() for s in spec if str(s).strip()]
    return [s.strip() for s in str(spec or "*").split(",") if s.strip()] or ["*"]


def _selected(records, pats) -> list:
    out = []
    for rec in records:
        if any(fnmatch.fnmatchcase(rec["name"].casefold(), p.casefold()) for p in pats):
            out.append(rec)
    return out


def load_linetypes(ctx, spec, contents=None, path=None, reload=False, ask=None) -> dict:
    pats = _names(spec)
    if contents is not None:
        records = parse_lin(contents)
        source = "inline"
    elif path:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                records = parse_lin(fh.read())
        except OSError:
            raise CommandError("Cannot open linetype file %s." % path)
        source = path
    else:
        records = library(ctx)
        source = "library"
    bad = [r["name"] for r in records if r["name"].casefold() in RESERVED]
    if bad:
        raise CommandError("%s cannot be defined by a linetype file." % ", ".join(bad))
    wanted = _selected(records, pats)
    if not wanted:
        if source == "library":
            raise CommandError('Linetype "%s" was not found in the standard library.' % ", ".join(pats))
        raise CommandError('Linetype "%s" was not found in the file.' % ", ".join(pats))
    loaded, already, reloaded = [], [], []
    for rec in wanted:
        have = ctx.d.table_get("linetypes", rec["name"])
        if have is not None:
            if reload:
                ctx.d.table_set("linetypes", rec)
                reloaded.append(rec["name"])
            else:
                already.append(rec["name"])
            continue
        ctx.d.table_set("linetypes", rec)
        loaded.append(rec["name"])
    return {"loaded": loaded, "already": already, "reloaded": reloaded}


def _report_load(ctx, res) -> None:
    if res["loaded"]:
        ctx.say("Linetype(s) %s loaded." % ", ".join(res["loaded"]))
    if res["reloaded"]:
        ctx.say("Linetype(s) %s reloaded." % ", ".join(res["reloaded"]))
    if res["already"]:
        ctx.say("Linetype(s) %s is already loaded." % ", ".join(res["already"]))


def set_current(ctx, name) -> str:
    rec = ctx.d.table_get("linetypes", str(name))
    if rec is None:
        raise CommandError('Linetype "%s" is not loaded.' % name)
    ctx.setvar("CELTYPE", rec["name"])
    ctx.say('Current linetype: "%s"' % rec["name"])
    return rec["name"]


def used_linetypes(ctx) -> set:
    used = {str(ctx.d.header.get("CELTYPE", "ByLayer")).casefold()}
    for e in ctx.d.ents.values():
        used.add(str(e.linetype).casefold())
    for rec in ctx.d.tables["layers"].values():
        used.add(str(rec.get("linetype", "")).casefold())
    for rec in ctx.d.tables["mlinestyles"].values():
        for el in rec.get("elements", []):
            used.add(str(el.get("linetype", "")).casefold())
    return used


def delete_linetypes(ctx, spec) -> list:
    pats = _names(spec)
    used = used_linetypes(ctx)
    removed = []
    for rec in list(ctx.d.tables["linetypes"].values()):
        low = rec["name"].casefold()
        if low in RESERVED or low in used:
            continue
        if any(fnmatch.fnmatchcase(low, p.casefold()) for p in pats):
            ctx.d.table_remove("linetypes", rec["name"])
            removed.append(rec["name"])
    return removed


def _list(ctx, pattern):
    recs = _selected(ctx.d.tables["linetypes"].values(), _names(pattern))
    if not recs:
        ctx.say("No matching linetypes found.")
    for rec in recs:
        ctx.say("%s  %s" % (rec["name"], rec["description"]))
    return recs


DASH_OPTS = ["?", "Load", "Set", "Delete"]


def _flow(ctx):
    r = yield ctx.keyword("Enter an option", DASH_OPTS)
    if r.kind != "keyword":
        return
    k = r.value
    if k == "?":
        t = yield Prompt("Enter linetype(s) to list", ("text",), [], "*", "*")
        _list(ctx, t.value if t.kind == "text" else "*")
    elif k == "Load":
        t = yield Prompt("Enter linetype(s) to load", ("text",), [], "*", "*")
        spec = t.value if t.kind == "text" else "*"
        f = yield Prompt("Enter name of linetype file", ("text",), [], "", "standard library")
        path = f.value.strip() if f.kind == "text" and f.value.strip() else None
        probe = load_probe(ctx, spec, path)
        reload = False
        if probe:
            y = yield ctx.yesno("Linetype %s is already loaded. Reload it?" % ", ".join(probe), "Yes")
            reload = y.kind == "keyword" and y.value == "Yes"
        _report_load(ctx, load_linetypes(ctx, spec, path=path, reload=reload))
    elif k == "Set":
        t = yield Prompt("Specify linetype name", ("text",), [], None, str(ctx.var("CELTYPE")))
        name = t.value.strip() if t.kind == "text" else str(ctx.var("CELTYPE"))
        set_current(ctx, name)
    else:
        t = yield Prompt("Enter linetype(s) to delete (unused only)", ("text",), [], "*", "*")
        removed = delete_linetypes(ctx, t.value if t.kind == "text" else "*")
        ctx.say("%d linetype(s) deleted." % len(removed) if removed else "No unused linetypes matched.")


def load_probe(ctx, spec, path):
    if path:
        return []
    return [r["name"] for r in _selected(library(ctx), _names(spec)) if ctx.d.table_get("linetypes", r["name"]) is not None]


@command("-linetype", group="format", label="Linetype (command line)", description="List, load, set or delete linetypes.", menu="")
def linetype_dash(ctx):
    yield from _flow(ctx)


@command("linetype", aliases=("lt", "ltype"), group="format", label="Linetype", description="Set the current linetype and load linetypes.", menu="Format > Linetype...")
def linetype(ctx):
    yield from _flow(ctx)


@executes("linetype", "-linetype")
def linetype_exec(ctx, args):
    out = {}
    if args.get("list") is not None:
        out["linetypes"] = [{"name": r["name"], "description": r["description"]} for r in _selected(ctx.d.tables["linetypes"].values(), _names(args["list"]))]
    if args.get("load") is not None or args.get("contents") is not None or args.get("file") is not None:
        res = load_linetypes(ctx, args.get("load", "*"), contents=args.get("contents"), path=args.get("file"), reload=bool(args.get("reload", False)))
        _report_load(ctx, res)
        out.update(res)
    if args.get("delete") is not None:
        out["deleted"] = delete_linetypes(ctx, args["delete"])
    if args.get("purge_unused"):
        out["deleted"] = out.get("deleted", []) + delete_linetypes(ctx, "*")
    cur = args.get("set", args.get("current"))
    if cur is not None:
        out["current"] = set_current(ctx, cur)
    if not out:
        raise CommandError("Give set, load, list or delete.")
    return out
