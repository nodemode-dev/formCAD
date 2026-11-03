import json
from collections import OrderedDict

from app.vault.base import MAX_DOCJSON, MAX_ENTITIES, VaultError

TABLE_LISTS = ("parts", "assemblies", "pmi", "graphs")
ID_FIELDS = ("id", "name", "handle", "key")
CACHE_SIZE = 4
_cache: OrderedDict = OrderedDict()


class EMap:
    def __init__(self):
        self.items: dict = {}
        self.orders: dict = {}
        self.names: dict = {}
        self.meta: dict = {}


def _label(rec) -> str:
    if isinstance(rec, dict):
        for f in ("label", "name"):
            v = rec.get(f)
            if isinstance(v, str) and v:
                return v
        if "kind" in rec and "handle" in rec:
            return "%s %s" % (rec["kind"], rec["handle"])
    return ""


def _keyed(records, field_order=ID_FIELDS):
    if not isinstance(records, list) or not records or not all(isinstance(r, dict) for r in records):
        return None
    for f in field_order:
        keys = [r.get(f) for r in records]
        if all(isinstance(k, (str, int)) and not isinstance(k, bool) for k in keys) and len(set(map(str, keys))) == len(keys):
            return f
    return None


def build(raw: bytes) -> EMap:
    if len(raw) > MAX_DOCJSON:
        raise VaultError("document.json is larger than the merge limit.")
    try:
        doc = json.loads(raw)
    except RecursionError:
        raise VaultError("document.json is nested too deeply.")
    except ValueError as err:
        raise VaultError("document.json is not valid JSON: %s" % err)
    if not isinstance(doc, dict):
        raise VaultError("document.json must hold an object.")
    m = EMap()
    m.meta["root_order"] = list(doc.keys())
    for k, v in doc.items():
        if k == "header" and isinstance(v, dict):
            m.orders["order:header"] = ["header:" + x for x in v.keys()]
            for hk, hv in v.items():
                m.items["header:" + hk] = hv
                m.names["header:" + hk] = hk
        elif k == "tables" and isinstance(v, dict):
            m.orders["order:tables"] = ["tbl:" + x for x in v.keys()]
            for tn, recs in v.items():
                field = _keyed(recs, ("name",))
                if field is None:
                    m.items["doc:tables." + tn] = recs
                    m.names["doc:tables." + tn] = tn
                    continue
                names = []
                for r in recs:
                    eid = "table:%s:%s" % (tn, r[field])
                    m.items[eid] = r
                    m.names[eid] = "%s %s" % (tn, _label(r) or r[field])
                    names.append(eid)
                m.orders["order:table:" + tn] = names
        elif k == "spaces" and isinstance(v, list) and all(isinstance(s, str) for s in v) and len(set(v)) == len(v):
            ids = []
            for s in v:
                m.items["space:" + s] = True
                m.names["space:" + s] = "space " + s
                ids.append("space:" + s)
            m.orders["order:spaces"] = ids
        elif k == "entities" and isinstance(v, list):
            ids = []
            for r in v:
                h = r.get("handle") if isinstance(r, dict) else None
                if not isinstance(h, int):
                    raise VaultError("document.json holds an entity without a handle.")
                eid = "entity:%d" % h
                if eid in m.items:
                    raise VaultError("document.json holds two entities with handle %d." % h)
                m.items[eid] = r
                m.names[eid] = _label(r)
                ids.append(eid)
            m.orders["order:entities"] = ids
        elif k in TABLE_LISTS and isinstance(v, list):
            field = _keyed(v)
            if field is None:
                m.items["doc:" + k] = v
                m.names["doc:" + k] = k
            else:
                ids = []
                for r in v:
                    eid = "list:%s:%s" % (k, r[field])
                    m.items[eid] = r
                    m.names[eid] = "%s %s" % (k, _label(r) or r[field])
                    ids.append(eid)
                m.orders["order:list:" + k] = ids
                m.meta.setdefault("list_fields", {})[k] = field
        elif k == "next_handle":
            m.meta["next_handle"] = v
        else:
            m.items["doc:" + k] = v
            m.names["doc:" + k] = k
        if len(m.items) > MAX_ENTITIES:
            raise VaultError("The document holds more than %d entities; it is too large to compare." % MAX_ENTITIES)
    return m


def cached(key: bytes, raw_loader) -> EMap:
    got = _cache.get(key)
    if got is not None:
        _cache.move_to_end(key)
        return got
    m = build(raw_loader())
    _cache[key] = m
    while len(_cache) > CACHE_SIZE:
        _cache.popitem(last=False)
    return m


def kind_of(eid: str) -> str:
    return eid.split(":", 1)[0]


