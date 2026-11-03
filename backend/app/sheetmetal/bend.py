import math

METHODS = ("kfactor", "allowance", "deduction", "table")
DATUMS = ("outside", "inside", "tangent")
METHOD_ALIASES = {"k": "kfactor", "kfactor": "kfactor", "ba": "allowance", "allowance": "allowance", "bd": "deduction", "deduction": "deduction", "table": "table"}
KMIN = (4.0 - math.pi) / math.pi
KSLOPE = (0.5 - KMIN) / 3.0
DEFAULT_K = 0.44


class BendError(ValueError):
    pass


def to_rad(deg):
    return math.radians(float(deg))


def to_deg(rad):
    return math.degrees(float(rad))


def included_from_deflection(theta):
    return math.pi - float(theta)


def deflection_from_included(phi):
    return math.pi - float(phi)


def _check(theta, r, t):
    if t <= 0:
        raise BendError("Thickness must be above zero.")
    if r < 0:
        raise BendError("Inside radius cannot be negative.")
    if theta < 0 or theta >= math.pi:
        raise BendError("Bend deflection must be from 0 up to but not including 180 degrees.")


def neutral_radius(r, t, k):
    return float(r) + float(k) * float(t)


def bend_allowance(theta, r, t, k):
    return float(theta) * neutral_radius(r, t, k)


def outside_setback(theta, r, t):
    return math.tan(float(theta) / 2.0) * (float(r) + float(t))


def inside_setback(theta, r):
    return math.tan(float(theta) / 2.0) * float(r)


def bend_deduction(theta, r, t, k):
    return 2.0 * outside_setback(theta, r, t) - bend_allowance(theta, r, t, k)


def ba_from_bd(theta, r, t, bd):
    return 2.0 * outside_setback(theta, r, t) - float(bd)


def bd_from_ba(theta, r, t, ba):
    return 2.0 * outside_setback(theta, r, t) - float(ba)


def k_from_ba(theta, r, t, ba):
    if theta <= 0:
        raise BendError("A zero angle bend has no K-factor.")
    return (float(ba) / float(theta) - float(r)) / float(t)


def k_from_bd(theta, r, t, bd):
    return k_from_ba(theta, r, t, ba_from_bd(theta, r, t, bd))


def k_from_test_bend(blank_length, straight_lengths, theta, r, t):
    return k_from_ba(theta, r, t, float(blank_length) - sum(float(s) for s in straight_lengths))


def y_from_k(k):
    return float(k) * math.pi / 2.0


def k_from_y(y):
    return float(y) * 2.0 / math.pi


def k_from_ratio(r, t):
    return min(0.5, KMIN + KSLOPE * float(r) / float(t))


def straight_from_leg(h, theta, r, t, datum="outside"):
    if datum == "outside":
        return float(h) - outside_setback(theta, r, t)
    if datum == "inside":
        return float(h) - inside_setback(theta, r)
    if datum == "tangent":
        return float(h)
    raise BendError("Unknown dimension datum %s." % datum)


def leg_from_straight(s, theta, r, t, datum="outside"):
    if datum == "outside":
        return float(s) + outside_setback(theta, r, t)
    if datum == "inside":
        return float(s) + inside_setback(theta, r)
    if datum == "tangent":
        return float(s)
    raise BendError("Unknown dimension datum %s." % datum)


def flat_length_outside(legs, bends):
    return sum(float(x) for x in legs) - sum(b["bd"] for b in bends)


def flat_length_inside(legs, bends):
    return sum(float(x) for x in legs) - sum(2.0 * b["issb"] for b in bends) + sum(b["ba"] for b in bends)


def flat_length_tangent(legs, bends):
    return sum(float(x) for x in legs) + sum(b["ba"] for b in bends)


def flat_length(legs, bends, datum="outside"):
    if datum == "outside":
        return flat_length_outside(legs, bends)
    if datum == "inside":
        return flat_length_inside(legs, bends)
    if datum == "tangent":
        return flat_length_tangent(legs, bends)
    raise BendError("Unknown dimension datum %s." % datum)


def _interp(points, x):
    pts = sorted((float(a), float(b)) for a, b in points)
    if not pts:
        return None, "empty"
    if x <= pts[0][0]:
        return pts[0][1], ("clamped" if x < pts[0][0] - 1e-12 else "")
    if x >= pts[-1][0]:
        return pts[-1][1], ("clamped" if x > pts[-1][0] + 1e-12 else "")
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            if x1 == x0:
                return y0, ""
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0), ""
    return pts[-1][1], ""


