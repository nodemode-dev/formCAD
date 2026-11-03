import math

from app.doc import hatchfill as H
from app.doc import patterns
from app.doc.entities import Arc, Circle, Ellipse, Line, LwPolyline, Spline, Text
from app.views import geom2d, model

TEXT_H_MM = 3.5


def paper(e, k):
    px, py = e.position

    def f(p):
        return [px + p[0] * k, py + p[1] * k, 0.0]

    return f


def convert(rec, f, k, layer):
    t = rec["t"]
    if t == "line":
        ent = Line(start=f(rec["a"]), end=f(rec["b"]))
    elif t == "circle":
        ent = Circle(center=f(rec["c"]), radius=rec["r"] * k)
    elif t == "arc":
        ent = Arc(center=f(rec["c"]), radius=rec["r"] * k, start_angle=rec["a0"], end_angle=rec["a1"])
    elif t == "ellipse":
        ent = Ellipse(center=f(rec["c"]), major=[rec["major"][0] * k, rec["major"][1] * k, 0.0], ratio=rec["ratio"], start_param=rec["a0"], end_param=rec["a1"])
    elif t == "spline":
        w = rec.get("w")
        ent = Spline(degree=rec["deg"], knots=list(rec["knots"]), control_points=[f(p) for p in rec["ctrl"]], weights=list(w) if w else [])
    else:
        pts = rec.get("pts") or []
        if len(pts) < 2:
            return None
        ent = LwPolyline.from_points([(f(p)[0], f(p)[1]) for p in pts], closed=False)
    ent.layer = layer
    return ent


def hatch_lines(e, faces, f, k, layer):
    out = []
    fams = patterns.LIBRARY["ANSI31"]
    unit = patterns.scale_unit(True) / (e.unit_mm or 1.0)
    for face in faces:
        rl = geom2d.rings(face)
        if not rl:
            continue
        rings = [[f(p)[:2] for p in r] for r in rl]
        segs, dense = H.pattern_segments(rings, fams, 1.0, 0.0, rings[0][0], unit, H.DISPLAY_RUNS)
        if dense:
            continue
        for row in segs.round(6).tolist():
            ent = Line(start=[row[0], row[1], 0.0], end=[row[2], row[3], 0.0])
            ent.layer = layer
            out.append(ent)
    return out


def entities(e):
    cache = e.cache or {}
    classes = cache.get("classes") or {}
    k = float(e.scale) / (e.unit_mm or 1.0)
    f = paper(e, k)
    out = []
    for cls in model.CLASSES:
        if not model.class_enabled(e.show, cls):
            continue
        layer = ((e.style or {}).get(cls) or {}).get("layer") or model.CLASS_LAYER[cls]
        for rec in classes.get(cls) or []:
            ent = convert(rec, f, k, layer)
            if ent is not None:
                out.append(ent)
    for bd in cache.get("bends") or []:
        ent = convert({"t": "line", "a": bd["a"], "b": bd["b"]}, f, k, model.LAYER_BEND)
        if ent is not None:
            out.append(ent)
        if e.show.get("label", True) and bd.get("note"):
            th = 2.5 / (e.unit_mm or 1.0)
            pa, pb = f(bd["a"]), f(bd["b"])
            ang = math.atan2(pb[1] - pa[1], pb[0] - pa[0])
            pos = [(pa[0] + pb[0]) / 2.0 - math.sin(ang) * th * 1.2, (pa[1] + pb[1]) / 2.0 + math.cos(ang) * th * 1.2, 0.0]
            txt = Text(position=pos, align_point=list(pos), height=th, text=bd["note"], rotation=ang, halign=1, valign=2)
            txt.layer = model.LAYER_BEND
            out.append(txt)
    faces = cache.get("faces") or []
    if faces and e.show.get("hatch", True):
        out.extend(hatch_lines(e, faces, f, k, model.LAYER_SECTION))
    for rec in cache.get("extra") or []:
        ent = convert(rec, f, k, model.LAYER_BREAK)
        if ent is not None:
            out.append(ent)
    if e.label and e.show.get("label", True):
        b = e.bounds()
        th = TEXT_H_MM / (e.unit_mm or 1.0)
        pos = [(b[0] + b[2]) / 2.0, b[1] - th * 1.8, 0.0]
        txt = Text(position=pos, align_point=list(pos), height=th, text=e.label, halign=1, valign=2)
        txt.layer = model.LAYER_LABEL
        out.append(txt)
    return out
