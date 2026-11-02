import math

from app.cmd import jig
from app.cmd.commands.draw import anum
from app.cmd.commands.modify import _erase, targets
from app.cmd.context import CommandError
from app.cmd.prompts import Prompt
from app.cmd.registry import command, executes
from app.doc import attribs, blockdefs, blockio, geom, wildcard
from app.doc.entities import Insert

PRESET_WORDS = ["Basepoint", "Scale", "X", "Y", "Z", "Rotate"]
EXPLODE_WORDS = ["Basepoint", "Scale", "Rotate"]
MAX_GHOST = 2000


def say_blocks(ctx, spec: str = "*") -> None:
    found = wildcard.filter_names(spec, blockdefs.names(ctx.d))
    ctx.say("Defined blocks: " + ", ".join(found) if found else "(none)")


def list_names(ctx):
    p = yield ctx.text("Enter block name(s) to list", "*")
    say_blocks(ctx, str(p.value) if p.kind == "text" else "*")


def ask_name(ctx, message: str = "Enter block name or [?]", default=None):
    while True:
        r = yield ctx.text(message, default)
        if r.kind != "text":
            return None
        t = str(r.value).strip()
        if t == "?":
            yield from list_names(ctx)
            continue
        if not t:
            return None
        return t


def ask_yes(ctx, message: str, default: str = "No"):
    r = yield ctx.yesno(message, default)
    return r.kind == "keyword" and r.value == "Yes"


def ordered(ctx, handles) -> list:
    order = {h: i for i, h in enumerate(ctx.d.spaces.get(ctx.doc.current_space, ()))}
    return sorted(handles, key=lambda h: order.get(h, len(order)))


def make_block(ctx, name, handles, base, mode, redefine=False, description="", annotative=False, explodable=True) -> dict:
    handles = ordered(ctx, [h for h in handles if ctx.d.get(h) is not None])
    if not handles:
        raise CommandError("No objects selected.")
    ents = blockdefs.clones_of(ctx.d, handles)
    try:
        rec = blockdefs.define(ctx.d, name, ents, base, description, annotative, explodable, redefine)
    except blockdefs.BlockError as err:
        raise CommandError(str(err))
    ctx.say('Block "%s" defined with %d object(s).' % (rec["name"], len(ents)))
    reference = None
    if mode in ("delete", "convert"):
        _erase(ctx, handles)
    if mode == "convert":
        try:
            ins = blockdefs.new_insert(ctx.d, rec["name"], base)
        except blockdefs.BlockError as err:
            raise CommandError(str(err))
        reference = ctx.add(ins)
    return {"name": rec["name"], "objects": len(ents), "reference": reference}


def block_flow(ctx, mode: str):
    redefine = False
    while True:
        name = yield from ask_name(ctx)
        if name is None:
            return
        try:
            name = blockdefs.check_name(name)
        except blockdefs.BlockError as err:
            ctx.say(str(err))
            continue
        rec = blockdefs.lookup(ctx.d, name)
        if rec is not None:
            if rec.get("xref"):
                ctx.say('Block "%s" is an external reference.' % rec["name"])
                continue
            if not (yield from ask_yes(ctx, 'Block "%s" already exists. Redefine it?' % rec["name"], "No")):
                continue
            why = blockdefs.lock_reason(ctx.d, rec["name"])
            if why:
                ctx.say(why)
                continue
            name = rec["name"]
            redefine = True
        break
    annotative = False
    base = None
    while base is None:
        b = yield ctx.point("Specify insertion base point", ["Annotative"], default=[0.0, 0.0, 0.0])
        if b.kind == "keyword":
            annotative = yield from ask_yes(ctx, "Create annotative block?", "Yes" if annotative else "No")
            continue
        if b.kind != "point":
            return
        base = b.value
    s = yield ctx.select("Select objects")
    if s.kind != "selection" or not s.value:
        ctx.say("No objects selected.")
        return
    make_block(ctx, name, s.value, base, mode, redefine, "", annotative)


