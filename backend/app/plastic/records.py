import copy

from app.part import registry, store

TABLE = "plastic"
OK_STATES = ("ok", "warning")


def plastic_types() -> set:
    return {t.type for t in registry.TYPES.values() if t.group == "plastic"}


def all_rows(d) -> list:
    tbl = d.tables.get(TABLE)
    return list(tbl.values()) if tbl is not None else []


def active_ids(d) -> list:
    t = store.tree(d)
    order = list(t["order"])
    if t.get("rollback") in order:
        order = order[: order.index(t["rollback"]) + 1]
    recs = store.records(d)
    kinds = plastic_types()
    out = []
    for fid in order:
        rec = recs.get(fid)
        if rec is None or rec["type"] not in kinds or rec.get("suppressed"):
            continue
        if (rec.get("state") or {}).get("status") not in OK_STATES:
            continue
        out.append(fid)
    return out


def write(d, fid, row) -> None:
    keep = set(store.tree(d)["order"])
    for old in all_rows(d):
        if old.get("feature") == fid or old.get("feature") not in keep:
            d.table_remove(TABLE, old["name"])
    r = copy.deepcopy(row)
    r["name"] = r["id"] = fid
    r["feature"] = fid
    d.table_set(TABLE, r)


def features(d) -> list:
    rows = {r["id"]: r for r in all_rows(d)}
    return [copy.deepcopy(rows[f]) for f in active_ids(d) if f in rows]


def feature(d, fid):
    for row in all_rows(d):
        if row["id"] == fid:
            return copy.deepcopy(row)
    return None
