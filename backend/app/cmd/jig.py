import math

from app.doc import geom
from app.doc.entities import Arc, Circle, Ellipse, Line, LwPolyline, MText, Point, Polyline3d, Ray, Solid, Spline, Text, XLine

MAX_ITEMS = 2000
JIG_COLOR = [255, 255, 255]
ACI = {1: [255, 0, 0], 2: [255, 255, 0], 3: [0, 255, 0], 4: [0, 255, 255], 5: [0, 0, 255], 6: [255, 0, 255], 7: [255, 255, 255], 8: [128, 128, 128], 9: [192, 192, 192]}


def _p(v):
    return [float(v[0]), float(v[1])]


def line(a, b) -> dict:
    return {"type": "line", "p1": _p(a), "p2": _p(b)}


def circle(c, r) -> dict:
    return {"type": "circle", "c": _p(c), "r": float(r)}


def arc(c, r, a0, a1) -> dict:
    return {"type": "arc", "c": _p(c), "r": float(r), "a0": geom.norm_angle(a0), "a1": geom.norm_angle(a1)}


def poly(verts, closed=False) -> dict:
    out = []
    for v in verts:
        if isinstance(v, dict):
            out.append([v["p"][0], v["p"][1], v.get("bulge", 0.0), v.get("sw", 0.0), v.get("ew", 0.0)])
        else:
            out.append([v[0], v[1], v[2] if len(v) > 2 else 0.0, 0.0, 0.0])
    return {"type": "poly", "verts": out, "closed": bool(closed), "elev": 0.0}


def segment(p0, p1, bulge=0.0) -> dict:
    return poly([[p0[0], p0[1], bulge], [p1[0], p1[1], 0.0]])


def rubber(base, p) -> list:
    return [line(base, p)]


def circle_radius(c, p, factor=1.0) -> list:
    r = geom.dist(c, p) * factor
    if r < geom.EPS:
        return [line(c, p)]
    return [circle(c, r), line(c, p)]


def circle_2p(a, b) -> list:
    r = geom.dist(a, b) / 2.0
    if r < geom.EPS:
        return [line(a, b)]
    return [circle(geom.midpoint(a, b), r), line(a, b)]


def circle_3p(a, b, c) -> list:
    res = geom.circle_from_3pts(a, b, c)
    if res is None:
        return [line(a, b), line(b, c)]
    return [circle(res[0], res[1])]


def arc_through(a, b, c) -> list:
    res = geom.arc_from_3pts(a, b, c)
    if res is None:
        return [line(a, c)]
    return [arc(*res)]


def arc_centre_ends(s, c, e) -> list:
    r = geom.dist(c, s)
    if r < geom.EPS:
        return []
    return [arc(c, r, geom.angle_of(c, s), geom.angle_of(c, e))]


def _rgb(e, d):
    col = e.color
    if isinstance(col, str) and col.startswith("#") and len(col) == 7:
        try:
            return [int(col[1:3], 16), int(col[3:5], 16), int(col[5:7], 16)], False
        except ValueError:
            return list(JIG_COLOR), True
    if col == 256:
        rec = d.layer(e.layer)
        col = rec.get("color", 7) if rec else 7
        if isinstance(col, str) and col.startswith("#"):
            return _rgb(Line(color=col), d)
    if isinstance(col, int) and col in ACI:
        return list(ACI[col]), col == 7
    return list(JIG_COLOR), True


def entity_geom(e, d):
    if isinstance(e, Line):
        return line(e.start, e.end)
    if isinstance(e, Circle):
        return circle(e.center, e.radius)
    if isinstance(e, Arc):
        return {"type": "arc", "c": _p(e.center), "r": e.radius, "a0": e.start_angle, "a1": e.end_angle}
    if isinstance(e, Ellipse):
        return {"type": "ellipse", "c": _p(e.center), "major": _p(e.major), "ratio": e.ratio, "a0": e.start_param, "a1": e.end_param}
    if isinstance(e, LwPolyline):
        g = poly(e.vertices, e.closed)
        g["elev"] = e.elevation
        return g
    if isinstance(e, Polyline3d):
        return poly([[p[0], p[1], 0.0] for p in e.points], e.closed)
    if isinstance(e, Spline):
        return {"type": "spline", "degree": e.degree, "knots": list(e.knots), "ctrl": [_p(p) for p in e.control_points], "weights": list(e.weights) if e.weights else None, "fit": [_p(p) for p in e.fit_points] if e.fit_points else None, "closed": e.closed}
    if isinstance(e, Point):
        size = float(d.header.get("PDSIZE", 0.0))
        return {"type": "point", "p": _p(e.position), "mode": int(d.header.get("PDMODE", 0)), "size": size if size > 0 else 1.0}
    if isinstance(e, (Ray, XLine)):
        n = math.hypot(e.direction[0], e.direction[1]) or 1.0
        return {"type": "ray" if isinstance(e, Ray) else "xline", "p": _p(e.base), "dir": [e.direction[0] / n, e.direction[1] / n]}
    if isinstance(e, Text):
        w = e.height * 0.6 * e.width_factor * max(len(e.text), 1)
        c, s = math.cos(e.rotation), math.sin(e.rotation)
        x, y = e.position[0], e.position[1]
        box = [[x, y], [x + w * c, y + w * s], [x + w * c - e.height * s, y + w * s + e.height * c], [x - e.height * s, y + e.height * c]]
        return {"type": "text", "insert": _p(e.position), "height": e.height, "rot": e.rotation, "box": box}
    if isinstance(e, Solid) and len(e.corners) >= 3:
        order = [0, 1, 3, 2] if len(e.corners) == 4 else list(range(len(e.corners)))
        return poly([e.corners[i] for i in order], True)
    box = e.bounds()
    if box is None:
        return None
    return poly([[box[0], box[1]], [box[2], box[1]], [box[2], box[3]], [box[0], box[3]]], True)