@command("block", aliases=("b", "bmake"), group="draw", label="Create Block", description="Create a block from selected objects (converted to a reference by default).", menu="Draw > Block > Create...")
def block_cmd(ctx):
    yield from block_flow(ctx, "convert")


@command("-block", aliases=("-b",), group="draw", label="Block (command line)", description="Command-line block creation; the selected objects are erased.", menu="")
def block_dash(ctx):
    yield from block_flow(ctx, "delete")


def _boolean(v) -> bool:
    return v is True or str(v).strip().lower() in ("1", "true", "yes", "y")


@executes("block")
def block_exec(ctx, args):
    return block_args(ctx, args, "convert")


@executes("-block")
def block_dash_exec(ctx, args):
    return block_args(ctx, args, "delete")


def block_args(ctx, args, default_mode):
    name = args.get("name")
    if not name:
        raise CommandError("A block name is required.")
    mode = str(args.get("mode", default_mode)).lower()
    if mode not in ("retain", "delete", "convert"):
        raise CommandError("Mode must be retain, delete or convert.")
    base = geom.as_pt(args["base"]) if args.get("base") is not None else [0.0, 0.0, 0.0]
    return make_block(ctx, str(name), targets(ctx, args), base, mode, _boolean(args.get("redefine", False)), str(args.get("description", "") or ""), _boolean(args.get("annotative", False)), args.get("explodable", True) is not False)


def leaves(d, ins, depth: int = 3) -> list:
    out = []
    for c in blockdefs.expand_insert(d, ins, include_attdefs=False):
        if c.kind == "insert" and depth > 0:
            out.extend(leaves(d, c, depth - 1))
        else:
            out.append(c)
        if len(out) >= MAX_GHOST:
            break
    return out


def ghost(ctx, name, scale, rotation, base, anchor=None):
    def fn(p):
        try:
            pos = anchor if anchor is not None else p
            rot = rotation or 0.0
            if anchor is not None:
                rot = geom.angle_of(anchor, p)
            ins = blockdefs.new_insert(ctx.d, name, pos, scale or [1.0, 1.0, 1.0], rot, base, attributes=False)
            return jig.entity_items(leaves(ctx.d, ins), ctx.d)
        except blockdefs.BlockError:
            return []

    return fn


def ask_factor(ctx, message: str, default=1.0, default_text: str = ""):
    while True:
        r = yield ctx.number(message, default=default, default_text=default_text)
        if r.kind not in ("number", "enter"):
            return None
        v = float(r.value) if r.kind == "number" else float(default)
        if abs(v) < 1e-12:
            ctx.say("Requires a non-zero number.")
            continue
        return v


def resolve_target(ctx):
    default = str(ctx.var("INSNAME") or "") or None
    while True:
        r = yield ctx.text("Enter block name or [?]", default)
        if r.kind != "text":
            return None
        raw = str(r.value).strip()
        if raw == "?":
            yield from list_names(ctx)
            continue
        if not raw:
            return None
        explode = raw.startswith("*")
        if explode:
            raw = raw[1:].strip()
        name, path = None, None
        redefine = False
        if "=" in raw:
            left, _, right = raw.partition("=")
            name = left.strip() or None
            path = right.strip() or None
            redefine = True
            if path is None:
                ctx.say("Invalid file specification.")
                continue
        elif blockdefs.lookup(ctx.d, raw) is not None:
            name = blockdefs.lookup(ctx.d, raw)["name"]
        elif blockio.looks_like_file(raw) or blockio.resolve_input(raw):
            path = raw
        else:
            ctx.say('Block "%s" not found.' % raw)
            continue
        if path is not None:
            full = blockio.resolve_input(path)
            if full is None:
                ctx.say('Cannot find the file "%s".' % path)
                continue
            target = name or blockio.stem_name(full)
            exists = blockdefs.lookup(ctx.d, target)
            if exists is not None and not redefine:
                if (yield from ask_yes(ctx, 'Block "%s" already exists. Redefine it?' % exists["name"], "No")):
                    redefine = True
                else:
                    return exists["name"], explode
            try:
                res = blockio.import_as_block(ctx.d, name, full, redefine or exists is not None)
            except (blockio.BlockIOError, blockdefs.BlockError) as err:
                ctx.say(str(err))
                return None
            ctx.say('Block "%s" defined from %s with %d object(s).' % (res["name"], full, res["objects"]))
            name = res["name"]
        return name, explode


