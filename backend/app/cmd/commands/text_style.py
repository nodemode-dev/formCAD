import copy
import math

from app.cmd.commands import text_common as tc
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.doc import tables as T

STYLE_KINDS = ("text", "mtext", "attdef")


def _same(a, b):
    return str(a).casefold() == str(b).casefold()


def _need(ctx, name):
    rec = ctx.d.table_get("textstyles", str(name).strip())
    if rec is None:
        raise CommandError("Text style %s not found." % str(name).strip())
    return rec


def users(ctx, name):
    d = ctx.d
    out = []
    for ent in d.ents.values():
        if ent.kind in STYLE_KINDS and _same(ent.style, name):
            out.append(("e", ent.handle))
        elif ent.kind not in STYLE_KINDS and _same(getattr(ent, "text_style", ""), name):
            out.append(("e", ent.handle))
    for rec in d.tables["dimstyles"].values():
        if _same(rec.get("vars", {}).get("DIMTXSTY", ""), name):
            out.append(("d", rec["name"]))
    for rec in d.tables["mleaderstyles"].values():
        if _same(rec.get("text_style", ""), name):
            out.append(("m", rec["name"]))
    for rec in d.tables["tablestyles"].values():
        if any(_same(c.get("text_style", ""), name) for c in rec.get("cell_styles", [])):
            out.append(("t", rec["name"]))
    return out


def retarget(ctx, old, new):
    d = ctx.d
    for kind, ref in users(ctx, old):
        if kind == "e":
            ent = d.modify(ref)
            if ent.kind in STYLE_KINDS:
                ent.style = new
            else:
                ent.text_style = new
        elif kind == "d":
            d.modify_record("dimstyles", ref)["vars"]["DIMTXSTY"] = new
        elif kind == "m":
            d.modify_record("mleaderstyles", ref)["text_style"] = new
        else:
            for c in d.modify_record("tablestyles", ref).get("cell_styles", []):
                if _same(c.get("text_style", ""), old):
                    c["text_style"] = new


def apply_style(ctx, name, props, current=True):
    name = tc.check_name(name)
    d = ctx.d
    existing = d.table_get("textstyles", name)
    rec = copy.deepcopy(existing) if existing else T.new_textstyle(name)
    if "font" in props:
        font = str(props["font"]).strip()
        if not font or len(font) > 255:
            raise CommandError("Invalid font name.")
        rec["font"] = font
    if "big_font" in props:
        big = str(props["big_font"] or "").strip()
        rec["big_font"] = "" if big.lower() == "none" else big
    if props.get("height") is not None:
        h = float(props["height"])
        if h < 0 or not math.isfinite(h):
            raise CommandError("Height must not be negative.")
        rec["height"] = h
    if props.get("width_factor") is not None:
        w = float(props["width_factor"])
        if not 0.01 <= w <= 100:
            raise CommandError("Requires a width factor between 0.01 and 100.")
        rec["width_factor"] = w
    if props.get("oblique") is not None:
        a = float(props["oblique"])
        if not -85.0 <= a <= 85.0:
            raise CommandError("Requires an oblique angle between -85 and 85 degrees.")
        rec["oblique"] = math.radians(a)
    for key in ("backwards", "upside_down", "vertical", "annotative"):
        if props.get(key) is not None:
            rec[key] = bool(props[key])
    d.table_set("textstyles", rec)
    if current:
        ctx.setvar("TEXTSTYLE", rec["name"])
    return rec, existing is None


def rename_style(ctx, old, new):
    rec = _need(ctx, old)
    if _same(rec["name"], "Standard"):
        raise CommandError("The Standard text style cannot be renamed.")
    new = tc.check_name(new)
    clash = ctx.d.table_get("textstyles", new)
    if clash is not None and not _same(clash["name"], rec["name"]):
        raise CommandError("A text style named %s already exists." % clash["name"])
    was_current = _same(ctx.d.header.get("TEXTSTYLE", "Standard"), rec["name"])
    old_name = rec["name"]
    moved = copy.deepcopy(rec)
    moved["name"] = new
    retarget(ctx, old_name, new)
    ctx.d.table_remove("textstyles", old_name)
    ctx.d.table_set("textstyles", moved)
    if was_current:
        ctx.setvar("TEXTSTYLE", new)
    return moved


def delete_style(ctx, name):
    rec = _need(ctx, name)
    if _same(rec["name"], "Standard"):
        raise CommandError("The Standard text style cannot be deleted.")
    if _same(rec["name"], ctx.d.header.get("TEXTSTYLE", "Standard")):
        raise CommandError("The current text style cannot be deleted.")
    if users(ctx, rec["name"]):
        raise CommandError("Text style %s is in use and cannot be deleted." % rec["name"])
    ctx.d.table_remove("textstyles", rec["name"])
    return rec["name"]


def set_current(ctx, name):
    rec = _need(ctx, name)
    ctx.setvar("TEXTSTYLE", rec["name"])
    return rec["name"]


def _result(ctx, extra=None):
    out = {"styles": tc.style_rows(ctx), "current": str(ctx.d.header.get("TEXTSTYLE", "Standard"))}
    if extra:
        out.update(extra)
    return out


