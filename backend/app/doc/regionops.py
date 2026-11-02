import math

from app.doc import curves2d as C
from app.doc import loops as L
from app.doc import planar as P

UNION = "union"
SUBTRACT = "subtract"
INTERSECT = "intersect"
MAX_LOOPS = 10000


class TooComplexToCombine(Exception):
    pass


def loops_prims(loops, tag, base):
    out = []
    for i, loop in enumerate(loops):
        out.extend(C.polyline_prims(loop.get("vertices", []), True, tag, base + i))
    return out


def rings_of(loops):
    return [P.flatten_loop(loop.get("vertices", [])) for loop in loops]


def inside(rings, x, y):
    hit = False
    for ring in rings:
        if P.point_in_ring(x, y, ring):
            hit = not hit
    return hit


def edge_mid(e):
    if e.kind == "line":
        return ((e.p0[0] + e.p1[0]) / 2.0, (e.p0[1] + e.p1[1]) / 2.0)
    a = e.a0 + e.sw / 2.0
    return (e.c[0] + e.r * math.cos(a), e.c[1] + e.r * math.sin(a))


def edge_key(e, q):
    a, b = (e.n0, e.n1) if e.n0 <= e.n1 else (e.n1, e.n0)
    if e.kind == "line":
        return (a, b, 0)
    m = edge_mid(e)
    return (a, b, 1, round(m[0] / q), round(m[1] / q))


def loop_dir(i, e):
    return 2 * i + 1 if e.rev else 2 * i


def tail_of(g, h):
    e = g.edges[h >> 1]
    return e.n1 if h & 1 else e.n0


def combine_pair(op, a_loops, b_loops):
    prims = loops_prims(a_loops, "a", 0) + loops_prims(b_loops, "b", 10000)
    if len(prims) > P.MAX_PRIMS:
        raise TooComplexToCombine("These regions are too complex to combine.")
    g = P.Graph(prims, prune=False, merge=False)
    ra, rb = rings_of(a_loops), rings_of(b_loops)
    q = g.tol * 50.0
    by_key = {}
    for i, e in enumerate(g.edges):
        by_key.setdefault(edge_key(e, q), []).append(i)
    kept = set()
    for i, e in enumerate(g.edges):
        own = e.src
        other = rb if own == "a" else ra
        mate = None
        for j in by_key.get(edge_key(e, q), ()):
            if j != i and g.edges[j].src != own:
                mate = j
                break
        h = loop_dir(i, e)
        if mate is not None:
            same = tail_of(g, h) == tail_of(g, loop_dir(mate, g.edges[mate]))
            if op == UNION or op == INTERSECT:
                if same and own == "a":
                    kept.add(h)
            elif not same and own == "a":
                kept.add(h)
            continue
        m = edge_mid(e)
        inn = inside(other, m[0], m[1])
        if op == UNION:
            if not inn:
                kept.add(h)
        elif op == INTERSECT:
            if inn:
                kept.add(h)
        elif own == "a":
            if not inn:
                kept.add(h)
        elif inn:
            kept.add(h ^ 1)
    return chain(g, kept)


def chain(g, kept):
    out = []
    used = set()
    for start in sorted(kept):
        if start in used:
            continue
        seq = []
        cur = start
        guard = len(kept) + 2
        while cur not in used and guard > 0:
            used.add(cur)
            seq.append(cur)
            guard -= 1
            lst = g.adj[g.head(cur)]
            i = g.pos[cur ^ 1]
            nxt = None
            for k in range(1, len(lst) + 1):
                cand = lst[(i - k) % len(lst)]
                if cand in kept and cand not in used or cand == start:
                    nxt = cand
                    break
            if nxt is None or nxt == start:
                break
            cur = nxt
        if len(seq) >= 1:
            verts, _src = g.loop(seq)
            if len(verts) >= 2 and abs(P.loop_area(verts)) > 1e-12:
                out.append(verts)
    return out


def shaped(loop_verts):
    raw = [{"vertices": v} for v in loop_verts]
    depth = L.rings_depth(raw)
    return [{"vertices": L.orient(l["vertices"], d % 2 == 0), "outer": d % 2 == 0} for l, d in zip(raw, depth)]


def combine(op, first, others):
    cur = first
    if op == SUBTRACT:
        for other in others:
            cur = shaped(combine_pair(SUBTRACT, cur, other))
            if not cur:
                break
        return cur
    for other in others:
        cur = shaped(combine_pair(op, cur, other))
        if not cur and op == INTERSECT:
            break
    return cur
