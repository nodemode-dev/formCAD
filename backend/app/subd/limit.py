import math
from functools import lru_cache

import numpy as np

from app.subd.cc import Level, SubdError, edge_table

BSPLINE_TO_BEZIER = np.array([[1, 4, 1, 0], [0, 4, 2, 0], [0, 2, 4, 0], [0, 1, 4, 1]], dtype=np.float64) / 6.0


def _smooth_matrix(n):
    size = 2 * n + 1
    A = np.zeros((size, size))

    def q(i):
        return 1 + (i % n)

    def r(i):
        return 1 + n + (i % n)

    def face_point(i):
        row = np.zeros(size)
        row[0] += 0.25
        row[q(i)] += 0.25
        row[r(i)] += 0.25
        row[q(i + 1)] += 0.25
        return row

    A[0, 0] = (n - 2.0) / n
    for i in range(n):
        A[0, q(i)] += 1.0 / (n * n)
        A[0] += face_point(i) / (n * n)
    for i in range(n):
        row = np.zeros(size)
        row[0] += 0.25
        row[q(i)] += 0.25
        row += 0.25 * (face_point(i - 1) + face_point(i))
        A[q(i)] = row
        A[r(i)] = face_point(i)
    return A


def canonical_ring(n):
    X = np.zeros((2 * n + 1, 3))
    qs = [np.array([math.cos(2 * math.pi * i / n), math.sin(2 * math.pi * i / n), 0.0]) for i in range(n)]
    for i in range(n):
        X[1 + i] = qs[i]
        X[1 + n + i] = qs[i] + qs[(i + 1) % n]
    return X


@lru_cache(maxsize=64)
def smooth_masks(n):
    if n < 3 or n > 60:
        raise SubdError("A vertex has valence %d; 3 to 60 is supported." % n)
    A = _smooth_matrix(n)
    vals, vecs = np.linalg.eig(A.T)
    order = np.argsort(-vals.real)
    lim = vecs[:, order[0]].real
    lim = lim / lim.sum()
    lam = vals[order[1]]
    rows = []
    for i in range(len(vals)):
        if abs(vals[i] - lam) < 1e-9:
            rows.append(vecs[:, i].real)
            rows.append(vecs[:, i].imag)
    u, s, vt = np.linalg.svd(np.array(rows), full_matrices=False)
    basis = vt[:2]
    qcos = np.array([math.cos(2 * math.pi * i / n) for i in range(n)])
    coef, *_ = np.linalg.lstsq(basis[:, 1:1 + n].T, qcos, rcond=None)
    mask = coef @ basis
    t = mask @ canonical_ring(n)
    if abs(t[0]) < 1e-12:
        raise SubdError("The tangent mask of valence %d is degenerate." % n)
    return lim, mask / t[0]


@lru_cache(maxsize=64)
def spoke_matrix(n):
    lim, mask = smooth_masks(n)
    rows = np.zeros((n, 2 * n + 1))
    for j in range(n):
        rows[j] = np.concatenate([[mask[0]], np.roll(mask[1:1 + n], j), np.roll(mask[1 + n:], j)])
    return lim, rows


def _sector_matrix(k):
    size = 1 + (k + 1) + k
    A = np.zeros((size, size))

    def q(i):
        return 1 + i

    def r(i):
        return 1 + (k + 1) + (i - 1)

    def face_point(i):
        row = np.zeros(size)
        row[0] += 0.25
        row[q(i - 1)] += 0.25
        row[r(i)] += 0.25
        row[q(i)] += 0.25
        return row

    A[0, q(0)] = 1.0 / 8.0
    A[0, 0] = 6.0 / 8.0
    A[0, q(k)] = 1.0 / 8.0
    for i in range(k + 1):
        row = np.zeros(size)
        if i == 0 or i == k:
            row[0] += 0.5
            row[q(i)] += 0.5
        else:
            row[0] += 0.25
            row[q(i)] += 0.25
            row += 0.25 * (face_point(i) + face_point(i + 1))
        A[q(i)] = row
    for i in range(1, k + 1):
        A[r(i)] = face_point(i)
    return A


def canonical_sector(k):
    X = np.zeros((2 * k + 2, 3))
    qs = [np.array([math.cos(math.pi * i / k), math.sin(math.pi * i / k), 0.0]) for i in range(k + 1)]
    for i in range(k + 1):
        X[1 + i] = qs[i]
    for i in range(1, k + 1):
        X[1 + (k + 1) + (i - 1)] = qs[i - 1] + qs[i]
    return X


