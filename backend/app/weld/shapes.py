import math

MAX_SIZE_MM = 5000.0
SHAPES = {
    "rect": [("w", "Width"), ("h", "Height")],
    "flat_bar": [("w", "Width"), ("t", "Thickness")],
    "rect_tube": [("w", "Width"), ("h", "Height"), ("t", "Wall"), ("r", "Outer corner radius (optional)")],
    "round_bar": [("d", "Diameter")],
    "round_tube": [("d", "Outer diameter"), ("t", "Wall")],
    "angle": [("a", "Leg one"), ("b", "Leg two"), ("t", "Thickness")],
    "channel": [("h", "Depth"), ("b", "Flange width"), ("t", "Thickness")],
}
BULGE_90 = math.tan(math.pi / 8.0)


class ShapeError(ValueError):
    pass


def listing() -> list:
    return [{"shape": k, "fields": [{"name": n, "label": lab} for n, lab in v]} for k, v in SHAPES.items()]


def line(a, b, role):
    return {"t": "line", "a": [a[0], a[1]], "b": [b[0], b[1]], "bulge": 0.0, "role": role}


def poly(points, tag):
    segs = []
    for i, p in enumerate(points):
        segs.append(line(p, points[(i + 1) % len(points)], "%s%d" % (tag, i)))
    return {"segs": segs, "closed": True}


def rounded(w, h, r, tag):
    if r <= 1e-9:
        return poly([(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)], tag)
    x, y = w / 2.0, h / 2.0
    corners = [((x - r, -y), (x, -y + r), (x - r, -y + r)), ((x, y - r), (x - r, y), (x - r, y - r)), ((-x + r, y), (-x, y - r), (-x + r, y - r)), ((-x, -y + r), (-x + r, -y), (-x + r, -y + r))]
    pts = [((-x + r, -y), (x - r, -y)), ((x, -y + r), (x, y - r)), ((x - r, y), (-x + r, y)), ((-x, y - r), (-x, -y + r))]
    ordered = []
    for i in range(4):
        a, b = pts[i]
        if math.dist(a, b) > 1e-9:
            ordered.append(line(a, b, "%sl%d" % (tag, i)))
        c0, c1, _ = corners[i]
        ordered.append({"t": "arc", "a": [c0[0], c0[1]], "b": [c1[0], c1[1]], "bulge": BULGE_90, "role": "%sa%d" % (tag, i)})
    return {"segs": ordered, "closed": True}


def circle(d, tag):
    return {"segs": [{"t": "circle", "c": [0.0, 0.0], "r": d / 2.0, "bulge": 0.0, "role": tag}], "closed": True}


def number(spec, key, mm, required=True, lo=0.0):
    v = spec.get(key)
    if v is None or v == "":
        if required:
            raise ShapeError("The profile %s needs %s." % (spec.get("shape"), key))
        return 0.0
    try:
        v = float(v) * mm
    except (TypeError, ValueError):
        raise ShapeError("%s must be a number." % key)
    if not math.isfinite(v) or v < lo or v > MAX_SIZE_MM:
        raise ShapeError("%s is out of range." % key)
    return v


