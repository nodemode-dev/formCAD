from app.doc import blocktools as BT
from app.doc import commit_hooks
from app.doc.blocktools import EditError
from app.doc.blockxf import clone_through, insert_matrices
from app.doc.model import block_space

RECORD = "*REFEDIT"
FADE = 85


def current(d):
    rec = d.tables["blocks"].get(RECORD)
    if rec is not None and isinstance(rec.get("edit"), dict) and rec["edit"].get("kind") == "refedit":
        return rec
    return None


def flag(doc) -> None:
    tx = doc._tx
    if tx is not None:
        tx.edit_ok = True


def working(rec) -> dict:
    return {int(k): v for k, v in rec["edit"]["ws"].items()}


def info(d, rec) -> dict:
    ed = rec["edit"]
    return {"open": True, "block": ed["block"], "reference": ed["ref"], "working": len(ed["ws"]), "faded": len(ed["ghosts"]), "removed": len(ed["removed"])}


def status(d) -> dict:
    rec = current(d)
    return info(d, rec) if rec is not None else {"open": False}


def locked_entity(doc, ent) -> bool:
    rec = current(doc.drawing)
    if rec is None:
        return False
    ed = rec["edit"]
    if ent.owner != ed["space"]:
        return False
    return str(ent.handle) not in ed["ws"]


def check_reference(doc, ins):
    from app.doc import blockedit

    d = doc.drawing
    if ins is None or ins.kind != "insert":
        raise EditError("Select a block reference.")
    if current(d) is not None:
        raise EditError("A reference is already being edited; finish with REFCLOSE.")
    if blockedit.current(d) is not None:
        raise EditError("Close the Block Editor first (BCLOSE).")
    if ins.owner != doc.current_space:
        raise EditError("The reference is not in the current space.")
    rec = d.table_get("blocks", ins.block)
    if rec is None:
        raise EditError('Block "%s" not found.' % ins.block)
    if rec.get("xref"):
        raise EditError("External references cannot be edited in place; use XOPEN.")
    if rec["name"].startswith("*") or rec.get("dyn_of"):
        raise EditError("Generated geometry cannot be edited.")
    if d.layer_locked(ins.layer):
        raise EditError("The reference is on a locked layer.")
    sx = float(ins.scale[0]) if ins.scale else 1.0
    sy = float(ins.scale[1]) if ins.scale and len(ins.scale) > 1 else sx
    if abs(sx) < 1e-12 or abs(sy) < 1e-12:
        raise EditError("The reference is flat; it cannot be edited in place.")
    if abs(abs(sx) - abs(sy)) > 1e-9 * max(abs(sx), abs(sy)):
        raise EditError("The reference must be scaled equally in X and Y.")
    arr = ins.array or {}
    if int(arr.get("rows", 1) or 1) > 1 or int(arr.get("cols", arr.get("columns", 1)) or 1) > 1:
        raise EditError("An arrayed reference cannot be edited in place.")
    if BT.would_self_reference(d, rec["name"], BT.used_blocks(d, rec["name"])):
        raise EditError('Block "%s" references itself.' % rec["name"])
    return rec


def open_edit(doc, handle: int, objects=None) -> dict:
    d = doc.drawing
    ins = d.get(int(handle))
    rec = check_reference(doc, ins)
    m = insert_matrices(ins, rec)[0]
    flag(doc)
    bname = rec["name"]
    bspace = block_space(bname)
    chosen = None if objects in (None, "all", "All") else {int(h) for h in objects}
    ws, ghosts, ghost_of, skipped = {}, [], {}, 0
    for be in list(d.entities(bspace)):
        c = clone_through(be, m)
        if c is None:
            skipped += 1
            continue
        c.handle = 0
        c.owner = ins.owner
        if chosen is not None and be.handle not in chosen:
            c.transparency = FADE
            h = d.add_entity(c, ins.owner)
            d.ents[h].extra = {**d.ents[h].extra, "refedit_ghost": True}
            ghosts.append(h)
            ghost_of[str(h)] = be.handle
        else:
            h = d.add_entity(c, ins.owner)
            ws[str(h)] = be.handle
    prev_visible = ins.visible
    d.modify(ins.handle).visible = False
    srec = d.define_block(RECORD, [0.0, 0.0, 0.0], "")
    srec["edit"] = {"kind": "refedit", "ref": ins.handle, "block": bname, "space": ins.owner, "matrix": list(m), "ws": ws, "ghosts": ghosts, "ghost_of": ghost_of, "removed": [], "prev_visible": prev_visible}
    out = info(d, srec)
    out["skipped"] = skipped
    return out