@lru_cache(maxsize=64)
def sector_cross(k):
    if k < 2 or k > 60:
        raise SubdError("A crease sector of %d faces is not supported." % k)
    A = _sector_matrix(k)
    vals, vecs = np.linalg.eig(A.T)
    order = np.argsort(-vals.real)
    X = canonical_sector(k)
    along = np.zeros(len(A))
    along[1] = 0.5
    along[k + 1] = -0.5
    for i in order:
        if abs(vals[i] - 1.0) < 1e-9:
            continue
        cand = vecs[:, i].real
        t = cand @ X
        if abs(t[1]) > 1e-6 * np.linalg.norm(cand):
            cand = cand - t[0] * along
            return cand / (cand @ X)[1]
    raise SubdError("The crease cross mask of %d faces is degenerate." % k)


class Topo:
    def __init__(self, lv: Level):
        self.lv = lv
        quads = lv.quads()
        self.q = quads
        nv = len(lv.v)
        self.nv = nv
        ea, eb, inv, cnt, nxt, prv = edge_table(lv)
        self.ea, self.eb, self.cnt = ea, eb, cnt
        self.nonmanifold = bool(np.any(cnt > 2))
        rows = quads.tolist()
        self.rows = rows
        self.fwd = {}
        for f, row in enumerate(rows):
            for c in range(4):
                self.fwd[(row[c], row[(c + 1) % 4])] = f
        keys = set(zip(ea[cnt == 1].tolist(), eb[cnt == 1].tolist()))
        for a, b, s in zip(lv.sharp_a.tolist(), lv.sharp_b.tolist(), lv.sharp_s.tolist()):
            if s > 0:
                keys.add((min(a, b), max(a, b)))
        self.sharp = keys
        self.val = np.zeros(nv, dtype=np.int64)
        np.add.at(self.val, ea, 1)
        np.add.at(self.val, eb, 1)
        self.nsharp = np.zeros(nv, dtype=np.int64)
        self.sharp_nb = {}
        for a, b in keys:
            self.nsharp[a] += 1
            self.nsharp[b] += 1
            self.sharp_nb.setdefault(a, []).append(b)
            self.sharp_nb.setdefault(b, []).append(a)
        self.touch = np.zeros(nv, dtype=bool)
        for row in rows:
            for c in range(4):
                a, b = row[c], row[(c + 1) % 4]
                if (a, b) in keys or (b, a) in keys:
                    self.touch[row] = True
                    break

    def is_sharp(self, a, b):
        return (a, b) in self.sharp or (b, a) in self.sharp

    def around(self, v, f):
        row = self.rows[f]
        c = row.index(v)
        return row[(c - 1) % 4], row[(c + 1) % 4], row[(c + 2) % 4]


def vertex_data(topo: Topo):
    V = topo.lv.v
    nv = topo.nv
    L = V.copy()
    tan = {}
    kinds = np.zeros(nv, dtype=np.int8)
    inc = [[] for _ in range(nv)]
    for f, row in enumerate(topo.rows):
        for v in row:
            inc[v].append(f)
    for v in range(nv):
        faces = inc[v]
        if not faces:
            continue
        ns = int(topo.nsharp[v])
        if ns <= 1:
            ring_smooth(topo, v, faces, L, tan)
        elif ns == 2:
            ring_crease(topo, v, faces, L, tan)
            kinds[v] = 1
        else:
            ring_corner(topo, v, faces, L, tan)
            kinds[v] = 2
    return L, tan, kinds


def ring_smooth(topo, v, faces, L, tan):
    n = len(faces)
    f0 = faces[0]
    ring_q, ring_r = [], []
    f = f0
    for step in range(n):
        prev, nxt, opp = topo.around(v, f)
        ring_q.append(nxt)
        ring_r.append(opp)
        g = topo.fwd.get((v, prev))
        if g is None:
            raise SubdError("A vertex is on an open boundary.")
        f = g
    if f != f0:
        raise SubdError("A vertex has a pinched neighbourhood.")
    pts = topo.lv.v[[v] + ring_q + ring_r]
    lim, rows = spoke_matrix(n)
    L[v] = lim @ pts
    t = rows @ pts
    for j in range(n):
        tan[(v, ring_q[j])] = t[j]


def sector_walk(topo, v, start):
    f = start
    prev, nxt, opp = topo.around(v, f)
    qs = [nxt]
    rs = []
    for _ in range(64):
        prev, nxt, opp = topo.around(v, f)
        rs.append(opp)
        qs.append(prev)
        if topo.is_sharp(v, prev):
            return qs, rs
        g = topo.fwd.get((v, prev))
        if g is None:
            return qs, rs
        f = g
    raise SubdError("A crease sector is too long.")


