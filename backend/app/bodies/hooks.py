import copy
import importlib

TABLE = "configs"
KEY = "@suppress"
REBUILDERS = ("app.part.rebuild", "app.part.engine", "app.part.build")


def part_store():
    try:
        from app.part import store

        return store
    except ImportError:
        return None


def feature_rows(d) -> list:
    store = part_store()
    if store is None or not store.has_part(d):
        return []
    return store.ordered(d)


def find_feature(d, name):
    text = str(name)
    for rec in feature_rows(d):
        if rec["id"] == text or str(rec.get("label", "")).casefold() == text.casefold():
            return rec
    return None


def state(d) -> dict:
    t = d.tables.get(TABLE)
    rec = t.get(KEY) if t is not None else None
    held = dict(rec["features"]) if rec else {}
    for rec in feature_rows(d):
        held[str(rec.get("label") or rec["id"])] = bool(rec.get("suppressed", False))
    return held


def known_features(d):
    rows = feature_rows(d)
    if not rows:
        return None
    return [str(r.get("label") or r["id"]) for r in rows] + [r["id"] for r in rows]


def set_suppressed(d, features: dict) -> list:
    if not features:
        return []
    store = part_store()
    t = d.tables.get(TABLE)
    held = dict(t.get(KEY)["features"]) if (t is not None and t.get(KEY)) else {}
    done = []
    for name, flag in features.items():
        rec = find_feature(d, name)
        if rec is not None and store is not None:
            fixed = copy.deepcopy(rec)
            fixed["suppressed"] = bool(flag)
            fixed.setdefault("state", {})
            fixed["state"] = dict(fixed["state"], status="suppressed" if flag else "stale")
            store.put(d, fixed)
        else:
            held[str(name)] = bool(flag)
        done.append(str(name))
    if held or (t is not None and t.get(KEY)):
        d.table_set(TABLE, {"name": KEY, "features": held})
    return sorted(done)


def rebuild(d) -> None:
    if not feature_rows(d):
        return
    from app.doc.service import service

    doc = next((x for x in list(service.docs.values()) if x.drawing is d), None)
    if doc is None:
        return
    for path in REBUILDERS:
        try:
            module = importlib.import_module(path)
        except ImportError:
            continue
        fn = getattr(module, "rebuild", None)
        if callable(fn):
            fn(doc)
            return
