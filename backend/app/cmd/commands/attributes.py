import math

from app.cmd import jig
from app.cmd.commands import text_common as tc
from app.cmd.commands.blocks import ask_name, ask_yes, list_names
from app.cmd.commands.draw import anum, dnum
from app.cmd.commands.modify import LOCKED_MSG, targets
from app.cmd.commands.text_draw import _ask_style
from app.cmd.context import CommandError
from app.cmd.draw_support import pick_entity
from app.cmd.prompts import Prompt
from app.cmd.registry import command, executes
from app.doc import attribs, battman, blockdefs, geom, wildcard
from app.doc.entities import Insert
from app.doc.model import block_space
from app.sysvars import registry as sv

MODE_OPTS = ["Invisible", "Constant", "Verify", "Preset", "Lock position", "Annotative", "Multiple lines"]
MODE_KEYS = {"Invisible": "invisible", "Constant": "constant", "Verify": "verify", "Preset": "preset", "Lock position": "lock_position", "Annotative": "annotative", "Multiple lines": "multiline"}
JUSTIFY_ATT = ["Left", "Center", "Right", "Middle", "TL", "TC", "TR", "ML", "MC", "MR", "BL", "BC", "BR"]
ATTMODE_WORDS = {1: "Normal", 2: "ON", 0: "OFF"}


def modes_line(modes: dict) -> str:
    return "Current attribute modes: " + " ".join("%s=%s" % (o, "Yes" if modes.get(MODE_KEYS[o]) else "No") for o in MODE_OPTS)


def ask_line(ctx, message: str, default=None):
    r = yield ctx.text(message, default)
    if r.kind == "text":
        return str(r.value)
    if r.kind == "enter":
        return ""
    return None


def settle(ctx, handle) -> None:
    live = ctx.d.modify(handle)
    if live.align_point is None or int(live.halign) in (3, 5):
        return
    g = tc.shape_of(ctx, attribs.display_text(live))[0]
    live.position = [float(g["insert"][0]), float(g["insert"][1]), 0.0]


def place_attdef(ctx, adef, block=None) -> int:
    try:
        if block is None:
            h = ctx.add(adef)
        else:
            rec = blockdefs.lookup(ctx.d, block)
            if rec is None:
                raise CommandError('Block "%s" not found.' % block)
            ctx.stamp(adef)
            h = ctx.d.add_entity(adef, block_space(rec["name"]))
    except ValueError as err:
        raise CommandError(str(err))
    settle(ctx, h)
    return h


def _tick(ctx, rec, rot=0.0):
    h = rec["height"] or tc.default_height(ctx)
    u, _v = tc.frame(rot)
    return lambda p: [jig.line(p, [p[0] + u[0] * h, p[1] + u[1] * h])]


def attdef_flow(ctx):
    modes = dict(ctx.mem.get("attdef_modes") or {k: False for k in MODE_KEYS.values()})
    ctx.say(modes_line(modes))
    while True:
        p = Prompt("Enter an option to change", ("keyword",), list(MODE_OPTS), None, "done", hint="bare")
        r = yield p
        if r.kind != "keyword":
            break
        key = MODE_KEYS[r.value]
        modes[key] = not modes.get(key, False)
        ctx.say(modes_line(modes))
    ctx.mem["attdef_modes"] = dict(modes)
    while True:
        tag = yield from ask_line(ctx, "Enter attribute tag name")
        if tag is None:
            return
        try:
            tag = attribs.normalize_tag(tag)
        except attribs.AttribError as err:
            ctx.say(str(err))
            continue
        break
    prompt = yield from ask_line(ctx, "Enter attribute prompt")
    if prompt is None:
        return
    default = yield from ask_line(ctx, "Enter attribute value" if modes.get("constant") else "Enter default attribute value")
    if default is None:
        return
    just = "Left"
    while True:
        rec = tc.style_record(ctx)
        ctx.say('Current text style: "%s" Text height: %s Justify: %s' % (rec["name"], ctx.fd(rec["height"] or tc.default_height(ctx)), just))
        msg = "Specify start point" if just == "Left" else tc.JUSTIFY[just][2]
        r = yield ctx.point(msg, ["Justify", "Style"], jig=_tick(ctx, rec))
        if r.kind == "keyword" and r.value == "Style":
            name = yield from _ask_style(ctx)
            if name:
                ctx.setvar("TEXTSTYLE", name)
            continue
        if r.kind == "keyword":
            j = yield ctx.keyword("Enter an option", JUSTIFY_ATT)
            if j.kind == "keyword":
                just = j.value
            continue
        if r.kind != "point":
            return
        p1 = r.value
        break
    ha, va, _m = tc.JUSTIFY[just]
    ap = p1 if just != "Left" else None
    if rec["height"]:
        height = rec["height"]
    else:
        dflt = tc.default_height(ctx)
        h = yield ctx.distance("Specify height", base=p1, default=dflt, positive=True, jig=lambda q: jig.rubber(p1, q))
        if h.kind == "enter":
            height = dflt
        else:
            height = dnum(h, p1)
            if height is None:
                return
    a = yield ctx.angle("Specify rotation angle of text", default=0.0, base=p1, jig=lambda q: jig.rubber(p1, q))
    rot = 0.0 if a.kind == "enter" else anum(a, p1)
    if rot is None:
        return
    adef = attribs.adef_from_text_args(p1, tag, prompt, default, height, rot, rec["name"], modes, ha, va, ap)
    place_attdef(ctx, adef)


