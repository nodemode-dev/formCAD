import json
import math
import time

import numpy as np

from app.param import ops
from app.sim import records
from app.topo import study as topo_study, surface, verify
from app.topo.grid import Cancelled, TopoError

MAX_VARIABLES = 8
MAX_EVALUATIONS = (80, 20)
OBJECTIVES = ("mass", "stress", "compliance")
PENALTY = 25.0


def plain_number(text) -> float:
    try:
        v = float(str(text).strip())
    except (TypeError, ValueError):
        raise TopoError("The parameter value %r is a formula; only plain number parameters can be varied." % (text,))
    if not math.isfinite(v):
        raise TopoError("The parameter value %r is not finite." % (text,))
    return v


def variables_of(d, opts: dict) -> list:
    rows = {r["name"].casefold(): r for r in ops.listing(d)["parameters"]}
    raw = opts.get("variables") or []
    if not isinstance(raw, list) or not raw or len(raw) > MAX_VARIABLES:
        raise TopoError("A shape study names between 1 and %d parameters to vary." % MAX_VARIABLES)
    out = []
    for item in raw:
        name = str((item or {}).get("param") or (item or {}).get("name") or "")
        row = rows.get(name.casefold())
        if row is None:
            raise TopoError("The document has no parameter %s." % name)
        if not row.get("driving", True):
            raise TopoError("The parameter %s is a reference dimension and cannot be varied." % name)
        lo, hi = float(item["min"]), float(item["max"])
        if not hi > lo:
            raise TopoError("The range of %s is empty." % name)
        now = plain_number(row["expr"])
        out.append({"param": row["name"], "min": lo, "max": hi, "initial": now, "expr_unit": row.get("unit") or ""})
    if len({v["param"].casefold() for v in out}) != len(out):
        raise TopoError("A parameter is listed twice.")
    return out


def geometry_for(doc, study_row: dict, values: dict):
    d = doc.drawing
    from app.part import rebuild

    with doc.lock:
        doc.begin("TOPOSHAPE")
        try:
            for name, v in values.items():
                ops.set_parameter(d, name, "%.9g" % v)
            rebuild.rebuild(doc, force=True)
            body = d.ents.get(study_row["geometry"]["body"])
            if body is None or body.kind != "solidbody":
                raise TopoError("The study body is gone after changing the parameters.")
            return topo_study.tessellation(d, body)
        finally:
            doc.rollback()


def resync(doc) -> None:
    from app.part import rebuild

    with doc.lock:
        doc.begin("TOPOSHAPE")
        try:
            rebuild.rebuild(doc, force=True)
        finally:
            doc.rollback()


def analyse(snap: dict, mesh, restrict: bool, cells: int):
    local = dict(snap)
    local["mesh"] = mesh
    setup = topo_study.resolve(local, restrict, {"cells": cells, "reduction": 0.5})
    prob = setup.problem
    chk = verify.solve_design(prob, prob.cls != 2, setup.spec.get("direct_dofs", 14000))
    volume = abs(surface.volume(mesh[0], mesh[1]))
    return {"mass_kg": volume * prob.rho, "volume_mm3": volume, "peak_stress_mpa": chk.peak, "compliance": chk.compliance, "max_displacement_mm": chk.max_disp, "cells": setup.grid.ne}