def _update(doc, mutate) -> None:
    d = doc.drawing
    rec = d.modify_record("blocks", RECORD)
    mutate(rec["edit"])


def ws_add(doc, handles) -> int:
    d = doc.drawing
    rec = current(d)
    if rec is None:
        raise EditError("No reference is being edited.")
    ed = rec["edit"]
    flag(doc)
    todo = []
    for h in handles:
        e = d.get(int(h))
        if e is None or e.owner != ed["space"] or int(h) == ed["ref"] or str(h) in ed["ws"] or int(h) in ed["ghosts"]:
            continue
        if d.layer_locked(e.layer):
            continue
        if e.kind == "insert" and BT.would_self_reference(d, ed["block"], [e.block]):
            raise EditError('Block "%s" would reference itself.' % ed["block"])
        todo.append(int(h))

    def mutate(edit):
        for h in todo:
            edit["ws"][str(h)] = 0

    _update(doc, mutate)
    return len(todo)


def ws_remove(doc, handles) -> int:
    d = doc.drawing
    rec = current(d)
    if rec is None:
        raise EditError("No reference is being edited.")
    ed = rec["edit"]
    flag(doc)
    todo = [int(h) for h in handles if str(int(h)) in ed["ws"]]

    def mutate(edit):
        for h in todo:
            orig = edit["ws"].pop(str(h))
            if orig:
                edit["removed"].append(orig)

    _update(doc, mutate)
    return len(todo)


def fade(doc, handles) -> int:
    d = doc.drawing
    rec = current(d)
    if rec is None:
        raise EditError("No reference is being edited.")
    ed = rec["edit"]
    flag(doc)
    todo = [int(h) for h in handles if ed["ws"].get(str(int(h)))]
    for h in todo:
        e = d.modify(h)
        e.transparency = FADE
        e.extra = {**e.extra, "refedit_ghost": True}

    def mutate(edit):
        for h in todo:
            edit["ghost_of"][str(h)] = edit["ws"].pop(str(h))
            edit["ghosts"].append(h)

    _update(doc, mutate)
    return len(todo)


def listing(d) -> list:
    rec = current(d)
    if rec is None:
        return []
    return sorted(int(k) for k in rec["edit"]["ws"])


def _finish(doc, rec, erase_ws: bool) -> None:
    d = doc.drawing
    ed = rec["edit"]
    for h in list(ed["ghosts"]):
        if h in d.ents:
            d.erase_entity(h)
    if erase_ws:
        for k in ed["ws"]:
            if int(k) in d.ents:
                d.erase_entity(int(k))
    ref = d.get(ed["ref"])
    if ref is not None:
        d.modify(ref.handle).visible = bool(ed.get("prev_visible", True))
    d.table_remove("blocks", RECORD)
    d._rec_space(block_space(RECORD))
    d.spaces.pop(block_space(RECORD), None)