@command("attdef", aliases=("att",), group="draw", label="Define Attributes", description="Define an attribute: tag, prompt, default, modes and text placement.", menu="Draw > Block > Define Attributes...")
def attdef_cmd(ctx):
    yield from attdef_flow(ctx)


@command("-attdef", group="draw", label="Attribute definition (command line)", description="Command-line ATTDEF.", menu="")
def attdef_dash(ctx):
    yield from attdef_flow(ctx)


@executes("attdef", "-attdef")
def attdef_exec(ctx, args):
    if args.get("point") is None:
        raise CommandError("An insertion point is required.")
    try:
        tag = attribs.normalize_tag(args.get("tag"))
    except attribs.AttribError as err:
        raise CommandError(str(err))
    modes = {k: bool(args.get(k, False)) for k in MODE_KEYS.values()}
    rec = tc.style_record(ctx, args.get("style"))
    height = float(args["height"]) if args.get("height") is not None else (rec["height"] or tc.default_height(ctx))
    if not height > 0 or not math.isfinite(height):
        raise CommandError("Height must be positive.")
    key = str(args.get("justify", "Left")).strip().lower()
    just = tc.JUSTIFY_WORDS.get(key)
    if just is None or just in ("Align", "Fit"):
        raise CommandError("Invalid justification.")
    ha, va, _m = tc.JUSTIFY[just]
    pos = geom.as_pt(args["point"])
    ap = pos if just != "Left" else None
    try:
        adef = attribs.adef_from_text_args(pos, tag, args.get("prompt", ""), args.get("default", ""), height, math.radians(float(args.get("rotation", 0.0))), rec["name"], modes, ha, va, ap)
    except attribs.AttribError as err:
        raise CommandError(str(err))
    if args.get("width_factor") is not None:
        adef.width_factor = float(args["width_factor"])
    h = place_attdef(ctx, adef, args.get("block"))
    return {"handle": h, "tag": tag}


def _ins_of(ctx, value):
    e = pick_entity(ctx, value)
    return e if isinstance(e, Insert) else None


def edit_values(ctx, ins, values: dict) -> int:
    live = ctx.d.modify(ins.handle)
    n = 0
    for tag, val in values.items():
        att = attribs.find(live, tag)
        if att is None:
            raise CommandError('Block reference has no attribute "%s".' % tag)
        try:
            att["value"] = attribs.check_value(val)
        except attribs.AttribError as err:
            raise CommandError(str(err))
        n += 1
    attribs.refresh_cache(ctx.d, live)
    return n