def ring_crease(topo, v, faces, L, tan):
    Vv = topo.lv.v
    a_, b_ = topo.sharp_nb[v]
    L[v] = (Vv[a_] + 4.0 * Vv[v] + Vv[b_]) / 6.0
    starts = [f for f in faces if topo.is_sharp(v, topo.around(v, f)[1])]
    if not starts:
        raise SubdError("A crease vertex has no sector start.")
    for s in starts:
        qs, rs = sector_walk(topo, v, s)
        k = len(rs)
        pts = Vv[[v] + qs + rs]
        tx = 0.5 * (pts[1] - pts[k + 1])
        tan[(v, qs[0])] = tx
        tan[(v, qs[k])] = -tx
        if k >= 2:
            ty = sector_cross(k) @ pts
            for j in range(1, k):
                th = math.pi * j / k
                tan[(v, qs[j])] = math.cos(th) * tx + math.sin(th) * ty


def ring_corner(topo, v, faces, L, tan):
    Vv = topo.lv.v
    L[v] = Vv[v]
    for f in faces:
        prev, nxt, opp = topo.around(v, f)
        tan[(v, nxt)] = Vv[nxt] - Vv[v]
        tan[(v, prev)] = Vv[prev] - Vv[v]


def regular_grid(topo, f):
    fwd = topo.fwd
    v0, v1, v2, v3 = topo.rows[f]

    def cyc(face, start):
        row = topo.rows[face]
        c = row.index(start)
        return row[c:] + row[:c]

    G = np.zeros((4, 4), dtype=np.int64)
    G[1, 1], G[2, 1], G[2, 2], G[1, 2] = v0, v1, v2, v3
    B = cyc(fwd[(v1, v0)], v1)
    G[1, 0], G[2, 0] = B[2], B[3]
    R = cyc(fwd[(v2, v1)], v2)
    G[3, 1], G[3, 2] = R[2], R[3]
    T = cyc(fwd[(v3, v2)], v3)
    G[2, 3], G[1, 3] = T[2], T[3]
    Lf = cyc(fwd[(v0, v3)], v0)
    G[0, 2], G[0, 1] = Lf[2], Lf[3]
    G[0, 0] = cyc(fwd[(v0, int(G[0, 1]))], v0)[2]
    G[3, 0] = cyc(fwd[(v1, int(G[2, 0]))], v1)[2]
    G[3, 3] = cyc(fwd[(v2, int(G[3, 2]))], v2)[2]
    G[0, 3] = cyc(fwd[(v3, int(G[1, 3]))], v3)[2]
    return G


def build_patches(lv: Level, force_hermite=False):
    topo = Topo(lv)
    if topo.nonmanifold:
        raise SubdError("An edge is shared by more than two faces.")
    L, tan, kinds = vertex_data(topo)
    Vv = lv.v
    nf = len(topo.rows)
    ctrl = np.zeros((nf, 4, 4, 3))
    regular = np.zeros(nf, dtype=bool)
    good = ((topo.val == 4) & (kinds == 0) & ~topo.touch).tolist()
    for f in range(nf):
        v0, v1, v2, v3 = topo.rows[f]
        if not force_hermite and good[v0] and good[v1] and good[v2] and good[v3]:
            G = regular_grid(topo, f)
            ctrl[f] = np.einsum("ia,abk,jb->ijk", BSPLINE_TO_BEZIER, Vv[G], BSPLINE_TO_BEZIER)
            regular[f] = True
            continue
        P = ctrl[f]
        P[0, 0], P[3, 0], P[3, 3], P[0, 3] = L[v0], L[v1], L[v2], L[v3]
        P[1, 0] = L[v0] + tan[(v0, v1)] / 3.0
        P[2, 0] = L[v1] + tan[(v1, v0)] / 3.0
        P[3, 1] = L[v1] + tan[(v1, v2)] / 3.0
        P[3, 2] = L[v2] + tan[(v2, v1)] / 3.0
        P[1, 3] = L[v3] + tan[(v3, v2)] / 3.0
        P[2, 3] = L[v2] + tan[(v2, v3)] / 3.0
        P[0, 1] = L[v0] + tan[(v0, v3)] / 3.0
        P[0, 2] = L[v3] + tan[(v3, v0)] / 3.0
        P[1, 1] = P[1, 0] + P[0, 1] - P[0, 0]
        P[2, 1] = P[2, 0] + P[3, 1] - P[3, 0]
        P[1, 2] = P[1, 3] + P[0, 2] - P[0, 3]
        P[2, 2] = P[2, 3] + P[3, 2] - P[3, 3]
    return ctrl, regular, topo, kinds


def bezier_points(P, u, v):
    bu = np.stack([(1 - u) ** 3, 3 * u * (1 - u) ** 2, 3 * u ** 2 * (1 - u), u ** 3], axis=-1)
    bv = np.stack([(1 - v) ** 3, 3 * v * (1 - v) ** 2, 3 * v ** 2 * (1 - v), v ** 3], axis=-1)
    return np.einsum("...i,...ijk,...j->...k", bu, P, bv)