def _nosig(value):
    if isinstance(value, dict):
        return {k: _nosig(v) for k, v in value.items() if k != "sig"}
    if isinstance(value, list):
        return [_nosig(v) for v in value]
    return value


def derived_entity(rec) -> bool:
    return isinstance(rec, dict) and rec.get("kind") == "solidbody" and isinstance(rec.get("source"), dict) and rec["source"].get("op") == "part"


def core(eid: str, rec):
    if not isinstance(rec, dict):
        return rec
    if eid.startswith("table:features:"):
        out = {k: v for k, v in rec.items() if k != "state"}
        if "refs" in out:
            out["refs"] = _nosig(out["refs"])
        return out
    if eid == "header:PARTTREE":
        return {k: v for k, v in rec.items() if k != "built"}
    return rec


def display(m: EMap, eid: str) -> str:
    return m.names.get(eid) or eid


def assemble(keys: list, items: dict, orders: dict, next_handle) -> dict:
    out: dict = {}
    for k in keys:
        if k == "header":
            hdr = {}
            for hid in orders.get("order:header", []):
                if hid in items:
                    hdr[hid[7:]] = items[hid]
            out[k] = hdr
        elif k == "tables":
            tables = {}
            for tid in orders.get("order:tables", []):
                tn = tid[4:]
                if "doc:tables." + tn in items:
                    tables[tn] = items["doc:tables." + tn]
                elif "order:table:" + tn in orders:
                    tables[tn] = [items[e] for e in orders["order:table:" + tn] if e in items]
            out[k] = tables
        elif k == "spaces":
            out[k] = [e.split(":", 1)[1] for e in orders.get("order:spaces", []) if e in items]
        elif k == "entities":
            out[k] = [items[e] for e in orders.get("order:entities", []) if e in items]
        elif k in TABLE_LISTS:
            if "doc:" + k in items:
                out[k] = items["doc:" + k]
            else:
                out[k] = [items[e] for e in orders.get("order:list:" + k, []) if e in items]
        elif k == "next_handle":
            out[k] = next_handle
        elif "doc:" + k in items:
            out[k] = items["doc:" + k]
    return out


def scan_strings(value, out: set, depth: int = 0) -> None:
    if depth > 8:
        return
    if isinstance(value, str):
        out.add(value)
    elif isinstance(value, dict):
        for v in value.values():
            scan_strings(v, out, depth + 1)
    elif isinstance(value, list):
        for v in value:
            scan_strings(v, out, depth + 1)


def walk_diff(a, b, path: str, out: list, depth: int = 0, limit: int = 40) -> None:
    if len(out) >= limit:
        return
    if a == b:
        return
    if isinstance(a, dict) and isinstance(b, dict) and depth < 4:
        for k in sorted(set(a) | set(b), key=str):
            if k not in a:
                out.append({"path": path + str(k), "a": None, "b": b[k], "change": "added"})
            elif k not in b:
                out.append({"path": path + str(k), "a": a[k], "b": None, "change": "removed"})
            else:
                walk_diff(a[k], b[k], path + str(k) + ".", out, depth + 1, limit)
            if len(out) >= limit:
                return
        return
    out.append({"path": path.rstrip(".") or ".", "a": a, "b": b, "change": "changed"})


def diff(a: EMap, b: EMap, limit: int = 500) -> dict:
    added, removed, changed = [], [], []
    derived = 0
    for eid in b.items:
        if eid not in a.items and b.items[eid] not in ([], {}, None):
            added.append({"entity": eid, "name": display(b, eid), "change": "added", "fields": []})
    for eid in a.items:
        if eid not in b.items:
            if a.items[eid] not in ([], {}, None):
                removed.append({"entity": eid, "name": display(a, eid), "change": "removed", "fields": []})
        elif a.items[eid] != b.items[eid]:
            if derived_entity(a.items[eid]) or derived_entity(b.items[eid]):
                derived += 1
                continue
            ca, cb = core(eid, a.items[eid]), core(eid, b.items[eid])
            if ca == cb:
                derived += 1
                continue
            fields: list = []
            walk_diff(ca, cb, "", fields)
            changed.append({"entity": eid, "name": display(b, eid), "change": "changed", "fields": fields})
    orders = []
    for k in sorted(set(a.orders) | set(b.orders)):
        oa = [e for e in a.orders.get(k, []) if e in b.items]
        ob = [e for e in b.orders.get(k, []) if e in a.items]
        if oa != ob:
            orders.append({"entity": k, "name": "order of " + k.split(":", 1)[1], "change": "reordered", "fields": []})
    rows = added + removed + changed + orders
    return {"summary": {"added": len(added), "removed": len(removed), "changed": len(changed), "reordered": len(orders), "derived": derived}, "items": rows[:limit], "truncated": len(rows) > limit}
