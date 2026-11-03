import math

from app.flow.limits import FlowError, need

LABEL = "Straight fin with a uniform section, one film coefficient h. Insulated tip or a convecting tip through the corrected length."


def fin(spec: dict) -> dict:
    h = need(spec.get("h"), "The film coefficient h", positive=True, high=1e5)
    k = need(spec.get("k"), "The conductivity k", positive=True, high=1e4)
    length = need(spec.get("length"), "The fin length", positive=True, high=10.0)
    theta = need(spec.get("theta_root", spec.get("delta_t")), "The root temperature above ambient", high=5000.0)
    if "perimeter" in spec and "area" in spec:
        perimeter = need(spec["perimeter"], "The perimeter", positive=True, high=100.0)
        area = need(spec["area"], "The section area", positive=True, high=10.0)
        thickness = spec.get("thickness")
        thickness = need(thickness, "The thickness", positive=True) if thickness is not None else 4.0 * area / perimeter
    elif "width" in spec and "thickness" in spec:
        w = need(spec["width"], "The fin width", positive=True, high=10.0)
        thickness = need(spec["thickness"], "The fin thickness", positive=True, high=10.0)
        perimeter, area = 2.0 * (w + thickness), w * thickness
    elif "diameter" in spec:
        d = need(spec["diameter"], "The pin diameter", positive=True, high=10.0)
        perimeter, area, thickness = math.pi * d, math.pi * d * d / 4.0, d
    else:
        raise FlowError("Give width and thickness, a diameter, or perimeter and area.")
    tip = str(spec.get("tip", "adiabatic"))
    if tip not in ("adiabatic", "convective"):
        raise FlowError("The tip must be adiabatic or convective.")
    lc = length + (area / perimeter if tip == "convective" else 0.0)
    m = math.sqrt(h * perimeter / (k * area))
    ml = m * lc
    q = math.sqrt(h * perimeter * k * area) * theta * math.tanh(ml)
    eta = math.tanh(ml) / ml
    ideal = h * perimeter * lc * theta
    biot = h * thickness / (2.0 * k)
    notes = []
    if biot > 0.1:
        notes.append("The Biot number %.3f is above 0.1; the one dimensional fin model may be off. Use the finite element cooling study." % biot)
    return {
        "label": LABEL,
        "m": m,
        "ml": ml,
        "corrected_length": lc,
        "heat_flow": q,
        "efficiency": eta,
        "ideal_heat_flow": ideal,
        "tip_temperature_rise": theta / math.cosh(ml),
        "biot": biot,
        "notes": notes,
    }


def sink(spec: dict) -> dict:
    one = fin(spec)
    n = int(need(spec.get("count"), "The fin count", positive=True, high=10000))
    h = float(spec["h"])
    theta = float(spec.get("theta_root", spec.get("delta_t")))
    base = need(spec.get("base_area", 0.0), "The exposed base area", low=0.0, high=100.0)
    total = n * one["heat_flow"] + h * base * theta
    return {"fin": one, "count": n, "heat_flow": total, "resistance": theta / total if total else None, "base_heat_flow": h * base * theta}
