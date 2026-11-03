import math
import os

from app.cutting import shapes as S
from app.cutting.shapes import CutError

MAX_DXF_BYTES = 30 * 1024 * 1024
MAX_ENTITIES = 200000


def parts_from_raw(raw_loops, name, qty=1, qty_by_handle=None):
    groups = S.group_loops(raw_loops)
    out = []
    for i, g in enumerate(groups):
        h = g.get("handle")
        nm = name if len(groups) == 1 else ("%s %s" % (name, h) if h is not None else "%s %d" % (name, i + 1))
        q = qty
        if qty_by_handle and h is not None and str(h) in qty_by_handle:
            q = int(qty_by_handle[str(h)])
        if q < 1:
            continue
        out.append({"name": nm, "qty": q, "loops": g["loops"], "handle": h})
    return out


def lw_points(vertices, closed, tol=S.FLATTEN_TOL):
    pts = []
    n = len(vertices)
    count = n if closed else n - 1
    for i in range(max(count, 0)):
        a = vertices[i]
        b = vertices[(i + 1) % n]
        pts.extend(S.bulge_points(tuple(a["p"][:2]), tuple(b["p"][:2]), a.get("bulge", 0.0) or 0.0, tol))
    return pts


def from_entities(d, layer=None, qty=1, qty_by_handle=None):
    raw = []
    count = 0
    for e in d.ents.values():
        if layer and e.layer != layer:
            continue
        if e.kind == "lwpolyline" and e.closed and len(e.vertices) >= 3:
            pts = lw_points(e.vertices, True)
            if len(pts) >= 3:
                raw.append({"pts": pts, "circle": None, "handle": e.handle})
        elif e.kind == "circle" and e.radius > 1e-6:
            c = [float(e.center[0]), float(e.center[1])]
            raw.append({"pts": S.circle_points(c, float(e.radius)), "circle": {"c": c, "r": float(e.radius)}, "handle": e.handle})
        else:
            continue
        count += 1
        if count > MAX_ENTITIES:
            raise CutError("The drawing has more than %d closed outlines." % MAX_ENTITIES)
    if not raw:
        raise CutError("The drawing has no closed polylines or circles%s." % (" on layer %s" % layer if layer else ""))
    return parts_from_raw(raw, "Outline", qty, qty_by_handle)


def from_flat(d, handle=None, qty=1):
    from app.sheetmetal import flat

    try:
        data = flat.compute(d, handle)
    except Exception as err:
        raise CutError("The flat pattern is not available: %s" % err)
    loops = []
    for lp in data["loops"]:
        loops.append({"segs": lp["segs"], "outer": bool(lp.get("outer", True))})
    if not loops:
        raise CutError("The flat pattern has no outline.")
    name = (data.get("material") and "Flat %s" % data["material"]) or "Flat pattern"
    return [{"name": name, "qty": qty, "loops": loops, "source": "flat"}]


def from_dxf(path, qty=1):
    import ezdxf

    full = os.path.abspath(os.path.expanduser(str(path)))
    if not os.path.isfile(full):
        raise CutError("The file %s does not exist." % os.path.basename(full))
    if os.path.getsize(full) > MAX_DXF_BYTES:
        raise CutError("The file is larger than %d MB." % (MAX_DXF_BYTES // (1024 * 1024)))
    if os.path.splitext(full)[1].lower() != ".dxf":
        raise CutError("Only DXF files are read here.")
    try:
        doc = ezdxf.readfile(full)
    except Exception as err:
        raise CutError("The DXF file could not be read: %s" % err)
    raw = []
    n = 0
    for e in doc.modelspace():
        t = e.dxftype()
        n += 1
        if n > MAX_ENTITIES:
            raise CutError("The file has more than %d entities." % MAX_ENTITIES)
        if t == "LWPOLYLINE" and e.closed:
            verts = [{"p": (p[0], p[1]), "bulge": p[4]} for p in e.get_points("xyseb")]
            pts = lw_points(verts, True)
            if len(pts) >= 3:
                raw.append({"pts": pts, "circle": None})
        elif t == "CIRCLE":
            c = [float(e.dxf.center.x), float(e.dxf.center.y)]
            r = float(e.dxf.radius)
            raw.append({"pts": S.circle_points(c, r), "circle": {"c": c, "r": r}})
    if not raw:
        raise CutError("The file has no closed polylines or circles.")
    return parts_from_raw(raw, os.path.splitext(os.path.basename(full))[0], qty)
