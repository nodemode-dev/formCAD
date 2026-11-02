from app.doc import attribs, blockdefs
from app.doc.model import block_space

MODE_FIELDS = ("invisible", "constant", "verify", "preset", "lock_position", "annotative", "multiline")


class BattmanError(Exception):
    pass


def _rec(d, block):
    rec = blockdefs.lookup(d, block)
    if rec is None:
        raise BattmanError('Block "%s" not found.' % block)
    if rec.get("xref"):
        raise BattmanError('Block "%s" is an external reference.' % rec["name"])
    why = blockdefs.lock_reason(d, rec["name"])
    if why:
        raise BattmanError(why)
    return rec


def row(adef) -> dict:
    return {
        "handle": adef.handle,
        "tag": adef.tag,
        "prompt": adef.prompt,
        "default": adef.default,
        "height": adef.height,
        "rotation": adef.rotation,
        "style": adef.style,
        "layer": adef.layer,
        "modes": {k: bool((adef.modes or {}).get(k, False)) for k in MODE_FIELDS},
    }


def listing(d, block: str) -> list:
    rec = blockdefs.lookup(d, block)
    if rec is None:
        raise BattmanError('Block "%s" not found.' % block)
    return [row(a) for a in attribs.definitions(d, rec["name"])]


def _find(d, rec, tag):
    adef = attribs.definition(d, rec["name"], tag)
    if adef is None:
        raise BattmanError('Block "%s" has no attribute tagged "%s".' % (rec["name"], tag))
    return adef


def _sync(d, rec, renames=None) -> int:
    return attribs.sync_block(d, rec["name"], renames)


def edit(d, block: str, tag: str, changes: dict, sync: bool = True) -> dict:
    rec = _rec(d, block)
    adef = _find(d, rec, tag)
    renames = {}
    live = d.modify(adef.handle)
    old_tag = live.tag
    for key, val in changes.items():
        if key == "tag":
            new = attribs.normalize_tag(val)
            if new.casefold() != old_tag.casefold() and not attribs.unique_tag(d, rec["name"], new, live):
                raise BattmanError('Block "%s" already has an attribute tagged "%s".' % (rec["name"], new))
            live.tag = new
            if new.casefold() != old_tag.casefold():
                renames[new.casefold()] = old_tag.casefold()
        elif key == "prompt":
            live.prompt = str(val)
        elif key == "default":
            live.default = attribs.check_value(val)
        elif key == "height":
            h = float(val)
            if not h > 0:
                raise BattmanError("Height must be positive.")
            live.height = h
        elif key == "rotation":
            live.rotation = float(val)
        elif key == "layer":
            name = str(val)
            if d.layer(name) is None:
                raise BattmanError('Cannot find layer "%s".' % name)
            live.layer = d.layer(name)["name"]
        elif key == "style":
            if d.table_get("textstyles", str(val)) is None:
                raise BattmanError('Style "%s" not found.' % val)
            live.style = d.table_get("textstyles", str(val))["name"]
        elif key in MODE_FIELDS:
            modes = dict(live.modes or {})
            modes[key] = bool(val)
            live.modes = modes
        else:
            raise BattmanError("Unknown attribute property: %s." % key)
    n = _sync(d, rec, renames) if sync else 0
    return {"tag": live.tag, "synchronized": n}


def remove(d, block: str, tag: str, sync: bool = True) -> dict:
    rec = _rec(d, block)
    adef = _find(d, rec, tag)
    d.erase_entity(adef.handle)
    n = _sync(d, rec) if sync else 0
    return {"tag": adef.tag, "synchronized": n}


def reorder(d, block: str, tags, sync: bool = True) -> dict:
    rec = _rec(d, block)
    defs = attribs.definitions(d, rec["name"])
    want = [str(t).casefold() for t in tags]
    have = [a.tag.casefold() for a in defs]
    if sorted(want) != sorted(have) or len(set(want)) != len(want):
        raise BattmanError("The new order must list every tag exactly once.")
    by_tag = {a.tag.casefold(): a for a in defs}
    space = block_space(rec["name"])
    d._rec_space(space)
    seq = d.spaces[space]
    slots = [i for i, h in enumerate(seq) if h in {a.handle for a in defs}]
    for slot, key in zip(slots, want):
        seq[slot] = by_tag[key].handle
    n = _sync(d, rec) if sync else 0
    return {"order": [by_tag[k].tag for k in want], "synchronized": n}


def move(d, block: str, tag: str, delta: int, sync: bool = True) -> dict:
    rec = _rec(d, block)
    defs = attribs.definitions(d, rec["name"])
    tags = [a.tag for a in defs]
    key = str(tag).casefold()
    idx = next((i for i, t in enumerate(tags) if t.casefold() == key), -1)
    if idx < 0:
        raise BattmanError('Block "%s" has no attribute tagged "%s".' % (rec["name"], tag))
    j = idx + delta
    if j < 0 or j >= len(tags):
        return {"order": tags, "synchronized": 0}
    tags[idx], tags[j] = tags[j], tags[idx]
    return reorder(d, block, tags, sync)


def sync(d, block: str) -> int:
    return _sync(d, _rec(d, block))