def _yes(r, default):
    if r.kind == "keyword":
        return r.value == "Yes"
    return default


@command("-style", group="format", label="Text Style (command line)", description="Create or modify a text style at the command line.", menu="")
@command("style", aliases=("st",), group="format", label="Text Style...", description="Create or modify a text style.", menu="Format > Text Style...")
def style(ctx):
    cur = str(ctx.d.header.get("TEXTSTYLE", "Standard"))
    while True:
        r = yield ctx.text("Enter name of text style or [?]", cur)
        if r.kind != "text":
            return
        name = str(r.value).strip()
        if name == "?":
            p = yield ctx.text("Enter text style(s) to list", "*")
            tc.say_styles(ctx, str(p.value) if p.kind == "text" else "*")
            continue
        try:
            tc.check_name(name)
        except CommandError as err:
            ctx.say(str(err))
            continue
        break
    existing = ctx.d.table_get("textstyles", name)
    base = existing or T.new_textstyle(name)
    ctx.say("Existing style." if existing else "New style.")
    props = {}
    f = yield ctx.text("Specify full font name or font file name (TTF or OTF)", base["font"])
    if f.kind != "text":
        return
    props["font"] = f.value
    if not tc.is_outline(f.value):
        big = yield ctx.text("Enter big font file name or [None]", base.get("big_font") or "None")
        if big.kind != "text":
            return
        props["big_font"] = big.value
    an = yield ctx.yesno("Annotative?", "Yes" if base.get("annotative") else "No")
    props["annotative"] = _yes(an, bool(base.get("annotative")))
    h = yield ctx.number("Specify height of text", default=float(base["height"]), minimum=0, default_text=ctx.fd(float(base["height"])))
    if h.kind == "number":
        props["height"] = float(h.value)
    w = yield ctx.number("Specify width factor", default=float(base["width_factor"]), minimum=0.01, maximum=100, default_text="%.4f" % float(base["width_factor"]))
    if w.kind == "number":
        props["width_factor"] = float(w.value)
    o = yield ctx.number("Specify obliquing angle", default=math.degrees(float(base["oblique"])), minimum=-85, maximum=85, default_text="%g" % round(math.degrees(float(base["oblique"])), 6))
    if o.kind == "number":
        props["oblique"] = float(o.value)
    b = yield ctx.yesno("Display text backwards?", "Yes" if base.get("backwards") else "No")
    props["backwards"] = _yes(b, bool(base.get("backwards")))
    u = yield ctx.yesno("Display text upside-down?", "Yes" if base.get("upside_down") else "No")
    props["upside_down"] = _yes(u, bool(base.get("upside_down")))
    v = yield ctx.yesno("Vertical?", "Yes" if base.get("vertical") else "No")
    props["vertical"] = _yes(v, bool(base.get("vertical")))
    rec, _created = apply_style(ctx, name, props, True)
    ctx.say('"%s" is now the current text style.' % rec["name"])


@executes("style", "-style")
def style_exec(ctx, args):
    name = args.get("name")
    if not name:
        return _result(ctx)
    props = {k: args[k] for k in ("font", "big_font", "height", "width_factor", "oblique", "backwards", "upside_down", "vertical", "annotative") if k in args}
    rec, created = apply_style(ctx, name, props, bool(args.get("current", True)))
    return _result(ctx, {"name": rec["name"], "created": created})


@command("style.list", group="format", label="List Text Styles", description="List text styles.")
def style_list(ctx):
    p = yield ctx.text("Enter text style(s) to list", "*")
    tc.say_styles(ctx, str(p.value) if p.kind == "text" else "*")


@executes("style.list")
def style_list_exec(ctx, args):
    return _result(ctx)


@command("style.rename", group="format", label="Rename Text Style", description="Rename a text style.")
def style_rename(ctx):
    o = yield ctx.text("Enter old style name")
    if o.kind != "text":
        return
    n = yield ctx.text("Enter new style name")
    if n.kind != "text":
        return
    rec = rename_style(ctx, o.value, n.value)
    ctx.say('Text style renamed to "%s".' % rec["name"])


@executes("style.rename")
def style_rename_exec(ctx, args):
    rec = rename_style(ctx, args.get("name", ""), args.get("new_name", ""))
    return _result(ctx, {"name": rec["name"]})


@command("style.delete", group="format", label="Delete Text Style", description="Delete an unused text style.")
def style_delete(ctx):
    n = yield ctx.text("Enter style name to delete")
    if n.kind != "text":
        return
    ctx.say('Text style "%s" deleted.' % delete_style(ctx, n.value))


@executes("style.delete")
def style_delete_exec(ctx, args):
    gone = delete_style(ctx, args.get("name", ""))
    return _result(ctx, {"deleted": gone})


@command("style.current", group="format", label="Set Current Text Style", description="Make a text style current.")
def style_current(ctx):
    n = yield ctx.text("Enter style name to make current", str(ctx.d.header.get("TEXTSTYLE", "Standard")))
    if n.kind != "text":
        return
    ctx.say('"%s" is now the current text style.' % set_current(ctx, n.value))


@executes("style.current")
def style_current_exec(ctx, args):
    return _result(ctx, {"name": set_current(ctx, args.get("name", ""))})
