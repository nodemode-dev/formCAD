import numpy as np

from app.nurbs3d.blend import level_of
from app.nurbs3d.form import FormError, NurbsForm, arc_derivs

MAX_REFINE = 64


def refine_start(form: NurbsForm, need: int) -> int:
    added = 0
    while len(form.poles) < need and added < MAX_REFINE:
        mid = (form.knots[0] + form.knots[1]) / 2.0
        form.insert_knot(mid)
        added += 1
    return added


def match(moving: NurbsForm, which: str, target: NurbsForm, target_end: str, cont=1, scale=1.0, refine=True):
    order = level_of(cont)
    if moving.periodic or target.periodic:
        raise FormError("A periodic curve has no end to match; make it non-periodic first.")
    if which not in ("start", "end") or target_end not in ("start", "end"):
        raise FormError("An end is start or end.")
    if order > moving.degree:
        raise FormError("Matching to G%d needs a curve of degree %d or more; raise the degree first." % (order, order))
    scale = float(scale)
    if not scale > 0:
        raise FormError("The influence scale must be positive.")
    work = moving.reversed() if which == "end" else moving.copy()
    added = 0
    need = order + 3
    if len(work.poles) < need:
        if not refine:
            raise FormError("The curve has too few poles for G%d; allow refinement." % order)
        added = refine_start(work, need)
        if len(work.poles) < need:
            raise FormError("The curve could not be refined enough.")
    tgt = arc_derivs(target, target_end, "toward")
    own = arc_derivs(work, "start", "away")
    sigma = own["speed"] * scale
    t, r2, r3 = tgt["t"], tgt["r2"], tgt["r3"]
    d1 = sigma * t
    d2 = sigma**2 * r2 + own["s2"] * t
    d3 = sigma**3 * r3 + 3 * sigma * own["s2"] * r2 + own["s3"] * t
    work.poles[0] = [float(v) for v in tgt["point"]]
    wants = {1: d1, 2: d2, 3: d3}
    lo = work.knots[0]
    for k in range(1, order + 1):
        cur = work.derivs(lo, k)[k]
        probe = work.copy()
        probe.poles[k] = [probe.poles[k][0] + 1.0, probe.poles[k][1], probe.poles[k][2]]
        coef = float(probe.derivs(lo, k)[k][0] - cur[0])
        if abs(coef) < 1e-14:
            raise FormError("The curve end is degenerate; pole %d has no influence." % k)
        step = (wants[k] - cur) / coef
        work.poles[k] = [float(work.poles[k][i] + step[i]) for i in range(3)]
    out = work.reversed() if which == "end" else work
    return out, added