def attedit_flow(ctx):
    ins = None
    while ins is None:
        r = yield ctx.entity("Select block reference")
        if r.kind != "entity":
            return
        ins = _ins_of(ctx, r.value)
        if ins is None:
            ctx.say("Select a block reference.")
    if not ins.attributes:
        ctx.say("That block reference has no editable attributes.")
        return
    if ctx.locked(ins):
        ctx.say(LOCKED_MSG)
        return
    answers = {}
    for att in ins.attributes:
        got = yield ctx.text("Enter value for %s" % att["tag"], att.get("value", ""))
        if got.kind not in ("text", "enter"):
            return
        answers[att["tag"]] = att.get("value", "") if got.kind == "enter" else str(got.value)
    try:
        edit_values(ctx, ins, answers)
    except CommandError as err:
        ctx.say(str(err))


@command("attedit", aliases=("ate", "eattedit"), group="modify", label="Edit Attribute", description="Edit the attribute values of one block reference in turn.", menu="Modify > Object > Attribute > Single...")
def attedit_cmd(ctx):
    yield from attedit_flow(ctx)


@executes("attedit")
def attedit_exec(ctx, args):
    h = args.get("handle")
    if h is None:
        found = targets(ctx, args)
        h = found[0] if found else None
    ins = ctx.d.get(int(h)) if h is not None else None
    if not isinstance(ins, Insert):
        raise CommandError("Select a block reference.")
    if not ins.attributes:
        raise CommandError("That block reference has no editable attributes.")
    if ctx.locked(ins):
        raise CommandError(LOCKED_MSG)
    values = args.get("values") or {}
    if not isinstance(values, dict):
        raise CommandError("values must map tags to new values.")
    return {"changed": edit_values(ctx, ins, values), "handle": ins.handle}


def spec_value_match(spec: str, value: str) -> bool:
    if spec == "\\":
        return value == ""
    return wildcard.matches(wildcard.compile_spec(spec), value)


def choose_attributes(ctx, handles, block_spec="*", tag_spec="*", value_spec="*", visible=True) -> list:
    b = wildcard.compile_spec(block_spec or "*")
    t = wildcard.compile_spec(tag_spec or "*")
    attmode = int(ctx.d.header.get("ATTMODE", 1))
    out = []
    for h in handles:
        ins = ctx.d.get(h)
        if not isinstance(ins, Insert) or not wildcard.matches(b, ins.block):
            continue
        if visible and (not ctx.d.visible(ins) or attmode == 0):
            continue
        for att in ins.attributes or []:
            if not wildcard.matches(t, att.get("tag", "")) or not spec_value_match(value_spec or "*", att.get("value", "")):
                continue
            if visible and not att.get("vis", True) and attmode != 2:
                continue
            out.append((ins.handle, att["tag"]))
    return out


def change_attribute(ctx, handle, tag, edits: dict) -> bool:
    ins = ctx.d.get(handle)
    if ins is None or ctx.locked(ins):
        return False
    live = ctx.d.modify(handle)
    att = attribs.find(live, tag)
    if att is None:
        return False
    if "value" in edits:
        att["value"] = attribs.check_value(edits["value"])
    for key in ("layer", "color", "linetype", "lineweight"):
        if key in edits:
            att[key] = edits[key]
    return True


def replace_in(value: str, old: str, new: str) -> str:
    return new if old == "" else value.replace(old, new)


def one_at_a_time(ctx, chosen):
    for handle, tag in chosen:
        while True:
            ins = ctx.d.get(handle)
            att = attribs.find(ins, tag) if ins is not None else None
            if att is None:
                break
            ctx.say("%s = %s" % (att["tag"], att.get("value", "")))
            r = yield Prompt("Enter an option", ("keyword",), ["Value", "Layer", "Color", "Next"], "Next", "Next", hint="bare")
            if r.kind != "keyword" or r.value == "Next":
                break
            if r.value == "Value":
                mode = yield ctx.keyword("Enter type of value modification", ["Change", "Replace"], "Replace")
                if mode.kind != "keyword":
                    break
                if mode.value == "Replace":
                    nv = yield from ask_line(ctx, "Enter new attribute value")
                    if nv is None:
                        break
                    new_value = nv
                else:
                    old = yield from ask_line(ctx, "Enter string to change")
                    new = yield from ask_line(ctx, "Enter new string")
                    if old is None or new is None:
                        break
                    new_value = replace_in(att.get("value", ""), old, new)
                try:
                    change_attribute(ctx, handle, tag, {"value": new_value})
                except attribs.AttribError as err:
                    ctx.say(str(err))
            elif r.value == "Layer":
                name = yield from ask_line(ctx, "Enter new layer name")
                if not name:
                    continue
                rec = ctx.d.layer(name)
                if rec is None:
                    ctx.say('Cannot find layer "%s".' % name)
                    continue
                change_attribute(ctx, handle, tag, {"layer": rec["name"]})
            else:
                text = yield from ask_line(ctx, "Enter new color")
                if not text:
                    continue
                try:
                    col = sv.parse_color(text)
                except sv.SysvarError:
                    ctx.say("Invalid color name or number.")
                    continue
                change_attribute(ctx, handle, tag, {"color": col})


