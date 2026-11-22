import copy

from app.param import adapt, explain
from app.param import expr as X
from app.param import store as S
from app.param import units as U
from app.solve.errors import SolverFault

TOL = 1e-12
STEPS = 8


class Refused(S.ParamError):
    def __init__(self, message: str, explanation=None):
        super().__init__(message)
        self.message = message
        self.explanation = explanation


def mark(d) -> None:
    rec = d.recorder
    if rec is not None:
        rec.constraint_done = True


def touch(d, handles) -> None:
    for h in handles:
        if d.get(h) is not None:
            d.modify(h)


def summary(rep) -> dict:
    return {"status": rep.status, "dof": rep.dof, "iterations": rep.iterations, "ms": round(rep.ms, 3), "redundant": [r["id"] for r in rep.redundant if r["id"] < S.IMPLICIT_BASE]}


def sketch_of(d, handle) -> str:
    for s in S.sketches(d):
        if handle in s["entities"]:
            return s["name"]
    return ""


def settle_sketch(d, handles, sketch):
    names = {sketch_of(d, h) for h in handles}
    if sketch:
        if S.get_sketch(d, sketch) is None:
            raise S.ParamError("There is no sketch named %s." % sketch)
        if any(sketch_of(d, h) != sketch for h in handles):
            raise S.ParamError("Every object must belong to sketch %s." % sketch)
        return sketch
    names.discard("")
    if len(names) > 1:
        raise S.ParamError("The objects belong to different sketches.")
    if names:
        only = next(iter(names))
        if any(sketch_of(d, h) != only for h in handles):
            raise S.ParamError("Some objects are outside sketch %s." % only)
        return only
    return ""


def norm_refs(raw) -> list:
    out = []
    for r in raw:
        if isinstance(r, (int, float)):
            out.append([int(r), "whole"])
        elif isinstance(r, str):
            h, _, part = r.partition(":")
            out.append([int(h, 0), part or "whole"])
        else:
            out.append([int(r[0]), str(r[1]) if len(r) > 1 and r[1] else "whole"])
    return out


def check_label(d, label: str, ignore: str = "") -> None:
    bad = X.valid_name(label)
    if bad:
        raise S.ParamError(bad)
    if S.name_taken(d, label, ignore):
        raise S.ParamError("The name %s is already in use." % label)


def attempt(d, net, rec, value, force=False):
    sk = net.sk
    refs = net.refs(rec["refs"])
    try:
        sk.restore(rec["id"], rec["kind"], refs, value, rec.get("label") or None, dict(rec.get("ctx") or {}))
    except SolverFault as err:
        raise S.ParamError(str(err))
    before = list(sk._x)
    net.recs[rec["id"]] = rec
    rep = sk.solve()
    ours = any(r["id"] == rec["id"] for r in rep.redundant)
    if (not rep.ok) or (ours and not force):
        info = explain.explain(d, net, rep, rec["id"], before)
        sk._x = before
        raise Refused("Refused: " + info["message"] + " The drawing was not changed.", info)
    return rep


def commit_net(d, net, extra_driven=True) -> list:
    changed = net.write_back()
    touch(d, net.bind.keys())
    if extra_driven:
        refresh_driven(d, net)
    return changed


def refresh_driven(d, net) -> None:
    for cid, val in net.driven_values().items():
        rec = S.get_con(d, cid)
        if rec is not None and abs(float(rec.get("value") or 0.0) - val) > 1e-9:
            rec = copy.deepcopy(rec)
            rec["value"] = val
            S.put_con(d, rec)


