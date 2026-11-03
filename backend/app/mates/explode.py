import copy
import math

import numpy as np

from app.assembly import store as A
from app.assembly import xform
from app.mates import store as S
from app.param.units import mm_per_unit
from app.solid import work

AXES = {"x": (1, 0, 0), "-x": (-1, 0, 0), "y": (0, 1, 0), "-y": (0, -1, 0), "z": (0, 0, 1), "-z": (0, 0, -1)}
MAX_STEPS = 500


def views(d) -> dict:
    return S.header(d).setdefault("explode", {"views": {}, "active": ""})


def _save(d, h) -> None:
    S.save_header(d, h)


def unit_dir(value) -> list:
    if isinstance(value, str):
        key = value.strip().lower().replace("+", "")
        if key not in AXES:
            raise S.MateRefused("Direction %s is not x, y, z, -x, -y or -z." % value)
        return [float(v) for v in AXES[key]]
    v = np.asarray(value, dtype=float).reshape(-1)
    if v.size != 3 or not np.all(np.isfinite(v)) or float(np.linalg.norm(v)) < 1e-9:
        raise S.MateRefused("A direction is three numbers that are not all zero.")
    return [float(x) for x in v / np.linalg.norm(v)]


def clean_step(d, spec: dict, sid: int) -> dict:
    comps = [str(c) for c in (spec.get("comps") or [])]
    if not comps:
        raise S.MateRefused("An explode step needs at least one component.")
    for c in comps:
        rec = A.get(d, c)
        if rec is None:
            raise S.MateRefused("There is no component %s." % c)
    dist = float(spec.get("dist", 0.0))
    if not math.isfinite(dist):
        raise S.MateRefused("The distance must be a finite number.")
    return {"id": sid, "name": str(spec.get("name") or "Step %d" % sid)[:80], "comps": list(dict.fromkeys(comps)), "dir": unit_dir(spec.get("dir", "z")), "dist": dist}


def get_view(d, name: str) -> dict:
    v = views(d)["views"].get(name)
    if v is None:
        raise S.MateRefused("There is no explode view %s." % name)
    return v


def listing(d) -> dict:
    h = views(d)
    return {"active": h.get("active", ""), "views": {k: copy.deepcopy(v) for k, v in h["views"].items()}}


def new_view(d, name: str) -> dict:
    name = str(name or "").strip()
    if not name:
        raise S.MateRefused("Give the explode view a name.")
    h = S.header(d)
    ex = h.setdefault("explode", {"views": {}, "active": ""})
    if name in ex["views"]:
        raise S.MateRefused("There is already an explode view %s." % name)
    ex["views"][name] = {"steps": [], "name": name}
    if not ex.get("active"):
        ex["active"] = name
    _save(d, h)
    return ex["views"][name]


def delete_view(d, name: str) -> None:
    h = S.header(d)
    ex = h["explode"]
    if name not in ex["views"]:
        raise S.MateRefused("There is no explode view %s." % name)
    del ex["views"][name]
    if ex.get("active") == name:
        ex["active"] = next(iter(ex["views"]), "")
    _save(d, h)


def set_active(d, name: str) -> None:
    h = S.header(d)
    if name and name not in h["explode"]["views"]:
        raise S.MateRefused("There is no explode view %s." % name)
    h["explode"]["active"] = name
    _save(d, h)


def add_step(d, name: str, spec: dict, index=None) -> dict:
    h = S.header(d)
    ex = h["explode"]
    if name not in ex["views"]:
        raise S.MateRefused("There is no explode view %s." % name)
    steps = ex["views"][name]["steps"]
    if len(steps) >= MAX_STEPS:
        raise S.MateRefused("A view holds at most %d steps." % MAX_STEPS)
    sid = int(h.get("next_step", 1))
    h["next_step"] = sid + 1
    step = clean_step(d, spec, sid)
    if index is None or int(index) >= len(steps):
        steps.append(step)
    else:
        steps.insert(max(0, int(index)), step)
    _save(d, h)
    return step


def edit_step(d, name: str, sid: int, spec: dict) -> dict:
    h = S.header(d)
    steps = h["explode"]["views"].get(name, {}).get("steps")
    if steps is None:
        raise S.MateRefused("There is no explode view %s." % name)
    for i, s in enumerate(steps):
        if s["id"] == int(sid):
            merged = {**s, **{k: v for k, v in spec.items() if v is not None}}
            steps[i] = clean_step(d, merged, s["id"])
            _save(d, h)
            return steps[i]
    raise S.MateRefused("There is no step %s in %s." % (sid, name))


def remove_step(d, name: str, sid: int) -> None:
    h = S.header(d)
    steps = h["explode"]["views"].get(name, {}).get("steps")
    if steps is None:
        raise S.MateRefused("There is no explode view %s." % name)
    keep = [s for s in steps if s["id"] != int(sid)]
    if len(keep) == len(steps):
        raise S.MateRefused("There is no step %s in %s." % (sid, name))
    h["explode"]["views"][name]["steps"] = keep
    _save(d, h)


def move_step(d, name: str, sid: int, index: int) -> list:
    h = S.header(d)
    steps = h["explode"]["views"].get(name, {}).get("steps")
    if steps is None:
        raise S.MateRefused("There is no explode view %s." % name)
    cur = next((i for i, s in enumerate(steps) if s["id"] == int(sid)), None)
    if cur is None:
        raise S.MateRefused("There is no step %s in %s." % (sid, name))
    s = steps.pop(cur)
    steps.insert(max(0, min(int(index), len(steps))), s)
    _save(d, h)
    return steps


def origin_of(rec: dict) -> np.ndarray:
    return xform.as_matrix(rec.get("transform"))[:3, 3].copy()