def ask_preset(ctx, st: dict, word: str, name: str):
    if word == "Scale":
        v = yield from ask_factor(ctx, "Specify scale factor for XYZ axes", 1.0)
        if v is not None:
            st["scale"], st["x"], st["y"], st["z"] = v, None, None, None
    elif word in ("X", "Y", "Z"):
        v = yield from ask_factor(ctx, "Specify %s scale factor" % word, 1.0)
        if v is not None:
            st[word.lower()] = v
            st["scale"] = None
    elif word == "Rotate":
        r = yield ctx.angle("Specify rotation angle", default=0.0)
        if r.kind in ("number", "enter"):
            st["rot"] = float(r.value) if r.kind == "number" else 0.0
    elif word == "Basepoint":
        r = yield ctx.point("Specify base point", jig=ghost(ctx, name, preset_scale(st), st["rot"], None))
        if r.kind == "point":
            st["base"] = [r.value[0], r.value[1], 0.0]


def preset_scale(st: dict):
    if st["scale"] is not None:
        return [st["scale"]] * 3
    if any(st[k] is not None for k in ("x", "y", "z")):
        return [st["x"] if st["x"] is not None else 1.0, st["y"] if st["y"] is not None else 1.0, st["z"] if st["z"] is not None else 1.0]
    return None


def ask_scale(ctx, pos, name, st):
    tol = ctx.d.tolerances["absolute"]
    while True:
        p = Prompt("Enter X scale factor, specify opposite corner", ("distance", "point"), ["Corner", "XYZ"], 1.0, "1", pos)
        r = yield p
        if r.kind == "enter":
            sx = 1.0
        elif r.kind == "number":
            sx = float(r.value)
            if abs(sx) < 1e-12:
                ctx.say("Requires a non-zero number.")
                continue
        elif r.kind in ("point", "keyword") and (r.kind == "point" or r.value == "Corner"):
            corner = r.value if r.kind == "point" else None
            if corner is None:
                c = yield ctx.point("Specify opposite corner", base=pos, rect=True)
                if c.kind != "point":
                    return None
                corner = c.value
            dx, dy = corner[0] - pos[0], corner[1] - pos[1]
            if abs(dx) < tol or abs(dy) < tol:
                ctx.say("The corner must not be level with the insertion point.")
                continue
            return [dx, dy, abs(dx)]
        elif r.kind == "keyword":
            sx = yield from ask_factor(ctx, "Specify X scale factor", 1.0)
            if sx is None:
                return None
            sy = yield from ask_factor(ctx, "Specify Y scale factor", sx, "use X scale factor")
            if sy is None:
                return None
            sz = yield from ask_factor(ctx, "Specify Z scale factor", abs(sx), "use size of X")
            if sz is None:
                return None
            return [sx, sy, sz]
        else:
            return None
        sy = yield from ask_factor(ctx, "Enter Y scale factor", sx, "use X scale factor")
        if sy is None:
            return None
        return [sx, sy, abs(sx)]


def ask_values(ctx, name: str):
    values = {}
    if not int(ctx.var("ATTREQ")):
        return values
    defs = attribs.asked(ctx.d, name)
    for a in defs:
        msg = a.prompt.strip() or "Enter attribute value"
        r = yield ctx.text(msg, a.default)
        if r.kind != "text":
            return None
        values[a.tag] = str(r.value)
    for a in defs:
        if attribs.mode_of(a, "verify"):
            r = yield ctx.text("Verify attribute values (%s)" % a.tag, values[a.tag])
            if r.kind != "text":
                return None
            values[a.tag] = str(r.value)
    return values