def geom_bounds(g):
    t = g["type"]
    if t == "line":
        return geom.bounds_of_points([g["p1"], g["p2"]])
    if t == "circle":
        return g["c"][0] - g["r"], g["c"][1] - g["r"], g["c"][0] + g["r"], g["c"][1] + g["r"]
    if t == "arc":
        return geom.arc_bounds(g["c"], g["r"], g["a0"], g["a1"])
    if t == "ellipse":
        ent = Ellipse(center=g["c"] + [0.0], major=g["major"] + [0.0], ratio=g["ratio"], start_param=g["a0"], end_param=g["a1"])
        return ent.bounds()
    if t == "poly":
        ent = LwPolyline(vertices=[{"p": [v[0], v[1]], "bulge": v[2]} for v in g["verts"]], closed=g["closed"])
        return ent.bounds()
    if t == "spline":
        return geom.bounds_of_points(g["ctrl"] or g["fit"] or [])
    if t == "point":
        return geom.bounds_of_points([g["p"]])
    if t == "text":
        return geom.bounds_of_points(g["box"])
    if t in ("ray", "xline"):
        return geom.bounds_of_points([g["p"]])
    return None


def item(g, kind=None, color=None, color7=True, layer="0", lw=0.25) -> dict:
    box = geom_bounds(g)
    return {
        "h": None,
        "kind": kind or g["type"],
        "layer": layer,
        "color": list(color or JIG_COLOR),
        "color7": color7,
        "lw": lw,
        "lt": None,
        "tr": 0.0,
        "plot": False,
        "order": 0,
        "geom": g,
        "prims": [],
        "grips": [],
        "bounds": list(box) if box else None,
        "jig": True,
    }


def entity_item(e, d, handle=None) -> dict | None:
    g = entity_geom(e, d)
    if g is None:
        return None
    rgb, c7 = _rgb(e, d)
    lw = e.lineweight / 100.0 if isinstance(e.lineweight, (int, float)) and e.lineweight > 0 else 0.25
    out = item(g, e.kind, rgb, c7, e.layer, lw)
    out["h"] = handle
    return out


def entity_items(ents, d) -> list:
    out = []
    for e in ents:
        it = entity_item(e, d)
        if it is not None:
            out.append(it)
        if len(out) >= MAX_ITEMS:
            break
    return out


def moved_items(d, handles, vec) -> list:
    clones = []
    for h in handles[:MAX_ITEMS]:
        e = d.get(h)
        if e is None:
            continue
        c = e.copy_as_new()
        c.move_by(vec)
        clones.append(c)
    return entity_items(clones, d)


def items(shapes) -> list:
    return [item(g) for g in shapes if g]


def build(runner, pt) -> dict:
    run = runner.run
    if run is None:
        return {"items": []}
    cursor = [float(pt[0]), float(pt[1]), 0.0]
    if run.sel is not None and run.sel.window and run.sel.window[0] in ("fence", "wp", "cp") and run.sel.window[1]:
        chain = [[p[0], p[1]] for p in run.sel.window[1]] + [[cursor[0], cursor[1]]]
        return {"items": items([poly(chain, run.sel.window[0] != "fence" and len(chain) > 2)])}
    if run.sel is not None and run.sel.window and len(run.sel.window[1]) == 1:
        a = run.sel.window[1][0]
        return {"items": items([poly([[a[0], a[1]], [cursor[0], a[1]], [cursor[0], cursor[1]], [a[0], cursor[1]]], True)])}
    if run.frames:
        return {"items": []}
    prompt = run.prompt
    fn = getattr(prompt, "jig", None) if prompt is not None else None
    if fn is None:
        return {"items": []}
    restore = runner.jig_prepare(cursor)
    try:
        res = fn(cursor)
    except Exception:
        res = []
    finally:
        restore()
    out = []
    for r in res or []:
        if isinstance(r, dict) and "geom" in r:
            out.append(r)
        elif isinstance(r, dict):
            out.append(item(r))
    return {"items": out[:MAX_ITEMS]}
