from app.part import rebuild, store
from app.part.registry import PartError
from app.sheetmetal import records, rule
from app.solid import work


def body_id(doc):
    d = doc.drawing
    rebuild.ensure_built(doc)
    t = store.tree(d)
    order = list(t["order"])
    if t.get("rollback") in order:
        order = order[: order.index(t["rollback"]) + 1]
    cache = rebuild.cache_of(doc)
    for fid in reversed(order):
        e = cache.entries.get(fid)
        if e is not None and not e.error and e.wid:
            return e.wid
    return None


def verify(doc) -> dict:
    d = doc.drawing
    rl = rule.rule_of_part(d)
    if rl is None:
        raise PartError("The part has no sheet metal rule yet.")
    wid = body_id(doc)
    if wid is None:
        raise PartError("The part has no body to measure.")
    bends = records.bends(d)
    radii = sorted({round(b["radius"], 9) for b in bends} | {rl["inner_radius_mm"]})
    out = work.kcall("sm_verify", {"id": wid, "thickness": rl["thickness_mm"], "radii": radii}, work.LONG)
    out["thickness_mm"] = rl["thickness_mm"]
    out["radii_mm"] = radii
    out["bends"] = len(bends)
    return out
