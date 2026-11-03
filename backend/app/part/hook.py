from app.doc import commit_hooks
from app.param import store as S
from app.part import rebuild, store

PRIORITY = 80
WATCHED_TABLES = ("parameters", "sketches", "constraints")


def watched_handles(d) -> set:
    out = set()
    for rec in store.records(d).values():
        if rec["type"] == "sketch":
            sk = S.get_sketch(d, rec["params"].get("sketch") or "")
            if sk is not None:
                out.update(int(h) for h in sk["entities"])
        for h in (rec.get("params") or {}).get("tools") or []:
            try:
                out.add(int(h))
            except (TypeError, ValueError):
                continue
    return out


def follow(doc, tx) -> None:
    if getattr(tx, "part_done", False):
        return
    d = doc.drawing
    if not store.has_part(d):
        return
    keys = list(tx.before)
    handles = watched_handles(d)
    hit = any((k[0] == "e" and k[1] in handles) or (k[0] == "t" and k[1] in WATCHED_TABLES) for k in keys)
    if not hit:
        return
    t = store.tree(d)
    if t["auto"]:
        rebuild.rebuild(doc)
    else:
        from app.part import tree

        tree.mark_stale(doc)


commit_hooks.register(PRIORITY, follow)
