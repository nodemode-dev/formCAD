from app.doc import commit_hooks

PRIORITY = 95
WATCHED_TABLES = ("components", "patterns", "asmconfigs")
WATCHED_HEADERS = ("ASSEMBLY", "PARTTREE")


def relevant(doc, tx) -> bool:
    d = doc.drawing
    for key in tx.before:
        kind = key[0]
        if kind == "e":
            ent = d.ents.get(key[1])
            if ent is not None and ent.kind in ("solidbody", "meshbody"):
                return True
            old = tx.before[key]
            if isinstance(old, dict) and old.get("kind") in ("solidbody", "meshbody"):
                return True
        elif kind == "t" and key[1] in WATCHED_TABLES:
            return True
        elif kind == "h" and key[1] in WATCHED_HEADERS:
            return True
    return False


def follow(doc, tx) -> None:
    if getattr(tx, "cam_done", False):
        return
    table = doc.drawing.tables.get("cam")
    if table is None or not len(table) or not relevant(doc, tx):
        return
    tx.cam_done = True
    from app.cam import gen

    gen.mark_stale(doc)


commit_hooks.register(PRIORITY, follow)