def place(ctx, name, pos, scale, rot, base, values, explode, array=None):
    try:
        ins = blockdefs.new_insert(ctx.d, name, pos, scale, rot, base, array, values if values is not None else True)
    except blockdefs.BlockError as err:
        raise CommandError(str(err))
    if not explode:
        return [ctx.add(ins)]
    rec = blockdefs.lookup(ctx.d, name)
    if rec is not None and rec.get("explodable") is False:
        raise CommandError('Block "%s" cannot be exploded.' % rec["name"])
    made = []
    space = ctx.doc.current_space
    for c in blockdefs.expand_insert(ctx.d, ins):
        c.handle = 0
        try:
            made.append(ctx.d.add_entity(c, space))
        except ValueError as err:
            raise CommandError(str(err))
    return made


def insert_flow(ctx):
    got = yield from resolve_target(ctx)
    if got is None:
        return
    name, explode = got
    st = {"scale": None, "x": None, "y": None, "z": None, "rot": None, "base": None}
    words = EXPLODE_WORDS if explode else PRESET_WORDS
    while True:
        sc = preset_scale(st)
        p = yield ctx.point("Specify insertion point", words, jig=ghost(ctx, name, sc, st["rot"], st["base"]))
        if p.kind == "keyword":
            yield from ask_preset(ctx, st, p.value, name)
            continue
        if p.kind != "point":
            return
        pos = p.value
        break
    scale = preset_scale(st)
    if scale is None:
        if explode:
            v = yield from ask_factor(ctx, "Specify scale factor", 1.0)
            if v is None:
                return
            scale = [v, v, v]
        else:
            scale = yield from ask_scale(ctx, pos, name, st)
            if scale is None:
                return
    rot = st["rot"]
    if rot is None:
        r = yield ctx.angle("Specify rotation angle", default=0.0, base=pos, jig=ghost(ctx, name, scale, None, st["base"], pos))
        if r.kind == "enter":
            rot = 0.0
        else:
            rot = anum(r, pos)
            if rot is None:
                return
    values = None
    if not explode:
        values = yield from ask_values(ctx, name)
        if values is None:
            return
    place(ctx, name, pos, scale, rot, st["base"], values, explode)
    ctx.setvar("INSNAME", name)


@command("insert", aliases=("i", "ddinsert"), group="draw", label="Insert Block", description="Insert a block or a drawing file; options Basepoint, Scale, X, Y, Z, Rotate; a star prefix inserts exploded.", menu="Insert > Block...")
def insert_cmd(ctx):
    yield from insert_flow(ctx)


@command("-insert", group="draw", label="Insert (command line)", description="Command-line INSERT.", menu="")
def insert_dash(ctx):
    yield from insert_flow(ctx)


def _scale_arg(args):
    if args.get("scale") is None:
        return None
    s = args["scale"]
    if isinstance(s, (int, float)):
        return [float(s)] * 3
    return [float(v) for v in s]