def attedit_dash_flow(ctx):
    each = yield from ask_yes(ctx, "Edit attributes one at a time?", "Yes")
    visible = yield from ask_yes(ctx, "Edit only attributes visible on screen?", "Yes")
    b = yield from ask_line(ctx, "Enter block name specification", "*")
    t = yield from ask_line(ctx, "Enter attribute tag specification", "*")
    v = yield from ask_line(ctx, "Enter attribute value specification", "*")
    if b is None or t is None or v is None:
        return
    s = yield ctx.select("Select attributes")
    if s.kind != "selection":
        return
    chosen = choose_attributes(ctx, s.value, b, t, v, visible)
    ctx.say("%d attribute(s) selected." % len(chosen))
    if not chosen:
        return
    if each:
        yield from one_at_a_time(ctx, chosen)
        return
    old = yield from ask_line(ctx, "Enter string to change")
    new = yield from ask_line(ctx, "Enter new string")
    if old is None or new is None:
        return
    ctx.say("Performing global editing of attribute values.")
    changed = 0
    for handle, tag in chosen:
        ins = ctx.d.get(handle)
        att = attribs.find(ins, tag) if ins is not None else None
        if att is None:
            continue
        try:
            if change_attribute(ctx, handle, tag, {"value": replace_in(att.get("value", ""), old, new)}):
                changed += 1
        except attribs.AttribError as err:
            ctx.say("%s: %s" % (tag, err))
    ctx.say("%d attribute(s) changed." % changed)


@command("-attedit", aliases=("-ate", "atte"), group="modify", label="Edit Attributes (command line)", description="Edit attributes chosen by block, tag and value, one at a time or globally.", menu="Modify > Object > Attribute > Global")
def attedit_dash(ctx):
    yield from attedit_dash_flow(ctx)


@executes("-attedit")
def attedit_dash_exec(ctx, args):
    handles = targets(ctx, args) if ("handles" in args or "handle" in args) else [e.handle for e in ctx.visible_entities() if e.kind == "insert"]
    chosen = choose_attributes(ctx, handles, str(args.get("block", "*")), str(args.get("tag", "*")), str(args.get("value", "*")), bool(args.get("visible", True)))
    changed = 0
    edits = dict(args.get("set") or {})
    if "color" in edits:
        try:
            edits["color"] = sv.parse_color(edits["color"])
        except sv.SysvarError:
            raise CommandError("Invalid color name or number.")
    if "layer" in edits:
        rec = ctx.d.layer(str(edits["layer"]))
        if rec is None:
            raise CommandError('Cannot find layer "%s".' % edits["layer"])
        edits["layer"] = rec["name"]
    skipped = []
    for handle, tag in chosen:
        ins = ctx.d.get(handle)
        att = attribs.find(ins, tag) if ins is not None else None
        if att is None:
            continue
        step = dict(edits)
        if args.get("find") is not None:
            step["value"] = replace_in(att.get("value", ""), str(args["find"]), str(args.get("replace", "")))
        try:
            if step and change_attribute(ctx, handle, tag, step):
                changed += 1
        except attribs.AttribError:
            skipped.append(tag)
    return {"selected": len(chosen), "changed": changed, "refused": skipped}


