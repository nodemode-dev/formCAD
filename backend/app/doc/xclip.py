import math

from app.doc import blockedit
from app.doc.blocktools import EditError
from app.doc.entities import LwPolyline

MAX_POINTS = 10000


def get(ins):
    clip = (ins.extra or {}).get("clip") if isinstance(ins.extra, dict) else None
    return clip if isinstance(clip, dict) and clip.get("points") else None


def target(doc, handle):
    ins = doc.drawing.get(int(handle))
    if ins is None or ins.kind != "insert":
        raise EditError("Select a block or external reference.")
    if doc.drawing.layer_locked(ins.layer):
        raise EditError("The object is on a locked layer.")
    return ins


def rect_points(a, b):
    x0, x1 = sorted((float(a[0]), float(b[0])))
    y0, y1 = sorted((float(a[1]), float(b[1])))
    if x1 - x0 < 1e-9 or y1 - y0 < 1e-9:
        raise EditError("The clip rectangle has no area.")
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def polygon_of(ent):
    if ent is None or ent.kind != "lwpolyline":
        raise EditError("Select a polyline.")
    if not ent.closed:
        raise EditError("The polyline must be closed.")
    pts = [[float(v["p"][0]), float(v["p"][1])] for v in ent.vertices]
    if any(abs(v.get("bulge", 0.0) or 0.0) > 0 for v in ent.vertices):
        raise EditError("The clip polyline must have straight segments.")
    return pts


def area(pts):
    s = 0.0
    for i, p in enumerate(pts):
        q = pts[(i + 1) % len(pts)]
        s += p[0] * q[1] - q[0] * p[1]
    return s / 2.0


def set_new(doc, handle, points, invert=False):
    ins = target(doc, handle)
    pts = [[float(p[0]), float(p[1])] for p in points]
    if len(pts) < 3:
        raise EditError("A clip boundary needs at least three points.")
    if len(pts) > MAX_POINTS:
        raise EditError("The clip boundary has too many points.")
    if not all(math.isfinite(v) for p in pts for v in p) or abs(area(pts)) < 1e-12:
        raise EditError("The clip boundary has no area.")
    blockedit.flag(doc)
    e = doc.drawing.modify(ins.handle)
    e.extra = {**e.extra, "clip": {"points": pts, "on": True, "invert": bool(invert)}}
    return {"handle": ins.handle, "points": len(pts), "invert": bool(invert)}


def set_on(doc, handle, on):
    ins = target(doc, handle)
    clip = get(ins)
    if clip is None:
        raise EditError("The reference has no clip boundary.")
    e = doc.drawing.modify(ins.handle)
    e.extra = {**e.extra, "clip": {**clip, "on": bool(on)}}
    return {"handle": ins.handle, "on": bool(on)}


def delete(doc, handle):
    ins = target(doc, handle)
    if get(ins) is None:
        raise EditError("The reference has no clip boundary.")
    e = doc.drawing.modify(ins.handle)
    e.extra = {k: v for k, v in e.extra.items() if k != "clip"}
    return {"handle": ins.handle, "deleted": True}


def generate(ctx, handle):
    ins = target(ctx.doc, handle)
    clip = get(ins)
    if clip is None:
        raise EditError("The reference has no clip boundary.")
    pl = LwPolyline(vertices=[{"p": [p[0], p[1]], "bulge": 0.0, "sw": 0.0, "ew": 0.0} for p in clip["points"]], closed=True)
    return {"handle": ctx.add(pl)}
