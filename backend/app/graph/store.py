import copy
import hashlib
import json
import os

from app.graph import model

TABLE = "graphs"
HEADER = "GRAPHS"
MAX_FILE = 32 * 1024 * 1024
EXT = ".graph"


class StoreError(ValueError):
    pass


def header(d) -> dict:
    raw = d.header.get(HEADER)
    out = {"schema": 1, "next": 1}
    if isinstance(raw, dict):
        out.update(copy.deepcopy(raw))
    return out


def save_header(d, h: dict) -> None:
    d.set_header(HEADER, copy.deepcopy(h))


def records(d) -> list:
    t = d.tables.get(TABLE)
    if t is None:
        return []
    return sorted(t.values(), key=lambda r: int(r.get("n", 0)))


def get(d, gid: str):
    t = d.tables.get(TABLE)
    if t is None or not gid:
        return None
    hit = t.get(str(gid))
    if hit is not None:
        return hit
    for r in t.values():
        if str(r.get("label", "")).casefold() == str(gid).casefold():
            return r
    return None


def need(d, gid: str) -> dict:
    rec = get(d, gid)
    if rec is None:
        raise StoreError("There is no graph %s." % gid)
    return rec


def next_id(d) -> tuple:
    h = header(d)
    n = int(h["next"])
    h["next"] = n + 1
    save_header(d, h)
    return n, "G%d" % n


def blank_definition(gid: str, name: str) -> dict:
    return model.Graph(gid, name).to_definition()


def normalise(defn: dict, gid: str, name: str = "") -> dict:
    g = model.Graph.from_definition(defn, gid)
    if name:
        g.name = name
        g.meta["name"] = name
    if g.readonly:
        out = g.to_definition()
        out["id"] = gid
        return out
    out = g.to_definition()
    out["id"] = gid
    return out


def put_record(d, rec: dict) -> None:
    d.table_set(TABLE, copy.deepcopy(rec))


def create(d, name: str = "", definition: dict = None) -> dict:
    n, gid = next_id(d)
    label = (name or (definition or {}).get("name") or "Graph %d" % n).strip()
    defn = normalise(definition, gid, label) if definition is not None else blank_definition(gid, label)
    defn["name"] = label
    rec = {"name": gid, "id": gid, "n": n, "label": label, "definition": defn}
    put_record(d, rec)
    return rec


def update(d, gid: str, definition: dict, label: str = None) -> dict:
    rec = need(d, gid)
    if rec["definition"].get("version") and model.version_tuple(rec["definition"]["version"])[0] > model.version_tuple(model.VERSION)[0]:
        raise model.GraphRefused("This graph was written by a newer version of formCAD and cannot be changed here.", "newer")
    if model.version_tuple(definition.get("version", model.VERSION))[0] > model.version_tuple(model.VERSION)[0] or model.version_tuple(definition.get("min_reader", model.MIN_READER)) > model.version_tuple(model.VERSION):
        raise model.GraphRefused("A definition from a newer format version cannot be stored as an edit.", "newer")
    g = model.Graph.from_definition(definition, rec["id"])
    bad = [w.id for w in g.wires.values() if w.disabled]
    if bad:
        raise model.GraphRefused("The definition holds wires that would make a loop: %s." % ", ".join(bad), "cycle", bad)
    out = g.to_definition()
    out["id"] = rec["id"]
    new = dict(rec)
    new["definition"] = out
    new["label"] = (label if label is not None else out.get("name") or rec["label"]) or rec["label"]
    out["name"] = new["label"]
    put_record(d, new)
    return new


def delete(d, gid: str) -> None:
    rec = need(d, gid)
    d.table_remove(TABLE, rec["name"])


def digest(defn: dict) -> str:
    return hashlib.sha1(json.dumps(defn, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def dumps(defn: dict) -> str:
    return json.dumps(defn, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def read_file(path: str) -> dict:
    full = os.path.abspath(os.path.expanduser(str(path or "")))
    if not os.path.isfile(full):
        raise StoreError("The file %s does not exist." % full)
    if os.path.getsize(full) > MAX_FILE:
        raise StoreError("That graph file is larger than %d MB." % (MAX_FILE // (1024 * 1024)))
    try:
        with open(full, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as err:
        raise StoreError("That file is not readable graph JSON: %s" % err)
    if not isinstance(data, dict) or data.get("format") != model.FORMAT:
        raise StoreError("That file is not a formCAD graph file.")
    return data


def write_file(path: str, defn: dict) -> None:
    out = copy.deepcopy(defn)
    out["format"] = model.FORMAT
    out.pop("id", None)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(dumps(out))


def import_file(d, path: str, name: str = "") -> dict:
    data = read_file(path)
    return create(d, name or data.get("name") or os.path.splitext(os.path.basename(path))[0], data)


def export_definition(d, gid: str) -> dict:
    return copy.deepcopy(need(d, gid)["definition"])
