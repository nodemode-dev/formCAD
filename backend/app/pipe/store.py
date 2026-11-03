import copy
import math
import re

from app.pipe import limits
from app.pipe.limits import PipeError

TABLE = "pipes"
STYLES = ("tube", "pipe")
END_KINDS = ("plain", "flange")
LABEL = "Tube specs are user-editable examples authored by FormCAD, not values from any standard or catalogue. Enter the figures from the datasheet and bender die set you own."
EXAMPLES = [
    {"name": "Example 10 x 1 tube", "od": 10.0, "wall": 1.0, "material": "user entered", "min_clr_factor": 1.5, "min_straight_factor": 2.0, "springback": 0.0},
    {"name": "Example 25 x 2 tube", "od": 25.0, "wall": 2.0, "material": "user entered", "min_clr_factor": 1.5, "min_straight_factor": 2.0, "springback": 0.0},
    {"name": "Example 60 x 3 pipe", "od": 60.0, "wall": 3.0, "material": "user entered", "min_clr_factor": 1.5, "min_straight_factor": 2.0, "springback": 0.0},
]
SPEC_KEYS = ("od", "wall", "material", "min_clr_factor", "min_straight_factor", "springback", "elbow_clr_factor", "tee_c_factor", "bend_table", "note")


def rows(d, kind: str) -> list:
    tbl = d.tables.get(TABLE)
    out = [copy.deepcopy(r) for r in (tbl.values() if tbl is not None else []) if r.get("kind") == kind]
    return sorted(out, key=lambda r: (len(r["id"]), r["id"]))


def get(d, rid, kind=None):
    tbl = d.tables.get(TABLE)
    row = tbl.get(str(rid)) if tbl is not None else None
    if row is None or (kind and row.get("kind") != kind):
        return None
    return copy.deepcopy(row)


def need(d, rid, kind: str) -> dict:
    row = get(d, rid, kind)
    if row is None:
        raise PipeError("There is no %s %s." % ("tube spec" if kind == "spec" else "pipe run", rid))
    return row


def next_id(d, prefix: str) -> str:
    top = 0
    pat = re.compile(r"^%s(\d+)$" % prefix)
    for r in (d.tables[TABLE].values() if TABLE in d.tables else []):
        m = pat.match(str(r.get("id", "")))
        if m:
            top = max(top, int(m.group(1)))
    return "%s%d" % (prefix, top + 1)


def num(v, label, lo=None, hi=None, positive=False):
    if isinstance(v, bool):
        raise PipeError("%s must be a number." % label)
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise PipeError("%s must be a number." % label)
    if not math.isfinite(x) or (positive and x <= 0) or (lo is not None and x < lo) or (hi is not None and x > hi):
        raise PipeError("%s is out of range." % label)
    return x


def clean_spec(raw: dict, base=None) -> dict:
    row = dict(base or {})
    row.update({k: v for k, v in (raw or {}).items() if k in SPEC_KEYS or k in ("name", "label")})
    out = {"od": num(row.get("od"), "The outside diameter", 0.1, 5000.0, True), "wall": num(row.get("wall"), "The wall thickness", 0.01, 500.0, True)}
    if out["wall"] * 2 >= out["od"]:
        raise PipeError("The wall must be less than half the outside diameter.")
    out["label"] = str(row.get("label") or row.get("name") or "")[:80]
    out["material"] = str(row.get("material") or "")[:80]
    out["min_clr_factor"] = num(row.get("min_clr_factor", 1.5), "The minimum radius factor", 0.0, 100.0)
    out["min_straight_factor"] = num(row.get("min_straight_factor", 2.0), "The minimum straight factor", 0.0, 100.0)
    out["springback"] = num(row.get("springback", 0.0), "The springback", -30.0, 30.0)
    out["elbow_clr_factor"] = num(row.get("elbow_clr_factor", 1.5), "The elbow radius factor", 0.5, 20.0, True)
    out["tee_c_factor"] = num(row.get("tee_c_factor", 1.5), "The tee centre-to-end factor", 0.5, 20.0, True)
    table = row.get("bend_table") or []
    if not isinstance(table, list) or len(table) > 200:
        raise PipeError("The bend table is a list of at most 200 rows.")
    out["bend_table"] = [{"clr": num(t.get("clr"), "A bend table radius", 0.0, 1e5, True), "developed90": num(t.get("developed90"), "A bend table developed length", 0.0, 1e6, True)} for t in table]
    out["note"] = str(row.get("note") or "")[:300]
    return out


