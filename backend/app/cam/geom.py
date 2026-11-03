import math

import numpy as np
import pyclipper

from app.cam.limits import CamError

SCALE = 10000.0
JOINS = {"round": pyclipper.JT_ROUND, "miter": pyclipper.JT_MITER, "square": pyclipper.JT_SQUARE}


def to_int(rings) -> list:
    return [[(int(round(p[0] * SCALE)), int(round(p[1] * SCALE))) for p in r] for r in rings if len(r) >= 3]


def from_int(rings) -> list:
    return [[(p[0] / SCALE, p[1] / SCALE) for p in r] for r in rings if len(r) >= 3]


def vertex_count(rings) -> int:
    return sum(len(r) for r in rings)


def normalize(rings) -> list:
    ip = to_int(rings)
    if not ip:
        return []
    try:
        out = pyclipper.SimplifyPolygons(ip, pyclipper.PFT_EVENODD)
    except pyclipper.ClipperException as err:
        raise CamError("The outline cannot be used: %s." % err)
    return from_int(out)


def offset(rings, delta: float, join: str = "round", arc_tol: float = 0.005, miter: float = 2.0) -> list:
    ip = to_int(normalize(rings))
    if not ip:
        return []
    if abs(delta) < 1.0 / SCALE:
        return from_int(ip)
    po = pyclipper.PyclipperOffset(miter, max(1.0, arc_tol * SCALE))
    po.AddPaths(ip, JOINS.get(join, pyclipper.JT_ROUND), pyclipper.ET_CLOSEDPOLYGON)
    out = po.Execute(delta * SCALE)
    return from_int(out)


def boolean(kind: str, subject, clip, rule=pyclipper.PFT_EVENODD) -> list:
    pc = pyclipper.Pyclipper()
    s = to_int(subject)
    c = to_int(clip)
    if s:
        pc.AddPaths(s, pyclipper.PT_SUBJECT, True)
    if c:
        pc.AddPaths(c, pyclipper.PT_CLIP, True)
    if not s:
        return [] if kind != "union" else from_int(pyclipper.SimplifyPolygons(c, rule)) if c else []
    ct = {"union": pyclipper.CT_UNION, "difference": pyclipper.CT_DIFFERENCE, "intersection": pyclipper.CT_INTERSECTION, "xor": pyclipper.CT_XOR}[kind]
    return from_int(pc.Execute(ct, rule, rule))


def union(a, b=None):
    return boolean("union", a, b or [])


def difference(a, b):
    return boolean("difference", a, b)


def intersection(a, b):
    return boolean("intersection", a, b)


def clip_open_lines(lines, region) -> list:
    pc = pyclipper.Pyclipper()
    for ln in lines:
        pc.AddPath([(int(round(p[0] * SCALE)), int(round(p[1] * SCALE))) for p in ln], pyclipper.PT_SUBJECT, False)
    pc.AddPaths(to_int(region), pyclipper.PT_CLIP, True)
    tree = pc.Execute2(pyclipper.CT_INTERSECTION, pyclipper.PFT_EVENODD, pyclipper.PFT_EVENODD)
    out = []
    for p in pyclipper.OpenPathsFromPolyTree(tree):
        out.append([(q[0] / SCALE, q[1] / SCALE) for q in p])
    return out


def area(ring) -> float:
    a = np.asarray(ring, dtype=float)
    x, y = a[:, 0], a[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def is_ccw(ring) -> bool:
    return area(ring) > 0


def length(ring, closed=True) -> float:
    a = np.asarray(ring, dtype=float)
    if closed:
        a = np.vstack([a, a[:1]])
    return float(np.hypot(*np.diff(a, axis=0).T).sum())


def bounds(rings):
    a = np.vstack([np.asarray(r, dtype=float) for r in rings if len(r)])
    return float(a[:, 0].min()), float(a[:, 1].min()), float(a[:, 0].max()), float(a[:, 1].max())


def inside(point, rings) -> bool:
    ip = (int(round(point[0] * SCALE)), int(round(point[1] * SCALE)))
    n = 0
    for r in to_int(rings):
        v = pyclipper.PointInPolygon(ip, r)
        if v == -1:
            return True
        n += v
    return n % 2 == 1


def rotate_to(ring, point):
    a = np.asarray(ring, dtype=float)
    d = np.hypot(a[:, 0] - point[0], a[:, 1] - point[1])
    i = int(np.argmin(d))
    return [tuple(p) for p in np.roll(a, -i, axis=0)]


def reverse(ring) -> list:
    return list(reversed(ring))


def simplify(points, tol: float) -> list:
    a = np.asarray(points, dtype=float)
    n = len(a)
    if n < 3:
        return [tuple(p) for p in a]
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        p, q = a[i], a[j]
        seg = q - p
        ln = math.hypot(seg[0], seg[1])
        mid = a[i + 1 : j]
        if ln < 1e-12:
            d = np.hypot(mid[:, 0] - p[0], mid[:, 1] - p[1])
        else:
            d = np.abs(seg[0] * (mid[:, 1] - p[1]) - seg[1] * (mid[:, 0] - p[0])) / ln
        k = int(np.argmax(d))
        if d[k] > tol:
            m = i + 1 + k
            keep[m] = True
            stack.append((i, m))
            stack.append((m, j))
    return [tuple(p) for p in a[keep]]


def circle_ring(cx: float, cy: float, r: float, tol: float = 0.01, ccw: bool = True) -> list:
    n = max(16, int(math.ceil(math.pi / math.acos(max(0.0, 1.0 - tol / max(r, tol * 2))))))
    n = min(n, 720)
    ang = np.linspace(0.0, 2.0 * math.pi, n, endpoint=False)
    if not ccw:
        ang = -ang
    return [(cx + r * math.cos(t), cy + r * math.sin(t)) for t in ang]


def nearest_vertex_distance(rings, point) -> float:
    best = float("inf")
    for r in rings:
        a = np.asarray(r, dtype=float)
        d = np.hypot(a[:, 0] - point[0], a[:, 1] - point[1]).min()
        best = min(best, float(d))
    return best


def rect_ring(x0, y0, x1, y1) -> list:
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


class Region:
    def __init__(self, rings=None):
        self.rings = normalize(rings) if rings else []

    def empty(self) -> bool:
        return not self.rings

    def offset(self, delta, join="round", arc_tol=0.005):
        return Region(offset(self.rings, delta, join, arc_tol))

    def bounds(self):
        return bounds(self.rings) if self.rings else None

    def outer_rings(self) -> list:
        return [r for r in self.rings if is_ccw(r)]

    def hole_rings(self) -> list:
        return [r for r in self.rings if not is_ccw(r)]

    def contains(self, p) -> bool:
        return inside(p, self.rings)
