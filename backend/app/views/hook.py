from app.doc import commit_hooks
from app.views import build, ops, sources
from app.views.model import ViewError

PRIORITY = 90
WATCHED_TABLES = ("components", "patterns", "asmconfigs")
WATCHED_HEADERS = ("ASSEMBLY", "PARTTREE")


def relevant(doc, tx) -> bool:
    d = doc.drawing
    for key in tx.before:
        kind = key[0]
        if kind == "e":
            ent = d.ents.get(key[1])
            if ent is not None and ent.kind == "solidbody":
                return True
            old = tx.before[key]
            if isinstance(old, dict) and old.get("kind") == "solidbody":
                return True
        elif kind == "t" and key[1] in WATCHED_TABLES:
            return True
        elif kind == "h" and key[1] in WATCHED_HEADERS:
            return True
    return False


def follow(doc, tx) -> None:
    if getattr(tx, "views_done", False) or not relevant(doc, tx):
        return
    d = doc.drawing
    views = ops.views_of(d)
    if not views:
        return
    tx.views_done = True
    cache = {}
    for v in sorted(views, key=lambda e: e.handle):
        key = repr(sorted((v.source or {}).items()))
        if key not in cache:
            cache[key] = sources.current_signature(doc, v.source)
        sig = cache[key]
        if not sig or sig == (v.state or {}).get("sig"):
            continue
        ent = d.modify(v.handle)
        st = dict(ent.state or {})
        st["status"] = "stale"
        ent.state = st
        if ent.auto:
            try:
                build.rebuild(doc, v.handle)
            except ViewError:
                pass
            except Exception as err:
                build.fail(d, v.handle, str(err))


commit_hooks.register(PRIORITY, follow)
