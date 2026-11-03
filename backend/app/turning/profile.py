import math

import numpy as np

SC = 10000.0
MAX_PROFILE_POINTS = 5000
MAX_SECTIONS = 4000


class TurnError(ValueError):
    pass


def _round_corner(a, b, c, r, kind, tol=0.005):
    v1 = (a[0] - b[0], a[1] - b[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    l1, l2 = math.hypot(*v1), math.hypot(*v2)
    if l1 < 1e-9 or l2 < 1e-9:
        return [b]
    u1 = (v1[0] / l1, v1[1] / l1)
    u2 = (v2[0] / l2, v2[1] / l2)
    cosang = max(-1.0, min(1.0, u1[0] * u2[0] + u1[1] * u2[1]))
    ang = math.acos(cosang)
    if ang < 1e-6 or abs(ang - math.pi) < 1e-6:
        return [b]
    if kind == "chamfer":
        d = min(r, l1 * 0.999, l2 * 0.999)
        return [(b[0] + u1[0] * d, b[1] + u1[1] * d), (b[0] + u2[0] * d, b[1] + u2[1] * d)]
    t = r / math.tan(ang / 2.0)
    t = min(t, l1 * 0.999, l2 * 0.999)
    rr = t * math.tan(ang / 2.0)
    p1 = (b[0] + u1[0] * t, b[1] + u1[1] * t)
    p2 = (b[0] + u2[0] * t, b[1] + u2[1] * t)
    bis = (u1[0] + u2[0], u1[1] + u2[1])
    bl = math.hypot(*bis)
    bis = (bis[0] / bl, bis[1] / bl)
    dc = rr / math.sin(ang / 2.0)
    cen = (b[0] + bis[0] * dc, b[1] + bis[1] * dc)
    a0 = math.atan2(p1[1] - cen[1], p1[0] - cen[0])
    a1 = math.atan2(p2[1] - cen[1], p2[0] - cen[0])
    sw = a1 - a0
    while sw > math.pi:
        sw -= 2 * math.pi
    while sw < -math.pi:
        sw += 2 * math.pi
    step = 2.0 * math.acos(max(0.0, 1.0 - tol / rr)) if rr > tol else math.pi / 2
    n = max(2, int(math.ceil(abs(sw) / max(step, 1e-3))))
    return [(cen[0] + rr * math.cos(a0 + sw * i / n), cen[1] + rr * math.sin(a0 + sw * i / n)) for i in range(n + 1)]


def build(spec: dict) -> dict:
    raw = spec.get("pts") or []
    if len(raw) < 2:
        raise TurnError("A turning profile needs at least two points.")
    if len(raw) > MAX_PROFILE_POINTS:
        raise TurnError("A turning profile has at most %d points." % MAX_PROFILE_POINTS)
    diam = spec.get("units", "diameter") == "diameter"
    pts = []
    mods = []
    for p in raw:
        if isinstance(p, dict):
            z = float(p["z"])
            if "d" in p:
                v = float(p["d"]) / 2.0
            elif "r" in p:
                v = float(p["r"])
            else:
                raise TurnError("A profile point needs d (diameter) or r (radius).")
            mod = ("fillet", float(p["fillet"])) if p.get("fillet") else (("chamfer", float(p["chamfer"])) if p.get("chamfer") else None)
        else:
            z, v = float(p[0]), float(p[1])
            v = v / 2.0 if diam else v
            mod = None
        if v < -1e-9:
            raise TurnError("A profile radius cannot be negative.")
        pts.append((z, max(v, 0.0)))
        mods.append(mod)
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        if mods[i]:
            out.extend(_round_corner(pts[i - 1], pts[i], pts[i + 1], mods[i][1], mods[i][0]))
        else:
            out.append(pts[i])
    out.append(pts[-1])
    out = simplify(out)
    return {"pts": out}


def simplify(pts, tol=0.0005):
    out = [pts[0]]
    for i in range(1, len(pts)):
        if math.hypot(pts[i][0] - out[-1][0], pts[i][1] - out[-1][1]) > 1e-7:
            out.append(pts[i])
    res = [out[0]]
    for i in range(1, len(out) - 1):
        a, b, c = res[-1], out[i], out[i + 1]
        cr = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        L = math.hypot(c[0] - a[0], c[1] - a[1])
        if L > 0 and abs(cr) / L < tol:
            continue
        res.append(b)
    res.append(out[-1])
    return res


def from_triangles(tris, tol=0.002, max_sections=MAX_SECTIONS):
    t = np.asarray(tris, float)
    if t.ndim != 3 or t.shape[0] == 0:
        raise TurnError("The model has no triangles to take a turning profile from.")
    zs = np.unique(np.round(t[:, :, 2].ravel(), 5))
    if len(zs) < 2:
        raise TurnError("The model has no extent along the axis.")
    if len(zs) > max_sections:
        raise TurnError("The model has %d section heights; at most %d. Use a coarser mesh." % (len(zs), max_sections))
    eps = (zs[-1] - zs[0]) * 1e-5
    A = np.concatenate([t[:, 0], t[:, 1], t[:, 2]])
    B = np.concatenate([t[:, 1], t[:, 2], t[:, 0]])
    lo = np.minimum(A[:, 2], B[:, 2])
    hi = np.maximum(A[:, 2], B[:, 2])
    keep = hi - lo > 1e-9
    A, B, lo, hi = A[keep], B[keep], lo[keep], hi[keep]

    def radius_at(z):
        m = (lo <= z) & (hi >= z)
        if not m.any():
            return None
        a, b = A[m], B[m]
        s = (z - a[:, 2]) / (b[:, 2] - a[:, 2])
        x = a[:, 0] + s * (b[:, 0] - a[:, 0])
        y = a[:, 1] + s * (b[:, 1] - a[:, 1])
        return float(np.hypot(x, y).max())

    pts = []
    for i in range(len(zs) - 2, -1, -1):
        z0, z1 = float(zs[i]), float(zs[i + 1])
        e = min(eps, (z1 - z0) / 4.0)
        r0 = radius_at(z0 + e)
        r1 = radius_at(z1 - e)
        if r0 is None or r1 is None:
            continue
        pts.append((z1, r1))
        pts.append((z0, r0))
    if len(pts) < 2:
        raise TurnError("No turning profile could be taken from the model.")
    return {"pts": simplify(pts, tol)}


def polygon(profile, z_front=None, z_end=None):
    p = list(profile["pts"])
    if z_front is not None and p[0][0] < z_front - 1e-9:
        p.insert(0, (z_front, p[0][1]))
    if z_end is not None and p[-1][0] > z_end + 1e-9:
        p.append((z_end, p[-1][1]))
    return [(p[0][0], 0.0)] + p + [(p[-1][0], 0.0)]


def check_direction(profile):
    z = [p[0] for p in profile["pts"]]
    for i in range(1, len(z)):
        if z[i] > z[i - 1] + 1e-9:
            return False
    return True