def regions_of(spec, mm):
    kind = spec.get("shape")
    if kind not in SHAPES:
        raise ShapeError("Unknown profile shape %s; use one of %s." % (kind, ", ".join(SHAPES)))
    n = lambda k, req=True: number(spec, k, mm, req)
    if kind == "rect" or kind == "flat_bar":
        w, h = n("w"), n("h" if kind == "rect" else "t")
        if w <= 0 or h <= 0:
            raise ShapeError("Sizes must be positive.")
        return [{"outer": rounded(w, h, 0.0, "o"), "holes": []}], "%s %gx%g" % (kind, w / mm, h / mm)
    if kind == "rect_tube":
        w, h, t, r = n("w"), n("h"), n("t"), n("r", False)
        if min(w, h, t) <= 0 or t * 2 >= min(w, h):
            raise ShapeError("The wall must be positive and less than half of the width and height.")
        if r > min(w, h) / 2.0:
            raise ShapeError("The outer corner radius is too large.")
        ri = max(r - t, 0.0)
        return [{"outer": rounded(w, h, r, "o"), "holes": [rounded(w - 2 * t, h - 2 * t, ri, "i")]}], "rect_tube %gx%gx%g" % (w / mm, h / mm, t / mm)
    if kind == "round_bar":
        d = n("d")
        if d <= 0:
            raise ShapeError("The diameter must be positive.")
        return [{"outer": circle(d, "o"), "holes": []}], "round_bar %g" % (d / mm)
    if kind == "round_tube":
        d, t = n("d"), n("t")
        if d <= 0 or t <= 0 or t * 2 >= d:
            raise ShapeError("The wall must be positive and less than half of the diameter.")
        return [{"outer": circle(d, "o"), "holes": [circle(d - 2 * t, "i")]}], "round_tube %gx%g" % (d / mm, t / mm)
    if kind == "angle":
        a, b, t = n("a"), n("b"), n("t")
        if min(a, b, t) <= 0 or t >= min(a, b):
            raise ShapeError("The thickness must be positive and less than both legs.")
        x0, y0 = -a / 2.0, -b / 2.0
        pts = [(x0, y0), (x0 + a, y0), (x0 + a, y0 + t), (x0 + t, y0 + t), (x0 + t, y0 + b), (x0, y0 + b)]
        return [{"outer": poly(pts, "o"), "holes": []}], "angle %gx%gx%g" % (a / mm, b / mm, t / mm)
    h, b, t = n("h"), n("b"), n("t")
    if min(h, b, t) <= 0 or t * 2 >= h or t >= b:
        raise ShapeError("The thickness must be positive and less than half the depth and less than the flange width.")
    x0, y0 = -b / 2.0, -h / 2.0
    pts = [(x0, y0), (x0 + b, y0), (x0 + b, y0 + t), (x0 + t, y0 + t), (x0 + t, y0 + h - t), (x0 + b, y0 + h - t), (x0 + b, y0 + h), (x0, y0 + h)]
    return [{"outer": poly(pts, "o"), "holes": []}], "channel %gx%gx%g" % (h / mm, b / mm, t / mm)


def points_of(regions) -> list:
    pts = []
    for r in regions:
        for s in r["outer"]["segs"]:
            if s["t"] == "circle":
                c, rad = s["c"], float(s["r"])
                for k in range(16):
                    ang = 2 * math.pi * k / 16
                    pts.append((c[0] + rad * math.cos(ang), c[1] + rad * math.sin(ang)))
                continue
            a, b = s["a"], s["b"]
            pts.append((a[0], a[1]))
            pts.append((b[0], b[1]))
            bulge = float(s.get("bulge", 0.0) or 0.0)
            if abs(bulge) > 1e-12:
                dx, dy = b[0] - a[0], b[1] - a[1]
                ln = math.hypot(dx, dy) or 1.0
                sag = abs(bulge) * ln / 2.0
                sign = 1.0 if bulge > 0 else -1.0
                pts.append(((a[0] + b[0]) / 2 + sign * dy / ln * sag, (a[1] + b[1]) / 2 - sign * dx / ln * sag))
    return pts


def shifted(regions, du, dv):
    if abs(du) < 1e-12 and abs(dv) < 1e-12:
        return regions

    def loop(lp):
        segs = []
        for s in lp["segs"]:
            q = dict(s)
            if s["t"] == "circle":
                q["c"] = [s["c"][0] + du, s["c"][1] + dv]
            else:
                q["a"] = [s["a"][0] + du, s["a"][1] + dv]
                q["b"] = [s["b"][0] + du, s["b"][1] + dv]
            segs.append(q)
        return {"segs": segs, "closed": lp.get("closed", True)}

    return [{"outer": loop(r["outer"]), "holes": [loop(h) for h in r.get("holes") or []]} for r in regions]
