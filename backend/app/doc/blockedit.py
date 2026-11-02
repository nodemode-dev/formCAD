import copy
import hashlib
import json

from app.doc import blocktools as BT
from app.doc.blocktools import EditError
from app.doc.model import SPACE_MODEL, block_space

SCRATCH = "*BEDIT$"
CURRENT = "<Current Drawing>"
LEAVES_MODEL = ("layout", "mspace", "pspace", "mview", "chspace", "pagesetup", "plot", "print", "publish", "vports")


def sessions(d) -> list:
    return [r for r in d.tables["blocks"].values() if isinstance(r.get("edit"), dict) and r["edit"].get("kind") == "bedit"]


def current(d):
    found = sessions(d)
    return found[0] if found else None


def scratch_space(rec) -> str:
    return block_space(rec["name"])


def is_scratch(name: str) -> bool:
    return str(name).startswith(SCRATCH)


def signature(d, rec) -> str:
    items = []
    for e in d.entities(scratch_space(rec)):
        data = e.to_dict()
        data.pop("handle", None)
        data.pop("owner", None)
        items.append(data)
    body = json.dumps([items, rec["base"], rec.get("description", "")], sort_keys=True, default=str)
    return hashlib.sha1(body.encode("utf-8")).hexdigest()


def dirty(d, rec) -> bool:
    return rec["edit"].get("sig") != signature(d, rec)


def flag(doc) -> None:
    tx = doc._tx
    if tx is not None:
        tx.edit_ok = True


def info(d, rec) -> dict:
    ed = rec["edit"]
    return {"open": True, "name": ed["source"], "drawing": bool(ed.get("drawing")), "new": bool(ed.get("new")), "dirty": dirty(d, rec), "space": scratch_space(rec), "base": list(rec["base"]), "objects": len(d.spaces.get(scratch_space(rec), [])), "description": rec.get("description", ""), "dynamic": bool(ed.get("dynamic"))}


def status(d) -> dict:
    rec = current(d)
    if rec is None:
        return {"open": False}
    return info(d, rec)


def listing(d) -> list:
    out = []
    for r in sorted(d.tables["blocks"].values(), key=lambda r: r["name"].casefold()):
        if r["name"].startswith("*") or r.get("xref"):
            continue
        out.append({"name": r["name"], "description": r.get("description", ""), "base": list(r["base"]), "objects": len(d.spaces.get(block_space(r["name"]), [])), "references": len(BT.references_to(d, r["name"])), "dynamic": bool(r.get("dynamic"))})
    return out


def check_target(d, name):
    if d.tables["blocks"].has(name):
        rec = d.table_get("blocks", name)
        if rec.get("xref"):
            raise EditError('"%s" is an external reference; open its file with XOPEN.' % rec["name"])
        if rec["name"].startswith("*"):
            raise EditError('"%s" is generated geometry and cannot be edited.' % rec["name"])
        if BT.would_self_reference(d, rec["name"], BT.used_blocks(d, rec["name"])):
            raise EditError('Block "%s" references itself.' % rec["name"])
        return rec
    if not BT.valid_name(name) or name.startswith("*"):
        raise EditError("Invalid block name.")
    return None


def open_editor(doc, name: str, create: bool = True) -> dict:
    from app.doc import refedit

    d = doc.drawing
    if refedit.current(d) is not None:
        raise EditError("A reference is being edited; finish with REFCLOSE or discard it first.")
    if current(d) is not None:
        raise EditError('The block editor is already editing "%s".' % current(d)["edit"]["source"])
    if doc.current_space != SPACE_MODEL:
        raise EditError("Not available outside model space.")
    raw = str(name or "").strip()
    drawing_mode = raw.casefold() in (CURRENT.casefold(), "")
    new = False
    if drawing_mode:
        source, src_space, base0, desc = CURRENT, SPACE_MODEL, [0.0, 0.0, 0.0], ""
        dynamic = None
    else:
        rec = check_target(d, raw)
        if rec is None:
            if not create:
                raise EditError('Block "%s" not found.' % raw)
            new = True
            source, src_space, base0, desc, dynamic = raw, "", [0.0, 0.0, 0.0], "", None
        else:
            source, src_space, base0, desc = rec["name"], block_space(rec["name"]), list(rec["base"]), rec.get("description", "")
            dynamic = copy.deepcopy(rec.get("dynamic"))
    flag(doc)
    sname = SCRATCH + source
    srec = d.define_block(sname, [0.0, 0.0, 0.0], desc)
    mapping = {}
    if src_space:
        neg = [-base0[0], -base0[1], -base0[2] if len(base0) > 2 else 0.0]
        for e in list(d.entities(src_space)):
            c = e.copy_as_new()
            c.move_by(neg)
            h = d.add_entity(c, block_space(sname))
            mapping[str(h)] = e.handle
    srec["edit"] = {"kind": "bedit", "source": source, "drawing": drawing_mode, "new": new, "base0": base0, "map": mapping, "sig": "", "dynamic": bool(dynamic)}
    srec["edit"]["sig"] = signature(d, srec)
    doc.current_space = block_space(sname)
    return info(d, srec)