def table_lookup(table, thickness, radius, theta):
    mode = METHOD_ALIASES.get(table.get("mode"), None) or {"k": "kfactor", "ba": "allowance", "bd": "deduction"}.get(table.get("mode"))
    axis = table.get("axis", "angle")
    sets = table.get("sets") or []
    tol = float(table.get("tolerance", 1e-6))
    chosen = None
    for s in sets:
        st = s.get("thickness")
        sr = s.get("radius")
        if st is not None and abs(float(st) - thickness) > tol:
            continue
        if sr is not None and abs(float(sr) - radius) > tol:
            continue
        chosen = s
        break
    if chosen is None:
        return None, "outside"
    if axis == "ratio":
        x = radius / thickness
    elif axis == "angle":
        x = to_deg(theta)
    else:
        raise BendError("A bend table axis is angle or ratio.")
    v, flag = _interp(chosen.get("points") or [], x)
    if v is None:
        return None, "outside"
    return v, flag


def resolve_bend(rule, theta, r=None, t=None, override=None):
    """rule keys: thickness_mm, inner_radius_mm, bend_method, k_factor, ba_mm, bd_mm, table, table_out_of_range, backup_k. theta is the deflection in radians."""
    rule = dict(rule or {})
    if override:
        rule.update({k: v for k, v in override.items() if v is not None})
    t = float(t if t is not None else rule.get("thickness_mm", 0.0))
    r = float(r if r is not None else rule.get("inner_radius_mm", t))
    theta = float(theta)
    _check(theta, r, t)
    method = METHOD_ALIASES.get(str(rule.get("bend_method", "kfactor")))
    if method is None:
        raise BendError("Unknown bend method %s." % rule.get("bend_method"))
    warns = []
    ref90 = math.pi / 2.0
    k = None
    ba = None
    used = method
    if method == "kfactor":
        k = float(rule.get("k_factor", DEFAULT_K))
        ba = bend_allowance(theta, r, t, k)
    elif method == "allowance":
        v = float(rule.get("ba_mm", 0.0))
        ba = v * theta / ref90
        k = k_from_ba(theta, r, t, ba) if theta > 0 else float(rule.get("k_factor", DEFAULT_K))
    elif method == "deduction":
        v = float(rule.get("bd_mm", 0.0))
        k90 = k_from_bd(ref90, r, t, v)
        k = k90
        ba = bend_allowance(theta, r, t, k)
    else:
        table = rule.get("table")
        if not table:
            raise BendError("The bend method is table but no table is set.")
        v, flag = table_lookup(table, t, r, theta)
        policy = rule.get("table_out_of_range", "clamp_warn")
        if v is None:
            if policy == "backup_k" or rule.get("backup_k") is not None:
                k = float(rule.get("backup_k", DEFAULT_K))
                ba = bend_allowance(theta, r, t, k)
                warns.append("Bend not covered by the table; the backup K-factor %.4g was used." % k)
                used = "kfactor"
            else:
                raise BendError("Bend thickness %.4g and radius %.4g are not covered by the table." % (t, r))
        else:
            if flag == "clamped":
                warns.append("Bend is outside the table range; the nearest table value was used.")
            mode = {"k": "kfactor", "ba": "allowance", "bd": "deduction"}.get(table.get("mode"), METHOD_ALIASES.get(table.get("mode")))
            if mode == "kfactor":
                k = v
                ba = bend_allowance(theta, r, t, k)
            elif mode == "allowance":
                ba = v
                k = k_from_ba(theta, r, t, ba) if theta > 0 else DEFAULT_K
            else:
                ba = ba_from_bd(theta, r, t, v)
                k = k_from_ba(theta, r, t, ba) if theta > 0 else DEFAULT_K
    if ba < -1e-12:
        raise BendError("The bend allowance is negative.")
    ossb = outside_setback(theta, r, t)
    out = {
        "method": used,
        "theta": theta,
        "included": included_from_deflection(theta),
        "radius": r,
        "thickness": t,
        "k": k,
        "neutral_radius": r + k * t,
        "ba": ba,
        "bd": 2.0 * ossb - ba,
        "ossb": ossb,
        "issb": inside_setback(theta, r),
        "warnings": warns,
    }
    if out["bd"] > 2.0 * ossb + 1e-9:
        raise BendError("The bend deduction exceeds twice the outside setback.")
    return out
