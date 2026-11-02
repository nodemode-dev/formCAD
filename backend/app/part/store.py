import copy

TABLE = "features"
HEADER = "PARTTREE"


def blank() -> dict:
    return {"order": [], "rollback": None, "next": 1, "body": 0, "names": {}, "auto": True, "workspace": "drafting", "built": ""}


def tree(d) -> dict:
    raw = d.header.get(HEADER)
    out = blank()
    if isinstance(raw, dict):
        out.update(copy.deepcopy(raw))
    return out


def save_tree(d, t: dict) -> None:
    d.set_header(HEADER, copy.deepcopy(t))


def has_part(d) -> bool:
    raw = d.header.get(HEADER)
    return isinstance(raw, dict) and bool(raw.get("order"))


def records(d) -> dict:
    tbl = d.tables.get(TABLE)
    return {r["id"]: r for r in tbl.values()} if tbl is not None else {}


def get(d, fid: str):
    tbl = d.tables.get(TABLE)
    return tbl.get(fid) if tbl is not None else None


def put(d, rec: dict) -> None:
    rec = copy.deepcopy(rec)
    rec["name"] = rec["id"]
    d.table_set(TABLE, rec)


def drop(d, fid: str) -> None:
    d.table_remove(TABLE, fid)


def ordered(d, t=None) -> list:
    t = t or tree(d)
    recs = records(d)
    return [recs[f] for f in t["order"] if f in recs]


def new_id(t: dict) -> str:
    fid = "F%d" % t["next"]
    t["next"] += 1
    return fid


def blank_state() -> dict:
    return {"status": "stale", "message": "", "warnings": [], "ms": 0.0, "failed": {}, "hash": ""}