def execute(doc, study_id: str, overrides: dict, ctl, restrict: bool) -> dict:
    ctl.step("Reading the study", 0.0)
    with doc.lock:
        d = doc.drawing
        row = records.need(d, study_id, "study")
        if row.get("type") != "shape":
            raise TopoError("Study %s is a %s study, not a shape study." % (study_id, row.get("type")))
        opts = dict(row.get("options") or {})
        opts.update({k: v for k, v in (overrides or {}).items() if k != "seconds"})
        variables = variables_of(d, opts)
        body = d.ents.get(row["geometry"]["body"])
        if body is None or body.kind != "solidbody":
            raise TopoError("The solid body of study %s no longer exists." % study_id)
        snap = {"study": row, "loads": [records.need(d, i, "load") for i in row.get("loads") or []], "fixtures": [records.need(d, i, "fixture") for i in row.get("fixtures") or []], "material": records.get(d, row["material"], "material") if row.get("material") else None, "regions": {}}
    objective = str(opts.get("objective") or "mass")
    if objective not in OBJECTIVES:
        raise TopoError("The objective is mass, stress or compliance.")
    budget = int(max(3, min(int(opts.get("evaluations", 40)), MAX_EVALUATIONS[1 if restrict else 0])))
    cells = int(min(max(int(opts.get("cells", 1500)), 200), topo_study.cap(restrict, "cells")))
    mat = topo_study.material_mm(snap["material"])
    limit = float(opts.get("stress_limit_mpa") or 0.0)
    if limit <= 0 and mat["yield"] > 0:
        limit = mat["yield"] / max(1.0, float(opts.get("safety_factor") or 1.5))
    names = [v["param"] for v in variables]
    lo = np.array([v["min"] for v in variables])
    hi = np.array([v["max"] for v in variables])
    x0 = np.array([min(max(v["initial"], v["min"]), v["max"]) for v in variables])
    history = []
    state = {"initial": None, "mass_cap": float(opts.get("mass_limit_kg") or 0.0)}

    def evaluate(vals: np.ndarray) -> float:
        if ctl.cancelled():
            raise Cancelled("The shape study was cancelled.")
        values = {n: float(v) for n, v in zip(names, vals)}
        mesh = geometry_for(doc, row, values)
        res = analyse(snap, mesh, restrict, cells)
        if state["initial"] is None:
            state["initial"] = res
            if state["mass_cap"] <= 0:
                state["mass_cap"] = res["mass_kg"]
        res.update({"values": values})
        over_stress = limit > 0 and res["peak_stress_mpa"] > limit
        over_mass = objective != "mass" and res["mass_kg"] > state["mass_cap"] * 1.0001
        if objective == "mass":
            score = res["mass_kg"] / state["initial"]["mass_kg"]
            if over_stress:
                score += PENALTY * (res["peak_stress_mpa"] / limit - 1.0)
        elif objective == "stress":
            score = res["peak_stress_mpa"] / state["initial"]["peak_stress_mpa"]
        else:
            score = res["compliance"] / state["initial"]["compliance"]
            if over_stress:
                score += PENALTY * (res["peak_stress_mpa"] / limit - 1.0)
        if over_mass:
            score += PENALTY * (res["mass_kg"] / state["mass_cap"] - 1.0)
        res["objective"] = score
        res["feasible"] = not over_stress and not over_mass
        history.append(res)
        ctl.step("Trying candidate %d of %d" % (len(history), budget), min(0.95, len(history) / float(budget)), {"candidate": len(history), "mass_kg": res["mass_kg"], "peak_stress_mpa": res["peak_stress_mpa"], "objective": score})
        return score

    from scipy.optimize import minimize

    span = np.where(hi > lo, hi - lo, 1.0)

    def scaled(u):
        return evaluate(lo + np.clip(u, 0.0, 1.0) * span)

    start = (x0 - lo) / span
    evaluate(x0)
    if len(history) < budget:
        try:
            minimize(scaled, start, method="Nelder-Mead", bounds=[(0.0, 1.0)] * len(names), options={"maxfev": budget - 1, "xatol": 2e-3, "fatol": 1e-4, "initial_simplex": simplex(start)})
        except Cancelled:
            raise
    resync(doc)
    feasible = [h for h in history if h["feasible"]]
    pool = feasible or history
    best = min(pool, key=lambda h: h["objective"])
    first = history[0]
    clean = {
        "objective": objective,
        "stress_limit_mpa": limit,
        "evaluations": len(history),
        "met_limit": bool(best["feasible"]),
        "variables": [{"param": v["param"], "min": v["min"], "max": v["max"], "initial": v["initial"], "best": best["values"][v["param"]]} for v in variables],
        "initial": {k: first[k] for k in ("mass_kg", "peak_stress_mpa", "compliance", "max_displacement_mm")},
        "best": {k: best[k] for k in ("mass_kg", "peak_stress_mpa", "compliance", "max_displacement_mm")},
        "history": [{"values": h["values"], "mass_kg": h["mass_kg"], "peak_stress_mpa": h["peak_stress_mpa"], "compliance": h["compliance"], "objective": h["objective"], "feasible": h["feasible"]} for h in history],
        "analysis_cells": best["cells"],
        "notes": ["Mass is the exact volume of the rebuilt body; stress and compliance come from a voxel analysis, so they carry a cell-size error (see the topology notes)."],
        "created": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
    }
    clean = json.loads(json.dumps(clean, default=float))
    ctl.step("Storing the result", 0.98)
    with doc.lock:
        with doc.transaction("TOPOSHAPE"):
            d = doc.drawing
            for old in records.of_kind(d, "result"):
                if old.get("study") == study_id:
                    d.table_remove(records.TABLE, old["id"])
            res = records.put_result(d, {"study": study_id, "type": "shape", "blob": None, "summary": clean, "fields": [], "modes": [], "created": clean["created"]})
            srow = records.get(d, study_id)
            srow["result"] = res["id"]
            srow["status"] = "solved"
            d.table_set(records.TABLE, srow)
    return {"study": study_id, "result": res["id"], "summary": clean}


def simplex(start: np.ndarray) -> np.ndarray:
    n = len(start)
    pts = [start.copy()]
    for k in range(n):
        p = start.copy()
        p[k] = p[k] + 0.15 if p[k] + 0.15 <= 1.0 else p[k] - 0.15
        pts.append(np.clip(p, 0.0, 1.0))
    return np.array(pts)


def apply_best(ctx, study_id: str, values: dict = None) -> dict:
    row = records.need(ctx.d, study_id, "study")
    if row.get("type") != "shape":
        raise TopoError("Study %s is not a shape study." % study_id)
    if values is None:
        rid = row.get("result")
        if not rid:
            raise TopoError("Study %s has no result yet; run the shape search first." % study_id)
        res = records.need(ctx.d, rid, "result")
        values = {v["param"]: v["best"] for v in res["summary"]["variables"]}
    done = {}
    for name, v in values.items():
        out = ops.set_parameter(ctx.d, name, "%.9g" % float(v))
        done[name] = out.get("value")
    return {"study": study_id, "values": {k: float(v) for k, v in values.items()}, "applied": done}