def _plan(d, rec, target, same):
    ed = rec["edit"]
    sspace = scratch_space(rec)
    scratch = list(d.entities(sspace))
    names = [e.block for e in scratch if e.kind == "insert" and e.block]
    if not ed.get("drawing") and BT.would_self_reference(d, target, names):
        raise EditError('Block "%s" references itself; remove that reference first.' % target)
    return scratch


def _write(doc, rec, target, same):
    d = doc.drawing
    ed = rec["edit"]
    scratch = _plan(d, rec, target, same)
    base0 = ed["base0"]
    drawing_mode = bool(ed.get("drawing"))
    tspace = SPACE_MODEL if drawing_mode else block_space(target)
    tr = d.table_get("blocks", target) if not drawing_mode else None
    if not drawing_mode and tr is None:
        tr = d.define_block(target, [0.0, 0.0, 0.0], rec.get("description", ""))
        tr = d.table_get("blocks", target)
    d.ensure_space(tspace)
    if same:
        mapping = {int(k): v for k, v in ed.get("map", {}).items()}
    else:
        mapping = {}
        for h in list(d.spaces.get(tspace, [])):
            if drawing_mode:
                break
            d.erase_entity(h)
    kept = set()
    updated = added = 0
    order = []
    for e in scratch:
        c = copy.deepcopy(e)
        c.move_by([base0[0], base0[1], base0[2] if len(base0) > 2 else 0.0])
        orig = mapping.get(e.handle)
        if orig and orig in d.ents and d.ents[orig].owner == tspace:
            c.handle = orig
            c.owner = tspace
            d.modify(orig)
            d.ents[orig] = c
            kept.add(orig)
            order.append(orig)
            updated += 1
        else:
            c.handle = 0
            h = d.add_entity(c, tspace)
            kept.add(h)
            order.append(h)
            mapping[e.handle] = h
            added += 1
    removed = 0
    for h in list(d.spaces.get(tspace, [])):
        if h not in kept:
            d.erase_entity(h)
            removed += 1
    d._rec_space(tspace)
    d.spaces[tspace] = [h for h in order if h in d.ents] + [h for h in d.spaces[tspace] if h not in order and h in d.ents]
    if not drawing_mode:
        tr = d.modify_record("blocks", target)
        shift = rec["base"]
        tr["base"] = [base0[0] + shift[0], base0[1] + shift[1], (base0[2] if len(base0) > 2 else 0.0) + (shift[2] if len(shift) > 2 else 0.0)]
        tr["description"] = rec.get("description", "")
    return updated, added, removed, mapping


def _normalise(doc, rec, target, mapping, same):
    d = doc.drawing
    srec = d.modify_record("blocks", rec["name"])
    ed = srec["edit"]
    shift = list(srec["base"])
    if any(abs(v) > 0 for v in shift):
        neg = [-shift[0], -shift[1], -(shift[2] if len(shift) > 2 else 0.0)]
        for e in d.entities(scratch_space(srec)):
            d.modify(e.handle).move_by(neg)
        ed["base0"] = [ed["base0"][i] + shift[i] for i in range(3)] if not ed.get("drawing") else ed["base0"]
        srec["base"] = [0.0, 0.0, 0.0]
    ed["map"] = {str(k): v for k, v in mapping.items()}
    ed["source"] = target if not ed.get("drawing") else ed["source"]
    ed["new"] = False
    ed["sig"] = signature(d, srec)


