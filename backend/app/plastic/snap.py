import math

STEPS = 2000


def taper_k(ratio: float) -> float:
    r = min(1.0, max(0.05, float(ratio)))
    if r >= 0.999999:
        return 1.0
    n = STEPS
    h = 1.0 / n
    total = 0.0
    for i in range(n + 1):
        u = i * h
        f = (1.0 - u) ** 2 / (1.0 - (1.0 - r) * u) ** 3
        total += f * (1 if i in (0, n) else (4 if i % 2 else 2))
    return 3.0 * total * h / 3.0


def strain_pct(length: float, root: float, deflection: float, ratio: float = 1.0) -> float:
    k = taper_k(ratio)
    return 100.0 * 3.0 * deflection * root / (2.0 * length * length * k)


def deflection_for(length: float, root: float, strain_percent: float, ratio: float = 1.0) -> float:
    k = taper_k(ratio)
    return (strain_percent / 100.0) * 2.0 * length * length * k / (3.0 * root)


def forces(width: float, root: float, length: float, strain_percent: float, modulus: float | None, friction: float | None, lead_deg: float) -> dict:
    out = {"deflection_force": None, "mating_force": None}
    if not modulus:
        return out
    p = width * root * root * modulus * (strain_percent / 100.0) / (6.0 * length)
    out["deflection_force"] = p
    if friction is not None:
        a = math.radians(lead_deg)
        den = 1.0 - friction * math.tan(a)
        out["mating_force"] = p * (friction + math.tan(a)) / den if den > 1e-6 else None
    return out