@executes("insert", "-insert")
def insert_exec(ctx, args):
    raw = str(args.get("name") or args.get("file") or "").strip()
    if not raw:
        raise CommandError("A block name is required.")
    explode = bool(args.get("explode", False)) or raw.startswith("*")
    raw = raw.lstrip("*") if raw.startswith("*") else raw
    name = None
    file_arg = args.get("file")
    if file_arg or (blockdefs.lookup(ctx.d, raw) is None and (blockio.looks_like_file(raw) or blockio.resolve_input(raw))):
        path = str(file_arg or raw)
        full = blockio.resolve_input(path)
        if full is None:
            raise CommandError('Cannot find the file "%s".' % path)
        target = str(args["name"]).strip() if file_arg and args.get("name") else blockio.stem_name(full)
        exists = blockdefs.lookup(ctx.d, target)
        try:
            if exists is None or _boolean(args.get("redefine", False)):
                name = blockio.import_as_block(ctx.d, target, full, exists is not None)["name"]
            else:
                name = exists["name"]
        except (blockio.BlockIOError, blockdefs.BlockError) as err:
            raise CommandError(str(err))
    else:
        rec = blockdefs.lookup(ctx.d, raw)
        if rec is None:
            raise CommandError('Block "%s" not found.' % raw)
        name = rec["name"]
    if args.get("point") is None:
        raise CommandError("An insertion point is required.")
    scale = _scale_arg(args)
    if explode and scale is not None:
        scale = [scale[0]] * 3
    rot = math.radians(float(args.get("rotation", 0.0)))
    base = geom.as_pt(args["base"]) if args.get("base") is not None else None
    arr = args.get("array") or None
    vals = args.get("attributes")
    handles = place(ctx, name, geom.as_pt(args["point"]), scale, rot, base, vals if isinstance(vals, dict) else None, explode, arr)
    return {"handles": handles, "handle": handles[0] if handles else None, "block": name}


@command("base", group="draw", label="Base Point", description="Set the drawing insertion base point.", menu="Draw > Block > Base")
def base_cmd(ctx):
    cur = ctx.var("INSBASE") or [0.0, 0.0]
    r = yield ctx.point("Enter base point", default=[cur[0], cur[1], 0.0])
    if r.kind == "point":
        ctx.setvar("INSBASE", [r.value[0], r.value[1]])
        ctx.say("Insertion base point set to %s." % ctx.fp(r.value))


@executes("base")
def base_exec(ctx, args):
    if args.get("point") is None:
        raise CommandError("A point is required.")
    p = geom.as_pt(args["point"])
    ctx.setvar("INSBASE", [p[0], p[1]])
    return {"base": [p[0], p[1]]}


def replace_refs(ctx, old: str, new: str, purge: bool) -> dict:
    d = ctx.d
    a = blockdefs.lookup(d, old)
    b = blockdefs.lookup(d, new)
    if a is None:
        raise CommandError('Block "%s" not found.' % old)
    if b is None:
        raise CommandError('Block "%s" not found.' % new)
    if a["name"].casefold() == b["name"].casefold():
        raise CommandError("The replacement block is the same block.")
    refs = blockdefs.references(d, a["name"])
    for r in refs:
        if r.owner.startswith("block:"):
            owner = r.owner[6:]
            if owner.casefold() == b["name"].casefold() or blockdefs.reaches(d, b["name"], owner):
                raise CommandError('Block "%s" references itself.' % owner)
    n = 0
    for r in refs:
        live = d.modify(r.handle)
        live.block = b["name"]
        attribs.sync_insert(d, live)
        n += 1
    purged = False
    if purge and not blockdefs.references(d, a["name"]) and a["name"].casefold() in {x.casefold() for x in blockdefs.unused(d)}:
        blockdefs.remove(d, a["name"])
        purged = True
    ctx.say('Replaced %d reference(s) of block "%s" with "%s".' % (n, a["name"], b["name"]))
    if purged:
        ctx.say('Block "%s" purged.' % a["name"])
    return {"block": a["name"], "replacement": b["name"], "count": n, "purged": purged}


def replace_flow(ctx):
    old = yield from ask_name(ctx, "Enter name of block to replace")
    if old is None:
        return
    new = yield from ask_name(ctx, "Enter name of replacement block")
    if new is None:
        return
    purge = yield from ask_yes(ctx, "Purge the old block definition?", "No")
    try:
        replace_refs(ctx, old, new, purge)
    except CommandError as err:
        ctx.say(str(err))


@command("blockreplace", aliases=("-blockreplace",), group="modify", label="Block Replace", description="Replace every reference of one block by another block.", menu="Tools > Extra Tools > Blocks > Replace Block")
def blockreplace_cmd(ctx):
    yield from replace_flow(ctx)


