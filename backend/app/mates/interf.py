import numpy as np

from app.assembly import parts, walk, xform
from app.mates import store as S
from app.param.units import mm_per_unit
from app.solid import surfwork, work

MAX_ITEMS = 400


def matrix12(m: np.ndarray, mmu: float) -> list:
    out = [float(v) for v in m[:3, :4].reshape(-1)]
    for k in (3, 7, 11):
        out[k] *= mmu
    return out


def gather(doc, poses=None) -> tuple:
    d = doc.drawing
    mmu = mm_per_unit(d)
    insts = walk.instances(doc)
    tops = {}
    for i in insts:
        if i.depth == 0 and not i.index:
            tops[i.cid] = i.world
    items, meta = [], {}
    for inst in insts:
        lp = inst.part
        if lp is None or getattr(lp, "is_assembly", False) or not lp.bodies or inst.suppressed:
            continue
        world = inst.world
        top = inst.path[0].split("#")[0].split("/")[0] if inst.path else inst.cid
        if poses and top in poses and top in tops:
            new = xform.as_matrix(poses[top])
            world = new @ np.linalg.inv(tops[top]) @ world
        for b in lp.bodies:
            key = inst.key if len(lp.bodies) == 1 else "%s|%s" % (inst.key, b.handle)
            try:
                wid = parts.shapes(lp, b)
            except work.SolidError:
                continue
            items.append({"key": key, "id": wid, "matrix": matrix12(world, mmu)})
            meta[key] = {"cid": inst.cid, "key": inst.key, "label": inst.record["label"], "top": top}
    if len(items) > MAX_ITEMS:
        raise S.MateRefused("More than %d bodies cannot be checked together." % MAX_ITEMS)
    return items, meta, mmu


def settings(d) -> dict:
    return S.header(d).get("settings", {})


def check(doc, clearance=None, fuzzy=None, min_volume=None, poses=None, ignore=None, pairs=None) -> dict:
    d = doc.drawing
    items, meta, mmu = gather(doc, poses)
    tol = surfwork.model_tolerance(d)
    cfg = settings(d)
    fz = float(fuzzy) * mmu if fuzzy else (float(cfg.get("fuzzy") or 0.0) * mmu or tol["tol"])
    cl = clearance if clearance is not None else cfg.get("clearance")
    cl = float(cl) * mmu if cl else None
    mv = float(min_volume) * mmu**3 if min_volume else (float(cfg.get("min_volume") or 0.0) * mmu**3 or 1e-3)
    skip = []
    for a, b in ignore or []:
        skip.append([a, b])
    params = {"items": items, "fuzzy": fz, "min_volume": mv, "skip": skip}
    if cl:
        params["clearance"] = cl
    if pairs:
        params["pairs"] = pairs
    res = work.kcall("asm_interference", params, work.LONG)

    def label(k):
        return meta.get(k, {}).get("label", k)

    out = {"interferences": [], "clearances": [], "errors": res.get("errors", []), "stats": res["stats"], "ms": res["ms"], "fuzzy": fz / mmu, "linear": res["linear"] / mmu, "bodies": len(items), "units_mm": mmu}
    for r in res["interferences"]:
        out["interferences"].append({"a": r["a"], "b": r["b"], "label_a": label(r["a"]), "label_b": label(r["b"]), "components": [meta[r["a"]]["cid"], meta[r["b"]]["cid"]], "volume": r["volume"] / mmu**3, "volume_mm3": r["volume"], "centre": [v / mmu for v in r["centre"]]})
    for r in res["clearances"]:
        out["clearances"].append({"a": r["a"], "b": r["b"], "label_a": label(r["a"]), "label_b": label(r["b"]), "components": [meta[r["a"]]["cid"], meta[r["b"]]["cid"]], "distance": r["distance"] / mmu, "contact": r["contact"], "point_a": [v / mmu for v in r["point_a"]], "point_b": [v / mmu for v in r["point_b"]]})
    out["count"] = len(out["interferences"])
    return out
