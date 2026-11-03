import math

from app.doc.entities import Arc, Circle, Line, LwPolyline, Solid, Text
from app.drawann import build

KINDS = ("gdtframe", "datumsym", "balloon", "finishmark", "centermark")


def entities(prims, layer="0", color=256):
    out = []

    def keep(ent):
        ent.layer, ent.color = layer, color
        out.append(ent)

    for p in prims:
        t = p[0]
        if t == "l":
            if math.hypot(p[3] - p[1], p[4] - p[2]) > 1e-9:
                keep(Line(start=[p[1], p[2], 0.0], end=[p[3], p[4], 0.0]))
        elif t == "c":
            keep(Circle(center=[p[1], p[2], 0.0], radius=p[3]))
        elif t == "a":
            keep(Arc(center=[p[1], p[2], 0.0], radius=p[3], start_angle=p[4], end_angle=p[5]))
        elif t == "p":
            keep(LwPolyline.from_points([(x, y) for x, y in p[1]], closed=bool(p[2])))
        elif t == "f":
            pts = [[x, y, 0.0] for x, y in p[1]]
            for i in range(1, len(pts) - 1):
                keep(Solid(corners=[pts[0], pts[i], pts[i + 1]]))
        elif t == "t":
            pos = [p[1], p[2], 0.0]
            hal = {"l": 0, "c": 1, "r": 2}[p[5]]
            keep(Text(position=pos, align_point=list(pos), height=float(p[3]), text=str(p[4]), rotation=float(p[6]), halign=hal, valign=2))
    return out


def parts(e, st=None, d=None):
    prims, _info = build.build(e, st, d)
    return entities(prims, e.layer, e.color)