@executes("blockreplace")
def blockreplace_exec(ctx, args):
    return replace_refs(ctx, str(args.get("block") or args.get("old") or ""), str(args.get("replacement") or args.get("new") or ""), _boolean(args.get("purge", False)))


def burst_handles(ctx, handles) -> dict:
    d = ctx.d
    done = 0
    made = 0
    for e in ctx.editable(handles):
        if not isinstance(e, Insert):
            continue
        rec = blockdefs.lookup(d, e.block)
        if rec is None:
            continue
        if rec.get("explodable") is False or rec.get("xref"):
            ctx.say('Block "%s" cannot be exploded.' % rec["name"])
            continue
        parts = blockdefs.expand_insert(d, e, include_attdefs=False) + attribs.burst_texts(d, e)
        space = e.owner
        d.erase_entity(e.handle)
        for p in parts:
            p.handle = 0
            made += 1
            d.add_entity(p, space)
        done += 1
    ctx.say("%d block reference(s) burst into %d object(s)." % (done, made))
    return {"burst": done, "created": made}


@command("burst", group="modify", label="Burst", description="Explode block references turning attributes into text.", menu="Tools > Extra Tools > Blocks > Burst")
def burst_cmd(ctx):
    s = yield ctx.select("Select objects")
    if s.kind != "selection" or not s.value:
        return
    if not any(isinstance(ctx.d.get(h), Insert) for h in s.value):
        ctx.say("Select a block reference.")
        return
    burst_handles(ctx, s.value)


@executes("burst")
def burst_exec(ctx, args):
    return burst_handles(ctx, targets(ctx, args))


@command("blocks.list", group="draw", label="List Blocks", description="List the defined blocks with reference counts.", menu="", undoable=False, repeatable=False)
def blocks_list(ctx):
    rows = blockdefs.listing(ctx.d)
    if not rows:
        ctx.say("(none)")
    for r in rows:
        ctx.say("%s: %d reference(s), %d object(s), %d attribute definition(s)" % (r["name"], r["references"], r["objects"], r["attributes"]))
    yield from ()


@executes("blocks.list")
def blocks_list_exec(ctx, args):
    return {"blocks": blockdefs.listing(ctx.d, bool(args.get("anonymous", False)))}


@command("blockspalette", aliases=("blocks", "insertpalette"), group="draw", label="Blocks", description="Open the Blocks window; without the interface it lists the defined blocks.", menu="", undoable=False, repeatable=False)
def blocks_palette(ctx):
    rows = blockdefs.listing(ctx.d)
    if not rows:
        ctx.say("No blocks defined in this drawing.")
    for r in rows:
        ctx.say("%s: %d reference(s), %d attribute definition(s)" % (r["name"], r["references"], r["attributes"]))
    yield from ()


@executes("blockspalette")
def blocks_palette_exec(ctx, args):
    return {"blocks": blockdefs.listing(ctx.d, bool(args.get("anonymous", False)))}


@command("block.description", group="modify", label="Block Description", description="Set or clear the description of a block.", menu="Modify > Object > Block Description...")
def block_description(ctx):
    name = yield from ask_name(ctx, "Enter block name")
    if name is None:
        return
    rec = blockdefs.lookup(ctx.d, name)
    if rec is None:
        ctx.say('Block "%s" not found.' % name)
        return
    r = yield ctx.text("Enter block description", rec.get("description", ""))
    if r.kind != "text":
        return
    try:
        blockdefs.set_description(ctx.d, rec["name"], r.value)
    except blockdefs.BlockError as err:
        ctx.say(str(err))


@executes("block.description")
def block_description_exec(ctx, args):
    try:
        rec = blockdefs.set_description(ctx.d, str(args.get("name", "")), str(args.get("description", "")))
    except blockdefs.BlockError as err:
        raise CommandError(str(err))
    return {"name": rec["name"], "description": rec["description"]}
