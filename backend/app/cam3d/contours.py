import numpy as np

from app.cam3d import pushcutter

SEG = {
    1: (("B", "L"),), 2: (("R", "B"),), 4: (("T", "R"),), 8: (("L", "T"),),
    3: (("R", "L"),), 6: (("T", "B"),), 12: (("L", "R"),), 9: (("B", "T"),),
    14: (("L", "B"),), 13: (("B", "R"),), 11: (("R", "T"),), 7: (("T", "L"),),
    5: (("B", "L"), ("T", "R")), 10: (("R", "B"), ("L", "T")),
}


def inside(iv, v, eps=1e-9):
    if len(iv) == 0:
        return False
    k = np.searchsorted(iv[:, 0], v + eps, side="right") - 1
    return k >= 0 and v <= iv[k, 1] + eps


def weave_loops(surface, cu, z, bounds, step, cancel=None):
    x0, y0, x1, y1 = bounds
    nx = max(int(np.ceil((x1 - x0) / step)), 2) + 1
    ny = max(int(np.ceil((y1 - y0) / step)), 2) + 1
    xs = np.linspace(x0, x1, nx)
    ys = np.linspace(y0, y1, ny)
    ivx = pushcutter.fibers(surface, cu, z, 0, ys, x0 - 1.0, x1 + 1.0, cancel)
    ivy = pushcutter.fibers(surface, cu, z, 1, xs, y0 - 1.0, y1 + 1.0, cancel)
    occ = np.zeros((nx, ny), dtype=bool)
    for j in range(ny):
        iv = ivx[j]
        if len(iv):
            k = np.searchsorted(iv[:, 0], xs + 1e-9, side="right") - 1
            kk = np.clip(k, 0, len(iv) - 1)
            occ[:, j] = (k >= 0) & (xs <= iv[kk, 1] + 1e-9)
    cross = {}

    def hx(i, j):
        key = ("h", i, j)
        if key in cross:
            return cross[key]
        a, b = xs[i], xs[i + 1]
        iv = ivx[j]
        val = None
        for lo, hi in iv:
            if occ[i, j] != occ[i + 1, j]:
                cand = hi if occ[i, j] else lo
                if a - 1e-9 <= cand <= b + 1e-9:
                    val = cand
                    break
        if val is None:
            val = (a + b) / 2.0
        cross[key] = (val, ys[j])
        return cross[key]

    def vy(i, j):
        key = ("v", i, j)
        if key in cross:
            return cross[key]
        a, b = ys[j], ys[j + 1]
        iv = ivy[i]
        val = None
        for lo, hi in iv:
            if occ[i, j] != occ[i, j + 1]:
                cand = hi if occ[i, j] else lo
                if a - 1e-9 <= cand <= b + 1e-9:
                    val = cand
                    break
        if val is None:
            val = (a + b) / 2.0
        cross[key] = (xs[i], val)
        return cross[key]

    return march(occ, lambda key: hx(key[1], key[2]) if key[0] == "h" else vy(key[1], key[2]))


def march(occ, point):
    nxt = {}
    mask = occ[:-1, :-1].astype(np.int8) | (occ[1:, :-1].astype(np.int8) << 1) | (occ[1:, 1:].astype(np.int8) << 2) | (occ[:-1, 1:].astype(np.int8) << 3)
    ci, cj = np.nonzero((mask != 0) & (mask != 15))
    for i, j in zip(ci.tolist(), cj.tolist()):
        for a, b in SEG[int(mask[i, j])]:
            ka = {"B": ("h", i, j), "T": ("h", i, j + 1), "L": ("v", i, j), "R": ("v", i + 1, j)}[a]
            kb = {"B": ("h", i, j), "T": ("h", i, j + 1), "L": ("v", i, j), "R": ("v", i + 1, j)}[b]
            nxt.setdefault(ka, []).append(kb)
    targets = {v for outs in nxt.values() for v in outs}
    order = [k for k in nxt if k not in targets] + [k for k in nxt if k in targets]
    loops = []
    used = set()
    for start in order:
        if start in used:
            continue
        chain = [start]
        used.add(start)
        cur = start
        closed = False
        while True:
            outs = nxt.get(cur)
            if not outs:
                break
            n = outs[0]
            if n == start:
                closed = True
                break
            if n in used:
                break
            used.add(n)
            chain.append(n)
            cur = n
        loops.append((np.array([point(k) for k in chain]), closed))
    return loops


def field_loops(field, level, xs, ys):
    f = np.where(np.isfinite(field), field, -1e30)
    occ = f > level
    cache = {}

    def point(key):
        if key in cache:
            return cache[key]
        kind, i, j = key
        if kind == "h":
            f0, f1 = f[i, j], f[i + 1, j]
            t = 0.5 if f0 == f1 else (level - f0) / (f1 - f0)
            t = min(max(t, 0.0), 1.0)
            p = (xs[i] + (xs[i + 1] - xs[i]) * t, ys[j])
        else:
            f0, f1 = f[i, j], f[i, j + 1]
            t = 0.5 if f0 == f1 else (level - f0) / (f1 - f0)
            t = min(max(t, 0.0), 1.0)
            p = (xs[i], ys[j] + (ys[j + 1] - ys[j]) * t)
        cache[key] = p
        return p

    return march(occ, point)


def simplify2(pts, tol, closed):
    n = len(pts)
    if n < 4 or tol <= 0:
        return pts
    keep = np.zeros(n, dtype=bool)
    keep[0] = True
    keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        p = pts[a + 1:b]
        d = pts[b] - pts[a]
        ln = np.hypot(d[0], d[1])
        if ln < 1e-12:
            dist = np.hypot(p[:, 0] - pts[a, 0], p[:, 1] - pts[a, 1])
        else:
            dist = np.abs(d[0] * (p[:, 1] - pts[a, 1]) - d[1] * (p[:, 0] - pts[a, 0])) / ln
        k = int(np.argmax(dist))
        if dist[k] > tol:
            keep[a + 1 + k] = True
            stack.append((a, a + 1 + k))
            stack.append((a + 1 + k, b))
    return pts[keep]


def simplify3(pts, tol):
    n = len(pts)
    if n < 3 or tol <= 0:
        return pts
    keep = np.zeros(n, dtype=bool)
    keep[0] = True
    keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        p = pts[a + 1:b]
        d = pts[b] - pts[a]
        ln = np.linalg.norm(d)
        if ln < 1e-12:
            dist = np.linalg.norm(p - pts[a], axis=1)
        else:
            dist = np.linalg.norm(np.cross(p - pts[a], d / ln), axis=1)
        k = int(np.argmax(dist))
        if dist[k] > tol:
            keep[a + 1 + k] = True
            stack.append((a, a + 1 + k))
            stack.append((a + 1 + k, b))
    return pts[keep]
