import copy
import json
import math
import os

from app.sheetmetal import bend

HEADER = "SHEETTABLES"
DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "sheetmetal", "bend_tables.json")
BUILTIN_RATIO = "air-forming-ratio"
MAX_TABLES = 200
MAX_SETS = 200
MAX_POINTS = 400
ID_MAX = 60


class TableError(ValueError):
    pass


def library() -> dict:
    try:
        with open(DATA, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        raw = {}
    return raw if isinstance(raw, dict) else {}


def builtin_tables() -> dict:
    return {
        BUILTIN_RATIO: {
            "id": BUILTIN_RATIO,
            "name": "Air forming K by radius to thickness ratio",
            "mode": "k",
            "axis": "ratio",
            "sets": [{"points": [[0.0, bend.KMIN], [3.0, 0.5], [1000.0, 0.5]]}],
            "origin": "builtin",
            "source": "S. Benson, Calculating k-factors for the press brake, The Fabricator (formula, cap at R/T = 3)",
        }
    }


def clean_id(raw) -> str:
    tid = str(raw or "").strip()
    if not tid or len(tid) > ID_MAX or any(c in tid for c in "\n\r\t/\\"):
        raise TableError("A table id holds 1 to %d characters on one line." % ID_MAX)
    return tid


def num(value, what, lo=None, hi=None):
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise TableError("%s must be a number." % what)
    if not math.isfinite(v) or (lo is not None and v < lo) or (hi is not None and v > hi):
        raise TableError("%s is out of range." % what)
    return v


def validate(table) -> dict:
    if not isinstance(table, dict):
        raise TableError("A bend table is an object.")
    mode = str(table.get("mode") or "").strip()
    if mode not in ("k", "ba", "bd"):
        raise TableError("A bend table gives K, BA or BD: set mode to k, ba or bd.")
    axis = str(table.get("axis") or "angle").strip()
    if axis not in ("angle", "ratio"):
        raise TableError("A bend table runs over angle or ratio.")
    sets_in = table.get("sets")
    if not isinstance(sets_in, list) or len(sets_in) > MAX_SETS:
        raise TableError("A bend table holds up to %d sets." % MAX_SETS)
    sets = []
    for i, s in enumerate(sets_in, 1):
        if not isinstance(s, dict):
            raise TableError("Set %d is not an object." % i)
        pts = s.get("points")
        if not isinstance(pts, list) or not pts or len(pts) > MAX_POINTS:
            raise TableError("Set %d needs 1 to %d points." % (i, MAX_POINTS))
        points = []
        for pt in pts:
            if not isinstance(pt, (list, tuple)) or len(pt) != 2:
                raise TableError("Set %d: a point is [x, value]." % i)
            x = num(pt[0], "Set %d x" % i, 0.0, 1.0e6)
            v = num(pt[1], "Set %d value" % i, 0.0, 1.0e6)
            if mode == "k" and not 0.0 < v < 1.0:
                raise TableError("Set %d: a K-factor lies between 0 and 1." % i)
            points.append([x, v])
        row = {"points": points}
        for key in ("thickness", "radius"):
            if s.get(key) is not None:
                row[key] = num(s[key], "Set %d %s" % (i, key), 0.0, 1.0e6)
        sets.append(row)
    out = {"mode": mode, "axis": axis, "sets": sets, "tolerance": num(table.get("tolerance", 1e-6), "tolerance", 0.0, 1.0)}
    out["name"] = str(table.get("name") or "")[:ID_MAX]
    out["source"] = str(table.get("source") or "")[:400]
    return out


def document(d) -> dict:
    raw = d.header.get(HEADER)
    out = {"tables": {}, "gauges": {}}
    if isinstance(raw, dict):
        out["tables"] = copy.deepcopy(raw.get("tables") or {})
        out["gauges"] = copy.deepcopy(raw.get("gauges") or {})
    return out


def save(d, data) -> None:
    d.set_header(HEADER, copy.deepcopy(data))


def get(d, tid):
    tid = str(tid or "")
    if not tid:
        return None
    doc = document(d)["tables"]
    if tid in doc:
        t = copy.deepcopy(doc[tid])
        t["id"], t["origin"] = tid, "document"
        return t
    for row in library().get("tables") or []:
        if isinstance(row, dict) and row.get("id") == tid:
            t = validate(row)
            t["id"], t["origin"] = tid, "library"
            return t
    b = builtin_tables().get(tid)
    return copy.deepcopy(b) if b else None


def listing(d) -> list:
    out = []
    for tid, t in builtin_tables().items():
        out.append({"id": tid, "name": t["name"], "mode": t["mode"], "axis": t["axis"], "sets": len(t["sets"]), "origin": "builtin", "source": t["source"]})
    for row in library().get("tables") or []:
        if isinstance(row, dict) and row.get("id"):
            try:
                t = validate(row)
            except TableError:
                continue
            out.append({"id": row["id"], "name": t["name"], "mode": t["mode"], "axis": t["axis"], "sets": len(t["sets"]), "origin": "library", "source": t["source"]})
    for tid, t in sorted(document(d)["tables"].items()):
        out.append({"id": tid, "name": t.get("name", ""), "mode": t.get("mode"), "axis": t.get("axis"), "sets": len(t.get("sets") or []), "origin": "document", "source": t.get("source", "")})
    return out


def put(d, tid, table) -> dict:
    tid = clean_id(tid)
    if tid in builtin_tables():
        raise TableError("%s is a built-in table; give your own table another id." % tid)
    clean = validate(table)
    data = document(d)
    if tid not in data["tables"] and len(data["tables"]) >= MAX_TABLES:
        raise TableError("The document holds up to %d bend tables." % MAX_TABLES)
    data["tables"][tid] = clean
    save(d, data)
    return {"id": tid, **clean, "origin": "document"}


def remove(d, tid) -> None:
    tid = str(tid or "")
    data = document(d)
    if tid not in data["tables"]:
        raise TableError("There is no document bend table %s." % tid)
    del data["tables"][tid]
    save(d, data)


def gauges(d) -> list:
    out = []
    for row in library().get("gauges") or []:
        if isinstance(row, dict) and row.get("id"):
            out.append({**copy.deepcopy(row), "origin": "library"})
    for gid, row in sorted(document(d)["gauges"].items()):
        out.append({**copy.deepcopy(row), "id": gid, "origin": "document"})
    return out


def put_gauge(d, gid, row) -> dict:
    gid = clean_id(gid)
    if not isinstance(row, dict):
        raise TableError("A gauge table is an object.")
    entries = row.get("entries")
    if not isinstance(entries, list) or not entries or len(entries) > MAX_POINTS:
        raise TableError("A gauge table needs entries of gauge and thickness.")
    clean = []
    for e in entries:
        if not isinstance(e, dict) or "gauge" not in e:
            raise TableError("A gauge entry is {gauge, thickness_mm}.")
        clean.append({"gauge": str(e["gauge"])[:20], "thickness_mm": num(e.get("thickness_mm"), "Gauge thickness", 1e-3, 1.0e3)})
    data = document(d)
    data["gauges"][gid] = {"name": str(row.get("name") or "")[:ID_MAX], "material": str(row.get("material") or "")[:ID_MAX], "source": str(row.get("source") or "")[:400], "entries": clean}
    save(d, data)
    return {"id": gid, **data["gauges"][gid], "origin": "document"}


def remove_gauge(d, gid) -> None:
    data = document(d)
    if str(gid) not in data["gauges"]:
        raise TableError("There is no document gauge table %s." % gid)
    del data["gauges"][str(gid)]
    save(d, data)
