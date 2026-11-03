import copy
import math
import time

import numpy as np

from app.topo import filters, simp, verify
from app.topo.grid import DESIGN, SOLID, Cancelled, TopoError
from app.topo.problem import Problem

MAX_OUTER = 8
RELIEF_SHARE = 0.95
RELIEF_BUDGET = 0.08


class Outcome:
    def __init__(self):
        self.attempts: list = []
        self.baseline = None
        self.final = None
        self.xphys = None
        self.level = 0.5
        self.solid = None
        self.met_target = False
        self.met_stress = False
        self.limit = 0.0
        self.target_reduction = 0.0
        self.reduction = 0.0
        self.seconds = 0.0
        self.notes: list = []
        self.history: list = []
        self.iterations = 0
        self.converged = False
        self.grey = 0.0

    def summary(self) -> dict:
        b, f = self.baseline, self.final
        return {
            "target_reduction": self.target_reduction,
            "reduction": self.reduction,
            "met_target": self.met_target,
            "met_stress": self.met_stress,
            "stress_limit_mpa": self.limit,
            "initial_mass_kg": b.mass,
            "final_mass_kg": f.mass,
            "initial_volume_fraction": b.volume_fraction,
            "final_volume_fraction": f.volume_fraction,
            "peak_stress_before_mpa": b.peak,
            "peak_stress_after_mpa": f.peak,
            "stress_ratio": f.peak / b.peak if b.peak > 0 else 0.0,
            "p99_stress_after_mpa": f.p99,
            "compliance_before": b.compliance,
            "compliance_after": f.compliance,
            "max_displacement_before_mm": b.max_disp,
            "max_displacement_after_mm": f.max_disp,
            "threshold": self.level,
            "grey_share": self.grey,
            "outer_attempts": [dict(a) for a in self.attempts],
            "iterations": self.iterations,
            "converged": self.converged,
            "disconnected_cells_removed": f.dropped,
            "seconds": self.seconds,
            "notes": list(self.notes),
        }


def guess(lo, hi, limit):
    (v0, s0), (v1, s1) = lo, hi
    if not math.isfinite(s0) or s0 <= limit or s1 >= limit or v1 <= v0:
        return 0.5 * (v0 + v1)
    a, b = math.log(s0), math.log(s1)
    frac = (a - math.log(limit * 0.97)) / (a - b) if a != b else 0.5
    frac = min(0.85, max(0.15, frac))
    return v0 + frac * (v1 - v0)


def relief_cells(problem: Problem, chk, limit: float, axes) -> np.ndarray:
    from scipy.ndimage import binary_dilation

    g = problem.grid
    design = problem.cls == DESIGN
    hot = (chk.vm > RELIEF_SHARE * limit) & chk.solid & design
    if not hot.any():
        return np.zeros(g.ne, dtype=bool)
    budget = max(1, int(RELIEF_BUDGET * float(chk.solid[design].sum())))
    if hot.sum() > budget:
        ids = np.flatnonzero(hot)
        keep = ids[np.argsort(-chk.vm[ids])[:budget]]
        hot = np.zeros(g.ne, dtype=bool)
        hot[keep] = True
    cross = np.zeros((3, 3, 3), dtype=bool)
    cross[1, 1, :] = cross[1, :, 1] = cross[:, 1, 1] = True
    grown = binary_dilation(hot.reshape(g.shape()), structure=cross).ravel() & design
    if axes:
        grown = (filters.orbit_matrix(g, axes) @ grown.astype(float)) > 0
    return grown