def close_edit(doc, save: bool = True) -> dict:
    d = doc.drawing
    rec = current(d)
    if rec is None:
        raise EditError("No reference is being edited.")
    ed = rec["edit"]
    flag(doc)
    if not save:
        discarded = sum(1 for _k, v in ed["ws"].items() if v)
        kept_host = sum(1 for _k, v in ed["ws"].items() if not v)
        for k, orig in ed["ws"].items():
            if orig and int(k) in d.ents:
                d.erase_entity(int(k))
        _finish(doc, rec, False)
        return {"saved": False, "discarded": discarded, "host_kept": kept_host}
    bname = ed["block"]
    brec = d.table_get("blocks", bname)
    if brec is None:
        raise EditError('Block "%s" no longer exists; discard the reference changes.' % bname)
    bspace = block_space(brec["name"])
    inv = BT.inverse(ed["matrix"])
    if inv is None:
        raise EditError("The reference transform cannot be inverted.")
    ws = working(rec)
    plans = []
    for mh, orig in ws.items():
        e = d.get(mh)
        if e is None:
            plans.append((mh, orig, None))
            continue
        c = clone_through(e, inv)
        if c is None:
            raise EditError("An object in the working set cannot be written back.")
        plans.append((mh, orig, c))
    names = [c.block for _m, _o, c in plans if c is not None and c.kind == "insert" and c.block]
    if BT.would_self_reference(d, brec["name"], names):
        raise EditError('Block "%s" would reference itself; remove that reference or use REFCLOSE Discard.' % brec["name"])
    updated = added = erased = 0
    for mh, orig, c in plans:
        if c is None:
            if orig and orig in d.ents:
                d.erase_entity(orig)
                erased += 1
            continue
        c.visible = True
        c.transparency = "ByLayer" if c.transparency == FADE else c.transparency
        c.extra = {k: v for k, v in c.extra.items() if k != "refedit_ghost"}
        if orig and orig in d.ents and d.ents[orig].owner == bspace:
            c.handle = orig
            c.owner = bspace
            d.modify(orig)
            d.ents[orig] = c
            updated += 1
        else:
            c.handle = 0
            d.add_entity(c, bspace)
            added += 1
    for orig in ed["removed"]:
        if orig in d.ents and d.ents[orig].owner == bspace:
            d.erase_entity(orig)
            erased += 1
    _finish(doc, rec, True)
    from app.doc import dynblock

    dynblock.refresh_references(d, brec["name"])
    from app.doc import attribs

    attribs.sync_block(d, brec["name"])
    return {"saved": True, "block": brec["name"], "updated": updated, "added": added, "erased": erased}


def strip_for_save(data: dict) -> None:
    recs = [r for r in data.get("tables", {}).get("blocks", []) if r.get("name") == RECORD and isinstance(r.get("edit"), dict)]
    if not recs:
        return
    ed = recs[0]["edit"]
    gone = {int(k) for k, v in ed["ws"].items() if v} | set(ed["ghosts"])
    data["entities"] = [e for e in data.get("entities", []) if e.get("handle") not in gone]
    for e in data["entities"]:
        if e.get("handle") == ed["ref"]:
            e["visible"] = bool(ed.get("prev_visible", True))
    data["tables"]["blocks"] = [r for r in data["tables"]["blocks"] if r.get("name") != RECORD]
    data["spaces"] = [s for s in data.get("spaces", []) if s != block_space(RECORD)]


def guard_hook(doc, tx) -> None:
    d = doc.drawing
    rec = current(d)
    if rec is None or getattr(tx, "edit_ok", False):
        return
    ed = rec["edit"]
    ws = ed["ws"]
    bad = []
    fresh = []
    for key, before in list(tx.before.items()):
        if key[0] != "e":
            continue
        h = key[1]
        if before is None:
            if h in d.ents and d.ents[h].owner == ed["space"] and str(h) not in ws:
                fresh.append(h)
            continue
        if str(h) in ws:
            continue
        if before.get("owner") == ed["space"] or h == ed["ref"]:
            bad.append(key)
    if fresh:
        tx.edit_ok = True
        try:
            _update(doc, lambda edit: [edit["ws"].__setitem__(str(h), 0) for h in fresh])
        finally:
            tx.edit_ok = False
    if not bad:
        return
    spaces = {}
    for key in bad:
        before = tx.before.pop(key)
        d.apply_key(key, before)
        owner = before.get("owner")
        spaces[owner] = True
    for sp in spaces:
        skey = ("s", sp)
        prior = tx.before.get(skey)
        cur = list(d.spaces.get(sp, []))
        if prior is None:
            prior = [h for h in cur]
            for key in bad:
                if key[1] not in prior:
                    prior.append(key[1])
        merged = [h for h in prior if h in d.ents] + [h for h in cur if h not in prior]
        d.spaces[sp] = merged
    runner = getattr(doc, "runner", None)
    if runner is not None:
        runner.log("%d object(s) outside the working set were left unchanged." % len(bad))


commit_hooks.register(5, guard_hook)
