import copy

from app.param import adapt, ops
from app.param import expr as X
from app.param import store as S

PLANES = {
    "XY": {"name": "XY", "origin": [0.0, 0.0, 0.0], "x": [1.0, 0.0, 0.0], "normal": [0.0, 0.0, 1.0]},
    "XZ": {"name": "XZ", "origin": [0.0, 0.0, 0.0], "x": [1.0, 0.0, 0.0], "normal": [0.0, -1.0, 0.0]},
    "YZ": {"name": "YZ", "origin": [0.0, 0.0, 0.0], "x": [0.0, 1.0, 0.0], "normal": [1.0, 0.0, 0.0]},
}
MAX_NAME = 64


def plane_of(plane, origin=None) -> dict:
    if isinstance(plane, dict):
        rec = {"name": str(plane.get("name") or "Custom"), "origin": [float(v) for v in plane.get("origin", [0, 0, 0])][:3], "x": [float(v) for v in plane.get("x", [1, 0, 0])][:3], "normal": [float(v) for v in plane.get("normal", [0, 0, 1])][:3]}
    else:
        key = str(plane or "XY").upper()
        if key not in PLANES:
            raise S.ParamError("The plane must be XY, XZ or YZ.")
        rec = copy.deepcopy(PLANES[key])
    if origin is not None:
        rec["origin"] = [float(v) for v in origin][:3]
    if len(rec["origin"]) != 3 or len(rec["x"]) != 3 or len(rec["normal"]) != 3:
        raise S.ParamError("A plane needs three-number origin, x axis and normal.")
    return rec


def find(d, name):
    rec = S.get_sketch(d, name)
    if rec is None:
        raise S.ParamError("There is no sketch named %s." % name)
    return rec


def check_name(d, name: str) -> None:
    if not name or len(name) > MAX_NAME or name.strip() != name or any(c in name for c in "@'\"\\/:"):
        raise S.ParamError("A sketch name holds 1 to %d characters and no @ ' \" / \\ or colon." % MAX_NAME)
    if S.get_sketch(d, name) is not None:
        raise S.ParamError("A sketch named %s already exists." % name)


def check_members(d, handles, name="") -> list:
    out = []
    for h in handles:
        h = int(h)
        ent = d.get(h)
        if ent is None:
            raise S.ParamError("Object %d does not exist." % h)
        if not adapt.constrainable(ent):
            raise S.ParamError(adapt.refuse_text(ent))
        other = ops.sketch_of(d, h)
        if other and other != name:
            raise S.ParamError("Object %d already belongs to sketch %s." % (h, other))
        if h not in out:
            out.append(h)
    return out


def create(d, name, plane="XY", handles=(), origin=None) -> dict:
    check_name(d, name)
    rec = {"name": name, "plane": plane_of(plane, origin), "entities": check_members(d, handles), "construction": [], "space": "model"}
    S.put_sketch(d, rec)
    ops.touch(d, rec["entities"])
    ops.mark(d)
    return info(d, name)


def add_entities(d, name, handles) -> dict:
    rec = copy.deepcopy(find(d, name))
    new = [h for h in check_members(d, handles, name) if h not in rec["entities"]]
    rec["entities"].extend(new)
    S.put_sketch(d, rec)
    ops.touch(d, new)
    ops.mark(d)
    return info(d, name)


def adopt(d) -> list:
    taken = []
    for rec in S.sketches(d):
        space = "sketch:" + rec["name"]
        have = set(rec["entities"])
        new = [h for h in d.spaces.get(space, []) if h not in have and h in d.ents]
        if new:
            add_entities(d, rec["name"], new)
            taken.extend(new)
    return taken


def remove_entities(d, name, handles) -> dict:
    rec = copy.deepcopy(find(d, name))
    gone = {int(h) for h in handles}
    for r in S.constraints(d):
        if r.get("sketch") == name and gone & set(adapt.handles_of(r)):
            raise S.ParamError("Delete the constraints on object %d first." % sorted(gone & set(adapt.handles_of(r)))[0])
    rec["entities"] = [h for h in rec["entities"] if h not in gone]
    rec["construction"] = [h for h in rec["construction"] if h not in gone]
    S.put_sketch(d, rec)
    ops.touch(d, gone)
    ops.mark(d)
    return info(d, name)


