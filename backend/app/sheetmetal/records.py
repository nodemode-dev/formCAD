import copy

from app.part import registry, store

TABLE = "sheetmetal"
OK_STATES = ("ok", "warning")


def sheet_types() -> set:
    return {t.type for t in registry.TYPES.values() if t.group == "sheetmetal"}


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
    kinds = sheet_types()
    out = []
    for fid in order:
        rec = recs.get(fid)
        if rec is None or rec["type"] not in kinds or rec.get("suppressed"):
            continue
        if (rec.get("state") or {}).get("status") not in OK_STATES:
            continue
        out.append(fid)
    return out


def write(d, fid, feature_row, bend_rows) -> None:
    tbl = table(d)
    keep = set(store.tree(d)["order"])
    if tbl is not None:
        for row in all_rows(d):
            if row.get("feature") == fid or row.get("feature") not in keep:
                d.table_remove(TABLE, row["name"])
    row = copy.deepcopy(feature_row)
    row["name"] = row["id"] = fid
    row["kind"] = "feature"
    row["feature"] = fid
    d.table_set(TABLE, row)
    for b in bend_rows:
        r = copy.deepcopy(b)
        r["name"] = r["id"]
        r["kind"] = "bend"
        r["feature"] = fid
        d.table_set(TABLE, r)


def features(d) -> list:
    rows = {r["id"]: r for r in all_rows(d) if r.get("kind") == "feature"}
    return [copy.deepcopy(rows[f]) for f in active_ids(d) if f in rows]


def feature(d, fid):
    for row in all_rows(d):
        if row.get("kind") == "feature" and row["id"] == fid:
            return copy.deepcopy(row)
    return None


def bends(d) -> list:
    by = {}
    for row in all_rows(d):
        if row.get("kind") == "bend":
            by.setdefault(row["feature"], []).append(row)
    out = []
    for fid in active_ids(d):
        out.extend(copy.deepcopy(sorted(by.get(fid, []), key=lambda r: r.get("seq", 0))))
    return out


def bend(d, bid):
    for row in all_rows(d):
        if row.get("kind") == "bend" and row["id"] == bid:
            return copy.deepcopy(row)
    return None
