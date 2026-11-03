import math

from app.flow.limits import FlowError, need

LABEL = "Estimate only. One dimensional slab cooling for freeze times, and a free-plate curvature from a differential shrinkage you enter. No pressure-volume-temperature model, no fibre orientation, no crystallisation."
MIN_FOURIER = 0.2


def slab_time(thickness: float, diffusivity: float, t_start: float, t_wall: float, t_end: float, notes: list) -> float:
    h = need(thickness, "The thickness", positive=True, high=1.0)
    a = need(diffusivity, "The thermal diffusivity", positive=True, high=1e-3)
    t0 = need(t_start, "The melt temperature", high=2000.0)
    tw = need(t_wall, "The mould wall temperature", high=2000.0)
    te = need(t_end, "The freeze or ejection temperature", high=2000.0)
    if not (t0 > te > tw):
        raise FlowError("The temperatures must satisfy melt > freeze or ejection > mould wall.")
    arg = 4.0 / math.pi * (t0 - tw) / (te - tw)
    t = h * h / (math.pi ** 2 * a) * math.log(arg)
    if a * t / (h * h) < MIN_FOURIER:
        notes.append("The Fourier number %.3f is below %.1f, where one term of the series is not accurate; the time is low." % (a * t / (h * h), MIN_FOURIER))
    return t


def pack(spec: dict) -> dict:
    notes = []
    gate_t = slab_time(spec.get("gate_thickness"), spec.get("diffusivity"), spec.get("t_melt"), spec.get("t_mould"), spec.get("t_freeze"), notes)
    part_t = slab_time(spec.get("thickness"), spec.get("diffusivity"), spec.get("t_melt"), spec.get("t_mould"), spec.get("t_eject", spec.get("t_freeze")), notes)
    ratio = gate_t / part_t
    if ratio < 0.5:
        advice = "The gate freezes well before the part has cooled, so holding pressure stops feeding the thick section early; shrinkage and sink are likely there. A larger gate lengthens the pack time."
    elif ratio < 1.2:
        advice = "The gate freeze time is close to the cooling time; the holding time can be set near the gate freeze time."
    else:
        advice = "The gate stays open as long as the part cools, so the holding time is limited by the cooling time rather than the gate."
    return {"label": LABEL, "gate_freeze_time": gate_t, "cooling_time": part_t, "ratio": ratio, "advice": advice, "notes": list(dict.fromkeys(notes))}


def warp(spec: dict) -> dict:
    length = need(spec.get("length"), "The strip length", positive=True, high=100.0)
    thickness = need(spec.get("thickness"), "The thickness", positive=True, high=1.0)
    if "delta_strain" in spec:
        de = need(spec["delta_strain"], "The differential shrinkage strain", high=1.0)
        source = "differential shrinkage strain between the two faces"
    else:
        alpha = need(spec.get("alpha"), "The shrinkage coefficient", positive=True, high=1e-2)
        dt = need(spec.get("delta_t"), "The temperature difference between the mould halves", high=1000.0)
        de = alpha * dt
        source = "coefficient times the mould half temperature difference"
    kappa = de / thickness
    sag = kappa * length * length / 8.0
    notes = ["A free thin plate with a linear strain change through the thickness bends to curvature (difference in face strain) / thickness with no stress; the sagitta is curvature x length^2 / 8 for small angles."]
    if sag > 0.1 * length:
        notes.append("The deflection is not small against the length; the small angle formula is off.")
    return {"label": LABEL, "source": source, "differential_strain": de, "curvature": kappa, "radius": (1.0 / kappa) if kappa else None, "deflection": sag, "notes": notes}
