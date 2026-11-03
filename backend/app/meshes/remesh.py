import math

import numpy as np

from app.meshes import core, spatial
from app.meshes.core import Mesh, MeshError
from app.meshes.jobs import QUIET

SPLIT = 4.0 / 3.0
COLLAPSE = 4.0 / 5.0
MAX_ITERATIONS = 20


def key(a, b):
    return (a, b) if a < b else (b, a)


def sub(p, q):
    return (p[0] - q[0], p[1] - q[1], p[2] - q[2])


def cross(u, v):
    return (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])


def dot(u, v):
    return u[0] * v[0] + u[1] * v[1] + u[2] * v[2]


def unit_normal(p, q, r):
    n = cross(sub(q, p), sub(r, p))
    ln = math.sqrt(dot(n, n))
    if ln < 1e-300:
        return None, 0.0
    return (n[0] / ln, n[1] / ln, n[2] / ln), ln * 0.5


def third(tri, a, b):
    x, y, z = tri
    if x == a and y == b:
        return z
    if y == a and z == b:
        return x
    if z == a and x == b:
        return y
    return None


class Soup:
    def __init__(self, m: Mesh, feature_deg: float, lock_boundary: bool):
        self.P = [tuple(p) for p in m.v.tolist()]
        self.T = [tuple(t) for t in m.t.tolist()]
        self.VT = [set() for _ in self.P]
        self.ET = {}
        self.FN = [set() for _ in self.P]
        self.lock_boundary = lock_boundary
        self.boundary = set()
        for ti, t in enumerate(self.T):
            self.register(ti)
        bad = [k for k, v in self.ET.items() if len(v) > 2]
        if bad:
            raise MeshError("The mesh has %d non-manifold edges; repair it before remeshing." % len(bad))
        self.find_features(m, feature_deg)

    def register(self, ti):
        a, b, c = self.T[ti]
        for u, v in ((a, b), (b, c), (c, a)):
            self.ET.setdefault(key(u, v), []).append(ti)
        for v in (a, b, c):
            self.VT[v].add(ti)

    def unregister(self, ti):
        a, b, c = self.T[ti]
        for u, v in ((a, b), (b, c), (c, a)):
            k = key(u, v)
            lst = self.ET.get(k)
            if lst is not None:
                lst.remove(ti)
                if not lst:
                    del self.ET[k]
        for v in (a, b, c):
            self.VT[v].discard(ti)

    def add_tri(self, a, b, c):
        self.T.append((a, b, c))
        self.register(len(self.T) - 1)

    def drop_tri(self, ti):
        self.unregister(ti)
        self.T[ti] = None

    def add_vertex(self, p):
        self.P.append(p)
        self.VT.append(set())
        self.FN.append(set())
        return len(self.P) - 1

    def set_feature(self, a, b):
        self.FN[a].add(b)
        self.FN[b].add(a)

    def clear_feature(self, a, b):
        self.FN[a].discard(b)
        self.FN[b].discard(a)

    def is_feature(self, a, b):
        return b in self.FN[a]

    def find_features(self, m, feature_deg):
        fn = core.triangle_normals(m)
        cos_limit = math.cos(math.radians(feature_deg)) if feature_deg > 0 else -2.0
        for k, tris in self.ET.items():
            if len(tris) == 1:
                self.set_feature(*k)
                self.boundary.add(k)
            elif feature_deg > 0 and float(np.dot(fn[tris[0]], fn[tris[1]])) < cos_limit:
                self.set_feature(*k)

    def length(self, a, b):
        return math.dist(self.P[a], self.P[b])

    def split(self, a, b):
        k = key(a, b)
        tris = list(self.ET[k])
        pa, pb = self.P[a], self.P[b]
        mid = self.add_vertex(((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2, (pa[2] + pb[2]) / 2))
        feat = self.is_feature(a, b)
        if feat:
            self.clear_feature(a, b)
            self.set_feature(a, mid)
            self.set_feature(mid, b)
            if k in self.boundary:
                self.boundary.discard(k)
                self.boundary.add(key(a, mid))
                self.boundary.add(key(mid, b))
        for t in tris:
            tri = self.T[t]
            for u, v in ((a, b), (b, a)):
                r = third(tri, u, v)
                if r is not None:
                    self.drop_tri(t)
                    self.add_tri(u, mid, r)
                    self.add_tri(mid, v, r)
                    break
        return mid

    def neighbours(self, v):
        out = set()
        for t in self.VT[v]:
            out.update(self.T[t])
        out.discard(v)
        return out

    def collapse_plan(self, u, v, limit):
        k = key(u, v)
        etris = self.ET.get(k)
        if not etris:
            return None
        feat = self.is_feature(u, v)
        fu, fv = len(self.FN[u]), len(self.FN[v])
        if feat:
            if k in self.boundary and self.lock_boundary:
                return None
            if fv != 2:
                return None
            newpos = self.P[u]
        else:
            if fu and fv:
                return None
            if fv:
                return None
            if fu:
                newpos = self.P[u]
            else:
                a, b = self.P[u], self.P[v]
                newpos = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2)
        opposite = set()
        for t in etris:
            opposite.add(next(x for x in self.T[t] if x != u and x != v))
        if self.neighbours(u) & self.neighbours(v) != opposite:
            return None
        if feat:
            for w in self.FN[v]:
                if w != u and self.is_feature(u, w):
                    return None
        skip = set(etris)
        for moved, other in ((v, u), (u, v)):
            if moved == u and newpos == self.P[u]:
                continue
            for t in self.VT[moved]:
                if t in skip:
                    continue
                tri = self.T[t]
                old = [self.P[x] for x in tri]
                new = [newpos if x == moved else (newpos if x == other else self.P[x]) for x in tri]
                n0, a0 = unit_normal(*old)
                n1, a1 = unit_normal(*new)
                if n0 is None or n1 is None or dot(n0, n1) < 0.2:
                    return None
                for x in tri:
                    if x != moved and x != other and math.dist(newpos, self.P[x]) > limit:
                        return None
        return newpos

    def collapse(self, u, v, newpos):
        k = key(u, v)
        etris = list(self.ET[k])
        for t in etris:
            self.drop_tri(t)
        for t in list(self.VT[v]):
            a, b, c = self.T[t]
            self.drop_tri(t)
            self.add_tri(*[u if x == v else x for x in (a, b, c)])
        for w in list(self.FN[v]):
            self.clear_feature(v, w)
            if w != u:
                self.set_feature(u, w)
        if k in self.boundary:
            self.boundary.discard(k)
        for bk in [b for b in self.boundary if v in b]:
            self.boundary.discard(bk)
            other = bk[0] if bk[1] == v else bk[1]
            self.boundary.add(key(u, other))
        self.P[u] = newpos

    def valence_target(self, v):
        return 4 if self.FN[v] and any(key(v, w) in self.boundary for w in self.FN[v]) else 6

    def try_flip(self, a, b):
        k = key(a, b)
        tris = self.ET.get(k)
        if not tris or len(tris) != 2 or self.is_feature(a, b):
            return False
        t1, t2 = tris
        c = third(self.T[t1], a, b)
        if c is None:
            t1, t2 = t2, t1
            c = third(self.T[t1], a, b)
        d = third(self.T[t2], b, a)
        if c is None or d is None or c == d or key(c, d) in self.ET:
            return False
        val = lambda x: len(self.neighbours(x))
        before = sum(abs(val(x) - self.valence_target(x)) for x in (a, b, c, d))
        after = sum(abs(val(x) + dv - self.valence_target(x)) for x, dv in ((a, -1), (b, -1), (c, 1), (d, 1)))
        if after >= before:
            return False
        P = self.P
        n_old1, _ = unit_normal(P[a], P[b], P[c])
        n_old2, _ = unit_normal(P[b], P[a], P[d])
        n1, a1 = unit_normal(P[c], P[a], P[d])
        n2, a2 = unit_normal(P[c], P[d], P[b])
        if None in (n_old1, n_old2, n1, n2):
            return False
        if dot(n1, n_old1) < 0.5 or dot(n2, n_old1) < 0.5 or dot(n1, n_old2) < 0.5 or dot(n2, n_old2) < 0.5:
            return False
        self.drop_tri(t1)
        self.drop_tri(t2)
        self.add_tri(c, a, d)
        self.add_tri(c, d, b)
        return True

    def arrays(self):
        alive = [i for i, t in enumerate(self.T) if t is not None]
        tri = np.array([self.T[i] for i in alive], dtype=np.int64).reshape(-1, 3)
        return np.array(self.P, dtype=np.float64).reshape(-1, 3), tri

    def compacted(self):
        v, t = self.arrays()
        return core.compact(Mesh(v, t))