def pose(d, name: str, t=None) -> dict:
    view = get_view(d, name)
    steps = view["steps"]
    n = len(steps)
    t = float(n if t is None else t)
    t = max(0.0, min(float(n), t))
    offsets = {}
    lines = []
    for i, s in enumerate(steps):
        f = max(0.0, min(1.0, t - i))
        vec = np.asarray(s["dir"], dtype=float) * float(s["dist"])
        for c in s["comps"]:
            rec = A.get(d, c)
            if rec is None:
                continue
            before = offsets.get(c, np.zeros(3)).copy()
            offsets[c] = before + vec * f
            start = origin_of(rec) + before
            lines.append({"step": s["id"], "comp": c, "from": start.tolist(), "to": (start + vec).tolist(), "progress": f})
    mats = {}
    for c, off in offsets.items():
        rec = A.get(d, c)
        m = xform.as_matrix(rec.get("transform")).copy()
        m[:3, 3] += off
        mats[c] = xform.to_list(m)
    return {"view": name, "t": t, "steps": n, "progress": [max(0.0, min(1.0, t - i)) for i in range(n)], "offsets": {c: v.tolist() for c, v in offsets.items()}, "matrices": mats, "lines": lines}


def suggest(doc, save_as=None, margin=0.1) -> dict:
    from app.mates import interf

    d = doc.drawing
    items, meta, mmu = interf.gather(doc)
    by_top = {}
    for it in items:
        m = meta[it["key"]]
        if m["top"] in by_top:
            continue
        by_top[m["top"]] = it
    if len(by_top) < 2:
        raise S.MateRefused("An explode suggestion needs at least two components with solids.")
    res = work.kcall("asm_blocking", {"items": list(by_top.values())}, work.LONG)
    block = res["blocking"]
    cid_of = {it["key"]: top for top, it in by_top.items()}
    box = {}
    for top, it in by_top.items():
        bb = work.kcall("bounds", {"id": it["id"]}, work.SHORT)
        m = np.array(it["matrix"]).reshape(3, 4)
        lo, hi = np.array(bb["min"]), np.array(bb["max"])
        pts = np.array([[x, y, z, 1.0] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
        w = pts @ m.T
        box[top] = (w.min(axis=0) / mmu, w.max(axis=0) / mmu)
    allc = np.mean([(b[0] + b[1]) / 2 for b in box.values()], axis=0)
    span = max(float(np.max(b[1] - b[0])) for b in box.values())
    fixed = {t for t in by_top if A.get(d, t).get("fixed")}
    remaining = set(by_top)
    steps = []
    notes = []
    guard = 0
    while len([t for t in remaining if t not in fixed]) and guard < len(by_top) + 2:
        guard += 1
        free = {}
        for top in remaining - fixed:
            it = by_top[top]
            opts = []
            for entry in block[it["key"]]:
                who = {cid_of[k] for k in entry["blockers"] if cid_of.get(k) in remaining}
                if not who:
                    opts.append(entry["dir"])
            if opts:
                free[top] = opts
        forced = False
        if not free:
            forced = True
            top = min(remaining - fixed, key=lambda t: min(len({cid_of[k] for k in e["blockers"] if cid_of.get(k) in remaining}) for e in block[by_top[t]["key"]]))
            best = min(block[by_top[top]["key"]], key=lambda e: len({cid_of[k] for k in e["blockers"] if cid_of.get(k) in remaining}))
            free[top] = [best["dir"]]
            notes.append("%s is interlocked with the others; its step is a guess." % A.get(d, top)["label"])
        groups = {}
        for top, opts in free.items():
            centre = (box[top][0] + box[top][1]) / 2
            out = centre - allc

            def score(v):
                v = np.asarray(v, dtype=float)
                return (float(v @ out) / (np.linalg.norm(out) + 1e-9)) + (0.25 if v[2] > 0 else 0.0)

            pick = max(opts, key=score)
            groups.setdefault(tuple(int(x) for x in pick), []).append(top)
        for dirv, tops in groups.items():
            dv = np.asarray(dirv, dtype=float)
            dist = 0.0
            for top in tops:
                lo, hi = box[top]
                gap = 0.0
                for other, (olo, ohi) in box.items():
                    if other == top:
                        continue
                    perp = [k for k in range(3) if abs(dv[k]) < 0.5]
                    if all(lo[k] < ohi[k] and olo[k] < hi[k] for k in perp):
                        k = int(np.argmax(np.abs(dv)))
                        gap = max(gap, (ohi[k] - lo[k]) if dv[k] > 0 else (hi[k] - olo[k]))
                dist = max(dist, gap)
            dist = (dist if dist > 0 else span * 0.5) + span * margin
            steps.append({"id": len(steps) + 1, "name": "Step %d" % (len(steps) + 1), "comps": sorted(tops, key=lambda t: int(t[1:])), "dir": list(map(float, dv)), "dist": round(dist, 4), "interlocked": forced})
        remaining -= {t for ts in groups.values() for t in ts}
    out = {"steps": steps, "notes": notes, "suggestion": True, "blocked_by_fixed": sorted(fixed)}
    if save_as:
        h = S.header(d)
        ex = h["explode"]
        ex["views"][save_as] = {"steps": [], "name": save_as}
        sid = int(h.get("next_step", 1))
        for s in steps:
            ex["views"][save_as]["steps"].append({"id": sid, "name": s["name"], "comps": s["comps"], "dir": s["dir"], "dist": s["dist"]})
            sid += 1
        h["next_step"] = sid
        if not ex.get("active"):
            ex["active"] = save_as
        S.save_header(d, h)
        out["saved_as"] = save_as
    return out
