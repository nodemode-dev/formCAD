import copy
import math

import numpy as np

from app.assembly import store, xform
from app.assembly.store import AssemblyError

KINDS = ("linear", "circular", "feature")
MAX_COUNT = 2000


def _count(v, name, lo=1) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise AssemblyError("%s must be a whole number." % name)
    if n < lo or n > MAX_COUNT:
        raise AssemblyError("%s must be from %d to %d." % (name, lo, MAX_COUNT))
    return n


def _num(v, name) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise AssemblyError("%s must be a number." % name)
    if not math.isfinite(f):
        raise AssemblyError("%s must be a finite number." % name)
    return f


def clean_params(kind: str, p: dict, old: dict | None = None) -> dict:
    p = dict(p or {})
    cur = copy.deepcopy(old or {})
    cur.update({k: v for k, v in p.items() if v is not None or k in ("dir2",)})
    try:
        if kind == "linear":
            d1 = xform.unit(cur.get("dir1", (1, 0, 0)), "Direction 1")
            out = {"dir1": [float(v) for v in d1], "spacing1": _num(cur.get("spacing1", 10.0), "Spacing 1"), "count1": _count(cur.get("count1", 2), "Count 1", 1)}
            if cur.get("dir2") is not None:
                d2 = xform.unit(cur["dir2"], "Direction 2")
                out.update(dir2=[float(v) for v in d2], spacing2=_num(cur.get("spacing2", 10.0), "Spacing 2"), count2=_count(cur.get("count2", 2), "Count 2", 1))
            else:
                out.update(dir2=None, spacing2=0.0, count2=1)
            if out["count1"] * out["count2"] > MAX_COUNT:
                raise AssemblyError("A pattern may hold at most %d copies." % MAX_COUNT)
            return out
        if kind == "circular":
            ax = xform.unit(cur.get("axis_dir", (0, 0, 1)), "Axis direction")
            org = xform.vec(cur.get("axis_origin", (0, 0, 0)), "Axis origin")
            return {"axis_origin": [float(v) for v in org], "axis_dir": [float(v) for v in ax], "count": _count(cur.get("count", 4), "Count", 1), "angle": _num(cur.get("angle", 360.0), "Angle"), "equal": bool(cur.get("equal", True))}
        if kind == "feature":
            return {"target": str(cur.get("target") or ""), "feature": str(cur.get("feature") or ""), "ref_site": int(cur.get("ref_site", 0)), "flip": bool(cur.get("flip", False)), "sites": cur.get("sites") or [], "sites_unit": str(cur.get("sites_unit") or "mm")}
    except xform.TransformError as err:
        raise AssemblyError(str(err))
    raise AssemblyError("A pattern is linear, circular or feature.")


def linear(params: dict) -> list:
    d1 = np.asarray(params["dir1"], dtype=float)
    d2 = np.asarray(params["dir2"], dtype=float) if params.get("dir2") is not None else None
    n1, n2 = int(params["count1"]), int(params.get("count2") or 1)
    out = []
    for j in range(n2):
        for i in range(n1):
            idx = i + j * n1
            if idx == 0:
                continue
            v = d1 * params["spacing1"] * i
            if d2 is not None:
                v = v + d2 * params["spacing2"] * j
            out.append((idx, xform.translation(v)))
    return out


def circular(params: dict) -> list:
    n = int(params["count"])
    ang = float(params["angle"])
    if n < 2:
        return []
    full = abs(abs(ang) - 360.0) < 1e-9
    step = ang / n if (params.get("equal", True) and full) else ang / (n - 1)
    return [(k, xform.rotation(params["axis_dir"], k * step, params["axis_origin"])) for k in range(1, n)]


def feature(params: dict, target_local, scale_to_units: float) -> list:
    sites = params.get("sites") or []
    if len(sites) < 2:
        return []
    ref = int(params.get("ref_site", 0))
    if not 0 <= ref < len(sites):
        raise AssemblyError("The reference site %d is not one of the %d sites." % (ref, len(sites)))
    flip = -1.0 if params.get("flip") else 1.0

    def frame(site):
        c = np.asarray(site["c"], dtype=float) * scale_to_units
        n = np.asarray(site["n"], dtype=float) * flip
        local = xform.placement(c, n)
        return np.asarray(target_local, dtype=float) @ local

    f_ref = frame(sites[ref])
    inv = xform.inverse(f_ref)
    out = []
    for k, s in enumerate(sites):
        if k == ref:
            continue
        out.append((len(out) + 1, frame(s) @ inv))
    return out


