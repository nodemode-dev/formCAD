import copy
import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data" / "sim-materials.json"
SCALE = {"rho": 1.0, "E": 1e9, "nu": 1.0, "sigma_y": 1e6, "sigma_u": 1e6, "k": 1.0, "alpha": 1e-6, "cp": 1.0}
_cache: dict = {}


def raw() -> dict:
    if not _cache:
        _cache.update(json.loads(DATA.read_text(encoding="utf-8")))
    return _cache


def entry(row: dict) -> dict:
    data = raw()
    srcs = data["sources"]
    fields = {}
    sources = []
    for key, cell in row["values"].items():
        if not cell:
            fields[key] = None
            continue
        fields[key] = cell["value"] * SCALE[key]
        s = srcs[cell["source"]]
        item = {"field": key, "value": cell["value"], "org": s["org"], "title": s["title"], "url": s["url"], "note": cell.get("kind") or cell.get("note") or ""}
        sources.append(item)
    return {"id": row["id"], "name": row["name"], **fields, "sources": sources, "conflicts": list(row.get("conflicts") or []), "alternates": {k: [{"value": a["value"] * SCALE[k], "org": srcs[a["source"]]["org"], "title": srcs[a["source"]]["title"], "url": srcs[a["source"]]["url"], "note": a.get("note", "")} for a in (c.get("alternates") or [])] for k, c in row["values"].items() if c and c.get("alternates")}, "note": row.get("note", ""), "single_source": bool(row.get("single_source"))}


def library() -> dict:
    data = raw()
    return {"note": data["note"], "terms": data["terms"], "units": {"rho": "kg/m3", "E": "Pa", "nu": "1", "sigma_y": "Pa", "sigma_u": "Pa", "k": "W/m/K", "alpha": "1/K", "cp": "J/kg/K"}, "materials": [entry(r) for r in data["materials"]]}


def find(lib_id: str):
    for r in raw()["materials"]:
        if r["id"] == lib_id:
            return entry(r)
    return None


def fill(rawrow: dict) -> dict:
    lib = rawrow.get("library")
    if not lib:
        return rawrow
    e = find(str(lib))
    if e is None:
        raise ValueError("There is no library material %s." % lib)
    out = copy.deepcopy(rawrow)
    for key in SCALE:
        if out.get(key) in (None, "") and e.get(key) is not None:
            out[key] = e[key]
    if not out.get("sources"):
        out["sources"] = e["sources"]
    if not out.get("label") and not out.get("name"):
        out["name"] = e["name"]
    return out
