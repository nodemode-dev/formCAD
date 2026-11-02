from app.part.registry import FeatureType, Param, PartError, register
from app.solid import work

OPS = ("add", "subtract", "common")


def move_plan(step):
    raw_t, raw_r = step.p("translate"), step.p("rotate")
    call = {}
    if raw_t is not None:
        if not isinstance(raw_t, (list, tuple)) or len(raw_t) != 3:
            raise PartError("Translate needs three numbers.")
        call["translate"] = [float(v) * step.mm for v in raw_t]
    if raw_r is not None:
        if not isinstance(raw_r, dict) or raw_r.get("axis") is None:
            raise PartError("Rotate needs an axis and degrees.")
        call["rotate"] = {"origin": [float(v) * step.mm for v in (raw_r.get("origin") or [0, 0, 0])], "axis": [float(v) for v in raw_r["axis"]], "degrees": float(raw_r.get("degrees", 0.0))}
    if not call:
        raise PartError("Give translate, rotate or both.")
    return {"method": "transform", "params": call}


def combine_plan(step):
    op = str(step.p("op") or "")
    if op not in OPS:
        raise PartError("Choose add, subtract or common.")
    handles = step.p("tools") or []
    if not handles:
        raise PartError("Choose the bodies to combine with.")
    wids = [step.base]
    for h in handles:
        try:
            e = step.d.get(int(h))
        except (TypeError, ValueError):
            e = None
        if e is None or e.kind != "solidbody":
            raise PartError("The body with handle %s is gone; the combine cannot be rebuilt." % h)
        wids.append(work.worker_id(step.d, e))
    return {"method": "combine", "params": {"op": op, "bodies": wids, "fuzzy": float(step.d.tolerances["absolute"]) * step.mm, "force": bool(step.p("force"))}}


register(FeatureType("move_body", "Move Body", group="body", plan=move_plan, params=[
    Param("translate", "vector", None, label="Move by"),
    Param("rotate", "json", None, label="Rotate"),
], roles=("~",)))

register(FeatureType("combine_body", "Combine", group="body", plan=combine_plan, params=[
    Param("op", "enum", "add", choices=list(OPS), label="Operation"),
    Param("tools", "json", None, label="Tool bodies"),
    Param("force", "bool", False, label="Force"),
], roles=("~",)))