def add_constraint(d, kind, raw_refs, expr=None, value=None, driving=True, label=None, sketch=None, force=False, hold=()) -> dict:
    if kind not in S.GEOMETRIC_WORDS and kind not in S.DIM_KINDS:
        raise S.ParamError("Unknown constraint type '%s'." % kind)
    refs = norm_refs(raw_refs)
    if not refs:
        raise S.ParamError("A constraint needs at least one object.")
    handles = sorted({h for h, _ in refs})
    scope_name = settle_sketch(d, handles, sketch)
    net = adapt.load(d, seeds=handles, sketch=scope_name or None)
    for h in handles:
        net.binding(h)
    resolved = net.refs(refs)
    cid = S.next_id(d)
    rec = {"id": cid, "kind": kind, "refs": refs, "sketch": scope_name, "label": "", "expr": "", "value": None, "driving": True, "ctx": {}}
    dim = kind in S.DIM_KINDS
    solver_value = None
    if dim:
        label = label or S.next_label(d, kind)
        check_label(d, label)
        rec["label"] = label
        rec["driving"] = bool(driving)
        try:
            measured = net.sk.measure(kind, resolved)
        except SolverFault as err:
            raise S.ParamError(str(err))
        if expr is not None and str(expr).strip():
            rec["expr"] = str(expr).strip()
            bad = X.check(rec["expr"])
            if bad:
                raise S.ParamError(bad)
            scope = S.Scope(d)
            scope.dims[label.casefold()] = rec
            try:
                solver_value = scope.lookup(label)
            except X.ExprError as err:
                raise S.ParamError(str(err))
        elif value is not None:
            solver_value = float(value)
            rec["expr"] = U.format_value(solver_value)
        else:
            solver_value = float(U.format_value(measured))
            rec["expr"] = U.format_value(measured)
        if not driving:
            rec["expr"] = ""
            rec["value"] = measured
            rec["ctx"] = {}
            S.put_con(d, rec)
            mark(d)
            touch(d, handles)
            return {"id": cid, "label": label, "value": measured, "driving": False, "status": "reference", "moved": []}
        rec["value"] = solver_value
    rep = attempt(d, net, rec, solver_value, force)
    rec["ctx"] = copy.deepcopy(net.sk.cons[cid].ctx)
    S.put_con(d, rec)
    moved = commit_net(d, net)
    mark(d)
    out = {"id": cid, "label": rec["label"], "kind": kind, "moved": moved, "report": summary(rep)}
    if dim:
        out["value"] = rec["value"]
        out["expr"] = rec["expr"]
    return out


def unused_check(d, ids) -> None:
    gone = set(ids)
    removing = [S.get_con(d, i) for i in gone]
    labels = {r["label"].casefold() for r in removing if r and r.get("label")}
    if not labels:
        return
    rest = [r for r in S.dim_records(d) if r["id"] not in gone]
    for r in removing:
        if r and r.get("label"):
            users = S.dependents(d, r["label"], dims=rest)
            if users:
                raise S.ParamError("%s is used by %s." % (r["label"], users[0]))


def remove_constraints(d, ids) -> dict:
    ids = sorted({int(i) for i in ids})
    recs = [S.get_con(d, i) for i in ids]
    missing = [i for i, r in zip(ids, recs) if r is None]
    if missing:
        raise S.ParamError("There is no constraint #%d." % missing[0])
    unused_check(d, ids)
    handles = set()
    for r in recs:
        handles.update(adapt.handles_of(r))
    try:
        reach = set(adapt.load(d, seeds=sorted(handles)).bind)
    except S.ParamError:
        reach = set()
    for r in recs:
        S.drop_con(d, r["id"])
    touch(d, handles | reach)
    mark(d)
    return {"removed": ids, "count": len(ids)}


def constraints_of(d, handles) -> list:
    hs = set(handles)
    return [r for r in S.constraints(d) if hs & set(adapt.handles_of(r))]


def reevaluate(d, scope) -> dict:
    values = {}
    for r in S.dim_records(d):
        if r.get("driving", True):
            try:
                values[r["id"]] = scope.lookup(r["label"])
            except X.ExprError as err:
                raise S.ParamError("%s: %s" % (r["label"], err))
    for p in S.user_params(d):
        try:
            scope.lookup(p["name"])
        except X.ExprError as err:
            raise S.ParamError("%s: %s" % (p["name"], err))
    return values


def apply_values(d, scope, values: dict, extra_records=()) -> list:
    changed = []
    for r in S.dim_records(d):
        if r.get("driving", True) and r["id"] in values and abs(values[r["id"]] - float(r.get("value") or 0.0)) > TOL:
            changed.append(r)
    if not changed:
        return []
    seeds = sorted({h for r in changed for h in adapt.handles_of(r)})
    net = adapt.load(d, seeds=seeds, scope=scope)
    rep = net.sk.solve(analyse=False)
    if not rep.ok:
        net = adapt.load(d, seeds=seeds, scope=S.Scope(d))
        stored = {r["id"]: float(r.get("value") or 0.0) for r in changed}
        sk = net.sk
        ok = True
        for step in range(1, STEPS + 1):
            t = step / STEPS
            for r in changed:
                v = stored[r["id"]] + (values[r["id"]] - stored[r["id"]]) * t
                try:
                    srep = sk.set_value(r["id"], v)
                except SolverFault:
                    ok = False
                    break
                if not srep.ok:
                    ok = False
                    break
            if not ok:
                break
        if not ok:
            net = adapt.load(d, seeds=seeds, scope=scope)
            before = list(net.sk._x)
            bad = net.sk.solve()
            info = explain.explain(d, net, bad, changed[0]["id"], before)
            raise Refused("Refused: the new values cannot all be met. " + info["message"] + " The drawing was not changed.", info)
    out = []
    for r in changed:
        nr = copy.deepcopy(r)
        nr["value"] = values[r["id"]]
        S.put_con(d, nr)
        out.append(r["label"])
    commit_net(d, net)
    return out


