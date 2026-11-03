import math

import numpy as np

from app.meshes import core, spatial
from app.meshes.core import Mesh, MeshError
from app.meshes.jobs import QUIET

MODES = ("proportion", "count", "tolerance")
MIN_TRIANGLES = 4


def simplify_to(m: Mesh, count: int, lock_boundary: bool) -> Mesh:
    import fast_simplification as fs

    count = max(MIN_TRIANGLES, min(int(count), len(m.t)))
    if count >= len(m.t):
        return m
    v, t = np.array(m.v, dtype=np.float64), np.array(m.t, dtype=np.int32)
    before = core.edge_classes(m)
    vol0 = core.signed_volume(m)
    best, best_err = None, None
    for agg in (7.0, 9.0, 5.0):
        pts, faces = fs.simplify(v, t, target_count=count, agg=agg, preserve_border=bool(lock_boundary))
        out = Mesh(pts, np.asarray(faces, dtype=np.int64).reshape(-1, 3))
        keep = core.areas(out) > 0
        if not keep.all():
            out = core.compact(Mesh(out.v, out.t[keep]))
        if len(out.t) > 1.05 * count + 4:
            continue
        after = core.edge_classes(out)
        if len(after["naked"]) > len(before["naked"]) or after["nonmanifold"] > before["nonmanifold"]:
            continue
        err = 0.0
        if not len(before["naked"]) and abs(vol0) > 0:
            err = abs(core.signed_volume(out) - vol0) / abs(vol0)
        if err <= 0.02:
            return out
        if best is None or err < best_err:
            best, best_err = out, err
    if best is None:
        raise MeshError("The mesh could not be reduced to %d triangles without opening it." % count)
    return best


def reduce(m: Mesh, mode: str, value: float, lock_boundary: bool = True, act=QUIET) -> tuple:
    n = len(m.t)
    if mode not in MODES:
        raise MeshError("The reduce mode is proportion, count or tolerance.")
    if n < 2 * MIN_TRIANGLES:
        raise MeshError("The mesh has too few triangles to reduce.")
    value = float(value)
    if mode == "proportion":
        if not 0.0 < value < 1.0:
            raise MeshError("The proportion kept must be above 0 and below 1.")
        act.step("Reducing the mesh", 0.2)
        out = simplify_to(m, round(n * value), lock_boundary)
        tol_found = None
    elif mode == "count":
        if not (value >= MIN_TRIANGLES and math.isfinite(value)):
            raise MeshError("The target triangle count must be at least %d." % MIN_TRIANGLES)
        if value >= n:
            raise MeshError("The target count must be below the current %d triangles." % n)
        act.step("Reducing the mesh", 0.2)
        out = simplify_to(m, int(value), lock_boundary)
        tol_found = None
    else:
        if not (value > 0 and math.isfinite(value)):
            raise MeshError("The tolerance must be positive.")
        lo, hi = MIN_TRIANGLES, n
        best = m
        best_dev = {"max": 0.0, "rms": 0.0}
        for k in range(11):
            act.step("Searching the reduction within the tolerance", 0.1 + 0.08 * k)
            mid = int(math.exp((math.log(lo) + math.log(hi)) / 2))
            if mid >= hi or mid <= lo:
                break
            try:
                trial = simplify_to(m, mid, lock_boundary)
            except MeshError:
                lo = mid
                continue
            dev = spatial.deviation(m, trial, 40_000, act.check)
            if dev["max"] <= value:
                best, best_dev = trial, dev
                hi = mid
            else:
                lo = mid
            if hi - lo <= max(2, 0.01 * hi):
                break
        out = best
        tol_found = best_dev
    act.step("Measuring the deviation", 0.92)
    dev = spatial.deviation(m, out, 150_000, act.check)
    act.check()
    if tol_found is not None and out is m:
        dev = {"max": 0.0, "rms": 0.0}
    info = {"before": n, "after": int(len(out.t)), "deviation_max": dev["max"], "deviation_rms": dev["rms"], "mode": mode, "lock_boundary": bool(lock_boundary)}
    return out, info
