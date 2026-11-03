import copy

TABLE = "mates"
HEADER = "MATES"
SCHEMA = 1


class MateRefused(ValueError):
    def __init__(self, message: str, explanation: dict | None = None):
        super().__init__(message)
        self.message = message
        self.explanation = explanation or {}


def blank() -> dict:
    return {"schema": SCHEMA, "next": 1, "next_step": 1, "explode": {"views": {}, "active": ""}, "settings": {"fuzzy": 0.0, "clearance": 0.0, "min_volume": 0.0}}


def header(d) -> dict:
    out = blank()
    raw = d.header.get(HEADER)
    if isinstance(raw, dict):
        for k, v in raw.items():
            out[k] = copy.deepcopy(v)
    return out


def save_header(d, h: dict) -> None:
    d.set_header(HEADER, copy.deepcopy(h))


def records(d) -> list:
    t = d.tables.get(TABLE)
    return sorted(t.values(), key=lambda r: int(r["id"])) if t is not None else []


def key(mid: int) -> str:
    return "M%d" % int(mid)


def get(d, mid):
    t = d.tables.get(TABLE)
    if t is None:
        return None
    if isinstance(mid, str) and not mid.isdigit():
        hit = t.get(mid)
        if hit is not None:
            return hit
        for r in t.values():
            if r.get("label", "").casefold() == mid.casefold():
                return r
        return None
    return t.get(key(int(mid)))


def put(d, rec: dict) -> None:
    rec = copy.deepcopy(rec)
    rec["name"] = key(rec["id"])
    d.table_set(TABLE, rec)


def drop(d, mid: int) -> None:
    d.table_remove(TABLE, key(mid))


def next_id(d) -> int:
    h = header(d)
    n = int(h["next"])
    h["next"] = n + 1
    save_header(d, h)
    return n
