import math

import numpy as np

from tests.support.gcode import Program

BOX_FACES = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]


def box_triangles(lo, hi):
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    return [(v[a], v[b], v[c]) for a, b, c in BOX_FACES]


def _ear_clip(poly):
    pts = list(poly)
    if _signed_area(pts) < 0:
        pts.reverse()
    idx = list(range(len(pts)))
    out = []
    while len(idx) > 3:
        for k in range(len(idx)):
            a, b, c = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            pa, pb, pc = pts[a], pts[b], pts[c]
            if (pb[0] - pa[0]) * (pc[1] - pa[1]) - (pb[1] - pa[1]) * (pc[0] - pa[0]) <= 1e-12:
                continue
            if any(_in_triangle(pts[q], pa, pb, pc) for q in idx if q not in (a, b, c)):
                continue
            out.append((a, b, c))
            idx.pop(k)
            break
        else:
            raise ValueError("polygon cannot be triangulated")
    out.append(tuple(idx))
    return pts, out


def _in_triangle(p, a, b, c):
    def s(p1, p2, p3):
        return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])

    d1, d2, d3 = s(p, a, b), s(p, b, c), s(p, c, a)
    return d1 > 0 and d2 > 0 and d3 > 0


def _signed_area(pts):
    return 0.5 * sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))


def prism_triangles(profile_xz, y0, y1):
    pts, tris = _ear_clip(profile_xz)
    out = []
    for a, b, c in tris:
        A, B, C = pts[a], pts[b], pts[c]
        out.append(((A[0], y0, A[1]), (B[0], y0, B[1]), (C[0], y0, C[1])))
        out.append(((A[0], y1, A[1]), (C[0], y1, C[1]), (B[0], y1, B[1])))
    n = len(pts)
    for i in range(n):
        P, Q = pts[i], pts[(i + 1) % n]
        p0, q0, p1, q1 = (P[0], y0, P[1]), (Q[0], y0, Q[1]), (P[0], y1, P[1]), (Q[0], y1, Q[1])
        out.append((p0, q1, q0))
        out.append((p0, p1, q1))
    return out


def stl_text(triangles, name="part"):
    out = ["solid %s" % name]
    for tri in triangles:
        a, b, c = (np.asarray(v, dtype=float) for v in tri)
        n = np.cross(b - a, c - a)
        n = n / (np.linalg.norm(n) or 1.0)
        out += ["facet normal %r %r %r" % tuple(float(x) for x in n), "outer loop"] + ["vertex %r %r %r" % tuple(float(c) for c in v) for v in tri] + ["endloop", "endfacet"]
    out.append("endsolid %s" % name)
    return "\n".join(out) + "\n"


def open_mesh(docs, tmp_path, triangles, name="part"):
    path = tmp_path / ("%s.stl" % name)
    path.write_text(stl_text(triangles, name))
    return docs.open(path)


class Mill:
    def __init__(self, doc, safe=(15.0, 5.0, 2.0), slot=1, machine="mill3", stock=None):
        self.doc = doc
        body = {"machine": machine, "wcs": {"origin_on": "custom", "origin": [0, 0, 0], "slot": slot}, "stock": stock or {"kind": "from_model"}, "safe": {"clearance": safe[0], "retract": safe[1], "feed": safe[2]}}
        self.setup = doc.post("/cam/setups", body)["id"]
        self.safe = safe

    def tool(self, number, kind="flat", diameter=6.0, **extra):
        rec = {"kind": kind, "diameter": diameter, "number": number}
        rec.update(extra)
        return self.doc.post("/cam/tools", {"tool": rec})

    def op(self, kind, tool, geometry=None, params=None, feeds=None, heights=None):
        body = {"type": kind, "setup": self.setup, "tool": tool, "params": params or {}, "feeds": feeds or {"rpm": 10000, "vf_cut": 800, "vf_plunge": 200, "vf_ramp": 400}, "heights": heights or {}}
        if geometry is not None:
            body["geometry"] = geometry
        return self.doc.post("/cam/ops", body)["id"]

    def post(self, post="linuxcnc", ops=None, **options):
        body = {"post": post, "options": options or None}
        if ops:
            body["ops"] = ops
        res = self.doc.post("/cam/preview", body)
        return Program(res["text"]), res["text"]


def at_depth(program, z, tol=1e-6):
    return [m for m in program.cutting() if abs(m.start[2] - z) < tol and abs(m.end[2] - z) < tol]


def sample_points(moves, step_deg=2.0, seg=0.5):
    pts = []
    for m in moves:
        if m.arc:
            pts.extend(Program_points([m], step_deg))
        else:
            n = max(1, int(math.dist(m.start[:2], m.end[:2]) / seg))
            for k in range(n + 1):
                t = k / n
                pts.append(tuple(m.start[i] + (m.end[i] - m.start[i]) * t for i in range(3)))
    return pts


def Program_points(moves, step_deg):
    holder = Program("")
    holder.moves = list(moves)
    return holder.path_points(cutting_only=False, step_deg=step_deg)


def dist_to_segment(p, a, b):
    ax, ay = a[0], a[1]
    dx, dy = b[0] - ax, b[1] - ay
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L))
    return math.hypot(p[0] - ax - t * dx, p[1] - ay - t * dy)


def dist_to_polygon(p, poly):
    return min(dist_to_segment(p, poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly)))


def inside(p, poly):
    x, y = p[0], p[1]
    c = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            c = not c
    return c


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def segments_xy(moves, step_deg=2.0):
    segs = []
    for m in moves:
        pts = Program_points([m], step_deg) if m.arc else [m.start, m.end]
        for a, b in zip(pts, pts[1:]):
            segs.append((a[0], a[1], b[0], b[1]))
    return np.asarray(segs, dtype=float).reshape(-1, 4)


def min_dist_to_segments(points, segs):
    P = np.asarray(points, dtype=float)[:, None, :2]
    A = segs[None, :, 0:2]
    B = segs[None, :, 2:4]
    d = B - A
    L = (d ** 2).sum(axis=2)
    L = np.where(L == 0, 1e-18, L)
    t = np.clip(((P - A) * d).sum(axis=2) / L, 0.0, 1.0)
    proj = A + t[..., None] * d
    return np.sqrt(((P - proj) ** 2).sum(axis=2)).min(axis=1)


def rapids_into_uncut_stock(program, stock_top, tol=1e-6):
    reached = {}
    bad = []
    started = False
    for m in program.moves:
        if not started:
            started = True
            if m.rapid:
                continue
        if m.cutting:
            for p in (m.start, m.end):
                key = (round(p[0], 3), round(p[1], 3))
                reached[key] = min(reached.get(key, math.inf), p[2])
            continue
        lo = min(m.start[2], m.end[2])
        if lo >= stock_top - tol:
            continue
        sideways = math.dist(m.start[:2], m.end[:2]) > tol
        key = (round(m.end[0], 3), round(m.end[1], 3))
        if sideways or reached.get(key, math.inf) > m.end[2] + tol:
            bad.append(m)
    return bad
