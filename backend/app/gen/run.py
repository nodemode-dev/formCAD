import copy
import io
import json
import math
import time

import numpy as np

from app.gen import filters as _filters, rules, thumb
from app.sim import records
from app.topo import outcome as topo_outcome, outer, simp, study as topo_study, surface, verify
from app.topo.grid import DESIGN, SOLID, VOID, Cancelled, TopoError

CAPS = {"runs": (24, 8), "passes": (6, 3), "seconds": (3600, 600)}
DEFAULTS = {
    "objective": "min_mass",
    "safety_factor": 2.0,
    "volume_fractions": [0.3, 0.45],
    "min_member_cells": 2.5,
    "passes": 4,
    "iterations": 60,
    "methods": [
        {"method": "additive", "direction": "+z"},
        {"method": "milling3", "directions": ["+y", "-y"]},
        {"method": "cutting", "axis": "y"},
        {"method": "casting", "direction": "+z"},
    ],
}
OBJECTIVES = ("min_mass", "min_compliance")
KEYS = tuple(DEFAULTS) + ("keep_distinct", "stress_limit_mpa")


def cap(restrict: bool, key: str):
    window, locked = CAPS[key]
    return locked if restrict else window


def snapshot(doc, study_id: str) -> dict:
    d = doc.drawing
    row = records.need(d, study_id, "study")
    if row.get("type") != "generative":
        raise TopoError("Study %s is a %s study, not a generative study." % (study_id, row.get("type")))
    body = d.ents.get(row["geometry"]["body"])
    if body is None or body.kind != "solidbody":
        raise TopoError("The solid body of study %s no longer exists." % study_id)
    snap = {"study": row, "loads": [records.need(d, i, "load") for i in row.get("loads") or []], "fixtures": [records.need(d, i, "fixture") for i in row.get("fixtures") or []], "material": records.get(d, row["material"], "material") if row.get("material") else None}
    snap["mesh"] = topo_study.tessellation(d, body)
    snap["regions"] = {}
    opts = row.get("options") or {}
    for key in ("preserve", "obstacles"):
        for reg in opts.get(key) or []:
            if isinstance(reg, dict) and "body" in reg and reg["body"] not in snap["regions"]:
                ent = d.ents.get(int(reg["body"]))
                if ent is None or ent.kind != "solidbody":
                    raise TopoError("The %s region names body %s, which is not a solid body." % (key[:-1], reg["body"]))
                snap["regions"][reg["body"]] = topo_study.tessellation(d, ent)
    return snap


def options_of(row: dict, overrides: dict = None) -> dict:
    raw = dict((row.get("options") or {}).get("generative") or {})
    over = dict(overrides or {})
    raw.update(over.pop("generative", None) or {})
    for k in KEYS:
        if k in over:
            raw[k] = over[k]
    out = copy.deepcopy(DEFAULTS)
    out.update({k: copy.deepcopy(v) for k, v in raw.items() if k in KEYS})
    if out["objective"] not in OBJECTIVES:
        raise TopoError("The objective is min_mass or min_compliance.")
    if not isinstance(out["methods"], list) or not out["methods"]:
        raise TopoError("Name at least one manufacturing method.")
    for ms in out["methods"]:
        if not isinstance(ms, dict) or ms.get("method") not in rules.METHODS:
            raise TopoError("A method is one of %s." % ", ".join(rules.METHODS))
    try:
        out["volume_fractions"] = [float(v) for v in out["volume_fractions"]]
        out["safety_factor"] = float(out["safety_factor"])
        out["min_member_cells"] = float(out["min_member_cells"])
        out["passes"] = int(out["passes"])
        out["iterations"] = int(out["iterations"])
    except (TypeError, ValueError):
        raise TopoError("The volume fractions, safety factor, member size, passes and iterations must be numbers.")
    if any(not (0.05 <= v <= 0.95) for v in out["volume_fractions"]) or not out["volume_fractions"]:
        raise TopoError("Each volume fraction is between 0.05 and 0.95.")
    if out["safety_factor"] < 1.0:
        raise TopoError("The safety factor is at least 1.")
    if out["min_member_cells"] < 2.0:
        raise TopoError("The smallest member must span at least 2 cells; a thinner member is lost between grid cells. Raise it, or use a finer grid.")
    return out


