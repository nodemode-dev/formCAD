import copy

KINDS = {
    "layer": ("layers", "layer"),
    "linetype": ("linetypes", "linetype"),
    "textstyle": ("textstyles", "text style"),
    "style": ("textstyles", "text style"),
    "dimstyle": ("dimstyles", "dimension style"),
    "block": ("blocks", "block"),
    "mleaderstyle": ("mleaderstyles", "multileader style"),
    "tablestyle": ("tablestyles", "table style"),
    "view": ("views", "view"),
    "ucs": ("ucs", "UCS"),
}
BAD = set('<>/\\":;?*|,=`')
FROZEN = {"layers": ("0", "Defpoints"), "linetypes": ("ByLayer", "ByBlock", "Continuous"), "textstyles": ("Standard",), "dimstyles": ("Standard",)}
DIM_BLOCK_VARS = ("DIMBLK", "DIMBLK1", "DIMBLK2", "DIMLDRBLK")


class RenameError(Exception):
    pass


def canonical(kind: str) -> str:
    low = str(kind).strip().lower().replace(" ", "").replace("_", "")
    low = {"lt": "linetype", "ltype": "linetype", "la": "layer", "mleader": "mleaderstyle", "mls": "mleaderstyle", "ta": "tablestyle", "dimensionstyle": "dimstyle", "textstyle": "textstyle"}.get(low, low)
    if low not in KINDS:
        raise RenameError("Unknown object type: %s." % kind)
    return low


def valid_name(name) -> bool:
    return isinstance(name, str) and bool(name.strip()) and len(name) <= 255 and not any(c in BAD or ord(c) < 32 for c in name)


def _eq(a, b) -> bool:
    return str(a).casefold() == str(b).casefold()


def _retarget_entities(d, pred, setter) -> int:
    n = 0
    for h, e in list(d.ents.items()):
        if pred(e):
            setter(d.modify(h))
            n += 1
    return n


def rename(d, kind: str, old: str, new: str) -> dict:
    kind = canonical(kind)
    table, label = KINDS[kind]
    rec = d.table_get(table, str(old))
    if rec is None:
        raise RenameError('Cannot find %s "%s".' % (label, old))
    old = rec["name"]
    if not valid_name(new):
        raise RenameError('"%s" is not a valid %s name.' % (new, label))
    new = new.strip()
    for frozen in FROZEN.get(table, ()):
        if _eq(old, frozen):
            raise RenameError('The %s "%s" cannot be renamed.' % (label, old))
    if table == "blocks" and (old.startswith("*") or new.startswith("*")):
        raise RenameError("Anonymous blocks cannot be renamed.")
    if d.table_get(table, new) is not None and not _eq(old, new):
        raise RenameError('A %s named "%s" already exists.' % (label, new))
    if old == new:
        return {"type": kind, "old": old, "new": new, "updated": 0}
    updated = 0
    if table == "layers":
        updated += _retarget_entities(d, lambda e: _eq(e.layer, old), lambda e: setattr(e, "layer", new))
        if _eq(d.header.get("CLAYER", ""), old):
            d.set_header("CLAYER", new)
        from app.doc import layerops

        updated += layerops.after_rename(d, old, new)
    elif table == "linetypes":
        updated += _retarget_entities(d, lambda e: _eq(e.linetype, old), lambda e: setattr(e, "linetype", new))
        for lay in list(d.tables["layers"].values()):
            if _eq(lay.get("linetype", ""), old):
                d.modify_record("layers", lay["name"])["linetype"] = new
                updated += 1
        for ms in list(d.tables["mlinestyles"].values()):
            if any(_eq(el.get("linetype", ""), old) for el in ms.get("elements", [])):
                r = d.modify_record("mlinestyles", ms["name"])
                for el in r["elements"]:
                    if _eq(el.get("linetype", ""), old):
                        el["linetype"] = new
                updated += 1
        if _eq(d.header.get("CELTYPE", ""), old):
            d.set_header("CELTYPE", new)
    elif table == "textstyles":
        updated += _retarget_entities(d, lambda e: e.kind in ("text", "mtext", "attdef") and _eq(getattr(e, "style", ""), old), lambda e: setattr(e, "style", new))
        for ds in list(d.tables["dimstyles"].values()):
            if _eq(ds["vars"].get("DIMTXSTY", ""), old):
                d.modify_record("dimstyles", ds["name"])["vars"]["DIMTXSTY"] = new
                updated += 1
        for ms in list(d.tables["mleaderstyles"].values()):
            if _eq(ms.get("text_style", ""), old):
                d.modify_record("mleaderstyles", ms["name"])["text_style"] = new
                updated += 1
        if _eq(d.header.get("TEXTSTYLE", ""), old):
            d.set_header("TEXTSTYLE", new)
    elif table == "dimstyles":
        updated += _retarget_entities(d, lambda e: e.kind == "dimension" and _eq(e.style, old), lambda e: setattr(e, "style", new))
        if _eq(d.header.get("DIMSTYLE", ""), old):
            d.set_header("DIMSTYLE", new)
    elif table == "blocks":
        updated += _retarget_entities(d, lambda e: e.kind == "insert" and _eq(e.block, old), lambda e: setattr(e, "block", new))
        for ds in list(d.tables["dimstyles"].values()):
            if any(_eq(ds["vars"].get(v, ""), old) for v in DIM_BLOCK_VARS):
                r = d.modify_record("dimstyles", ds["name"])
                for v in DIM_BLOCK_VARS:
                    if _eq(r["vars"].get(v, ""), old):
                        r["vars"][v] = new
                updated += 1
        updated += _retarget_entities(d, lambda e: e.kind == "dimension" and any(_eq(e.overrides.get(v, ""), old) for v in DIM_BLOCK_VARS), lambda e: _dim_blocks(e, old, new))
        _move_block_space(d, old, new)
    elif table == "mleaderstyles":
        updated += _retarget_entities(d, lambda e: e.kind == "mleader" and _eq(getattr(e, "style", ""), old), lambda e: setattr(e, "style", new))
        if _eq(d.header.get("CMLEADERSTYLE", ""), old):
            d.set_header("CMLEADERSTYLE", new)
    elif table == "tablestyles":
        updated += _retarget_entities(d, lambda e: e.kind == "table" and _eq(getattr(e, "style", ""), old), lambda e: setattr(e, "style", new))
        if _eq(d.header.get("CTABLESTYLE", ""), old):
            d.set_header("CTABLESTYLE", new)
    fresh = copy.deepcopy(d.table_get(table, old))
    fresh["name"] = new
    d.table_remove(table, old)
    d.table_set(table, fresh)
    return {"type": kind, "old": old, "new": new, "updated": updated}


def _dim_blocks(e, old, new) -> None:
    ov = dict(e.overrides)
    for v in DIM_BLOCK_VARS:
        if _eq(ov.get(v, ""), old):
            ov[v] = new
    e.overrides = ov


def _move_block_space(d, old, new) -> None:
    src, dst = "block:" + old, "block:" + new
    if src not in d.spaces:
        return
    for h in list(d.spaces[src]):
        if h in d.ents:
            d.modify(h).owner = dst
    d._rec_space(src)
    d._rec_space(dst)
    d.spaces[dst] = d.spaces.pop(src)
