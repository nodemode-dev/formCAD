import math

GLENAIR_SOURCE = "Glenair, Wire Bundle Diameter Calculator (manufacturer reference guide); one source, not cross-checked"
GLENAIR_FACTORS = [(1, 1.0), (2, 2.0), (3, 2.2), (7, 3.0), (10, 4.0), (20, 5.6), (36, 7.4), (50, 8.5), (100, 12.2), (200, 17.2), (300, 21.0)]
BRAID_SHIELD_MM = 0.025 * 25.4
MAX_CONDUCTORS = 300
MIN_BEND_FACTOR = 10.0
MIN_BEND_SOURCE = "Lectromec summary of AS50881 (10 x largest wire or cable diameter); one secondary source"
FLAGS = [
    {"rule": "bundle diameter packing factor", "source": GLENAIR_SOURCE, "status": "single source", "override": "segment diameter"},
    {"rule": "minimum bend radius 10 x bundle diameter", "source": MIN_BEND_SOURCE, "status": "single source, secondary", "override": "settings min_bend_factor, segment min_radius, cable or wire min_radius"},
]


class RuleError(ValueError):
    pass


def packing_factor(n: int) -> float:
    if n < 1:
        return 0.0
    if n > MAX_CONDUCTORS:
        raise RuleError("The packing table stops at %d conductors in one bundle; give the segment diameter." % MAX_CONDUCTORS)
    for (n0, f0), (n1, f1) in zip(GLENAIR_FACTORS, GLENAIR_FACTORS[1:]):
        if n0 <= n <= n1:
            return f0 + (f1 - f0) * (n - n0) / (n1 - n0) if n1 > n0 else f0
    return GLENAIR_FACTORS[-1][1]


def bundle_diameter(ods, shield=False, covering=0.0) -> float:
    ods = [float(o) for o in ods]
    if not ods:
        return 0.0
    avg = sum(ods) / len(ods)
    d = avg * packing_factor(len(ods))
    if shield:
        d += BRAID_SHIELD_MM
    return d + 2.0 * max(0.0, float(covering))


def conductor_mm(awg: float) -> float:
    return 0.127 * 92.0 ** ((36.0 - float(awg)) / 39.0)


def parse_gauge(text):
    s = str(text or "").lower().replace("awg", "").strip()
    try:
        v = float(s)
    except ValueError:
        return None
    return v if 0 <= v <= 40 and math.isfinite(v) else None