@command("attdisp", group="view", label="Attribute Display", description="Set attribute display: Normal, ON or OFF.", menu="View > Attribute Display")
def attdisp_cmd(ctx):
    cur = ATTMODE_WORDS.get(int(ctx.var("ATTMODE")), "Normal")
    r = yield ctx.keyword("Enter attribute visibility setting", ["Normal", "ON", "OFF"], cur)
    if r.kind == "keyword":
        ctx.setvar("ATTMODE", {"Normal": 1, "ON": 2, "OFF": 0}[r.value])


@executes("attdisp")
def attdisp_exec(ctx, args):
    word = str(args.get("mode", "normal")).strip().lower()
    mode = {"normal": 1, "on": 2, "off": 0}.get(word)
    if mode is None:
        raise CommandError("Mode must be normal, on or off.")
    ctx.setvar("ATTMODE", mode)
    return {"mode": mode}


def sync_message(ctx, name: str) -> int:
    rec = blockdefs.lookup(ctx.d, name)
    if rec is None:
        raise CommandError('Block "%s" not found.' % name)
    if not attribs.definitions(ctx.d, rec["name"]):
        raise CommandError('Block "%s" has no attribute definitions.' % rec["name"])
    n = attribs.sync_block(ctx.d, rec["name"])
    ctx.say("ATTSYNC block %s: %d reference(s) synchronized." % (rec["name"], n))
    return n


def attsync_flow(ctx):
    while True:
        r = yield ctx.keyword("Enter an option", ["?", "Name", "Select"], "Select")
        if r.kind != "keyword":
            return
        if r.value == "?":
            p = yield ctx.text("Enter block name(s) to list", "*")
            spec = str(p.value) if p.kind == "text" else "*"
            rows = [n for n in wildcard.filter_names(spec, blockdefs.names(ctx.d)) if attribs.definitions(ctx.d, n)]
            ctx.say("Blocks with attributes: " + ", ".join(rows) if rows else "(none)")
            continue
        if r.value == "Name":
            name = yield from ask_name(ctx, "Enter block name")
            if name is None:
                return
        else:
            name = None
            while name is None:
                e = yield ctx.entity("Select a block reference")
                if e.kind != "entity":
                    return
                ins = _ins_of(ctx, e.value)
                if ins is None:
                    ctx.say("Select a block reference.")
                    continue
                name = ins.block
        rec = blockdefs.lookup(ctx.d, name)
        if rec is None:
            ctx.say('Block "%s" not found.' % name)
            continue
        if not attribs.definitions(ctx.d, rec["name"]):
            ctx.say('Block "%s" has no attribute definitions.' % rec["name"])
            return
        if (yield from ask_yes(ctx, "ATTSYNC block %s?" % rec["name"], "Yes")):
            try:
                sync_message(ctx, rec["name"])
            except CommandError as err:
                ctx.say(str(err))
        return


@command("attsync", group="modify", label="Synchronize Attributes", description="Rebuild every reference of a block from its attribute definitions.", menu="Modify > Object > Attribute > Synchronize")
def attsync_cmd(ctx):
    yield from attsync_flow(ctx)


@executes("attsync")
def attsync_exec(ctx, args):
    name = str(args.get("name") or args.get("block") or "")
    return {"block": name, "synchronized": sync_message(ctx, name)}


def list_defs(ctx, name: str) -> None:
    rows = battman.listing(ctx.d, name)
    if not rows:
        ctx.say("(no attribute definitions)")
    for r in rows:
        flags = [k for k, v in r["modes"].items() if v]
        ctx.say("%s  prompt=%s  default=%s  height=%s%s" % (r["tag"], r["prompt"], r["default"], ctx.fd(r["height"]), ("  " + ",".join(flags)) if flags else ""))


