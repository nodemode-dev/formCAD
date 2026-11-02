import math

import numpy as np

from app.nurbs3d.form import FormError, NurbsForm, arc_derivs

DEFAULT_CURVATURE_TOL = 1e-3


def own_measure(a: NurbsForm, end_a: str, b: NurbsForm, end_b: str) -> dict:
    da = arc_derivs(a, end_a, "toward")
    db = arc_derivs(b, end_b, "away")
    pos = float(np.linalg.norm(da["point"] - db["point"]))
    ang = math.atan2(float(np.linalg.norm(np.cross(da["t"], db["t"]))), float(da["t"] @ db["t"]))
    ka, kb = da["curvature"], db["curvature"]
    vec = float(np.linalg.norm(da["r2"] - db["r2"]))
    third = float(np.linalg.norm(da["r3"] - db["r3"]))
    scale3 = max(float(np.linalg.norm(da["r3"])), float(np.linalg.norm(db["r3"])), max(ka, kb) ** 2, 1e-12)
    scale2 = max(ka, kb, 1e-12)
    return {
        "position_gap": pos,
        "tangent_angle": ang,
        "curvature_a": ka,
        "curvature_b": kb,
        "curvature_gap": abs(ka - kb),
        "curvature_vector_gap": vec,
        "curvature_relative": vec / scale2 if max(ka, kb) > 1e-12 else 0.0,
        "third_gap": third,
        "third_relative": third / scale3,
        "param_a": da["u"],
        "param_b": db["u"],
    }


def decide(own: dict, worker: dict | None, tol: float, angle_tol: float, curv_tol: float) -> dict:
    out = dict(own)
    out["tolerances"] = {"position": tol, "angle": angle_tol, "curvature_relative": curv_tol}
    g0 = own["position_gap"] <= tol
    g1_angle = own["tangent_angle"] <= angle_tol
    g2_own = own["curvature_vector_gap"] <= curv_tol * max(own["curvature_a"], own["curvature_b"], 1e-12) or own["curvature_vector_gap"] <= 1e-12
    if worker and worker.get("is_done"):
        out["source"] = "occt"
        out["g0"] = bool(worker.get("g0")) and g0
        out["g1"] = bool(worker.get("g1")) and g1_angle and out["g0"]
        out["g2"] = bool(worker.get("g2")) and g2_own and out["g1"]
        out["occt"] = {k: worker.get(k) for k in ("position_gap", "tangent_angle", "normal_angle", "curvature_variation", "curvature_a", "curvature_b")}
    else:
        out["source"] = "formcad"
        out["g0"] = g0
        out["g1"] = g0 and g1_angle
        out["g2"] = out["g1"] and g2_own
        if worker and not worker.get("is_done"):
            out["occt_status"] = worker.get("status_error")
    out["g3"] = bool(out["g2"] and own["third_relative"] <= curv_tol)
    level = "none"
    for name in ("g0", "g1", "g2", "g3"):
        if out[name]:
            level = name.upper()
        else:
            break
    out["level"] = level
    return out


def ends_of(form: NurbsForm, which: str) -> dict:
    lo, hi = form.domain()
    return {"u": hi if which == "end" else lo, "point": form.point(hi if which == "end" else lo)}
