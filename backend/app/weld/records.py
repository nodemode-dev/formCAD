import copy

from app.part import registry, store

TABLE = "weld"
OK_STATES = ("ok", "warning")


def weld_types() -> set:
    return {t.type for t in registry.TYPES.values() if t.group == "weldment"}


def table(d):
    return d.tables.get(TABLE)


def all_rows(d) -> list:
    tbl = table(d)
    return list(tbl.values()) if tbl is not None else []


def active_ids(d) -> list:
    t = store.tree(d)
    order = list(t["order"])
    if t.get("rollback") in order:
        order = order[: order.index(t["rollback"]) + 1]
    recs = store.records(d)
    kinds = weld_types()
    out = []
    for fid in order:
        rec = recs.get(fid)
        if rec is None or rec["type"] not in kinds or rec.get("suppressed"):
            continue
        if (rec.get("state") or {}).get("status") not in OK_STATES:
            continue
        out.append(fid)
    return out


def write(d, fid, rows) -> None:
    keep = set(store.tree(d)["order"])
    for row in all_rows(d):
        if row.get("feature") == fid or row.get("feature") not in keep:
            d.table_remove(TABLE, row["name"])
    for i, r in enumerate(rows):
        q = copy.deepcopy(r)
        q["feature"] = fid
        q["name"] = q["id"] = "%s/%s" % (fid, r["key"])
        q["seq"] = i
        d.table_set(TABLE, q)


def rows(d, kind=None) -> list:
    active = active_ids(d)
    order = {f: i for i, f in enumerate(active)}
    got = [copy.deepcopy(r) for r in all_rows(d) if r.get("feature") in order and (kind is None or r.get("kind") == kind)]
    got.sort(key=lambda r: (order[r["feature"]], r.get("seq", 0)))
    return got
