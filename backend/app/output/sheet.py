import math
from collections import namedtuple

import numpy as np

PT_PER_MM = 72.0 / 25.4
MAX_OPS = 4000000

Style = namedtuple("Style", "rgb alpha width cap join dash layer")


class Sheet:
    def __init__(self, name, width, height, printable):
        self.name = str(name)
        self.width = float(width)
        self.height = float(height)
        self.printable = [float(v) for v in printable]
        self.ops = []
        self.layers = {}
        self.links = []
        self.empty = True

    def layer(self, name, on=True):
        key = str(name).casefold()
        if key not in self.layers:
            self.layers[key] = [str(name), bool(on)]
        return key

    def stroke(self, pts, closed, style):
        self.empty = False
        self.ops.append(("S", pts, closed, style))

    def fill(self, rings, style, evenodd=True):
        self.empty = False
        self.ops.append(("F", rings, style, evenodd))

    def text(self, font, glyphs, style):
        self.empty = False
        self.ops.append(("T", font, glyphs, style))

    def push_clip(self, rings, evenodd=False):
        self.ops.append(("C", rings, evenodd))

    def pop_clip(self):
        self.ops.append(("E",))

    def link(self, rect, url):
        self.links.append((rect, url))


def canon_dash(pattern, scale):
    out = []
    for v in pattern:
        v = float(v) * scale
        on = v >= 0
        n = abs(v)
        if out and out[-1][0] == on and (n > 0 and out[-1][1] > 0 or not on):
            out[-1][1] += n
        else:
            if out and out[-1][0] == on:
                out.append([not on, 0.0])
            out.append([on, n])
    if len(out) > 1 and out[0][0] == out[-1][0] and out[0][1] > 0 and out[-1][1] > 0:
        out[0][1] += out[-1][1]
        out.pop()
    if not out:
        return None
    if out[0][0] is False:
        out.append(out.pop(0))
        lead = out[-1][1]
    else:
        lead = 0.0
    if len(out) % 2:
        out.append([False, 0.0])
    arr = [x[1] for x in out]
    total = sum(arr)
    if total <= 0 or all(not x[0] or x[1] == 0 for x in out[0::2]) and all(x[1] == 0 for x in out):
        return None
    phase = (total - lead) % total if lead else 0.0
    return tuple(arr), phase


def dash_pieces(pts, closed, arr, phase):
    p = np.asarray(pts, dtype=float)
    if closed and len(p) >= 2:
        p = np.vstack([p, p[:1]])
    if len(p) < 2:
        return [], []
    total = sum(arr)
    if total <= 0:
        return [p], []
    seg = np.hypot(np.diff(p[:, 0]), np.diff(p[:, 1]))
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    length = cum[-1]
    pieces = []
    dots = []
    pos = -(phase % total)
    n = len(arr)
    i = 0
    budget = 200000
    while pos < length and budget > 0:
        budget -= 1
        a = arr[i % n]
        if i % 2 == 0:
            s, e = max(pos, 0.0), min(pos + a, length)
            if a == 0:
                if 0.0 <= pos <= length:
                    dots.append(_at(p, cum, pos))
            elif e > s:
                pieces.append(_slice(p, cum, s, e))
        pos += a
        i += 1
        if total == 0:
            break
    return pieces, dots


def _at(p, cum, d):
    k = int(np.searchsorted(cum, d, side="right")) - 1
    k = max(0, min(k, len(p) - 2))
    seg = cum[k + 1] - cum[k]
    t = 0.0 if seg <= 0 else (d - cum[k]) / seg
    return p[k] + (p[k + 1] - p[k]) * t


def _slice(p, cum, s, e):
    a = _at(p, cum, s)
    b = _at(p, cum, e)
    lo = int(np.searchsorted(cum, s, side="right"))
    hi = int(np.searchsorted(cum, e, side="left"))
    mid = p[lo:hi]
    return np.vstack([a[None, :], mid, b[None, :]]) if len(mid) else np.vstack([a[None, :], b[None, :]])