def set_construction(d, name, handles, flag=True) -> dict:
    rec = copy.deepcopy(find(d, name))
    for h in handles:
        h = int(h)
        if h not in rec["entities"]:
            raise S.ParamError("Object %d is not in sketch %s." % (h, name))
        if flag and h not in rec["construction"]:
            rec["construction"].append(h)
        if not flag and h in rec["construction"]:
            rec["construction"].remove(h)
    S.put_sketch(d, rec)
    ops.touch(d, handles)
    ops.mark(d)
    return info(d, name)


def delete(d, name) -> dict:
    rec = find(d, name)
    ids = [r["id"] for r in S.constraints(d) if r.get("sketch") == name]
    others = [r for r in S.dim_records(d) if r.get("sketch") != name]
    for r in S.dim_records(d):
        if r.get("sketch") == name:
            users = S.dependents(d, r["label"], dims=others)
            if users:
                raise S.ParamError("%s is used by %s." % (r["label"], users[0]))
    for cid in ids:
        S.drop_con(d, cid)
    d.table_remove(S.SKETCHES, name)
    ops.touch(d, rec["entities"])
    ops.mark(d)
    return {"deleted": name, "constraints": len(ids)}


def rename(d, old, new) -> dict:
    rec = copy.deepcopy(find(d, old))
    if new.casefold() != old.casefold():
        check_name(d, new)
    for r in S.dim_records(d):
        if r.get("expr") and any(s == old.casefold() for _n, s in X.references(r["expr"]) if s):
            raise S.ParamError("A dimension expression refers to %s@%s; edit it first." % (r["label"], old))
    d.table_remove(S.SKETCHES, old)
    rec["name"] = new
    S.put_sketch(d, rec)
    for r in S.constraints(d):
        if r.get("sketch") == old:
            q = copy.deepcopy(r)
            q["sketch"] = new
            S.put_con(d, q)
    ops.touch(d, rec["entities"])
    ops.mark(d)
    return info(d, new)


def prune(d, name=None) -> None:
    for rec in S.sketches(d):
        if name and rec["name"] != name:
            continue
        keep = [h for h in rec["entities"] if d.get(h) is not None]
        if len(keep) != len(rec["entities"]):
            q = copy.deepcopy(rec)
            q["entities"] = keep
            q["construction"] = [h for h in q["construction"] if h in keep]
            S.put_sketch(d, q)


def info(d, name) -> dict:
    rec = find(d, name)
    st = ops.status(d, sketch=name)
    cons = [r for r in S.constraints(d) if r.get("sketch") == name]
    dims = [{"id": r["id"], "name": r["label"], "kind": r["kind"], "expr": r.get("expr") or "", "value": r.get("value"), "driving": bool(r.get("driving", True))} for r in cons if r.get("label")]
    rels = [{"id": r["id"], "kind": r["kind"], "refs": r["refs"], "dangling": bool(r.get("dangling"))} for r in cons if not r.get("label")]
    return {"name": rec["name"], "plane": rec["plane"], "entities": S.members(d, rec), "construction": rec["construction"], "status": st["status"], "dof": st["dof"], "entityStatus": st["entities"], "relations": rels, "dimensions": dims, "redundant": st["redundant"], "conflicts": st["conflicts"], "dangling": st["dangling"], "ms": st["ms"]}


def listing(d) -> list:
    out = []
    for rec in sorted(S.sketches(d), key=lambda r: r["name"].casefold()):
        st = ops.status(d, sketch=rec["name"])
        out.append({"name": rec["name"], "plane": rec["plane"]["name"], "entities": len(rec["entities"]), "status": st["status"], "dof": st["dof"]})
    return out