def set_parameter(d, name, expr, unit=None, comment=None) -> dict:
    expr = str(expr).strip()
    bad = X.valid_name(name)
    if bad:
        raise S.ParamError(bad)
    if any(r["label"].casefold() == name.casefold() for r in S.dim_records(d)):
        return set_dimension(d, name, expr)
    bad = X.check(expr or "0")
    if bad:
        raise S.ParamError(bad)
    old = next((p for p in S.user_params(d) if p["name"].casefold() == name.casefold()), None)
    rec = {"name": old["name"] if old else name, "expr": expr or "0", "unit": (unit if unit is not None else (old or {}).get("unit", "")) or "", "comment": (comment if comment is not None else (old or {}).get("comment", "")) or ""}
    if rec["unit"] and not U.is_unit(rec["unit"]):
        raise S.ParamError("Unknown unit '%s'." % rec["unit"])
    params = [p for p in S.user_params(d) if p["name"].casefold() != name.casefold()] + [rec]
    scope = S.Scope(d, params=params)
    values = reevaluate(d, scope)
    moved = apply_values(d, scope, values)
    S.put_param(d, rec)
    mark(d)
    return {"name": rec["name"], "value": scope.lookup(rec["name"]), "created": old is None, "changed": moved}


def set_dimension(d, label, expr) -> dict:
    rec = next((r for r in S.dim_records(d) if r["label"].casefold() == label.casefold()), None)
    if rec is None:
        raise S.ParamError("There is no dimension named %s." % label)
    expr = str(expr).strip()
    if not rec.get("driving", True):
        raise S.ParamError("%s is a reference dimension; make it driving first." % rec["label"])
    bad = X.check(expr)
    if bad:
        raise S.ParamError(bad)
    nr = copy.deepcopy(rec)
    nr["expr"] = expr
    dims = [r for r in S.dim_records(d) if r["id"] != rec["id"]] + [nr]
    scope = S.Scope(d, dims=dims)
    values = reevaluate(d, scope)
    nr["value"] = float(rec.get("value") or 0.0)
    S.put_con(d, nr)
    moved = apply_values(d, S.Scope(d), values)
    mark(d)
    return {"name": rec["label"], "value": values[rec["id"]], "changed": moved}


def set_driving(d, label, driving: bool) -> dict:
    rec = next((r for r in S.dim_records(d) if r["label"].casefold() == label.casefold()), None)
    if rec is None:
        raise S.ParamError("There is no dimension named %s." % label)
    if bool(rec.get("driving", True)) == bool(driving):
        return {"name": rec["label"], "driving": bool(driving), "changed": False}
    handles = adapt.handles_of(rec)
    nr = copy.deepcopy(rec)
    if driving:
        nr["driving"] = True
        nr["expr"] = U.format_value(float(rec.get("value") or 0.0))
        net = adapt.load(d, seeds=handles, sketch=rec.get("sketch") or None)
        net.driven = [r for r in net.driven if r["id"] != rec["id"]]
        attempt(d, net, nr, float(rec.get("value") or 0.0))
        nr["ctx"] = copy.deepcopy(net.sk.cons[rec["id"]].ctx)
        S.put_con(d, nr)
        commit_net(d, net)
    else:
        dependents = S.dependents(d, rec["label"])
        if dependents:
            raise S.ParamError("%s is used by %s." % (rec["label"], dependents[0]))
        nr["driving"] = False
        nr["expr"] = ""
        S.put_con(d, nr)
        touch(d, handles)
    mark(d)
    return {"name": rec["label"], "driving": bool(driving), "changed": True}


def delete_parameter(d, name) -> dict:
    if any(r["label"].casefold() == name.casefold() for r in S.dim_records(d)):
        raise S.ParamError("%s belongs to a dimensional constraint; delete the constraint instead." % name)
    p = next((p for p in S.user_params(d) if p["name"].casefold() == name.casefold()), None)
    if p is None:
        raise S.ParamError("There is no parameter named %s." % name)
    users = S.dependents(d, p["name"])
    if users:
        raise S.ParamError("%s is used by %s." % (p["name"], users[0]))
    d.table_remove(S.PARAMS, p["name"])
    mark(d)
    return {"name": p["name"]}


