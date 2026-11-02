from app.doc import blockedit, refedit, xref


def persistent_dict(drawing, keep_edits: bool = False) -> dict:
    data = drawing.to_dict()
    if not keep_edits:
        refedit.strip_for_save(data)
        blockedit.strip_for_save(data)
    xref.strip_for_save(data)
    return data


def reconcile(doc) -> None:
    blockedit.reconcile(doc)


def command_refusal(doc, name: str) -> str:
    blockedit.reconcile(doc)
    msg = blockedit.refusal(doc, name)
    if msg:
        return msg
    if refedit.current(doc.drawing) is not None and name.lstrip("-").lower() in ("bedit", "xopen_inplace"):
        return "A reference is being edited; finish with REFCLOSE."
    return ""


def locked_entity(doc, ent) -> bool:
    return refedit.locked_entity(doc, ent)


def block_lock(d, name: str) -> str:
    low = str(name).casefold()
    if blockedit.is_scratch(name) or name == refedit.RECORD:
        return "This block belongs to an open editing session."
    head = str(name).split("|", 1)[0]
    if "|" in str(name) and xref.is_xref(d.table_get("blocks", head)):
        return 'Block "%s" belongs to the external reference "%s".' % (name, head)
    rec = blockedit.current(d)
    if rec is not None and rec["edit"]["source"].casefold() == low:
        return 'Block "%s" is open in the Block Editor; close it first (BCLOSE).' % rec["edit"]["source"]
    ref = refedit.current(d)
    if ref is not None and ref["edit"]["block"].casefold() == low:
        return 'Block "%s" is being edited in place; finish with REFCLOSE.' % ref["edit"]["block"]
    return ""


def register_locks() -> None:
    try:
        from app.doc import blockdefs
    except ImportError:
        return
    if block_lock not in blockdefs.edit_locks:
        blockdefs.edit_locks.append(block_lock)


register_locks()