def clean_point(p, label):
    if isinstance(p, dict):
        comp = str(p.get("component") or "").strip()
        if not comp:
            raise PipeError("%s needs a component." % label)
        loc = p.get("local") or [0, 0, 0]
        if not isinstance(loc, (list, tuple)) or len(loc) != 3:
            raise PipeError("%s needs three local coordinates." % label)
        return {"component": comp, "local": [num(c, label, -1e7, 1e7) for c in loc]}
    if not isinstance(p, (list, tuple)) or len(p) != 3:
        raise PipeError("%s needs three coordinates." % label)
    return [num(c, label, -1e7, 1e7) for c in p]


def clean_run(raw: dict, base=None) -> dict:
    row = dict(base or {})
    row.update({k: v for k, v in (raw or {}).items() if k not in ("id", "kind")})
    style = str(row.get("style") or "tube")
    if style not in STYLES:
        raise PipeError("A run style is one of %s." % ", ".join(STYLES))
    pts = row.get("points") or []
    if not isinstance(pts, list):
        raise PipeError("The points are a list.")
    limits.need(len(pts), "points", "Route points")
    if len(pts) < 2:
        raise PipeError("A route needs at least two points.")
    out = {"label": str(row.get("label") or row.get("name") or "")[:80], "spec": str(row.get("spec") or ""), "style": style}
    out["points"] = [clean_point(p, "Point %d" % (i + 1)) for i, p in enumerate(pts)]
    rad = row.get("radii") or []
    if not isinstance(rad, list) or len(rad) > max(len(pts) - 2, 0):
        raise PipeError("There is one radius per interior point at most.")
    out["radii"] = [None if r in (None, "", 0) else num(r, "A bend radius", 0.0, 1e6, True) for r in rad]
    out["clr"] = None if row.get("clr") in (None, "") else num(row.get("clr"), "The centreline radius", 0.0, 1e6, True)
    ends = row.get("ends") or {}
    out["ends"] = {"a": str(ends.get("a") or "plain"), "b": str(ends.get("b") or "plain"), "a_thickness": num(ends.get("a_thickness", 0.0), "End A flange thickness", 0.0, 1e4), "b_thickness": num(ends.get("b_thickness", 0.0), "End B flange thickness", 0.0, 1e4)}
    for k in ("a", "b"):
        if out["ends"][k] not in END_KINDS:
            raise PipeError("An end is one of %s." % ", ".join(END_KINDS))
    taps = row.get("taps") or []
    reds = row.get("reducers") or []
    limits.need(len(taps), "taps", "Taps")
    limits.need(len(reds), "reducers", "Reducers")
    if style == "tube" and (taps or reds):
        raise PipeError("Taps and reducers belong to pipe style runs; a bent tube has only bends.")
    out["taps"] = [{"segment": int(t["segment"]), "distance": num(t["distance"], "A tap distance", 0.0, 1e7), "c": None if t.get("c") in (None, "") else num(t["c"], "A tap centre-to-end", 0.0, 1e5, True), "branch": t.get("branch")} for t in taps]
    out["reducers"] = [{"segment": int(r["segment"]), "distance": num(r["distance"], "A reducer distance", 0.0, 1e7), "od_to": num(r["od_to"], "A reducer outside diameter", 0.1, 5000.0, True), "wall_to": None if r.get("wall_to") in (None, "") else num(r["wall_to"], "A reducer wall", 0.01, 500.0, True), "length": None if r.get("length") in (None, "") else num(r["length"], "A reducer length", 0.0, 1e5, True)} for r in reds]
    out["part"] = str(row.get("part") or "")[:60]
    out["spool"] = str(row.get("spool") or "")[:60]
    out["bodies"] = [int(h) for h in (row.get("bodies") or [])]
    return out


def add(d, kind: str, prefix: str, fields: dict) -> dict:
    limits.need(len(rows(d, kind)) + 1, "specs" if kind == "spec" else "runs", "Records")
    rid = next_id(d, prefix)
    row = {"name": rid, "id": rid, "kind": kind, **fields}
    if not row.get("label"):
        row["label"] = rid
    d.table_set(TABLE, row)
    return copy.deepcopy(row)


def put(d, rid: str, kind: str, fields: dict) -> dict:
    need(d, rid, kind)
    row = d.modify_record(TABLE, rid)
    row.update(fields)
    return copy.deepcopy(row)


def drop(d, rid: str, kind: str) -> None:
    need(d, rid, kind)
    d.table_remove(TABLE, rid)
