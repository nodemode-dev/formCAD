import math

from app.analysis.combs import CURVE_KINDS
from app.solid import surfwork as sw
from app.solid import work
from app.solid.work import SolidError

CODES = {"vertex": 0, "mid": 1, "centre": 2, "quadrant": 3, "end": 4, "intersection": 5, "perpendicular": 6, "nearest": 7, "surface": 8, "curve": 9}
ALIASES = {"endpoint": "end", "midpoint": "mid", "center": "centre", "quad": "quadrant", "int": "intersection", "perp": "perpendicular", "near": "nearest", "onsurface": "surface", "oncurve": "curve", "on surface": "surface", "on curve": "curve"}
BIAS = {"vertex": 1.0, "end": 1.0, "centre": 0.9, "quadrant": 0.8, "intersection": 0.9, "mid": 0.7, "perpendicular": 0.5, "curve": 0.2, "nearest": 0.1, "surface": 0.0}
MAX_BODIES = 64
MAX_CURVES = 400


def clean_modes(modes) -> list:
    if modes is None or modes == "all" or modes == ["all"]:
        return list(CODES)
    out = []
    for m in modes:
        w = ALIASES.get(str(m).lower().strip(), str(m).lower().strip())
        if w not in CODES:
            raise SolidError("Unknown 3D snap %s; choose from %s." % (m, ", ".join(CODES)))
        if w not in out:
            out.append(w)
    return out


def vec3(raw, name):
    try:
        v = [float(c) for c in raw]
    except (TypeError, ValueError):
        raise SolidError("The %s needs three numbers." % name)
    if len(v) != 3 or not all(math.isfinite(c) for c in v):
        raise SolidError("The %s needs three finite numbers." % name)
    return v


def query(doc, ray: dict, aperture: float, modes=None, base=None, plane=None, handles=None, limit: int = 60) -> dict:
    mode_list = clean_modes(modes)
    if not isinstance(ray, dict):
        raise SolidError("Give the pick ray as origin and dir.")
    o, dr = vec3(ray.get("origin"), "ray origin"), vec3(ray.get("dir"), "ray direction")
    if math.sqrt(sum(c * c for c in dr)) < 1e-12:
        raise SolidError("The pick ray has no direction.")
    if not math.isfinite(float(aperture)) or float(aperture) <= 0:
        raise SolidError("The aperture must be a positive number.")
    limit = max(1, min(int(limit), 200))
    with doc.lock:
        d = doc.drawing
        s = work.mm(d)
        wanted = set(int(h) for h in handles) if handles else None
        items, bodies = [], {}
        curves = 0
        for e in d.ordered_entities():
            if wanted and e.handle not in wanted:
                continue
            if not d.visible(e):
                continue
            if e.kind == "solidbody":
                if len(bodies) >= MAX_BODIES:
                    continue
                bodies[e.handle] = e
                items.append({"id": work.worker_id(d, e), "ref": e.handle})
            elif e.kind in CURVE_KINDS and curves < MAX_CURVES:
                try:
                    items.append({"curve": sw.curve_spec(d, e), "ref": e.handle})
                    curves += 1
                except SolidError:
                    continue
        params = {
            "items": items, "ray": {"origin": [c * s for c in o], "dir": dr}, "aperture": float(aperture) * s, "modes": mode_list,
            "base": [c * s for c in vec3(base, "base point")] if base is not None else None,
            "plane": {"x": list(vec3(plane["x"], "plane x")), "y": list(vec3(plane["y"], "plane y"))} if plane else None,
            "limit": limit * 2,
        }
    if not items:
        return {"candidates": [], "modes": mode_list, "mm_per_unit": s}
    res = work.kcall("an_snap", params, work.SHORT)
    out = []
    for c in res["candidates"]:
        ent = bodies.get(c.get("ref"))
        pid = None
        if ent is not None and c.get("index", -1) is not None and c.get("index", -1) >= 0:
            ids = ent.edge_ids if c["element"] == "edge" else ent.face_ids if c["element"] == "face" else []
            if c["index"] < len(ids):
                pid = ids[c["index"]]
        rec = {
            "kind": c["kind"], "code": CODES[c["kind"]], "point": [v / s for v in c["point"]], "dist": c["dist"] / s,
            "handle": c.get("ref"), "element": c["element"], "index": c.get("index"), "pid": pid,
            "rank": c["dist"] / s - BIAS.get(c["kind"], 0.0) * float(aperture) * 0.15,
        }
        for key in ("normal", "axis", "param", "ref2", "index2"):
            if c.get(key) is not None:
                rec[key] = c[key]
        out.append(rec)
    out.sort(key=lambda r: (r["rank"], r["code"]))
    return {"candidates": out[:limit], "modes": mode_list, "mm_per_unit": s}