def save_editor(doc, as_name: str = "", redefine: bool = False) -> dict:
    d = doc.drawing
    rec = current(d)
    if rec is None:
        raise EditError("The block editor is not open.")
    ed = rec["edit"]
    flag(doc)
    drawing_mode = bool(ed.get("drawing"))
    if as_name:
        if drawing_mode:
            raise EditError("The drawing itself cannot be saved under a block name.")
        if not BT.valid_name(as_name) or as_name.startswith("*"):
            raise EditError("Invalid block name.")
        existing = d.table_get("blocks", as_name)
        if existing is not None:
            if existing.get("xref") or existing["name"].startswith("*"):
                raise EditError('"%s" cannot be redefined.' % existing["name"])
            if not redefine:
                raise EditError('Block "%s" already exists.' % existing["name"])
            as_name = existing["name"]
        target = as_name
        same = False
    else:
        target = ed["source"]
        same = True
    updated, added, removed, mapping = _write(doc, rec, target, same)
    _normalise(doc, rec, target, mapping, same)
    if not drawing_mode:
        from app.doc import dynblock

        dynblock.refresh_references(d, target)
        from app.doc import attribs

        attribs.sync_block(d, target)
    if as_name and not drawing_mode:
        _rename_scratch(doc, rec["name"], target)
    out = info(d, current(d))
    out.update({"updated": updated, "added": added, "removed": removed, "saved": target})
    return out


def _rename_scratch(doc, old, target):
    d = doc.drawing
    new = SCRATCH + target
    if old == new:
        return
    rec = copy.deepcopy(d.table_get("blocks", old))
    rec["name"] = new
    old_space = block_space(old)
    new_space = block_space(new)
    d.table_remove("blocks", old)
    d.table_set("blocks", rec)
    d._rec_space(old_space)
    d._rec_space(new_space)
    handles = list(d.spaces.pop(old_space, []))
    d.spaces[new_space] = handles
    for h in handles:
        d.modify(h).owner = new_space
    doc.current_space = new_space


def close_editor(doc, save: bool = False) -> dict:
    d = doc.drawing
    rec = current(d)
    if rec is None:
        raise EditError("The block editor is not open.")
    flag(doc)
    out = {}
    if save:
        out = save_editor(doc)
    rec = current(d)
    source = rec["edit"]["source"]
    sspace = scratch_space(rec)
    for h in list(d.spaces.get(sspace, [])):
        d.erase_entity(h)
    d._rec_space(sspace)
    d.spaces.pop(sspace, None)
    d.table_remove("blocks", rec["name"])
    doc.current_space = SPACE_MODEL
    out.update({"closed": source, "saved_first": bool(save)})
    return out


def set_description(doc, text: str) -> None:
    d = doc.drawing
    rec = current(d)
    if rec is None:
        raise EditError("The block editor is not open.")
    srec = d.modify_record("blocks", rec["name"])
    srec["description"] = str(text)[:255]


def strip_for_save(data: dict) -> None:
    names = [r["name"] for r in data.get("tables", {}).get("blocks", []) if isinstance(r.get("edit"), dict) and r["edit"].get("kind") == "bedit"]
    if not names:
        return
    spaces = {block_space(n) for n in names}
    data["tables"]["blocks"] = [r for r in data["tables"]["blocks"] if r["name"] not in names]
    data["spaces"] = [s for s in data.get("spaces", []) if s not in spaces]
    data["entities"] = [e for e in data.get("entities", []) if e.get("owner") not in spaces]


def refusal(doc, command_name: str) -> str:
    rec = current(doc.drawing)
    if rec is None:
        return ""
    if command_name.lstrip("-").lower() in LEAVES_MODEL:
        return 'Not available in the Block Editor (editing "%s"); close it first (BCLOSE).' % rec["edit"]["source"]
    return ""


def reconcile(doc) -> None:
    d = doc.drawing
    rec = current(d)
    if rec is not None:
        space = scratch_space(rec)
        if doc.current_space != space and space in d.spaces:
            doc.current_space = space
    elif doc.current_space.startswith("block:" + SCRATCH) or doc.current_space not in d.spaces:
        doc.current_space = SPACE_MODEL
