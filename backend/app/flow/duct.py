import math

from app.flow.limits import FlowError, need

LAMINAR_MAX = 2300.0
TURBULENT_MIN = 4000.0
SJ_RANGE = (5000.0, 3.0e8)
SJ_ROUGHNESS = (1e-6, 0.01)
MAX_SEGMENTS = 400
METHODS = ("swamee_jain", "colebrook")
LABEL = "Darcy-Weisbach with the Swamee-Jain or Colebrook friction factor. A series path with one flow rate; roughness and fitting coefficients are entered by you (no table is shipped)."


def colebrook(re: float, rel: float) -> float:
    f = swamee_jain(max(re, 4000.0), rel)
    for _ in range(60):
        rhs = -2.0 * math.log10(rel / 3.7 + 2.51 / (re * math.sqrt(f)))
        nxt = 1.0 / (rhs * rhs)
        if abs(nxt - f) < 1e-12:
            f = nxt
            break
        f = nxt
    return f


def swamee_jain(re: float, rel: float) -> float:
    return 0.25 / math.log10(rel / 3.7 + 5.74 / re ** 0.9) ** 2


def friction(re: float, rel: float, method: str = "swamee_jain", notes=None) -> float:
    notes = notes if notes is not None else []
    if re <= 0:
        raise FlowError("The Reynolds number must be positive.")
    if re < LAMINAR_MAX:
        return 64.0 / re
    pick = swamee_jain if method == "swamee_jain" else colebrook
    if re < TURBULENT_MIN:
        lam = 64.0 / LAMINAR_MAX
        turb = pick(TURBULENT_MIN, rel) if rel > 0 else pick(TURBULENT_MIN, 1e-12)
        w = (re - LAMINAR_MAX) / (TURBULENT_MIN - LAMINAR_MAX)
        notes.append("Reynolds number %.0f is in the transition range; the friction factor is interpolated and uncertain." % re)
        return lam + w * (turb - lam)
    if method == "swamee_jain":
        if not (SJ_RANGE[0] <= re <= SJ_RANGE[1]):
            notes.append("Reynolds number %.3g is outside the range of the Swamee-Jain fit (5000 to 3e8)." % re)
        if rel > 0 and not (SJ_ROUGHNESS[0] <= rel <= SJ_ROUGHNESS[1]):
            notes.append("The relative roughness %.3g is outside the range of the Swamee-Jain fit (1e-6 to 0.01)." % rel)
    return pick(re, max(rel, 1e-12))


def section(seg: dict, label: str) -> tuple:
    shape = str(seg.get("shape", "round"))
    if shape == "round":
        d = need(seg.get("diameter"), label + " diameter", positive=True, high=100.0)
        return math.pi * d * d / 4.0, d, d
    if shape == "rect":
        a = need(seg.get("width"), label + " width", positive=True, high=100.0)
        b = need(seg.get("height"), label + " height", positive=True, high=100.0)
        return a * b, 4.0 * a * b / (2.0 * (a + b)), None
    raise FlowError("%s: the section shape must be round or rect." % label)


def run(spec: dict) -> dict:
    rho = need(spec.get("density"), "The density", positive=True, high=30000.0)
    mu = need(spec.get("viscosity"), "The viscosity", positive=True, high=1e4)
    q = need(spec.get("flow"), "The volume flow", positive=True, high=1e4)
    method = str(spec.get("method", "swamee_jain"))
    if method not in METHODS:
        raise FlowError("The friction method must be swamee_jain or colebrook.")
    segs = spec.get("segments")
    if not isinstance(segs, list) or not segs:
        raise FlowError("The duct needs at least one segment.")
    if len(segs) > MAX_SEGMENTS:
        raise FlowError("The duct has more than %d segments." % MAX_SEGMENTS)
    rows, notes, total, last = [], [], 0.0, None
    for i, seg in enumerate(segs):
        if not isinstance(seg, dict):
            raise FlowError("Segment %d is not a record." % (i + 1))
        label = "Segment %d" % (i + 1)
        kind = str(seg.get("kind", "straight"))
        if kind not in ("straight", "fitting", "equivalent_length"):
            raise FlowError("%s: the kind must be straight, fitting or equivalent_length." % label)
        if "diameter" in seg or "width" in seg or last is None:
            area, dh, _ = section(seg, label)
            last = (area, dh)
        area, dh = last
        v = q / area
        re = rho * v * dh / mu
        dyn = 0.5 * rho * v * v
        local = []
        f = friction(re, need(seg.get("roughness", 0.0), label + " roughness", low=0.0, high=1.0) / dh, method, local)
        notes += ["%s: %s" % (label, n) for n in local]
        if kind == "straight":
            length = need(seg.get("length"), label + " length", positive=True, high=1e6)
            k = f * length / dh
        elif kind == "fitting":
            k = need(seg.get("k"), label + " loss coefficient", low=0.0, high=1e4)
            length = k * dh / f
        else:
            length = need(seg.get("length"), label + " equivalent length", low=0.0, high=1e6)
            k = f * length / dh
        dp = k * dyn
        total += dp
        rows.append({"index": i, "name": str(seg.get("name", "")), "kind": kind, "velocity": v, "dynamic_pressure": dyn, "reynolds": re, "friction_factor": f, "loss_coefficient": k, "equivalent_length": length, "hydraulic_diameter": dh, "area": area, "pressure_drop": dp, "cumulative": total})
        if kind != "straight" and "k" in seg and re < LAMINAR_MAX:
            notes.append("%s: loss coefficients are for turbulent flow; this segment is laminar." % label)
    return {"label": LABEL, "method": method, "pressure_drop": total, "segments": rows, "notes": notes}
