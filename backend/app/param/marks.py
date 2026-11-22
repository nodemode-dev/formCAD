import math
import weakref

from app.doc import curvepath, nurbs
from app.param import adapt, ops
from app.param import store as S

TONES = {"under": [59, 130, 246], "over": [239, 68, 68], "fully": None, "dangling": [234, 179, 8]}
_cache = weakref.WeakKeyDictionary()


def point_of(ent, part: str):
    part = (part or "whole").lower()
    k = ent.kind
    if k == "line":
        if part == "start":
            return [ent.start[0], ent.start[1]]
        if part == "end":
            return [ent.end[0], ent.end[1]]
        return [(ent.start[0] + ent.end[0]) / 2.0, (ent.start[1] + ent.end[1]) / 2.0]
    if k == "point":
        return [ent.position[0], ent.position[1]]
    if k in ("circle", "ellipse"):
        return [ent.center[0], ent.center[1]]
    if k == "arc":
        c, r = ent.center, ent.radius
        if part == "center":
            return [c[0], c[1]]
        sweep = (ent.end_angle - ent.start_angle) % math.tau
        a = ent.start_angle if part == "start" else ent.end_angle if part == "end" else ent.start_angle + sweep / 2.0
        return [c[0] + r * math.cos(a), c[1] + r * math.sin(a)]
    if k == "spline":
        c = curvepath.spline_curve(ent)
        if c is None:
            return None
        lo, hi = c.domain()
        u = lo if part == "start" else hi if part == "end" else 0.5 * (lo + hi)
        q = nurbs.point_at(c, u)
        return [q[0], q[1]]
    if k == "lwpolyline" and ent.vertices:
        if part[:1] == "v" and part[1:].isdigit() and int(part[1:]) < len(ent.vertices):
            p = ent.vertices[int(part[1:])]["p"]
            return [p[0], p[1]]
        if part[:1] == "s" and part[1:].isdigit():
            i = int(part[1:])
            n = len(ent.vertices)
            if i < n:
                a, b = ent.vertices[i]["p"], ent.vertices[(i + 1) % n]["p"]
                return [(a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0]
        p = ent.vertices[0]["p"]
        return [p[0], p[1]]
    return None


def visible(cfg: dict, key: str, except_key: str, handle: int) -> bool:
    inside = handle in cfg.get(except_key, ())
    return (cfg.get(key, "all") == "all") != inside


def compute(doc) -> dict:
    d = doc.drawing
    out = {"status": {}, "glyphs": {}, "dims": {}, "sketch": {}}
    recs = S.constraints(d)
    sketches = S.sketches(d)
    if not recs and not sketches:
        return out
    cfg = S.settings(d)
    drafting = sorted({h for r in recs if not r.get("sketch") and not r.get("dangling") for h in adapt.handles_of(r)})
    if drafting:
        try:
            st = ops.status(d, handles=drafting)
            for h, v in st["entities"].items():
                out["status"][int(h)] = v
        except S.ParamError:
            pass
    for sk in sketches:
        try:
            st = ops.status(d, sketch=sk["name"])
        except S.ParamError:
            continue
        for h, v in st["entities"].items():
            out["status"][int(h)] = dict(v)
        for h in sk["entities"]:
            out["sketch"][h] = {"name": sk["name"], "status": st["status"], "dof": st["dof"]}
            if h in sk["construction"]:
                out["sketch"][h]["construction"] = True
    slots = {}
    for r in recs:
        hs = sorted(set(adapt.handles_of(r)))
        ents = [(h, d.get(h)) for h in hs]
        if any(e is None for _h, e in ents):
            continue
        for h, part in r["refs"]:
            h = int(h)
            ent = d.get(h)
            p = point_of(ent, part)
            if p is None:
                continue
            if r.get("label"):
                if not visible(cfg, "dims", "dim_except", h):
                    continue
                if len(r["refs"]) > 1 and h != int(r["refs"][0][0]):
                    continue
                q = point_of(d.get(int(r["refs"][-1][0])), r["refs"][-1][1]) if len(r["refs"]) > 1 else None
                at = [(p[0] + q[0]) / 2.0, (p[1] + q[1]) / 2.0] if q else p
                out["dims"].setdefault(h, []).append({"id": r["id"], "name": r["label"], "expr": r.get("expr") or "", "value": r.get("value"), "driving": bool(r.get("driving", True)), "kind": r["kind"], "p": at})
            else:
                if not visible(cfg, "bars", "bar_except", h):
                    continue
                n = slots.get(h, 0)
                slots[h] = n + 1
                out["glyphs"].setdefault(h, []).append({"id": r["id"], "k": r["kind"], "p": p, "slot": n, "dangling": bool(r.get("dangling"))})
    return out


def data_for(doc) -> dict:
    key = (doc.rev, doc.state_id)
    hit = _cache.get(doc)
    if hit is not None and hit[0] == key:
        return hit[1]
    data = compute(doc)
    _cache[doc] = (key, data)
    return data


def mark_for(doc, handle: int):
    if not S.has_constraints(doc.drawing) and not S.sketches(doc.drawing):
        return None
    data = data_for(doc)
    st = data["status"].get(handle)
    sk = data["sketch"].get(handle)
    glyphs = data["glyphs"].get(handle)
    dims = data["dims"].get(handle)
    if st is None and sk is None and not glyphs and not dims:
        return None
    state = st["status"] if st else "none"
    mark = {"t": "cbar", "state": state, "dof": st["dof"] if st else 0, "rgb": TONES.get(state), "glyphs": glyphs or [], "dims": dims or []}
    if any(g["dangling"] for g in mark["glyphs"]):
        mark["dangling"] = True
    if sk is not None:
        mark["sketch"] = sk
    return mark