def guess(lo, hi, limit):
    return outer.guess(lo, hi, limit)


def mesh_of(grid, solid, sigma=0.6):
    arrays = {"solid": np.asarray(solid, dtype=np.uint8).reshape(grid.shape())}
    v, t, level = topo_outcome.extract(grid, arrays, 8, sigma)
    return v, t, abs(surface.volume(v, t))


def one(problem, bounds, spec, method, ms, vf, x0, progress, cancel, label):
    st = simp.Settings(spec)
    res = simp.optimise(problem, vf, st, bounds, progress, cancel, x0, label)
    level = verify.match_volume(problem, res.xphys, vf)
    solid = verify.threshold(problem, res.xphys, level)
    solid = rules.repair(problem.grid, problem.cls, solid, method, ms, res.xphys, level)
    chk = verify.try_design(problem, solid, st.direct_dofs)
    return res, level, chk


def run_method(problem, bounds, base_spec, ms, opts, limit, baseline, progress, cancel, tick):
    method = ms["method"]
    spec = dict(base_spec)
    spec.update(rules.spec_filters(method, ms))
    spec["iterations"] = min(int(opts["iterations"]), int(spec.get("iterations", 100)))
    spec["radius_cells"] = min(8.0, max(1.5, opts["min_member_cells"]))
    spec.pop("reduction", None)
    passes = []
    found = []
    if opts["objective"] == "min_compliance":
        targets = list(opts["volume_fractions"])
        x0 = None
        for n, vf in enumerate(targets):
            label = "%s at %.0f percent material" % (rules.LABELS[method], vf * 100)
            res, level, chk = one(problem, bounds, spec, method, ms, vf, x0, lambda l, f, i: progress(label, (n + f) / len(targets), i), cancel, label)
            tick()
            passes.append({"volume_fraction": vf, "result_fraction": chk.volume_fraction, "peak_stress_mpa": chk.peak if math.isfinite(chk.peak) else None, "failure": chk.failure, "iterations": res.iterations})
            found.append((res, level, chk, vf))
        return found, passes
    lo = None
    hi = None
    x0 = None
    vf = min(0.9, max(0.15, 0.45 * baseline.peak / max(limit, 1e-9) + 0.1))
    best = None
    least = None
    for n in range(int(opts["passes"])):
        label = "%s, pass %d at %.0f percent material" % (rules.LABELS[method], n + 1, vf * 100)
        pass_spec = spec if n == 0 else dict(spec, iterations=max(20, spec["iterations"] // 2))
        res, level, chk = one(problem, bounds, pass_spec, method, ms, vf, x0, lambda l, f, i, n=n: progress(label, (n + f) / opts["passes"], i), cancel, label)
        tick()
        ok = not chk.failure and chk.peak <= limit
        passes.append({"volume_fraction": vf, "result_fraction": chk.volume_fraction, "peak_stress_mpa": chk.peak if math.isfinite(chk.peak) else None, "failure": chk.failure, "iterations": res.iterations, "within_limit": ok})
        x0 = res.x
        actual = chk.volume_fraction
        if ok:
            if best is None or actual < best[2].volume_fraction:
                best = (res, level, chk, vf)
            hi = (actual, chk.peak)
        else:
            if not chk.failure and (least is None or chk.peak < least[2].peak):
                least = (res, level, chk, vf)
            lo = (actual, chk.peak if math.isfinite(chk.peak) else max(limit * 3.0, baseline.peak))
        if lo is not None and hi is not None and hi[0] - lo[0] < 0.03:
            break
        if lo is None:
            vf = max(0.1, vf * 0.72)
        elif hi is None:
            vf = min(0.95, max(vf * 1.3, lo[0] + 0.08))
        else:
            vf = guess(lo, hi, limit)
    pick = best or least
    if pick is None:
        raise TopoError("The %s study found no design that connects the loads to the supports. Allow more material or relax the method." % rules.LABELS[method])
    return [pick], passes


def distinct(items: list) -> list:
    kept = []
    for it in items:
        dup = False
        for k in kept:
            if k["method"] == it["method"] and abs(k["mass_kg"] - it["mass_kg"]) <= 0.1 * max(k["mass_kg"], 1e-12) and k["manufacturing"]["holes"] == it["manufacturing"]["holes"]:
                dup = True
                break
        if not dup:
            kept.append(it)
    return kept


def describe(grid, problem, mat_rho, yield_mpa, limit, method, ms, found, passes, opts, seconds):
    res, level, chk, vf = found
    solid = chk.solid
    v, t, vol = mesh_of(grid, solid)
    peak = chk.peak if math.isfinite(chk.peak) else None
    sf = (yield_mpa / peak) if peak and yield_mpa > 0 else None
    p99 = chk.p99 if math.isfinite(chk.p99) else None
    report = rules.manufacturing_report(grid, problem.cls, solid, method, ms, opts["min_member_cells"])
    return {
        "method": method,
        "label": rules.LABELS[method],
        "params": {k: v for k, v in ms.items() if k != "method"},
        "objective": opts["objective"],
        "target_fraction": vf,
        "volume_fraction": chk.volume_fraction,
        "mass_kg": vol * mat_rho,
        "voxel_mass_kg": chk.mass,
        "mesh_volume_mm3": vol,
        "mesh_triangles": int(len(t)),
        "safety_factor": sf,
        "safety_factor_p99": (yield_mpa / p99) if p99 and yield_mpa > 0 else None,
        "required_safety_factor": opts["safety_factor"] if opts["objective"] == "min_mass" else None,
        "meets_safety_factor": bool(sf is not None and sf >= opts["safety_factor"] - 1e-9),
        "peak_stress_mpa": peak,
        "p99_stress_mpa": p99,
        "max_displacement_mm": chk.max_disp,
        "compliance": chk.compliance,
        "manufacturing": report,
        "manufacturable": report["manufacturable"],
        "disconnected_cells_removed": chk.dropped,
        "passes": passes,
        "iterations": sum(p.get("iterations", 0) for p in passes),
        "seconds": seconds,
        "thumbnail_png_base64": thumb.render(solid.reshape(grid.shape())),
        "notes": ([] if report["member_size_ok"] else ["%.0f percent of the material sits in members thinner than the %g cell minimum; use a finer grid (more cells) for a trustworthy minimum member size." % (report["thin_share"] * 100, opts["min_member_cells"])]) + ([] if sf is None or sf >= opts["safety_factor"] - 1e-9 else ["The safety factor is below the required %g; allow more passes or material." % opts["safety_factor"]]),
    }


def compute(doc, study_id: str, overrides: dict, ctl, restrict: bool) -> dict:
    t0 = time.monotonic()
    ctl.step("Reading the study", 0.0)
    with doc.lock:
        snap = snapshot(doc, study_id)
    opts = options_of(snap["study"], overrides)
    runs = len(opts["methods"]) * (len(opts["volume_fractions"]) if opts["objective"] == "min_compliance" else 1)
    if runs > cap(restrict, "runs"):
        raise TopoError("The study matrix holds %d runs; the limit is %d%s. Name fewer methods or volume fractions." % (runs, cap(restrict, "runs"), " for a macro or an outside agent" if restrict else ""))
    opts["passes"] = max(1, min(opts["passes"], cap(restrict, "passes")))
    ctl.step("Building the design grid", 0.01)
    topo_over = {k: v for k, v in (overrides or {}).items() if k in topo_study.OPTION_KEYS}
    setup = topo_study.resolve(dict(snap, study=dict(snap["study"], options={k: v for k, v in (snap["study"].get("options") or {}).items() if k != "generative"})), restrict, topo_over)
    problem, grid = setup.problem, setup.grid
    mat = topo_study.material_mm(snap["material"])
    yield_mpa = mat["yield"]
    if yield_mpa <= 0:
        raise TopoError("The material needs a yield strength to report a safety factor.")
    limit = float(opts.get("stress_limit_mpa") or 0.0) or yield_mpa / opts["safety_factor"]
    if opts.get("stress_limit_mpa"):
        opts["safety_factor"] = yield_mpa / limit
    deadline_runs = [0]
    done_runs = [0]
    live = problem.cls != VOID
    ctl.step("Solving the full design", 0.02)
    st0 = simp.Settings(setup.spec)
    baseline = verify.solve_design(problem, live, st0.direct_dofs)
    if baseline.peak > limit and opts["objective"] == "min_mass":
        raise TopoError("The full design already exceeds the stress limit (%.3g MPa against %.3g MPa, safety factor %.3g). Loosen the safety factor or reduce the load." % (baseline.peak, limit, opts["safety_factor"]))

    def progress(label, frac, info):
        ctl.step(label, 0.03 + 0.95 * (done_runs[0] + min(1.0, frac)) / max(1, len(opts["methods"])), info)

    def tick():
        return None

    outs = []
    method_seconds = {}
    for ms in opts["methods"]:
        if ctl.cancelled():
            raise Cancelled(ctl.message or "The study was cancelled.")
        t1 = time.monotonic()
        try:
            found, passes = run_method(problem, setup.bounds, setup.spec, ms, opts, limit, baseline, progress, ctl.cancelled, tick)
        except Cancelled as err:
            raise Cancelled(ctl.message or str(err))
        sec = time.monotonic() - t1
        items = [describe(grid, problem, mat["rho"], yield_mpa, limit, ms["method"], ms, f, passes, opts, sec / len(found)) for f in found]
        for it, f in zip(items, found):
            it["_solid"] = f[2].solid
            it["_vm"] = f[2].vm
            it["_density"] = f[0].xphys
        outs.extend(items)
        done_runs[0] += 1
    if opts.get("keep_distinct", True):
        outs = distinct(outs)
    if not outs:
        raise TopoError("No outcome survived the checks.")
    for n, it in enumerate(outs):
        it["id"] = "O%d" % (n + 1)
    cls3 = problem.cls
    buf = io.BytesIO()
    arrays = {}
    for it in outs:
        i = it["id"]
        arrays[i + "_solid"] = np.asarray(it.pop("_solid"), dtype=np.uint8).reshape(grid.shape())
        arrays[i + "_vm"] = np.asarray(it.pop("_vm"), dtype=np.float32).reshape(grid.shape())
        arrays[i + "_density"] = np.asarray(it.pop("_density"), dtype=np.float32).reshape(grid.shape())
    summary = {
        "objective": opts["objective"],
        "options": opts,
        "stress_limit_mpa": limit,
        "required_safety_factor": opts["safety_factor"],
        "baseline": {"mass_kg": baseline.mass, "mass_cad_kg": setup.info["body_volume_mm3"] * mat["rho"], "peak_stress_mpa": baseline.peak, "safety_factor": yield_mpa / baseline.peak if baseline.peak > 0 else None, "compliance": baseline.compliance, "max_displacement_mm": baseline.max_disp},
        "yield_mpa": yield_mpa,
        "grid": grid.dims(),
        "cells_design": setup.info["cells_design"],
        "cells_preserved": setup.info["cells_preserved"],
        "material": setup.info["material"],
        "notes": list(setup.info["notes"]),
        "outcomes": outs,
        "seconds": time.monotonic() - t0,
        "safety_factor_basis": "Peak von Mises over the design cells of the thresholded outcome re-analysed on the design grid (hexahedra); the p99 value and the peak are both stored.",
    }
    clean = json.loads(json.dumps(summary, default=float))
    np.savez_compressed(buf, cls=np.asarray(cls3, dtype=np.uint8).reshape(grid.shape()), meta=np.array(json.dumps({"grid": grid.dims(), "summary": clean}, default=float)), **arrays)
    return {"study": study_id, "data": buf.getvalue(), "summary": clean}


def unpack(data: bytes):
    from app.sim import npz
    from app.topo.grid import Grid

    with np.load(npz.checked(data), allow_pickle=False) as z:
        arrays = {k: z[k] for k in z.files}
    meta = json.loads(str(arrays.pop("meta")))
    g = meta["grid"]
    return Grid(g["nx"], g["ny"], g["nz"], g["h"], g["origin"]), arrays, meta