def smooth(soup: Soup, original: spatial.Surface, strength: float = 1.0):
    v, t = soup.arrays()
    if not len(t):
        return
    p = v[t]
    cen = p.mean(axis=1)
    fn = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    area = 0.5 * np.linalg.norm(fn, axis=1)
    acc = np.zeros_like(v)
    wsum = np.zeros(len(v))
    nrm = np.zeros_like(v)
    for k in range(3):
        np.add.at(acc, t[:, k], cen * area[:, None])
        np.add.at(wsum, t[:, k], area)
        np.add.at(nrm, t[:, k], fn)
    ok = wsum > 0
    q = np.where(ok[:, None], acc / np.where(ok, wsum, 1.0)[:, None], v)
    ln = np.linalg.norm(nrm, axis=1)
    ln[ln == 0] = 1.0
    nrm = nrm / ln[:, None]
    move = q - v
    move -= nrm * np.einsum("ij,ij->i", move, nrm)[:, None]
    free = np.array([len(soup.FN[i]) == 0 and bool(soup.VT[i]) for i in range(len(v))])
    idx = np.nonzero(free & ok)[0]
    if not len(idx):
        return
    target = v[idx] + strength * move[idx]
    _d, snapped, _w = original.nearest(target)
    for k, i in enumerate(idx.tolist()):
        soup.P[i] = (float(snapped[k][0]), float(snapped[k][1]), float(snapped[k][2]))


