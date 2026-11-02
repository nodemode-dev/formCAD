import math

import numpy as np

from app.nurbs3d.form import FormError, NurbsForm, arc_derivs

LEVELS = {"G0": 0, "G1": 1, "G2": 2, "G3": 3}
MIN_CHORD = 1e-9


def level_of(value) -> int:
    if isinstance(value, int) and 0 <= value <= 3:
        return value
    key = str(value).upper().strip()
    if key in LEVELS:
        return LEVELS[key]
    if key.isdigit() and 0 <= int(key) <= 3:
        return int(key)
    raise FormError("Continuity is G0, G1, G2 or G3.")


def hermite_controls(p_start, p_end, start_d, end_d):
    ca, cb = len(start_d), len(end_d)
    d = ca + cb + 1
    ctrl = [None] * (d + 1)
    ctrl[0] = np.array(p_start, dtype=float)
    ctrl[d] = np.array(p_end, dtype=float)

    def fall(k):
        out = 1.0
        for i in range(k):
            out *= d - i
        return out

    if ca >= 1:
        ctrl[1] = ctrl[0] + start_d[0] / fall(1)
    if ca >= 2:
        ctrl[2] = 2 * ctrl[1] - ctrl[0] + start_d[1] / fall(2)
    if ca >= 3:
        ctrl[3] = 3 * ctrl[2] - 3 * ctrl[1] + ctrl[0] + start_d[2] / fall(3)
    if cb >= 1:
        ctrl[d - 1] = ctrl[d] - end_d[0] / fall(1)
    if cb >= 2:
        ctrl[d - 2] = 2 * ctrl[d - 1] - ctrl[d] + end_d[1] / fall(2)
    if cb >= 3:
        ctrl[d - 3] = ctrl[d] - 3 * ctrl[d - 1] + 3 * ctrl[d - 2] - end_d[2] / fall(3)
    return ctrl


def blend(a: NurbsForm, end_a: str, b: NurbsForm, end_b: str, cont_a=2, cont_b=2, factor_a=1.0, factor_b=1.0) -> NurbsForm:
    ca, cb = level_of(cont_a), level_of(cont_b)
    if a.periodic or b.periodic:
        raise FormError("A periodic curve has no end to blend; make it non-periodic first.")
    if end_a not in ("start", "end") or end_b not in ("start", "end"):
        raise FormError("An end is start or end.")
    fa, fb = float(factor_a), float(factor_b)
    if not (math.isfinite(fa) and math.isfinite(fb)) or fa <= 0 or fb <= 0:
        raise FormError("A shape factor must be a positive number.")
    da = arc_derivs(a, end_a, "toward")
    db = arc_derivs(b, end_b, "away")
    chord = float(np.linalg.norm(db["point"] - da["point"]))
    if chord < MIN_CHORD:
        raise FormError("The two ends coincide; there is nothing to blend.")
    sa, sb = fa * chord, fb * chord
    start_d, end_d = [], []
    for k, key in enumerate(("t", "r2", "r3"), start=1):
        if k <= ca:
            start_d.append(sa**k * da[key])
        if k <= cb:
            end_d.append(sb**k * db[key])
    ctrl = hermite_controls(da["point"], db["point"], start_d, end_d)
    d = len(ctrl) - 1
    return NurbsForm(d, [[float(v) for v in q] for q in ctrl], [], [0.0, 1.0], [d + 1, d + 1], False)
