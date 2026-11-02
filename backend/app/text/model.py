import math

import numpy as np


class Glyph:
    __slots__ = ("adv", "trail", "strokes", "contours", "tris", "box", "build_tris", "src")

    def __init__(self, adv, trail=0.0, strokes=None, contours=None, tris=None, box=None, build_tris=None):
        self.src = None
        self.adv = adv
        self.trail = trail
        self.strokes = strokes
        self.contours = contours
        self.tris = tris
        self.box = box
        self.build_tris = build_tris

    def triangles(self):
        if self.tris is None and self.build_tris is not None:
            self.tris = self.build_tris(self.contours)
        return self.tris


def box_of(arrays):
    arrays = [a for a in arrays if len(a)]
    if not arrays:
        return (0.0, 0.0, 0.0, 0.0)
    pts = np.vstack(arrays)
    return (float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max()))


def affine(a=1.0, b=0.0, c=0.0, d=1.0, e=0.0, f=0.0):
    return (a, b, c, d, e, f)


def compose(m, n):
    a1, b1, c1, d1, e1, f1 = m
    a2, b2, c2, d2, e2, f2 = n
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def rotation(angle, ox=0.0, oy=0.0):
    c, s = math.cos(angle), math.sin(angle)
    return (c, s, -s, c, ox, oy)


def apply(m, arr):
    a, b, c, d, e, f = m
    out = np.empty_like(arr)
    out[:, 0] = arr[:, 0] * a + arr[:, 1] * c + e
    out[:, 1] = arr[:, 0] * b + arr[:, 1] * d + f
    return out


def flat(arr, digits=6):
    return np.round(arr, digits).ravel().tolist()


class Sink:
    def __init__(self):
        self.lines = []
        self.fills = []
        self.tris = []
        self.points = []

    def stroke(self, arr, closed, ckey, m):
        t = apply(m, arr)
        self.lines.append((t, closed, ckey))
        self.points.append(t)

    def tri(self, arr, ckey, m):
        t = apply(m, arr)
        self.tris.append((t, ckey))
        self.points.append(t)

    def segment(self, x0, y0, x1, y1, ckey, m):
        self.stroke(np.array([[x0, y0], [x1, y1]], dtype=float), False, ckey, m)

    def prims(self, m, digits=6):
        out = []
        for arr, closed, ckey in self.lines:
            p = {"t": "pl", "pts": flat(apply(m, arr), digits), "closed": bool(closed)}
            tag(p, ckey)
            out.append(p)
        grouped = {}
        for arr, ckey in self.tris:
            grouped.setdefault(ckey, []).append(apply(m, arr))
        for ckey, parts in grouped.items():
            p = {"t": "tri", "pts": flat(np.vstack(parts), digits)}
            tag(p, ckey)
            out.append(p)
        return out

    def bounds(self, m):
        if not self.points:
            return None
        pts = np.vstack([apply(m, p) for p in self.points])
        return (float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max()))


def tag(prim, ckey):
    if ckey is None:
        return
    if ckey[0] == "i":
        prim["ci"] = ckey[1]
    else:
        prim["c"] = [ckey[1], ckey[2], ckey[3]]
