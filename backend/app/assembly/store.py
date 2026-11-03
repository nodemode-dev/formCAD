import copy
import re

SCHEMA = 1
HEADER = "ASSEMBLY"
COMPONENTS = "components"
PATTERNS = "patterns"
CONFIGS = "asmconfigs"
TYPES = ("part", "assembly", "embedded")
SEARCH_STEPS = ("relative", "absolute", "same_folder", "search_folders", "deep")
DEFAULT_ORDER = ("relative", "absolute", "same_folder", "search_folders")
DEFAULT_CONFIG = "Default"
MAX_COMPONENTS = 20000
LABEL_MAX = 120
ID_RE = re.compile(r"^C(\d+)$")


class AssemblyError(ValueError):
    pass


def blank() -> dict:
    return {
        "schema": SCHEMA, "next": 1, "next_pattern": 1, "active_config": DEFAULT_CONFIG, "search_folders": [], "search_order": list(DEFAULT_ORDER),
        "embed_cache": True, "finds": {}, "find_next": 1,
    }


def header(d) -> dict:
    raw = d.header.get(HEADER)
    out = blank()
    if isinstance(raw, dict):
        out.update(copy.deepcopy(raw))
    return out


def is_assembly(d) -> bool:
    return isinstance(d.header.get(HEADER), dict)


def save_header(d, h: dict) -> None:
    d.set_header(HEADER, copy.deepcopy(h))


def ensure(d) -> dict:
    h = header(d)
    if not is_assembly(d):
        save_header(d, h)
    elif int(h.get("schema", 1)) > SCHEMA:
        raise AssemblyError("This assembly was written with schema %s by a newer FormCAD; this version reads schema %d." % (h.get("schema"), SCHEMA))
    return h


def writable(d) -> dict:
    h = ensure(d)
    return h


def _table(d, name):
    return d.tables.get(name)


def components(d) -> list:
    tbl = _table(d, COMPONENTS)
    if tbl is None:
        return []
    return sorted(tbl.values(), key=lambda r: int(r.get("n", 0)))


def get(d, cid: str):
    tbl = _table(d, COMPONENTS)
    return tbl.get(cid) if tbl is not None else None


def put(d, rec: dict) -> None:
    rec = copy.deepcopy(rec)
    rec["name"] = rec["id"]
    d.table_set(COMPONENTS, rec)


def drop(d, cid: str) -> None:
    d.table_remove(COMPONENTS, cid)


def patterns(d) -> list:
    tbl = _table(d, PATTERNS)
    if tbl is None:
        return []
    return sorted(tbl.values(), key=lambda r: int(re.sub(r"\D", "", r["id"]) or 0))


def get_pattern(d, pid: str):
    tbl = _table(d, PATTERNS)
    return tbl.get(pid) if tbl is not None else None


def put_pattern(d, rec: dict) -> None:
    rec = copy.deepcopy(rec)
    rec["name"] = rec["id"]
    d.table_set(PATTERNS, rec)


def drop_pattern(d, pid: str) -> None:
    d.table_remove(PATTERNS, pid)


def configs(d) -> list:
    tbl = _table(d, CONFIGS)
    return tbl.values() if tbl is not None else []


def get_config(d, name: str):
    tbl = _table(d, CONFIGS)
    return tbl.get(name) if tbl is not None else None


def need(d, cid: str) -> dict:
    rec = get(d, str(cid or "").strip())
    if rec is None:
        raise AssemblyError("There is no component %s." % cid)
    return rec


def find_component(d, ident) -> dict:
    key = str(ident or "").strip()
    rec = get(d, key)
    if rec is not None:
        return rec
    hits = [r for r in components(d) if r["label"].casefold() == key.casefold()]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise AssemblyError("%s names more than one component; use the id (%s)." % (key, ", ".join(r["id"] for r in hits)))
    raise AssemblyError("There is no component %s." % key)


def new_id(h: dict) -> tuple:
    n = int(h["next"])
    h["next"] = n + 1
    return "C%d" % n, n


def new_pattern_id(h: dict) -> str:
    n = int(h["next_pattern"])
    h["next_pattern"] = n + 1
    return "P%d" % n


def clean_label(text, fallback: str) -> str:
    s = re.sub(r"[\x00-\x1f]", " ", str(text or "")).strip()[:LABEL_MAX]
    return s or fallback


def unique_label(d, base: str, ignore: str = "") -> str:
    used = {r["label"].casefold() for r in components(d) if r["id"] != ignore}
    if base.casefold() not in used:
        return base
    i = 2
    while "%s<%d>" % (base, i) in {u for u in used} or ("%s<%d>" % (base, i)).casefold() in used:
        i += 1
    return "%s<%d>" % (base, i)