def run(problem: Problem, spec: dict, bounds, progress=None, cancel=None) -> Outcome:
    t0 = time.monotonic()
    out = Outcome()
    reduction = float(spec.get("reduction", 0.5))
    if not (0.02 <= reduction <= 0.95):
        raise TopoError("The mass reduction target must be between 2 and 95 percent.")
    out.target_reduction = reduction
    limit = float(spec.get("stress_limit_mpa") or 0.0)
    if limit <= 0 and problem.yield_mpa > 0:
        factor = float(spec.get("safety_factor") or 1.0)
        limit = problem.yield_mpa / max(1.0, factor)
    out.limit = limit
    st = simp.Settings(spec)
    max_outer = int(max(1, min(MAX_OUTER, spec.get("max_outer", 6))))
    live = problem.cls != 2
    if progress:
        progress("Solving the full design", 0.0, {})
    out.baseline = verify.solve_design(problem, live, st.direct_dofs)
    if limit > 0 and out.baseline.peak > limit:
        raise TopoError("The full design already exceeds the stress limit (%.3g MPa against %.3g MPa). Loosen the limit or reduce the load." % (out.baseline.peak, limit))
    vf_target = 1.0 - reduction
    vf = vf_target
    best = None
    lo = None
    hi = (1.0, out.baseline.peak)
    x0 = None
    total_it = 0
    relief_left = int(max(0, min(4, spec.get("relief_passes", 0))))
    hot = np.zeros(problem.grid.ne, dtype=bool)
    axes = filters.plane_axes(problem.grid, st.symmetry, bounds) if st.symmetry else []
    for k in range(max_outer):
        if cancel is not None and cancel():
            raise Cancelled("The optimisation was cancelled.")
        label = "Optimising at %.0f percent material (pass %d)" % (vf * 100.0, k + 1)

        def prog(lbl, frac, info, k=k, label=label):
            if progress:
                progress(label, (k + frac) / max_outer * 0.95 + 0.02, info)

        working = problem
        if hot.any():
            working = copy.copy(problem)
            working.cls = problem.cls.copy()
            working.cls[hot & (problem.cls == DESIGN)] = SOLID
        res = simp.optimise(working, vf, st, bounds, prog, cancel, x0, label)
        total_it += res.iterations
        level = verify.match_volume(working, res.xphys, vf)
        chk = verify.try_design(problem, verify.threshold(working, res.xphys, level), st.direct_dofs)
        entry = {"pass": k + 1, "volume_fraction": chk.volume_fraction, "target_fraction": vf, "peak_stress_mpa": chk.peak if math.isfinite(chk.peak) else None, "failure": chk.failure, "iterations": res.iterations, "converged": res.converged, "level": level, "seconds": res.seconds, "stress_relief_cells": int(hot.sum())}
        out.attempts.append(entry)
        out.history.extend(res.history)
        ok = not chk.failure and (limit <= 0 or chk.peak <= limit)
        entry["within_limit"] = ok
        if ok:
            if best is None or chk.volume_fraction < best[0].volume_fraction:
                best = (chk, res, level)
            hi = (vf, chk.peak)
            if lo is None or hi[0] - lo[0] < 0.02:
                break
        else:
            fresh = relief_cells(problem, chk, limit, axes) & ~hot if relief_left > 0 and (lo is None or lo[0] == vf) else None
            if fresh is not None and fresh.any() and float(((problem.cls == SOLID) | hot | fresh).sum()) < 0.85 * vf * float(live.sum()):
                hot |= fresh
                relief_left -= 1
                entry["action"] = "stress relief"
                x0 = res.x
                lo = (vf, chk.peak)
                continue
            lo = (vf, chk.peak)
        if lo is None or hi[0] - lo[0] < 0.02:
            break
        x0 = res.x
        vf = guess(lo, hi, limit)
        entry["action"] = "more material"
    if best is None:
        chk, res, level = out.baseline, None, 0.5
        cut = [a for a in out.attempts if a.get("failure")]
        out.notes.append("No reduced design stayed under the stress limit within %d passes; the full design is returned.%s" % (max_outer, (" %d pass%s lost the load path: %s" % (len(cut), "es" if len(cut) != 1 else "", cut[0]["failure"])) if cut else ""))
        out.final = out.baseline
        out.solid = live
        out.xphys = np.where(live, 1.0, 0.0)
        out.level = 0.5
    else:
        out.final, res, out.level = best
        out.solid = out.final.solid
        out.xphys = res.xphys
        out.converged = res.converged
        out.grey = simp.grey_share(problem, res.xphys)
    out.iterations = total_it
    out.reduction = 1.0 - out.final.volume_fraction / max(1e-12, out.baseline.volume_fraction)
    out.met_stress = limit <= 0 or out.final.peak <= limit
    out.met_target = out.reduction >= reduction - 0.005
    if not out.met_target:
        out.notes.append("The stress limit needed more material than the target allows: reduction %.1f percent against the %.1f percent asked." % (out.reduction * 100, reduction * 100))
    if progress:
        progress("Done", 1.0, {})
    out.seconds = time.monotonic() - t0
    return out