def transforms(pat: dict, seed_local, target_local=None, scale_to_units: float = 1.0) -> list:
    kind = pat["kind"]
    if kind == "linear":
        items = linear(pat["params"])
    elif kind == "circular":
        items = circular(pat["params"])
    else:
        items = feature(pat["params"], target_local if target_local is not None else xform.identity(), scale_to_units)
    skip = {int(i) for i in pat.get("skip") or []}
    return [(i, m) for i, m in items if i not in skip]


def count_of(pat: dict) -> int:
    kind = pat["kind"]
    p = pat["params"]
    if kind == "linear":
        return int(p["count1"]) * int(p.get("count2") or 1)
    if kind == "circular":
        return int(p["count"])
    return len(p.get("sites") or [])


def new_record(pid: str, kind: str, seed: str, params: dict, label: str = "") -> dict:
    if kind not in KINDS:
        raise AssemblyError("A pattern is linear, circular or feature.")
    return {"name": pid, "id": pid, "kind": kind, "label": label or pid, "seed": seed, "params": params, "skip": [], "suppressed": False}


def feature_sites(lp, fid: str) -> list:
    from app.part import store as PS
    from app.part import tree as PT
    from app.solid import work

    d = lp.drawing
    if not PS.has_part(d):
        raise AssemblyError("That part has no feature tree, so a feature cannot drive a pattern.")
    rec = PS.get(d, fid)
    if rec is None:
        for r in PS.records(d).values():
            if r["label"].casefold() == str(fid).casefold():
                rec = r
                break
    if rec is None:
        raise AssemblyError("The part has no feature %s." % fid)
    t = PS.tree(d)
    body_h = int(t.get("body") or 0)
    body = next((b for b in lp.bodies if b.handle == body_h), lp.bodies[0] if lp.bodies else None)
    if body is None:
        raise AssemblyError("The part has no solid body.")
    names = t.get("names") or {}
    pid_by_key = {k: v for k, v in names.items()}
    prefix = rec["id"] + ":"
    wanted = [pid for k, pid in pid_by_key.items() if k.startswith(prefix) and not k[len(prefix):].startswith("e(")]
    if not wanted:
        raise AssemblyError("The feature %s did not create any named face, so there is nothing to follow." % rec["label"])
    wid = work.worker_id(lp.drawing, body.ent)

    def geom(idx):
        return work.kcall("geometry", {"id": wid, "face": idx}, work.SHORT)

    seeds = []
    for pid in set(wanted):
        if pid in body.face_ids:
            g = geom(body.face_ids.index(pid))
            if g.get("kind") == "cylinder":
                seeds.append(g)
    if not seeds:
        raise AssemblyError("The feature %s made no cylindrical face; a pattern follows holes and round bosses." % rec["label"])
    radius = seeds[0]["radius"]
    axis = np.asarray(seeds[0]["axis"], dtype=float)
    box = body.summary.get("bbox") or [0, 0, 0, 1, 1, 1]
    size = max(1e-9, math.dist(box[:3], box[3:]))
    tol = size * 1e-6
    sites = []
    for idx in range(len(body.face_ids)):
        g = geom(idx)
        if g.get("kind") != "cylinder" or abs(g["radius"] - radius) > max(tol, 1e-6 * radius):
            continue
        a = np.asarray(g["axis"], dtype=float)
        if abs(abs(float(np.dot(a, axis))) - 1.0) > 1e-6:
            continue
        o = np.asarray(g["axis_origin"], dtype=float)
        c = np.asarray(g["centroid"], dtype=float)
        a = a / np.linalg.norm(a)
        p = o + a * float(np.dot(c - o, a))
        a = a if np.dot(a, axis) > 0 else -a
        for s in sites:
            d0 = p - s["ps"][0]
            if np.linalg.norm(d0 - a * float(np.dot(d0, a))) < max(radius * 1e-3, tol):
                s["ps"].append(p)
                break
        else:
            sites.append({"ps": [p], "n": a})
    out = []
    for s in sites:
        c = np.mean(np.asarray(s["ps"]), axis=0)
        out.append({"c": [float(v) for v in c], "n": [float(v) for v in s["n"]], "radius": float(radius), "faces": len(s["ps"])})
    out.sort(key=lambda s: (round(s["c"][2], 6), round(s["c"][1], 6), round(s["c"][0], 6)))
    return out
