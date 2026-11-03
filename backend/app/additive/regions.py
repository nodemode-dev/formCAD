import math

import numpy as np
import pyclipper as pc

S = 10000.0
ARC_TOL = 0.005


def ints(arr) -> list:
    return np.rint(np.asarray(arr, dtype=np.float64) * S).astype(np.int64).tolist()


def floats(path) -> np.ndarray:
    return np.asarray(path, dtype=np.float64).reshape(-1, 2) / S


def clean(paths, dist=0.002) -> list:
    out = []
    d = dist * S
    for p in paths:
        if len(p) < 3:
            continue
        c = pc.CleanPolygon(p, d)
        if len(c) >= 3:
            out.append(c)
    return out


def union(a, b=None) -> list:
    c = pc.Pyclipper()
    if a:
        c.AddPaths(a, pc.PT_SUBJECT, True)
    if b:
        c.AddPaths(b, pc.PT_CLIP, True)
    if not a and not b:
        return []
    return c.Execute(pc.CT_UNION, pc.PFT_NONZERO, pc.PFT_NONZERO)


def diff(a, b) -> list:
    if not a:
        return []
    if not b:
        return union(a)
    c = pc.Pyclipper()
    c.AddPaths(a, pc.PT_SUBJECT, True)
    c.AddPaths(b, pc.PT_CLIP, True)
    return c.Execute(pc.CT_DIFFERENCE, pc.PFT_NONZERO, pc.PFT_NONZERO)


def inter(a, b) -> list:
    if not a or not b:
        return []
    c = pc.Pyclipper()
    c.AddPaths(a, pc.PT_SUBJECT, True)
    c.AddPaths(b, pc.PT_CLIP, True)
    return c.Execute(pc.CT_INTERSECTION, pc.PFT_NONZERO, pc.PFT_NONZERO)


def offset(paths, delta_mm: float, join=pc.JT_ROUND) -> list:
    if not paths:
        return []
    if abs(delta_mm) < 1e-9:
        return union(paths)
    o = pc.PyclipperOffset(2.0, ARC_TOL * S)
    o.AddPaths(paths, join, pc.ET_CLOSEDPOLYGON)
    return o.Execute(delta_mm * S)


def area(paths) -> float:
    return sum(pc.Area(p) for p in paths) / (S * S)


def islands(paths) -> list:
    if not paths:
        return []
    c = pc.Pyclipper()
    c.AddPaths(paths, pc.PT_SUBJECT, True)
    tree = c.Execute2(pc.CT_UNION, pc.PFT_NONZERO, pc.PFT_NONZERO)
    out = []

    def walk(node):
        for ch in node.Childs:
            if not ch.IsHole:
                outer = ch.Contour
                holes = [h.Contour for h in ch.Childs]
                out.append([outer] + holes)
                for h in ch.Childs:
                    walk(h)

    walk(tree)
    return out


def drop_small(paths, min_area_mm2: float) -> list:
    if min_area_mm2 <= 0:
        return paths
    keep = []
    for isl in islands(paths):
        a = abs(pc.Area(isl[0])) - sum(abs(pc.Area(h)) for h in isl[1:])
        if a / (S * S) >= min_area_mm2:
            keep.extend(isl)
    return keep


def clip_lines(lines, region, closed_subject=False) -> list:
    if not lines or not region:
        return []
    c = pc.Pyclipper()
    c.AddPaths(lines, pc.PT_SUBJECT, False)
    c.AddPaths(region, pc.PT_CLIP, True)
    tree = c.Execute2(pc.CT_INTERSECTION, pc.PFT_NONZERO, pc.PFT_NONZERO)
    return pc.OpenPathsFromPolyTree(tree)


def line_inside(p, q, region) -> bool:
    if not region:
        return False
    got = clip_lines([[[int(round(p[0] * S)), int(round(p[1] * S))], [int(round(q[0] * S)), int(round(q[1] * S))]]], region)
    if len(got) != 1:
        return False
    a, b = got[0][0], got[0][-1]
    want = math.hypot((q[0] - p[0]) * S, (q[1] - p[1]) * S)
    return math.hypot(b[0] - a[0], b[1] - a[1]) >= want - 2.0


def point_in(pt, paths) -> bool:
    n = 0
    for p in paths:
        r = pc.PointInPolygon([int(round(pt[0] * S)), int(round(pt[1] * S))], p)
        if r != 0:
            n += 1
    return n % 2 == 1


def perimeter_mm(path) -> float:
    a = np.asarray(path, dtype=np.float64)
    if len(a) < 2:
        return 0.0
    d = np.diff(np.vstack([a, a[:1]]), axis=0)
    return float(np.hypot(d[:, 0], d[:, 1]).sum() / S)
