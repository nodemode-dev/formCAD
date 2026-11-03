import math

LIMITS = {
    "interactive": {"tracks": 400000, "pads": 60000, "vias": 60000, "zone_points": 3000000, "components": 20000, "silk": 200000, "board_mm": 600.0},
    "restricted": {"tracks": 40000, "pads": 8000, "vias": 8000, "zone_points": 300000, "components": 2000, "silk": 20000, "board_mm": 300.0},
}


class OutputError(ValueError):
    pass


def limits(restricted: bool) -> dict:
    return LIMITS["restricted" if restricted else "interactive"]


def num(v, name, default=None):
    if v is None:
        if default is None:
            raise OutputError("%s is missing." % name)
        return default
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise OutputError("%s is not a number." % name)
    if not math.isfinite(x):
        raise OutputError("%s is not finite." % name)
    return x


def bulge_arc(a, b, bulge):
    dx, dy = b[0] - a[0], b[1] - a[1]
    chord = math.hypot(dx, dy)
    if chord < 1e-12 or abs(bulge) < 1e-12:
        return None
    sweep = 4.0 * math.atan(bulge)
    r = chord / (2.0 * math.sin(abs(sweep) / 2.0))
    mx, my = (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0
    h = r * math.cos(abs(sweep) / 2.0) * (1.0 if sweep > 0 else -1.0)
    return mx - dy / chord * h, my + dx / chord * h, r, sweep


def arc_through(a, m, b):
    ax, ay = a
    bx, by = m
    cx, cy = b
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    cross = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
    return ux, uy, math.hypot(ax - ux, ay - uy), cross > 0


def loop_points(loop, tol=None):
    pts = []
    verts = loop.get("verts") or []
    n = len(verts)
    for i in range(n):
        a, b = verts[i], verts[(i + 1) % n]
        pts.append((float(a[0]), float(a[1])))
        bulge = float(a[2]) if len(a) > 2 else 0.0
        arc = bulge_arc((a[0], a[1]), (b[0], b[1]), bulge) if abs(bulge) > 1e-12 else None
        if arc:
            cx, cy, r, sweep = arc
            a0 = math.atan2(a[1] - cy, a[0] - cx)
            if tol and r > tol:
                step = 2.0 * math.acos(max(0.0, min(1.0, 1.0 - tol / r)))
                steps = max(2, int(math.ceil(abs(sweep) / max(step, 1e-3))))
            else:
                steps = max(2, int(abs(sweep) / math.radians(5)))
            for k in range(1, steps):
                t = a0 + sweep * k / steps
                pts.append((cx + r * math.cos(t), cy + r * math.sin(t)))
    return pts


def area(pts):
    s = 0.0
    for i in range(len(pts)):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % len(pts)]
        s += x0 * y1 - x1 * y0
    return s / 2.0


def outline_box(view):
    xs, ys = [], []
    for loop in view["outline"]["loops"]:
        for x, y in loop_points(loop):
            xs.append(x)
            ys.append(y)
    if not xs:
        raise OutputError("The board has no outline.")
    return min(xs), min(ys), max(xs), max(ys)


def clean(view: dict, restricted: bool = False) -> dict:
    if not isinstance(view, dict):
        raise OutputError("The board description is missing.")
    lim = limits(restricted)
    out = {"name": str(view.get("name") or "board")[:120], "thickness": num(view.get("thickness"), "thickness", 1.6), "layers": list(view.get("layers") or ["F.Cu", "B.Cu"])}
    if len(out["layers"]) < 2 or len(out["layers"]) > 16 or out["layers"][0] != "F.Cu" or out["layers"][-1] != "B.Cu":
        raise OutputError("The copper layers must run F.Cu first to B.Cu last, between 2 and 16 layers.")
    if out["thickness"] <= 0.05 or out["thickness"] > 10:
        raise OutputError("The board thickness must be between 0.05 and 10 mm.")
    loops = (view.get("outline") or {}).get("loops") or []
    if not loops:
        raise OutputError("The board has no outline.")
    outer = [lp for lp in loops if lp.get("outer", True)]
    if len(outer) != 1:
        raise OutputError("The board outline needs exactly one outer loop.")
    out["outline"] = {"loops": [{"outer": bool(lp.get("outer", True)), "verts": [[num(v[0], "x"), num(v[1], "y"), num(v[2], "bulge", 0.0) if len(v) > 2 else 0.0] for v in lp["verts"]]} for lp in loops]}
    for lp in out["outline"]["loops"]:
        if len(lp["verts"]) < 3:
            raise OutputError("An outline loop needs at least three vertices.")
    box = outline_box(out)
    if max(box[2] - box[0], box[3] - box[1]) > lim["board_mm"]:
        raise OutputError("The board is larger than %g mm; the limit for this caller." % lim["board_mm"])
    for key, cap in (("tracks", "tracks"), ("pads", "pads"), ("vias", "vias"), ("components", "components"), ("silk", "silk")):
        rows = list(view.get(key) or [])
        if len(rows) > lim[cap]:
            raise OutputError("The board has %d %s; the limit for this caller is %d." % (len(rows), key, lim[cap]))
        out[key] = rows
    zones = list(view.get("zones") or [])
    pts = 0
    for z in zones:
        for poly in z.get("polys") or []:
            for ring in poly:
                pts += len(ring)
    if pts > lim["zone_points"]:
        raise OutputError("The copper fills hold %d points; the limit for this caller is %d." % (pts, lim["zone_points"]))
    out["zones"] = zones
    out["holes"] = list(view.get("holes") or [])
    out["origin"] = list(box[:2])
    out["box"] = list(box)
    out["tent_vias"] = bool(view.get("tent_vias", True))
    out["mask_margin"] = num(view.get("mask_margin"), "mask_margin", 0.05)
    out["paste_margin"] = num(view.get("paste_margin"), "paste_margin", 0.0)
    out["created"] = str(view.get("created") or "")
    return out
