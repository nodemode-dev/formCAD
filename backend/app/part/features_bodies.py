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


def tool_ids(step, what):
    out = []
    for h in step.p("tools") or []:
        try:
            e = step.d.get(int(h))
        except (TypeError, ValueError):
            e = None
        if e is None or e.kind != "solidbody":
            raise PartError("The body with handle %s is gone; the %s cannot be rebuilt." % (h, what))
        out.append(work.worker_id(step.d, e))
    return out


def combine_plan(step):
    op = str(step.p("op") or "")
    if op not in OPS:
        raise PartError("Choose add, subtract or common.")
    if not step.p("tools"):
        raise PartError("Choose the bodies to combine with.")
    wids = [step.base] + tool_ids(step, "combine")
    return {"method": "combine", "params": {"op": op, "bodies": wids, "fuzzy": float(step.d.tolerances["absolute"]) * step.mm, "force": bool(step.p("force"))}}


def split_plan(step):
    from app.bodies import multibody

    planes = step.p("planes") or []
    if not planes and not step.p("tools"):
        raise PartError("Give a cutting plane or a surface body to split with.")
    try:
        specs = [multibody.plane_spec(step.d, p, step.mm) for p in planes]
    except multibody.BodyError as err:
        raise PartError(str(err))
    return {"method": "split", "params": {"body": step.base, "planes": specs, "tools": tool_ids(step, "split"), "fuzzy": float(step.d.tolerances["absolute"]) * step.mm, "force": bool(step.p("force"))}}


def copy_plan(step):
    one = move_plan(step)["params"]
    extras = []
    for k in range(1, int(step.p("count") or 1) + 1):
        call = {}
        if "translate" in one:
            call["translate"] = [v * k for v in one["translate"]]
        if "rotate" in one:
            call["rotate"] = dict(one["rotate"], degrees=one["rotate"]["degrees"] * k)
        extras.append({"method": "transform", "params": call})
    return {"passthrough": True, "extras": extras}


register(FeatureType("move_body", "Move Body", group="body", plan=move_plan, params=[
    Param("translate", "vector", None, label="Move by"),
    Param("rotate", "json", None, label="Rotate"),
], roles=("~",)))

register(FeatureType("combine_body", "Combine", group="body", plan=combine_plan, params=[
    Param("op", "enum", "add", choices=list(OPS), label="Operation"),
    Param("tools", "json", None, label="Tool bodies"),
    Param("force", "bool", False, label="Force"),
], roles=("~",)))

register(FeatureType("split_body", "Split Body", group="body", plan=split_plan, params=[
    Param("planes", "json", None, label="Cutting planes"),
    Param("tools", "json", None, label="Cutting bodies"),
    Param("keep", "int", 1, min=1, max=64, label="Piece kept in the part"),
    Param("force", "bool", False, label="Force"),
], roles=("~",)))

register(FeatureType("copy_body", "Copy Body", group="body", plan=copy_plan, params=[
    Param("translate", "vector", None, label="Move by"),
    Param("rotate", "json", None, label="Rotate"),
    Param("count", "int", 1, min=1, max=500, label="Copies"),
], roles=("~",)))
