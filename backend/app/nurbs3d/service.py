import math

from app.nurbs3d import blend as blend_mod
from app.nurbs3d import continuity as cont_mod
from app.nurbs3d import match as match_mod
from app.nurbs3d.form import FormError, NurbsForm
from app.param.units import mm_per_unit
from app.services import kernel

SHORT = 60.0
LONG = 300.0
LENGTH_KEYS = ("distance", "length", "tol")
RECORD_KEYS = ("curve", "a", "b")
POINT_KEYS = ("points",)
DEFAULT_CURVATURE_TOL = cont_mod.DEFAULT_CURVATURE_TOL
FIT_FLOOR = 1e-6


class CurveError(Exception):
    pass


def have_kernel() -> bool:
    return kernel.serial() != 0


def scale_of(d) -> float:
    return mm_per_unit(d)


def tolerances(d) -> tuple:
    tol = float(d.tolerances.get("absolute", 1e-9))
    ang = float(d.tolerances.get("angular", 1e-9))
    return tol, ang


def curvature_tol(d) -> float:
    return float(d.tolerances.get("curvature", DEFAULT_CURVATURE_TOL))


def fit_tolerance(d, given=None) -> float:
    if given is not None:
        v = float(given)
        if not math.isfinite(v) or v <= 0:
            raise CurveError("The tolerance must be a positive number.")
        return v
    return max(tolerances(d)[0], FIT_FLOOR)


def scaled_record(rec, k):
    out = dict(rec)
    out["poles"] = [[c * k for c in q] for q in rec["poles"]]
    return out


def to_mm(d, params: dict) -> dict:
    k = scale_of(d)
    out = dict(params)
    for key in RECORD_KEYS:
        if isinstance(out.get(key), dict):
            out[key] = scaled_record(out[key], k)
    if isinstance(out.get("curves"), list):
        out["curves"] = [scaled_record(r, k) for r in out["curves"]]
    for key in POINT_KEYS:
        if out.get(key) is not None:
            out[key] = [[float(c) * k for c in q] for q in out[key]]
    for key in LENGTH_KEYS:
        if out.get(key) is not None:
            out[key] = float(out[key]) * k
    return out


def from_mm(d, result: dict) -> dict:
    k = 1.0 / scale_of(d)
    out = dict(result)
    if isinstance(out.get("curve"), dict):
        out["curve"] = scaled_record(out["curve"], k)
    for key in ("deviation", "added_length", "tol_used", "position_gap"):
        if isinstance(out.get(key), (int, float)):
            out[key] = out[key] * k
    tol = out.get("tolerances")
    if isinstance(tol, dict):
        out["tolerances"] = {kk: (vv * k if kk in ("vertex_max", "edge_max", "face_max", "limit") else vv) for kk, vv in tol.items()}
    return out


def worker(d, method: str, params: dict, timeout: float = SHORT) -> dict:
    tol, ang = tolerances(d)
    payload = to_mm(d, dict(params))
    payload.setdefault("tol", tol * scale_of(d))
    payload.setdefault("angle_tol", ang)
    try:
        res = kernel.call(method, payload, timeout)
    except kernel.KernelError as err:
        raise CurveError(str(err))
    return from_mm(d, res)


def audit_of(res: dict) -> dict:
    t = res.get("tolerances") or {}
    out = {"checked": bool(t) and "error" not in t}
    for key in ("vertex_max", "edge_max", "face_max", "limit", "exceeds"):
        if key in t:
            out[key] = t[key]
    if "tol_used" in res:
        out["tol_used"] = res["tol_used"]
    if "deviation" in res:
        out["deviation"] = res["deviation"]
    return out


def form_of(e) -> NurbsForm:
    if e is None or e.kind != "nurbscurve":
        raise CurveError("Select a NURBS curve.")
    try:
        return NurbsForm.from_entity(e)
    except FormError as err:
        raise CurveError(str(err))


def checked_record(d, form: NurbsForm):
    try:
        form.check()
    except FormError as err:
        raise CurveError(str(err))
    if not have_kernel():
        return form.to_record(), {"checked": False, "note": "No kernel is installed; the curve was not checked by the kernel."}
    res = worker(d, "curve_make", {"curve": form.to_record()})
    return res["curve"], audit_of(res)


def apply(e, rec: dict, audit: dict, source: dict | None = None) -> None:
    e.set_record(rec)
    e.audit = audit
    if source is not None:
        e.source = source


def make_through(d, params: dict) -> dict:
    res = worker(d, "curve_interpolate", params)
    return {"record": res["curve"], "audit": audit_of(res)}


def end_near(form: NurbsForm, point) -> str:
    lo, hi = form.domain()
    a, b = form.point(lo), form.point(hi)
    q = [float(point[0]), float(point[1])]
    da = math.hypot(a[0] - q[0], a[1] - q[1])
    db = math.hypot(b[0] - q[0], b[1] - q[1])
    return "start" if da <= db else "end"


def param_near(form: NurbsForm, point) -> float:
    q = [float(point[0]), float(point[1])]
    best, bu = None, form.domain()[0]
    for u in form.sample_params(32):
        p = form.point(u)
        dist = math.hypot(p[0] - q[0], p[1] - q[1])
        if best is None or dist < best:
            best, bu = dist, u
    lo, hi = form.domain()
    step = (hi - lo) / (32 * max(len(form.knots) - 1, 1))
    a, b = max(lo, bu - step), min(hi, bu + step)
    for _ in range(50):
        m1, m2 = a + (b - a) / 3.0, b - (b - a) / 3.0
        p1, p2 = form.point(m1), form.point(m2)
        if math.hypot(p1[0] - q[0], p1[1] - q[1]) < math.hypot(p2[0] - q[0], p2[1] - q[1]):
            b = m2
        else:
            a = m1
    return (a + b) / 2.0


def do_blend(d, fa, end_a, fb, end_b, cont_a, cont_b, factor_a, factor_b) -> dict:
    try:
        form = blend_mod.blend(fa, end_a, fb, end_b, cont_a, cont_b, factor_a, factor_b)
    except FormError as err:
        raise CurveError(str(err))
    rec, audit = checked_record(d, form)
    audit["continuity"] = {"start": blend_mod.level_of(cont_a), "end": blend_mod.level_of(cont_b)}
    return {"record": rec, "audit": audit}


def do_match(d, moving, which, target, target_end, cont, scale=1.0, refine=True) -> dict:
    try:
        form, added = match_mod.match(moving, which, target, target_end, cont, scale, refine)
    except FormError as err:
        raise CurveError(str(err))
    rec, audit = checked_record(d, form)
    audit["refined_knots"] = added
    return {"record": rec, "audit": audit}


def measure(d, fa, end_a, fb, end_b) -> dict:
    tol, ang = tolerances(d)
    k = scale_of(d)
    try:
        own = cont_mod.own_measure(fa, end_a, fb, end_b)
    except FormError as err:
        raise CurveError(str(err))
    worker_res = None
    if have_kernel():
        try:
            res = worker(d, "curve_continuity", {"a": fa.to_record(), "b": fb.to_record(), "end_a": end_a, "end_b": end_b, "tol": tol, "angle_tol": ang, "curvature_tol": curvature_tol(d)})
            worker_res = res
        except CurveError:
            worker_res = None
    out = cont_mod.decide(own, worker_res, tol, ang, curvature_tol(d))
    out["end_a"], out["end_b"] = end_a, end_b
    return out
