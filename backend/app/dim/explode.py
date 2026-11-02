import math

from app.dim import regen
from app.dim import vars as DV
from app.doc.entities import Arc, Circle, Line, LwPolyline, Solid, Text

COLOR = {"dim": "DIMCLRD", "arrow": "DIMCLRD", "ext1": "DIMCLRE", "ext2": "DIMCLRE", "text": "DIMCLRT"}
WEIGHT = {"dim": "DIMLWD", "arrow": "DIMLWD", "ext1": "DIMLWE", "ext2": "DIMLWE"}
LTYPE = {"dim": "DIMLTYPE", "ext1": "DIMLTEX1", "ext2": "DIMLTEX2"}


def _style_of(doc, dim, V, role, ent):
    ent.layer = dim.layer
    ent.transparency = dim.transparency
    ent.plot_style = dim.plot_style
    ent.ltscale = dim.ltscale
    col = V.get(COLOR.get(role, "DIMCLRD"), 0)
    ent.color = dim.color if (col == 0) else col
    if role != "text":
        lw = int(V.get(WEIGHT.get(role, "DIMLWD"), -2))
        ent.lineweight = dim.lineweight if lw == -2 else lw
        lt = str(V.get(LTYPE.get(role, ""), "") or "")
        if lt and lt.casefold() != "byblock" and doc.drawing.table_get("linetypes", lt) is not None:
            ent.linetype = lt
        else:
            ent.linetype = dim.linetype
    else:
        ent.lineweight = dim.lineweight
        ent.linetype = dim.linetype
    ent.owner = dim.owner
    return ent


def _z(p):
    return [float(p[0]), float(p[1]), 0.0]


def parts(doc, dim):
    out, V, S = regen.generate(doc, dim)
    res = []

    def add(ent, role):
        res.append(_style_of(doc, dim, V, role, ent))

    for p, q, role in out.segs:
        add(Line(start=_z(p), end=_z(q)), role)
    for c, r, a0, sw, role in out.arcs:
        if sw >= 2 * math.pi - 1e-9:
            add(Circle(center=_z(c), radius=float(r)), role)
        else:
            add(Arc(center=_z(c), radius=float(r), start_angle=a0 % (2 * math.pi), end_angle=(a0 + sw) % (2 * math.pi)), role)
    for pts, closed, role in out.polys:
        add(LwPolyline(vertices=[{"p": [float(p[0]), float(p[1])], "bulge": 0.0} for p in pts], closed=bool(closed)), role)
    for c, r, filled, role in out.circles:
        if filled:
            add(LwPolyline(vertices=[{"p": [c[0] - r / 2.0, c[1]], "bulge": 1.0}, {"p": [c[0] + r / 2.0, c[1]], "bulge": 1.0}], closed=True, const_width=float(r)), role)
        else:
            add(Circle(center=_z(c), radius=float(r)), role)
    for pts, role in out.fills:
        if len(pts) == 3:
            add(Solid(corners=[_z(p) for p in pts]), role)
        elif len(pts) == 4:
            add(Solid(corners=[_z(pts[0]), _z(pts[1]), _z(pts[3]), _z(pts[2])]), role)
        else:
            add(LwPolyline(vertices=[{"p": [float(p[0]), float(p[1])], "bulge": 0.0} for p in pts], closed=True), role)
    for b in out.blocks:
        for text, cx, cy, h in b.parts:
            at = b.to_world(cx, cy)
            add(Text(position=_z(at), align_point=_z(at), height=float(h), text=text, rotation=b.rot, style=str(V.get("DIMTXSTY") or "Standard"), halign=1, valign=2), "text")
        for x0, y0, x1, y1 in b.lines:
            p, q = b.to_world(x0, y0), b.to_world(x1, y1)
            add(Line(start=_z(p), end=_z(q)), "text")
        for cx, cy, r, a0, a1 in b.arcs:
            c = b.to_world(cx, cy)
            add(Arc(center=_z(c), radius=float(r), start_angle=(a0 + b.rot) % (2 * math.pi), end_angle=(a1 + b.rot) % (2 * math.pi)), "text")
    return res
