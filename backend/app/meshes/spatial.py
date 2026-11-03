import numpy as np
from scipy.spatial import cKDTree

from app.meshes.core import Mesh

LATTICE_LIMIT = 2_500_000


def surface_samples(m: Mesh, limit: int = 1_500_000) -> np.ndarray:
    if not len(m.t):
        return m.v.copy()
    p = m.v[m.t]
    parts = [m.v, p.mean(axis=1), (p[:, 0] + p[:, 1]) / 2, (p[:, 1] + p[:, 2]) / 2, (p[:, 2] + p[:, 0]) / 2]
    out = np.vstack(parts)
    if len(out) > limit:
        out = out[np.random.default_rng(7).choice(len(out), limit, replace=False)]
    return out


def closest_on_triangles(pts, a, b, c):
    ab, ac, ap = b - a, c - a, pts - a
    d1, d2 = np.einsum("ij,ij->i", ab, ap), np.einsum("ij,ij->i", ac, ap)
    bp = pts - b
    d3, d4 = np.einsum("ij,ij->i", ab, bp), np.einsum("ij,ij->i", ac, bp)
    cp = pts - c
    d5, d6 = np.einsum("ij,ij->i", ab, cp), np.einsum("ij,ij->i", ac, cp)
    vc = d1 * d4 - d3 * d2
    vb = d5 * d2 - d1 * d6
    va = d3 * d6 - d5 * d4
    out = np.empty_like(pts)
    denom = va + vb + vc
    with np.errstate(divide="ignore", invalid="ignore"):
        v = np.where(denom != 0, vb / denom, 0.0)
        w = np.where(denom != 0, vc / denom, 0.0)
        out[:] = a + ab * v[:, None] + ac * w[:, None]

    def seg(mask, p0, p1, tt):
        out[mask] = p0[mask] + (p1[mask] - p0[mask]) * np.clip(tt[mask], 0.0, 1.0)[:, None]

    e_ab = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        tab = np.where(d1 - d3 != 0, d1 / (d1 - d3), 0.0)
        tac = np.where(d2 - d6 != 0, d2 / (d2 - d6), 0.0)
        tbc = np.where((d4 - d3) + (d5 - d6) != 0, (d4 - d3) / ((d4 - d3) + (d5 - d6)), 0.0)
    e_ac = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
    e_bc = (va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0)
    seg(e_ab, a, b, tab)
    seg(e_ac, a, c, tac)
    seg(e_bc, b, c, tbc)
    out[(d1 <= 0) & (d2 <= 0)] = a[(d1 <= 0) & (d2 <= 0)]
    cb = (d3 >= 0) & (d4 <= d3)
    out[cb] = b[cb]
    cc = (d6 >= 0) & (d5 <= d6)
    out[cc] = c[cc]
    return out


class Surface:
    def __init__(self, m: Mesh):
        self.m = m
        p = m.v[m.t]
        self.a, self.b, self.c = p[:, 0], p[:, 1], p[:, 2]
        longest = np.maximum.reduce([np.linalg.norm(p[:, 0] - p[:, 1], axis=1), np.linalg.norm(p[:, 1] - p[:, 2], axis=1), np.linalg.norm(p[:, 2] - p[:, 0], axis=1)])
        spacing = max(float(np.median(longest)) * 0.75, 1e-12)
        k = np.clip(np.ceil(longest / spacing), 1, 24).astype(np.int64)
        while int(((k + 1) * (k + 2) // 2).sum()) > LATTICE_LIMIT:
            spacing *= 1.5
            k = np.clip(np.ceil(longest / spacing), 1, 24).astype(np.int64)
        pts, ids = [], []
        for kv in np.unique(k):
            sel = np.nonzero(k == kv)[0]
            w = [(i / kv, j / kv, (kv - i - j) / kv) for i in range(kv + 1) for j in range(kv + 1 - i)]
            w = np.array(w)
            q = p[sel]
            pts.append(np.einsum("sk,tkd->tsd", w, np.stack([q[:, 0], q[:, 1], q[:, 2]], axis=1)).reshape(-1, 3))
            ids.append(np.repeat(sel, len(w)))
        self.samples = np.vstack(pts)
        self.owner = np.concatenate(ids)
        self.reach = float((longest / k).max()) * 0.6
        self.tree = cKDTree(self.samples)

    def nearest(self, pts, k: int = 12):
        pts = np.asarray(pts, dtype=np.float64).reshape(-1, 3)
        best = np.full(len(pts), np.inf)
        where = np.zeros((len(pts), 3))
        which = np.zeros(len(pts), dtype=np.int64)
        for s in range(0, len(pts), 20000):
            chunk = pts[s : s + 20000]
            d0, _i0 = self.tree.query(chunk, workers=-1)
            lists = self.tree.query_ball_point(chunk, d0 + self.reach, workers=-1)
            counts = np.fromiter((len(x) for x in lists), dtype=np.int64, count=len(lists))
            flat = np.fromiter((j for x in lists for j in x), dtype=np.int64, count=int(counts.sum()))
            who = np.repeat(np.arange(len(chunk)), counts)
            tri = self.owner[flat]
            q = closest_on_triangles(chunk[who], self.a[tri], self.b[tri], self.c[tri])
            dist = np.linalg.norm(q - chunk[who], axis=1)
            order = np.lexsort((dist, who))
            who_s, first = np.unique(who[order], return_index=True)
            pick = order[first]
            best[s + who_s] = dist[pick]
            where[s + who_s] = q[pick]
            which[s + who_s] = tri[pick]
        return best, where, which


def deviation(a: Mesh, b: Mesh, limit: int = 600_000, check=None) -> dict:
    if not len(a.t) or not len(b.t):
        return {"max": 0.0, "rms": 0.0}
    tick = check or (lambda: None)
    sb = Surface(b)
    tick()
    sa = Surface(a)
    tick()
    pa = surface_samples(a, limit)
    pb = surface_samples(b, limit)
    tick()
    d1 = sb.nearest(pa)[0]
    tick()
    d2 = sa.nearest(pb)[0]
    tick()
    both = np.concatenate([d1, d2])
    return {"max": float(both.max()), "rms": float(np.sqrt((both**2).mean()))}
