import math
import weakref

from app.doc import curves2d as C
from app.doc import planar as P

STYLE_NORMAL = 0
STYLE_OUTER = 1
STYLE_IGNORE = 2
MAX_LOOPS = 10000
_cache = weakref.WeakKeyDictionary()


def working(doc, handles=None):
    d = doc.drawing
    if handles is not None:
        out = []
        for h in handles:
            e = d.get(h)
            if e is not None and d.visible(e):
                out.append(e)
        return out
    return [e for e in d.entities(doc.current_space) if d.visible(e)]


def prims_for(ents):
    boxes = []
    for e in ents:
        b = e.bounds()
        if b is not None and all(math.isfinite(v) for v in b):
            boxes.append(b)
    reach = C.reach_of(boxes)
    out = []
    for e in ents:
        out.extend(C.prims_of(e, reach))
    return out


def graph_for(doc, boundary, gap):
    key = (doc.rev, doc.current_space, tuple(boundary) if boundary is not None else None, round(gap, 12), len(doc.drawing.ents))
    got = _cache.get(doc)
    if got is not None and got[0] == key:
        return got[1]
    g = P.Graph(prims_for(working(doc, boundary)), gap=gap)
    _cache[doc] = (key, g)
    return g


def rep_point(verts):
    ring = P.flatten_loop(verts)
    n = len(ring)
    for i in range(n):
        a, b = ring[i], ring[(i + 1) % n]
        if math.hypot(b[0] - a[0], b[1] - a[1]) > 1e-12:
            return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
    return ring[0]


def orient(verts, outer):
    area = P.loop_area(verts)
    if (area > 0) != outer:
        return P.reverse_loop(verts)
    return verts


def make_loop(verts, sources, depth):
    outer = depth % 2 == 0
    return {"vertices": orient(verts, outer), "sources": list(sources), "outer": outer, "depth": depth}


def detect_at(doc, pt, style=STYLE_NORMAL, gap=0.0, boundary=None):
    g = graph_for(doc, boundary, gap)
    found = g.face_at(pt[0], pt[1])
    if found is None:
        return []
    seq, _area = found
    verts, sources = g.loop(seq)
    out = [make_loop(verts, sources, 0)]
    if style == STYLE_IGNORE:
        return out
    comp = g.comp[seq[0] >> 1]
    ring = g.sample(seq)
    cands = []
    for c in g.components():
        if c == comp:
            continue
        ol = g.outline(c)
        if ol is None:
            continue
        p0 = g.directed(ol[0][0]).p
        if P.point_in_ring(p0[0], p0[1], ring):
            cands.append((ol[0], g.sample(ol[0])))
    if len(cands) > P.MAX_ISLANDS:
        raise P.TooComplex("Too many islands for boundary detection.")
    for i, (cseq, cr) in enumerate(cands):
        depth = 1
        for j, (_s, other) in enumerate(cands):
            if i != j and P.point_in_ring(cr[0][0], cr[0][1], other):
                depth += 1
        if style == STYLE_OUTER and depth > 1:
            continue
        v, s = g.loop(cseq)
        out.append(make_loop(v, s, depth))
    return out


def loop_key(verts):
    pts = sorted((round(v["p"][0], 7), round(v["p"][1], 7), round(v.get("bulge", 0.0) or 0.0, 6)) for v in verts)
    return tuple(pts)


def rings_depth(loops):
    rings = [(P.flatten_loop(l["vertices"]), rep_point(l["vertices"])) for l in loops]
    depth = []
    for i, (_r, pt) in enumerate(rings):
        d = 0
        for j, (rj, _p) in enumerate(rings):
            if i != j and P.point_in_ring(pt[0], pt[1], rj):
                d += 1
        depth.append(d)
    return depth


def loops_from_objects(ents, style=STYLE_NORMAL, gap=0.0):
    raw = []
    open_ents = []
    for e in ents:
        cl = C.closed_loop_of(e)
        if cl is not None:
            raw.append((cl, [e.handle]))
        elif e.kind == "region":
            for lp in e.loops:
                raw.append(([dict(v) for v in lp.get("vertices", [])], [e.handle]))
        elif e.kind in ("line", "arc", "lwpolyline", "polyline3d", "ellipse", "spline"):
            open_ents.append(e)
    if open_ents:
        g = P.Graph(prims_for(open_ents), gap=gap)
        for c in g.components():
            ol = g.outline(c)
            if ol is None:
                continue
            v, s = g.loop(ol[0])
            raw.append((P.reverse_loop(v), s))
    seen = set()
    uniq = []
    for verts, src in raw:
        if len(verts) < 2:
            continue
        k = loop_key(verts)
        if k in seen:
            continue
        seen.add(k)
        uniq.append((verts, src))
    if len(uniq) > MAX_LOOPS:
        raise P.TooComplex("Too many loops.")
    shaped = [{"vertices": v, "sources": s} for v, s in uniq]
    depth = rings_depth(shaped)
    out = []
    for lp, dp in zip(shaped, depth):
        if style == STYLE_IGNORE and dp > 0:
            continue
        if style == STYLE_OUTER and dp > 1:
            continue
        out.append(make_loop(lp["vertices"], lp["sources"], dp))
    return out


def centroid_of(verts):
    ring = P.flatten_loop(verts)
    return (sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring))


def rebuild_loop(d, handles, gap, near):
    ents = []
    for h in handles:
        e = d.get(h)
        if e is None:
            return None
        ents.append(e)
    if len(ents) == 1:
        cl = C.closed_loop_of(ents[0])
        if cl is not None:
            return cl, [ents[0].handle]
        if ents[0].kind == "region":
            return None
    g = P.Graph(prims_for(ents), gap=gap)
    best = None
    for seq, area in g.faces():
        if area <= 0:
            continue
        v, s = g.loop(seq)
        c = centroid_of(v)
        dist = math.hypot(c[0] - near[0], c[1] - near[1])
        if best is None or dist < best[0]:
            best = (dist, v, s)
    if best is None:
        return None
    return best[1], best[2]