def clip_polyline(pts, rect):
    p = np.asarray(pts, dtype=float)
    if len(p) < 2:
        return []
    x0, y0, x1, y1 = rect
    lo = p.min(axis=0)
    hi = p.max(axis=0)
    if lo[0] >= x0 and lo[1] >= y0 and hi[0] <= x1 and hi[1] <= y1:
        return [(p, 0.0)]
    if hi[0] < x0 or hi[1] < y0 or lo[0] > x1 or lo[1] > y1:
        return []
    a = p[:-1]
    b = p[1:]
    d = b - a
    t0 = np.zeros(len(a))
    t1 = np.ones(len(a))
    ok = np.ones(len(a), dtype=bool)
    for ax, lim_lo, lim_hi in ((0, x0, x1), (1, y0, y1)):
        dd = d[:, ax]
        with np.errstate(divide="ignore", invalid="ignore"):
            ta = (lim_lo - a[:, ax]) / dd
            tb = (lim_hi - a[:, ax]) / dd
        tmin = np.where(dd == 0, -np.inf, np.minimum(ta, tb))
        tmax = np.where(dd == 0, np.inf, np.maximum(ta, tb))
        par_ok = (a[:, ax] >= lim_lo) & (a[:, ax] <= lim_hi)
        ok &= np.where(dd == 0, par_ok, True)
        t0 = np.maximum(t0, tmin)
        t1 = np.minimum(t1, tmax)
    ok &= t0 < t1
    seglen = np.hypot(d[:, 0], d[:, 1])
    cum = np.concatenate([[0.0], np.cumsum(seglen)])
    out = []
    cur = None
    start = 0.0
    idx = np.nonzero(ok)[0]
    last = -2
    last_end = False
    for i in idx:
        pa = a[i] + d[i] * t0[i]
        pb = a[i] + d[i] * t1[i]
        joined = cur is not None and i == last + 1 and t0[i] <= 1e-12 and last_end
        if not joined:
            if cur is not None:
                out.append((np.array(cur), start))
            cur = [pa, pb]
            start = cum[i] + seglen[i] * t0[i]
        else:
            cur.append(pb)
        last = i
        last_end = t1[i] >= 1.0 - 1e-12
    if cur is not None:
        out.append((np.array(cur), start))
    return out


def clip_ring(ring, rect):
    pts = [tuple(q) for q in np.asarray(ring, dtype=float)]
    x0, y0, x1, y1 = rect
    edges = (
        (lambda q: q[0] >= x0, lambda a, b: (x0, a[1] + (b[1] - a[1]) * (x0 - a[0]) / (b[0] - a[0]))),
        (lambda q: q[0] <= x1, lambda a, b: (x1, a[1] + (b[1] - a[1]) * (x1 - a[0]) / (b[0] - a[0]))),
        (lambda q: q[1] >= y0, lambda a, b: (a[0] + (b[0] - a[0]) * (y0 - a[1]) / (b[1] - a[1]), y0)),
        (lambda q: q[1] <= y1, lambda a, b: (a[0] + (b[0] - a[0]) * (y1 - a[1]) / (b[1] - a[1]), y1)),
    )
    for inside, cut in edges:
        if not pts:
            break
        out = []
        prev = pts[-1]
        for cur in pts:
            if inside(cur):
                if not inside(prev):
                    out.append(cut(prev, cur))
                out.append(cur)
            elif inside(prev):
                out.append(cut(prev, cur))
            prev = cur
        pts = out
    return np.array(pts) if len(pts) >= 3 else None


def rect_ring(rect):
    x0, y0, x1, y1 = rect
    return np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=float)


def ring_area(ring):
    r = np.asarray(ring, dtype=float)
    x, y = r[:, 0], r[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def point_in_rings(x, y, rings):
    hit = False
    for r in rings:
        n = len(r)
        j = n - 1
        for i in range(n):
            xi, yi = r[i][0], r[i][1]
            xj, yj = r[j][0], r[j][1]
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                hit = not hit
            j = i
    return hit