def remesh(m: Mesh, length: float, iterations: int = 5, feature_deg: float = 30.0, lock_boundary: bool = True, act=QUIET) -> tuple:
    if not (length > 0 and math.isfinite(length)):
        raise MeshError("The target edge length must be positive.")
    iterations = max(1, min(int(iterations), MAX_ITERATIONS))
    if len(m.t) < 4:
        raise MeshError("The mesh has too few triangles to remesh.")
    diag = float(np.linalg.norm(m.v.max(axis=0) - m.v.min(axis=0)))
    if length > diag / 2:
        raise MeshError("The edge length is more than half the size of the mesh.")
    area = float(core.areas(m).sum())
    expect = area / (0.4330127 * length * length)
    if expect > 4 * max(len(m.t), 20000):
        raise MeshError("An edge length of %g would make about %d triangles; use a larger length or a coarser mesh." % (length, expect))
    act.step("Preparing the mesh", 0.02)
    soup = Soup(m, feature_deg, lock_boundary)
    original = spatial.Surface(m)
    hi, lo = SPLIT * length, COLLAPSE * length
    for it in range(iterations):
        base = 0.05 + 0.9 * it / iterations
        span = 0.9 / iterations
        act.step("Pass %d of %d: splitting long edges" % (it + 1, iterations), base)
        for a, b in [k for k in list(soup.ET) if soup.length(*k) > hi]:
            if key(a, b) in soup.ET and soup.length(a, b) > hi:
                if key(a, b) in soup.boundary and soup.lock_boundary:
                    continue
                soup.split(a, b)
        act.step("Pass %d of %d: collapsing short edges" % (it + 1, iterations), base + span * 0.25)
        for a, b in [k for k in list(soup.ET) if soup.length(*k) < lo]:
            if key(a, b) not in soup.ET or soup.length(a, b) >= lo:
                continue
            plan = soup.collapse_plan(a, b, hi)
            if plan is not None:
                soup.collapse(a, b, plan)
                continue
            plan = soup.collapse_plan(b, a, hi)
            if plan is not None:
                soup.collapse(b, a, plan)
        act.step("Pass %d of %d: flipping edges" % (it + 1, iterations), base + span * 0.5)
        for a, b in list(soup.ET):
            if key(a, b) in soup.ET:
                soup.try_flip(a, b)
        act.step("Pass %d of %d: smoothing" % (it + 1, iterations), base + span * 0.75)
        smooth(soup, original, 1.0)
    act.step("Measuring the deviation", 0.96)
    out = soup.compacted()
    dev = spatial.deviation(m, out, 150_000)
    e = np.concatenate([np.linalg.norm(out.v[out.t[:, i]] - out.v[out.t[:, (i + 1) % 3]], axis=1) for i in range(3)]) if len(out.t) else np.zeros(1)
    info = {"before": int(len(m.t)), "after": int(len(out.t)), "edge_mean": float(e.mean()), "edge_min": float(e.min()), "edge_max": float(e.max()), "deviation_max": dev["max"], "deviation_rms": dev["rms"], "iterations": iterations}
    return out, info