def rename_parameter(d, old, new) -> dict:
    bad = X.valid_name(new)
    if bad:
        raise S.ParamError(bad)
    if S.name_taken(d, new, old):
        raise S.ParamError("The name %s is already in use." % new)
    prm = next((p for p in S.user_params(d) if p["name"].casefold() == old.casefold()), None)
    dim = next((r for r in S.dim_records(d) if r["label"].casefold() == old.casefold()), None)
    if prm is None and dim is None:
        raise S.ParamError("There is no parameter named %s." % old)
    for p in S.user_params(d):
        text = X.rename(p.get("expr") or "", old, new)
        if text != p.get("expr"):
            q = dict(p)
            q["expr"] = text
            S.put_param(d, q)
    handles = set()
    for r in S.dim_records(d):
        text = X.rename(r.get("expr") or "", old, new) if r.get("driving", True) else ""
        label = new if dim is not None and r["id"] == dim["id"] else r["label"]
        if text != (r.get("expr") or "") or label != r["label"]:
            q = copy.deepcopy(r)
            q["expr"] = text
            q["label"] = label
            S.put_con(d, q)
            handles.update(adapt.handles_of(r))
    if prm is not None:
        d.table_remove(S.PARAMS, prm["name"])
        q = dict(prm)
        q["name"] = new
        S.put_param(d, q)
    touch(d, handles)
    mark(d)
    return {"old": old, "new": new}


def listing(d) -> dict:
    scope = S.Scope(d)
    rows = []
    for r in S.dim_records(d):
        row = {"name": r["label"], "expr": r.get("expr") or "", "type": r["kind"], "group": "dimensional", "driving": bool(r.get("driving", True)), "constraint": r["id"], "sketch": r.get("sketch", ""), "unit": "deg" if r["kind"] == "angle" else ""}
        try:
            row["value"] = scope.lookup(r["label"])
            row["error"] = ""
        except X.ExprError as err:
            row["value"] = None
            row["error"] = str(err)
        row["shown"] = "error" if row["value"] is None else "%.4f" % row["value"]
        rows.append(row)
    for p in S.user_params(d):
        row = {"name": p["name"], "expr": p.get("expr") or "", "type": "User", "group": "user", "unit": p.get("unit") or "", "comment": p.get("comment") or "", "driving": True, "constraint": None, "sketch": ""}
        try:
            row["value"] = scope.lookup(p["name"])
            row["error"] = ""
        except X.ExprError as err:
            row["value"] = None
            row["error"] = str(err)
        row["shown"] = "error" if row["value"] is None else "%.4f" % U.from_base(d, row["value"], row["unit"])
        rows.append(row)
    return {"parameters": rows, "dimensional": [r for r in rows if r["group"] == "dimensional"], "user": [r for r in rows if r["group"] == "user"]}


def status(d, sketch=None, handles=None) -> dict:
    sk_rec = S.get_sketch(d, sketch) if sketch else None
    if sketch and sk_rec is None:
        raise S.ParamError("There is no sketch named %s." % sketch)
    if sketch:
        net = adapt.load(d, sketch=sketch)
    elif handles:
        net = adapt.load(d, seeds=list(handles))
    else:
        net = adapt.load(d, everything=True)
    rep = net.sk.solve(analyse=True)
    stat = net.entity_status(rep)
    ents = {}
    mine = set(S.members(d, sk_rec)) if sk_rec else set()
    for h, v in stat.items():
        st = v["status"]
        if st == "unconstrained":
            st = "under" if h in mine else "none"
        ents[h] = {"status": st, "dof": v["dof"]}
    for h in (S.members(d, sk_rec) if sk_rec else []):
        ents.setdefault(h, {"status": "under", "dof": 0})
    dangling = [r["id"] for r in S.constraints(d) if r.get("dangling") and (not sketch or r.get("sketch") == sketch)]
    over = bool(rep.redundant) or not rep.ok
    if over:
        overall = "over"
    elif sk_rec is not None and ents and rep.dof == 0:
        overall = "fully"
    elif sk_rec is None and rep.dof == 0 and rep.status == "fully":
        overall = "fully"
    elif ents:
        overall = "under"
    else:
        overall = "none"
    red = []
    for r in rep.redundant:
        if r["id"] >= S.IMPLICIT_BASE:
            continue
        red.append(explain.item(d, net, r["id"]))
        red[-1]["duplicates"] = [explain.item(d, net, x["id"]) for x in r["duplicates"] if x["id"] < S.IMPLICIT_BASE]
    return {"status": overall, "dof": rep.dof, "entities": {str(h): v for h, v in ents.items()}, "redundant": red, "conflicts": [explain.item(d, net, c["id"]) for c in rep.conflicts], "dangling": dangling, "constraints": len(net.recs), "ms": round(rep.ms, 3), "sketch": sketch or ""}