def battman_flow(ctx):
    name = None
    while name is None:
        got = yield from ask_name(ctx, "Enter name of block to manage")
        if got is None:
            return
        rec = blockdefs.lookup(ctx.d, got)
        if rec is None:
            ctx.say('Block "%s" not found.' % got)
            continue
        name = rec["name"]
    while True:
        p = Prompt('Block %s: enter an option' % name, ("keyword",), ["Edit", "Remove", "moveUp", "moveDown", "Sync", "List", "eXit"], "eXit", "eXit", hint="bare")
        r = yield p
        if r.kind != "keyword" or r.value == "eXit":
            return
        try:
            if r.value == "List":
                list_defs(ctx, name)
            elif r.value == "Sync":
                ctx.say("%d reference(s) synchronized." % battman.sync(ctx.d, name))
            elif r.value in ("Remove", "moveUp", "moveDown"):
                tag = yield from ask_line(ctx, "Enter attribute tag")
                if not tag:
                    continue
                if r.value == "Remove":
                    battman.remove(ctx.d, name, tag)
                    ctx.say("Attribute %s removed." % tag.upper())
                else:
                    res = battman.move(ctx.d, name, tag, -1 if r.value == "moveUp" else 1)
                    ctx.say("Order: " + ", ".join(res["order"]))
            else:
                tag = yield from ask_line(ctx, "Enter attribute tag")
                if not tag:
                    continue
                adef = attribs.definition(ctx.d, name, tag)
                if adef is None:
                    ctx.say('Block "%s" has no attribute tagged "%s".' % (name, tag))
                    continue
                yield from battman_props(ctx, name, adef.tag)
        except (battman.BattmanError, attribs.AttribError) as err:
            ctx.say(str(err))


def battman_props(ctx, name: str, tag: str):
    while True:
        adef = attribs.definition(ctx.d, name, tag)
        p = Prompt("Enter an option to change", ("keyword",), ["Tag", "Prompt", "Default", "Invisible", "Constant", "Height", "Layer", "eXit"], "eXit", "eXit", hint="bare")
        r = yield p
        if r.kind != "keyword" or r.value == "eXit":
            return
        try:
            if r.value in ("Tag", "Prompt", "Default", "Layer"):
                key = r.value.lower()
                cur = {"tag": adef.tag, "prompt": adef.prompt, "default": adef.default, "layer": adef.layer}[key]
                v = yield from ask_line(ctx, "Enter new %s" % key, cur)
                if v is None:
                    return
                res = battman.edit(ctx.d, name, tag, {key: v})
                tag = res["tag"]
            elif r.value in ("Invisible", "Constant"):
                key = r.value.lower()
                yes = yield from ask_yes(ctx, "%s?" % r.value, "Yes" if adef.modes.get(key) else "No")
                battman.edit(ctx.d, name, tag, {key: yes})
            else:
                h = yield ctx.distance("Specify new height", default=adef.height, positive=True)
                if h.kind in ("number", "enter"):
                    battman.edit(ctx.d, name, tag, {"height": adef.height if h.kind == "enter" else h.value})
        except (battman.BattmanError, attribs.AttribError) as err:
            ctx.say(str(err))


@command("battman", group="modify", label="Block Attribute Manager", description="Manage the attribute definitions of a block: edit, remove, reorder, synchronize.", menu="Modify > Object > Attribute > Block Attribute Manager...")
def battman_cmd(ctx):
    yield from battman_flow(ctx)


@executes("battman")
def battman_exec(ctx, args):
    name = str(args.get("block") or args.get("name") or "")
    op = str(args.get("op", "list")).lower()
    sync = bool(args.get("sync", True))
    try:
        if op == "list":
            return {"attributes": battman.listing(ctx.d, name)}
        if op == "edit":
            return battman.edit(ctx.d, name, str(args.get("tag", "")), dict(args.get("changes") or {}), sync)
        if op == "remove":
            return battman.remove(ctx.d, name, str(args.get("tag", "")), sync)
        if op == "order":
            return battman.reorder(ctx.d, name, list(args.get("tags") or []), sync)
        if op == "up":
            return battman.move(ctx.d, name, str(args.get("tag", "")), -1, sync)
        if op == "down":
            return battman.move(ctx.d, name, str(args.get("tag", "")), 1, sync)
        if op == "sync":
            return {"synchronized": battman.sync(ctx.d, name)}
    except (battman.BattmanError, attribs.AttribError) as err:
        raise CommandError(str(err))
    raise CommandError("Unknown operation: %s." % op)
